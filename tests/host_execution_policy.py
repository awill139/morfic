"""Third-party code never runs on the host without the explicit opt-in — .NET included."""
import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain
import asyncio
import dataclasses
import os
import tempfile
from pathlib import Path

os.environ["MORFIC_HOME"] = tempfile.mkdtemp(prefix="morfic-test-hostexec-")
os.environ.pop("MORFIC_ALLOW_HOST_EXECUTION", None)
os.environ.pop("PERSONAL_SOFTWARE_ALLOW_HOST_EXECUTION", None)

from morfic import deployer
from morfic.db import init_db

init_db()
from morfic.models import DeploymentPlan

repo = Path(tempfile.mkdtemp(prefix="morfic-test-repo-"))
calls = []


async def fake_run_checked(app_id, cmd, cwd, timeout, **kw):
    calls.append(cmd)


def fake_managed_dotnet(*a, **kw):
    calls.append("ensure_managed_dotnet")
    return "/fake/dotnet"


deployer.container_runtime = lambda: None
deployer._run_checked = fake_run_checked
deployer.ensure_managed_dotnet = fake_managed_dotnet
deployer.dotnet_executable = lambda: None

for kind, install in (("dotnet", [["dotnet", "restore", "A.csproj"]]), ("python", [["pip", "install", "-r", "requirements.txt"]]), ("node", [["npm", "install"]])):
    plan = DeploymentPlan(name="x", summary="x", project_type=kind, install_commands=install, run_command=["run"])
    try:
        asyncio.run(deployer._prepare_environment(1, repo, plan))
    except RuntimeError as e:
        assert "container" in str(e).lower(), e
    else:
        raise AssertionError(f"{kind} project was prepared on the host without opt-in")
assert calls == [], f"host tooling was invoked without opt-in: {calls}"

# With the explicit opt-in the .NET path is available again.
deployer.settings = dataclasses.replace(deployer.settings, allow_host_execution=True)
plan = DeploymentPlan(name="x", summary="x", project_type="dotnet", install_commands=[["dotnet", "restore", "A.csproj"]], run_command=["dotnet", "run"])
asyncio.run(deployer._prepare_environment(1, repo, plan))
assert "ensure_managed_dotnet" in calls or any("restore" in " ".join(c) for c in calls if isinstance(c, list))

print("HOST EXECUTION POLICY PASS: python/node/dotnet require opt-in without a container runtime")
