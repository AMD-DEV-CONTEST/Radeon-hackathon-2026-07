"""Proof Before Mutation demo script.

CLAUDE_PROOF_BEFORE_MUTATION_DEMO_SCRIPT_LOCK_001 — rung 8.

Declares the canonical 11-step happy-path and 3-step blocked-path
demo for public/external review. The script is text; this module
asserts the script contains the required structure and DOES NOT
require network, Docker, ProgramBench, or training writes.
"""

from __future__ import annotations

from .proof_before_mutation_demo_script_record import (
    PROOF_BEFORE_MUTATION_DEMO_STATUS_TOKENS,
    DemoStep,
    ProofBeforeMutationDemoScriptRecord,
)

# The required copy phrase — every demo deliverable must contain
# this string (case-insensitive substring match).
PROOF_BEFORE_MUTATION_PHRASE = "Proof Before Mutation"

# Demo fixture repo location — never the user's real workspace.
DEMO_FIXTURE_REPO_PATH = "tests/fixtures/proof_before_mutation_demo_repo"


_HAPPY_PATH: tuple[DemoStep, ...] = (
    DemoStep(
        n=1,
        title="Open fixture repo",
        description=(
            "Proof Before Mutation begins: open the local demo fixture "
            f"repository at {DEMO_FIXTURE_REPO_PATH}. No external network "
            "access. No user real-source touched."
        ),
    ),
    DemoStep(
        n=2,
        title="Detect issue",
        description=(
            "Determinex detects a failing test in the fixture repo using a "
            "local verifier process. No network calls."
        ),
    ),
    DemoStep(
        n=3,
        title="Local model diagnoses",
        description=(
            "A locally-admitted model (REAL_LOCAL_MODEL_ADMISSION_LOCK_001) "
            "produces a diagnosis of the failing test. The model output is "
            "treated as untrusted; nothing is applied yet."
        ),
    ),
    DemoStep(
        n=4,
        title="Determinex quarantines patch",
        description=(
            "REAL_PATCH_PLAN_QUARANTINE_LOCK_001 validates the model's "
            "patch plan schema, paths, and op set. Bad entries are rejected."
        ),
    ),
    DemoStep(
        n=5,
        title="Temp verifier runs",
        description=(
            "REAL_TEMP_PATCH_VERIFY_LOCK_001 applies the plan to an "
            "isolated temp workspace and runs the verifier there. The real "
            "workspace is unchanged at this step."
        ),
    ),
    DemoStep(
        n=6,
        title="User approval required",
        description=(
            "An operator approval packet (REAL_HUMAN_APPROVAL_ADMISSION_LOCK_001) "
            "is requested. Without it, the apply gate refuses to proceed."
        ),
    ),
    DemoStep(
        n=7,
        title="Patch body hash is bound",
        description=(
            "The approval packet binds a canonical sha256 of the patch "
            "bodies (REAL_APPROVAL_DIFF_BODY_CONTENT_BINDING_LOCK_001) plus "
            "an HMAC-SHA256 signature "
            "(APPROVAL_SIGNATURE_CRYPTOGRAPHIC_BINDING_LOCK_001)."
        ),
    ),
    DemoStep(
        n=8,
        title="Source mutation applies only after approval",
        description=(
            "SOURCE_MUTATION_APPLY_AFTER_APPROVAL_LOCK_001 re-checks every "
            "gate (approval/verifier/snapshot/body hash/symlink) and only "
            "then writes to the fixture workspace."
        ),
    ),
    DemoStep(
        n=9,
        title="Post-apply verifier runs",
        description=(
            "POST_APPLY_VERIFIER_NO_DEFAULT_PASS_LOCK_001 runs the real "
            "verifier on the mutated workspace. A missing or stub verifier "
            "fails closed."
        ),
    ),
    DemoStep(
        n=10,
        title="Signed evidence appears",
        description=(
            "An evidence artifact is written and indexed. The evidence is "
            "an audit record, NOT an authorization to mutate again."
        ),
    ),
    DemoStep(
        n=11,
        title="Training remains blocked unless separately eligible",
        description=(
            "training_eligible stays False. The Claude IDE lane does not "
            "open training; only an explicit separate gate could."
        ),
    ),
)


_BLOCKED_PATH: tuple[DemoStep, ...] = (
    DemoStep(
        n=1,
        title="Missing approval",
        description=(
            "Attempt apply with approval=None. Apply gate returns "
            "SOURCE_MUTATION_BLOCKED_NO_APPROVAL. Evidence records the refusal."
        ),
        is_blocked_step=True,
    ),
    DemoStep(
        n=2,
        title="Changed patch body",
        description=(
            "Submit a valid approval whose canonical_patch_body_hash matches "
            "one set of bodies, but supply DIFFERENT plan_entries to the "
            "apply gate. Apply returns "
            "SOURCE_MUTATION_BLOCKED_BODY_HASH_MISMATCH "
            "(CLAUDE-AUTH-001 attack scenario blocked)."
        ),
        is_blocked_step=True,
    ),
    DemoStep(
        n=3,
        title="Missing verifier",
        description=(
            "Attempt apply with temp_verify=None. Apply gate returns "
            "SOURCE_MUTATION_BLOCKED_VERIFIER_NOT_PASSED. Evidence records "
            "the refusal."
        ),
        is_blocked_step=True,
    ),
)


