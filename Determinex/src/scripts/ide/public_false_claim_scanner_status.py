"""Public False Claim Scanner / Claim Boundary status loader.

DETERMINEX_REACT_PUBLIC_FALSE_CLAIM_SCANNER_BINDING_LOCK_001.

load() reads Codex's public false-claim scanner evidence (from the
flagship certification artifact + proof report export contract) and
returns a render-safe view-model the React panel can display.

The panel DISPLAYS the public-safety boundary: every phrase listed
here is BLOCKED or FLAGGED by the scanner. The scanner output is a
*claim boundary*; it does NOT grant authority, promote support, or
weaken any forbidden shortcut.

Hard rules enforced by load():

  * flagship run artifact absent / unparseable -> AWAITING_EVIDENCE
  * flagship status != PASSED -> BLOCKED_MALFORMED
  * export run artifact absent / unparseable -> AWAITING_EVIDENCE
  * export status != PASSED -> BLOCKED_MALFORMED
  * false_claim_scanner_model.blocked_or_flagged_phrases length != 9
    -> BLOCKED_SCANNER_COUNT_MISMATCH
  * proof_report_export.forbidden_report_claims length != 11 ->
    BLOCKED_FORBIDDEN_COUNT_MISMATCH
  * any phrase entry's action != BLOCK_OR_FLAG ->
    BLOCKED_SCANNER_ACTION_MISMATCH
  * any phrase entry's current_claim_allowed != False ->
    BLOCKED_SCANNER_ACTION_MISMATCH
  * any required-block phrase missing from the combined scanner+contract
    set -> BLOCKED_SCANNER_MISSING_REQUIRED_PHRASE
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

LOCK_ID = "DETERMINEX_REACT_PUBLIC_FALSE_CLAIM_SCANNER_BINDING_LOCK_001"
EXPECTED_SCANNER_PHRASES = 9
EXPECTED_FORBIDDEN_REPORT_CLAIMS = 11

# Phrases the spec REQUIRES to be blocked or flagged. The actual scanner
# wording may vary slightly (e.g. "supports all apps today" vs "all apps
# supported"); the loader treats matches case-insensitively after
# substring normalisation.
REQUIRED_BLOCK_PHRASES = (
    "release ready",
    "production ready",
    "all apps supported",
    "all languages supported",
    "all platforms supported",
    "fully autonomous source mutation",
    "training eligible by default",
    "unknown/novel cases supported by default",
    "no edge cases",
    "arbitrary app generation",
    "commercial",
)

DECISION_PREFIX = "REACT_PUBLIC_FALSE_CLAIM_SCANNER_BINDING"


def _token(suffix: str) -> str:
    return f"{DECISION_PREFIX}_{suffix}"


REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Claim scanner output is a public-safety boundary. It prevents "
    "report language from overstating support, release readiness, "
    "production readiness, authority, training eligibility, or "
    "universal coverage.",
    "Every listed phrase is BLOCKED or FLAGGED.",
    "Forbidden shortcuts remain forbidden.",
    "Universal support is not claimed.",
    "Release-supported remains 0 cells / 0 families.",
)


@dataclass(frozen=True)
class ScannerPhraseRow:
    phrase: str
    action: str
    current_claim_allowed: bool
    source: str  # "flagship_scanner" or "export_contract"


@dataclass(frozen=True)
class PublicFalseClaimScannerStatus:
    decision: str
    target_surface: str
    target_workflow: str
    lock_id: str
    flagship_scanner_phrases: tuple[ScannerPhraseRow, ...]
    export_forbidden_phrases: tuple[ScannerPhraseRow, ...]
    combined_blocked_phrases: tuple[str, ...]
    flagship_scanner_count: int
    export_forbidden_count: int
    safe_replacement_boundary: str
    flagship_evidence_ref: str
    export_evidence_ref: str
    captions: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["flagship_scanner_phrases"] = [asdict(s) for s in self.flagship_scanner_phrases]
        d["export_forbidden_phrases"] = [asdict(s) for s in self.export_forbidden_phrases]
        for k in ("combined_blocked_phrases", "captions", "notes"):
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


def _shell(*, decision: str, note: str) -> PublicFalseClaimScannerStatus:
    return PublicFalseClaimScannerStatus(
        decision=decision,
        target_surface="Public False Claim Scanner",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        lock_id=LOCK_ID,
        flagship_scanner_phrases=(),
        export_forbidden_phrases=(),
        combined_blocked_phrases=(),
        flagship_scanner_count=0,
        export_forbidden_count=0,
        safe_replacement_boundary="",
        flagship_evidence_ref="",
        export_evidence_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(note,),
    )


def _awaiting(note: str) -> PublicFalseClaimScannerStatus:
    return _shell(decision=_token("AWAITING_EVIDENCE"), note=note)


def _block(decision: str, note: str) -> PublicFalseClaimScannerStatus:
    return _shell(decision=decision, note=note)


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _phrase_row(p: dict, *, source: str) -> ScannerPhraseRow:
    return ScannerPhraseRow(
        phrase=str(p.get("phrase") or ""),
        action=str(p.get("action") or ""),
        current_claim_allowed=bool(p.get("current_claim_allowed", False)),
        source=source,
    )


def load(
    flagship_dir: Path | str | None = None,
    export_dir: Path | str | None = None,
) -> PublicFalseClaimScannerStatus:
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
        return _block(
            _token("BLOCKED_MALFORMED"),
            f"flagship status={fblob.get('status')!r}",
        )

    echosen = _locate_latest_evidence(edir)
    if echosen is None:
        return _awaiting(f"export evidence absent at {edir}")
    try:
        eblob = json.loads(echosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not parse export evidence: {exc}")
    if eblob.get("status") != "PUBLIC_PROOF_REPORT_EXPORT_PASSED":
        return _block(
            _token("BLOCKED_MALFORMED"),
            f"export status={eblob.get('status')!r}",
        )

    scanner = fblob.get("false_claim_scanner_model") or {}
    scanner_phrases_raw = scanner.get("blocked_or_flagged_phrases") or []
    if (
        not isinstance(scanner_phrases_raw, list)
        or len(scanner_phrases_raw) != EXPECTED_SCANNER_PHRASES
    ):
        return _block(
            _token("BLOCKED_SCANNER_COUNT_MISMATCH"),
            f"flagship scanner phrases length="
            f"{len(scanner_phrases_raw) if isinstance(scanner_phrases_raw, list) else 'absent'} "
            f"(expected {EXPECTED_SCANNER_PHRASES})",
        )

    contract = eblob.get("proof_report_export_contract") or {}
    forbidden_raw = contract.get("forbidden_report_claims") or []
    if (
        not isinstance(forbidden_raw, list)
        or len(forbidden_raw) != EXPECTED_FORBIDDEN_REPORT_CLAIMS
    ):
        return _block(
            _token("BLOCKED_FORBIDDEN_COUNT_MISMATCH"),
            f"export forbidden_report_claims length="
            f"{len(forbidden_raw) if isinstance(forbidden_raw, list) else 'absent'} "
            f"(expected {EXPECTED_FORBIDDEN_REPORT_CLAIMS})",
        )

    flagship_phrases = tuple(_phrase_row(p, source="flagship_scanner") for p in scanner_phrases_raw)
    export_phrases = tuple(_phrase_row(p, source="export_contract") for p in forbidden_raw)

    for row in (*flagship_phrases, *export_phrases):
        if row.action != "BLOCK_OR_FLAG":
            return _block(
                _token("BLOCKED_SCANNER_ACTION_MISMATCH"),
                f"scanner phrase {row.phrase!r} action={row.action!r} (expected BLOCK_OR_FLAG)",
            )
        if row.current_claim_allowed is not False:
            return _block(
                _token("BLOCKED_SCANNER_ACTION_MISMATCH"),
                f"scanner phrase {row.phrase!r} current_claim_allowed must be false",
            )

    combined_lower = {row.phrase.lower() for row in (*flagship_phrases, *export_phrases)}
    missing = []
    for required in REQUIRED_BLOCK_PHRASES:
        if not any(required.lower() in phrase for phrase in combined_lower):
            missing.append(required)
    if missing:
        return _block(
            _token("BLOCKED_SCANNER_MISSING_REQUIRED_PHRASE"),
            f"required block phrases not covered: {missing}",
        )

    combined = tuple(sorted(combined_lower))

    return PublicFalseClaimScannerStatus(
        decision=_token("PASSED"),
        target_surface="Public False Claim Scanner",
        target_workflow="public false claim scanner",
        lock_id=LOCK_ID,
        flagship_scanner_phrases=flagship_phrases,
        export_forbidden_phrases=export_phrases,
        combined_blocked_phrases=combined,
        flagship_scanner_count=len(flagship_phrases),
        export_forbidden_count=len(export_phrases),
        safe_replacement_boundary=str(scanner.get("safe_replacement_boundary") or ""),
        flagship_evidence_ref=_relative_to_repo(fchosen),
        export_evidence_ref=_relative_to_repo(echosen),
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(),
    )


__all__ = [
    "load",
    "ScannerPhraseRow",
    "PublicFalseClaimScannerStatus",
    "REQUIRED_PANEL_CAPTIONS",
    "REQUIRED_BLOCK_PHRASES",
    "EXPECTED_SCANNER_PHRASES",
    "EXPECTED_FORBIDDEN_REPORT_CLAIMS",
    "LOCK_ID",
]
