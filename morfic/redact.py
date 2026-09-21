"""Best-effort secret redaction and size-bounding for anything that may leave the machine as a log."""
from __future__ import annotations

import re

# Every pattern uses bounded quantifiers so a hostile or minified 100 KB prompt cannot cause quadratic
# backtracking (tests/telemetry_optout.py guards this).

# Maximum characters of a prompt or a response that are ever included in a log excerpt.
MAX_EXCERPT_CHARS = 20_000

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S), "[REDACTED PRIVATE KEY]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "[REDACTED API KEY]"),                       # OpenAI / Anthropic
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}"), "[REDACTED TOKEN]"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED AWS KEY]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "[REDACTED TOKEN]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "[REDACTED API KEY]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{12,}"), r"\1 [REDACTED]"),
    (re.compile(r"\b[A-Za-z][A-Za-z0-9+.\-]{0,20}://[^\s/:@]{1,100}:[^\s/@]{1,200}@"), "[REDACTED CREDENTIALS]@"),  # user:pass@host
    # name = value / "name": "value" for names that contain a secret-looking word. The pattern starts at the
    # keyword itself (no unbounded prefix), so it can't backtrack quadratically on long identifiers.
    (re.compile(
        r"""(?ix)
        (?P<key>(?:api[_\-]?key|secret|token|passw(?:or)?d|passphrase|private[_\-]?key|credential|auth)[A-Za-z0-9_.\-]{0,40}["']?
        \s{0,5}[:=]\s{0,5})
        (?P<val>"[^"\n]{4,500}"|'[^'\n]{4,500}'|[^\s,;"'\#]{4,500})
        """), r"\g<key>[REDACTED]"),
]


def redact_secrets(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def excerpt(text: str | None, limit: int = MAX_EXCERPT_CHARS) -> str:
    """Redact secrets, then bound the size. Redaction runs first so a secret can't survive by
    straddling the truncation point."""
    if not text:
        return ""
    cleaned = redact_secrets(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + f"\n…[truncated {len(cleaned) - limit} characters]"
