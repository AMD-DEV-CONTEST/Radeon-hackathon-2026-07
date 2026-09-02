"""Unified product splash demo spec.

DETERMINEX_UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_LOCK_001 — rung 8.

Canonical 5-step sequence (one per surface), at least one happy
path, one blocked path, one teaching moment, and one proof view.
Required tagline 'Proof Before Mutation' must appear; required
phrases 'Generated is not verified.' and 'Working means
build/test/smoke passed.' must appear; required negative caveats
about scope must appear ('not all apps', 'not all languages',
'not production-ready arbitrary apps', 'not training enabled').
No network, no Docker, no ProgramBench, no real external mutation.
"""

from __future__ import annotations

from .unified_product_splash_demo_spec_record import (
    REQUIRED_NEGATIVE_CAVEATS,
    REQUIRED_PHRASES,
    REQUIRED_TAGLINE,
    UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_STATUS_TOKENS,
    DemoSequenceStep,
    UnifiedProductSplashDemoSpecRecord,
)

_FORBIDDEN_INFRA_PHRASES = {
    "network": ("call openai", "call anthropic", "remote model", "external api"),
    "docker": ("docker run", "docker compose", "docker pull"),
    "programbench": ("programbench eval", "programbench run"),
    "real_external_mutation": (
        "mutate the user's real repo",
        "real user source repo",
        "live production codebase",
    ),
}


_CANONICAL_SEQUENCE: tuple[DemoSequenceStep, ...] = (
    DemoSequenceStep(
        n=1,
        surface="idea_lab",
        title="Idea Lab — beginner idea to scaffold",
        description=(
            "A beginner types an idea. Determinex writes a structured spec, "
            "a beginner-friendly summary, then a blueprint and scaffold. "
            "Acceptance tests run; the smoke plan is laid out. "
            "Proof Before Mutation begins here: 'Build It' stays disabled "
            "until the support-matrix check passes, and 'Working' stays "
            "disabled until build/test/smoke evidence exists. "
            "Generated is not verified. Working means build/test/smoke passed."
        ),
        is_teaching_step=False,
    ),
    DemoSequenceStep(
        n=2,
        surface="repo_clinic",
        title="Repo Clinic — diagnose & verifier-gated repair on a fixture",
        description=(
            "Open the fixture repo at tests/fixtures/proof_before_mutation_demo_repo. "
            "Diagnose a failing test. Show the quarantined patch plan. "
            "Temp verifier runs. Approval is required. Source mutation happens "
            "only after the approval gate + body-hash + symlink refusal + "
            "post-apply verifier. Generated is not verified."
        ),
    ),
    DemoSequenceStep(
        n=3,
        surface="maintenance_bay",
        title="Maintenance Bay — proposed dependency update under compatibility verifier",
        description=(
            "Propose a dependency bump. Risk classification is shown; "
            "advisory status is caveated. The update is quarantined and the "
            "compatibility verifier is required. Demonstrate the blocked path: "
            "no compatibility verifier present -> UPDATED label disabled."
        ),
        is_blocked_step=True,
    ),
    DemoSequenceStep(
        n=4,
        surface="learning_studio",
        title="Learning Studio — explain the failure & teach the fix in beginner / pro mode",
        description=(
            "Switch to beginner mode: plain-language explanation of why the "
            "test failed. Switch to professional mode: side-by-side annotated "
            "code. Press 'open in Repo Clinic' to route any suggested fix "
            "through the gated workflow. Working means build/test/smoke passed."
        ),
        is_teaching_step=True,
    ),
    DemoSequenceStep(
        n=5,
        surface="proof_operator_center",
        title="Proof / Operator Center — evidence, gates, blocked actions, training False",
        description=(
            "Show the evidence ledger view, the source-mutation gate state, "
            "verifier status, rollback status, the blocked actions list, "
            "ProgramBench / provenance read-only mirror, and the training "
            "status badge — training stays False. Caveats: not all apps, "
            "not all languages, not production-ready arbitrary apps, "
            "not training enabled. Proof Before Mutation."
        ),
        is_proof_view=True,
    ),
)


def canonical_sequence() -> tuple[DemoSequenceStep, ...]:
    return _CANONICAL_SEQUENCE


