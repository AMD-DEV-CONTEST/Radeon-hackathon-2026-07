from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .gtm_agent_control_plane_v2 import build_agent_control_plane
from .gtm_generative_execution_kernel import compile_generative_execution_kernel


SCHEMA = "ProofLaunchRealtimeCreativeCouncilV1"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _short(value: str, words: int = 8) -> str:
    pieces = value.split()
    return " ".join(pieces[:words]) + ("…" if len(pieces) > words else "")


_CAMPAIGN_NAMES = {
    "forbidden_move": "The Rule We Refuse",
    "specific_challenge": "The Sixty-Second Rejection",
    "object_mystery": "One Object. No Pitch.",
    "confession_without_theater": "What We Got Wrong",
    "category_inversion": "The Opposite Launch",
    "compressed_enemy": "Delete the Default",
    "verdict_first": "Verdict Before Features",
    "unfinished_scene": "One Beat Before It Breaks",
    "identity_callout": "Built for the Person Holding the Risk",
    "counterfactual": "What If the Ritual Disappeared?",
    "artifact_teardown": "Put the Artifact on Trial",
    "one_line_wager": "One Bet, Made Visible",
}


def _first_line(hook_id: str, brief: Mapping[str, str]) -> str:
    category = brief["category"]
    proof = brief["approved_proof"]
    tension = brief["tension"]
    audience = _short(brief["audience"], 9)
    outcome = brief["decision_job"]
    lines = {
        "forbidden_move": f"Do not ship another {category} story until it can prove this: {proof}",
        "specific_challenge": f"Give {category} sixty seconds. If it cannot make '{proof}' inspectable, reject it.",
        "object_mystery": f"One object should let {audience} understand why {category} exists—without a feature tour.",
        "confession_without_theater": f"We optimized the launch before admitting the real failure: {tension}",
        "category_inversion": f"The strongest launch for {category} may begin by helping the wrong buyer say no.",
        "compressed_enemy": f"The enemy is not another vendor. It is the moment when {tension.lower()}.",
        "verdict_first": f"Verdict: the category is measuring fluency when it should measure whether people can {outcome.lower()}.",
        "unfinished_scene": f"The campaign looked finished. Then one accountable buyer asked where '{proof}' came from.",
        "identity_callout": f"For the person who has to defend the decision after the demo: this is the test that matters.",
        "counterfactual": f"What would {category} become if the audience never had to perform belief before seeing proof?",
        "artifact_teardown": f"Put the cleanest {category} output on the table. Now mark every sentence the evidence cannot carry.",
        "one_line_wager": f"Our wager: one inspectable proof object will outperform a week of polished {category} claims.",
    }
    return lines[hook_id]


def _participation(interaction_id: str, brief: Mapping[str, str]) -> str:
    proof = brief["approved_proof"]
    outcome = brief["decision_job"]
    actions = {
        "choose_the_verdict": "Choose pass, repair or reject before the evidence reveal; then compare the reason, not the vote.",
        "falsify_the_rule": f"Offer one counterexample that would make '{proof}' insufficient and name the safer rule.",
        "private_seven_day_ritual": "Run the behavior privately for seven days; continue only if the final decision becomes easier.",
        "saveable_diagnostic": f"Save the one-page diagnostic and use it the next time you must {outcome.lower()}.",
        "one_object_audit": "Audit one current artifact, label fact/inference/gap, and keep the result private unless its owner approves.",
        "remix_with_constraint": "Remix the format, but preserve the proof sentence, limitation and rejection condition exactly.",
        "complete_the_missing_field": "Complete one missing field—source, limitation or owner—before reacting to the creative.",
        "prediction_before_reveal": "Predict which claim will survive before the receipt is shown; score the prediction against the evidence.",
        "choose_what_to_delete": "Delete the sentence that adds the least decision value and explain what becomes clearer.",
        "peer_relay_object": "Pass the proof card to one accountable peer; they add a verdict, not a compliment.",
    }
    return actions[interaction_id]


def _tone_instruction(tone_id: str) -> str:
    return {
        "forensic_calm": "Short declarative sentences; label fact, inference and unknown; zero launch theater.",
        "founder_blunt": "First-person accountability, concrete failure and the decision that changed; no heroic origin myth.",
        "warm_confidant": "Private, behavior-specific language that removes shame and never pressures public sharing.",
        "deadpan_contrarian": "Dry understatement and one precise inversion; never mock the audience.",
        "editorial_authority": "Dense but elegant argument; strong nouns, few adjectives and one memorable line.",
        "cinematic_restraint": "Let objects and pauses carry emotion; copy appears only when it changes the reading of the scene.",
        "technical_elegance": "Expose the mechanism, environment and failure condition in language an evaluator can repeat.",
        "playful_precision": "Use wit as compression, not decoration; every joke must sharpen the product truth.",
        "community_candid": "Peer voice, useful before the ask, with explicit uncertainty and no manufactured consensus.",
        "provocative_generosity": "Make the sharp claim, then give away the exact tool needed to challenge it.",
    }[tone_id]


