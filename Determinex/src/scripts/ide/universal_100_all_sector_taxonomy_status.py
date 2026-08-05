"""Universal 100 All-Sector Taxonomy status loader.

DETERMINEX_REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_LOCK_001.

The all-sector taxonomy is **routing structure**, not support proof.
Every sector listed names a routing target with default_claim_state
NOT_CLAIMED and default_support_state classified — membership in the
taxonomy does NOT grant any capability claim.

Hard rules enforced by load():

  * status != UNIVERSAL_100_ALL_SECTOR_TAXONOMY_PASSED -> BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * sectors missing or empty -> BLOCKED_MALFORMED
  * sector_count != len(sectors) -> BLOCKED_MALFORMED
  * any sector with default_support_state above scaffold_only (i.e.
    build_supported / test_supported / smoke_supported / user_ready_*
    / release_supported / fully_supported_*) -> BLOCKED_TAXONOMY_OVERCLAIM
  * any sector with default_claim_state in {IMPLEMENTED,
    IMPLEMENTED_WITH_CAVEATS, PARTIAL} -> BLOCKED_TAXONOMY_OVERCLAIM
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
    FORBIDDEN_BROAD_CLAIM_PHRASES,
)

# Taxonomy-specific refusal-context keys. Codex's all-sector taxonomy
# carries every sector's "never_claim", "missing_rung_template",
# "claim_boundary", "release_boundary", and "safety_or_authority_constraints"
# inline; phrases listed there are by definition refusal context, not
# current capability claims. Whole subtrees rooted at these keys are
# skipped by the forbidden-phrase walker.
_REFUSAL_CONTEXT_KEYS = {
    "forbidden_claims",
    "missing_rung_templates",
    "routing_templates",
    "never_claim",
    "must_never_claim",
    "must_not_claim",
    "must_refuse",
    "claim_boundary",
    "release_boundary",
    "safety_or_authority_constraints",
    "missing_rung_template",
    "first_probe_strategy",
    "blocked_path_demo",
    "blocked_path_summary",
    "does_not_mean",
    "what_remains_forbidden",
    "fallbacks_enforced",
    "negative_claims",
    "refused_claims",
    "captions",
    "required_panel_captions",
}


def _walk_taxonomy_strings_for_forbidden(node: object, hits: set[str]) -> None:
    if isinstance(node, str):
        lowered = node.lower()
        for phrase in FORBIDDEN_BROAD_CLAIM_PHRASES:
            if phrase in lowered:
                hits.add(phrase)
    elif isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and k.lower() in _REFUSAL_CONTEXT_KEYS:
                continue
            _walk_taxonomy_strings_for_forbidden(v, hits)
    elif isinstance(node, list):
        for item in node:
            _walk_taxonomy_strings_for_forbidden(item, hits)


_REPO_ROOT = _HERE.parent.parent.parent

_DEFAULT_EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "universal_100_all_sector_taxonomy"

EXPECTED_STATUS = "UNIVERSAL_100_ALL_SECTOR_TAXONOMY_PASSED"

REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Taxonomy is routing structure, not support proof.",
    '"Taxonomy family present" does not mean capability exists.',
    "Default claim state remains NOT_CLAIMED; default support state remains classified.",
    "No source mutation without authority.",
    "Universal 100 means universal intake/routing, not magic execution.",
    "Blocked cells are visible by exact missing rung.",
)


REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_STATUS_TOKENS = (
    "REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_PASSED",
    "REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_AWAITING_EVIDENCE",
    "REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_BLOCKED_MALFORMED",
    "REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_BLOCKED_AUTHORITY_CONFUSION",
    "REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_BLOCKED_BROAD_CLAIM",
    "REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_BLOCKED_TAXONOMY_OVERCLAIM",
)


# Support states that are NOT allowed as a taxonomy default (would imply
# capability without probe evidence).
_FORBIDDEN_DEFAULT_SUPPORT_STATES = frozenset(
    {
        "build_supported",
        "test_supported",
        "smoke_supported",
        "repair_supported",
        "maintain_supported",
        "teach_supported",
        "user_ready_with_caveats",
        "packaging_supported",
        "fresh_install_verified",
        "release_gate_ready",
        "release_supported",
        "fully_supported_with_caveats",
    }
)

_FORBIDDEN_DEFAULT_CLAIM_STATES = frozenset(
    {
        "IMPLEMENTED",
        "IMPLEMENTED_WITH_CAVEATS",
        "PARTIAL",
    }
)


@dataclass(frozen=True)
class TaxonomySectorRow:
    sector_id: str
    sector_family: str
    taxonomy_index: int
    default_claim_state: str
    default_support_state: str
    representative_app_classes: tuple[str, ...]
    likely_languages: tuple[str, ...]
    likely_platforms: tuple[str, ...]
    likely_workflows: tuple[str, ...]
    likely_blockers: tuple[str, ...]
    required_adapters: tuple[str, ...]
    required_toolchains: tuple[str, ...]
    required_verifiers: tuple[str, ...]
    depth_targets: tuple[str, ...]
    missing_rung_template: str
    first_probe_strategy: str
    claim_boundary: tuple[str, ...]
    release_boundary: tuple[str, ...]
    safety_or_authority_constraints: tuple[str, ...]


@dataclass(frozen=True)
class AllSectorTaxonomyStatus:
    decision: str
    target_surface: str
    target_workflow: str
    sector_count: int
    top_level_sector_families: tuple[str, ...]
    sectors: tuple[TaxonomySectorRow, ...]
    routing_templates_count: int
    missing_rung_templates_count: int
    taxonomy_rule: str
    strongest_truthful_claim: str
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
            "top_level_sector_families",
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


def _sector_row(s: dict) -> TaxonomySectorRow:
    return TaxonomySectorRow(
        sector_id=str(s.get("sector_id") or "(unknown)"),
        sector_family=str(s.get("sector_family") or "(unknown)"),
        taxonomy_index=int(s.get("taxonomy_index") or 0),
        default_claim_state=str(s.get("default_claim_state") or "(unknown)"),
        default_support_state=str(s.get("default_support_state") or "(unknown)"),
        representative_app_classes=tuple(
            str(x) for x in (s.get("representative_app_classes") or [])
        ),
        likely_languages=tuple(str(x) for x in (s.get("likely_languages") or [])),
        likely_platforms=tuple(str(x) for x in (s.get("likely_platforms") or [])),
        likely_workflows=tuple(str(x) for x in (s.get("likely_workflows") or [])),
        likely_blockers=tuple(str(x) for x in (s.get("likely_blockers") or [])),
        required_adapters=tuple(str(x) for x in (s.get("required_adapters") or [])),
        required_toolchains=tuple(str(x) for x in (s.get("required_toolchains") or [])),
        required_verifiers=tuple(str(x) for x in (s.get("required_verifiers") or [])),
        depth_targets=tuple(str(x) for x in (s.get("depth_targets") or [])),
        missing_rung_template=str(s.get("missing_rung_template") or ""),
        first_probe_strategy=str(s.get("first_probe_strategy") or ""),
        claim_boundary=tuple(str(x) for x in (s.get("claim_boundary") or [])),
        release_boundary=tuple(str(x) for x in (s.get("release_boundary") or [])),
        safety_or_authority_constraints=tuple(
            str(x) for x in (s.get("safety_or_authority_constraints") or [])
        ),
    )


def _shell(*, decision: str, note: str) -> AllSectorTaxonomyStatus:
    return AllSectorTaxonomyStatus(
        decision=decision,
        target_surface="Universal 100 All-Sector Taxonomy",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        sector_count=0,
        top_level_sector_families=tuple(),
        sectors=tuple(),
        routing_templates_count=0,
        missing_rung_templates_count=0,
        taxonomy_rule="",
        strongest_truthful_claim="(awaiting)" if "AWAITING" in decision else "(blocked)",
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


def _awaiting(note: str) -> AllSectorTaxonomyStatus:
    return _shell(
        decision="REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_AWAITING_EVIDENCE",
        note=note,
    )


def _block(decision: str, note: str) -> AllSectorTaxonomyStatus:
    return _shell(decision=decision, note=note)


def load(evidence_dir: Path | str | None = None) -> AllSectorTaxonomyStatus:
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
            "REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_BLOCKED_MALFORMED",
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
                "REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_BLOCKED_AUTHORITY_CONFUSION",
                f"authority flag {flag} is true",
            )
    if _auth("broad_claims_granted"):
        return _block(
            "REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_BLOCKED_BROAD_CLAIM",
            "broad_claims_granted is true",
        )

    sectors_raw = blob.get("sectors")
    if not isinstance(sectors_raw, list) or not sectors_raw:
        return _block(
            "REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_BLOCKED_MALFORMED",
            "sectors missing or empty",
        )

    declared_count = int(blob.get("sector_count") or 0)
    if declared_count != len(sectors_raw):
        return _block(
            "REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_BLOCKED_MALFORMED",
            f"sector_count={declared_count} != len(sectors)={len(sectors_raw)}",
        )

    sectors = tuple(_sector_row(s) for s in sectors_raw)

    # Taxonomy must not imply capability. Every sector must default to
    # NOT_CLAIMED / classified (or scaffold_only at most). Anything above
    # that would convert taxonomy into a support claim.
    for s in sectors:
        if s.default_support_state.lower() in _FORBIDDEN_DEFAULT_SUPPORT_STATES:
            return _block(
                "REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_BLOCKED_TAXONOMY_OVERCLAIM",
                f"sector {s.sector_id} default_support_state={s.default_support_state} above classified/scaffold_only",
            )
        if s.default_claim_state.upper() in _FORBIDDEN_DEFAULT_CLAIM_STATES:
            return _block(
                "REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_BLOCKED_TAXONOMY_OVERCLAIM",
                f"sector {s.sector_id} default_claim_state={s.default_claim_state} above NOT_CLAIMED/ROADMAP/FUTURE_WING/FORBIDDEN",
            )

    hits: set[str] = set()
    _walk_taxonomy_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            "REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_BLOCKED_BROAD_CLAIM",
            f"forbidden broad-claim phrases as current claim: {sorted(hits)}",
        )

    routing_templates = blob.get("routing_templates")
    missing_rung_templates = blob.get("missing_rung_templates")

    def _container_len(value: object) -> int:
        if isinstance(value, (list, dict)):
            return len(value)
        return 0

    return AllSectorTaxonomyStatus(
        decision="REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_PASSED",
        target_surface="Universal 100 All-Sector Taxonomy",
        target_workflow="all-sector taxonomy (routing only)",
        sector_count=declared_count,
        top_level_sector_families=tuple(
            str(x) for x in (blob.get("top_level_sector_families") or [])
        ),
        sectors=sectors,
        routing_templates_count=_container_len(routing_templates),
        missing_rung_templates_count=_container_len(missing_rung_templates),
        taxonomy_rule=str(blob.get("taxonomy_rule") or ""),
        strongest_truthful_claim=str(blob.get("strongest_truthful_claim") or ""),
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
    "REACT_UNIVERSAL_100_ALL_SECTOR_TAXONOMY_BINDING_STATUS_TOKENS",
    "REQUIRED_PANEL_CAPTIONS",
    "TaxonomySectorRow",
    "AllSectorTaxonomyStatus",
]
