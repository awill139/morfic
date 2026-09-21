from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import settings
from .distribution import distribution
from .envvars import getenv

SERVICE = "personal-software-runtime"


@dataclass
class ProviderSettings:
    provider: str = "official" if distribution.mode == "official" else ""
    official_base_url: str = distribution.official_base_url
    # Official modes only. Master switch for everything the runtime sends to the Morfic backend beyond the
    # AI calls themselves: usage events and per-call logs (task, model, sizes, latency, token counts).
    share_usage_data: bool = True
    # When sharing is on, also include redacted, size-bounded excerpts of the prompts sent to and the
    # responses received from the AI. Has no effect while share_usage_data is off.
    diagnostic_consent: bool = True
    official_ai_mode: str = "managed"
    official_byok_provider: str = "anthropic"
    openai_model: str = "gpt-5"
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_base_url: str = "https://api.anthropic.com/v1"


CONFIG_PATH = settings.home / "provider.json"
FALLBACK_SECRET_PATH = settings.home / "provider-secrets.json"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def load_provider_settings() -> ProviderSettings:
    data = _load_json(CONFIG_PATH)
    cfg = ProviderSettings()
    for k in asdict(cfg):
        if k in data:
            if isinstance(getattr(cfg, k), bool):
                setattr(cfg, k, bool(data[k]))
            elif isinstance(data[k], str):
                setattr(cfg, k, data[k])
    # Environment variables remain useful for headless/server usage.
    cfg.provider = getenv("PROVIDER", cfg.provider).strip().lower()
    cfg.official_base_url = getenv("OFFICIAL_URL", cfg.official_base_url).rstrip("/")
    cfg.official_ai_mode = getenv("OFFICIAL_AI_MODE", cfg.official_ai_mode).strip().lower()
    cfg.official_byok_provider = getenv("OFFICIAL_BYOK_PROVIDER", cfg.official_byok_provider).strip().lower()
    cfg.openai_model = getenv("OPENAI_MODEL", cfg.openai_model).strip()
    cfg.openai_base_url = getenv("OPENAI_BASE_URL", cfg.openai_base_url).rstrip("/")
    cfg.anthropic_model = getenv("ANTHROPIC_MODEL", cfg.anthropic_model).strip()
    cfg.anthropic_base_url = getenv("ANTHROPIC_BASE_URL", cfg.anthropic_base_url).rstrip("/")
    return cfg


def save_provider_settings(cfg: ProviderSettings) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except Exception:
        pass


def _keyring():
    # MORFIC_SECRET_STORE=file keeps secrets in a 0600 file inside the data directory instead of the
    # OS keychain. The test suite uses it so that tests never touch a developer's real keychain.
    if (getenv("SECRET_STORE", "") or "").strip().lower() == "file":
        return None
    try:
        import keyring  # type: ignore
        return keyring
    except Exception:
        return None


def set_secret(name: str, value: str) -> None:
    value = value.strip()
    if not value:
        return
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, name, value)
            return
        except Exception:
            pass
    data = _load_json(FALLBACK_SECRET_PATH)
    data[name] = value
    FALLBACK_SECRET_PATH.write_text(json.dumps(data), encoding="utf-8")
    try:
        os.chmod(FALLBACK_SECRET_PATH, 0o600)
    except Exception:
        pass


def get_secret(name: str) -> str:
    if name == "official_token":
        value = getenv("OFFICIAL_TOKEN")
        if value:
            return value
    else:
        env = {"openai_api_key": "OPENAI_API_KEY", "anthropic_api_key": "ANTHROPIC_API_KEY"}.get(name)
        if env and os.getenv(env):
            return os.getenv(env, "")
    kr = _keyring()
    if kr is not None:
        try:
            value = kr.get_password(SERVICE, name)
            if value:
                return value
        except Exception:
            pass
    return str(_load_json(FALLBACK_SECRET_PATH).get(name, ""))


def delete_secret(name: str) -> None:
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, name)
        except Exception:
            pass
    data = _load_json(FALLBACK_SECRET_PATH)
    if name in data:
        del data[name]
        FALLBACK_SECRET_PATH.write_text(json.dumps(data), encoding="utf-8")


def has_secret(name: str) -> bool:
    return bool(get_secret(name))
