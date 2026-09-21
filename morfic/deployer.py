from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from .config import settings
from .containerize import ensure_container_recipe
from .runtimes import container_runtime, container_setup_message, ensure_managed_dotnet, dotnet_executable
from .db import add_log, get_app, update_app
from .gitops import clone_repo
from .models import AppManifest, DeploymentPlan
from .planner import make_plan
from .repair import apply_patch, propose_repair
from .hosted import emit_event

PROCESSES: dict[int, subprocess.Popen] = {}



async def deploy_github(app_id: int, repo_url: str, intent: str, plan_override: DeploymentPlan | None = None, ref: str | None = None) -> dict[str, Any]:
    app = get_app(app_id)
    if not app:
        raise RuntimeError("App not found")
    workspace = Path(app.workspace)
    repo = workspace / "repo"
    workspace.mkdir(parents=True, exist_ok=True)
    update_app(app_id, status="cloning", last_error=None)
    asyncio.create_task(emit_event("repo_deploy_started", app_ref=str(app_id), source_type="github", stage="clone"))
    try:
        if plan_override and plan_override.container_image:
            # Prebuilt curated images do not need their source repository cloned merely
            # to start the service. This keeps heavyweight apps such as Jellyfin out
            # of the LLM/repo-analysis path entirely.
            repo.mkdir(parents=True, exist_ok=True)
            add_log(app_id, "catalog", f"Using curated prebuilt image: {plan_override.container_image}")
        else:
            log = await asyncio.to_thread(clone_repo, repo_url, repo, ref)
            add_log(app_id, "git", log)
        update_app(app_id, status="planning")
        plan = plan_override or await make_plan(repo, intent)
        manifest = AppManifest(name=plan.name or app.name, description=plan.summary or app.description, requested_intent=intent,
            capabilities=app.capabilities, source_type="github", source_url=repo_url, deployment_plan=plan)
        update_app(app_id, name=manifest.name, description=manifest.description, manifest_json=manifest)
        result = await run_repo(app_id, repo, plan, manifest)
        asyncio.create_task(emit_event("repo_deploy_succeeded", app_ref=str(app_id), source_type="github", success=True, repair_attempt=result.get("repair_attempts",0)))
        return result
    except Exception as e:
        add_log(app_id, "error", str(e))
        update_app(app_id, status="failed", last_error=str(e))
        asyncio.create_task(emit_event("repo_deploy_failed", app_ref=str(app_id), source_type="github", success=False, error_class=type(e).__name__, error_message=str(e)))
        raise


async def run_repo(app_id: int, repo: Path, plan: DeploymentPlan, manifest: AppManifest | None = None) -> dict[str, Any]:
    last_error = ""
    for attempt in range(settings.max_repair_attempts + 1):
        update_app(app_id, status="installing" if attempt == 0 else "repairing", repair_attempts=attempt)
        try:
            await _prepare_environment(app_id, repo, plan)
            result = await _start(app_id, repo, plan)
            if manifest:
                manifest.deployment_plan = plan
            update_app(app_id, status="running", local_url=result.get("local_url"), pid=result.get("pid"), last_error=None,
                       repair_attempts=attempt, manifest_json=manifest if manifest else get_app(app_id).manifest)
            return {"ok": True, **result, "plan": plan.model_dump(), "repair_attempts": attempt}
        except Exception as e:
            last_error = str(e)
            add_log(app_id, "error", last_error)
            asyncio.create_task(emit_event("execution_failure", app_ref=str(app_id), source_type="github", stage="run", success=False, error_class=type(e).__name__, error_message=last_error, repair_attempt=attempt))
            if attempt >= settings.max_repair_attempts:
                break
            action = await propose_repair(repo, plan, last_error)
            if not action:
                break
            add_log(app_id, "repair", action.summary)
            asyncio.create_task(emit_event("repair_attempt", app_ref=str(app_id), source_type="github", stage="repair", repair_attempt=attempt+1, metadata={"summary": action.summary[:300]}))
            plan = apply_patch(repo, plan, action) or plan
            if manifest:
                manifest.deployment_plan = plan
                update_app(app_id, manifest_json=manifest, repair_attempts=attempt + 1)
    update_app(app_id, status="failed", last_error=last_error, repair_attempts=settings.max_repair_attempts)
    raise RuntimeError(last_error or "Deployment failed")


