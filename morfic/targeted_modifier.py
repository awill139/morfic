from __future__ import annotations

import json
import re
from pathlib import Path

from .inspector import inspect_editable_files
from .llm import llm
from .models import AppManifest, PatchAction
from .prompts import (
    MODIFY_IMPACT_SYSTEM,
    MODIFY_PATCH_SYSTEM,
    MODIFY_NEW_FILE_SYSTEM,
    REPAIR_GENERATION_JSON_SYSTEM,
)

MAX_PLAN_REPAIRS = 2
MAX_PATCH_ATTEMPTS = 2
MAX_NEW_FILES = 4
MAX_EXISTING_FILES = 6


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        json.loads(text)
        return text
    except Exception:
        a, b = text.find("{"), text.rfind("}")
        return text[a:b+1] if a >= 0 and b > a else text


async def _json_with_repair(system: str, payload: dict, *, label: str, max_tokens: int = 4500) -> dict:
    raw = await llm.chat(system, json.dumps(payload, ensure_ascii=False), json_mode=True, max_output_tokens=max_tokens)
    current = raw
    last_error: Exception | None = None
    for attempt in range(MAX_PLAN_REPAIRS + 1):
        try:
            data = json.loads(_extract_json(current))
            if not isinstance(data, dict):
                raise ValueError("top-level response is not an object")
            return data
        except Exception as e:
            last_error = e
            if attempt >= MAX_PLAN_REPAIRS:
                break
            repair_payload = {
                "artifact": label,
                "parse_error": str(e),
                "original_request": payload.get("request", ""),
                "partial_response": current[-24000:],
                "instruction": "Return one complete compact valid JSON object and no prose.",
            }
            current = await llm.chat(
                REPAIR_GENERATION_JSON_SYSTEM,
                json.dumps(repair_payload, ensure_ascii=False),
                json_mode=True,
                max_output_tokens=max_tokens,
            )
    raise RuntimeError(f"Model returned invalid {label} after repair: {last_error}")


def _source_map(snapshot: dict[str, str]) -> list[dict]:
    return [_outline(path, content) for path, content in snapshot.items()]


