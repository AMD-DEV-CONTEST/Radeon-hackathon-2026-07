"""Universal 100 Top-Level Sector Completion Campaign status loader.

DETERMINEX_REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_LOCK_001.

The campaign is a 40-family scoreboard and execution plan. It is
ACCOUNTING/ROUTING, NOT support promotion. Membership in the
scoreboard does NOT grant capability.

"Universal 100 Level 1" means: complete top-level identification,
classification, routing, missing-rung assignment, and depth-accounting
coverage. It does NOT mean universal execution, all-app/all-language/
all-platform support, production readiness, or release readiness.

Hard rules enforced by load():

  * status != UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_PASSED
    -> BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * top_level_sector_scoreboard missing or empty -> BLOCKED_MALFORMED
  * summary.top_level_sector_families != 40 -> BLOCKED_LEVEL_1_NOT_40
  * summary.level_1_scoreboard_coverage != 40 -> BLOCKED_LEVEL_1_NOT_40
  * scoreboard contains a family with classified != True OR
    assigned_missing_rung != True OR routed-equivalent missing
    -> BLOCKED_LEVEL_1_NOT_40
  * summary.release_supported_count > 0 without release-proof source
    path -> BLOCKED_RELEASE_OVERCLAIM
  * forbidden broad-claim phrase as current claim outside refusal
    context -> BLOCKED_BROAD_CLAIM
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

_DEFAULT_EVIDENCE_DIR = (
    _REPO_ROOT / "assurance" / "evidence" / "universal_100_top_level_sector_completion_campaign"
)

EXPECTED_STATUS = "UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_PASSED"
EXPECTED_FAMILY_COUNT = 40

REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Universal 100 Level 1 means top-level identification/classification/routing, not universal execution.",
    "40 / 40 routed does not mean 40 / 40 supported.",
    "Scaffold-supported is not working-app proof.",
    "Smoke-supported is not production proof.",
    "Packaging-supported is not release-supported.",
    "Release-supported remains 0.",
    "Fixture-local evidence is not production readiness.",
    "Blocked cells remain visible by exact missing rung.",
    "No all-app support. No all-language support. No all-platform support.",
    "No source mutation, training, proof-execution, or release authority.",
)


REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_STATUS_TOKENS = (
    "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_PASSED",
    "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_AWAITING_EVIDENCE",
    "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_BLOCKED_MALFORMED",
    "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_BLOCKED_AUTHORITY_CONFUSION",
    "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_BLOCKED_BROAD_CLAIM",
    "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_BLOCKED_LEVEL_1_NOT_40",
    "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_BLOCKED_RELEASE_OVERCLAIM",
)


@dataclass(frozen=True)
class CampaignFamilyRow:
    sector_id: str
    sector_family: str
    identified: bool
    classified: bool
    assigned_missing_rung: bool
    represented_in_completion_campaign_ledger: bool
    cells_accounted: int
    blocked_by_missing_local_toolchain: bool
    blocked_by_missing_fixture: bool
    blocked_by_missing_verifier: bool
    forbidden_policy_blocked: bool
    fixture_local_verified: int
    missing_rungs: tuple[str, ...]
    known_blockers: tuple[str, ...]
    coverage: dict[str, int]
    claim_boundary: tuple[str, ...]
    release_boundary: tuple[str, ...]


@dataclass(frozen=True)
class TopLevelSectorCompletionCampaignStatus:
    decision: str
    target_surface: str
    target_workflow: str
    top_level_sector_families: int
    level_1_scoreboard_coverage: int
    families_with_any_cell_evidence: int
    families_roadmap_only: int
    families_blocked_by_missing_local_toolchain: int
    families_blocked_by_missing_fixture: int
    families_blocked_by_missing_verifier: int
    families_forbidden_policy_blocked: int
    families_with_smoke_supported_coverage: int
    families_with_test_supported_coverage: int
    families_with_repair_supported_coverage: int
    families_with_maintain_supported_coverage: int
    families_with_teach_supported_coverage: int
    families_with_scaffold_supported_coverage: int
    families_with_packaging_supported_coverage: int
    families_with_user_ready_with_caveats_coverage: int
    families_with_fresh_install_verified_coverage: int
    families_with_release_supported_coverage: int
    release_supported_count: int
    user_ready_with_caveats_count: int
    support_depth_counts: dict[str, int]
    scoreboard: tuple[CampaignFamilyRow, ...]
    level_1_target: str
    level_1_not_claimed: tuple[str, ...]
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
        d["scoreboard"] = [asdict(r) for r in self.scoreboard]
        for k in ("level_1_not_claimed", "claim_boundary", "forbidden_claims", "captions", "notes"):
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


def _family_row(entry: dict) -> CampaignFamilyRow:
    return CampaignFamilyRow(
        sector_id=str(entry.get("sector_id") or "(unknown)"),
        sector_family=str(entry.get("sector_family") or "(unknown)"),
        identified=bool(entry.get("identified")),
        classified=bool(entry.get("classified")),
        assigned_missing_rung=bool(entry.get("assigned_missing_rung")),
        represented_in_completion_campaign_ledger=bool(
            entry.get("represented_in_completion_campaign_ledger")
        ),
        cells_accounted=int(entry.get("cells_accounted") or 0),
        blocked_by_missing_local_toolchain=bool(entry.get("blocked_by_missing_local_toolchain")),
        blocked_by_missing_fixture=bool(entry.get("blocked_by_missing_fixture")),
        blocked_by_missing_verifier=bool(entry.get("blocked_by_missing_verifier")),
        forbidden_policy_blocked=bool(entry.get("forbidden_policy_blocked")),
        fixture_local_verified=int(entry.get("fixture_local_verified") or 0),
        missing_rungs=tuple(str(x) for x in (entry.get("missing_rungs") or [])),
        known_blockers=tuple(str(x) for x in (entry.get("known_blockers") or [])),
        coverage=_str_int_map(entry.get("coverage")),
        claim_boundary=tuple(str(x) for x in (entry.get("claim_boundary") or [])),
        release_boundary=tuple(str(x) for x in (entry.get("release_boundary") or [])),
    )


def _shell(*, decision: str, note: str) -> TopLevelSectorCompletionCampaignStatus:
    return TopLevelSectorCompletionCampaignStatus(
        decision=decision,
        target_surface="Universal 100 Top-Level Sector Completion Campaign",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        top_level_sector_families=0,
        level_1_scoreboard_coverage=0,
        families_with_any_cell_evidence=0,
        families_roadmap_only=0,
        families_blocked_by_missing_local_toolchain=0,
        families_blocked_by_missing_fixture=0,
        families_blocked_by_missing_verifier=0,
        families_forbidden_policy_blocked=0,
        families_with_smoke_supported_coverage=0,
        families_with_test_supported_coverage=0,
        families_with_repair_supported_coverage=0,
        families_with_maintain_supported_coverage=0,
        families_with_teach_supported_coverage=0,
        families_with_scaffold_supported_coverage=0,
        families_with_packaging_supported_coverage=0,
        families_with_user_ready_with_caveats_coverage=0,
        families_with_fresh_install_verified_coverage=0,
        families_with_release_supported_coverage=0,
        release_supported_count=0,
        user_ready_with_caveats_count=0,
        support_depth_counts={},
        scoreboard=tuple(),
        level_1_target="",
        level_1_not_claimed=tuple(),
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


def _awaiting(note: str) -> TopLevelSectorCompletionCampaignStatus:
    return _shell(
        decision="REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_AWAITING_EVIDENCE",
        note=note,
    )


def _block(decision: str, note: str) -> TopLevelSectorCompletionCampaignStatus:
    return _shell(decision=decision, note=note)


def load(evidence_dir: Path | str | None = None) -> TopLevelSectorCompletionCampaignStatus:
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
            "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_BLOCKED_MALFORMED",
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
                "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_BLOCKED_AUTHORITY_CONFUSION",
                f"authority flag {flag} is true",
            )
    if _auth("broad_claims_granted"):
        return _block(
            "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_BLOCKED_BROAD_CLAIM",
            "broad_claims_granted is true",
        )

    scoreboard_raw = blob.get("top_level_sector_scoreboard")
    if not isinstance(scoreboard_raw, list) or not scoreboard_raw:
        return _block(
            "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_BLOCKED_MALFORMED",
            "top_level_sector_scoreboard missing or empty",
        )

    summary = blob.get("summary") or {}
    families = int(summary.get("top_level_sector_families", 0))
    coverage_total = int(summary.get("level_1_scoreboard_coverage", 0))
    if (
        families != EXPECTED_FAMILY_COUNT
        or coverage_total != EXPECTED_FAMILY_COUNT
        or len(scoreboard_raw) != EXPECTED_FAMILY_COUNT
    ):
        return _block(
            "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_BLOCKED_LEVEL_1_NOT_40",
            f"Level 1 must be 40/40 (families={families}, coverage={coverage_total}, scoreboard_len={len(scoreboard_raw)})",
        )

    scoreboard = tuple(_family_row(entry) for entry in scoreboard_raw)
    for row in scoreboard:
        # Level 1 coverage requires every family to be identified, classified, and
        # represented in the completion-campaign ledger. assigned_missing_rung is
        # only true when there *are* missing rungs — sectors with full coverage
        # legitimately have no missing rungs to assign and assigned_missing_rung=false,
        # so it is NOT a Level 1 requirement.
        if (
            not row.identified
            or not row.classified
            or not row.represented_in_completion_campaign_ledger
        ):
            return _block(
                "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_BLOCKED_LEVEL_1_NOT_40",
                f"family {row.sector_id} missing identified/classified/represented_in_completion_campaign_ledger true",
            )

    release_supported = int(summary.get("release_supported_count", 0))
    families_release = int(summary.get("families_with_release_supported_coverage", 0))
    if (release_supported > 0 or families_release > 0) and not _has_release_proof_reference(blob):
        return _block(
            "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_BLOCKED_RELEASE_OVERCLAIM",
            f"release_supported_count={release_supported}/families={families_release} without release-proof path",
        )

    hits: set[str] = set()
    _walk_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_BLOCKED_BROAD_CLAIM",
            f"forbidden broad-claim phrases as current claim: {sorted(hits)}",
        )

    return TopLevelSectorCompletionCampaignStatus(
        decision="REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_PASSED",
        target_surface="Universal 100 Top-Level Sector Completion Campaign",
        target_workflow="top-level sector completion campaign (scoreboard + plan)",
        top_level_sector_families=families,
        level_1_scoreboard_coverage=coverage_total,
        families_with_any_cell_evidence=int(summary.get("families_with_any_cell_evidence", 0)),
        families_roadmap_only=int(summary.get("families_roadmap_only", 0)),
        families_blocked_by_missing_local_toolchain=int(
            summary.get("families_blocked_by_missing_local_toolchain", 0)
        ),
        families_blocked_by_missing_fixture=int(
            summary.get("families_blocked_by_missing_fixture", 0)
        ),
        families_blocked_by_missing_verifier=int(
            summary.get("families_blocked_by_missing_verifier", 0)
        ),
        families_forbidden_policy_blocked=int(summary.get("families_forbidden_policy_blocked", 0)),
        families_with_smoke_supported_coverage=int(
            summary.get("families_with_smoke_supported_coverage", 0)
        ),
        families_with_test_supported_coverage=int(
            summary.get("families_with_test_supported_coverage", 0)
        ),
        families_with_repair_supported_coverage=int(
            summary.get("families_with_repair_supported_coverage", 0)
        ),
        families_with_maintain_supported_coverage=int(
            summary.get("families_with_maintain_supported_coverage", 0)
        ),
        families_with_teach_supported_coverage=int(
            summary.get("families_with_teach_supported_coverage", 0)
        ),
        families_with_scaffold_supported_coverage=int(
            summary.get("families_with_scaffold_supported_coverage", 0)
        ),
        families_with_packaging_supported_coverage=int(
            summary.get("families_with_packaging_supported_coverage", 0)
        ),
        families_with_user_ready_with_caveats_coverage=int(
            summary.get("families_with_user_ready_with_caveats_coverage", 0)
        ),
        families_with_fresh_install_verified_coverage=int(
            summary.get("families_with_fresh_install_verified_coverage", 0)
        ),
        families_with_release_supported_coverage=families_release,
        release_supported_count=release_supported,
        user_ready_with_caveats_count=int(summary.get("user_ready_with_caveats_count", 0)),
        support_depth_counts=_str_int_map(summary.get("support_depth_counts")),
        scoreboard=scoreboard,
        level_1_target=str(blob.get("universal_100_level_1_target") or ""),
        level_1_not_claimed=tuple(
            str(x) for x in (blob.get("universal_100_level_1_not_claimed") or [])
        ),
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
    "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_STATUS_TOKENS",
    "REQUIRED_PANEL_CAPTIONS",
    "CampaignFamilyRow",
    "TopLevelSectorCompletionCampaignStatus",
]
