from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from .inspector import inspect_repo
from .llm import llm
from .models import DeploymentPlan, PatchAction
from .prompts import REPAIR_SYSTEM


async def propose_repair(repo: Path, plan: DeploymentPlan, error: str) -> PatchAction | None:
    heuristic = heuristic_repair(repo, error)
    if heuristic:
        return heuristic
    payload = {"error": error[-18000:], "plan": plan.model_dump(), "repo": inspect_repo(repo)}
    raw = await llm.chat(REPAIR_SYSTEM, json.dumps(payload, indent=2)[:100000], json_mode=True)
    try:
        return PatchAction.model_validate(json.loads(_extract_json(raw)))
    except Exception as e:
        raise RuntimeError(f"Invalid repair response: {e}\n{raw[:1000]}") from e


def heuristic_repair(repo: Path, error: str) -> PatchAction | None:
    m = re.search(r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]", error)
    if m:
        missing = m.group(1).split(".")[0]
        candidates = [p.stem for p in repo.glob("*.py") if p.stem not in {"main", "app", "server"}]
        match = difflib.get_close_matches(missing, candidates, n=1, cutoff=0.72)
        if match:
            replacement = match[0]
            for p in repo.glob("*.py"):
                text = p.read_text(encoding="utf-8", errors="replace")
                if f"from {missing} import " in text or f"import {missing}" in text:
                    new = text.replace(f"from {missing} import ", f"from {replacement} import ").replace(f"import {missing}", f"import {replacement}")
                    return PatchAction(summary=f"Corrected likely local import typo {missing} → {replacement}", file_writes=[{"path": p.name, "content": new}])
    return None


def apply_patch(root_dir: Path, plan: DeploymentPlan | None, action: PatchAction) -> DeploymentPlan | None:
    root = root_dir.resolve()
    for item in action.file_writes:
        rel = Path(item["path"])
        target = (root / rel).resolve()
        if root not in target.parents and target != root:
            raise RuntimeError(f"Patch attempted to write outside app workspace: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item["content"], encoding="utf-8")
    for path in action.file_deletes:
        target = (root / path).resolve()
        if root not in target.parents:
            raise RuntimeError(f"Patch attempted to delete outside app workspace: {path}")
        if target.exists() and target.is_file():
            target.unlink()
    if plan is None:
        return None
    data = plan.model_dump()
    if action.run_command is not None:
        data["run_command"] = action.run_command
    if action.install_commands is not None:
        data["install_commands"] = action.install_commands
    if action.port is not None:
        data["port"] = action.port
    return DeploymentPlan.model_validate(data)


def _extract_json(text: str) -> str:
    s, e = text.find("{"), text.rfind("}")
    return text[s:e+1] if s >= 0 and e > s else text