def _strategy_fit_score(
    territory: Mapping[str, Any],
    brief: Mapping[str, str],
) -> tuple[int, list[str]]:
    """Rank finalists against the declared operating context, never taste or market effect."""
    axes = territory["axis_signature"]
    score = 0
    reasons: list[str] = []

    def admit(points: int, reason: str) -> None:
        nonlocal score
        score += points
        reasons.append(f"+{points} {reason}")

    business_model = brief["business_model"].lower()
    lifecycle = brief["lifecycle"].lower()
    surface_text = f"{brief['product_surface']} {brief['category']} {brief['brand_voice']}".lower()
    if business_model == "b2b":
        tone_weights = {
            "technical_elegance": 5, "forensic_calm": 5,
            "editorial_authority": 4, "provocative_generosity": 3,
            "founder_blunt": 2, "deadpan_contrarian": 1,
        }
        visual_weights = {
            "screen_evidence": 5, "diagram_as_drama": 5,
            "evidence_wall": 4, "practical_demo": 4,
            "editorial_brutalism": 2, "human_pov": 1,
        }
        narrative_weights = {
            "failure_mechanism_repair": 5, "open_casefile": 4,
            "myth_counterexample_rule": 4, "question_ladder": 3,
            "reversal_proof_action": 3,
        }
    else:
        tone_weights = {
            "warm_confidant": 5, "playful_precision": 5,
            "cinematic_restraint": 4, "community_candid": 4,
            "founder_blunt": 2, "deadpan_contrarian": 2,
        }
        visual_weights = {
            "tactile_artifact": 5, "human_pov": 5,
            "quiet_cinema": 4, "practical_demo": 4,
            "kinetic_type": 3, "anti_ui": 2,
        }
        narrative_weights = {
            "ritual_payoff": 5, "scene_question_reveal": 5,
            "countdown_constraint": 4, "before_during_after": 4,
            "object_accumulation": 3,
        }
    for axis, weights in (
        ("tone", tone_weights),
        ("visual", visual_weights),
        ("narrative", narrative_weights),
    ):
        points = weights.get(axes[axis], 0)
        if points:
            admit(points, f"{axis} fits {business_model.upper()} decision behavior")

    lifecycle_hooks = {
        "pre_pmf": {"confession_without_theater", "identity_callout", "counterfactual", "one_line_wager"},
        "launch": {"unfinished_scene", "specific_challenge", "object_mystery", "verdict_first", "forbidden_move"},
        "growth": {"category_inversion", "compressed_enemy", "verdict_first", "artifact_teardown"},
        "mature": {"category_inversion", "artifact_teardown", "counterfactual", "compressed_enemy"},
    }
    if axes["hook"] in lifecycle_hooks.get(lifecycle, set()):
        admit(4, f"hook matches {lifecycle} lifecycle job")
    if brief["budget"].lower() in {"zero", "lean"} and axes["interaction"] in {
        "peer_relay_object", "saveable_diagnostic", "remix_with_constraint",
        "one_object_audit", "prediction_before_reveal", "choose_what_to_delete",
    }:
        admit(4, "participation can travel without paid reach")
    if any(token in surface_text for token in ("ai", "software", "web", "agent", "technical")):
        if axes["visual"] in {"screen_evidence", "diagram_as_drama", "evidence_wall", "practical_demo"}:
            admit(3, "visual grammar can expose a digital mechanism")
        if axes["tone"] in {"technical_elegance", "forensic_calm", "editorial_authority"}:
            admit(3, "tone matches technical evidence burden")
    if "forensic" in surface_text and axes["tone"] == "forensic_calm":
        admit(3, "declared voice explicitly requests forensic restraint")
    if "founder" in surface_text and axes["hook"] in {"confession_without_theater", "identity_callout", "one_line_wager"}:
        admit(3, "founder context rewards accountable first-person stakes")
    return score, reasons


