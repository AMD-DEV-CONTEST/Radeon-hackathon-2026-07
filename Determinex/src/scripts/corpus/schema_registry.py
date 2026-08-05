"""
scripts/corpus/schema_registry.py — Schema version registry and migration skeleton.

Every corpus record carries a schema_version field. This module:
  - Defines the canonical version history (oldest to newest)
  - Validates that incoming records carry a known schema version
  - Provides migration functions for records from older schema versions
  - Rejects records from future (unknown) schema versions — fail-closed

Why this matters: retraining pipelines that silently accept records with
unknown schema versions can corrupt the training set with improperly
structured or signed data. Explicit version gating catches future-you
breaking past-you's corpus silently.

Usage:
    from corpus.schema_registry import SchemaRegistry, SchemaVersionError

    registry = SchemaRegistry()
    registry.validate_version(record.get("schema_version"))   # raises on mismatch
    upgraded = registry.migrate(record)                        # returns upgraded copy
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Version history (append-only — never remove an entry)
# ---------------------------------------------------------------------------

CURRENT_VERSION = "determinex-agent-trace-v1"

_VERSION_HISTORY: list[str] = [
    "determinex-agent-trace-v1",  # initial: all fields, BLAKE2b-256 HMAC, sorted-key JSON
    # "determinex-agent-trace-v2",  # future: add schema_migration_history field
    # "determinex-agent-trace-v3",  # future: add training_eligible flag
]

_KNOWN_VERSIONS: frozenset[str] = frozenset(_VERSION_HISTORY)


# ---------------------------------------------------------------------------
# Migration functions  (from_version → to_version)
# ---------------------------------------------------------------------------
# Pattern: def _migrate_vX(record: dict) -> dict — returns NEW dict, never mutates.
# Add to _MIGRATIONS when defining; remove the comment on the version line above.

# def _migrate_v1_to_v2(record: dict[str, Any]) -> dict[str, Any]:
#     upgraded = dict(record)
#     upgraded["schema_migration_history"] = [record["schema_version"]]
#     upgraded["schema_version"] = "determinex-agent-trace-v2"
#     return upgraded

_MIGRATIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    # "determinex-agent-trace-v1": _migrate_v1_to_v2,
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SchemaVersionError(ValueError):
    """Raised when a record carries an unknown or incompatible schema version."""


# ---------------------------------------------------------------------------
# SchemaRegistry
# ---------------------------------------------------------------------------


class SchemaRegistry:
    """
    Validates and migrates corpus records across schema versions.
    Fail-closed: unknown versions raise SchemaVersionError, not a silent pass.
    """

    def __init__(self, current: str = CURRENT_VERSION) -> None:
        self.current = current

    def validate_version(self, version: str | None) -> None:
        """
        Raise SchemaVersionError if *version* is not in the known history.
        None and empty string are treated as missing field (rejected).
        """
        if not version:
            raise SchemaVersionError(
                f"Record is missing schema_version. Expected one of: {sorted(_KNOWN_VERSIONS)}"
            )
        if version not in _KNOWN_VERSIONS:
            raise SchemaVersionError(
                f"Unknown schema_version {version!r}. "
                f"Known versions: {sorted(_KNOWN_VERSIONS)}. "
                "This record may be from a newer Determinex version than this codebase supports, "
                "or may be corrupted."
            )
        if version != self.current:
            log.info(
                "[schema_registry] Record schema_version=%r is older than current=%r — "
                "migration available via SchemaRegistry.migrate()",
                version,
                self.current,
            )

    def is_current(self, version: str) -> bool:
        """Return True if *version* matches the current schema version."""
        return version == self.current

    def migrate(self, record: dict[str, Any]) -> dict[str, Any]:
        """
        Migrate *record* to the current schema version.

        Returns a NEW dict — original is not mutated.
        Raises SchemaVersionError if the version is unknown.
        Raises NotImplementedError if a migration function is not yet written.
        """
        self.validate_version(record.get("schema_version"))
        result = dict(record)

        while result.get("schema_version") != self.current:
            current_v = result["schema_version"]
            migration_fn = _MIGRATIONS.get(current_v)
            if migration_fn is None:
                raise SchemaVersionError(
                    f"No migration path from schema_version={current_v!r} "
                    f"to current={self.current!r}. "
                    "Add a migration function to _MIGRATIONS in schema_registry.py."
                )
            result = migration_fn(result)

        return result

    def require_migration(self, record: dict[str, Any]) -> bool:
        """Return True if *record* needs migration to reach the current version."""
        version = record.get("schema_version")
        return bool(version) and version != self.current and version in _KNOWN_VERSIONS

    @staticmethod
    def version_history() -> list[str]:
        """Return the ordered version history, oldest to newest."""
        return list(_VERSION_HISTORY)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: SchemaRegistry | None = None


def get_registry() -> SchemaRegistry:
    global _registry
    if _registry is None:
        _registry = SchemaRegistry()
    return _registry
