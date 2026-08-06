from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .gtm_human_capability_kernel import (
    EDGE_PROHIBITED_TACTICS,
    SURFACE_PLAYBOOKS,
    SURFACE_SPECIALIST_LENSES,
    normalize_surface_id,
    surface_playbook,
    unconventional_edge_play,
)


PLAN_SCHEMA = "ProofLaunchPlatformNativeChallengerPlanV1"
CANDIDATE_SCHEMA = "ProofLaunchPlatformNativeCandidateV1"
RECEIPT_SCHEMA = "ProofLaunchPlatformNativeChallengerReceiptV1"
EXPECTED_SURFACE_COUNT = 13


class GTMPlatformNativeChallengerError(ValueError):
    """A platform-native challenger escaped its frozen brief or review boundary."""


CREATIVE_FIELDS = (
    "campaign_platform",
    "hook",
    "progression",
    "body",
    "cta",
    "participation_mechanism",
    "proof_integration",
    "falsifier",
)

CONCEPT_FIELDS = (
    "organizing_idea",
    "thesis",
    "editorial_mechanism",
    "reader_action",
    "stop_condition",
)

FORBIDDEN_OUTCOME_PATTERNS = (
    re.compile(r"\bguarantee(?:d|s)?\b", re.I),
    re.compile(r"\btop[- ]?1\b", re.I),
    re.compile(r"\b4A[- ]?(?:grade|quality|level)?\b", re.I),
    re.compile(r"\b(?:increase|improve|lift|reduce|grow|boost)(?:d|s|ing)?\s+\d+(?:\.\d+)?%", re.I),
    re.compile(r"\b(?:revenue|roi|conversion)\s+(?:increase|improve|lift|grow)(?:d|s|ing)?\b", re.I),
    re.compile(r"\b(?:eliminates?|ensures?|increases?|improves?|reduces?|accelerates?|boosts?)\b", re.I),
)

GENERIC_COPY_MARKERS = (
    "unlock the power",
    "revolutionize your",
    "game changer",
    "seamless solution",
    "in today's fast-paced world",
    "elevate your",
    "transform your business",
    "lorem ipsum",
)


SURFACE_GENERATION_BLUEPRINTS: dict[str, dict[str, object]] = {
    "linkedin": {
        "artifact": "one senior-operator post built around a named decision rule",
        "body_markers": [
            "OPERATING TENSION:",
            "DECISION RULE:",
            "PROOF BOUNDARY:",
            "PRACTITIONER ACTION:",
            "FAILS WHEN:",
        ],
        "craft": "Use one declarative opening, one concrete operating tension, one decision rule, one bounded proof line and one practitioner action. Ask at most one question.",
    },
    "tiktok": {
        "artifact": "a shootable 9:16 short-video script, not a prose post",
        "body_markers": ["0:00 VISUAL:", "0:02 VO:", "0:06 PROOF:", "0:12 ACTION:"],
        "craft": "Write visible actions and spoken lines. The first frame shows the workflow failure; the proof beat is inspectable; the action beat gives value without a click.",
    },
    "reddit": {
        "artifact": "a transparent operator teardown that can survive skeptical comments",
        "body_markers": ["AFFILIATION:", "WHAT FAILED:", "MECHANISM:", "TRADE-OFF:"],
        "craft": "Disclose the builder affiliation early, give a specific failure/mechanism/trade-off, avoid launch-copy cadence, and invite falsification rather than praise.",
    },
    "youtube": {
        "artifact": "a production-ready long-form video package",
        "body_markers": ["TITLE:", "THUMBNAIL:", "0:00-0:30:", "CHAPTER:", "RECOMMENDATION BOUNDARY:"],
        "craft": "Make title and thumbnail complementary, state the viewing contract in the first 30 seconds, provide chapter progression, and end at a bounded buyer decision.",
    },
    "instagram": {
        "artifact": "a save-worthy diagnostic carousel with an image-first hierarchy",
        "body_markers": ["SLIDE 1:", "SLIDE 2:", "SLIDE 3:", "SLIDE 4:", "SLIDE 5:"],
        "craft": "Each slide performs a different visual job. Keep on-image copy concise, make the system legible without the caption, and hand over one reusable diagnostic.",
    },
    "x": {
        "artifact": "a compressed evidence thread with a falsifiable category thesis",
        "body_markers": ["1/", "2/", "3/", "4/"],
        "craft": "Lead with a precise thesis, add information in every turn, include the strongest counterargument, and state the dated update condition. Remove throat-clearing.",
    },
    "google_search": {
        "artifact": "an indexable buyer-decision page that completes one query-defined task",
        "body_markers": ["DIRECT ANSWER:", "DECISION CRITERIA:", "WHEN NOT TO USE:", "EVIDENCE BOUNDARY:", "NEXT STEP:"],
        "craft": "Answer before selling. Add information gain through a usable decision rule, name limitations, keep entities explicit, and make the page useful without signup.",
    },
    "bing_search": {
        "artifact": "a crawlable entity-comparison page with source-visible structure",
        "body_markers": ["ENTITY MAP:", "COMPARISON CRITERIA:", "EXCEPTION:", "SOURCE BOUNDARY:", "OWNER ACTION:"],
        "craft": "Resolve a category ambiguity with stable terminology and an auditable comparison path. Separate product fact, inference and unresolved evidence.",
    },
    "chatgpt_answers": {
        "artifact": "a citation-worthy owned answer asset",
        "body_markers": ["QUESTION:", "DIRECT ANSWER:", "METHOD:", "LIMITATION:", "UPDATED:"],
        "craft": "Make each claim locally self-contained and extractable. Distinguish approved product fact from hypothesis and publish a precise update date.",
    },
    "claude_answers": {
        "artifact": "a counterexample-first expert brief for careful synthesis",
        "body_markers": ["COMMON MODEL:", "COUNTEREXAMPLE:", "BOUNDARY CONDITIONS:", "DECISION FRAMEWORK:", "UPDATED:"],
        "craft": "Preserve nuance and source boundaries. Explain where the common answer fails and which conditions change the recommendation.",
    },
    "gemini_answers": {
        "artifact": "a provenance-bound multimodal proof graph",
        "body_markers": ["ENTITY:", "TEXT EVIDENCE:", "MEDIA EVIDENCE:", "RELATIONSHIP:", "LIMITATION:"],
        "craft": "Describe only supplied or producible media, bind text and media to the same entity and claim, and expose the decision changed by that relationship.",
    },
    "perplexity_answers": {
        "artifact": "a primary-source gap report with citation-ready passages",
        "body_markers": ["RESEARCH QUESTION:", "SOURCE MAP:", "FINDING:", "DISAGREEMENT:", "DECISION IMPLICATION:", "UPDATED:"],
        "craft": "Do not imitate a derivative listicle. Separate source map, finding, disagreement and decision implication so excerpts cannot overstate the evidence.",
    },
    "copilot_answers": {
        "artifact": "a permission-aware enterprise decision packet",
        "body_markers": ["PERMISSION BOUNDARY:", "AUTHORIZED EVIDENCE:", "DECISION OPTIONS:", "OWNER ACTION:", "AUDIT HANDOFF:"],
        "craft": "Keep public and tenant-authorized context separate, preserve ownership, and route the bounded decision to a named human role without executing it.",
    },
}


