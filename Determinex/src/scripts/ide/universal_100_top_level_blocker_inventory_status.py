"""Universal 100 Top-Level Blocker Inventory status loader.

DETERMINEX_REACT_UNIVERSAL_100_TOP_LEVEL_BLOCKER_INVENTORY_BINDING_LOCK_001.

load() reads Codex's blocker-inventory evidence and returns a render-safe
view-model the React panel can display. The inventory classifies every
known blocker by category, family, sector, local resolvability, the safe
next rung that may attempt to close it, and the forbidden shortcut that
would falsely promote it.

The panel DISPLAYS evidence; it does NOT grant authority. Inventory
classifies blockers and routes to safe next rungs; it does NOT promote
any cell, grant capability, or weaken any forbidden shortcut.

Hard rules enforced by load():

  * status != UNIVERSAL_100_TOP_LEVEL_BLOCKER_INVENTORY_PASSED ->
    BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * blockers list absent / empty when blocker_count > 0 ->
    BLOCKED_MALFORMED
  * blocker entry missing required key (blocker_id / category /
    family / sector_id / local_resolvability / safe_next_rung /
    forbidden_shortcut) -> BLOCKED_MALFORMED
  * category_counts / local_resolvability_counts absent ->
    BLOCKED_MALFORMED
  * forbidden broad-claim phrase outside refusal context ->
    BLOCKED_BROAD_CLAIM
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from .universal_100_matrix_probe_batch_status import (  # noqa: E402
    _walk_strings_for_forbidden,
)

_REPO_ROOT = _HERE.parent.parent.parent
_EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "universal_100_top_level_blocker_inventory"
EXPECTED_STATUS = "UNIVERSAL_100_TOP_LEVEL_BLOCKER_INVENTORY_PASSED"
LOCK_ID = "DETERMINEX_UNIVERSAL_100_TOP_LEVEL_BLOCKER_INVENTORY_LOCK_001"

DECISION_PREFIX = "REACT_UNIVERSAL_100_TOP_LEVEL_BLOCKER_INVENTORY_BINDING"


def _token(suffix: str) -> str:
    return f"{DECISION_PREFIX}_{suffix}"


REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Inventory classifies blockers and safe next rungs only.",
    "Inventory does not promote support or grant capability.",
    "Forbidden shortcuts remain forbidden.",
    "Operator-action and provider-gate blockers remain operator-gated.",
    "Local resolvability does not mean automatic closure.",
    "Universal 100 means routing/accounting, not universal execution.",
)


_BLOCKER_REQUIRED_KEYS = (
    "blocker_id",
    "category",
    "family",
    "sector_id",
    "local_resolvability",
    "safe_next_rung",
    "forbidden_shortcut",
)


@dataclass(frozen=True)
class BlockerRow:
    blocker_id: str
    category: str
    family: str
    sector_id: str
    affected_cells: tuple[str, ...]
    local_resolvability: str
    safe_next_rung: str
    forbidden_shortcut: str
    can_be_attempted_in_this_wave: bool


@dataclass(frozen=True)
class Universal100TopLevelBlockerInventoryStatus:
    decision: str
    target_surface: str
    target_workflow: str
    lock_id: str
    blocker_count: int
    blockers: tuple[BlockerRow, ...]
    category_counts: dict[str, int]
    local_resolvability_counts: dict[str, int]
    source_mutation_authorized: bool
    real_user_source_mutation_authorized: bool
    approval_authority_granted: bool
    proof_execution_authority_granted: bool
    training_eligible: bool
    training_rows_written: bool
    release_ready: bool
    broad_claims_granted: bool
    artifact_import_authorized: bool
    benchmark_execution_authorized: bool
    programbench_execution_authorized: bool
    release_deploy_workflow_created: bool
    claim_boundary: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    source_records: tuple[str, ...]
    evidence_ref: str
    captions: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["blockers"] = [asdict(b) for b in self.blockers]
        for k in ("claim_boundary", "forbidden_claims", "source_records", "captions", "notes"):
            d[k] = list(getattr(self, k))
        return d

    @property
    def is_passed(self) -> bool:
        return self.decision.endswith("_BINDING_PASSED")

    @property
    def is_awaiting(self) -> bool:
        return self.decision.endswith("_BINDING_AWAITING_EVIDENCE")

    @property
    def is_blocked(self) -> bool:
        return "_BINDING_BLOCKED_" in self.decision


def _locate_latest_evidence(evidence_dir: Path) -> Path | None:
    if not evidence_dir.is_dir():
        return None
    candidates = sorted(evidence_dir.glob("run_*.json"))
    return candidates[-1] if candidates else None


def _blocker_row(b: dict) -> BlockerRow:
    return BlockerRow(
        blocker_id=str(b.get("blocker_id") or ""),
        category=str(b.get("category") or ""),
        family=str(b.get("family") or ""),
        sector_id=str(b.get("sector_id") or ""),
        affected_cells=tuple(str(c) for c in (b.get("affected_cells") or [])),
        local_resolvability=str(b.get("local_resolvability") or ""),
        safe_next_rung=str(b.get("safe_next_rung") or ""),
        forbidden_shortcut=str(b.get("forbidden_shortcut") or ""),
        can_be_attempted_in_this_wave=bool(b.get("can_be_attempted_in_this_wave", False)),
    )


def _shell(*, decision: str, note: str) -> Universal100TopLevelBlockerInventoryStatus:
    return Universal100TopLevelBlockerInventoryStatus(
        decision=decision,
        target_surface="Universal 100 Top-Level Blocker Inventory",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        lock_id=LOCK_ID,
        blocker_count=0,
        blockers=(),
        category_counts={},
        local_resolvability_counts={},
        source_mutation_authorized=False,
        real_user_source_mutation_authorized=False,
        approval_authority_granted=False,
        proof_execution_authority_granted=False,
        training_eligible=False,
        training_rows_written=False,
        release_ready=False,
        broad_claims_granted=False,
        artifact_import_authorized=False,
        benchmark_execution_authorized=False,
        programbench_execution_authorized=False,
        release_deploy_workflow_created=False,
        claim_boundary=(),
        forbidden_claims=(),
        source_records=(),
        evidence_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(note,),
    )


def _awaiting(note: str) -> Universal100TopLevelBlockerInventoryStatus:
    return _shell(decision=_token("AWAITING_EVIDENCE"), note=note)


def _block(decision: str, note: str) -> Universal100TopLevelBlockerInventoryStatus:
    return _shell(decision=decision, note=note)


def load(
    evidence_dir: Path | str | None = None,
) -> Universal100TopLevelBlockerInventoryStatus:
    ed = Path(evidence_dir) if evidence_dir else _EVIDENCE_DIR
    chosen = _locate_latest_evidence(ed)
    if chosen is None:
        return _awaiting(f"no evidence file under {ed}")
    try:
        blob = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not read evidence: {exc}")

    if blob.get("status") != EXPECTED_STATUS:
        return _block(
            _token("BLOCKED_MALFORMED"),
            f"evidence status={blob.get('status')!r} (expected {EXPECTED_STATUS})",
        )

    auth = blob.get("authority") or {}

    def _auth(flag: str) -> bool:
        return bool(blob.get(flag) is True or auth.get(flag) is True)

    for flag in (
        "source_mutation_authorized",
        "real_user_source_mutation_authorized",
        "training_eligible",
        "training_rows_written",
        "approval_authority_granted",
        "release_ready",
        "proof_execution_authority_granted",
        "release_deploy_workflow_created",
        "artifact_import_authorized",
        "benchmark_execution_authorized",
        "programbench_execution_authorized",
    ):
        if _auth(flag):
            return _block(
                _token("BLOCKED_AUTHORITY_CONFUSION"),
                f"authority flag {flag} is true",
            )
    if _auth("broad_claims_granted"):
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            "broad_claims_granted is true",
        )

    blocker_count = int(blob.get("blocker_count", 0))
    blockers_raw = blob.get("blockers")
    if not isinstance(blockers_raw, list):
        return _block(
            _token("BLOCKED_MALFORMED"),
            "blockers list absent",
        )
    if blocker_count > 0 and not blockers_raw:
        return _block(
            _token("BLOCKED_MALFORMED"),
            f"blocker_count={blocker_count} but blockers list empty",
        )

    for i, b in enumerate(blockers_raw):
        if not isinstance(b, dict):
            return _block(
                _token("BLOCKED_MALFORMED"),
                f"blocker index {i} is not a dict",
            )
        for k in _BLOCKER_REQUIRED_KEYS:
            if not b.get(k):
                return _block(
                    _token("BLOCKED_MALFORMED"),
                    f"blocker index {i} missing key {k!r}",
                )

    category_counts_raw = blob.get("category_counts")
    if not isinstance(category_counts_raw, dict):
        return _block(
            _token("BLOCKED_MALFORMED"),
            "category_counts absent",
        )
    local_resolvability_counts_raw = blob.get("local_resolvability_counts")
    if not isinstance(local_resolvability_counts_raw, dict):
        return _block(
            _token("BLOCKED_MALFORMED"),
            "local_resolvability_counts absent",
        )

    hits: set[str] = set()
    _walk_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            f"forbidden broad-claim phrases: {sorted(hits)}",
        )

    blockers = tuple(_blocker_row(b) for b in blockers_raw)

    return Universal100TopLevelBlockerInventoryStatus(
        decision=_token("PASSED"),
        target_surface="Universal 100 Top-Level Blocker Inventory",
        target_workflow=str(
            blob.get("target_workflow") or "universal 100 top-level blocker inventory"
        ),
        lock_id=LOCK_ID,
        blocker_count=blocker_count,
        blockers=blockers,
        category_counts={str(k): int(v) for k, v in category_counts_raw.items()},
        local_resolvability_counts={
            str(k): int(v) for k, v in local_resolvability_counts_raw.items()
        },
        source_mutation_authorized=False,
        real_user_source_mutation_authorized=False,
        approval_authority_granted=False,
        proof_execution_authority_granted=False,
        training_eligible=False,
        training_rows_written=False,
        release_ready=False,
        broad_claims_granted=False,
        artifact_import_authorized=False,
        benchmark_execution_authorized=False,
        programbench_execution_authorized=False,
        release_deploy_workflow_created=False,
        claim_boundary=tuple(str(x) for x in (blob.get("claim_boundary") or [])),
        forbidden_claims=tuple(str(x) for x in (blob.get("forbidden_claims") or [])),
        source_records=tuple(str(s) for s in (blob.get("source_records") or [])),
        evidence_ref=_relative_to_repo(chosen),
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(),
    )


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


REACT_UNIVERSAL_100_TOP_LEVEL_BLOCKER_INVENTORY_BINDING_STATUS_TOKENS = tuple(
    _token(suffix)
    for suffix in (
        "PASSED",
        "AWAITING_EVIDENCE",
        "BLOCKED_MALFORMED",
        "BLOCKED_AUTHORITY_CONFUSION",
        "BLOCKED_BROAD_CLAIM",
    )
)


__all__ = [
    "load",
    "BlockerRow",
    "Universal100TopLevelBlockerInventoryStatus",
    "REQUIRED_PANEL_CAPTIONS",
    "EXPECTED_STATUS",
    "LOCK_ID",
    "REACT_UNIVERSAL_100_TOP_LEVEL_BLOCKER_INVENTORY_BINDING_STATUS_TOKENS",
]
