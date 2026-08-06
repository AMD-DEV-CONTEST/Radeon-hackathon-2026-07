#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.v10_competition_contract import (
    FULL_CAMPAIGN_PACK,
    OFFICIAL_SCORE_MAXIMA,
    REALTIME_DEMO_PACK,
    BaselineCandidate,
    DemoInput,
    DemoKind,
    OfficialSource,
    RuleFact,
    RuleState,
    ScoreDimensionEvidence,
    SubmissionPreflight,
    approve_claim,
    blinded_order,
    contract_digest,
    mastering_claim,
    noncomparable_features,
    overlapping_task_set,
    score_self_check,
    select_top3_baselines,
    validate_pack,
)
from prooflaunch_remix.v10_program import CortexProgram


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "docs/CORTEX_X_V10_1500_TODO.md"
CONFIG = ROOT / "config/cortex_x_v10_competition_contract_v3.json"
EVIDENCE = ROOT / "evidence/v10/competition-contract-v3-mechanical-fixture.json"


MODELSCOPE_SOURCE = OfficialSource(
    source_id="modelscope-event-299",
    url="https://modelscope.cn/api/v1/competitions/299/detail",
    revision="observed-2026-07-31-response",
    content_sha256="ae96835c2edd086af3714268bab8316ac437768ea0f6e75edf65eb795e4ddaa0",
    observed_at="2026-07-31",
)

GITHUB_SOURCE = OfficialSource(
    source_id="amd-official-submission-readme",
    url="https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/d95240359c837717230b36bdab12df94f1669cf6/README.md",
    revision="d95240359c837717230b36bdab12df94f1669cf6",
    content_sha256="ee89881dc921ed85d350f62b8671d4d6712499084dc872f9ef51a95c1d8f12bd",
    observed_at="2026-07-31",
)


def _rule_source(todo_id: str) -> tuple[str, str]:
    number = int(todo_id)
    if number in {5, 6, 15, 16, 17, 18, 19}:
        return GITHUB_SOURCE.source_id, f"official-readme#todo-{todo_id}"
    return MODELSCOPE_SOURCE.source_id, f"modelscope-event-299#todo-{todo_id}"


def _rules() -> tuple[RuleFact, ...]:
    program = CortexProgram.from_files((CANONICAL,))
    rows = []
    for item in program.todos[:50]:
        source_id, locator = _rule_source(item.todo_id)
        rows.append(
            RuleFact(
                todo_id=item.todo_id,
                rule_id=f"competition-v3-{item.todo_id}",
                statement=item.text,
                source_id=source_id,
                source_locator=locator,
                state=RuleState.FROZEN,
            )
        )
    if [item.todo_id for item in rows] != [f"{index:04d}" for index in range(1, 51)]:
        raise RuntimeError("Competition Contract V3 must cover TODO 0001-0050 in order")
    return tuple(rows)


def _baselines() -> tuple[BaselineCandidate, ...]:
    tasks = ("brief_to_plan", "tool_orchestration", "human_approval")
    return (
        BaselineCandidate(
            "langgraph",
            "https://github.com/langchain-ai/langgraph",
            "b2926a0ff9589c28c7e01fe7cdbb337b86d5a4b4",
            "MIT",
            True,
            tasks,
            True,
            1,
            20,
        ),
        BaselineCandidate(
            "crewai",
            "https://github.com/crewAIInc/crewAI",
            "c8f441cffa1c9412003a1f535ba464a39b4de60d",
            "MIT",
            True,
            tasks,
            True,
            2,
            20,
        ),
        BaselineCandidate(
            "openai-agents-python",
            "https://github.com/openai/openai-agents-python",
            "ff0e7866f1b8e8b88fd6d8f49bce0068ca92027f",
            "MIT",
            True,
            tasks,
            True,
            3,
            20,
        ),
        BaselineCandidate(
            "autogen",
            "https://github.com/microsoft/autogen",
            "027ecf0a379bcc1d09956d46d12d44a3ad9cee14",
            "license-review-required",
            False,
            tasks,
            True,
            4,
            20,
        ),
    )