def canonical_happy_path() -> tuple[DemoStep, ...]:
    return _HAPPY_PATH


def canonical_blocked_path() -> tuple[DemoStep, ...]:
    return _BLOCKED_PATH


def build_record() -> ProofBeforeMutationDemoScriptRecord:
    happy = _HAPPY_PATH
    blocked = _BLOCKED_PATH

    # Required-phrase check across every step's title + description.
    haystack = " ".join((s.title + " " + s.description) for s in (happy + blocked))
    phrase_present = PROOF_BEFORE_MUTATION_PHRASE.lower() in haystack.lower()
    # The phrase is the marketing tagline; require it in the
    # higher-level demo notes rather than every step. Provide it in
    # the record's notes tuple — see below.

    # Authority ambiguity: every happy-path step number must be unique
    # and contiguous 1..11; blocked-path 1..3.
    if [s.n for s in happy] != list(range(1, 12)):
        return _block(
            "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_AUTHORITY_AMBIGUITY",
            note="happy-path steps are not contiguous 1..11",
            happy=happy,
            blocked=blocked,
        )
    if [s.n for s in blocked] != list(range(1, 4)):
        return _block(
            "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_AUTHORITY_AMBIGUITY",
            note="blocked-path steps are not contiguous 1..3",
            happy=happy,
            blocked=blocked,
        )

    # All blocked-path steps must declare is_blocked_step=True.
    if not all(s.is_blocked_step for s in blocked):
        return _block(
            "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_MISSING_BLOCKED_PATH",
            note="blocked path contains steps without is_blocked_step=True",
            happy=happy,
            blocked=blocked,
        )
    if any(s.is_blocked_step for s in happy):
        return _block(
            "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_AUTHORITY_AMBIGUITY",
            note="happy-path step marked is_blocked_step",
            happy=happy,
            blocked=blocked,
        )

    # Forbidden infrastructure mentions: the demo must not require
    # network, docker, or programbench. Case-insensitive substring.
    forbidden = {
        "network": ("call openai", "call anthropic", "remote model", "external api"),
        "docker": ("docker run", "docker compose", "docker pull"),
        "programbench": ("programbench eval", "programbench run"),
    }
    network_required = any(p in haystack.lower() for p in forbidden["network"])
    docker_required = any(p in haystack.lower() for p in forbidden["docker"])
    pb_required = any(p in haystack.lower() for p in forbidden["programbench"])

    if network_required or docker_required or pb_required:
        return _block(
            "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_NETWORK_REQUIRED",
            note=(
                f"forbidden infra required: network={network_required}, "
                f"docker={docker_required}, programbench={pb_required}"
            ),
            happy=happy,
            blocked=blocked,
        )

    # Training-writes forbidden.
    if "write training row" in haystack.lower() or "training corpus write" in haystack.lower():
        return _block(
            "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_NETWORK_REQUIRED",
            note="training write language found in demo script",
            happy=happy,
            blocked=blocked,
        )

    # User-source-mutation outside fixture — refuse.
    if "real user repo" in haystack.lower() or "user source repo" in haystack.lower():
        return _block(
            "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_PATH_INCLUDED",
            note="demo references real user source repo rather than fixture",
            happy=happy,
            blocked=blocked,
        )

    if not phrase_present:
        return _block(
            "PROOF_BEFORE_MUTATION_DEMO_BLOCKED_MISSING_PHRASE",
            note=(
                f"required marketing phrase {PROOF_BEFORE_MUTATION_PHRASE!r} "
                "missing from demo script copy"
            ),
            happy=happy,
            blocked=blocked,
        )

    return ProofBeforeMutationDemoScriptRecord(
        decision="PROOF_BEFORE_MUTATION_DEMO_SCRIPT_WRITTEN",
        happy_path_steps=happy,
        blocked_path_steps=blocked,
        fixture_repo_path=DEMO_FIXTURE_REPO_PATH,
        copy_phrase_present=phrase_present,
        network_required=False,
        docker_required=False,
        programbench_required=False,
        training_rows_written=False,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            f"demo tagline: {PROOF_BEFORE_MUTATION_PHRASE}",
            "happy path: 11 steps from fixture open to evidence write",
            "blocked path: 3 refusal scenarios with audit evidence",
            "no network, no docker, no ProgramBench, no training rows",
        ),
    )


def _block(
    decision: str,
    *,
    note: str,
    happy: tuple[DemoStep, ...],
    blocked: tuple[DemoStep, ...],
) -> ProofBeforeMutationDemoScriptRecord:
    return ProofBeforeMutationDemoScriptRecord(
        decision=decision,
        happy_path_steps=happy,
        blocked_path_steps=blocked,
        fixture_repo_path=DEMO_FIXTURE_REPO_PATH,
        copy_phrase_present=False,
        network_required=False,
        docker_required=False,
        programbench_required=False,
        training_rows_written=False,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


__all__ = [
    "PROOF_BEFORE_MUTATION_PHRASE",
    "DEMO_FIXTURE_REPO_PATH",
    "canonical_happy_path",
    "canonical_blocked_path",
    "build_record",
    "PROOF_BEFORE_MUTATION_DEMO_STATUS_TOKENS",
    "DemoStep",
    "ProofBeforeMutationDemoScriptRecord",
]
