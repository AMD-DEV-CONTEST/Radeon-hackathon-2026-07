#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Mapping

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_multimodal_breakout_factory import verify_multimodal_breakout_factory


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FIELDS = {
    "strategy_rationale", "platform_native_primary_copy", "alternate_openings",
    "decision_tool", "comment_or_reply_system", "seo_geo_derivatives", "claim_inventory", "genome_execution",
}
COPY_FIELDS = {"first_line", "body", "proof", "participation", "cta"}
REPLY_FIELDS = {"first_comment", "objection_branches"}
SEO_FIELDS = {"search_explainer", "answer_engine_citation_unit"}
GENOME_FIELDS = {"hook_mechanism", "narrative_mechanism", "proof_mechanism", "interaction_mechanism"}
DECISION_TOOL_FIELDS = {"name", "steps", "kill_rule", "privacy_boundary"}
UNSUPPORTED = re.compile(
    r"\b(?:guarantee(?:d|s)?|will go viral|will drive revenue|best[- ]in[- ]class|world[- ]class|top\s*1|4a[- ]grade)\b",
    re.IGNORECASE,
)
UNAVAILABLE_DESTINATION = re.compile(r"\b(?:click(?: below)?|schedule (?:a )?(?:demo|call)|request (?:a )?(?:demo|walkthrough)|download|link to|tap here)\b|\[[^]]*link[^]]*\]", re.IGNORECASE)
INVENTED_PRODUCT_CAPABILITY = re.compile(
    r"(?:\b(?:our|the|this|a)\s+(?:product|solution|tool|platform|system|demonstration|demo)\b[^.!?\n]{0,100}\b(?:reveals?|provides?|helps?|enables?|allows?|offers?|highlights?|integrates?|identifies?|surfaces?|prevents?|ensures?|shows?|builds?|cuts? through)\b)|(?:\bit\s+(?:reveals?|provides?|helps?|enables?|allows?|offers?|highlights?|integrates?|identifies?|surfaces?|prevents?|ensures?|shows?)\b)",
    re.IGNORECASE,
)
UNAVAILABLE_DEMO_ACTION = re.compile(r"\b(?:view|explore|open|watch|see|try)\s+(?:the|a|our|this)?\s*(?:demo|demonstration|walkthrough)\b", re.IGNORECASE)
GENERIC_TRANSITION = re.compile(
    r"\b(?:most ai governance|consider this|the hype (?:cycle )?is real|this isn['’]t about [^.;]{2,80}[;,.]?\s*it['’]s about)\b",
    re.IGNORECASE,
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _extract(raw: str) -> dict[str, Any]:
    start = raw.find("{")
    if start < 0:
        raise ValueError("model output contains no JSON object")
    value, _ = json.JSONDecoder().raw_decode(raw[start:])
    if not isinstance(value, dict):
        raise ValueError("model output must be one JSON object")
    return value


def adapt_claim_inventory(candidate: Mapping[str, Any], *, approved_proof: str) -> tuple[dict[str, Any], int]:
    """Clamp truth labels only; never rewrite audience-facing creative."""

    adapted = json.loads(json.dumps(candidate, ensure_ascii=False))
    rows = adapted.get("claim_inventory")
    if not isinstance(rows, list):
        return adapted, 0
    normalized = []
    changes = 0
    approved_seen = False
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("claim"), str):
            normalized.append(row)
            continue
        if row["claim"] == approved_proof and not approved_seen:
            replacement = {"claim": approved_proof, "status": "approved_proof", "evidence": approved_proof}
            approved_seen = True
        else:
            replacement = {"claim": row["claim"], "status": "hypothesis", "evidence": "none; requires owner evidence"}
        if dict(row) != replacement:
            changes += 1
        normalized.append(replacement)
    if not approved_seen:
        normalized.append({"claim": approved_proof, "status": "approved_proof", "evidence": approved_proof})
        changes += 1
    adapted["claim_inventory"] = normalized
    return adapted, changes