SURFACE_CONCEPT_LENSES: dict[str, dict[str, str]] = {
    "linkedin": {
        "operation": "reverse a familiar senior-operator assumption with one named decision rule",
        "native_value": "a practitioner can audit one live handoff without leaving the post",
    },
    "tiktok": {
        "operation": "make one invisible operating failure physically visible in the first frame",
        "native_value": "a viewer can pause and perform the same audit with objects already at hand",
    },
    "reddit": {
        "operation": "disclose affiliation, confess a real design trade-off and invite a skeptical teardown",
        "native_value": "an operator can falsify the mechanism without praising or contacting the builder",
    },
    "youtube": {
        "operation": "turn a category promise into a buyer audit with an explicit rejection rule",
        "native_value": "a buyer can reject an unsuitable approach before considering the product",
    },
    "instagram": {
        "operation": "make one reusable diagnostic object carry a five-step visual argument",
        "native_value": "a practitioner can save and apply the diagnostic without relying on the caption",
    },
    "x": {
        "operation": "state a falsifiable category thesis, then publish its strongest counterargument",
        "native_value": "a skeptical reader can identify the condition that would change the thesis",
    },
    "google_search": {
        "operation": "answer one buyer-intent query with a decision test that can reject the product",
        "native_value": "a searcher completes the evaluation task without signup or salesperson context",
    },
    "bing_search": {
        "operation": "resolve one category ambiguity by mapping entities, authority and exceptions separately",
        "native_value": "a buyer can route one unresolved boundary to its accountable owner",
    },
    "chatgpt_answers": {
        "operation": "make a direct answer locally extractable while naming what evidence cannot support",
        "native_value": "a user can audit the recommendation criteria inside the answer itself",
    },
    "claude_answers": {
        "operation": "lead with a counterexample that breaks the popular one-axis recommendation",
        "native_value": "a careful reader can change the decision when boundary conditions change",
    },
    "gemini_answers": {
        "operation": "bind one text claim to producible media states without borrowing a result from the media",
        "native_value": "a reviewer can spot a text-media contradiction before accepting the synthesis",
    },
    "perplexity_answers": {
        "operation": "separate owned evidence, missing sources, disagreement and decision implication",
        "native_value": "a researcher can withhold a market conclusion that the source map cannot support",
    },
    "copilot_answers": {
        "operation": "separate authorized context, decision options, human ownership and denied actions",
        "native_value": "an operator can deny the next external action and preserve an audit handoff",
    },
}


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def build_platform_native_concept_prompt(
    *, plan: Mapping[str, Any], request: Mapping[str, Any]
) -> str:
    """Build a compact editorial-planning call before surface rendering.

    This deliberately removes the long strategy-card context used by the draft call.
    The model chooses an editorial mechanism, not new product facts, tools or results.
    """

    verify_platform_native_challenger_plan(plan)
    surface_id = normalize_surface_id(str(request.get("surface_id", "")))
    if request.get("request_id") not in {
        row.get("request_id") for row in plan.get("requests", [])
    }:
        raise GTMPlatformNativeChallengerError("concept request is not bound to plan")
    brief = plan["brief"]
    lens = SURFACE_CONCEPT_LENSES[surface_id]
    compact_truth = {
        "product_name": brief["product_name"],
        "product_truth": brief["product_truth"],
        "audience": brief["audience"],
        "problem": brief["problem"],
        "voice": brief["voice"],
    }
    shape = {field: f"<{field}>" for field in CONCEPT_FIELDS}
    return (
        "Choose one original editorial concept for a platform-native organic GTM artifact. "
        "Return exactly one flat JSON object and no markdown. This is a private concept card, not public copy.\n\n"
        f"SURFACE_ID={surface_id}\n"
        f"FACT_WHITELIST={canonical_json(compact_truth)}\n"
        f"EDITORIAL_LENS={canonical_json(lens)}\n"
        f"OUTPUT_SHAPE={canonical_json(shape)}\n\n"
        "organizing_idea is an ownable three-to-eight-word editorial title and must not begin with AI, GTM or Autonomous. "
        "Do not use workflow, validation, governance, traceability, visibility, transparency, confidence or alignment in that title. "
        "thesis is one decisive category insight, not a question and not a product claim. "
        "editorial_mechanism explains how the artifact reveals the insight using only the reader's own material or a producible content prop; it must not invent a product feature. "
        "reader_action is a self-contained action that creates value without a click, reply, download, promised response or external asset. "
        "Begin reader_action with apply, audit, choose, compare, evaluate, inspect, label, map, mark, observe, rewrite, route, score, test or trace. "
        "stop_condition is a qualitative observation that would invalidate this editorial route; it must explicitly contain stop, fails, cannot, does not, no longer or contradicts and use no percentage, duration, rate or invented benchmark. "
        "Never invent a customer, result, integration, dashboard, matrix, score, source map, worksheet, calculator, screenshot, demo, access flow or evidence pack. "
        "The finished artifact must contain everything it asks the reader to inspect. A comparison or capability case is allowed when every path fits inside the surface blueprint and is visibly labeled SYNTHETIC SCENARIO, HYPOTHETICAL or COMPOSITE DEMO. "
        "Never claim an achieved increase, improvement, reduction, acceleration, boost, prevention, solution or guarantee. "
        "Use the product truth only to understand the category boundary; do not repeat or paraphrase it as proof in this concept card. "
        "Every field must perform a different job and contain complete natural language with no placeholders."
    )


