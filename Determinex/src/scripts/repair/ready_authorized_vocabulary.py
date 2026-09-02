"""Vocabulary classifier for CLAUDE_AUTH_005_READY_AUTHORIZED_LANGUAGE_LOCK_001.

The Claude IDE / repair / frontend lane uses status tokens with a
range of meanings. This module is the single source of truth for
mapping a given token to one of the 8 disjoint authority classes
in ready_authorized_vocabulary_record.AUTHORITY_VOCABULARY_CLASSES.

Critical invariant — enforced by tests:

  * No ``*_READY`` token classifies into a class in
    CLASSES_THAT_IMPLY_AUTHORIZATION.
  * No token containing the substring ``READY`` may be confused
    with ``AUTHORIZED``.
  * ``*_FIXTURE`` approval tokens classify as
    ``approval_present`` but NEVER ``source_mutation_authorized``.

The classifier does NOT mutate the existing token surface. It
adds a layer that an operator or downstream agent can consult to
distinguish a capability signal from an authorization signal.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from .ready_authorized_vocabulary_record import (
    CLASSES_THAT_IMPLY_AUTHORIZATION,
    READY_AUTHORIZED_LANGUAGE_STATUS_TOKENS,
    ReadyAuthorizedLanguageRecord,
    TokenClassification,
)

# Canonical classification map — one entry per known status token.
# Keep this exhaustive over the audit set; the test suite walks the
# repo to keep this in sync.
_TOKEN_CLASSIFICATION: dict[str, tuple[str, str, str]] = {
    # token -> (surface, vocabulary_class, rationale)
    # ----- capability_available (READY) -----
    "IDE_BACKEND_COMMAND_SURFACE_READY": (
        "backend",
        "capability_available",
        "backend dispatcher is wired up; does not imply any approval",
    ),
    "IDE_DIAGNOSE_DRY_RUN_READY": (
        "backend",
        "capability_available",
        "diagnose dry-run flow is wired; no live model called",
    ),
    "IDE_DIAGNOSE_LIVE_OPT_IN_READY": (
        "backend",
        "capability_available",
        "live opt-in flow exists; the opt-in itself is a separate request",
    ),
    "MODEL_ROUTE_PANEL_READY": (
        "shared",
        "capability_available",
        "model-route panel is renderable; no admission implied",
    ),
    "INTAKE_READY": (
        "backend",
        "capability_available",
        "intake gate is open; nothing has been admitted yet",
    ),
    "IDE_SOURCE_APPLY_DRY_RUN_READY": (
        "backend",
        "capability_available",
        "source-apply dry-run can render; mutation is NOT authorized",
    ),
    "SOURCE_APPLY_DRY_RUN_READY": (
        "backend",
        "capability_available",
        "repair-side mirror of dry-run readiness; no mutation authorized",
    ),
    "LOCAL_MODEL_LIVE_ADMISSION_READY": (
        "backend",
        "capability_available",
        "live-admission flow can be invoked; admission itself requires admit()",
    ),
    "REAL_LOCAL_MODEL_CONFIG_READY": (
        "backend",
        "capability_available",
        "real-local-model config can be written; nothing is admitted",
    ),
    "FRONTEND_COMMAND_INVOKE_CLIENT_READY": (
        "frontend",
        "capability_available",
        "frontend invoke client is wired; no backend state changed",
    ),
    "TAURI_RUST_COMMAND_BRIDGE_READY": (
        "frontend",
        "capability_available",
        "Tauri bridge is mounted; commands still go through gates",
    ),
    "FRONTEND_PANEL_COMMAND_WIRING_READY": (
        "frontend",
        "capability_available",
        "panel-to-command wiring complete",
    ),
    "WORKSPACE_STATUS_PANEL_READY": (
        "frontend",
        "capability_available",
        "workspace status panel is renderable",
    ),
    "REPAIR_PANEL_SHELL_READY": (
        "frontend",
        "capability_available",
        "repair panel shell is renderable",
    ),
    "FRONTEND_DIAGNOSE_DRY_RUN_READY": (
        "frontend",
        "capability_available",
        "frontend diagnose dry-run is renderable",
    ),
    "TEMP_VERIFY_PANEL_READY": (
        "frontend",
        "capability_available",
        "temp-verify panel is renderable; no verifier has run",
    ),
    "HUMAN_APPROVAL_PANEL_READY": (
        "frontend",
        "capability_available",
        "approval panel is renderable; no approval has been granted",
    ),
    "SOURCE_APPLY_DRY_RUN_PANEL_READY": (
        "frontend",
        "capability_available",
        "source-apply dry-run panel is renderable; no mutation will happen",
    ),
    "EVIDENCE_VIEWER_READY": ("frontend", "capability_available", "evidence viewer is renderable"),
    "LOCAL_MODEL_SETTINGS_PANEL_READY": (
        "frontend",
        "capability_available",
        "local-model settings panel is renderable",
    ),
    # ----- admission_present (ADMITTED) -----
    "LIVE_MODEL_ADMITTED": (
        "backend",
        "admission_present",
        "live model admitted by admit() gate; does not authorize source mutation",
    ),
    "LIVE_MODEL_NOT_ADMITTED": (
        "backend",
        "request_pending",
        "live model not admitted; admission flow still pending",
    ),
    "LOCAL_MODEL_METADATA_ADMITTED": (
        "backend",
        "admission_present",
        "metadata-level admission; live model still requires a separate admission",
    ),
    "REAL_LOCAL_MODEL_ADMITTED": (
        "backend",
        "admission_present",
        "real-local-model gate admitted; does not authorize source mutation",
    ),
    # ----- approval_present (ACCEPTED) -----
    "REAL_HUMAN_APPROVAL_ACCEPTED": (
        "backend",
        "approval_present",
        "operator approval accepted by strict HMAC gate; "
        "still must pass apply-time body-hash and signature-kind checks",
    ),
    "SOURCE_APPROVAL_ACCEPTED_FIXTURE": (
        "backend",
        "approval_present",
        "FIXTURE-only approval; apply gate refuses fixture approvals "
        "(CLAUDE-AUTH-002 remediation), so this NEVER implies source_mutation_authorized",
    ),
    "SOURCE_MUTATION_APPROVAL_ACCEPTED_FIXTURE": (
        "backend",
        "approval_present",
        "repair-side FIXTURE-only approval; apply gate refuses fixture approvals",
    ),
    # ----- source_mutation_authorized (the only token in this class) -----
    "SOURCE_MUTATION_APPLIED_AFTER_APPROVAL": (
        "backend",
        "source_mutation_authorized",
        "post-fact authorization record; emitted ONLY by the apply gate "
        "after every check (approval, verifier, snapshot, hash binding, "
        "symlink refusal). Reading this token implies the mutation has "
        "ALREADY happened — not that future mutation is authorized.",
    ),
    # ----- evidence_present (verifier/snapshot run records) -----
    "POST_APPLY_VERIFIER_PASSED": (
        "backend",
        "evidence_present",
        "post-apply verifier produced a pass record",
    ),
    "ROLLBACK_SNAPSHOT_WRITTEN": (
        "backend",
        "evidence_present",
        "rollback snapshot artifact written; restoration still requires the rollback executor",
    ),
    "REAL_TEMP_PATCH_VERIFIER_PASSED": (
        "backend",
        "evidence_present",
        "temp verifier produced a pass record on an isolated workspace; "
        "the real workspace has NOT been mutated",
    ),
}


def classes() -> tuple[str, ...]:
    from .ready_authorized_vocabulary_record import (
        AUTHORITY_VOCABULARY_CLASSES,
    )

    return AUTHORITY_VOCABULARY_CLASSES


def classify(token: str) -> TokenClassification | None:
    """Classify a single token. Returns None if the token is not
    in the canonical map — callers must add unknown tokens
    explicitly; auto-classification would defeat the lock."""
    entry = _TOKEN_CLASSIFICATION.get(token)
    if entry is None:
        return None
    surface, klass, rationale = entry
    return TokenClassification(
        token=token,
        surface=surface,
        vocabulary_class=klass,
        rationale=rationale,
    )


def classify_many(tokens: list[str]) -> tuple[list[TokenClassification], list[str]]:
    """Return (classifications, unknown_tokens)."""
    out: list[TokenClassification] = []
    unknown: list[str] = []
    for t in tokens:
        c = classify(t)
        if c is None:
            unknown.append(t)
        else:
            out.append(c)
    return out, unknown


def known_tokens() -> tuple[str, ...]:
    return tuple(sorted(_TOKEN_CLASSIFICATION.keys()))


def assert_ready_does_not_imply_authorized() -> ReadyAuthorizedLanguageRecord:
    """Walks the canonical map and verifies no READY token lands
    in a class that implies authorization."""
    classifications: list[TokenClassification] = []
    ambiguous: list[str] = []
    ui_confusions: list[str] = []

    for tok in sorted(_TOKEN_CLASSIFICATION):
        c = classify(tok)
        if c is None:
            continue
        classifications.append(c)
        # Hard invariant 1: no READY-like token may classify into
        # an authorization-implying class.
        if "READY" in tok and c.vocabulary_class in CLASSES_THAT_IMPLY_AUTHORIZATION:
            ambiguous.append(
                f"{tok!r} classifies as {c.vocabulary_class!r} — "
                "READY tokens must never imply authorization"
            )
        # Hard invariant 2: fixture-only approvals must classify
        # as approval_present, never as source_mutation_authorized.
        if "FIXTURE" in tok and c.vocabulary_class == "source_mutation_authorized":
            ambiguous.append(
                f"{tok!r} classifies as source_mutation_authorized even though it is fixture-only"
            )
        # Hard invariant 3: no frontend (UI) surface token may
        # classify into an authorization-implying class.
        if c.surface == "frontend" and c.vocabulary_class in CLASSES_THAT_IMPLY_AUTHORIZATION:
            ui_confusions.append(
                f"frontend token {tok!r} classifies as "
                f"{c.vocabulary_class!r} — UI surfaces must never "
                "directly carry an authorization signal"
            )

    if ui_confusions:
        decision = "READY_AUTHORIZED_LANGUAGE_BLOCKED_UI_AUTHORITY_CONFUSION"
    elif ambiguous:
        decision = "READY_AUTHORIZED_LANGUAGE_BLOCKED_AMBIGUOUS_LABEL"
    else:
        decision = "READY_AUTHORIZED_LANGUAGE_PASSED"

    return ReadyAuthorizedLanguageRecord(
        decision=decision,
        tokens_classified=tuple(classifications),
        ambiguous_labels=tuple(ambiguous),
        ui_authority_confusions=tuple(ui_confusions),
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            "ready does not mean authorized",
            "no UI surface may directly carry an authorization signal",
            "fixture approvals are approval_present, never source_mutation_authorized",
        ),
    )


__all__ = [
    "classes",
    "classify",
    "classify_many",
    "known_tokens",
    "assert_ready_does_not_imply_authorized",
    "READY_AUTHORIZED_LANGUAGE_STATUS_TOKENS",
    "ReadyAuthorizedLanguageRecord",
    "TokenClassification",
]
