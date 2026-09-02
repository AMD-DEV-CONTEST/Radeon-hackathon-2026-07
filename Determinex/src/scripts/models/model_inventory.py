"""Local model inventory abstraction for the model router.

The inventory is a passive, fixture-injectable view of which model
identifiers are *currently available* on this host. It deliberately
performs **no subprocess calls and no network I/O**:

  * Live-probing Ollama (``ollama list``) is intentionally out of scope.
    A future rung (``MODEL_ROUTER_LIVE_LOCAL_MODEL_ADMISSION_LOCK_001``)
    may add an opt-in probe routed through ``intake.hardened_runner``.
  * For the router lock, "available" means: the id appears in the static
    config spine (``determinex_settings`` defaults) or in the
    ``DETERMINEX_ROUTER_AVAILABLE_MODELS`` env var (comma-separated list),
    or in an explicit ``available_ids`` argument (used by tests).

Failure mode: an empty inventory is a legitimate state — the router
treats it as "no local model available" and falls back along its chain.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field


def _split_env(name: str) -> set[str]:
    raw = os.environ.get(name, "") or ""
    return {chunk.strip() for chunk in raw.split(",") if chunk.strip()}


@dataclass(frozen=True)
class LocalModelInventory:
    """Static, fixture-injectable view of locally-available model ids.

    Use ``LocalModelInventory.from_env()`` for a config-derived view, or
    pass ``available_ids=`` directly for tests.
    """

    available_ids: frozenset[str] = field(default_factory=frozenset)
    source: str = "explicit"

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def empty(cls) -> LocalModelInventory:
        return cls(available_ids=frozenset(), source="empty")

    @classmethod
    def of(cls, ids: Iterable[str]) -> LocalModelInventory:
        cleaned = {x.strip() for x in ids if x and x.strip()}
        return cls(available_ids=frozenset(cleaned), source="explicit")

    @classmethod
    def from_env(cls) -> LocalModelInventory:
        """Build an inventory from the env-var spine.

        Reads:
          * DETERMINEX_BUILDER_MODEL / DETERMINEX_OBSERVER_MODEL /
            DETERMINEX_ARCHITECT_MODEL — the three currently-configured ids
          * DETERMINEX_ROUTER_AVAILABLE_MODELS — explicit extra list

        Never reads from the network. Never invokes a subprocess.
        """
        from_spine: set[str] = set()
        for env_name, default in (
            ("DETERMINEX_BUILDER_MODEL", "determinex-engineer-v11-dsl"),
            ("DETERMINEX_OBSERVER_MODEL", "determinex-observer-v6-dsl"),
            ("DETERMINEX_ARCHITECT_MODEL", "determinex-sentinel-v5-dsl"),
        ):
            v = os.environ.get(env_name, default) or ""
            if v.strip():
                from_spine.add(v.strip())

        extra = _split_env("DETERMINEX_ROUTER_AVAILABLE_MODELS")
        merged = from_spine | extra
        return cls(available_ids=frozenset(merged), source="env")

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_available(self, model_id: str) -> bool:
        return bool(model_id) and (model_id in self.available_ids)

    def __contains__(self, model_id: object) -> bool:
        return isinstance(model_id, str) and self.is_available(model_id)

    def __bool__(self) -> bool:
        return bool(self.available_ids)
