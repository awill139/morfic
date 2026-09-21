from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .llm import llm
from .models import AppManifest, PatchAction
from .prompts import LOCALIZE_STRINGS_SYSTEM, REPAIR_GENERATION_JSON_SYSTEM

_LANGUAGE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(chinese|mandarin|simplified chinese|zh[-_ ]?cn)\b", re.I), "Simplified Chinese"),
    (re.compile(r"\b(traditional chinese|zh[-_ ]?tw)\b", re.I), "Traditional Chinese"),
    (re.compile(r"\b(spanish|español)\b", re.I), "Spanish"),
    (re.compile(r"\b(french|français)\b", re.I), "French"),
    (re.compile(r"\b(german|deutsch)\b", re.I), "German"),
    (re.compile(r"\b(japanese|日本語)\b", re.I), "Japanese"),
    (re.compile(r"\b(korean|한국어)\b", re.I), "Korean"),
    (re.compile(r"\b(portuguese|português)\b", re.I), "Portuguese"),
    (re.compile(r"\b(italian|italiano)\b", re.I), "Italian"),
    (re.compile(r"\b(arabic|العربية)\b", re.I), "Arabic"),
    (re.compile(r"\b(hindi|हिन्दी)\b", re.I), "Hindi"),
    (re.compile(r"\b(russian|русский)\b", re.I), "Russian"),
]

_LOCALIZATION_HINTS = re.compile(
    r"\b(translate|translation|locali[sz]e|language|make (?:it|the app|everything|all)|in)\b", re.I
)

@dataclass(frozen=True)
class Candidate:
    id: str
    path: str
    start: int
    end: int
    text: str
    kind: str
    quote: str = ""
    context: str = ""


def detect_localization_request(request: str) -> str | None:
    """Return a target language for clear localization requests, otherwise None."""
    target = None
    for pattern, language in _LANGUAGE_PATTERNS:
        if pattern.search(request):
            target = language
            break
    if not target:
        return None
    # A bare language name can occur in unrelated requests; require a localization-ish cue.
    if _LOCALIZATION_HINTS.search(request) or len(request.split()) <= 8:
        return target
    return None


def _humanish(text: str) -> bool:
    s = text.strip()
    if len(s) < 2 or len(s) > 300:
        return False
    if not re.search(r"[A-Za-z\u00C0-\u024F]", s):
        return False
    if re.match(r"^(https?://|/|\./|\.\./|#[A-Za-z0-9_-]+|\.[A-Za-z0-9_-]+)", s):
        return False
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.-]*", s) and " " not in s:
        # Single code-like token. Keep common visible CTA words, otherwise skip.
        return s.lower() in {
            "save", "cancel", "add", "delete", "edit", "today", "history", "settings", "submit",
            "sleep", "water", "exercise", "mood", "meals", "dashboard", "insights", "weekly", "daily",
        }
    return True


def _context(source: str, start: int, end: int, radius: int = 80) -> str:
    a = max(0, start - radius)
    b = min(len(source), end + radius)
    return source[a:b].replace("\n", " ")


def _extract_html(path: str, source: str, counter: int) -> tuple[list[Candidate], int]:
    out: list[Candidate] = []
    # Visible text nodes. Avoid script/style bodies by first tracking rough blocked ranges.
    blocked: list[tuple[int, int]] = []
    for m in re.finditer(r"<(script|style)\b[^>]*>.*?</\1\s*>", source, flags=re.I | re.S):
        blocked.append((m.start(), m.end()))

    def is_blocked(pos: int) -> bool:
        return any(a <= pos < b for a, b in blocked)

    for m in re.finditer(r">([^<>]+)<", source, flags=re.S):
        start, end = m.start(1), m.end(1)
        if is_blocked(start):
            continue
        raw = m.group(1)
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        s, e = start + leading, start + trailing
        text = source[s:e]
        if not _humanish(text):
            continue
        cid = f"s{counter}"; counter += 1
        out.append(Candidate(cid, path, s, e, text, "html_text", context=_context(source, s, e)))

    attr_re = re.compile(r"\b(placeholder|title|aria-label|alt|value)\s*=\s*([\"'])(.*?)\2", re.I | re.S)
    for m in attr_re.finditer(source):
        text = m.group(3)
        if not _humanish(text):
            continue
        s, e = m.start(3), m.end(3)
        cid = f"s{counter}"; counter += 1
        out.append(Candidate(cid, path, s, e, text, "html_attr", quote=m.group(2), context=_context(source, s, e)))
    return out, counter


