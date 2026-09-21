"""Environment-variable lookup for Morfic settings.

Every setting is read as ``MORFIC_<NAME>`` first, then the legacy
``PERSONAL_SOFTWARE_<NAME>`` spelling, so existing installs and scripts keep working.
"""
from __future__ import annotations

import os

PREFIXES = ("MORFIC_", "PERSONAL_SOFTWARE_")


def getenv(name: str, default: str | None = None) -> str | None:
    for prefix in PREFIXES:
        value = os.environ.get(prefix + name)
        if value is not None:
            return value
    return default
