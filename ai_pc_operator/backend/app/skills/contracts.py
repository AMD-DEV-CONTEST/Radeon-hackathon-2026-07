"""Skill contracts - typed inputs, outputs, and results.

These are the canonical Pydantic types used by every skill handler.
Skills declare their inputs/outputs in the registry; the runtime
validates them before/after execution.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SkillStatus(str, Enum):
    """Outcome status for a skill run."""

    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"
    ROLLED_BACK = "rolled_back"
    NEEDS_APPROVAL = "needs_approval"


class SkillInputSpec(BaseModel):
    """Declared input parameter for a skill."""

    name: str
    type: str = "string"  # string | int | float | bool | path | url | json
    required: bool = True
    description: str = ""
    default: Optional[Any] = None


class SkillOutputSpec(BaseModel):
    """Declared output field for a skill."""

    name: str
    type: str = "string"
    description: str = ""


class SkillVerificationSpec(BaseModel):
    """Verification method attached to a skill."""

    method: str  # file_exists | dom_state | screenshot_diff | ocr_text | process_healthy | http_status | json_path
    config: Dict[str, Any] = Field(default_factory=dict)
    required: bool = True


class SkillPermission(str, Enum):
    """Permission scopes a skill may request."""

    FS_READ = "fs.read"
    FS_WRITE = "fs.write"
    FS_DELETE = "fs.delete"
    NET_HTTP = "net.http"
    PROCESS_SPAWN = "process.spawn"
    VAULT_READ = "vault.read"
    VAULT_WRITE = "vault.write"
    SCREEN_READ = "screen.read"
    SCREEN_CLICK = "screen.click"
    BROWSER_AUTOMATE = "browser.automate"


class SkillDefinition(BaseModel):
    """Full skill metadata as stored in the registry."""

    id: str
    domain: str
    name: str
    description: str
    version: str = "1.0.0"
    risk_level: int = 0
    requires_approval: bool = False
    reversible: bool = True
    idempotent: bool = True
    timeout_sec: int = 30
    retry_limit: int = 2
    enabled: bool = True
    handler: str  # dotted path, e.g. "app.skills.handlers.file.list_dir"
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    inputs: List[SkillInputSpec] = Field(default_factory=list)
    outputs: List[SkillOutputSpec] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    verification: List[SkillVerificationSpec] = Field(default_factory=list)
    permissions: List[SkillPermission] = Field(default_factory=list)


class SkillRunRequest(BaseModel):
    """Request to execute a skill."""

    skill_id: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    task_id: Optional[str] = None
    node_id: Optional[str] = None
    command_id: Optional[int] = None
    device_id: Optional[str] = None


class SkillRunResult(BaseModel):
    """Result of a skill execution."""

    skill_id: str
    status: SkillStatus
    outputs: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: int = 0
    attempts: int = 1
    evidence_ids: List[int] = Field(default_factory=list)
    verification_passed: Optional[bool] = None
    verification_details: List[Dict[str, Any]] = Field(default_factory=list)
