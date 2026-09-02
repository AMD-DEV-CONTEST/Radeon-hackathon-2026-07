"""Universal 100 Sector State and Ingestion Ladder status loader.

DETERMINEX_REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_LOCK_001.

load() reads the Codex sector state ladder evidence and returns a
render-safe view-model the React Sector State Ladder panel can display.

The panel DISPLAYS the lifecycle ladder + sector registry; it does NOT
grant authority and does NOT advance any sector beyond Codex's recorded
state. No field implies source mutation, approval, proof-execution,
training, release readiness, or universal app/language/platform support.

Hard rules enforced by load():

  * status != UNIVERSAL_100_SECTOR_STATE_AND_INGESTION_LADDER_PASSED ->
    BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * forbidden broad-claim phrase as current claim outside refusal
    context -> BLOCKED_BROAD_CLAIM
  * sector_registry missing or empty -> BLOCKED_MALFORMED
  * support_lifecycle_states missing required start (DISCOVERED) or
    end (FULLY_SUPPORTED_WITH_CAVEATS) -> BLOCKED_MALFORMED
  * any sector that names a release_supported promotion_target without
    naming packaging/fresh-install evidence -> BLOCKED_RELEASE_OVERCLAIM
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

_DEFAULT_EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "universal_100_sector_state_ladder"

EXPECTED_STATUS = "UNIVERSAL_100_SECTOR_STATE_AND_INGESTION_LADDER_PASSED"

REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Fixture-local proof is not production readiness.",
    "Smoke-supported is not release-supported.",
    "Fully supported with caveats is not release-supported.",
    "No source mutation without authority.",
    "No working-app claim without build/test/smoke evidence.",
    "Universal 100 means universal intake/routing, not magic execution.",
    "Blocked cells are visible by exact missing rung.",
)


REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_STATUS_TOKENS = (
    "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_PASSED",
    "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_AWAITING_EVIDENCE",
    "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_BLOCKED_MALFORMED",
    "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_BLOCKED_AUTHORITY_CONFUSION",
    "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_BLOCKED_BROAD_CLAIM",
    "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_BLOCKED_RELEASE_OVERCLAIM",
)


@dataclass(frozen=True)
class SectorRow:
    sector_id: str
    sector_name: str
    included_app_classes: tuple[str, ...]
    included_languages: tuple[str, ...]
    included_platforms: tuple[str, ...]
    included_workflows: tuple[str, ...]
    required_adapters: tuple[str, ...]
    required_fixtures: tuple[str, ...]
    required_toolchains: tuple[str, ...]
    required_verifiers: tuple[str, ...]
    promotion_targets: tuple[str, ...]
    known_supported_cells: tuple[str, ...]
    known_blocked_cells: tuple[str, ...]
    missing_rungs: tuple[str, ...]
    claim_boundary: tuple[str, ...]
    release_boundary: tuple[str, ...]
    next_probe_batch: str


@dataclass(frozen=True)
class Universal100SectorStateLadderStatus:
    decision: str
    target_surface: str
    target_workflow: str
    sector_count: int
    sectors: tuple[SectorRow, ...]
    support_lifecycle_states: tuple[str, ...]
    blocker_missing_rung_states: tuple[str, ...]
    promotion_rules: tuple[dict[str, object], ...]
    claim_boundary: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
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
        d["sectors"] = [asdict(s) for s in self.sectors]
        for k in (
            "support_lifecycle_states",
            "blocker_missing_rung_states",
            "claim_boundary",
            "forbidden_claims",
            "captions",
            "notes",
        ):
            d[k] = list(getattr(self, k))
        return d

    @property
    def is_passed(self) -> bool:
        return self.decision == "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_PASSED"

    @property
    def is_awaiting(self) -> bool:
        return self.decision == "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_AWAITING_EVIDENCE"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_BLOCKED_")


def _locate_latest_evidence(evidence_dir: Path) -> Path | None:
    if not evidence_dir.is_dir():
        return None
    candidates = sorted(evidence_dir.glob("run_*.json"))
    return candidates[-1] if candidates else None


def _shell(*, decision: str, note: str) -> Universal100SectorStateLadderStatus:
    return Universal100SectorStateLadderStatus(
        decision=decision,
        target_surface="Universal 100 Sector State Ladder",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        sector_count=0,
        sectors=tuple(),
        support_lifecycle_states=tuple(),
        blocker_missing_rung_states=tuple(),
        promotion_rules=tuple(),
        claim_boundary=tuple(),
        forbidden_claims=tuple(),
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


def _awaiting(note: str) -> Universal100SectorStateLadderStatus:
    return _shell(
        decision="REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_AWAITING_EVIDENCE", note=note
    )


def _block(decision: str, note: str) -> Universal100SectorStateLadderStatus:
    return _shell(decision=decision, note=note)


def _sector_row(s: dict) -> SectorRow:
    return SectorRow(
        sector_id=str(s.get("sector_id") or "(unknown)"),
        sector_name=str(s.get("sector_name") or "(unknown)"),
        included_app_classes=tuple(str(x) for x in (s.get("included_app_classes") or [])),
        included_languages=tuple(str(x) for x in (s.get("included_languages") or [])),
        included_platforms=tuple(str(x) for x in (s.get("included_platforms") or [])),
        included_workflows=tuple(str(x) for x in (s.get("included_workflows") or [])),
        required_adapters=tuple(str(x) for x in (s.get("required_adapters") or [])),
        required_fixtures=tuple(str(x) for x in (s.get("required_fixtures") or [])),
        required_toolchains=tuple(str(x) for x in (s.get("required_toolchains") or [])),
        required_verifiers=tuple(str(x) for x in (s.get("required_verifiers") or [])),
        promotion_targets=tuple(str(x) for x in (s.get("promotion_targets") or [])),
        known_supported_cells=tuple(str(x) for x in (s.get("known_supported_cells") or [])),
        known_blocked_cells=tuple(str(x) for x in (s.get("known_blocked_cells") or [])),
        missing_rungs=tuple(str(x) for x in (s.get("missing_rungs") or [])),
        claim_boundary=tuple(str(x) for x in (s.get("claim_boundary") or [])),
        release_boundary=tuple(str(x) for x in (s.get("release_boundary") or [])),
        next_probe_batch=str(s.get("next_probe_batch") or ""),
    )


def load(evidence_dir: Path | str | None = None) -> Universal100SectorStateLadderStatus:
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
            "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_BLOCKED_MALFORMED",
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
                "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_BLOCKED_AUTHORITY_CONFUSION",
                f"authority flag {flag} is true",
            )
    if _auth("broad_claims_granted"):
        return _block(
            "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_BLOCKED_BROAD_CLAIM",
            "broad_claims_granted is true",
        )

    sector_registry_raw = blob.get("sector_registry")
    if not isinstance(sector_registry_raw, list) or not sector_registry_raw:
        return _block(
            "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_BLOCKED_MALFORMED",
            "sector_registry missing or empty",
        )

    lifecycle = blob.get("support_lifecycle_states")
    if not isinstance(lifecycle, list) or not lifecycle:
        return _block(
            "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_BLOCKED_MALFORMED",
            "support_lifecycle_states missing or empty",
        )
    if lifecycle[0] != "DISCOVERED":
        return _block(
            "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_BLOCKED_MALFORMED",
            f"lifecycle must start at DISCOVERED, got {lifecycle[0]!r}",
        )
    if "FULLY_SUPPORTED_WITH_CAVEATS" not in lifecycle:
        return _block(
            "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_BLOCKED_MALFORMED",
            "lifecycle missing FULLY_SUPPORTED_WITH_CAVEATS terminus",
        )

    blockers = blob.get("blocker_missing_rung_states")
    if not isinstance(blockers, list):
        blockers = []

    # release_supported overclaim guard: any sector that names RELEASE_SUPPORTED
    # in promotion_targets must also name a packaging/fresh-install rung.
    sectors = tuple(_sector_row(s) for s in sector_registry_raw)
    for s in sectors:
        if "RELEASE_SUPPORTED" in s.promotion_targets:
            text = " ".join(s.release_boundary + s.missing_rungs).lower()
            if (
                "packaging" not in text
                and "fresh install" not in text
                and "release gate" not in text
            ):
                return _block(
                    "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_BLOCKED_RELEASE_OVERCLAIM",
                    f"sector {s.sector_id} targets RELEASE_SUPPORTED without naming packaging/fresh-install/release-gate rung",
                )

    hits: set[str] = set()
    _walk_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_BLOCKED_BROAD_CLAIM",
            f"forbidden broad-claim phrases as current claim: {sorted(hits)}",
        )

    return Universal100SectorStateLadderStatus(
        decision="REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_PASSED",
        target_surface="Universal 100 Sector State Ladder",
        target_workflow="sector state and ingestion ladder",
        sector_count=len(sectors),
        sectors=sectors,
        support_lifecycle_states=tuple(str(x) for x in lifecycle),
        blocker_missing_rung_states=tuple(str(x) for x in blockers),
        promotion_rules=tuple(
            dict(r) for r in (blob.get("promotion_rules") or []) if isinstance(r, dict)
        ),
        claim_boundary=tuple(str(x) for x in (blob.get("claim_boundary") or [])),
        forbidden_claims=tuple(str(x) for x in (blob.get("forbidden_claims") or [])),
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
    "REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_STATUS_TOKENS",
    "REQUIRED_PANEL_CAPTIONS",
    "SectorRow",
    "Universal100SectorStateLadderStatus",
]