def bind_genome_metadata(candidate: Mapping[str, Any], *, work_order: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    """Bind immutable work-order metadata without touching audience-facing creative."""

    adapted = json.loads(json.dumps(candidate, ensure_ascii=False))
    spine = work_order["input"]["campaign_spine"]
    expected = {
        "hook_mechanism": spine["opening_job"],
        "narrative_mechanism": spine["narrative_beats"],
        "proof_mechanism": spine["single_approved_proof"],
        "interaction_mechanism": spine["participation_job"],
    }
    changed = int(adapted.get("genome_execution") != expected)
    adapted["genome_execution"] = expected
    return adapted, changed


def _words(value: object) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", str(value).casefold())
        if token not in {"the", "and", "that", "this", "with", "from", "your", "into", "for", "one"}
    }


def candidate_failures(
    candidate: Mapping[str, Any], *, factory: Mapping[str, Any],
    work_order: Mapping[str, Any] | None = None,
    editorial_source: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    failures = []
    if set(candidate) != EXPECTED_FIELDS:
        failures.append("top-level fields violate the closed contract")
    copy = candidate.get("platform_native_primary_copy")
    if not isinstance(copy, Mapping) or set(copy) != COPY_FIELDS:
        failures.append("primary copy fields violate the closed contract")
        copy = {}
    first_line = copy.get("first_line")
    body = copy.get("body")
    if not isinstance(first_line, str) or not 12 <= len(first_line.strip()) <= 180:
        failures.append("first line is absent, shallow or overlong")
    if not isinstance(body, list) or not 3 <= len(body) <= 7 or any(not isinstance(row, str) or len(row.strip()) < 12 for row in body):
        failures.append("body must contain three to seven substantive blocks")
    proof = copy.get("proof")
    approved = factory["brief"]["approved_proof"]
    if proof != approved:
        failures.append("proof must equal the approved proof exactly")
    for field in ("participation", "cta"):
        if not isinstance(copy.get(field), str) or len(copy[field].strip()) < 8:
            failures.append(f"{field} is missing or shallow")
    openings = candidate.get("alternate_openings")
    if not isinstance(openings, list) or len(openings) != 5 or len(set(openings)) != 5 or any(not isinstance(row, str) or len(row.strip()) < 12 for row in openings):
        failures.append("alternate openings must contain five distinct substantive lines")
    decision_tool = candidate.get("decision_tool")
    if not isinstance(decision_tool, Mapping) or set(decision_tool) != DECISION_TOOL_FIELDS:
        failures.append("decision tool violates the closed contract")
    else:
        steps = decision_tool.get("steps")
        if (
            not isinstance(decision_tool.get("name"), str)
            or not isinstance(steps, list)
            or not 3 <= len(steps) <= 5
            or any(not isinstance(row, str) or len(row.strip()) < 12 for row in steps)
            or any(not isinstance(decision_tool.get(field), str) or len(decision_tool[field].strip()) < 16 for field in ("kill_rule", "privacy_boundary"))
        ):
            failures.append("decision tool must be a named, usable three-to-five-step rule with kill and privacy boundaries")
    replies = candidate.get("comment_or_reply_system")
    if not isinstance(replies, Mapping) or set(replies) != REPLY_FIELDS:
        failures.append("reply system violates the closed contract")
    else:
        branches = replies.get("objection_branches")
        if (
            not isinstance(replies.get("first_comment"), str)
            or not isinstance(branches, list)
            or len(branches) != 3
            or any(not isinstance(row, Mapping) or set(row) != {"objection", "reply"} for row in branches)
        ):
            failures.append("reply system lacks one first comment and three branches")
    derivatives = candidate.get("seo_geo_derivatives")
    if not isinstance(derivatives, Mapping) or set(derivatives) != SEO_FIELDS or any(not isinstance(value, str) or len(value.strip()) < 40 for value in derivatives.values()):
        failures.append("SEO/GEO derivatives are incomplete")
    claims = candidate.get("claim_inventory")
    if (
        not isinstance(claims, list)
        or not claims
        or any(not isinstance(row, Mapping) or set(row) != {"claim", "status", "evidence"} for row in claims)
    ):
        failures.append("claim inventory is absent")
    else:
        approved_rows = [row for row in claims if row.get("status") == "approved_proof"]
        if len(approved_rows) != 1 or approved_rows[0].get("claim") != approved or approved_rows[0].get("evidence") != approved:
            failures.append("claim inventory misclassifies unapproved facts as approved proof")
        if any(row.get("status") not in {"approved_proof", "hypothesis"} for row in claims):
            failures.append("claim inventory contains an unsupported truth status")
    genome_execution = candidate.get("genome_execution")
    if not isinstance(genome_execution, Mapping) or set(genome_execution) != GENOME_FIELDS:
        failures.append("genome execution fields violate the closed contract")
    elif work_order is not None:
        spine = work_order["input"]["campaign_spine"]
        expected_genome = {
            "hook_mechanism": spine["opening_job"],
            "narrative_mechanism": spine["narrative_beats"],
            "proof_mechanism": spine["single_approved_proof"],
            "interaction_mechanism": spine["participation_job"],
        }
        if dict(genome_execution) != expected_genome:
            failures.append("genome execution does not exactly instantiate the assigned campaign genome")
    if editorial_source:
        source_words = _words(_canonical(editorial_source))
        creative_words = _words(_canonical({
            "copy": candidate.get("platform_native_primary_copy"),
            "tool": candidate.get("decision_tool"),
            "replies": candidate.get("comment_or_reply_system"),
        }))
        if len(source_words & creative_words) < 12:
            failures.append("candidate is insufficiently anchored to the supplied owner-approved editorial source")
        source_hook_words = _words(editorial_source.get("hook", ""))
        first_line_words = _words(first_line or "")
        hook_union = source_hook_words | first_line_words
        hook_similarity = len(source_hook_words & first_line_words) / len(hook_union) if hook_union else 0.0
        if hook_similarity > 0.55:
            failures.append("first line copies the source hook instead of instantiating the assigned genome")
    serialized = _canonical(candidate)
    if UNSUPPORTED.search(serialized):
        failures.append("candidate contains an unsupported effect or quality claim")
    if UNAVAILABLE_DESTINATION.search(serialized):
        failures.append("candidate references an unavailable destination")
    if UNAVAILABLE_DEMO_ACTION.search(serialized):
        failures.append("candidate asks for an unavailable demonstration action")
    if INVENTED_PRODUCT_CAPABILITY.search(serialized):
        failures.append("candidate invents an unapproved product capability")
    public_copy = _canonical({"copy": copy, "replies": candidate.get("comment_or_reply_system")})
    if GENERIC_TRANSITION.search(public_copy):
        failures.append("candidate uses generic AI-marketing exposition instead of concrete platform-native craft")
    named_products = {
        product.casefold()
        for category in factory["candidate_campaigns"][0]["text_generation_request"]["stress_pack"]
        for product in category["reference_products"]
    }
    lower = serialized.casefold()
    if any(product in lower for product in named_products):
        failures.append("candidate names or imitates a reference product")
    return tuple(dict.fromkeys(failures))


def _prompt(
    factory: Mapping[str, Any], work_order: Mapping[str, Any], failures: tuple[str, ...] = (),
    editorial_source: Mapping[str, Any] | None = None,
) -> str:
    contract = {
        "strategy_rationale": "80-180 words explaining the audience tension, decision and mechanism",
        "platform_native_primary_copy": {
            "first_line": "12-180 characters",
            "body": ["three to seven substantive platform-native blocks"],
            "proof": factory["brief"]["approved_proof"],
            "participation": "one concrete useful audience action",
            "cta": "one low-friction next step",
        },
        "alternate_openings": ["exactly five distinct alternatives"],
        "decision_tool": {
            "name": "a memorable platform-native name",
            "steps": ["three to five concrete steps usable today"],
            "kill_rule": "the exact condition that makes the method fail or stop",
            "privacy_boundary": "how to participate without exposing confidential data",
        },
        "comment_or_reply_system": {
            "first_comment": "one value-adding first comment",
            "objection_branches": ["exactly three substantive reply branches"],
        },
        "seo_geo_derivatives": {
            "search_explainer": "one source-grounded search-native paragraph",
            "answer_engine_citation_unit": "one source-grounded answer-engine paragraph",
        },
        "claim_inventory": [
            {"claim": "every factual clause", "status": "approved_proof or hypothesis", "evidence": "proof text or none"}
        ],
        "genome_execution": {
            "hook_mechanism": work_order["input"]["campaign_spine"]["opening_job"],
            "narrative_mechanism": work_order["input"]["campaign_spine"]["narrative_beats"],
            "proof_mechanism": work_order["input"]["campaign_spine"]["single_approved_proof"],
            "interaction_mechanism": work_order["input"]["campaign_spine"]["participation_job"],
        },
    }
    repair = "" if not failures else "\nPRIOR ATTEMPT FAILED:\n- " + "\n- ".join(failures) + "\nRewrite from scratch."
    source = {} if editorial_source is None else editorial_source
    spine = work_order["input"]["campaign_spine"]
    opening_directives = {
        "issue a concrete test the audience can try before accepting the claim": (
            "Begin with an imperative test the reader can perform on one current artifact; do not begin with a launch slogan or rhetorical question."
        ),
        "make one physical or interface object carry the unanswered question": (
            "Begin on one named physical or interface object and let its missing witness create the question; do not begin with advice."
        ),
        "open inside a consequential scene one beat before resolution": (
            "Begin mid-scene with a named human, object and unresolved release decision; withhold the answer for one beat."
        ),
    }
    assigned_execution = opening_directives.get(
        spine["opening_job"],
        f"The first line must materially enact this job: {spine['opening_job']}.",
    )
    return (
        "You are a senior platform-native GTM creative team. Instantiate the supplied campaign genome into one complete, "
        "directly reviewable text system. Be specific to the exact industry, audience, lifecycle and platform. Demonstrate the "
        "product conflict instead of listing features. Use only the approved proof; label every other factual proposition as a "
        "hypothesis. Absorb capability mechanisms but never name, imitate or compare against reference products. Return exactly "
        "one JSON object with no markdown. Do not claim that a product reveals, provides, helps, enables, allows, offers, highlights, "
        "integrates, identifies or surfaces anything unless that capability appears verbatim in approved proof. Do not invent a link, "
        "demo destination, customer, metric, workflow or interface. The CTA must be a useful native participation action requiring no "
        "unavailable destination. Never say that the demonstration shows, highlights, reveals or provides anything; its existence is "
        "the only approved fact. Do not ask the reader to view, explore, open, watch, see or try the demonstration. Exactly one "
        f"ASSIGNED EXECUTION: {assigned_execution} Follow this narrative order exactly: {spine['narrative_beats']}. "
        f"The interaction must materially do this: {spine['participation_job']}. The source hook is raw research, not a template: "
        "do not copy or lightly paraphrase it. Do not reuse the contrast 'what AI can make' versus 'what it will cost'. "
        "The post must give the audience a named portable decision tool, a concrete synthetic or privacy-safe scene, an exact "
        "kill condition, and a useful action that can be completed without a link. Avoid generic AI-governance exposition, generic "
        "questions, feature lists and slogans. Every paragraph must either advance the scene, expose the mechanism, apply the tool, "
        "state the boundary, or change the audience decision. Treat EDITORIAL_SOURCE as owner-approved strategy and synthetic scenario "
        "material, not as observed customer or market evidence. Preserve its disclosure and privacy boundaries. Exactly one "
        "claim-inventory row may be approved_proof and its claim and evidence must both equal the "
        "approved proof; all other factual propositions are hypotheses. Objection branches must each be {objection, reply}.\nWORK_ORDER:\n"
        + _canonical(work_order)
        + "\nEDITORIAL_SOURCE:\n"
        + _canonical(source)
        + "\nOUTPUT_CONTRACT:\n"
        + _canonical(contract)
        + repair
    )


def _model_manifest(snapshot: Path) -> tuple[str, str]:
    required = ("config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors.index.json")
    if any(not (snapshot / name).is_file() for name in required) or not list(snapshot.glob("model-*.safetensors")):
        raise SystemExit("local MLX model snapshot is incomplete")
    entries = [{"name": path.name, "bytes": path.stat().st_size, "blob": path.resolve().name} for path in sorted(snapshot.iterdir()) if path.is_file()]
    return snapshot.name, _digest(entries)


def _editorial_source(case_system: Mapping[str, Any] | None, factory: Mapping[str, Any]) -> dict[str, Any]:
    if case_system is None:
        return {}
    business_model = factory["brief"]["business_model"]
    platform = factory["brief"]["platform"].casefold()
    case = case_system["cases"][business_model]
    channel = next(row for row in case["channels"] if row["id"].casefold() == platform)
    activation = next(
        (row for row in case.get("activation_wave", []) if row.get("channel_id", "").casefold() == platform),
        {},
    )
    return {
        "audience": case["audience"], "campaign_bet": case["bet"], "platform": platform,
        "hook": channel["hook"], "source_blocks": channel["lines"], "native_move": channel["native_move"],
        "cta": channel["cta"], "kill_rule": channel["kill"], "craft_notes": channel["notes"],
        "measurement": channel["measurement"], "activation_job": activation.get("job"),
        "first_comment": activation.get("first_comment"), "conversation_tree": activation.get("conversation_tree", []),
        "experiment": activation.get("experiment", {}),
    }


def portfolio_failures(accepted: list[Mapping[str, Any]]) -> tuple[str, ...]:
    failures: list[str] = []
    if len(accepted) < 2:
        return ()
    first_lines = [row["candidate"]["platform_native_primary_copy"]["first_line"].strip().casefold() for row in accepted]
    if len(first_lines) != len(set(first_lines)):
        failures.append("portfolio repeats a primary first line")
    for left_index, left in enumerate(accepted):
        left_copy = left["candidate"]["platform_native_primary_copy"]
        left_words = _words(_canonical({"body": left_copy["body"], "tool": left["candidate"]["decision_tool"]}))
        for right in accepted[left_index + 1:]:
            right_copy = right["candidate"]["platform_native_primary_copy"]
            right_words = _words(_canonical({"body": right_copy["body"], "tool": right["candidate"]["decision_tool"]}))
            union = left_words | right_words
            similarity = len(left_words & right_words) / len(union) if union else 1.0
            if similarity > 0.52:
                failures.append(
                    f"portfolio candidates {left['candidate_id']} and {right['candidate_id']} are too similar ({similarity:.3f})"
                )
    return tuple(failures)


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute the text lane of a sealed multimodal factory with cached local Gemma 3 MLX.")
    parser.add_argument("--factory-portfolio", required=True, type=Path)
    parser.add_argument("--factory-index", required=True, type=int)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-case-system", type=Path)
    args = parser.parse_args()
    portfolio = json.loads(args.factory_portfolio.read_text(encoding="utf-8"))
    factory = portfolio["factories"][args.factory_index]
    verify_multimodal_breakout_factory(factory)
    case_system = None if args.source_case_system is None else json.loads(args.source_case_system.read_text(encoding="utf-8"))
    editorial_source = _editorial_source(case_system, factory)
    model_path = args.model_path.expanduser().resolve(strict=True)
    revision, manifest_sha = _model_manifest(model_path)
    os.environ.update({
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    })
    import mlx.core as mx
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    load_started = time.monotonic()
    model, tokenizer = load(str(model_path), lazy=False)
    model_load_seconds = time.monotonic() - load_started
    accepted = []
    private_attempts = []
    for index, campaign in enumerate(factory["candidate_campaigns"]):
        work_order = campaign["text_generation_request"]
        failures: tuple[str, ...] = ()
        accepted_candidate = None
        attempts = []
        for attempt in range(3):
            messages = [
                {"role": "system", "content": "Return one valid JSON object only."},
                {"role": "user", "content": _prompt(factory, work_order, failures, editorial_source)},
            ]
            rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            mx.random.seed(20260804 + index * 10 + attempt)
            started = time.monotonic()
            raw = "{" + generate(
                model, tokenizer, prompt=rendered + "\n{", max_tokens=1600,
                sampler=make_sampler(temp=0.45, top_p=0.9), verbose=False,
            ).lstrip()
            elapsed = time.monotonic() - started
            try:
                parsed = _extract(raw)
                parsed, truth_label_repairs = adapt_claim_inventory(
                    parsed, approved_proof=factory["brief"]["approved_proof"]
                )
                parsed, genome_binding_repairs = bind_genome_metadata(parsed, work_order=work_order)
                failures = candidate_failures(
                    parsed, factory=factory, work_order=work_order, editorial_source=editorial_source
                )
            except Exception as error:
                parsed = None
                truth_label_repairs = 0
                genome_binding_repairs = 0
                failures = (str(error),)
            attempts.append({
                "attempt": attempt + 1, "raw_output": raw, "failures": list(failures),
                "elapsed_seconds": elapsed, "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "bounded_truth_label_repair_count": truth_label_repairs,
                "bounded_genome_metadata_binding_count": genome_binding_repairs,
            })
            if not failures:
                accepted_candidate = parsed
                break
        private_attempts.append({"candidate_id": campaign["candidate_id"], "attempts": attempts})
        if accepted_candidate is not None:
            accepted.append({
                "candidate_id": campaign["candidate_id"], "genome_id": campaign["genome_id"],
                "candidate": accepted_candidate, "candidate_sha256": _digest(accepted_candidate),
                "mechanical_status": "accepted_pending_source_hidden_human_review",
                "bounded_truth_label_repair_count": attempts[-1]["bounded_truth_label_repair_count"],
                "bounded_genome_metadata_binding_count": attempts[-1]["bounded_genome_metadata_binding_count"],
            })
    cross_candidate_failures = portfolio_failures(accepted)
    public = {
        "schema": "ProofLaunchLocalMLXMultimodalFactoryTextReceiptV1",
        "factory_sha256": factory["content_sha256"], "model_id": "mlx-community/gemma-3-12b-it-4bit",
        "model_revision": revision, "model_manifest_sha256": manifest_sha,
        "model_load_seconds": model_load_seconds, "requested_candidate_count": 3,
        "accepted_candidate_count": len(accepted), "accepted_candidates": accepted,
        "model_call_count": sum(len(row["attempts"]) for row in private_attempts),
        "network_call_count": 0, "external_publish_executed": False, "winner_selected": False,
        "human_review_required": True,
        "editorial_source_supplied": bool(editorial_source),
        "portfolio_quality_gate": {
            "passed": not cross_candidate_failures,
            "failures": list(cross_candidate_failures),
            "accepted_for_editorial_pre_review": len(accepted) == 3 and not cross_candidate_failures,
        },
        "truth_boundary": "Local MLX text candidates passed mechanical structure and claim gates only. No human preference, named-product win, organic effect or multimodal rendering is claimed.",
    }
    public["content_sha256"] = _digest(public)
    trace = {
        "schema": "ProofLaunchLocalMLXMultimodalFactoryTextPrivateTraceV1",
        "public_receipt_sha256": public["content_sha256"], "attempts": private_attempts,
        "contains_secrets": False, "external_publish_executed": False,
    }
    trace["content_sha256"] = _digest(trace)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.output, json.dumps(public, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    trace_path = args.output.with_name(args.output.stem + ".private-trace.json")
    atomic_write_text(trace_path, json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(_canonical({
        "output": str(args.output), "trace": str(trace_path),
        "accepted_candidate_count": len(accepted), "model_call_count": public["model_call_count"],
        "content_sha256": public["content_sha256"],
    }))


if __name__ == "__main__":
    main()
