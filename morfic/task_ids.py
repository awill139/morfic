from __future__ import annotations
from . import prompts

_PROMPT_TASKS={
 prompts.RESOLVE_SYSTEM:'resolve',
 prompts.PLAN_REPO_SYSTEM:'plan_repo',
 prompts.GENERATE_SYSTEM:'generate_blueprint',
 prompts.GENERATE_FILE_SYSTEM:'generate_file',
 prompts.REPAIR_GENERATION_JSON_SYSTEM:'repair_json',
 prompts.REPAIR_GENERATED_FILE_SYSTEM:'repair_generated_file',
 prompts.MODIFY_REPO_SYSTEM:'modify_repo',
 prompts.REPAIR_SYSTEM:'repair_repo',
 prompts.LOCALIZE_STRINGS_SYSTEM:'localize_strings',
 prompts.MODIFY_IMPACT_SYSTEM:'modify_impact',
 prompts.MODIFY_PATCH_SYSTEM:'modify_patch',
 prompts.MODIFY_NEW_FILE_SYSTEM:'modify_new_file',
}

def task_for_system(system:str)->str|None:
    return _PROMPT_TASKS.get(system)
