"""ILS v2.2 - Participants schema + dynamic role derivation.

Defines who is involved in a task and in what capacity. Roles are either
explicitly assigned or dynamically derived from task context (intent type,
requester identity, target agent).

Role hierarchy (from ILS-v2x-execution-handoff B2):
  Level 0: system_admin  - can assign all roles
  Level 1: leader        - can assign reviewer, implementer, ops, observer
  Level 2: reviewer      - cannot assign
  Level 3: implementer   - cannot assign
  Level 4: ops           - cannot assign
  Level 5: observer      - cannot assign

Forbidden: any agent self-assigning a role (logged as security event).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

_log = logging.getLogger("ils.participants")


# -- Role enum --

class ParticipantRole(str, Enum):
    """Canonical participant roles derived from the ILS role hierarchy."""
    SYSTEM_ADMIN = "system_admin"
    LEADER = "leader"
    REVIEWER = "reviewer"
    IMPLEMENTER = "implementer"
    OPS = "ops"
    OBSERVER = "observer"
    REQUESTER = "requester"


# Authority hierarchy: who can assign which roles.
ASSIGNMENT_AUTHORITY: dict[ParticipantRole, set[ParticipantRole]] = {
    ParticipantRole.SYSTEM_ADMIN: {
        ParticipantRole.LEADER, ParticipantRole.REVIEWER,
        ParticipantRole.IMPLEMENTER, ParticipantRole.OPS, ParticipantRole.OBSERVER,
    },
    ParticipantRole.LEADER: {
        ParticipantRole.REVIEWER, ParticipantRole.IMPLEMENTER,
        ParticipantRole.OPS, ParticipantRole.OBSERVER,
    },
}

# -- Derivation source --

class DerivationSource(str, Enum):
    """How a participant role was determined."""
    EXPLICIT = "explicit"
    REQUESTER = "requester"
    TARGET_AGENT = "target_agent"
    INTENT_TYPE = "intent_type"
    POLICY = "policy"


# -- Models --

class ParticipantEntry(BaseModel):
    """One participant in a task."""
    agent_id: str = Field(description="Agent or user identifier")
    role: ParticipantRole
    derivation_source: DerivationSource = DerivationSource.EXPLICIT
    assigned_by: str | None = Field(
        default=None,
        description="Who assigned this role. None for system-derived.",
    )
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _no_self_assignment(self) -> "ParticipantEntry":
        """Enforce ILS B2: no agent may self-assign a non-requester role."""
        if (
            self.derivation_source == DerivationSource.EXPLICIT
            and self.assigned_by is not None
            and self.assigned_by == self.agent_id
            and self.role != ParticipantRole.REQUESTER
        ):
            _log.warning(
                "[ILS-SECURITY] self-assignment attempt: agent=%s role=%s",
                self.agent_id, self.role.value,
            )
            raise ValueError(
                "ILS-F006: agent cannot self-assign role. Self-assignment is prohibited."
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "derivation_source": self.derivation_source.value,
            "assigned_by": self.assigned_by,
            "assigned_at": self.assigned_at.isoformat(),
            "metadata": self.metadata,
        }

class TaskParticipants(BaseModel):
    """Container for all participants of a task."""
    entries: list[ParticipantEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_no_duplicates(self) -> "TaskParticipants":
        seen: set[tuple[str, str]] = set()
        for e in self.entries:
            key = (e.agent_id, e.role.value)
            if key in seen:
                raise ValueError(
                    "Duplicate participant: agent=%s role=%s" % (e.agent_id, e.role.value)
                )
            seen.add(key)
        return self

    def get_by_role(self, role: ParticipantRole) -> list[ParticipantEntry]:
        return [e for e in self.entries if e.role == role]

    def has_role(self, role: ParticipantRole) -> bool:
        return any(e.role == role for e in self.entries)

    def agent_roles(self, agent_id: str) -> list[ParticipantRole]:
        return [e.role for e in self.entries if e.agent_id == agent_id]

    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.entries]

# -- Dynamic role derivation --

def derive_roles(
    *,
    task_id: str,
    created_by: str,
    target_agent_id: str | None = None,
    intent_type: str | None = None,
    explicit_participants: list[dict[str, Any]] | None = None,
    project_config: dict[str, Any] | None = None,
) -> TaskParticipants:
    """Derive participant roles from task context.

    Sources (in order of precedence):
    1. created_by -> requester
    2. target_agent_id -> implementer (from deterministic routing)
    3. intent_type -> reviewer (if REVIEW intent)
    4. project_config -> leader, observer, ops (if configured)
    5. explicit_participants -> override/supplement any of the above
    """
    entries: list[ParticipantEntry] = []
    seen: dict[tuple[str, str], int] = {}

    def _add(
        agent_id: str,
        role: ParticipantRole,
        source: DerivationSource,
        assigned_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        key = (agent_id, role.value)
        entry = ParticipantEntry(
            agent_id=agent_id,
            role=role,
            derivation_source=source,
            assigned_by=assigned_by,
            metadata=metadata or {},
        )
        if key in seen:
            entries[seen[key]] = entry
        else:
            seen[key] = len(entries)
            entries.append(entry)

    # 1. Requester (always derived from created_by)
    if created_by:
        _add(created_by, ParticipantRole.REQUESTER, DerivationSource.REQUESTER)

    # 2. Target agent -> implementer
    if target_agent_id:
        _add(
            target_agent_id,
            ParticipantRole.IMPLEMENTER,
            DerivationSource.TARGET_AGENT,
        )

    # 3. Intent type -> reviewer for REVIEW intents
    if intent_type and intent_type.lower() == "review":
        if target_agent_id:
            _add(
                target_agent_id,
                ParticipantRole.REVIEWER,
                DerivationSource.INTENT_TYPE,
                metadata={"note": "auto-derived: REVIEW intent"},
            )

    # 4. Project config -> leader, observer, ops
    if project_config:
        for role_key in ("leader", "observer", "ops"):
            cfg_agents = project_config.get(role_key)
            if isinstance(cfg_agents, str):
                cfg_agents = [cfg_agents]
            if isinstance(cfg_agents, list):
                for agent_id in cfg_agents:
                    if agent_id:
                        _add(
                            agent_id,
                            ParticipantRole(role_key),
                            DerivationSource.POLICY,
                        )

    # 5. Explicit participants (highest precedence)
    if explicit_participants:
        for p in explicit_participants:
            agent_id = p.get("agent_id", "")
            role_str = p.get("role", "")
            if not agent_id or not role_str:
                continue
            try:
                role = ParticipantRole(role_str)
            except ValueError:
                _log.warning(
                    "[PARTICIPANTS] unknown role for agent=%s, skipping",
                    agent_id,
                )
                continue
            _add(
                agent_id,
                role,
                DerivationSource.EXPLICIT,
                assigned_by=p.get("assigned_by"),
                metadata=p.get("metadata"),
            )

    return TaskParticipants(entries=entries)

def validate_assignment(
    assigner_role: ParticipantRole,
    target_role: ParticipantRole,
) -> tuple[bool, str | None]:
    """Check if assigner_role is authorized to assign target_role."""
    allowed_targets = ASSIGNMENT_AUTHORITY.get(assigner_role)
    if allowed_targets is None:
        return False, "Role has no assignment authority"
    if target_role not in allowed_targets:
        return False, (
            "Role cannot assign target role. Allowed: %s"
            % [r.value for r in allowed_targets]
        )
    return True, None
