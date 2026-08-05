"""Public Authority Boundary status loader.

DETERMINEX_REACT_PUBLIC_AUTHORITY_BOUNDARY_BINDING_LOCK_001.

load() reads the Codex public authority-boundary preservation evidence
from the flagship certification + proof report export + edge case
roadmap artifacts and returns a render-safe view-model the React panel
can display.

The panel DISPLAYS the closed authority bag: all flags remain false,
release_supported remains 0 cells / 0 families. The panel does NOT
grant authority and CANNOT promote any flag from false to true.

Hard rules enforced by load():

  * any source artifact missing -> AWAITING_EVIDENCE
  * any source artifact status != PASSED -> BLOCKED_MALFORMED
  * any required authority flag is True -> BLOCKED_AUTHORITY_CONFUSION
  * release_supported_cells / release_supported_families != 0 ->
    BLOCKED_RELEASE_OVERCLAIM
  * any authority_boundary preservation flag has wrong polarity ->
    BLOCKED_AUTHORITY_CONFUSION
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


_REPO_ROOT = _HERE.parent.parent.parent
_FLAGSHIP_DIR = (
    _REPO_ROOT / "assurance" / "evidence" / "public_tidal_wave_flagship_flow_certification"
)
_EXPORT_DIR = _REPO_ROOT / "assurance" / "evidence" / "public_proof_report_export"

LOCK_ID = "DETERMINEX_REACT_PUBLIC_AUTHORITY_BOUNDARY_BINDING_LOCK_001"

DECISION_PREFIX = "REACT_PUBLIC_AUTHORITY_BOUNDARY_BINDING"


def _token(suffix: str) -> str:
    return f"{DECISION_PREFIX}_{suffix}"


def _as_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Authority remains locked down. Readiness, verification, "
    "reporting, and routing do not grant release support, mutation "
    "authority, proof execution authority, training eligibility, or "
    "broad claims.",
    "Release-supported remains 0 cells / 0 families.",
    "source_mutation_authorized remains false.",
    "real_user_source_mutation_authorized remains false.",
    "proof_execution_authority_granted remains false.",
    "training_eligible remains false.",
    "broad_claims_granted remains false.",
    "Universal support is not claimed.",
    "Proof report export is not release readiness.",
)


_REQUIRED_FALSE_FLAGS = (
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
    "broad_claims_granted",
)

_REQUIRED_PRESERVED_TRUE_FLAGS = (
    "release_support_unchanged_at_zero",
    "broad_claims_remain_false",
    "proof_execution_authority_remains_false",
    "source_mutation_remains_unauthorized",
    "real_user_source_mutation_remains_unauthorized",
    "training_eligibility_remains_false",
)


@dataclass(frozen=True)
class PublicAuthorityBoundaryStatus:
    decision: str
    target_surface: str
    target_workflow: str
    lock_id: str
    release_supported_cells: int
    release_supported_families: int
    source_mutation_authorized: bool
    real_user_source_mutation_authorized: bool
    proof_execution_authority_granted: bool
    training_eligible: bool
    broad_claims_granted: bool
    release_ready: bool
    artifact_import_authorized: bool
    benchmark_execution_authorized: bool
    programbench_execution_authorized: bool
    release_deploy_workflow_created: bool
    release_support_unchanged_at_zero: bool
    broad_claims_remain_false: bool
    proof_execution_authority_remains_false: bool
    source_mutation_remains_unauthorized: bool
    real_user_source_mutation_remains_unauthorized: bool
    training_eligibility_remains_false: bool
    universal_support_claimed: bool
    proof_report_export_is_release_readiness: bool
    report_schema_is_runtime_execution_proof: bool
    flagship_evidence_ref: str
    export_evidence_ref: str
    captions: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        for k in ("captions", "notes"):
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


def _shell(*, decision: str, note: str) -> PublicAuthorityBoundaryStatus:
    return PublicAuthorityBoundaryStatus(
        decision=decision,
        target_surface="Public Authority Boundary",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        lock_id=LOCK_ID,
        release_supported_cells=0,
        release_supported_families=0,
        source_mutation_authorized=False,
        real_user_source_mutation_authorized=False,
        proof_execution_authority_granted=False,
        training_eligible=False,
        broad_claims_granted=False,
        release_ready=False,
        artifact_import_authorized=False,
        benchmark_execution_authorized=False,
        programbench_execution_authorized=False,
        release_deploy_workflow_created=False,
        release_support_unchanged_at_zero=False,
        broad_claims_remain_false=False,
        proof_execution_authority_remains_false=False,
        source_mutation_remains_unauthorized=False,
        real_user_source_mutation_remains_unauthorized=False,
        training_eligibility_remains_false=False,
        universal_support_claimed=False,
        proof_report_export_is_release_readiness=False,
        report_schema_is_runtime_execution_proof=False,
        flagship_evidence_ref="",
        export_evidence_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(note,),
    )


def _awaiting(note: str) -> PublicAuthorityBoundaryStatus:
    return _shell(decision=_token("AWAITING_EVIDENCE"), note=note)


def _block(decision: str, note: str) -> PublicAuthorityBoundaryStatus:
    return _shell(decision=decision, note=note)


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load(
    flagship_dir: Path | str | None = None,
    export_dir: Path | str | None = None,
) -> PublicAuthorityBoundaryStatus:
    fdir = Path(flagship_dir) if flagship_dir else _FLAGSHIP_DIR
    edir = Path(export_dir) if export_dir else _EXPORT_DIR

    fchosen = _locate_latest_evidence(fdir)
    if fchosen is None:
        return _awaiting(f"flagship evidence absent at {fdir}")
    try:
        fblob = json.loads(fchosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not parse flagship evidence: {exc}")
    if fblob.get("status") != "PUBLIC_TIDAL_WAVE_FLAGSHIP_FLOW_CERTIFICATION_PASSED":
        return _block(_token("BLOCKED_MALFORMED"), f"flagship status={fblob.get('status')!r}")

    echosen = _locate_latest_evidence(edir)
    if echosen is None:
        return _awaiting(f"export evidence absent at {edir}")
    try:
        eblob = json.loads(echosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not parse export evidence: {exc}")
    if eblob.get("status") != "PUBLIC_PROOF_REPORT_EXPORT_PASSED":
        return _block(_token("BLOCKED_MALFORMED"), f"export status={eblob.get('status')!r}")

    for blob, src in ((fblob, "flagship"), (eblob, "export")):
        auth = blob.get("authority") or {}
        for flag in _REQUIRED_FALSE_FLAGS:
            if blob.get(flag) is True or auth.get(flag) is True:
                return _block(
                    _token("BLOCKED_AUTHORITY_CONFUSION"),
                    f"{src} authority flag {flag} is true",
                )

    flagship_rs = fblob.get("release_support_status") or {}
    flagship_ab = fblob.get("authority_boundary") or {}
    export_rs = eblob.get("release_support_status") or {}
    export_ab = eblob.get("authority_boundary") or {}

    cells = _as_int(flagship_rs.get("release_supported_cells", 0)) + _as_int(
        export_rs.get("release_supported_cells", 0)
    )
    families = _as_int(flagship_rs.get("release_supported_families", 0)) + _as_int(
        export_rs.get("release_supported_families", 0)
    )
    if cells != 0 or families != 0:
        return _block(
            _token("BLOCKED_RELEASE_OVERCLAIM"),
            f"release_supported (combined) cells={cells} families={families}",
        )

    # Preserved-true flags must be True everywhere -- and PRESENT.
    #
    # This read `if k in ab and ab[k] is not True`, i.e. the flags in a tuple named
    # _REQUIRED_PRESERVED_TRUE_FLAGS were only checked when they happened to be there. An
    # absent flag passed the gate and was then reported as True by the `.get(k, True)`
    # defaults further down, so this surface -- whose entire purpose is to prevent
    # overclaiming -- would assert that an invariant held on evidence that never mentioned
    # it. Compare `universal_support_claimed` a few lines below, which uses `is not False`
    # and correctly blocks on absence: the right idiom was already in this function, applied
    # inconsistently.
    #
    # Verified safe before changing: both current evidence blobs carry all 6 flags, so this
    # tightens the gate without moving it.
    for src, ab in (("flagship", flagship_ab), ("export", export_ab)):
        for k in _REQUIRED_PRESERVED_TRUE_FLAGS:
            if k not in ab:
                return _block(
                    _token("BLOCKED_AUTHORITY_CONFUSION"),
                    f"{src}.authority_boundary.{k} is absent; a required preserved-true "
                    f"flag cannot be assumed",
                )
            if ab[k] is not True:
                return _block(
                    _token("BLOCKED_AUTHORITY_CONFUSION"),
                    f"{src}.authority_boundary.{k} must be True (got {ab[k]!r})",
                )

    # Universal-support flag must be False.
    if flagship_ab.get("universal_support_claimed") is not False:
        return _block(
            _token("BLOCKED_AUTHORITY_CONFUSION"),
            "flagship.authority_boundary.universal_support_claimed must be False",
        )
    # Export-side claim assertions.
    if export_ab.get("proof_report_export_is_release_readiness") is not False:
        return _block(
            _token("BLOCKED_AUTHORITY_CONFUSION"),
            "export.authority_boundary.proof_report_export_is_release_readiness must be False",
        )
    if export_ab.get("report_schema_is_runtime_execution_proof") is not False:
        return _block(
            _token("BLOCKED_AUTHORITY_CONFUSION"),
            "export.authority_boundary.report_schema_is_runtime_execution_proof must be False",
        )

    return PublicAuthorityBoundaryStatus(
        decision=_token("PASSED"),
        target_surface="Public Authority Boundary",
        target_workflow="public authority boundary",
        lock_id=LOCK_ID,
        release_supported_cells=0,
        release_supported_families=0,
        source_mutation_authorized=False,
        real_user_source_mutation_authorized=False,
        proof_execution_authority_granted=False,
        training_eligible=False,
        broad_claims_granted=False,
        release_ready=False,
        artifact_import_authorized=False,
        benchmark_execution_authorized=False,
        programbench_execution_authorized=False,
        release_deploy_workflow_created=False,
        # Indexed, not `.get(..., True)`. The loop above now requires every one of these
        # keys to be PRESENT and True, so the old defaults were unreachable -- and while
        # they were reachable they were the actual defect: an absent flag skipped the check
        # and was then reported here as though the evidence had asserted it. Leaving a dead
        # default in place would keep the wrong behaviour one deleted guard away.
        release_support_unchanged_at_zero=bool(flagship_ab["release_support_unchanged_at_zero"]),
        broad_claims_remain_false=bool(flagship_ab["broad_claims_remain_false"]),
        proof_execution_authority_remains_false=bool(
            flagship_ab["proof_execution_authority_remains_false"]
        ),
        source_mutation_remains_unauthorized=bool(
            flagship_ab["source_mutation_remains_unauthorized"]
        ),
        real_user_source_mutation_remains_unauthorized=bool(
            flagship_ab["real_user_source_mutation_remains_unauthorized"]
        ),
        training_eligibility_remains_false=bool(flagship_ab["training_eligibility_remains_false"]),
        universal_support_claimed=False,
        proof_report_export_is_release_readiness=False,
        report_schema_is_runtime_execution_proof=False,
        flagship_evidence_ref=_relative_to_repo(fchosen),
        export_evidence_ref=_relative_to_repo(echosen),
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(),
    )


__all__ = [
    "load",
    "PublicAuthorityBoundaryStatus",
    "REQUIRED_PANEL_CAPTIONS",
    "LOCK_ID",
]
