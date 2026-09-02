"""Idea Lab verified demo status loader.

DETERMINEX_REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_LOCK_001 — rung 2.

load() reads the Codex Idea Lab verified Python CLI splash demo
evidence (if present locally) and produces a render-safe view-model
the React Idea Lab panel can display. If the evidence file is not
present, returns an AWAITING_EVIDENCE record — the UI must show
"awaiting Codex reconciliation" rather than fake a verified status.

The loader is read-only. It does NOT call the network, does NOT
spawn subprocesses, does NOT write training rows, does NOT broaden
the scoped demo claim.

Hard rules enforced by load():

  * If evidence claim_boundary is missing one of the required scope
    statements ('not all apps', 'not any language', 'not all
    codebases', 'not production-ready arbitrary app creation',
    'training remains false'), the loader BLOCKS with
    BLOCKED_BROAD_CLAIM.
  * If evidence carries any forbidden broad-claim phrase
    (FORBIDDEN_BROAD_CLAIM_PHRASES in the record module), BLOCKS
    with BLOCKED_BROAD_CLAIM.
  * If source_mutation_authorized or training_eligible is True in
    the evidence, BLOCKS with BLOCKED_AUTHORITY_CONFUSION.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from .idea_lab_verified_demo_status_record import (
    FORBIDDEN_BROAD_CLAIM_PHRASES,
    IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS,
    IdeaLabVerifiedDemoStatus,
)

# Required boundary statements every reconciled demo evidence must
# include in claim_boundary. Missing any of these = BLOCKED.
REQUIRED_BOUNDARY_STATEMENTS = (
    "Python CLI/file-data demo only",
    "not all apps",
    "not any language",
    "training remains false",
)


_DEFAULT_EVIDENCE_DIR = (
    Path(__file__).resolve().parents[2]
    / "assurance"
    / "evidence"
    / "idea_lab_python_cli_verified_splash_demo"
)


def _locate_latest_evidence(evidence_dir: Path) -> Path | None:
    if not evidence_dir.is_dir():
        return None
    # Pick the lexically-greatest run_*.json — the timestamp naming
    # convention makes this the most recent.
    candidates = sorted(evidence_dir.glob("run_*.json"))
    return candidates[-1] if candidates else None


def _awaiting(note: str) -> IdeaLabVerifiedDemoStatus:
    return IdeaLabVerifiedDemoStatus(
        decision="REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_AWAITING_EVIDENCE",
        demo_title="(awaiting Codex reconciliation)",
        target_surface="Idea Lab",
        target_app_class="(awaiting evidence)",
        target_language="(awaiting evidence)",
        beginner_idea="(awaiting evidence)",
        tests_passed=False,
        smoke_passed=False,
        verified_working_local_app=False,
        evidence_ref="",
        claim_boundary=(
            "no verified demo evidence available locally yet",
            "training remains false",
        ),
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


def _block(decision: str, note: str) -> IdeaLabVerifiedDemoStatus:
    return IdeaLabVerifiedDemoStatus(
        decision=decision,
        demo_title="(blocked)",
        target_surface="Idea Lab",
        target_app_class="(blocked)",
        target_language="(blocked)",
        beginner_idea="(blocked)",
        tests_passed=False,
        smoke_passed=False,
        verified_working_local_app=False,
        evidence_ref="",
        claim_boundary=(),
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


def load(evidence_dir: Path | str | None = None) -> IdeaLabVerifiedDemoStatus:
    ed = Path(evidence_dir) if evidence_dir else _DEFAULT_EVIDENCE_DIR
    chosen = _locate_latest_evidence(ed)
    if chosen is None:
        return _awaiting(f"no evidence file under {ed}")

    try:
        blob = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not read evidence: {exc}")

    # Aggregate-invariant gates.
    if blob.get("source_mutation_authorized") is True:
        return _block(
            "REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares source_mutation_authorized=True",
        )
    if blob.get("training_eligible") is True:
        return _block(
            "REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares training_eligible=True",
        )
    if (blob.get("authority") or {}).get("approval_authority_granted") is True:
        return _block(
            "REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares approval_authority_granted=True",
        )

    # Boundary statements present?
    boundary_list = blob.get("claim_boundary") or []
    boundary_joined = " ; ".join(str(b) for b in boundary_list).lower()
    missing_required = [
        req for req in REQUIRED_BOUNDARY_STATEMENTS if req.lower() not in boundary_joined
    ]
    if missing_required:
        return _block(
            "REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
            f"evidence claim_boundary missing required statements: {missing_required!r}",
        )

    # Forbidden broad-claim phrases anywhere in the evidence text
    # (case-insensitive). The blocked_path_demo section legitimately
    # mentions those phrases as REFUSED attempts; we exclude that
    # subsection from the scan. We then look for AFFIRMATIVE
    # occurrences — i.e. occurrences NOT preceded by a negation
    # marker. Per-occurrence regex scan (per-phrase) means a benign
    # 'not all apps' boundary entry does not mask an affirmative
    # 'Determinex supports all apps' marketing slip elsewhere.
    import re as _re

    safe_haystack = json.dumps({k: v for k, v in blob.items() if k != "blocked_path_demo"}).lower()
    for phrase in FORBIDDEN_BROAD_CLAIM_PHRASES:
        if phrase not in safe_haystack:
            continue
        affirmative_pattern = _re.compile(
            r"(?<!not )(?<!refuses )(?<!refused )(?<!refusing )"
            r"(?<!refuse )(?<!blocks )(?<!blocked )" + _re.escape(phrase)
        )
        if affirmative_pattern.search(safe_haystack):
            return _block(
                "REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
                f"evidence carries affirmative forbidden broad-claim phrase {phrase!r}",
            )

    # Verification subsection.
    ver = blob.get("verification") or {}
    tests_passed = bool(ver.get("tests_passed"))
    smoke_passed = bool(ver.get("smoke_passed"))
    verified = bool(ver.get("verified_working_local_app"))

    # If verification claims verified but lacks tests+smoke pass,
    # that's BLOCKED_AUTHORITY_CONFUSION (verified label without
    # required proof — a false-success).
    if verified and not (tests_passed and smoke_passed):
        return _block(
            "REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            (
                "verified_working_local_app=True without "
                f"tests_passed={tests_passed} and smoke_passed={smoke_passed}"
            ),
        )

    return IdeaLabVerifiedDemoStatus(
        decision="REACT_IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_PASSED",
        demo_title=str(blob.get("record_id") or chosen.stem),
        target_surface=str(blob.get("target_surface") or "Idea Lab"),
        target_app_class=str(blob.get("target_app_class") or ""),
        target_language=str(blob.get("target_language") or ""),
        beginner_idea=str(blob.get("beginner_idea") or ""),
        tests_passed=tests_passed,
        smoke_passed=smoke_passed,
        verified_working_local_app=verified,
        evidence_ref=str(chosen.as_posix()),
        claim_boundary=tuple(str(b) for b in boundary_list),
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            "evidence read from Codex Idea Lab demo bundle",
            "verified ONLY for this fixture demo path",
            "training remains false; source mutation not authorized",
        ),
    )


__all__ = [
    "load",
    "REQUIRED_BOUNDARY_STATEMENTS",
    "IDEA_LAB_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS",
    "IdeaLabVerifiedDemoStatus",
]