async def _prepare_environment(app_id: int, repo: Path, plan: DeploymentPlan) -> None:
    runtime = container_runtime()
    if plan.container_image:
        if not runtime:
            raise RuntimeError(container_setup_message())
        await _run_checked(app_id, [runtime, "pull", plan.container_image], repo, 1800)
        return
    if plan.compose_file:
        if not runtime:
            raise RuntimeError(container_setup_message())
        compose = repo / plan.compose_file
        if not compose.exists():
            raise RuntimeError(f"Compose file not found: {plan.compose_file}")
        await _run_checked(app_id, [runtime, "compose", "-f", plan.compose_file, "config"], repo, 180)
        # Pull declared images when possible. Compose will build local services during up if needed.
        await _run_checked(app_id, [runtime, "compose", "-f", plan.compose_file, "pull", "--ignore-buildable"], repo, 1800, allow_failure=True)
        return
    if runtime and plan.project_type in {"docker", "python", "node", "dotnet", "static"}:
        dockerfile = ensure_container_recipe(repo, plan)
        tag = f"personal-software-{app_id}"
        rel = dockerfile.relative_to(repo).as_posix()
        await _run_checked(app_id, [runtime, "build", "-f", rel, "-t", tag, "."], repo, 1800)
        return
    trusted_demo = _is_trusted_demo_clone(repo)
    # Anything past this point runs third-party code directly on the host, so it needs the
    # explicit opt-in (or a bundled demo repo). .NET is no exception to that rule.
    if not settings.allow_host_execution and not trusted_demo:
        raise RuntimeError(container_setup_message())
    if plan.project_type == "dotnet":
        dotnet = dotnet_executable() or await asyncio.to_thread(ensure_managed_dotnet)
        add_log(app_id, "runtime", f"Using managed .NET SDK: {dotnet}")
        for cmd in plan.install_commands:
            await _run_checked(app_id, _dotnetize(cmd, dotnet), repo, 1200)
        return
    add_log(app_id, "runtime", "Running bundled trusted demo repo on the host." if trusted_demo else "UNSAFE HOST EXECUTION enabled for development.")
    if plan.project_type == "python":
        venv = repo.parent / ".venv"
        if not venv.exists():
            await _run_checked(app_id, [sys.executable, "-m", "venv", str(venv)], repo, 180)
        for cmd in plan.install_commands:
            await _run_checked(app_id, _pythonize(cmd, venv), repo, 1200)
        return
    for cmd in plan.install_commands:
        await _run_checked(app_id, cmd, repo, 1200)


