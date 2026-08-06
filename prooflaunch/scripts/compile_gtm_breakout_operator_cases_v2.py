#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-breakout-operator-v1"
B2B_SOURCE = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v16/b2b-codex-editorial-war-room-receipt.json"
B2C_SOURCE = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v14/b2c-codex-reference-v1-receipt.json"
HANDOFF_SOURCE = ROOT / "evidence/v10/gtm-craft-handoff-matrix-v1.json"


LABELS = {
    "linkedin": "LINKEDIN",
    "tiktok": "TIKTOK",
    "reddit": "REDDIT",
    "youtube": "YOUTUBE",
    "instagram": "INSTAGRAM",
    "x": "X",
    "google_search": "GOOGLE / SEO",
    "bing_search": "BING / SEO",
    "chatgpt_answers": "CHATGPT / GEO",
    "claude_answers": "CLAUDE / GEO",
    "gemini_answers": "GEMINI / GEO",
    "perplexity_answers": "PERPLEXITY / GEO",
    "copilot_answers": "COPILOT / ENTERPRISE GEO",
}

ACTIVATION_ROLES = {
    "b2b": {
        "linkedin": "PRIMARY",
        "reddit": "SECONDARY",
        "google_search": "RETRIEVAL SUPPORT",
        "bing_search": "RETRIEVAL SUPPORT",
        "chatgpt_answers": "RETRIEVAL SUPPORT",
        "claude_answers": "RETRIEVAL SUPPORT",
        "gemini_answers": "RETRIEVAL SUPPORT",
        "perplexity_answers": "RETRIEVAL SUPPORT",
        "copilot_answers": "RETRIEVAL SUPPORT",
    },
    "b2c": {
        "tiktok": "PRIMARY",
        "instagram": "SECONDARY",
        "google_search": "RETRIEVAL SUPPORT",
        "bing_search": "RETRIEVAL SUPPORT",
        "chatgpt_answers": "RETRIEVAL SUPPORT",
        "claude_answers": "RETRIEVAL SUPPORT",
        "gemini_answers": "RETRIEVAL SUPPORT",
        "perplexity_answers": "RETRIEVAL SUPPORT",
        "copilot_answers": "RETRIEVAL SUPPORT",
    },
}


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def load_receipt(path: Path, *, business_model: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("business_model") != business_model:
        raise SystemExit(f"business model drifted: {path}")
    candidates = payload.get("accepted_candidates")
    if not isinstance(candidates, list) or len(candidates) != 13:
        raise SystemExit(f"expected thirteen accepted candidates: {path}")
    if payload.get("human_review_completed") is not False or payload.get("winner_selected") is not False:
        raise SystemExit(f"source overstates human review or a winner: {path}")
    if payload.get("external_publish_executed") is not False or payload.get("production_effect_observed") is not False:
        raise SystemExit(f"source overstates external execution: {path}")
    expected = set(LABELS)
    observed = {candidate.get("surface_id") for candidate in candidates}
    if observed != expected:
        raise SystemExit(f"surface coverage drifted: {path}")
    return payload


def channel(candidate: dict[str, Any], *, business_model: str) -> dict[str, Any]:
    measurement = candidate["measurement_contract"]
    return {
        "id": candidate["surface_id"],
        "label": LABELS[candidate["surface_id"]],
        "activation_role": ACTIVATION_ROLES[business_model].get(candidate["surface_id"], "HELD UNTIL SIGNAL"),
        "format": candidate["native_format_contract"].upper(),
        "hook": candidate["hook"],
        "lines": candidate["body"],
        "cta": candidate["cta"],
        "native_move": candidate["participation_mechanism"],
        "gate": "PENDING",
        "notes": [
            *candidate["progression"],
            "SPECIALIST LENSES — " + " · ".join(candidate["surface_specialist_lens_ids"]),
        ],
        "kill": candidate["falsifier"],
        "proof": candidate["proof_integration"],
        "measurement": {
            "primary": measurement["primary_measurement"],
            "baseline_window": measurement["baseline_window"],
            "test_design": measurement["test_design"],
            "activation_state": measurement["activation_state"],
            "causal_claim_allowed": measurement["causal_claim_allowed"],
        },
        "release_state": candidate["release_state"],
        "source_candidate_sha256": candidate["content_sha256"],
    }


def build_cases(b2b: dict[str, Any], b2c: dict[str, Any]) -> dict[str, Any]:
    return {
        "b2b": {
            "hero_deck": "Most AI GTM demos audition for output volume. This one auditions for judgment: which work gets refused, which evidence survives, and which human still owns release.",
            "product": "ProofLaunch — governed AI GTM employee",
            "stage": "Design-partner launch",
            "audience_short": "Founder-led B2B / VP Growth",
            "audience": "Founder-led B2B AI teams choosing whether an autonomous GTM employee deserves release authority",
            "disclosure": "PRODUCT-BEHAVIOR FIXTURE · HUMAN PREFERENCE AND MARKET RESPONSE NOT OBSERVED",
            "why_now": "Output is abundant. Refusal quality, provenance and platform-native judgment are the scarce product.",
            "evidence": "Thirteen platform-native drafts passed deterministic contracts; no human preference, publication, lift, conversion or revenue is observed.",
            "bet": "THE 40-ASSET INTERVIEW",
            "kill": "Qualified GTM operators cannot use the rejection rule to change one real release or vendor-selection decision.",
            "tension": "Do not ask what the AI can make. Ask what it is willing to cost the launch.",
            "signals": [
                ["CATEGORY SATURATION", "Every AI GTM product can fill a content calendar."],
                ["BUYER RISK", "Polished output can conceal unsupported claims, missing authority and broken handoffs."],
                ["OWNABLE DEMO", "A visible refusal exposes judgment, evidence lineage and the remaining human decision."],
            ],
            "platform": "THE 40-ASSET INTERVIEW",
            "platform_explainer": "Pin forty plausible assets to the wall. Make the employee reject thirty-nine with FACT, INFERENCE, HYPOTHESIS or BLOCKED labels. The surviving card must carry its evidence object, limitation and release owner.",
            "formula": "OUTPUT ABUNDANCE → REFUSAL TEST → EVIDENCE OBJECT → HUMAN RELEASE DECISION",
            "primary_channel": "PRIMARY / LINKEDIN — qualified operator judgment",
            "secondary_channel": "SECONDARY / REDDIT — disclosed builder critique",
            "support_channels": "SUPPORT / GOOGLE + AI ANSWERS — evidence retrieval",
            "held_channel_count": "HOLD / 9 SURFACES UNTIL QUALIFIED SIGNAL",
            "declines": [
                "feature tour", "generic AI list", "auto-DM bait", "fake founder confession", "engagement bait",
                "unbounded ROI claim", "cross-posted caption", "trend recap", "launch countdown", "vanity dashboard",
                "undisclosed automation", "winner claim before review",
            ],
            "channels": [channel(candidate, business_model="b2b") for candidate in b2b["accepted_candidates"]],
            "activation_wave": [
                {
                    "id": "b2b-linkedin-primary",
                    "role": "PRIMARY",
                    "surface": "LINKEDIN",
                    "channel_id": "linkedin",
                    "job": "Make refusal quality the buying criterion for governed AI GTM employees.",
                    "release_asset": "40-ASSET INTERVIEW / operator post",
                    "first_comment": "Four labels. FACT: directly supported. INFERENCE: editorial judgment. HYPOTHESIS: a result still awaiting observation. BLOCKED: rights, evidence or authority missing. Apply them to the smoothest sentence in your current launch—not the ugliest one.",
                    "conversation_tree": [
                        {
                            "trigger": "This is compliance theater.",
                            "reply": "Then the rule should fail a practical test: if it cannot remove a meeting, change a release decision or expose a missing evidence object, kill it. The target is decision latency, not paperwork.",
                            "advance_if": "The operator supplies one real handoff where the rule changes cycle time or release scope.",
                        },
                        {
                            "trigger": "A real agent should publish autonomously.",
                            "reply": "Internal autonomy and external authority are different axes. Let the model explore aggressively inside the node; require a named owner when an unsupported claim, spend or public action leaves it.",
                            "advance_if": "The buyer names the exact external action and acceptable authority boundary.",
                        },
                        {
                            "trigger": "Our team already has approvals.",
                            "reply": "Can the team reconstruct which evidence justified the final sentence after the Slack thread disappears? Approval without the evidence object is a memory of a decision, not a review trail.",
                            "advance_if": "The operator agrees to run one privacy-safe reconstruction test.",
                        },
                    ],
                    "conversion_path": [
                        "Post → save the four-label rejection card",
                        "Run one privacy-safe claim trial on a current draft",
                        "Return only the changed decision and missing evidence class",
                        "Open the bounded design-partner evidence pack",
                        "Human decides whether a 30-minute evidence review is justified",
                    ],
                    "experiment": {
                        "hypothesis": "A disqualification-first operator test earns more qualified evidence-review requests than a feature-led AI employee post.",
                        "test_window": "One audience-local weekday post plus seven calendar days of qualified-response observation; timing is a test setting, not a claimed optimum.",
                        "baseline_required": "One prior feature-led post or a frozen no-post cohort with the same qualified audience definition.",
                        "primary_metric": "Qualified operators who apply the four labels and report a changed release or buying decision.",
                        "secondary_metric": "Evidence-pack opens from those qualified operators, not raw impressions or generic comments.",
                        "kill_rule": "Stop after the bounded window when no qualified operator can apply the rule or the rule changes no decision.",
                    },
                    "human_release_required": True,
                    "external_execution": False,
                    "status": "READY_FOR_HUMAN_RELEASE_REVIEW",
                },
                {
                    "id": "b2b-reddit-secondary",
                    "role": "SECONDARY",
                    "surface": "REDDIT",
                    "channel_id": "reddit",
                    "job": "Invite practitioners to break the refusal rule in public without disguising the builder affiliation.",
                    "release_asset": "WE STOPPED THE DEMO / disclosed operator teardown",
                    "first_comment": "Builder here. The narrow question is not whether the product looks useful. What real launch sentence can pass CLAUSE + EVIDENCE + HYPOTHESIS + OWNER and still deserve rejection? A counterexample is more valuable than praise; do not paste private campaign material.",
                    "conversation_tree": [
                        {
                            "trigger": "This is self-promotion.",
                            "reply": "Correct that we built it; the affiliation is the first line. The useful claim must survive without the product: try the four fields on your own draft and reject the framework if it adds no decision value.",
                            "advance_if": "A practitioner tests the rule or supplies a concrete counterexample.",
                        },
                        {
                            "trigger": "The framework is too simplistic.",
                            "reply": "Name the missing field and the decision it changes. We will add it only if the counterexample is reproducible and does not collapse evidence, judgment and authority into one bucket.",
                            "advance_if": "The missing field is tied to a reproducible release failure.",
                        },
                    ],
                    "conversion_path": [
                        "Rules-compatible disclosed teardown",
                        "Privacy-safe practitioner counterexample",
                        "Public repair or explicit rejection of the rule",
                        "Optional evidence-pack inspection only after material fit",
                    ],
                    "experiment": {
                        "hypothesis": "A falsification request produces more qualified operator learning than a demo link or launch announcement.",
                        "test_window": "One approved community thread; observe until the community's normal discussion half-life ends.",
                        "baseline_required": "A prior disclosed builder post with comparable community fit, or no causal comparison claim.",
                        "primary_metric": "Distinct, reproducible practitioner counterexamples or privacy-safe applications of the rule.",
                        "secondary_metric": "Material repairs accepted into the next rule version.",
                        "kill_rule": "Remove or stop the route when moderator fit is absent, affiliation is misunderstood, or replies are promotional rather than diagnostic.",
                    },
                    "human_release_required": True,
                    "external_execution": False,
                    "status": "READY_FOR_HUMAN_RELEASE_REVIEW",
                },
            ],
            "sequence": [
                ["BEAT 1 / DISQUALIFY", "Release the rejection interview, not a feature list.", "Advance only when a qualified operator can apply the labels without explanation."],
                ["BEAT 2 / TRANSFER UTILITY", "Give the audience the evidence card and decision rule.", "Advance only when the rule changes a real draft or buying question."],
                ["BEAT 3 / SHOW THE TRAIL", "Expose one permissioned brief-to-release chain.", "Advance only while fact, inference, owner and limitation remain reconstructable."],
                ["BEAT 4 / INVITE INSPECTION", "Offer a bounded design-partner evidence review.", "Stop when authority, fit, evidence access or human release ownership is absent."],
            ],
            "metric_attention": "Qualified dwell through the rejection rule—not raw impressions.",
            "metric_participation": "A real draft or vendor answer receives a FACT / INFERENCE / HYPOTHESIS / BLOCKED decision.",
            "metric_action": "A named qualified operator changes a release or buying decision and requests the evidence pack.",
        },
        "b2c": {
            "hero_deck": "Most memory apps turn remembering into homework or performance. This synthetic concept asks for one ordinary private moment, then makes the weekly artifact earn another seven days.",
            "product": "LoopNote — synthetic private-reflection benchmark",
            "stage": "Synthetic zero-budget consumer launch",
            "audience_short": "Busy mobile users / private reflectors",
            "audience": "Busy mobile users who abandon high-effort journaling and do not want personal memory turned into a feed",
            "disclosure": "SYNTHETIC PRODUCT FIXTURE · NO APP, USER RESULT OR MARKET EFFECT EXISTS",
            "why_now": "Capture is effortless but remembering is performative; streak pressure and public reaction contaminate the ritual.",
            "evidence": "The benchmark concept defines one private daily capture and a weekly reflection card; usefulness, retention and demand remain unobserved.",
            "bet": "KEEP THE UNPOSTABLE",
            "kill": "Users cannot reproduce the tiny private ritual, or the weekly card is not useful without streak pressure, public sharing or richer context.",
            "tension": "Your day does not need a documentary—and your memory does not need an audience.",
            "signals": [
                ["HABIT FATIGUE", "Journaling asks for reflection precisely when people have the least time."],
                ["PERFORMANCE PRESSURE", "Public feeds reward shareability rather than personal meaning."],
                ["OWNABLE RITUAL", "One ordinary private moment becomes a weekly card the user may keep, edit or delete."],
            ],
            "platform": "KEEP THE UNPOSTABLE",
            "platform_explainer": "Ask for one tiny private moment per day. Never demand a streak or reveal. On day seven, return a reflection card whose usefulness—not public engagement—decides whether the ritual continues.",
            "formula": "ORDINARY MOMENT → PRIVATE CAPTURE → WEEKLY CARD → USER-CONTROLLED MEMORY",
            "primary_channel": "PRIMARY / TIKTOK — ritual comprehension",
            "secondary_channel": "SECONDARY / INSTAGRAM — save-worthy private moment",
            "support_channels": "SUPPORT / SEARCH + AI ANSWERS — category education",
            "held_channel_count": "HOLD / 9 SURFACES UNTIL QUALIFIED SIGNAL",
            "declines": [
                "streak shame", "public reveal", "nostalgia manipulation", "fake UGC", "loss anxiety", "influencer praise",
                "trend dance", "giveaway gate", "auto-share default", "clinical claim", "manufactured social proof", "retention claim",
            ],
            "channels": [channel(candidate, business_model="b2c") for candidate in b2c["accepted_candidates"]],
            "activation_wave": [
                {
                    "id": "b2c-tiktok-primary",
                    "role": "PRIMARY",
                    "surface": "TIKTOK",
                    "channel_id": "tiktok",
                    "job": "Make a private one-moment ritual reproducible in fifteen seconds without turning privacy into a reveal mechanic.",
                    "release_asset": "YOUR DAY IS NOT A DOCUMENTARY / 15-second vertical",
                    "first_comment": "The challenge is private. If you try it, reply only KEEP—not the moment itself. On day seven, the card must earn another week; a streak does not.",
                    "production_contract": [
                        "0:00–0:02 — blank journal opens, hesitates, closes; on-screen: YOUR DAY IS NOT A DOCUMENTARY",
                        "0:02–0:05 — one ordinary detail is marked beside the phone; VO: Give one detail a place to stay",
                        "0:05–0:09 — seven small frames collect behind an opaque privacy screen; no private content is readable",
                        "0:09–0:12 — weekly card remains face-down; on-screen: KEEP · EDIT · EXPORT · DELETE",
                        "0:12–0:15 — quiet hold; on-screen: KEEP THE UNPOSTABLE / SYNTHETIC CONCEPT · NO USER RESULT",
                    ],
                    "production_assets": [
                        {"kind": "video", "label": "VIDEO / 15S 4K CHALLENGER", "href": "../keep-unpostable-video-v1/keep-the-unpostable-vertical-4k-v1.mp4"},
                        {"kind": "audio", "label": "VOICE A / PRIVATE DOCUMENTARY", "href": "../keep-unpostable-audio-v1/master/voice-private-documentary-a-48k-stereo-24bit.wav"},
                        {"kind": "audio", "label": "VOICE B / DRY CONFIDANT", "href": "../keep-unpostable-audio-v1/master/voice-dry-confidant-b-48k-stereo-24bit.wav"},
                        {"kind": "audio", "label": "VOICE C / GENTLE EDITOR", "href": "../keep-unpostable-audio-v1/master/voice-gentle-editor-c-48k-stereo-24bit.wav"},
                    ],
                    "release_review": {
                        "id": "keep-unpostable-release-jury-v1",
                        "status": "AWAITING_FIVE_INDEPENDENT_HUMANS",
                        "expected_human_review_count": 5,
                        "submitted_human_review_count": 0,
                        "reviewer_hrefs": [
                            f"../keep-unpostable-release-jury-v1/public/reviewer-{index:02d}.html"
                            for index in range(1, 6)
                        ],
                    },
                    "execution_room": {
                        "id": "keep-unpostable-execution-room-v1",
                        "status": "READY_FOR_AUTHORIZED_DRY_RUN",
                        "href": "../keep-unpostable-execution-room-v1/index.html",
                        "route_count": 2,
                        "external_request_count": 0,
                    },
                    "conversation_tree": [
                        {
                            "trigger": "So we post the memory on day seven?",
                            "reply": "No. Optional sharing is not the payoff. The owner decides whether the private artifact is useful, edits or deletes it, then chooses whether to continue.",
                            "advance_if": "The viewer can restate the ritual without a public reveal.",
                        },
                        {
                            "trigger": "This is still another streak app.",
                            "reply": "Missing a day must create no penalty, badge or catch-up task. If the ritual produces guilt, the concept fails its own benchmark.",
                            "advance_if": "The viewer identifies a concrete pressure mechanism to remove.",
                        },
                    ],
                    "conversion_path": [
                        "15-second ritual comprehension",
                        "Privacy-safe KEEP response or private challenge start",
                        "Day-seven usefulness decision: keep, edit, export or delete",
                        "Explicit continue/stop choice; no forced signup or share",
                    ],
                    "experiment": {
                        "hypothesis": "A private, anti-documentary ritual produces more accurate action recall than a feature montage or streak promise.",
                        "test_window": "One human-approved post and a seven-day ritual window; no retention conclusion before day seven.",
                        "baseline_required": "A frozen feature-led 15-second concept shown to the same intended audience definition.",
                        "primary_metric": "Viewers who can reproduce the one-moment rule and privacy boundary without explanation.",
                        "secondary_metric": "Owners who reach a day-seven keep/edit/export/delete decision and explicitly choose whether to continue.",
                        "kill_rule": "Stop when viewers expect a public reveal, feel streak pressure, or cannot reproduce the action after one viewing.",
                    },
                    "human_release_required": True,
                    "external_execution": False,
                    "status": "READY_FOR_HUMAN_RELEASE_REVIEW",
                },
                {
                    "id": "b2c-instagram-secondary",
                    "role": "SECONDARY",
                    "surface": "INSTAGRAM",
                    "channel_id": "instagram",
                    "job": "Turn privacy and effort into a save-worthy five-slide diagnostic rather than a product carousel.",
                    "release_asset": "KEEP THE UNPOSTABLE / five-slide diagnostic",
                    "first_comment": "Save this only if the four checks change a real capture choice: polishing, audience, streak, emotional performance. The synthetic concept has no user result yet.",
                    "production_contract": [
                        "Slide 1 — YOUR DAY IS NOT CONTENT / uncaptured coffee ring / no app UI",
                        "Slide 2 — KEEP ONE DETAIL / texture, sound, sentence, color or place",
                        "Slide 3 — PRIVATE MEANS UNREADABLE HERE / weekly card stays visually obscured",
                        "Slide 4 — CHECK THE BURDEN / polishing · audience · streak · emotional performance",
                        "Slide 5 — REVIEW, DO NOT PERFORM / useful? keep · edit · export · delete",
                    ],
                    "production_assets": [
                        {"kind": "image", "label": "01 / DO NOT POST THIS", "href": "../keep-unpostable-carousel-v1/slide-01-1080x1350.png"},
                        {"kind": "image", "label": "02 / KEEP ONE USELESS DETAIL", "href": "../keep-unpostable-carousel-v1/slide-02-1080x1350.png"},
                        {"kind": "image", "label": "03 / HIDE THE PAYOFF", "href": "../keep-unpostable-carousel-v1/slide-03-1080x1350.png"},
                        {"kind": "image", "label": "04 / REMOVE THE PRESSURE", "href": "../keep-unpostable-carousel-v1/slide-04-1080x1350.png"},
                        {"kind": "image", "label": "05 / DID IT EARN ANOTHER WEEK", "href": "../keep-unpostable-carousel-v1/slide-05-1080x1350.png"},
                    ],
                    "conversation_tree": [
                        {
                            "trigger": "Why capture anything at all?",
                            "reply": "You may not need to. The diagnostic is successful when it helps someone choose the lightest adequate format—including no capture.",
                            "advance_if": "The viewer names the memory job and rejects an unnecessary format.",
                        },
                        {
                            "trigger": "Low effort loses context.",
                            "reply": "That is the central trade-off. Rich chronology, shared archives, clinical guidance and legal records should reject this route; ordinary private reflection may not need them.",
                            "advance_if": "The viewer can identify the minimum context their memory job requires.",
                        },
                    ],
                    "conversion_path": [
                        "Save the four-check diagnostic",
                        "Apply it to one real capture decision",
                        "Choose the lightest adequate format or no capture",
                        "Try the private seven-day ritual only when the diagnostic still fits",
                    ],
                    "experiment": {
                        "hypothesis": "A privacy-and-burden diagnostic earns more qualified saves and correct fit decisions than a synthetic product feature carousel.",
                        "test_window": "One human-approved carousel; measure qualified application over seven days, not same-day likes.",
                        "baseline_required": "A frozen feature carousel with the same visual production quality and audience definition.",
                        "primary_metric": "Viewers who apply the four checks and report a changed format or no-capture decision.",
                        "secondary_metric": "Qualified private-challenge starts after the diagnostic, separated from generic saves.",
                        "kill_rule": "Stop when viewers infer public sharing, clinical benefit, observed retention or a universal recommendation.",
                    },
                    "human_release_required": True,
                    "external_execution": False,
                    "status": "READY_FOR_HUMAN_RELEASE_REVIEW",
                },
            ],
            "sequence": [
                ["DAY 0 / CONTRACT", "Show the one-moment rule, privacy boundary and delete control.", "Advance only when a user can state the ritual and its trade-off."],
                ["DAYS 1–7 / KEEP", "Capture one ordinary moment without a public obligation.", "Do not reward streaks, volume or sharing."],
                ["DAY 7 / RETURN", "Generate the private weekly reflection card.", "Advance only when the owner finds the card useful and can edit, export or delete it."],
                ["WEEK 2 / CHOOSE", "Let the user continue, change the ritual or stop.", "Stop when low effort removes needed meaning or crosses clinical, legal or shared-record needs."],
            ],
            "metric_attention": "Qualified hold through the privacy contract and one-moment demonstration.",
            "metric_participation": "A private seven-day ritual is completed without forced sharing or streak pressure.",
            "metric_action": "The owner keeps, edits, exports or deletes a useful weekly card and explicitly chooses whether to continue.",
        },
    }


def main() -> None:
    b2b = load_receipt(B2B_SOURCE, business_model="b2b")
    b2c = load_receipt(B2C_SOURCE, business_model="b2c")
    handoff = json.loads(HANDOFF_SOURCE.read_text(encoding="utf-8"))
    coverage = handoff.get("coverage", {})
    if coverage.get("activated_handoff_role_count") != 12 or coverage.get("territory_handoff_count") != 432:
        raise SystemExit("craft handoff coverage drifted")
    cases = build_cases(b2b, b2c)

    script_path = OUTPUT / "operator.js"
    script = script_path.read_text(encoding="utf-8")
    replacement = "const cases = " + json.dumps(cases, ensure_ascii=False, indent=2, sort_keys=False) + ";\n\nlet activeCase"
    updated, count = re.subn(r"\Aconst cases = \{.*?\n\};\n\nlet activeCase", replacement, script, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit("operator case block could not be replaced exactly once")
    atomic_write_text(script_path, updated)

    case_system = {
        "schema": "ProofLaunchGTMLastMileCaseSystemV2",
        "case_count": 2,
        "surface_count_per_case": 13,
        "platform_native_delivery_count": 26,
        "cases": cases,
        "source_bindings": [
            {"path": str(B2B_SOURCE.relative_to(ROOT)), "sha256": sha256_file(B2B_SOURCE)},
            {"path": str(B2C_SOURCE.relative_to(ROOT)), "sha256": sha256_file(B2C_SOURCE)},
            {"path": str(HANDOFF_SOURCE.relative_to(ROOT)), "sha256": sha256_file(HANDOFF_SOURCE)},
        ],
        "craft_handoff_coverage": {
            "activated_handoff_role_count": coverage["activated_handoff_role_count"],
            "activated_handoff_role_ids": coverage["activated_handoff_role_ids"],
            "context_count": coverage["context_count"],
            "territory_handoff_count": coverage["territory_handoff_count"],
            "producer_reviewer_separation_pass_count": coverage["producer_reviewer_separation_pass_count"],
            "human_release_required_count": coverage["human_release_required_count"],
            "surface_specialist_lens_assignment_count": coverage["surface_specialist_lens_assignment_count"],
            "unconventional_edge_play_binding_count": coverage["unconventional_edge_play_binding_count"],
        },
        "activation_policy": {
            "maximum_simultaneous_primary_channels_per_case": 1,
            "maximum_simultaneous_secondary_channels_per_case": 1,
            "support_surfaces_are_retrieval_only_until_signal": True,
            "remaining_surfaces_are_held_until_human_approved_signal": True,
            "b2b": {
                "primary": "linkedin",
                "secondary": "reddit",
                "support": ["google_search", "bing_search", "chatgpt_answers", "claude_answers", "gemini_answers", "perplexity_answers", "copilot_answers"],
                "held": ["tiktok", "youtube", "instagram", "x"],
            },
            "b2c": {
                "primary": "tiktok",
                "secondary": "instagram",
                "support": ["google_search", "bing_search", "chatgpt_answers", "claude_answers", "gemini_answers", "perplexity_answers", "copilot_answers"],
                "held": ["linkedin", "reddit", "youtube", "x"],
            },
        },
        "human_review_completed": False,
        "winner_selected": False,
        "external_publish_executed": False,
        "market_effect_observed": False,
        "truth_boundary": (
            "This artifact integrates twenty-six platform-contract-valid draft candidates and a typed craft handoff matrix. "
            "It does not prove human preference, 4A quality, publication, organic breakout, conversion, revenue or named-product superiority."
        ),
    }
    case_system["content_sha256"] = hashlib.sha256(canonical(case_system)).hexdigest()
    atomic_write_text(OUTPUT / "case-system-v2.json", json.dumps(case_system, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT),
        "platform_native_delivery_count": 26,
        "activated_handoff_role_count": 12,
        "content_sha256": case_system["content_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
