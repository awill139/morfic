import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from morfic import deployer
from morfic.models import DeploymentPlan, FrontendSpec


def _plan(**kw):
    base = dict(name="x", summary="y", project_type="python",
                run_command=["python", "x.py"], frontend=FrontendSpec(kind="none"))
    base.update(kw)
    return DeploymentPlan(**base)


def test_plan_with_fallback_prefers_heuristic_without_llm():
    async def _fail(*a, **k):
        raise AssertionError("LLM should not be consulted when the heuristic plan works")
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "docker-compose.yml").write_text(
            'services:\n  web:\n    image: example/web\n    ports:\n      - "8123:8080"\n')
        with patch("morfic.deployer.make_plan", new=_fail):
            plan = asyncio.run(deployer.plan_with_fallback(root, "install test app"))
    assert plan.project_type == "docker"
    assert plan.compose_file == "docker-compose.yml"
    assert plan.port == 8123


def test_plan_with_fallback_uses_llm_when_unknown():
    fallback = _plan(project_type="python")
    async def _fake(repo, intent):
        assert intent == "install test app"
        return fallback
    with TemporaryDirectory() as td:
        root = Path(td)
        (root / "notes.txt").write_text("nothing to infer here")
        with patch("morfic.deployer.make_plan", new=_fake):
            plan = asyncio.run(deployer.plan_with_fallback(root, "install test app"))
    assert plan is fallback


def test_compose_commands_are_namespaced_per_app():
    plan = _plan(project_type="docker", compose_file="docker-compose.yml", compose_project="morfic-12")
    with patch("morfic.deployer.container_runtime", return_value="docker"):
        base = deployer._compose_base(12, plan)
    assert base == ["docker", "compose", "-p", "morfic-12", "-f", "docker-compose.yml"]


def test_compose_project_defaults_to_app_id():
    plan = _plan(project_type="docker", compose_file="docker-compose.yml")
    with patch("morfic.deployer.container_runtime", return_value="docker"):
        base = deployer._compose_base(9, plan)
    assert base[3] == "morfic-9"
    assert deployer._compose_project(3) == "morfic-3"
    assert deployer._compose_project(3) != deployer._compose_project(4)


def test_repair_failure_preserves_original_error():
    plan = _plan()
    async def _noop(*a, **k):
        return None
    async def _boom(*a, **k):
        raise RuntimeError("container did not become reachable")
    async def _repair_boom(*a, **k):
        raise RuntimeError("Configure OpenAI or Anthropic in Settings before asking for software.")
    with patch("morfic.deployer._prepare_environment", new=_boom), \
         patch("morfic.deployer.propose_repair", new=_repair_boom), \
         patch("morfic.deployer.update_app"), \
         patch("morfic.deployer.add_log"), \
         patch("morfic.deployer.emit_event", new=_noop):
        # settings.max_repair_attempts defaults to 3, so the repair path is exercised.
        try:
            asyncio.run(deployer.run_repo(42, Path("/tmp"), plan))
        except RuntimeError as e:
            assert "container did not become reachable" in str(e), str(e)
            assert "Configure OpenAI" not in str(e), str(e)
        else:
            raise AssertionError("run_repo should have raised the original error")


if __name__ == "__main__":
    test_plan_with_fallback_prefers_heuristic_without_llm()
    test_plan_with_fallback_uses_llm_when_unknown()
    test_compose_commands_are_namespaced_per_app()
    test_compose_project_defaults_to_app_id()
    test_repair_failure_preserves_original_error()
    print("WOW FIXES PASS: heuristic-first planning, compose isolation, repair error fidelity")