async def _start(app_id: int, repo: Path, plan: DeploymentPlan) -> dict[str, Any]:
    stop_app(app_id)
    runtime = container_runtime()
    use_compose = bool(runtime and plan.compose_file)
    use_prebuilt = bool(runtime and plan.container_image)
    use_container = bool(runtime and not plan.compose_file and not plan.container_image and plan.project_type in {"docker", "python", "node", "dotnet", "static"})
    if use_prebuilt:
        tag = f"personal-software-{app_id}"
        host_port = _free_port(plan.port) if plan.port else None
        cmd = [runtime, "run", "--rm", "--name", tag, "--pids-limit", "512", "--memory", "4g", "--cpus", "4", "--security-opt", "no-new-privileges"]
        if plan.port and host_port:
            cmd += ["-p", f"127.0.0.1:{host_port}:{plan.port}"]
        app_root = repo.parent
        for local_name, container_path in plan.persistent_mounts.items():
            local = app_root / local_name
            local.mkdir(parents=True, exist_ok=True)
            cmd += ["-v", f"{local}:{container_path}"]
        if plan.media_mounts:
            candidates = [(Path.home()/"Movies", "/media/Movies"), (Path.home()/"Videos", "/media/Videos"), (Path.home()/"Music", "/media/Music")]
            for local, target in candidates:
                if local.exists():
                    cmd += ["-v", f"{local}:{target}:ro"]
        for k,v in plan.env.items():
            cmd += ["-e", f"{k}={v}"]
        cmd.append(plan.container_image)
        env=os.environ.copy(); env.update(plan.env)
        p=subprocess.Popen(cmd,cwd=repo,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=env,**_popen_group_kwargs())
        PROCESSES[app_id]=p
        await asyncio.sleep(1.2)
        if p.poll() is not None:
            output=p.stdout.read() if p.stdout else ""
            raise RuntimeError(output or f"Container exited with {p.returncode}")
        if plan.port and host_port:
            url=f"http://127.0.0.1:{host_port}{plan.healthcheck_path}"
            if not await _wait_http(url,60):
                stop_app(app_id)
                raise RuntimeError(f"Container started but did not become reachable at {url}")
            return {"pid":p.pid,"local_url":f"http://127.0.0.1:{host_port}"}
        return {"pid":p.pid,"local_url":None}
    if use_compose:
        host_port = plan.port
        await _run_checked(app_id, [runtime, "compose", "-f", plan.compose_file, "up", "-d", "--remove-orphans"], repo, 1800)
        if plan.port:
            url = f"http://127.0.0.1:{plan.port}{plan.healthcheck_path}"
            if not await _wait_http(url, 45):
                raise RuntimeError(f"Container stack started but did not become reachable at {url}")
            return {"pid": None, "local_url": f"http://127.0.0.1:{plan.port}"}
        return {"pid": None, "local_url": None}
    if use_container:
        tag = f"personal-software-{app_id}"
        if plan.frontend.kind == "generated_cli" and not plan.port:
            return {"pid": None, "local_url": f"/content/{app_id}/cli"}
        host_port = _free_port(plan.port) if plan.port else None
        cmd = [runtime, "run", "--rm", "--name", tag, "--pids-limit", "256", "--memory", "2g", "--cpus", "2", "--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
        if plan.port and host_port:
            cmd += ["-p", f"127.0.0.1:{host_port}:{plan.port}"]
        for k, v in plan.env.items():
            cmd += ["-e", f"{k}={v}"]
        cmd.append(tag)
    else:
        if not plan.run_command:
            if plan.frontend.kind == "generated_cli":
                return {"pid": None, "local_url": f"/content/{app_id}/cli"}
            raise RuntimeError("No run command could be inferred for this app.")
        cmd = plan.run_command
        host_port = plan.port
        if plan.project_type == "python":
            cmd = _pythonize(cmd, repo.parent / ".venv")
        elif plan.project_type == "dotnet":
            cmd = _dotnetize(cmd, dotnet_executable() or ensure_managed_dotnet())
    env = os.environ.copy(); env.update(plan.env)
    p = subprocess.Popen(cmd, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, **_popen_group_kwargs())
    PROCESSES[app_id] = p
    await asyncio.sleep(1.2)
    if p.poll() is not None:
        output = p.stdout.read() if p.stdout else ""
        add_log(app_id, "process", output)
        if p.returncode != 0:
            raise RuntimeError(output or f"Process exited with {p.returncode}")
        return {"pid": None, "local_url": f"/content/{app_id}/cli" if plan.frontend.kind == "generated_cli" else None}
    if plan.port:
        effective_port = host_port or plan.port
        url = f"http://127.0.0.1:{effective_port}{plan.healthcheck_path}"
        if not await _wait_http(url, 15):
            stop_app(app_id)
            raise RuntimeError(f"App started but did not become reachable at {url}")
        return {"pid": p.pid, "local_url": f"http://127.0.0.1:{effective_port}"}
    return {"pid": p.pid, "local_url": f"/content/{app_id}/cli" if plan.frontend.kind == "generated_cli" else None}


async def invoke_cli(app_id: int, values: dict[str, str] | None = None, raw_args: str = "") -> dict[str, Any]:
    app = get_app(app_id)
    if not app or not app.manifest or not app.manifest.deployment_plan:
        raise RuntimeError("App is not ready")
    plan = app.manifest.deployment_plan
    repo = Path(app.workspace) / "repo"
    cmd = list(plan.run_command) or _infer_cli_command(repo)
    if not cmd:
        raise RuntimeError("No CLI entrypoint could be inferred")
    extra: list[str] = []
    if values:
        # v0.5 convention: typed UI values are appended in field order. Model planners should choose fields that match positional CLIs.
        for field in plan.frontend.fields:
            value = str(values.get(field.name, "")).strip()
            if value:
                extra.append(value)
    if raw_args.strip():
        import shlex
        extra += shlex.split(raw_args, posix=(os.name != "nt"))
    runtime = container_runtime()
    if runtime and plan.project_type in {"docker", "python", "node", "dotnet", "static"}:
        full = [runtime, "run", "--rm", "--pids-limit", "128", "--memory", "1g", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", f"personal-software-{app_id}", *cmd, *extra]
    else:
        if not settings.allow_host_execution and not _is_trusted_demo_clone(repo):
            raise RuntimeError("A container runtime is required to invoke this app safely.")
        full = cmd + extra
        if plan.project_type == "python":
            full = _pythonize(full, repo.parent / ".venv")
    p = await asyncio.to_thread(subprocess.run, full, cwd=repo, capture_output=True, text=True, timeout=120)
    output = (p.stdout or "") + (p.stderr or "")
    add_log(app_id, "invoke", output)
    return {"returncode": p.returncode, "output": output[-20000:]}


def stop_app(app_id: int) -> None:
    runtime = container_runtime()
    app = get_app(app_id)
    if runtime and app and app.manifest and app.manifest.deployment_plan and app.manifest.deployment_plan.compose_file:
        try:
            repo = Path(app.workspace) / "repo"
            subprocess.run([runtime, "compose", "-f", app.manifest.deployment_plan.compose_file, "down"], cwd=repo, capture_output=True, text=True, timeout=60)
        except Exception:
            pass
    elif runtime:
        try:
            subprocess.run([runtime, "stop", f"personal-software-{app_id}"], capture_output=True, text=True, timeout=15)
        except Exception:
            pass
    p = PROCESSES.pop(app_id, None)
    if p and p.poll() is None:
        try:
            if os.name == "nt": p.terminate()
            else: os.killpg(os.getpgid(p.pid), 15)
        except Exception:
            try: p.kill()
            except Exception: pass



def _is_trusted_demo_clone(repo: Path) -> bool:
    cfg = repo / ".git" / "config"
    if not cfg.exists():
        return False
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
        demo_root = str((settings.home / "demo-repos").resolve()).replace("\\", "/")
        return demo_root in text.replace("\\", "/")
    except Exception:
        return False

def _infer_cli_command(repo: Path) -> list[str]:
    for f in ["main.py", "app.py", "cli.py"]:
        if (repo / f).exists(): return ["python", f]
    return []


def _dotnetize(cmd: list[str], dotnet: str) -> list[str]:
    if not cmd:
        return cmd
    if cmd[0] == "dotnet":
        return [dotnet, *cmd[1:]]
    return cmd


def _pythonize(cmd: list[str], venv: Path) -> list[str]:
    if not cmd: return cmd
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if cmd[0] in {"python", "python3"}: return [str(py), *cmd[1:]]
    return cmd


async def _run_checked(app_id: int, cmd: list[str], cwd: Path, timeout: int, allow_failure: bool = False) -> None:
    add_log(app_id, "command", "> " + " ".join(cmd))
    p = await asyncio.to_thread(subprocess.run, cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    output = (p.stdout or "") + (p.stderr or "")
    add_log(app_id, "command", output)
    if p.returncode != 0 and not allow_failure:
        raise RuntimeError(output or f"Command failed: {cmd}")


async def _wait_http(url: str, seconds: float) -> bool:
    deadline = time.time() + seconds
    async with httpx.AsyncClient(timeout=1.2) as client:
        while time.time() < deadline:
            try:
                r = await client.get(url)
                if r.status_code < 500: return True
            except Exception: pass
            await asyncio.sleep(.4)
    return False


def _free_port(preferred: int | None) -> int:
    if preferred:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", preferred)); return preferred
        except OSError: pass
        finally: s.close()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return int(s.getsockname()[1])


def _popen_group_kwargs():
    if os.name == "nt": return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}