def build_record() -> UnifiedProductSplashDemoSpecRecord:
    seq = _CANONICAL_SEQUENCE
    haystack = " ".join(s.title + " " + s.description for s in seq)
    haystack_lower = haystack.lower()

    # 1) Tagline + phrases + caveats present.
    tagline_present = REQUIRED_TAGLINE.lower() in haystack_lower
    phrases_present = all(p.lower() in haystack_lower for p in REQUIRED_PHRASES)
    caveats_present = all(c.lower() in haystack_lower for c in REQUIRED_NEGATIVE_CAVEATS)

    # 2) Forbidden infra.
    network_required = any(p in haystack_lower for p in _FORBIDDEN_INFRA_PHRASES["network"])
    docker_required = any(p in haystack_lower for p in _FORBIDDEN_INFRA_PHRASES["docker"])
    pb_required = any(p in haystack_lower for p in _FORBIDDEN_INFRA_PHRASES["programbench"])
    real_ext = any(p in haystack_lower for p in _FORBIDDEN_INFRA_PHRASES["real_external_mutation"])

    # 3) Structural requirements: 5 steps mapped to 5 distinct surfaces.
    surfaces_seen = [s.surface for s in seq]
    expected_surfaces = [
        "idea_lab",
        "repo_clinic",
        "maintenance_bay",
        "learning_studio",
        "proof_operator_center",
    ]
    if surfaces_seen != expected_surfaces:
        return _block(
            "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_AUTHORITY_CONFUSION",
            seq=seq,
            haystack=haystack,
            note=f"surfaces must follow {expected_surfaces!r}; got {surfaces_seen!r}",
        )

    happy = any(not s.is_blocked_step for s in seq)
    blocked = any(s.is_blocked_step for s in seq)
    teaching = any(s.is_teaching_step for s in seq)
    proof = any(s.is_proof_view for s in seq)

    if not blocked:
        return _block(
            "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_AUTHORITY_CONFUSION",
            seq=seq,
            haystack=haystack,
            note="no blocked path step found",
        )
    if not teaching:
        return _block(
            "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_AUTHORITY_CONFUSION",
            seq=seq,
            haystack=haystack,
            note="no teaching step found",
        )
    if not proof:
        return _block(
            "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_MISSING_PROOF_VIEW",
            seq=seq,
            haystack=haystack,
            note="no proof/evidence view step",
        )

    if network_required or docker_required or pb_required or real_ext:
        return _block(
            "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_FALSE_UNIVERSALITY",
            seq=seq,
            haystack=haystack,
            note=(
                f"forbidden infra: network={network_required}, "
                f"docker={docker_required}, programbench={pb_required}, "
                f"real_external_mutation={real_ext}"
            ),
            network_required=network_required,
            docker_required=docker_required,
            pb_required=pb_required,
            real_ext=real_ext,
        )

    if not tagline_present:
        return _block(
            "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_FALSE_UNIVERSALITY",
            seq=seq,
            haystack=haystack,
            note=f"required tagline {REQUIRED_TAGLINE!r} not present",
        )
    if not phrases_present:
        missing = [p for p in REQUIRED_PHRASES if p.lower() not in haystack_lower]
        return _block(
            "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_FALSE_UNIVERSALITY",
            seq=seq,
            haystack=haystack,
            note=f"required phrases missing: {missing!r}",
        )
    if not caveats_present:
        missing = [c for c in REQUIRED_NEGATIVE_CAVEATS if c.lower() not in haystack_lower]
        return _block(
            "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_FALSE_UNIVERSALITY",
            seq=seq,
            haystack=haystack,
            note=f"required negative caveats missing: {missing!r}",
        )

    return UnifiedProductSplashDemoSpecRecord(
        decision="UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_WRITTEN",
        sequence=seq,
        tagline=REQUIRED_TAGLINE,
        required_phrases_present=True,
        required_caveats_present=True,
        happy_path_step_present=happy,
        blocked_path_step_present=blocked,
        teaching_step_present=teaching,
        proof_view_step_present=proof,
        network_required=False,
        docker_required=False,
        programbench_required=False,
        real_external_mutation=False,
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            "five-step sequence one per surface",
            "required tagline 'Proof Before Mutation' present",
            "Generated is not verified; Working means build/test/smoke passed",
            "negative caveats present (not all apps/languages/production/training)",
        ),
    )


def _block(decision: str, *, seq, haystack, note: str, **kw) -> UnifiedProductSplashDemoSpecRecord:
    return UnifiedProductSplashDemoSpecRecord(
        decision=decision,
        sequence=seq,
        tagline=REQUIRED_TAGLINE,
        required_phrases_present=False,
        required_caveats_present=False,
        happy_path_step_present=False,
        blocked_path_step_present=False,
        teaching_step_present=False,
        proof_view_step_present=False,
        network_required=kw.get("network_required", False),
        docker_required=kw.get("docker_required", False),
        programbench_required=kw.get("pb_required", False),
        real_external_mutation=kw.get("real_ext", False),
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


__all__ = [
    "REQUIRED_TAGLINE",
    "REQUIRED_PHRASES",
    "REQUIRED_NEGATIVE_CAVEATS",
    "canonical_sequence",
    "build_record",
    "UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_STATUS_TOKENS",
    "DemoSequenceStep",
    "UnifiedProductSplashDemoSpecRecord",
]
