"""scripts/intake/build_adapter_registry.py — selection logic.

The registry holds a list of BuildAdapter classes and offers:

    list_adapters()             → list[str] of human names
    list_build_system_ids()     → list[str] of id strings
    detect_all(workspace)       → every adapter that matched
    select(workspace)           → SelectionResult with the primary winner

Selection is deterministic:
    1. Drop adapters whose detect() did not match (matched=False).
    2. If zero match, fall back to UnknownAdapter — explicit, never silent.
    3. If one match, that's the primary.
    4. If multiple match, sort by (-priority, -confidence, build_system_id).
       The top entry is primary; multi_match=True flags the situation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from intake.build_adapters import (
    ADAPTERS_BUILTIN,
    BuildAdapter,
    DetectionResult,
    UnknownAdapter,
)


@dataclass
class SelectionResult:
    primary: type[BuildAdapter]
    matched: list[tuple[type[BuildAdapter], DetectionResult]] = field(default_factory=list)
    multi_match: bool = False
    note: str = ""


class BuildAdapterRegistry:
    def __init__(self, adapters: Sequence[type[BuildAdapter]] | None = None):
        self._adapters: list[type[BuildAdapter]] = list(
            adapters if adapters is not None else ADAPTERS_BUILTIN
        )

    # -- introspection ------------------------------------------------------

    def list_adapters(self) -> list[str]:
        return [a.name for a in self._adapters]

    def list_build_system_ids(self) -> list[str]:
        return [a.build_system_id for a in self._adapters]

    def get(self, build_system_id: str) -> type[BuildAdapter] | None:
        for a in self._adapters:
            if a.build_system_id == build_system_id:
                return a
        return None

    # -- detection / selection ---------------------------------------------

    def detect_all(self, workspace: Path) -> list[tuple[type[BuildAdapter], DetectionResult]]:
        out: list[tuple[type[BuildAdapter], DetectionResult]] = []
        for a in self._adapters:
            # Skip the Unknown fallback in detection — it's never a "match",
            # the select() path constructs it explicitly.
            if a is UnknownAdapter:
                continue
            try:
                r = a.detect(workspace)
            except Exception:  # noqa: BLE001 — never let detect crash select
                continue
            if r.matched and r.confidence > 0:
                out.append((a, r))
        return out

    def select(self, workspace: Path) -> SelectionResult:
        matches = self.detect_all(workspace)

        if not matches:
            return SelectionResult(
                primary=UnknownAdapter,
                matched=[
                    (
                        UnknownAdapter,
                        DetectionResult(
                            matched=False,
                            confidence=0.0,
                            notes="no build manifest detected",
                        ),
                    )
                ],
                multi_match=False,
                note="no build manifest detected; UnknownAdapter selected",
            )

        if len(matches) == 1:
            return SelectionResult(
                primary=matches[0][0],
                matched=matches,
                multi_match=False,
            )

        # Multi-match: deterministic tie-break.
        sorted_matches = sorted(
            matches,
            key=lambda x: (-x[0].priority, -x[1].confidence, x[0].build_system_id),
        )
        return SelectionResult(
            primary=sorted_matches[0][0],
            matched=sorted_matches,
            multi_match=True,
            note=("multi-match: " + ", ".join(a.build_system_id for a, _ in sorted_matches)),
        )


# ---------------------------------------------------------------------------
# Module-level default registry. Tests construct their own when isolation
# matters; production callers (codebase_explorer.detect_build_system) use
# this one.
# ---------------------------------------------------------------------------

_DEFAULT_REGISTRY = BuildAdapterRegistry()


def default_registry() -> BuildAdapterRegistry:
    return _DEFAULT_REGISTRY
