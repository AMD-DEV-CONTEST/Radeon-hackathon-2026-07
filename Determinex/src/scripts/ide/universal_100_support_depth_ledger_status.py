"""Universal 100 Support Depth Ledger status loader.

DETERMINEX_REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_LOCK_001.

The support-depth ledger is **accounting**, not promotion. The React
binding displays totals and breakdowns Codex computed across known
cells, but it does NOT convert accounting into capability claims.

Hard rules enforced by load():

  * status != UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_PASSED -> BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * summary.total_known_cells missing -> BLOCKED_MALFORMED
  * support_depth_counts missing or empty -> BLOCKED_MALFORMED
  * support_depth_counts.release_supported > 0 without release-proof
    source path -> BLOCKED_RELEASE_OVERCLAIM
  * support_depth_counts.user_ready_with_caveats > 0 without
    user-ready-proof source path -> BLOCKED_USER_READY_OVERCLAIM
  * forbidden broad-claim phrase as current claim -> BLOCKED_BROAD_CLAIM
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
    _has_release_proof_reference,
    _walk_strings_for_forbidden,
)

_REPO_ROOT = _HERE.parent.parent.parent

_DEFAULT_EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "universal_100_support_depth_ledger"

EXPECTED_STATUS = "UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_PASSED"

REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Support-depth ledger is accounting, not promotion.",
    '"Accounted for" does not mean "supported."',
    '"Smoke-supported" does not mean "production-ready."',
    '"Fixture-local" does not mean "real user repo authorized."',
    '"User-ready" remains false unless Codex evidence explicitly proves it.',
    '"Release-supported" remains false unless packaging/fresh-install/release gates explicitly prove it.',
    '"Missing rung named" is progress, not support.',
    "Universal 100 means universal intake/routing, not magic execution.",
    "Blocked cells are visible by exact missing rung.",
)


REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_STATUS_TOKENS = (
    "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_PASSED",
    "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_AWAITING_EVIDENCE",
    "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_BLOCKED_MALFORMED",
    "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_BLOCKED_AUTHORITY_CONFUSION",
    "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_BLOCKED_BROAD_CLAIM",
    "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_BLOCKED_RELEASE_OVERCLAIM",
    "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_BLOCKED_USER_READY_OVERCLAIM",
)


@dataclass(frozen=True)
class SupportDepthLedgerStatus:
    decision: str
    target_surface: str
    target_workflow: str
    total_known_cells: int
    fixture_local_smoke_supported: int
    test_supported: int
    repair_supported: int
    maintain_supported: int
    teach_supported: int
    user_ready_with_caveats: int
    release_supported: int
    routed_but_unsupported: int
    blocked_by_missing_rung: int
    forbidden_or_policy_blocked: int
    support_depth_counts: dict[str, int]
    claim_state_counts: dict[str, int]
    blocker_bucket_counts: dict[str, int]
    metadata_gap_counts: dict[str, int]
    counts_by_sector: dict[str, int]
    counts_by_language: dict[str, int]
    counts_by_app_class: dict[str, int]
    counts_by_platform: dict[str, int]
    counts_by_workflow: dict[str, int]
    counts_by_product_room: dict[str, int]
    support_depth_buckets: tuple[str, ...]
    blocker_buckets: tuple[str, ...]
    claim_boundary: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    strongest_truthful_claim: str
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
    evidence_ref: str
    captions: tuple[str, ...]
    current_next_rung: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        for k in (
            "support_depth_buckets",
            "blocker_buckets",
            "claim_boundary",
            "forbidden_claims",
            "captions",
            "notes",
        ):
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


def _str_int_map(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(k): int(v) for k, v in value.items() if isinstance(v, (int, float))}


def _per_group_totals(value: object) -> dict[str, int]:
    """Extract a per-group cell total from Codex's nested grouping shape.

    Codex emits dicts like {group_key: {total_cells, claim_state_counts, ...}}.
    We extract just the `total_cells` value per group so the panel can render
    a compact total without inventing source-of-truth detail.
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in value.items():
        if isinstance(v, dict) and isinstance(v.get("total_cells"), (int, float)):
            out[str(k)] = int(v["total_cells"])
        elif isinstance(v, (int, float)):
            out[str(k)] = int(v)
    return out


def _shell(*, decision: str, note: str) -> SupportDepthLedgerStatus:
    return SupportDepthLedgerStatus(
        decision=decision,
        target_surface="Universal 100 Support Depth Ledger",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        total_known_cells=0,
        fixture_local_smoke_supported=0,
        test_supported=0,
        repair_supported=0,
        maintain_supported=0,
        teach_supported=0,
        user_ready_with_caveats=0,
        release_supported=0,
        routed_but_unsupported=0,
        blocked_by_missing_rung=0,
        forbidden_or_policy_blocked=0,
        support_depth_counts={},
        claim_state_counts={},
        blocker_bucket_counts={},
        metadata_gap_counts={},
        counts_by_sector={},
        counts_by_language={},
        counts_by_app_class={},
        counts_by_platform={},
        counts_by_workflow={},
        counts_by_product_room={},
        support_depth_buckets=tuple(),
        blocker_buckets=tuple(),
        claim_boundary=tuple(),
        forbidden_claims=tuple(),
        strongest_truthful_claim="(awaiting)" if "AWAITING" in decision else "(blocked)",
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
        evidence_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        current_next_rung="",
        notes=(note,),
    )