def extract_platform_native_concept(raw: str | Mapping[str, Any]) -> dict[str, str]:
    """Recover model-written concept fields without synthesizing creative language."""

    parsed: Any = extract_first_json_object(raw) if isinstance(raw, str) else raw
    candidates: list[Mapping[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            candidates.append(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(parsed)
    if not candidates:
        raise GTMPlatformNativeChallengerError("concept output contains no object")
    best = max(
        candidates,
        key=lambda item: sum(field in item for field in CONCEPT_FIELDS),
    )
    return {
        field: str(best.get(field, "")).strip()
        for field in CONCEPT_FIELDS
    }


def platform_native_concept_failures(
    concept: Mapping[str, Any], *, plan: Mapping[str, Any], request: Mapping[str, Any]
) -> tuple[str, ...]:
    verify_platform_native_challenger_plan(plan)
    failures: list[str] = []
    if not isinstance(concept, Mapping):
        return ("concept_is_not_an_object",)
    missing = [field for field in CONCEPT_FIELDS if not _nonblank(concept.get(field), minimum=3, maximum=800)]
    if missing:
        failures.append("concept_missing_fields:" + "|".join(missing))
        return tuple(failures)
    values = {field: str(concept[field]).strip() for field in CONCEPT_FIELDS}
    title = values["organizing_idea"]
    title_words = re.findall(r"[a-z0-9]+", title.casefold())
    if not 3 <= len(title_words) <= 8:
        failures.append("concept_organizing_idea_word_count")
    if re.search(r"^(?:autonomous |ai )?gtm\b", title, re.I) or re.search(
        r"\b(?:workflow|validation|governance|traceability|visibility|transparency|confidence|alignment)\b",
        title,
        re.I,
    ):
        failures.append("concept_organizing_idea_is_generic")
    thesis = values["thesis"]
    if len(re.findall(r"[a-z0-9]+", thesis.casefold())) < 9 or thesis.endswith("?"):
        failures.append("concept_thesis_is_not_decisive")
    if len(re.findall(r"[a-z0-9]+", values["editorial_mechanism"].casefold())) < 12:
        failures.append("concept_editorial_mechanism_is_thin")
    action = values["reader_action"]
    if len(re.findall(r"[a-z0-9]+", action.casefold())) < 12 or not re.search(
        r"\b(?:apply|audit|choose|compare|evaluate|inspect|label|map|mark|observe|rewrite|route|score|test|trace)\b",
        action,
        re.I,
    ):
        failures.append("concept_reader_action_is_not_self_contained")
    stop = values["stop_condition"]
    if len(re.findall(r"[a-z0-9]+", stop.casefold())) < 14 or not re.search(
        r"\b(?:cannot|fails?|does not|no longer|contradicts?|stop)\b", stop, re.I
    ):
        failures.append("concept_stop_condition_is_not_observable")
    if re.search(
        r"\d+(?:\.\d+)?\s*(?:%|hours?\b|days?\b|weeks?\b|months?\b)",
        stop,
        re.I,
    ):
        failures.append("concept_stop_condition_invents_threshold")
    public = "\n".join(values.values())
    if str(plan["brief"]["approved_claim"]).casefold() in public.casefold():
        failures.append("concept_repeats_approved_claim")
    if re.search(
        r"\b(?:dashboard|decision matrix|source map|worksheet|calculator|screen(?: |-)?recording|screenshot|demo|download|request access|evidence pack)\b",
        public,
        re.I,
    ):
        failures.append("concept_invents_unbound_asset_or_product_detail")
    for pattern in FORBIDDEN_OUTCOME_PATTERNS:
        if _assertive_outcome_match(pattern, public):
            failures.append("concept_asserts_unsupported_outcome")
            break
    if len({value.casefold() for value in values.values()}) != len(values):
        failures.append("concept_reuses_one_field_for_multiple_jobs")
    return tuple(dict.fromkeys(failures))


def build_concept_anchored_draft_prompt(
    *,
    plan: Mapping[str, Any],
    request: Mapping[str, Any],
    concept: Mapping[str, Any],
) -> str:
    failures = platform_native_concept_failures(concept, plan=plan, request=request)
    if failures:
        raise GTMPlatformNativeChallengerError(
            "concept failed before drafting: " + " | ".join(failures)
        )
    surface_id = normalize_surface_id(str(request["surface_id"]))
    blueprint = SURFACE_GENERATION_BLUEPRINTS[surface_id]
    brief = plan["brief"]
    compact_brief = {
        "product_name": brief["product_name"],
        "product_truth": brief["product_truth"],
        "audience": brief["audience"],
        "approved_claim": brief["approved_claim"],
        "offer": brief["offer"],
        "voice": brief["voice"],
    }
    shape = {
        "campaign_platform": concept["organizing_idea"],
        "hook": "<one decisive native opening derived from the thesis>",
        "progression": [
            "<tension>",
            "<mechanism reveal>",
            "<bounded proof>",
            "<useful action>",
        ],
        "body": [
            f"{marker} <complete native block>" for marker in blueprint["body_markers"]
        ],
        "cta": "<qualified evidence-inspection or cohort-consideration action>",
        "participation_mechanism": concept["reader_action"],
        "proof_integration": brief["approved_claim"],
        "falsifier": concept["stop_condition"],
    }
    return (
        "Render the approved private concept into one complete platform-native draft. "
        "Return exactly one flat JSON object and no markdown.\n\n"
        f"SURFACE_ID={surface_id}\n"
        f"FROZEN_BRIEF={canonical_json(compact_brief)}\n"
        f"APPROVED_CONCEPT={canonical_json(dict(concept))}\n"
        f"SURFACE_BLUEPRINT={canonical_json(blueprint)}\n"
        f"EXACT_JSON_SHAPE={canonical_json(shape)}\n\n"
        "Use campaign_platform, reader_action and stop_condition from APPROVED_CONCEPT verbatim. Translate thesis and editorial_mechanism into native public copy without explaining the concept card. "
        "progression contains exactly four different complete sentences of at least nine words each; never use tension, reveal, proof, action, initial alignment, reality check or mechanism reveal as labels. "
        "body contains exactly one string per required marker and each string begins with that marker; each block must contain at least fourteen words, except TikTok, Instagram, X and Copilot where ten words is sufficient. "
        "proof_integration equals the approved claim exactly; nowhere else may the draft repeat, paraphrase or imply that claim. The phrase 'approved product fact' may appear only as a neutral evidence-object label beside its source or limitation, never as the subject of an added capability. If product explanation is essential, quote product_truth exactly once without expanding it. "
        "Treat product_truth and approved_claim as the complete product-fact whitelist. Do not invent any feature, artifact, customer, result, integration, tool, screenshot, source, score, threshold or media that the concept and whitelist do not provide. "
        "Do not invent a first-person case history, prior campaign, internal incident, customer anecdote, competitor example, quarter, year, elapsed time or numeric result. Reddit may disclose builder affiliation but still may not invent an event. "
        "Do not reference content presented below unless that content exists inside a required body block. Synthetic, hypothetical or composite cases are allowed to demonstrate capability only when visibly labeled inside every affected block; they are never production evidence. CTA and participation_mechanism must perform different jobs and cannot repeat the same sentence. "
        "For TikTok, keep 0:00 VISUAL at or below thirty-two words, 0:02 VO at or below twenty-six words, 0:06 PROOF at or below thirty-two words, and 0:12 ACTION at or below twenty-four words. "
        "The participation action must remain useful without a click, reply, download or promised asset. The CTA may invite inspection or cohort consideration but cannot promise access or a response. "
        "Never write reflect on, visibility, transparency, confidence or alignment as a substitute for a concrete action. Never report publication or observed effect. Never use eliminate, ensure, increase, improve, reduce, accelerate, boost, solve, prevent or guarantee as an achieved outcome. "
        "If UPDATED: is required, write exactly 'UPDATED: 2026-08-03 — no production effect observed.' No placeholders, extra keys, nested objects or duplicated blocks."
    )


def _content_digest(payload: Mapping[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    return digest(unsigned)


def _nonblank(value: object, *, minimum: int = 1, maximum: int = 2_400) -> bool:
    return isinstance(value, str) and minimum <= len(value.strip()) <= maximum


def _assertive_outcome_match(pattern: re.Pattern[str], text: str) -> bool:
    """Reject asserted effects while allowing an explicit nearby negation."""

    for match in pattern.finditer(text):
        prefix = text[max(0, match.start() - 80) : match.start()].casefold()
        if any(
            marker in prefix
            for marker in (
                "not claiming",
                "do not claim",
                "does not claim",
                "never claim",
                "cannot claim",
                "without claiming",
                "is not guaranteed to",
            )
        ):
            continue
        return True
    return False


def _frozen_measurement(surface_id: str, edge: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "surface_id": surface_id,
        "baseline_window": "owner-authorized_recent_3_to_6_month_surface_baseline_required",
        "test_design": "one_variable_frozen_organic_test",
        "primary_measurement": edge["qualified_growth_measurement"],
        "activation_state": "disabled_pending_owner_baseline_and_human_release",
        "causal_claim_allowed": False,
        "external_publish_executed": False,
    }


def _request_prompt(
    *,
    brief: Mapping[str, Any],
    surface_id: str,
    business_model: str,
    playbook: Mapping[str, str],
    edge: Mapping[str, Any],
) -> str:
    compact_brief = {
        key: brief[key]
        for key in (
            "brief_id",
            "product_name",
            "product_truth",
            "audience",
            "problem",
            "desired_outcome",
            "offer",
            "voice",
            "approved_claim_id",
            "approved_claim",
        )
    }
    contract = {
        "schema": CANDIDATE_SCHEMA,
        "creative_fields": list(CREATIVE_FIELDS),
        "progression": "array of exactly 4 nonblank beats",
        "body": "array of 3 to 7 nonblank platform-native blocks",
        "proof_rule": "approved_claim must appear verbatim exactly once in proof_integration",
        "release_rule": "draft only; never claim observed effect or publication; do not invent a numeric threshold before an owner-authorized baseline exists",
    }
    blueprint = SURFACE_GENERATION_BLUEPRINTS[surface_id]
    json_shape = {
        "campaign_platform": "<original 3-8 word organizing idea>",
        "hook": "<one decisive platform-native opening>",
        "progression": [
            "<tension beat>",
            "<mechanism reveal beat>",
            "<bounded proof beat>",
            "<useful action beat>",
        ],
        "body": [
            f"{marker} <complete native content for this marker>"
            for marker in blueprint["body_markers"]
        ],
        "cta": "<surface-native evidence inspection or cohort-consideration action>",
        "participation_mechanism": "<self-contained user value requiring no click, download, reply or promised asset>",
        "proof_integration": compact_brief["approved_claim"],
        "falsifier": "<observable non-numeric condition for stopping this creative route>",
    }
    return (
        "Create one clean-room, platform-native organic GTM challenger. Return exactly one JSON object and no markdown. "
        "Do not copy a named campaign, creator voice, trade dress or competitor expression. Do not manufacture engagement, identity, urgency or social proof. "
        "In public-facing creative, never use eliminate, ensure, increase, improve, reduce, accelerate or boost as achieved product effects; frame any effect as a hypothesis to test. "
        "Make the hook, progression, participation and proof object unusually sharp while remaining useful and honest.\n\n"
        f"FROZEN_BRIEF={canonical_json(compact_brief)}\n"
        f"BUSINESS_MODEL={business_model}\n"
        f"SURFACE_ID={surface_id}\n"
        f"SURFACE_PLAYBOOK={canonical_json(playbook)}\n"
        f"NON_CONSENSUS_EDGE_PLAY={canonical_json(edge)}\n"
        f"SURFACE_GENERATION_BLUEPRINT={canonical_json(blueprint)}\n"
        f"OUTPUT_CONTRACT={canonical_json(contract)}\n\n"
        f"EXACT_JSON_SHAPE={canonical_json(json_shape)}\n\n"
        "Creative jobs: campaign_platform is an ownable 3-8 word organizing idea; hook earns the first unit of attention without promise mismatch; "
        "progression has four different jobs (tension, reveal, proof, useful action); body is ready to edit into the native format; CTA asks for a qualified next action, not empty engagement; "
        "participation_mechanism creates user value even without a click; proof_integration is exactly the approved claim and contains no other sentence; falsifier states an observable stop condition without a made-up number. "
        "Every literal marker in SURFACE_GENERATION_BLUEPRINT.body_markers must begin a different body string. Do not reuse the frozen offer sentence verbatim as the CTA: translate the offer into this surface's native next action while still advancing inspection, evidence review or cohort consideration. "
        "Do not write imagine, what if, tired of, share your, reflect on, we're building, aims to, visibility, transparency, confidence or alignment as substitutes for a concrete mechanism. "
        "Treat FROZEN_BRIEF.product_truth and FROZEN_BRIEF.approved_claim as the complete factual product whitelist. Do not invent a source map, score, integration, customer, test result, feature, version, worksheet, diagnostic, calculator, screenshot, demo, download, request-access flow, external link or promised response. "
        "The approved claim may appear only as the exact proof_integration value. Do not restate, paraphrase or imply the brief-to-assets claim in hook, progression, body, CTA or participation. Use 'the approved product fact' when referring to it elsewhere. "
        "If the blueprint requires UPDATED:, write exactly 'UPDATED: 2026-08-03 — no production effect observed.' Do not use a different date. "
        "Match EXACT_JSON_SHAPE exactly: no nested objects, no additional keys, no markdown and no placeholder angle-bracket text in the answer. "
        "campaign_platform must be an ownable organizing idea, not a label beginning with GTM/AI/Autonomous GTM and not a phrase built around workflow, validation, governance or traceability. hook must contain a distinct thesis rather than copy NON_CONSENSUS_EDGE_PLAY.non_consensus_hook. "
        "Every progression beat must contain at least seven words and perform a complete editorial move. Every body block must contain at least fourteen words (ten for TikTok, Instagram, X and Copilot). participation_mechanism must contain at least twelve words and a self-contained action such as apply, audit, choose, compare, inspect, mark, rewrite, route, score or test. "
        "falsifier must contain at least fourteen words and one observable qualitative stop condition; use no percentage, duration, rate, increase, improvement or undefined baseline. "
        "The output must be materially unusable on another surface without structural rewriting."
    )


def build_platform_native_challenger_plan(
    brief: Mapping[str, Any], *, business_model: str
) -> dict[str, Any]:
    model = str(business_model).strip().casefold()
    if model not in {"b2b", "b2c"}:
        raise GTMPlatformNativeChallengerError("business_model must be b2b or b2c")
    required = {
        "brief_id",
        "product_name",
        "product_truth",
        "audience",
        "problem",
        "desired_outcome",
        "offer",
        "voice",
        "approved_claim_id",
        "approved_claim",
    }
    if not required.issubset(brief) or any(
        not _nonblank(brief.get(field), minimum=3, maximum=1_200) for field in required
    ):
        raise GTMPlatformNativeChallengerError("frozen brief is incomplete")
    frozen_brief = {field: str(brief[field]).strip() for field in sorted(required)}
    brief_sha = digest(frozen_brief)
    requests: list[dict[str, Any]] = []
    for surface_id in SURFACE_PLAYBOOKS:
        playbook = dict(surface_playbook(surface_id))
        edge = unconventional_edge_play(surface_id, model)
        measurement = _frozen_measurement(surface_id, edge)
        request = {
            "request_id": f"platform-native:{frozen_brief['brief_id']}:{model}:{surface_id}",
            "brief_sha256": brief_sha,
            "surface_id": surface_id,
            "business_model": model,
            "native_format_contract": playbook["native_format_contract"],
            "surface_specialist_lens_ids": [
                f"{surface_id}:{lens_id}" for lens_id, _ in SURFACE_SPECIALIST_LENSES
            ],
            "edge_play": edge,
            "measurement_contract": measurement,
            "maximum_generation_attempts": 2,
            "prompt": _request_prompt(
                brief=frozen_brief,
                surface_id=surface_id,
                business_model=model,
                playbook=playbook,
                edge=edge,
            ),
        }
        request["request_sha256"] = digest(request)
        requests.append(request)
    payload: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "brief": frozen_brief,
        "brief_sha256": brief_sha,
        "business_model": model,
        "surface_count": len(requests),
        "requests": requests,
        "execution_policy": {
            "autonomy_level": "L2_deterministic_workflow",
            "pattern": "route_then_bounded_evaluator_optimizer",
            "single_model_load": True,
            "maximum_attempts_per_surface": 2,
            "maximum_total_model_calls": 26,
            "sequential_fail_isolated": True,
            "automatic_winner_selection_enabled": False,
            "automatic_external_publish_enabled": False,
            "human_source_hidden_review_required": True,
        },
        "truth_boundary": (
            "This plan binds one frozen brief to thirteen distinct public-surface contracts and B2B/B2C edge plays. "
            "It does not prove generation, human preference, publication, organic breakout, conversion or revenue."
        ),
    }
    payload["content_sha256"] = digest(payload)
    verify_platform_native_challenger_plan(payload)
    return payload


def verify_platform_native_challenger_plan(value: object) -> None:
    if not isinstance(value, dict) or value.get("schema") != PLAN_SCHEMA:
        raise GTMPlatformNativeChallengerError("platform-native plan schema is invalid")
    if value.get("content_sha256") != _content_digest(value):
        raise GTMPlatformNativeChallengerError("platform-native plan digest is invalid")
    requests = value.get("requests")
    if not isinstance(requests, list) or len(requests) != EXPECTED_SURFACE_COUNT:
        raise GTMPlatformNativeChallengerError("platform-native surface coverage is incomplete")
    if [row.get("surface_id") for row in requests] != list(SURFACE_PLAYBOOKS):
        raise GTMPlatformNativeChallengerError("platform-native surfaces are missing or reordered")
    if value.get("brief_sha256") != digest(value.get("brief")):
        raise GTMPlatformNativeChallengerError("platform-native brief binding is invalid")
    model = value.get("business_model")
    for row in requests:
        surface_id = row["surface_id"]
        unsigned = dict(row)
        supplied = unsigned.pop("request_sha256", None)
        if supplied != digest(unsigned):
            raise GTMPlatformNativeChallengerError("platform-native request digest is invalid")
        if row.get("brief_sha256") != value.get("brief_sha256") or row.get("business_model") != model:
            raise GTMPlatformNativeChallengerError("platform-native request escaped its brief")
        if row.get("edge_play") != unconventional_edge_play(surface_id, str(model)):
            raise GTMPlatformNativeChallengerError("platform-native edge play is invalid")
        if row.get("native_format_contract") != surface_playbook(surface_id)["native_format_contract"]:
            raise GTMPlatformNativeChallengerError("platform-native format contract is invalid")
        if row.get("maximum_generation_attempts") != 2:
            raise GTMPlatformNativeChallengerError("platform-native attempt budget is invalid")
    policy = value.get("execution_policy")
    if not isinstance(policy, dict) or policy.get("maximum_total_model_calls") != 26:
        raise GTMPlatformNativeChallengerError("platform-native execution policy is invalid")
    for field in (
        "automatic_winner_selection_enabled",
        "automatic_external_publish_enabled",
    ):
        if policy.get(field) is not False:
            raise GTMPlatformNativeChallengerError("platform-native authority was upgraded")


def extract_first_json_object(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        raise GTMPlatformNativeChallengerError("platform-native model output is empty")
    decoder = json.JSONDecoder()
    variants = (
        ("none", raw),
        (
            "trailing_commas_removed",
            re.sub(r",\s*([}\]])", r"\1", raw),
        ),
    )
    for syntax_normalization, text in variants:
        first = text.find("{")
        if first < 0:
            continue
        try:
            value, _ = decoder.raw_decode(text[first:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            value = dict(value)
            value["__prooflaunch_json_syntax_normalization__"] = syntax_normalization
            return value
    for syntax_normalization, text in variants:
        for index, character in enumerate(text):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                value = dict(value)
                value["__prooflaunch_json_syntax_normalization__"] = syntax_normalization
                return value
    raise GTMPlatformNativeChallengerError("platform-native output has no JSON object")


def _normalize_generated_blocks(value: object) -> tuple[object, str]:
    """Normalize serialization only; never invent or rewrite creative language."""

    if isinstance(value, list):
        normalized: list[object] = []
        changed = False
        for item in value:
            if isinstance(item, dict):
                if isinstance(item.get("body_marker"), str) and isinstance(
                    item.get("body"), str
                ):
                    normalized.append(
                        f"{item['body_marker'].strip()} {item['body'].strip()}".strip()
                    )
                    changed = True
                    continue
                if "body" in item and isinstance(item.get("body"), (str, list, dict)):
                    nested, _ = _normalize_generated_blocks(item["body"])
                    if isinstance(nested, list):
                        normalized.extend(nested)
                    else:
                        normalized.append(nested)
                    changed = True
                    continue
                strings = [
                    nested.strip()
                    for nested in item.values()
                    if isinstance(nested, str) and nested.strip()
                ]
                if strings:
                    normalized.append(" ".join(strings))
                    changed = True
                    continue
            normalized.append(item)
        return (
            normalized,
            "list_object_values_preserved_in_source_order" if changed else "list_preserved",
        )
    if isinstance(value, dict):
        blocks: list[str] = []
        for key, item in value.items():
            if not isinstance(item, str) or not item.strip():
                continue
            label = str(key).strip()
            if label.endswith(":") or (label.upper() == label and "_" not in label):
                blocks.append(f"{label.rstrip(':')}: {item.strip()}")
            else:
                blocks.append(item.strip())
        return blocks, "object_labels_and_values_preserved_in_source_order"
    if isinstance(value, str):
        text = value.strip()
        paragraphs = [
            re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", item).strip()
            for item in re.split(r"\n\s*\n|\n(?=\s*(?:[-*•]|\d+[.)])\s+)", text)
            if item.strip()
        ]
        if len(paragraphs) <= 1:
            sentences = [
                item.strip()
                for item in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
                if item.strip()
            ]
            if len(sentences) > 1:
                return sentences, "sentence_boundaries_preserved"
        return paragraphs, "paragraph_boundaries_preserved"
    return value, "unsupported_shape_preserved"


def adapt_platform_native_candidate(
    parsed: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    syntax_normalization = str(
        parsed.get("__prooflaunch_json_syntax_normalization__", "none")
    )
    source = parsed.get("candidate") if isinstance(parsed.get("candidate"), dict) else parsed
    source = dict(source)
    nested_dicts: list[Mapping[str, Any]] = []

    def collect_nested(value: object) -> None:
        if isinstance(value, dict):
            nested_dicts.append(value)
            for nested in value.values():
                collect_nested(nested)
        elif isinstance(value, list):
            for nested in value:
                collect_nested(nested)

    collect_nested(source)
    for field in CREATIVE_FIELDS:
        if source.get(field) is not None:
            continue
        for nested in nested_dicts:
            if nested is source:
                continue
            if nested.get(field) is not None:
                source[field] = nested[field]
                break
    creative = {field: source.get(field) for field in CREATIVE_FIELDS}
    creative["progression"], progression_normalization = _normalize_generated_blocks(
        creative.get("progression")
    )
    creative["body"], body_normalization = _normalize_generated_blocks(
        creative.get("body")
    )
    approved_claim = str(plan["brief"]["approved_claim"])
    generated_proof = creative.get("proof_integration")
    proof_normalization = "exact_claim_preserved"
    if isinstance(generated_proof, str) and generated_proof.strip():
        occurrences = generated_proof.count(approved_claim)
        if occurrences == 0:
            case_insensitive = re.compile(
                re.escape(approved_claim.rstrip(".")) + r"\.?", re.I
            )
            if case_insensitive.search(generated_proof):
                creative["proof_integration"] = case_insensitive.sub(
                    approved_claim, generated_proof.strip(), count=1
                )
                proof_normalization = "immutable_approved_claim_case_normalized_in_place"
            else:
                creative["proof_integration"] = f"{approved_claim} {generated_proof.strip()}"
                proof_normalization = "immutable_approved_claim_prefixed_to_generated_role"
        elif occurrences > 1:
            first = generated_proof.find(approved_claim)
            remainder = generated_proof[first + len(approved_claim) :].replace(
                approved_claim, ""
            )
            creative["proof_integration"] = (
                generated_proof[: first + len(approved_claim)] + remainder
            ).strip()
            proof_normalization = "duplicate_exact_claim_removed_without_rewriting_role"
    candidate: dict[str, Any] = {
        "schema": CANDIDATE_SCHEMA,
        "brief_sha256": plan["brief_sha256"],
        "request_sha256": request["request_sha256"],
        "surface_id": request["surface_id"],
        "business_model": request["business_model"],
        "native_format_contract": request["native_format_contract"],
        "surface_specialist_lens_ids": request["surface_specialist_lens_ids"],
        "edge_play_card_id": request["edge_play"]["edge_play_card_id"],
        **creative,
        "serialization_normalization": {
            "json_syntax": syntax_normalization,
            "progression": progression_normalization,
            "body": body_normalization,
            "proof_integration": proof_normalization,
            "falsifier_contains_proposed_numeric_threshold": bool(
                re.search(r"\b\d+(?:\.\d+)?\s*%", str(creative.get("falsifier", "")))
            ),
            "numeric_threshold_activation_allowed_without_owner_baseline": False,
            "creative_language_synthesized_by_adapter": False,
        },
        "measurement_contract": request["measurement_contract"],
        "release_state": "draft_pending_source_hidden_human_review",
        "external_publish_executed": False,
        "winner_selected": False,
    }
    candidate["content_sha256"] = digest(candidate)
    return candidate


def candidate_failures(
    candidate: object, *, plan: Mapping[str, Any], request: Mapping[str, Any]
) -> tuple[str, ...]:
    failures: list[str] = []
    if not isinstance(candidate, dict):
        return ("candidate must be an object",)
    if candidate.get("schema") != CANDIDATE_SCHEMA:
        failures.append("candidate schema mismatch")
    if candidate.get("content_sha256") != _content_digest(candidate):
        failures.append("candidate digest mismatch")
    immutable = {
        "brief_sha256": plan["brief_sha256"],
        "request_sha256": request["request_sha256"],
        "surface_id": request["surface_id"],
        "business_model": request["business_model"],
        "native_format_contract": request["native_format_contract"],
        "surface_specialist_lens_ids": request["surface_specialist_lens_ids"],
        "edge_play_card_id": request["edge_play"]["edge_play_card_id"],
        "measurement_contract": request["measurement_contract"],
        "release_state": "draft_pending_source_hidden_human_review",
        "external_publish_executed": False,
        "winner_selected": False,
    }
    for field, expected in immutable.items():
        if candidate.get(field) != expected:
            failures.append(f"immutable binding mismatch: {field}")
    normalization = candidate.get("serialization_normalization")
    if not isinstance(normalization, dict) or normalization.get(
        "creative_language_synthesized_by_adapter"
    ) is not False:
        failures.append("serialization normalization disclosure is invalid")
    for field in (
        "campaign_platform",
        "hook",
        "cta",
        "participation_mechanism",
        "proof_integration",
        "falsifier",
    ):
        if not _nonblank(candidate.get(field), minimum=12, maximum=1_600):
            failures.append(f"{field} must be a substantive bounded string")
    progression = candidate.get("progression")
    if not isinstance(progression, list) or len(progression) != 4 or any(
        not _nonblank(item, minimum=12, maximum=700) for item in progression
    ):
        failures.append("progression must contain exactly four substantive beats")
    body = candidate.get("body")
    body_minimum = (
        5
        if request.get("surface_id") in {"tiktok", "instagram", "x"}
        else 18
    )
    if not isinstance(body, list) or not 3 <= len(body) <= 7 or any(
        not _nonblank(item, minimum=body_minimum, maximum=1_200) for item in body
    ):
        failures.append("body must contain three to seven substantive native blocks")
    approved_claim = str(plan["brief"]["approved_claim"])
    proof = str(candidate.get("proof_integration", ""))
    if proof.count(approved_claim) != 1:
        failures.append("proof_integration must contain the exact approved claim once")
    serialized = canonical_json(candidate)
    folded = serialized.casefold()
    for marker in GENERIC_COPY_MARKERS:
        if marker in folded:
            failures.append(f"generic copy marker: {marker}")
    public_creative = canonical_json(
        {
            field: candidate.get(field)
            for field in CREATIVE_FIELDS
            if field != "falsifier"
        }
    )
    for pattern in FORBIDDEN_OUTCOME_PATTERNS:
        if _assertive_outcome_match(pattern, public_creative):
            failures.append(f"unsupported outcome claim: {pattern.pattern}")
    if re.search(r"\b\d+(?:\.\d+)?\s*%", public_creative):
        failures.append("numeric threshold requires an owner-authorized baseline")
    if any(tactic.replace("_", " ") in folded for tactic in EDGE_PROHIBITED_TACTICS):
        failures.append("candidate repeats a prohibited tactic as an instruction")
    blocks = [str(candidate.get("hook", ""))]
    if isinstance(progression, list):
        blocks.extend(str(item) for item in progression)
    if isinstance(body, list):
        blocks.extend(str(item) for item in body)
    normalized = [re.sub(r"\W+", " ", item.casefold()).strip() for item in blocks]
    if len(set(normalized)) != len(normalized):
        failures.append("candidate repeats a hook, beat or body block verbatim")
    return tuple(dict.fromkeys(failures))


def compile_platform_native_receipt(
    *,
    plan: Mapping[str, Any],
    model: Mapping[str, Any],
    attempts_by_surface: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    verify_platform_native_challenger_plan(plan)
    results: list[dict[str, Any]] = []
    accepted_candidates: list[dict[str, Any]] = []
    for request in plan["requests"]:
        surface_id = request["surface_id"]
        attempts = attempts_by_surface.get(surface_id, ())
        if not 1 <= len(attempts) <= 2:
            raise GTMPlatformNativeChallengerError(
                f"surface attempt count is invalid: {surface_id}"
            )
        sealed_attempts: list[dict[str, Any]] = []
        accepted: dict[str, Any] | None = None
        for index, attempt in enumerate(attempts, start=1):
            raw = str(attempt.get("raw_output", ""))
            try:
                parsed = extract_first_json_object(raw)
                candidate = adapt_platform_native_candidate(
                    parsed, plan=plan, request=request
                )
                failures = candidate_failures(
                    candidate, plan=plan, request=request
                )
            except GTMPlatformNativeChallengerError as error:
                candidate = None
                failures = (str(error),)
            sealed_attempts.append(
                {
                    "attempt": index,
                    "source": str(attempt.get("source", "generation")),
                    "elapsed_seconds": round(float(attempt.get("elapsed_seconds", 0.0)), 6),
                    "generated_token_count": int(attempt.get("generated_token_count", 0)),
                    "raw_output_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                    "contract_passed": not failures,
                    "failures": list(failures),
                }
            )
            if not failures and candidate is not None and accepted is None:
                accepted = candidate
        if accepted is not None:
            accepted_candidates.append(accepted)
        results.append(
            {
                "surface_id": surface_id,
                "accepted": accepted is not None,
                "accepted_candidate_sha256": (
                    accepted["content_sha256"] if accepted is not None else None
                ),
                "attempts": sealed_attempts,
            }
        )
    payload: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "status": (
            "generated_validated_pending_human_review"
            if len(accepted_candidates) == EXPECTED_SURFACE_COUNT
            else "partial_rejected_by_harness"
        ),
        "plan_sha256": plan["content_sha256"],
        "brief_sha256": plan["brief_sha256"],
        "business_model": plan["business_model"],
        "model": dict(model),
        "surface_count": EXPECTED_SURFACE_COUNT,
        "accepted_surface_count": len(accepted_candidates),
        "results": results,
        "accepted_candidates": accepted_candidates,
        "human_review_completed": False,
        "winner_selected": False,
        "external_publish_executed": False,
        "production_effect_observed": False,
        "four_a_claim_eligible": False,
        "top1_claim_eligible": False,
        "truth_boundary": (
            "This receipt proves model-assisted generation plus deterministic platform-contract validation only. "
            "It does not prove human preference, publication, organic breakout, conversion, revenue, 4A quality or named-product superiority."
        ),
    }
    payload["content_sha256"] = digest(payload)
    verify_platform_native_receipt(payload, plan=plan)
    return payload


def verify_platform_native_receipt(
    value: object, *, plan: Mapping[str, Any]
) -> None:
    verify_platform_native_challenger_plan(plan)
    if not isinstance(value, dict) or value.get("schema") != RECEIPT_SCHEMA:
        raise GTMPlatformNativeChallengerError("platform-native receipt schema is invalid")
    if value.get("content_sha256") != _content_digest(value):
        raise GTMPlatformNativeChallengerError("platform-native receipt digest is invalid")
    if value.get("plan_sha256") != plan.get("content_sha256"):
        raise GTMPlatformNativeChallengerError("platform-native receipt plan binding is invalid")
    results = value.get("results")
    candidates = value.get("accepted_candidates")
    if not isinstance(results, list) or len(results) != EXPECTED_SURFACE_COUNT:
        raise GTMPlatformNativeChallengerError("platform-native receipt coverage is invalid")
    if not isinstance(candidates, list):
        raise GTMPlatformNativeChallengerError("platform-native accepted candidates are invalid")
    by_surface = {request["surface_id"]: request for request in plan["requests"]}
    if [row.get("surface_id") for row in results] != list(by_surface):
        raise GTMPlatformNativeChallengerError("platform-native result order is invalid")
    if value.get("accepted_surface_count") != len(candidates):
        raise GTMPlatformNativeChallengerError("platform-native accepted count is invalid")
    for candidate in candidates:
        surface_id = normalize_surface_id(candidate.get("surface_id", ""))
        request = by_surface.get(surface_id)
        if request is None or candidate_failures(candidate, plan=plan, request=request):
            raise GTMPlatformNativeChallengerError(
                f"accepted platform-native candidate is invalid: {surface_id}"
            )
    for field in (
        "human_review_completed",
        "winner_selected",
        "external_publish_executed",
        "production_effect_observed",
        "four_a_claim_eligible",
        "top1_claim_eligible",
    ):
        if value.get(field) is not False:
            raise GTMPlatformNativeChallengerError(
                f"platform-native receipt authority was upgraded: {field}"
            )
