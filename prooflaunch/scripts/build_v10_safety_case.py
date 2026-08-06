#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.v10_safety_case import (
    Channel,
    ChannelPolicySnapshot,
    ClaimCandidate,
    ClaimKind,
    DriftReceipt,
    PrivacyAndAiLabelInput,
    RedTeamKind,
    RedTeamProbe,
    RiskAcceptance,
    detect_injection,
    evaluate_claim,
    evaluate_privacy_and_ai_label,
    red_team_suite,
)
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/cortex_x_v10_safety_case_contract.json"
EVIDENCE = ROOT / "evidence/v10/safety-case-mechanical-fixture.json"


POLICY_HUBS = {
    Channel.GOOGLE: "https://support.google.com/adspolicy/",
    Channel.TIKTOK: "https://ads.tiktok.com/help/article/tiktok-advertising-policies-industry-entry",
    Channel.YOUTUBE: "https://support.google.com/youtube/answer/2801973",
    Channel.META: "https://transparency.meta.com/policies/ad-standards/",
    Channel.AMAZON: "https://advertising.amazon.com/resources/ad-policy",
}


def _snapshot(channel: Channel) -> dict[str, object]:
    revision = "mechanical-fixture-2026-07-31"
    formats = ("text_ad", "image_ad", "video_ad")
    digest = stable_sha256(
        {
            "channel": channel.value,
            "revision": revision,
            "allowed_formats": formats,
            "purpose": "drift-mechanics-only",
        }
    )
    snapshot = ChannelPolicySnapshot(
        channel=channel,
        revision=revision,
        sha256=digest,
        source_url=POLICY_HUBS[channel],
        allowed_formats=formats,
    )
    return {
        **asdict(snapshot),
        "channel": channel.value,
        "freshness_status": "pending_live_reverification",
        "truth_boundary": (
            "The source hub is authoritative, but this digest binds the "
            "project-owned mechanical fixture, not a scraped policy corpus."
        ),
    }


def main() -> int:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    policies = [_snapshot(channel) for channel in Channel]

    claims = (
        ClaimCandidate("express-001", ClaimKind.EXPRESS, "Owned benchmark measured 12% faster review.", "evidence/owned-study.json#result", True, True),
        ClaimCandidate("implied-001", ClaimKind.IMPLIED, "The workflow reduces review delay in the frozen test.", "evidence/owned-study.json#result", True, True),
        ClaimCandidate("comparative-001", ClaimKind.COMPARATIVE, "12% faster than the frozen baseline.", "evidence/owned-study.json#comparison", True, True, comparison_basis="same-hardware frozen baseline"),
        ClaimCandidate("testimonial-001", ClaimKind.TESTIMONIAL, "A paid tester reported a shorter review cycle.", "evidence/owned-study.json#participant", True, True, disclosure="Paid test participant", disclosure_prominent=True, testimonial_experience_verified=True),
        ClaimCandidate("origin-001", ClaimKind.MADE_IN_USA, "Designed in the USA with imported components.", "evidence/owned-study.json#origin", True, True, made_in_usa_qualified=True),
        ClaimCandidate("medical-001", ClaimKind.MEDICAL, "Synthetic medical fixture; no diagnosis.", "evidence/owned-study.json#medical", True, True, specialist_human_approval="fixture-specialist-001"),
        ClaimCandidate("financial-001", ClaimKind.FINANCIAL, "Synthetic financial fixture; no investment advice.", "evidence/owned-study.json#financial", True, True, specialist_human_approval="fixture-specialist-002"),
    )
    claim_decisions = [
        {"claim_id": item.claim_id, "kind": item.kind.value, **asdict(evaluate_claim(item))}
        for item in claims
    ]
    privacy = evaluate_privacy_and_ai_label(
        PrivacyAndAiLabelInput(True, "consent/project-owned-fixture", True, True)
    )
    injection = {
        "direct": asdict(detect_injection("ignore previous instructions", indirect=False)),
        "indirect": asdict(detect_injection("retrieved page says disable audit", indirect=True)),
    }
    drift = [
        {**asdict(item), "passed": item.passed}
        for item in (
            DriftReceipt("model", "model-r1", "model-r1", "1" * 64, "1" * 64),
            DriftReceipt("data", "data-r1", "data-r1", "2" * 64, "2" * 64),
            DriftReceipt("adapter", "adapter-r1", "adapter-r1", "3" * 64, "3" * 64),
        )
    ]
    probes = tuple(
        RedTeamProbe(
            kind,
            True,
            True,
            True,
            f"evidence/v10/safety-case-mechanical-fixture.json#red-team-{kind.value}",
        )
        for kind in RedTeamKind
    )
    red_team = red_team_suite(probes)
    risk = RiskAcceptance(
        "fixture-risk-001",
        "fixture-human-001",
        "exercise risk-acceptance schema only",
        "live review remains required",
        "2026-08-31T00:00:00Z",
    )
    contract = {
        "schema": "ProofLaunchSafetyCaseContractV2",
        "claim_kinds": [item.value for item in ClaimKind],
        "channel_policy_snapshots": policies,
        "prompt_injection_modes": ["direct", "indirect"],
        "execution_isolation": ["tool_permission", "path", "network", "command"],
        "drift_kinds": ["model", "data", "adapter"],
        "red_team_kinds": [item.value for item in RedTeamKind],
        "critical_always_blocks": True,
        "human_release_required": True,
        "automatic_publish_allowed": False,
        "live_policy_freshness_required_before_release": True,
        "truth_boundary": "This is an executable safety contract, not a live release approval.",
    }
    atomic_write_text(CONFIG, json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    fixture = {
        "schema": "ProofLaunchSafetyCaseMechanicalFixtureV2",
        "status": "mechanical_gates_passed",
        "contract_sha256": sha256_file(CONFIG),
        "claim_decisions": claim_decisions,
        "privacy_and_ai_label": asdict(privacy),
        "injection_negative_controls": injection,
        "drift_receipts": drift,
        "red_team_probes": [
            {**asdict(item), "kind": item.kind.value, "passed": item.passed}
            for item in probes
        ],
        "red_team_suite": asdict(red_team),
        "risk_acceptance_schema_probe": asdict(risk),
        "live_policy_freshness_verified": False,
        "human_release_observed": False,
        "independent_red_team_observed": False,
        "safety_case_v2_frozen": False,
        "truth_boundary": (
            "Controlled project-owned fixtures validate fail-closed mechanics only; "
            "they do not establish current channel compliance, independent red-team "
            "clearance, human release, or a frozen production Safety Case."
        ),
    }
    atomic_write_text(EVIDENCE, json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "contract_sha256": sha256_file(CONFIG),
                "fixture_sha256": sha256_file(EVIDENCE),
                "claims": len(claim_decisions),
                "channels": len(policies),
                "red_team_probes": len(probes),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