def _extract_js(path: str, source: str, counter: int) -> tuple[list[Candidate], int]:
    out: list[Candidate] = []
    # Conservative string-literal extractor. Template strings containing ${...} are skipped.
    string_re = re.compile(r"(?P<q>['\"`])(?P<body>(?:\\.|(?!\1).)*?)(?P=q)", re.S)
    for m in string_re.finditer(source):
        body = m.group("body")
        if m.group("q") == "`" and "${" in body:
            continue
        try:
            # Minimal unescape for readability; keep escaped source if decoding is unsafe.
            text = bytes(body, "utf-8").decode("unicode_escape") if "\\" in body and body.isascii() else body
        except Exception:
            text = body
        if not _humanish(text):
            continue
        # Avoid obvious implementation constants and HTML snippets/templates.
        low = text.lower().strip()
        if any(x in low for x in ("localstorage", "queryselector", "application/json", "text/html")):
            continue
        if "<" in text and ">" in text:
            continue
        s, e = m.start("body"), m.end("body")
        cid = f"s{counter}"; counter += 1
        out.append(Candidate(cid, path, s, e, text, "js_string", quote=m.group("q"), context=_context(source, s, e)))
    return out, counter


def extract_candidates(app_dir: Path, entry_file: str = "index.html") -> tuple[dict[str, str], list[Candidate]]:
    files: dict[str, str] = {}
    candidates: list[Candidate] = []
    counter = 1
    for path in ("index.html", "app.js", "script.js", "main.js"):
        p = app_dir / path
        if not p.exists() or not p.is_file():
            continue
        source = p.read_text(encoding="utf-8")
        files[path] = source
        if path.endswith(".html"):
            found, counter = _extract_html(path, source, counter)
        else:
            found, counter = _extract_js(path, source, counter)
        candidates.extend(found)
    return files, candidates


def _batches(items: list[Candidate], max_items: int = 32, max_chars: int = 7000) -> Iterable[list[Candidate]]:
    current: list[Candidate] = []
    chars = 0
    for item in items:
        weight = len(item.text) + len(item.context) + 80
        if current and (len(current) >= max_items or chars + weight > max_chars):
            yield current
            current, chars = [], 0
        current.append(item); chars += weight
    if current:
        yield current


def _parse_json_object(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a:b+1])
        raise


async def _translate_batch(batch: list[Candidate], target_language: str, request: str) -> dict[str, str]:
    payload = {
        "target_language": target_language,
        "user_request": request,
        "candidates": [
            {"id": c.id, "text": c.text, "file": c.path, "kind": c.kind, "context": c.context}
            for c in batch
        ],
    }
    raw = await llm.chat(
        LOCALIZE_STRINGS_SYSTEM,
        json.dumps(payload, ensure_ascii=False),
        json_mode=True,
        max_output_tokens=3000,
    )
    try:
        data = _parse_json_object(raw)
    except Exception as first:
        repair_payload = {
            "artifact": "localization translation map",
            "parse_error": str(first),
            "partial_response": raw[-12000:],
            "instruction": 'Return valid JSON with schema {"translations":[{"id":"...","text":"..."}]}.',
        }
        repaired = await llm.chat(REPAIR_GENERATION_JSON_SYSTEM, json.dumps(repair_payload, ensure_ascii=False), json_mode=True, max_output_tokens=3000)
        try:
            data = _parse_json_object(repaired)
        except Exception as second:
            raise RuntimeError(f"Localization batch returned invalid JSON after repair: {second}") from first
    allowed = {c.id for c in batch}
    result: dict[str, str] = {}
    for row in data.get("translations") or []:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "")
        text = row.get("text")
        if cid in allowed and isinstance(text, str) and text.strip():
            result[cid] = text
    return result


def _escape(candidate: Candidate, translated: str) -> str:
    if candidate.kind == "html_text":
        return html.escape(translated, quote=False)
    if candidate.kind == "html_attr":
        return html.escape(translated, quote=True)
    if candidate.kind == "js_string":
        q = candidate.quote or '"'
        out = translated.replace("\\", "\\\\")
        if q == "`":
            out = out.replace("`", "\\`").replace("${", "\\${")
        else:
            out = out.replace(q, "\\" + q)
        out = out.replace("\n", "\\n")
        return out
    return translated


async def propose_localization(app_dir: Path, manifest: AppManifest, request: str, target_language: str) -> PatchAction:
    files, candidates = extract_candidates(app_dir, manifest.entry_file or "index.html")
    if not candidates:
        raise RuntimeError("No user-facing strings were detected to localize.")

    translations: dict[str, str] = {}
    for batch in _batches(candidates):
        translations.update(await _translate_batch(batch, target_language, request))

    by_path: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        if candidate.id in translations and translations[candidate.id] != candidate.text:
            by_path.setdefault(candidate.path, []).append(candidate)

    writes: list[dict[str, str]] = []
    for path, path_candidates in by_path.items():
        source = files[path]
        for candidate in sorted(path_candidates, key=lambda c: c.start, reverse=True):
            replacement = _escape(candidate, translations[candidate.id])
            source = source[:candidate.start] + replacement + source[candidate.end:]
        writes.append({"path": path, "content": source})

    if not writes:
        raise RuntimeError("The localization model did not identify any visible strings that needed translation.")

    return PatchAction(
        summary=f"Localized the app to {target_language} using targeted string replacement",
        file_writes=writes,
        file_deletes=[],
    )