def _outline(path: str, content: str) -> dict:
    item: dict = {"path": path, "chars": len(content), "lines": content.count("\n") + 1}
    suffix = Path(path).suffix.lower()
    if suffix in {".html", ".htm"}:
        item["ids"] = list(dict.fromkeys(re.findall(r'\bid=["\']([^"\']+)', content, flags=re.I)))[:80]
        headings = re.findall(r"<h[1-4][^>]*>(.*?)</h[1-4]>", content, flags=re.I | re.S)
        item["headings"] = [re.sub(r"<[^>]+>", "", h).strip()[:100] for h in headings[:30]]
        item["scripts"] = re.findall(r'<script[^>]+src=["\']([^"\']+)', content, flags=re.I)[:30]
        item["stylesheets"] = re.findall(r'<link[^>]+href=["\']([^"\']+)', content, flags=re.I)[:30]
    elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
        funcs = re.findall(r"\b(?:function\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>)", content)
        item["functions"] = list(dict.fromkeys(a or b for a, b in funcs if (a or b)))[:100]
        item["storage_keys"] = list(dict.fromkeys(re.findall(r"localStorage\.(?:getItem|setItem|removeItem)\(\s*[\"']([^\"']+)", content)))[:40]
    elif suffix == ".css":
        selectors = re.findall(r"(?:^|\})\s*([^@{}][^{}]{0,180})\{", content, flags=re.M)
        item["selectors"] = [s.strip()[:160] for s in selectors[:100]]
    elif suffix == ".py":
        item["functions"] = re.findall(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", content, flags=re.M)[:100]
        item["classes"] = re.findall(r"^\s*class\s+([A-Za-z_]\w*)", content, flags=re.M)[:60]
    # A tiny preview helps the planner understand composition without sending whole files.
    preview = content if len(content) <= 1800 else content[:900] + "\n...\n" + content[-900:]
    item["preview"] = preview
    return item


def _safe_rel(path: str) -> str:
    cleaned = str(path or "").strip().replace("\\", "/")
    rel = Path(cleaned)
    if not cleaned or rel.is_absolute() or ".." in rel.parts:
        raise RuntimeError(f"Unsafe modification path: {path}")
    return rel.as_posix()


def _allowed_new_file(path: str) -> bool:
    return Path(path).suffix.lower() in {".html", ".css", ".js", ".json", ".md"}


def _choose_context(content: str, hints: list[str], *, max_chars: int = 42000) -> str:
    """Return relevant windows around planner hints, falling back to bounded full context.

    Input tokens are less dangerous than output tokens, but huge multi-file apps should still
    not be sent wholesale for every patch. We include windows around named functions/ids/text,
    plus the beginning/end so imports and closing insertion anchors are visible.
    """
    if len(content) <= max_chars:
        return content
    windows: list[tuple[int, int]] = []
    radius = 5000
    lower = content.lower()
    for raw_hint in hints[:12]:
        hint = str(raw_hint or "").strip()
        if not hint:
            continue
        idx = content.find(hint)
        if idx < 0:
            idx = lower.find(hint.lower())
        if idx >= 0:
            windows.append((max(0, idx - radius), min(len(content), idx + len(hint) + radius)))
    windows.extend([(0, min(len(content), 5000)), (max(0, len(content)-5000), len(content))])
    windows.sort()
    merged: list[tuple[int, int]] = []
    for a, b in windows:
        if merged and a <= merged[-1][1] + 500:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    chunks: list[str] = []
    remaining = max_chars
    for a, b in merged:
        if remaining <= 0:
            break
        chunk = content[a:b]
        if len(chunk) > remaining:
            chunk = chunk[:remaining]
        chunks.append(f"/* context chars {a}:{a+len(chunk)} */\n{chunk}")
        remaining -= len(chunk)
    return "\n\n/* ... unrelated regions omitted ... */\n\n".join(chunks)


def _nth_index(haystack: str, needle: str, occurrence: int) -> int:
    if not needle:
        return -1
    start = 0
    for _ in range(max(1, occurrence)):
        idx = haystack.find(needle, start)
        if idx < 0:
            return -1
        start = idx + len(needle)
    return idx


def apply_operations(source: str, operations: list[dict]) -> str:
    current = source
    for i, op in enumerate(operations):
        if not isinstance(op, dict):
            raise RuntimeError(f"Patch operation {i+1} is not an object")
        kind = str(op.get("op") or "").strip()
        occurrence = int(op.get("occurrence") or 1)
        if occurrence < 1:
            occurrence = 1
        if kind == "replace":
            old = str(op.get("old") or "")
            new = str(op.get("new") or "")
            idx = _nth_index(current, old, occurrence)
            if idx < 0:
                raise RuntimeError(f"replace anchor not found for operation {i+1}: {old[:180]!r}")
            current = current[:idx] + new + current[idx+len(old):]
        elif kind in {"insert_before", "insert_after"}:
            anchor = str(op.get("anchor") or "")
            content = str(op.get("content") or "")
            idx = _nth_index(current, anchor, occurrence)
            if idx < 0:
                raise RuntimeError(f"{kind} anchor not found for operation {i+1}: {anchor[:180]!r}")
            pos = idx if kind == "insert_before" else idx + len(anchor)
            current = current[:pos] + content + current[pos:]
        elif kind == "delete":
            old = str(op.get("old") or "")
            idx = _nth_index(current, old, occurrence)
            if idx < 0:
                raise RuntimeError(f"delete anchor not found for operation {i+1}: {old[:180]!r}")
            current = current[:idx] + current[idx+len(old):]
        else:
            raise RuntimeError(f"Unsupported patch operation: {kind}")
    return current


async def propose_targeted_generated_modification(app_dir: Path, manifest: AppManifest, request: str, validate_file) -> PatchAction:
    snapshot = inspect_editable_files(app_dir, max_files=60, max_chars=320000)
    if not snapshot:
        raise RuntimeError("No editable files were available for modification")

    plan_payload = {
        "request": request,
        "manifest": manifest.model_dump(),
        "source_map": _source_map(snapshot),
    }
    plan = await _json_with_repair(MODIFY_IMPACT_SYSTEM, plan_payload, label="modification impact plan", max_tokens=5000)
    summary = str(plan.get("summary") or request)[:300]

    new_files: list[dict[str, str]] = []
    planned_new = plan.get("new_files") or []
    for item in planned_new[:MAX_NEW_FILES]:
        if not isinstance(item, dict):
            continue
        path = _safe_rel(item.get("path"))
        if path in snapshot or not _allowed_new_file(path):
            continue
        payload = {
            "request": request,
            "manifest": manifest.model_dump(),
            "modification_summary": summary,
            "target_file": {"path": path, "purpose": str(item.get("purpose") or "")[:1000]},
            "source_map": _source_map(snapshot),
        }
        content = await llm.chat(
            MODIFY_NEW_FILE_SYSTEM,
            json.dumps(payload, ensure_ascii=False),
            json_mode=False,
            max_output_tokens=10000,
        )
        content = _strip_fence(content)
        validate_file(path, content)
        new_files.append({"path": path, "content": content})

    writes: list[dict[str, str]] = list(new_files)
    changes = plan.get("existing_file_changes") or []
    seen: set[str] = set()
    for item in changes[:MAX_EXISTING_FILES]:
        if not isinstance(item, dict):
            continue
        path = _safe_rel(item.get("path"))
        if path not in snapshot or path in seen:
            continue
        seen.add(path)
        instruction = str(item.get("instruction") or request).strip()
        hints = [str(x) for x in (item.get("hints") or []) if str(x).strip()][:12]
        original = snapshot[path]
        context = _choose_context(original, hints)
        last_error: Exception | None = None
        replacement: str | None = None

        for attempt in range(MAX_PATCH_ATTEMPTS + 1):
            patch_payload = {
                "request": request,
                "manifest": manifest.model_dump(),
                "modification_summary": summary,
                "target_file": path,
                "file_instruction": instruction,
                "hints": hints,
                "current_file_context": context,
                "known_new_files": [{"path": f["path"]} for f in new_files],
                "previous_error": str(last_error) if last_error else None,
            }
            patch = await _json_with_repair(MODIFY_PATCH_SYSTEM, patch_payload, label=f"targeted patch for {path}", max_tokens=6500)
            operations = patch.get("operations") or []
            try:
                if not operations:
                    raise RuntimeError("model returned no patch operations")
                candidate = apply_operations(original, operations)
                validate_file(path, candidate)
                replacement = candidate
                break
            except Exception as e:
                last_error = e
                if attempt >= MAX_PATCH_ATTEMPTS:
                    break
        if replacement is None:
            raise RuntimeError(f"Could not apply a localized patch to {path}: {last_error}")
        if replacement != original:
            writes.append({"path": path, "content": replacement})

    deletes = []
    for raw in (plan.get("file_deletes") or []):
        path = _safe_rel(raw)
        if path in snapshot:
            deletes.append(path)

    if not writes and not deletes:
        raise RuntimeError("The modification planner found no concrete localized changes to apply.")

    return PatchAction(summary=summary, file_writes=writes, file_deletes=deletes)


def _strip_fence(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:html|css|javascript|js|json)?\s*\n?(.*?)\n?```$", text, flags=re.I | re.S)
    return m.group(1).strip() if m else text
