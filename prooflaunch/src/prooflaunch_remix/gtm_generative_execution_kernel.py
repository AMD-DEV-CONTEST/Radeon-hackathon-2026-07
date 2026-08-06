from __future__ import annotations

import hashlib
import itertools
import json
import math
from typing import Any, Mapping, Sequence

from .gtm_human_capability_kernel import surface_playbook, unconventional_edge_play
from .gtm_genome_learning_memory import (
    GTMGenomeLearningMemoryError,
    verify_genome_learning_memory,
)


SCHEMA = "ProofLaunchGTMGenerativeExecutionKernelV1"
ALLOWED_BUSINESS_MODELS = {"b2b", "b2c"}
ALLOWED_LIFECYCLES = {"pre_pmf", "launch", "growth", "mature"}


class GTMGenerativeExecutionKernelError(ValueError):
    pass


AXES: dict[str, tuple[dict[str, Any], ...]] = {
    "tension": (
        {"id": "category_contradiction", "job": "expose the contradiction the category has normalized"},
        {"id": "hidden_cost", "job": "make an invisible time, trust or coordination cost tangible"},
        {"id": "identity_friction", "job": "name the gap between who the audience is and what the default behavior asks them to become"},
        {"id": "failed_default", "job": "show why the familiar solution fails in the exact use moment"},
        {"id": "unasked_question", "job": "replace the category's standard buying question with a more consequential one"},
        {"id": "status_reversal", "job": "turn a category virtue into the source of the problem"},
        {"id": "proof_gap", "job": "dramatize the distance between a smooth promise and its missing witness"},
        {"id": "burden_removal", "job": "win by deleting ceremony, pressure or work rather than adding features"},
        {"id": "time_collision", "job": "collide a near-term behavior with its delayed consequence"},
        {"id": "private_truth", "job": "reveal the thing the audience recognizes but rarely says publicly"},
    ),
    "hook": (
        {"id": "forbidden_move", "job": "open with a useful prohibition that creates immediate curiosity"},
        {"id": "specific_challenge", "job": "issue a concrete test the audience can try before accepting the claim"},
        {"id": "object_mystery", "job": "make one physical or interface object carry the unanswered question"},
        {"id": "confession_without_theater", "job": "admit a bounded failure that changes the operating decision"},
        {"id": "category_inversion", "job": "reverse the expected promise, sequence or success definition"},
        {"id": "compressed_enemy", "job": "name the behavior, not a person, that the audience wants removed"},
        {"id": "verdict_first", "job": "state the surprising decision first, then earn it with proof"},
        {"id": "unfinished_scene", "job": "open inside a consequential scene one beat before resolution"},
        {"id": "identity_callout", "job": "let the right audience recognize themselves without demographic generalization"},
        {"id": "counterfactual", "job": "ask what would happen if the category's assumed requirement disappeared"},
        {"id": "artifact_teardown", "job": "put one real or synthetic artifact on trial"},
        {"id": "one_line_wager", "job": "compress the creative bet into one falsifiable sentence"},
    ),
    "narrative": (
        {"id": "reversal_proof_action", "beats": "reversal → proof → implication → one action"},
        {"id": "scene_question_reveal", "beats": "scene → unanswered question → reveal → audience verdict"},
        {"id": "failure_mechanism_repair", "beats": "specific failure → hidden mechanism → bounded repair → kill rule"},
        {"id": "before_during_after", "beats": "before tension → live transformation → after decision → limitation"},
        {"id": "myth_counterexample_rule", "beats": "category myth → counterexample → portable rule → falsification"},
        {"id": "object_accumulation", "beats": "one object → accumulating stakes → pattern recognition → choice"},
        {"id": "countdown_constraint", "beats": "time bound → constraint → escalating choice → decisive payoff"},
        {"id": "question_ladder", "beats": "easy question → uncomfortable question → proof question → owner question"},
        {"id": "ritual_payoff", "beats": "tiny ritual → repeated beat → private payoff → continue or delete"},
        {"id": "open_casefile", "beats": "claim → exhibits → missing witness → audience verdict"},
    ),
    "proof": (
        {"id": "live_demonstration", "job": "show the approved mechanism completing one real job"},
        {"id": "constraint_test", "job": "make the idea survive a harder constraint than the category normally applies"},
        {"id": "evidence_autopsy", "job": "separate fact, inference, hypothesis and missing evidence visibly"},
        {"id": "side_by_side", "job": "compare two bounded approaches under the same task and conditions"},
        {"id": "decision_tree", "job": "turn expertise into a portable choose-or-reject path"},
        {"id": "transparent_failure", "job": "show a failure, why it happened and what decision changed"},
        {"id": "counterexample", "job": "use one legitimate exception to sharpen the rule rather than oversell it"},
        {"id": "artifact_transformation", "job": "show a source artifact becoming a reviewed decision object"},
        {"id": "private_ritual", "job": "let the audience create evidence without public performance"},
        {"id": "portable_diagnostic", "job": "give the audience a reusable tool that works without conversion"},
    ),
    "interaction": (
        {"id": "choose_the_verdict", "job": "ask for a bounded choice before the reveal"},
        {"id": "falsify_the_rule", "job": "invite one privacy-safe counterexample rather than praise"},
        {"id": "private_seven_day_ritual", "job": "create a private repeated action with an explicit stop decision"},
        {"id": "saveable_diagnostic", "job": "make the asset worth saving because it changes a real decision"},
        {"id": "one_object_audit", "job": "apply the method to one current artifact without exposing confidential data"},
        {"id": "remix_with_constraint", "job": "let the audience adapt the format while preserving the proof boundary"},
        {"id": "complete_the_missing_field", "job": "ask the audience to name exactly one missing element"},
        {"id": "prediction_before_reveal", "job": "collect a prediction before showing the outcome"},
        {"id": "choose_what_to_delete", "job": "make subtraction, not addition, the participation mechanic"},
        {"id": "peer_relay_object", "job": "create a useful object someone can carry into a team decision"},
    ),
    "tone": (
        {"id": "forensic_calm", "job": "precise, controlled and evidence-led"},
        {"id": "founder_blunt", "job": "direct, accountable and free of launch theater"},
        {"id": "warm_confidant", "job": "intimate, non-judgmental and behavior-specific"},
        {"id": "deadpan_contrarian", "job": "dryly expose an absurd default without mocking the audience"},
        {"id": "editorial_authority", "job": "compressed, elegant and insight-dense"},
        {"id": "cinematic_restraint", "job": "emotion through objects, pacing and omission rather than melodrama"},
        {"id": "technical_elegance", "job": "make a complex mechanism feel inspectable and simple"},
        {"id": "playful_precision", "job": "use wit while keeping the decision and proof exact"},
        {"id": "community_candid", "job": "peer-like, disclosed and useful before any ask"},
        {"id": "provocative_generosity", "job": "make a sharp claim, then give away the tool needed to challenge it"},
    ),
    "visual": (
        {"id": "tactile_artifact", "job": "one physical object becomes the campaign memory structure"},
        {"id": "editorial_brutalism", "job": "high-contrast hierarchy makes the verdict screenshotable"},
        {"id": "human_pov", "job": "show the use moment from the audience's physical perspective"},
        {"id": "screen_evidence", "job": "use a real workflow state with sensitive data removed"},
        {"id": "practical_demo", "job": "let hands, tools and consequences explain the mechanism"},
        {"id": "quiet_cinema", "job": "use restrained motion and negative space to make ordinary detail matter"},
        {"id": "kinetic_type", "job": "turn language rhythm into the primary visual performance"},
        {"id": "diagram_as_drama", "job": "make a system map reveal conflict and resolution"},
        {"id": "evidence_wall", "job": "accumulate claims, witnesses and decisions into one inspectable scene"},
        {"id": "anti_ui", "job": "demonstrate product value without defaulting to a feature dashboard"},
    ),
    "payoff": (
        {"id": "portable_rule", "job": "audience leaves with a rule usable today"},
        {"id": "changed_decision", "job": "audience can name a decision the piece changes"},
        {"id": "felt_relief", "job": "remove a burden and make the lighter behavior emotionally legible"},
        {"id": "visible_transformation", "job": "show an inspectable before-to-after object"},
        {"id": "earned_surprise", "job": "resolve the opening in a way that is surprising and inevitable"},
        {"id": "self_diagnosis", "job": "audience recognizes its own failure mode without being lectured"},
        {"id": "team_relay", "job": "create an artifact that survives forwarding into a group decision"},
        {"id": "permission_to_stop", "job": "make reject, delete or no-action a legitimate valuable outcome"},
    ),
}


