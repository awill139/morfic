"""Environment-variable aliases and the single-source version."""
import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain
import os
import re
import tempfile
from pathlib import Path

os.environ["MORFIC_HOME"] = tempfile.mkdtemp(prefix="morfic-test-config-")
for k in [k for k in os.environ if k.startswith("PERSONAL_SOFTWARE_")]:
    del os.environ[k]

from morfic import __version__
from morfic.envvars import getenv

# MORFIC_* wins; the legacy PERSONAL_SOFTWARE_* spelling still works; otherwise the default applies.
assert getenv("PROBE", "dflt") == "dflt"
os.environ["PERSONAL_SOFTWARE_PROBE"] = "legacy"
assert getenv("PROBE", "dflt") == "legacy"
os.environ["MORFIC_PROBE"] = "new"
assert getenv("PROBE", "dflt") == "new"
os.environ["MORFIC_PROBE"] = ""
assert getenv("PROBE", "dflt") == ""  # an explicitly empty value is honoured, not skipped

from morfic.config import load_settings
os.environ["MORFIC_LLM_TIMEOUT"] = "42"
assert load_settings().llm_call_timeout_seconds == 42
del os.environ["MORFIC_LLM_TIMEOUT"]
os.environ["PERSONAL_SOFTWARE_LLM_TIMEOUT"] = "43"
assert load_settings().llm_call_timeout_seconds == 43
os.environ["MORFIC_ALLOW_HOST_EXECUTION"] = "1"
assert load_settings().allow_host_execution is True

# The version has one source (morfic/__init__.py); nothing else may hard-code a number.
root = Path(__file__).resolve().parent.parent
assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
pyproject = (root / "pyproject.toml").read_text()
assert 'dynamic = ["version"]' in pyproject and 'attr = "morfic.__version__"' in pyproject
assert not re.search(r'^version\s*=\s*"', pyproject, re.M)
for path in (root / "morfic").glob("*.py"):
    assert f'"{__version__}"' not in path.read_text() or path.name == "__init__.py", f"{path.name} hard-codes the version"

from morfic.hosted import environment
assert environment()["client_version"] == __version__

# MORFIC_SECRET_STORE=file keeps secrets out of the OS keychain (the whole suite relies on this).
import json
from morfic import provider_config

assert os.environ["MORFIC_SECRET_STORE"] == "file" and provider_config._keyring() is None
provider_config.set_secret("official_token", "probe-token-not-real")
assert provider_config.get_secret("official_token") == "probe-token-not-real"
stored = json.loads(provider_config.FALLBACK_SECRET_PATH.read_text())
assert stored["official_token"] == "probe-token-not-real"
assert oct(provider_config.FALLBACK_SECRET_PATH.stat().st_mode & 0o777) == "0o600"

print("CONFIG AND VERSION PASS: env aliases, single-source version, file secret store")
