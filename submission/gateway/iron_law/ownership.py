"""ILS v2.2 - Ownership Registry.

Tracks which agent owns which module/resource to prevent conflict (ILS-G004).
In-memory store backed by an optional Postgres table for persistence.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

_log = logging.getLogger("ils.ownership")

DATABASE_URL = os.environ.get("DATABASE_URL")


@dataclass
class OwnershipClaim:
    module_id: str
    owner_agent_id: str
    claimed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    lease_duration_seconds: int | None = None
    scope: str = ""
    released_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        if self.released_at is not None:
            return False
        if self.lease_duration_seconds is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self.claimed_at).total_seconds()
        return elapsed < self.lease_duration_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "owner_agent_id": self.owner_agent_id,
            "claimed_at": self.claimed_at.isoformat(),
            "lease_duration_seconds": self.lease_duration_seconds,
            "scope": self.scope,
            "released_at": self.released_at.isoformat() if self.released_at else None,
            "is_active": self.is_active,
        }


class OwnershipRegistry:
    """Thread-safe in-memory ownership registry with optional DB persistence."""

    def __init__(self, persist: bool = True) -> None:
        self._lock = threading.Lock()
        self._claims: dict[str, OwnershipClaim] = {}  # module_id -> latest claim
        self._persist = persist and bool(DATABASE_URL)

    def claim(
        self,
        module_id: str,
        agent_id: str,
        scope: str = "",
        lease_seconds: int | None = None,
    ) -> OwnershipClaim:
        """Claim ownership of a module. Raises if already owned by another active agent."""
        with self._lock:
            existing = self._claims.get(module_id)
            if existing and existing.is_active and existing.owner_agent_id != agent_id:
                raise OwnershipConflictError(
                    module_id=module_id,
                    current_owner=existing.owner_agent_id,
                    requesting_agent=agent_id,
                )
            claim = OwnershipClaim(
                module_id=module_id,
                owner_agent_id=agent_id,
                lease_duration_seconds=lease_seconds,
                scope=scope,
            )
            self._claims[module_id] = claim
            if self._persist:
                self._db_upsert(claim)
            _log.info("[OWNERSHIP] claimed module=%s agent=%s scope=%s", module_id, agent_id, scope)
            return claim

    def release(self, module_id: str, agent_id: str) -> bool:
        """Release ownership. Returns True if released, False if not owned by this agent."""
        with self._lock:
            claim = self._claims.get(module_id)
            if not claim or claim.owner_agent_id != agent_id:
                return False
            claim.released_at = datetime.now(timezone.utc)
            if self._persist:
                self._db_release(module_id, agent_id)
            _log.info("[OWNERSHIP] released module=%s agent=%s", module_id, agent_id)
            return True

    def check(self, module_id: str) -> OwnershipClaim | None:
        """Return the active claim for a module, or None."""
        with self._lock:
            claim = self._claims.get(module_id)
            if claim and claim.is_active:
                return claim
            return None

    def active_claims(self) -> list[OwnershipClaim]:
        """Return all active claims."""
        with self._lock:
            return [c for c in self._claims.values() if c.is_active]

    def check_conflict(self, module_ids: list[str], agent_id: str) -> list[dict[str, str]]:
        """Check if any module in the list is owned by a different agent.
        Returns list of conflict descriptors (empty = no conflict).
        """
        conflicts: list[dict[str, str]] = []
        with self._lock:
            for mid in module_ids:
                claim = self._claims.get(mid)
                if claim and claim.is_active and claim.owner_agent_id != agent_id:
                    conflicts.append({
                        "module_id": mid,
                        "owner": claim.owner_agent_id,
                        "scope": claim.scope,
                        "claimed_at": claim.claimed_at.isoformat(),
                    })
        return conflicts

    def _db_upsert(self, claim: OwnershipClaim) -> None:
        try:
            conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
            conn.execute(
                """
                INSERT INTO ownership_registry (module_id, owner_agent_id, scope, lease_duration_seconds, claimed_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (module_id) DO UPDATE SET
                    owner_agent_id = EXCLUDED.owner_agent_id,
                    scope = EXCLUDED.scope,
                    lease_duration_seconds = EXCLUDED.lease_duration_seconds,
                    claimed_at = EXCLUDED.claimed_at,
                    released_at = NULL,
                    updated_at = now()
                """,
                (claim.module_id, claim.owner_agent_id, claim.scope,
                 claim.lease_duration_seconds, claim.claimed_at),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            _log.warning("DB upsert failed for ownership %s: %s", claim.module_id, exc)

    def _db_release(self, module_id: str, agent_id: str) -> None:
        try:
            conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
            conn.execute(
                """
                UPDATE ownership_registry
                SET released_at = now(), updated_at = now()
                WHERE module_id = %s AND owner_agent_id = %s AND released_at IS NULL
                """,
                (module_id, agent_id),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            _log.warning("DB release failed for ownership %s: %s", module_id, exc)


class OwnershipConflictError(Exception):
    """Raised when a module is already owned by a different active agent."""

    def __init__(self, module_id: str, current_owner: str, requesting_agent: str):
        self.module_id = module_id
        self.current_owner = current_owner
        self.requesting_agent = requesting_agent
        super().__init__(
            f"ILS-F004: module '{module_id}' is owned by '{current_owner}', "
            f"cannot claim from '{requesting_agent}'"
        )


# Module-level singleton for the process
_registry: OwnershipRegistry | None = None


def get_registry() -> OwnershipRegistry:
    global _registry
    if _registry is None:
        _registry = OwnershipRegistry()
    return _registry