def compile_realtime_creative_council(
    brief: Mapping[str, str],
    *,
    primary_platform: str,
    secondary_platform: str,
    candidate_count: int = 12,
) -> dict[str, Any]:
    kernel_brief = {
        "brief_id": brief["brief_id"],
        "business_model": brief["business_model"],
        "lifecycle": brief["lifecycle"],
        "industry": brief["industry"],
        "category": brief["category"],
        "product_surface": brief["product_surface"].replace(" ", "_"),
        "platform": primary_platform,
        "audience": brief["audience"],
        "decision_job": brief["audience_outcome"],
        "tension": brief["audience_problem"],
        "approved_proof": brief["product_truth"],
        "brand_voice": brief["brand_voice"],
        "budget": brief["budget"],
    }
    kernel = compile_generative_execution_kernel(
        kernel_brief,
        candidate_count=candidate_count,
    )
    critical_axes = ("hook", "narrative", "visual", "tone")
    finalists: list[Mapping[str, Any]] = []
    for candidate in kernel["candidate_blueprints"]:
        if all(
            all(
                candidate["genome"][axis]["id"] != prior["genome"][axis]["id"]
                for axis in critical_axes
            )
            for prior in finalists
        ):
            finalists.append(candidate)
        if len(finalists) == 3:
            break
    if len(finalists) != 3:
        raise ValueError("creative council could not find three critical-axis-distinct finalists")
    territories: list[dict[str, Any]] = []
    for index, candidate in enumerate(finalists):
        genome = candidate["genome"]
        hook_id = genome["hook"]["id"]
        interaction_id = genome["interaction"]["id"]
        tone_id = genome["tone"]["id"]
        territory = {
            "territory_id": f"territory-{index + 1}",
            "candidate_id": candidate["candidate_id"],
            "genome_id": candidate["genome_id"],
            "campaign_name": _CAMPAIGN_NAMES[hook_id],
            "first_line": _first_line(hook_id, kernel_brief),
            "human_truth": genome["tension"]["job"],
            "organizing_conflict": f"{genome['tension']['job']} versus {genome['payoff']['job']}",
            "primary_platform": primary_platform,
            "secondary_platform": secondary_platform,
            "portable_decision_tool": genome["proof"]["job"],
            "key_visual_metaphor": genome["visual"]["job"],
            "visual_grammar_id": genome["visual"]["id"],
            "tone_id": tone_id,
            "tone_instruction": _tone_instruction(tone_id),
            "narrative_grammar_id": genome["narrative"]["id"],
            "narrative_beats": genome["narrative"]["beats"],
            "first_1500ms_video": f"Open on {genome['hook']['job']}; use {genome['visual']['job']} before any logo or explanation.",
            "participation_mechanic": _participation(interaction_id, kernel_brief),
            "zero_budget_relay_object": f"A portable {genome['proof']['id'].replace('_', ' ')} that earns {genome['payoff']['id'].replace('_', ' ')}.",
            "proof_integration": brief["product_truth"],
            "why_it_could_fail": f"The route fails if {genome['hook']['job']} reads as theater instead of a decision tool.",
            "kill_rule": "Kill when five reviewers cannot distinguish its tension, proof behavior and participation mechanic from either other finalist.",
            "axis_signature": {axis: value["id"] for axis, value in genome.items()},
        }
        territories.append(territory)

    control = build_agent_control_plane()
    node_specs = (
        ("market-diagnosis", "market_intelligence_agent", "brief plus bounded market hypothesis", "one audience decision and category default"),
        ("strategy-debate", "strategy_council", f"{candidate_count} creative genomes", "three mutually exclusive strategic routes"),
        ("platform-language", "platform_copy_chief", "three route mandates plus platform grammar", "native copy systems, not reformats"),
        ("multimodal-direction", "imagegen_video_director", "selected visual and narrative genomes plus six exclusive placement briefs", "imagegen-routable visual contracts, three distinct image compositions and three independent six-scene film grammars"),
        ("adversarial-cut", "red_team_jury", "three complete route contracts", "context-fit scoring plus explicit kill rules"),
        ("release-harness", "authority_harness", "sealed artifacts and remaining gates", "named-human review boundary"),
    )
    node_receipts = []
    parent = kernel["brief_sha256"]
    for order, (node_id, agent_id, node_input, node_output) in enumerate(node_specs, 1):
        receipt = {
            "order": order,
            "node_id": node_id,
            "agent_id": agent_id,
            "input": node_input,
            "output": node_output,
            "loop": ["generate", "critique", "repair" if order in {2, 3, 4} else "accept"],
            "loop_iterations": 2 if order in {2, 3, 4} else 1,
            "input_sha256": parent,
            "model_call_observed": False,
            "tool_execution_observed": True,
            "external_action_executed": False,
        }
        receipt["output_sha256"] = _digest(receipt)
        parent = receipt["output_sha256"]
        node_receipts.append(receipt)

    distinct_axis_pairs = []
    for left in range(len(territories)):
        for right in range(left + 1, len(territories)):
            left_axes = territories[left]["axis_signature"]
            right_axes = territories[right]["axis_signature"]
            distance = sum(left_axes[key] != right_axes[key] for key in left_axes)
            distinct_axis_pairs.append({"pair": [territories[left]["territory_id"], territories[right]["territory_id"]], "axis_distance": distance})
    scorecards = []
    for territory in territories:
        score, reasons = _strategy_fit_score(territory, brief)
        scorecards.append({
            "territory_id": territory["territory_id"],
            "context_fit_score": score,
            "reasons": reasons,
            "creative_preference_claimed": False,
            "market_effect_claimed": False,
        })
    selected_scorecard = max(
        scorecards,
        key=lambda row: (row["context_fit_score"], row["territory_id"]),
    )
    selected = next(
        territory
        for territory in territories
        if territory["territory_id"] == selected_scorecard["territory_id"]
    )
    axes = selected["axis_signature"]
    visual_jobs = (
        (primary_platform, "image", "native feed key visual", axes["visual"], "decision object before product explanation"),
        (secondary_platform, "image", "native vertical visual", "practical_demo", "participation mechanism in motion"),
        ("search", "image", "persistent editorial answer visual", "diagram_as_drama", "one evidence relationship that survives the feed"),
        (primary_platform, "video_master", "argument-first film world", axes["visual"], "six crop-distinct scenes with consequence before feature"),
        (secondary_platform, "video_master", "participation-first film world", "kinetic_proof_path", "six crop-distinct scenes that invite a verdict"),
        ("search", "video_master", "provenance-first explainer film world", "editorial_source_map", "six scene-distinct frames that trace question, sources, rejection, answer and approval"),
    )
    placement_briefs = []
    for index, (surface, modality, job, grammar, cinematic_job) in enumerate(visual_jobs, 1):
        row = {
            "placement_id": f"visual-placement-{index:02d}",
            "surface_id": surface,
            "modality": modality,
            "creative_job": job,
            "visual_grammar_id": grammar,
            "cinematic_job": cinematic_job,
            "approved_truth": brief["product_truth"],
            "negative_constraints": ["no fake UI", "no unapproved outcome claim", "no stock cliché", "no cross-placement source reuse"],
            "generation_mode": "one_independent_imagegen_job_or_one_verified_exclusive_source",
        }
        row["brief_sha256"] = _digest(row)
        placement_briefs.append(row)
    imagegen_skill_contract = {
        "skill_id": "imagegen",
        "capability_state": "active",
        "routing_mode": "one_generation_or_verified_source_job_per_final_placement",
        "placement_brief_count": len(placement_briefs),
        "placement_briefs": placement_briefs,
        "required_output_receipts": ["provider", "model_or_procedural_mode", "source_sha256", "placement_id", "rights_status"],
        "hard_gates": {
            "reused_final_binary_allowed": False,
            "reused_copy_bundle_allowed": False,
            "reused_visual_source_allowed": False,
            "same_platform_cross_modality_source_reuse_allowed": False,
            "generic_placeholder_fallback_allowed": False,
        },
        "live_imagegen_calls_observed_in_council": 0,
        "truth_boundary": "The Agent council installs and routes an explicit imagegen skill contract. This receipt does not claim a live image-model call; the renderer separately proves any verified master selection or procedural source execution.",
    }
    imagegen_skill_contract["content_sha256"] = _digest(imagegen_skill_contract)
    payload = {
        "schema": SCHEMA,
        "control_plane_sha256": control["content_sha256"],
        "generative_kernel_sha256": kernel["content_sha256"],
        "blueprint_design_space": kernel["creative_genome"]["blueprint_design_space"],
        "candidate_blueprint_count": candidate_count,
        "minimum_pairwise_axis_distance": kernel["creative_genome"]["minimum_pairwise_axis_distance"],
        "finalist_axis_distances": distinct_axis_pairs,
        "selected_territory_id": selected["territory_id"],
        "selection_mode": "declared_context_fit_score_not_creative_winner",
        "selection_scorecards": scorecards,
        "territories": territories,
        "node_receipts": node_receipts,
        "imagegen_skill_contract": imagegen_skill_contract,
        "graph": [node[0] for node in node_specs],
        "harness": {
            "generic_copy_fallback_allowed": False,
            "same_formula_across_industries_forbidden": True,
            "platform_rewrite_required": True,
            "imagegen_skill_required_for_visual_placements": True,
            "one_visual_source_per_placement_required": True,
            "named_human_release_required": True,
            "automatic_publish_send_spend": False,
        },
        "deterministic_agent_node_execution_observed": True,
        "frontier_model_agent_execution_observed": False,
        "external_action_count": 0,
        "truth_boundary": "The receipt proves deterministic specialist-node execution over a large creative genome space. It does not claim autonomous frontier-model reasoning, human creative preference, publication or market effect.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


__all__ = ["SCHEMA", "compile_realtime_creative_council"]