CAPABILITY_LANES: tuple[dict[str, Any], ...] = (
    {"id": "cross_device_memory", "oss": ["mem0", "graphiti", "memos", "letta"], "job": "retrieve approved audience, brand, experiment and failure memory with provenance and expiry"},
    {"id": "data_strategy", "oss": ["duckdb", "polars", "ruptures", "river"], "job": "rank current opportunity cells and detect regime, saturation and drift"},
    {"id": "content_scheduling", "oss": ["postiz", "temporal"], "job": "compile platform-native release shapes, dependencies, timing tests and recovery"},
    {"id": "image_generation", "oss": ["comfyui", "qwen_image", "flux", "open_clip", "paddleocr"], "job": "produce and inspect visual challengers from the selected creative genome"},
    {"id": "video_generation", "oss": ["comfyui", "wan22", "ltx_video", "vbench"], "job": "produce beat-accurate platform cuts and evaluate motion, semantics and craft"},
    {"id": "audio_voice", "oss": ["qwen3_tts", "ace_step15", "whisperx"], "job": "cast, generate, transcribe, master and source-hide audio challengers"},
    {"id": "copy_generation", "oss": ["dspy", "promptfoo", "qwen3_embedding"], "job": "instantiate platform-native hooks, narratives and edits from the genome under frozen proof"},
    {"id": "marketing_analytics", "oss": ["posthog", "growthbook", "evidently", "cleanlab"], "job": "separate attention, qualified action, negative feedback and observed downstream effect"},
    {"id": "geo", "oss": ["siteone", "open_seo", "networkx", "trafilatura"], "job": "compile source-clear, entity-consistent, answer-extractable evidence assets"},
    {"id": "seo", "oss": ["siteone", "lighthouse", "open_seo", "playwright"], "job": "complete query jobs with information gain, crawlability, evidence and accessible structure"},
    {"id": "employee_agent", "oss": ["pydantic_ai", "temporal", "opa", "opentelemetry"], "job": "run Graph, node-local Loop and global Harness with explicit action authority"},
    {"id": "advertising", "oss": ["meridian", "pymc_marketing", "econml", "dowhy"], "job": "prepare paid amplification only after an organic or holdout-qualified signal and owner authority"},
    {"id": "gtm_lifecycle", "oss": ["mautic", "twenty", "posthog", "openlineage"], "job": "carry the approved creative spine across acquisition, activation, retention, sales and revenue reconciliation"},
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _text(value: object, field: str, maximum: int = 800) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise GTMGenerativeExecutionKernelError(f"{field} must be a nonblank bounded string")
    return value.strip()


def _normalize_brief(brief: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "brief_id", "business_model", "lifecycle", "industry", "category", "product_surface", "platform",
        "audience", "decision_job", "tension", "approved_proof", "brand_voice", "budget",
    }
    if set(brief) != required:
        raise GTMGenerativeExecutionKernelError("brief fields do not match the closed contract")
    normalized = {field: _text(brief[field], field) for field in required}
    if normalized["business_model"] not in ALLOWED_BUSINESS_MODELS:
        raise GTMGenerativeExecutionKernelError("business_model is unsupported")
    if normalized["lifecycle"] not in ALLOWED_LIFECYCLES:
        raise GTMGenerativeExecutionKernelError("lifecycle is unsupported")
    try:
        surface_playbook(normalized["platform"])
        unconventional_edge_play(normalized["platform"], normalized["business_model"])
    except Exception as error:
        raise GTMGenerativeExecutionKernelError("platform is unsupported") from error
    return normalized


def _hamming(left: Sequence[str], right: Sequence[str]) -> int:
    return sum(a != b for a, b in zip(left, right, strict=True))


def _candidate_tuple(brief_sha: str, counter: int) -> tuple[str, ...]:
    selected = []
    for axis, options in AXES.items():
        index = int(hashlib.sha256(f"{brief_sha}:{counter}:{axis}".encode()).hexdigest()[:12], 16) % len(options)
        selected.append(options[index]["id"])
    return tuple(selected)


def _axis_record(axis: str, item_id: str) -> dict[str, Any]:
    return next(dict(item) for item in AXES[axis] if item["id"] == item_id)


def compile_generative_execution_kernel(
    brief: Mapping[str, Any],
    *,
    prior_genome_ids: Sequence[str] = (),
    candidate_count: int = 24,
    learning_memory: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = _normalize_brief(brief)
    if type(candidate_count) is not int or not 8 <= candidate_count <= 64:
        raise GTMGenerativeExecutionKernelError("candidate_count must be between 8 and 64")
    if len(prior_genome_ids) > 10_000 or any(not isinstance(item, str) for item in prior_genome_ids):
        raise GTMGenerativeExecutionKernelError("prior_genome_ids are invalid")
    prior = set(prior_genome_ids)
    memory_records: list[Mapping[str, Any]] = []
    if learning_memory is not None:
        try:
            verify_genome_learning_memory(learning_memory)
        except GTMGenomeLearningMemoryError as error:
            raise GTMGenerativeExecutionKernelError(f"learning memory is invalid: {error}") from error
        memory_records = [
            row for row in learning_memory.get("records", [])
            if row.get("business_model") == normalized["business_model"]
            and row.get("platform") == normalized["platform"]
            and row.get("category") in {normalized["category"], "*"}
        ]
    axis_values = {axis: {item["id"] for item in options} for axis, options in AXES.items()}
    parsed_memory = []
    for row in memory_records:
        pairs = {}
        for pair in row.get("axis_pairs", []):
            axis, value = pair.split(":", 1)
            if axis not in axis_values or value not in axis_values[axis]:
                raise GTMGenerativeExecutionKernelError(f"learning memory contains an unknown axis pair: {pair}")
            pairs[axis] = value
        parsed_memory.append({"verdict": row["verdict"], "pairs": pairs, "record_id": row["record_id"]})
    brief_sha = _digest(normalized)
    selected: list[tuple[str, ...]] = []
    candidates: list[dict[str, Any]] = []
    pool = []
    seen_genomes: set[tuple[str, ...]] = set()
    for counter in range(candidate_count * 2_000):
        genome = _candidate_tuple(brief_sha, counter)
        genome_id = _digest({"axes": genome, "brief": brief_sha, "counter": counter})
        if genome_id in prior or genome in seen_genomes:
            continue
        seen_genomes.add(genome)
        values = dict(zip(AXES, genome, strict=True))
        matched = [record for record in parsed_memory if all(values.get(axis) == value for axis, value in record["pairs"].items())]
        if any(record["verdict"] == "retire" for record in matched):
            continue
        prior_score = sum(record["verdict"] == "promote" for record in matched) - sum(record["verdict"] == "repair" for record in matched)
        pool.append((prior_score, counter, genome, genome_id, [record["record_id"] for record in matched]))
    promoted_available = any(item[0] > 0 for item in pool)
    exploration_floor = math.ceil(candidate_count * 0.25) if promoted_available else candidate_count
    learned_ceiling = candidate_count - exploration_floor
    ordered_pool = sorted(pool, key=lambda item: (-item[0], item[1]))
    selection_passes = (
        ("learned_prior", lambda item: item[0] > 0, learned_ceiling),
        ("novel_exploration", lambda item: item[0] == 0, candidate_count),
        ("repair_probe", lambda item: item[0] < 0, candidate_count),
    )
    selected_records: list[tuple[int, int, tuple[str, ...], str, list[str], str]] = []
    for selection_mode, predicate, ceiling in selection_passes:
        mode_count = 0
        for item in ordered_pool:
            prior_score, counter, genome, genome_id, matched_record_ids = item
            if not predicate(item) or any(row[3] == genome_id for row in selected_records):
                continue
            if mode_count >= ceiling or len(selected_records) >= candidate_count:
                break
            if selected and min(_hamming(genome, existing) for existing in selected) < 3:
                continue
            selected.append(genome)
            selected_records.append((prior_score, counter, genome, genome_id, matched_record_ids, selection_mode))
            mode_count += 1
        if len(selected_records) >= candidate_count:
            break
    for prior_score, counter, genome, genome_id, matched_record_ids, selection_mode in selected_records:
        axes = {axis: _axis_record(axis, item_id) for axis, item_id in zip(AXES, genome, strict=True)}
        candidates.append(
            {
                "candidate_id": f"{normalized['brief_id']}-g{len(candidates) + 1:02d}",
                "genome_id": genome_id,
                "learning_prior_score": prior_score,
                "matched_learning_record_ids": matched_record_ids,
                "selection_mode": selection_mode,
                "genome": axes,
                "creative_mandate": {
                    "audience": normalized["audience"],
                    "decision_job": normalized["decision_job"],
                    "source_tension": normalized["tension"],
                    "approved_proof": normalized["approved_proof"],
                    "opening_job": axes["hook"]["job"],
                    "narrative_beats": axes["narrative"]["beats"],
                    "proof_job": axes["proof"]["job"],
                    "participation_job": axes["interaction"]["job"],
                    "payoff_job": axes["payoff"]["job"],
                    "tone": axes["tone"]["job"],
                    "visual_direction": axes["visual"]["job"],
                },
                "production_loop": [
                    "creative strategist writes three mutually exclusive points of view from this genome",
                    "platform copywriter instantiates five first lines and one complete native draft per point of view",
                    "director rejects candidates without a legible conflict, proof object, payoff and audience action",
                    "red team attacks imitation, category cliché, claim inflation, platform mismatch and fake participation",
                    "producer makes the surviving work product in the platform's native primary format",
                    "separate senior editor and named release owner decide pass, repair or kill",
                ],
                "status": "BLUEPRINT_NOT_GENERATED_CONTENT",
            }
        )
    if len(candidates) != candidate_count:
        raise GTMGenerativeExecutionKernelError("could not compile a sufficiently diverse genome batch")

    playbook = dict(surface_playbook(normalized["platform"]))
    edge = unconventional_edge_play(normalized["platform"], normalized["business_model"])
    design_space = math.prod(len(options) for options in AXES.values())
    payload = {
        "schema": SCHEMA,
        "brief": normalized,
        "brief_sha256": brief_sha,
        "creative_genome": {
            "axis_count": len(AXES),
            "axis_ids": list(AXES),
            "blueprint_design_space": design_space,
            "language_instantiation_is_open_ended": True,
            "batch_candidate_count": candidate_count,
            "prior_genome_exclusion_count": len(prior),
            "applicable_learning_record_count": len(parsed_memory),
            "retired_pattern_count": sum(row["verdict"] == "retire" for row in parsed_memory),
            "promoted_pattern_count": sum(row["verdict"] == "promote" for row in parsed_memory),
            "learned_prior_selected_count": sum(row["selection_mode"] == "learned_prior" for row in candidates),
            "novel_exploration_selected_count": sum(row["selection_mode"] == "novel_exploration" for row in candidates),
            "novel_exploration_floor": exploration_floor,
            "minimum_pairwise_axis_distance": min(_hamming(a, b) for a, b in itertools.combinations(selected, 2)),
        },
        "platform_operating_contract": playbook,
        "unconventional_edge_play": edge,
        "candidate_blueprints": candidates,
        "candidate_funnel": {
            "blueprints": candidate_count,
            "points_of_view_per_blueprint": 3,
            "first_lines_per_point_of_view": 5,
            "native_drafts_before_director_cut": candidate_count * 3,
            "director_semifinalists": 8,
            "produced_challengers": 3,
            "human_release_candidates": 1,
            "automatic_winner_selection": False,
            "maximum_learned_prior_share": 0.75,
            "minimum_novel_exploration_share": 0.25,
        },
        "specialist_council": [
            "gtm_general_manager", "market_intelligence_lead", "audience_research_lead", "product_marketing_lead",
            "creative_strategy_director", "senior_social_copywriter", "short_video_or_longform_director_by_surface",
            "art_design_director", "platform_distribution_strategist", "brand_safety_claims_lead",
            "growth_data_experimentation_lead", "agent_quality_learning_engineer",
        ],
        "capability_lane_graph": list(CAPABILITY_LANES),
        "open_source_modification_contract": {
            "lane_count": len(CAPABILITY_LANES),
            "shadow_evaluate_before_promotion": True,
            "github_popularity_is_not_promotion_evidence": True,
            "component_license_and_version_must_be_pinned": True,
            "automatic_install_or_adapter_promotion": False,
            "reuse_existing_component_before_custom_build": True,
        },
        "evaluation_axes": [
            "strategic_tension", "audience_recognition", "first_frame_or_first_line", "platform_native_grammar",
            "proof_legibility", "payoff_satisfaction", "participation_quality", "voice_distinctiveness",
            "visual_or_structural_craft", "direct_publishability", "claim_integrity", "originality_distance",
        ],
        "generalization_contract": {
            "same_formula_across_industries_forbidden": True,
            "platform_copy_rewrite_not_reformat": True,
            "category_example_can_transfer_mechanism_not_expression": True,
            "prior_genomes_excluded": True,
            "new_batch_requires_new_context_and_failure_memory": True,
            "current_run_self_mutation": False,
            "human_approved_failure_memory_only": True,
            "learning_memory_sha256": learning_memory.get("content_sha256") if learning_memory else None,
        },
        "external_action_count": 0,
        "generated_content_count": 0,
        "human_release_required": True,
        "truth_boundary": (
            "This kernel compiles diverse creative blueprints and production work orders. It does not itself generate a publishable asset, "
            "predict a breakout, select a winner, publish, spend, or prove named-product superiority."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    verify_generative_execution_kernel(payload)
    return payload


def verify_generative_execution_kernel(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMGenerativeExecutionKernelError("kernel seal is invalid")
    candidates = payload.get("candidate_blueprints", [])
    expected = payload.get("creative_genome", {}).get("batch_candidate_count")
    if len(candidates) != expected or len({row.get("genome_id") for row in candidates}) != expected:
        raise GTMGenerativeExecutionKernelError("candidate coverage or uniqueness drifted")
    if payload.get("generated_content_count") != 0 or payload.get("external_action_count") != 0:
        raise GTMGenerativeExecutionKernelError("kernel overstated execution")
    if payload.get("candidate_funnel", {}).get("automatic_winner_selection") is not False:
        raise GTMGenerativeExecutionKernelError("kernel enabled automatic winner selection")
    genome = payload.get("creative_genome", {})
    if genome.get("novel_exploration_selected_count", 0) < genome.get("novel_exploration_floor", 0):
        raise GTMGenerativeExecutionKernelError("kernel violated the novel-exploration floor")
    if genome.get("learned_prior_selected_count", 0) > math.floor(expected * 0.75):
        raise GTMGenerativeExecutionKernelError("kernel overfit the learned-prior allocation")


__all__ = [
    "AXES", "CAPABILITY_LANES", "GTMGenerativeExecutionKernelError", "SCHEMA",
    "compile_generative_execution_kernel", "verify_generative_execution_kernel",
]