def _awaiting(note: str) -> SupportDepthLedgerStatus:
    return _shell(
        decision="REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_AWAITING_EVIDENCE",
        note=note,
    )


def _block(decision: str, note: str) -> SupportDepthLedgerStatus:
    return _shell(decision=decision, note=note)


def _has_user_ready_proof_reference(blob: dict) -> bool:
    paths = blob.get("source_evidence_paths") or []
    for p in paths:
        s = str(p).lower()
        if "user_ready" in s or "user_ready_proof" in s or "user_ready_lock" in s:
            return True
    return False


def _count_from(target: dict, *keys: str) -> int:
    for k in keys:
        v = target.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def load(evidence_dir: Path | str | None = None) -> SupportDepthLedgerStatus:
    ed = Path(evidence_dir) if evidence_dir else _DEFAULT_EVIDENCE_DIR
    chosen = _locate_latest_evidence(ed)
    if chosen is None:
        return _awaiting(f"no evidence file under {ed}")
    try:
        blob = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not read evidence: {exc}")

    if blob.get("status") != EXPECTED_STATUS:
        return _block(
            "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_BLOCKED_MALFORMED",
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
                "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_BLOCKED_AUTHORITY_CONFUSION",
                f"authority flag {flag} is true",
            )
    if _auth("broad_claims_granted"):
        return _block(
            "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_BLOCKED_BROAD_CLAIM",
            "broad_claims_granted is true",
        )

    summary = blob.get("summary") or {}
    if "total_known_cells" not in summary:
        return _block(
            "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_BLOCKED_MALFORMED",
            "summary.total_known_cells missing",
        )

    support_depth_counts = _str_int_map(summary.get("support_depth_counts"))
    if not support_depth_counts:
        return _block(
            "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_BLOCKED_MALFORMED",
            "summary.support_depth_counts missing or empty",
        )

    release_supported = int(support_depth_counts.get("release_supported", 0))
    if release_supported > 0 and not _has_release_proof_reference(blob):
        return _block(
            "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_BLOCKED_RELEASE_OVERCLAIM",
            f"support_depth_counts.release_supported={release_supported} without release-proof source path",
        )

    user_ready = int(support_depth_counts.get("user_ready_with_caveats", 0))
    if user_ready > 0 and not _has_user_ready_proof_reference(blob):
        return _block(
            "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_BLOCKED_USER_READY_OVERCLAIM",
            f"support_depth_counts.user_ready_with_caveats={user_ready} without user-ready-proof source path",
        )

    hits: set[str] = set()
    _walk_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_BLOCKED_BROAD_CLAIM",
            f"forbidden broad-claim phrases as current claim: {sorted(hits)}",
        )

    return SupportDepthLedgerStatus(
        decision="REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_PASSED",
        target_surface="Universal 100 Support Depth Ledger",
        target_workflow="support depth ledger (accounting only)",
        total_known_cells=int(summary.get("total_known_cells", 0)),
        fixture_local_smoke_supported=int(summary.get("fixture_local_smoke_supported", 0)),
        test_supported=int(support_depth_counts.get("test_supported", 0)),
        repair_supported=int(support_depth_counts.get("repair_supported", 0)),
        maintain_supported=int(support_depth_counts.get("maintain_supported", 0)),
        teach_supported=int(support_depth_counts.get("teach_supported", 0)),
        user_ready_with_caveats=user_ready,
        release_supported=release_supported,
        routed_but_unsupported=int(summary.get("routed_but_unsupported", 0)),
        blocked_by_missing_rung=int(summary.get("blocked_by_missing_rung", 0)),
        forbidden_or_policy_blocked=int(summary.get("forbidden_or_policy_blocked", 0)),
        support_depth_counts=support_depth_counts,
        claim_state_counts=_str_int_map(summary.get("claim_state_counts")),
        blocker_bucket_counts=_str_int_map(summary.get("blocker_bucket_counts")),
        metadata_gap_counts=_str_int_map(summary.get("metadata_gap_counts")),
        counts_by_sector=_per_group_totals(blob.get("support_depth_counts_by_sector")),
        counts_by_language=_per_group_totals(blob.get("support_depth_counts_by_language")),
        counts_by_app_class=_per_group_totals(blob.get("support_depth_counts_by_app_class")),
        counts_by_platform=_per_group_totals(blob.get("support_depth_counts_by_platform")),
        counts_by_workflow=_per_group_totals(blob.get("support_depth_counts_by_workflow")),
        counts_by_product_room=_per_group_totals(blob.get("support_depth_counts_by_product_room")),
        support_depth_buckets=tuple(str(x) for x in (blob.get("support_depth_buckets") or [])),
        blocker_buckets=tuple(str(x) for x in (blob.get("blocker_buckets") or [])),
        claim_boundary=tuple(str(x) for x in (blob.get("claim_boundary") or [])),
        forbidden_claims=tuple(str(x) for x in (blob.get("forbidden_claims") or [])),
        strongest_truthful_claim=str(blob.get("strongest_truthful_claim") or ""),
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
        evidence_ref=_relative_to_repo(chosen),
        captions=REQUIRED_PANEL_CAPTIONS,
        current_next_rung=str(blob.get("next_recommended_rung") or ""),
        notes=(),
    )


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


__all__ = [
    "load",
    "REACT_UNIVERSAL_100_SUPPORT_DEPTH_LEDGER_BINDING_STATUS_TOKENS",
    "REQUIRED_PANEL_CAPTIONS",
    "SupportDepthLedgerStatus",
]
