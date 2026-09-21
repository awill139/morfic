from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class UIField(BaseModel):
    name: str
    label: str
    kind: Literal["text", "number", "textarea", "file", "select"] = "text"
    required: bool = False
    help: str = ""
    options: list[str] = Field(default_factory=list)


class FrontendSpec(BaseModel):
    kind: Literal["existing", "generated_static", "generated_cli", "none"] = "none"
    title: str = "Local app"
    description: str = ""
    fields: list[UIField] = Field(default_factory=list)


class DeploymentPlan(BaseModel):
    name: str
    summary: str
    project_type: Literal["python", "node", "dotnet", "docker", "static", "unknown"]
    install_commands: list[list[str]] = Field(default_factory=list)
    run_command: list[str] = Field(default_factory=list)
    port: int | None = None
    healthcheck_path: str = "/"
    env: dict[str, str] = Field(default_factory=dict)
    frontend: FrontendSpec = Field(default_factory=FrontendSpec)
    detected_files: list[str] = Field(default_factory=list)
    compose_file: str | None = None
    container_image: str | None = None
    persistent_mounts: dict[str, str] = Field(default_factory=dict)
    media_mounts: bool = False


class AppManifest(BaseModel):
    name: str
    description: str
    requested_intent: str
    capabilities: list[str] = Field(default_factory=list)
    source_type: Literal["generated", "github", "builtin"]
    source_url: str | None = None
    deployment_plan: DeploymentPlan | None = None
    entry_file: str | None = None
    version_notes: str = "Initial version"


class AppRecord(BaseModel):
    id: int
    name: str
    description: str
    requested_intent: str
    capabilities: list[str]
    source_type: str
    source_url: str | None
    status: str
    workspace: str
    local_url: str | None
    version: int
    manifest: AppManifest | None
    created_at: str
    updated_at: str
    last_error: str | None = None
    repair_attempts: int = 0
    pid: int | None = None


class CatalogEntry(BaseModel):
    id: str
    name: str
    description: str
    capabilities: list[str]
    keywords: list[str]
    repo_url: str
    # Immutable commit the marketplace installs. `ref_label` is the release tag it was taken from
    # (informational). Refresh both with scripts/update_catalog_pins.py.
    ref: str | None = None
    ref_label: str | None = None
    project_hint: str | None = None
    notes: str = ""
    deployment_plan: DeploymentPlan | None = None


class Resolution(BaseModel):
    strategy: Literal["installed", "catalog", "generate"]
    reason: str
    app_id: int | None = None
    catalog_entry: CatalogEntry | None = None
    generated_name: str | None = None
    capabilities: list[str] = Field(default_factory=list)


class PatchAction(BaseModel):
    summary: str
    file_writes: list[dict[str, str]] = Field(default_factory=list)
    file_deletes: list[str] = Field(default_factory=list)
    run_command: list[str] | None = None
    install_commands: list[list[str]] | None = None
    port: int | None = None