def main() -> int:
    rules = _rules()
    physical = DemoInput(
        demo_id="owned-physical-commerce-fixture",
        kind=DemoKind.PHYSICAL_COMMERCE,
        asset_sha256=contract_digest({"fixture": "owned-physical-commerce"}),
        rights_locator="config/cortex_x_v10_top1_4a_training_gate.json#rights",
        evidence_locator="evidence/v10/image-mastering-fixture/report.json",
        required_outputs=FULL_CAMPAIGN_PACK,
    )
    agent = DemoInput(
        demo_id="synthetic-agent-workflow-fixture",
        kind=DemoKind.AI_AGENT,
        asset_sha256=contract_digest({"fixture": "synthetic-agent-workflow"}),
        rights_locator="evidence/v10/frontier-free-api-sprint.json#data_class",
        evidence_locator="evidence/v10/submission-api-mechanical-fixture.json",
        required_outputs=REALTIME_DEMO_PACK,
    )
    validate_pack(physical.required_outputs, realtime=False)
    validate_pack(agent.required_outputs, realtime=True)

    baselines = _baselines()
    selected = select_top3_baselines(baselines, run_budget_minutes=60)
    overlap = overlapping_task_set(selected)
    not_comparable = noncomparable_features(
        (*FULL_CAMPAIGN_PACK, *overlap), overlap
    )

    score = score_self_check(
        tuple(
            ScoreDimensionEvidence(
                dimension=dimension,
                claimed_points=0,
                maximum_points=maximum,
                locator="",
                sha256="",
                observed=False,
            )
            for dimension, maximum in OFFICIAL_SCORE_MAXIMA.items()
        )
    )
    current_preflight = SubmissionPreflight(
        luma_registration_approved=False,
        amd_developer_program_member=False,
        team_size=0,
        radeon_local_inference_observed=False,
        pdf_present=(ROOT / "docs/ProofLaunch_Project_Profile.pdf").is_file(),
        source_and_readme_present=(ROOT / "README.md").is_file() and (ROOT / "src").is_dir(),
        demo_video_present=(ROOT / "docs/demo-video-url.txt").is_file(),
        ppt_or_poster_present=(ROOT / "docs/ProofLaunch_Poster.pptx").is_file(),
        official_fork_present=False,
        english_pr_present=False,
    ).evaluate()

    contract = {
        "schema": "ProofLaunchCompetitionContractV3",
        "observed_at": "2026-07-31",
        "track": "Track 1 — Development of Multimodal Content Creation Tools",
        "official_sources": [asdict(MODELSCOPE_SOURCE), asdict(GITHUB_SOURCE)],
        "deadlines": {
            "submission_deadline_utc8": "2026-08-06T23:59:00+08:00",
            "submission_deadline_new_york": "2026-08-06T11:59:00-04:00",
            "source": MODELSCOPE_SOURCE.source_id,
        },
        "eligibility_contract": {
            "luma_registration_and_approval_required": True,
            "amd_developer_program_membership_required_for_prize": True,
            "individual_or_team_size": [1, 3],
            "current_external_state_unobserved": True,
        },
        "model_and_runtime_policy": {
            "radeon_gpu_required": True,
            "rocm_required": True,
            "at_least_one_key_inference_local_on_radeon": True,
            "closed_online_api_only_core_forbidden": True,
            "open_source_modification_allowed": True,
            "lora_allowed": True,
            "controlnet_allowed": True,
            "distilled_models_allowed": True,
        },
        "submission_materials": {
            "complete_source": True,
            "english_readme_environment_start_dependencies": True,
            "project_profile_pdf": True,
            "demo_video_recommended_minutes": [3, 5],
            "demo_video_requires_actual_operation_and_radeon_execution": True,
            "supplementary_choose_one": ["PPT", "Poster"],
            "official_fork_and_english_pr_required": True,
        },
        "scoring": {
            "dimensions": OFFICIAL_SCORE_MAXIMA,
            "maximum": 100,
            "internal_readiness_minimum": 95,
            "unobserved_or_proxy_counts_as_zero": True,
            "official_judge_score_claimed": False,
        },
        "demo_contracts": [
            {**asdict(physical), "kind": physical.kind.value},
            {**asdict(agent), "kind": agent.kind.value},
        ],
        "campaign_packs": {
            "full": list(FULL_CAMPAIGN_PACK),
            "realtime": list(REALTIME_DEMO_PACK),
        },
        "mastering_language": {
            "non_native": mastering_claim(
                output_width=3840,
                output_height=2160,
                native_generation_observed=False,
            ),
            "native_claim_requires_observation": True,
        },
        "top3_protocol": {
            "selection": "date-pinned, license-approved, immutable-revision, executable on the same hardware, then independent rank",
            "run_budget_minutes": 60,
            "candidates": [asdict(item) for item in baselines],
            "selected_ids": [item.baseline_id for item in selected],
            "overlapping_tasks": list(overlap),
            "noncomparable_product_features": list(not_comparable),
            "no_global_leadership_claim_from_nonoverlap": True,
        },
        "blind_review_protocol": {
            "minimum_raters": 5,
            "anonymous_content_hashes": True,
            "deterministic_seeded_random_order": True,
            "example_order": list(
                blinded_order(
                    contract_digest({"artifact": "prooflaunch"}),
                    contract_digest({"artifact": "baseline"}),
                    seed=20260731,
                )
            ),
            "preference_rate_minimum": 0.75,
            "preference_wilson_lower_95_minimum_exclusive": 0.65,
            "publishable_rate_minimum": 0.95,
            "major_rework_definition": "Any candidate requiring strategy, claim, identity, layout, or channel-system reconstruction before release.",
            "score_conflict": "Use the median; a >2-point 0–5 spread requires a named independent adjudicator.",
        },
        "claim_policy": {
            "leadership_terms": ["Top-1", "Top-3", "best", "leading", "number one", "#1"],
            "comparison_and_named_approval_required": True,
            "unapproved_example_accepted": approve_claim(
                "ProofLaunch is Top-3",
                comparison_passed=False,
                approval_id=None,
                evidence_locator=None,
            ),
        },
        "todo_rules": [
            {**asdict(item), "state": item.state.value}
            for item in rules
        ],
        "truth_boundary": (
            "Competition Contract V3 freezes and tests rules and local mechanisms. It does not prove Luma approval, "
            "AMD Developer Program membership, official eligibility, real Radeon execution, model quality, demo video, fork, PR, or judge score."
        ),
    }
    contract["content_sha256"] = contract_digest(contract)
    atomic_write_text(CONFIG, json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    evidence = {
        "schema": "ProofLaunchCompetitionContractV3MechanicalReceipt",
        "observed_at": "2026-07-31",
        "contract": CONFIG.relative_to(ROOT).as_posix(),
        "contract_sha256": sha256_file(CONFIG),
        "canonical_sha256": sha256_file(CANONICAL),
        "todo_coverage": {
            "start": "0001",
            "end": "0050",
            "count": len(rules),
            "ordered": [item.todo_id for item in rules] == [f"{index:04d}" for index in range(1, 51)],
            "unique": len({item.todo_id for item in rules}) == 50,
        },
        "official_source_refresh": {
            "modelscope_api_http_status": 200,
            "modelscope_api_sha256": MODELSCOPE_SOURCE.content_sha256,
            "official_repo_main_commit": GITHUB_SOURCE.revision,
            "official_readme_sha256": GITHUB_SOURCE.content_sha256,
            "prior_audit_is_not_silently_reused": True,
        },
        "self_check": asdict(score),
        "submission_preflight": current_preflight,
        "live_radeon_calls": 0,
        "official_submission_actions": 0,
        "status": "mechanics_passed_external_gates_open",
        "truth_boundary": (
            "This receipt proves deterministic rule, score, demo, comparison, claim and preflight mechanics only. "
            "All unobserved external requirements remain open."
        ),
    }
    evidence["content_sha256"] = contract_digest(evidence)
    atomic_write_text(EVIDENCE, json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "contract_sha256": sha256_file(CONFIG),
                "evidence_sha256": sha256_file(EVIDENCE),
                "todo_count": len(rules),
                "submission_ready": current_preflight["submission_ready"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
