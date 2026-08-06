#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-last-mile-release-copy-v1"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def seal(value: dict) -> dict:
    payload = dict(value)
    payload["content_sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
    return payload


def tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    boundary = "Market response not observed."
    platforms = {
        "linkedin": {
            "surface": "linkedin_organic_carousel",
            "audience": "founder, VP Growth, product marketing and content leaders evaluating AI GTM work",
            "hook": "If your AI refuses to delete your best homepage line, it is working for the prompt—not for you.",
            "caption": (
                "If your AI refuses to delete your best homepage line, it is working for the prompt—not for you.\n\n"
                "Put the sentence you most want buyers to remember on trial.\n\n"
                "Ask for five witnesses:\n"
                "1. What was observed?\n"
                "2. Where is the source?\n"
                "3. In which population?\n"
                "4. Over what period?\n"
                "5. Under what limitation?\n\n"
                "The line in our launch rehearsal was: ‘An AI GTM employee that makes any brand go viral.’\n\n"
                "Observation: empty. Source: empty. Population: empty. Period: empty. Limitation: empty.\n\n"
                "So it lost its place on the homepage. Not false forever. Unsupported today.\n\n"
                "The narrower line survived: ProofLaunch Cortex-X compiles a rights-bound brief into review-ready GTM assets. "
                "That is a product behavior we can inspect; it is not evidence of preference, breakout, conversion, revenue or superiority.\n\n"
                "Run the 30-second self-trial: open your homepage, choose one outcome claim, ask ‘according to what?’, then label it hypothesis or delete it when the answer is only a model output, internal opinion or future plan.\n\n"
                "Keep the verdict private. If the deletion changes a real release decision, then inspect the workroom.\n\n"
                + boundary
            ),
            "single_action": "Open one homepage and put one outcome claim on trial privately.",
            "participation_seconds": 30,
            "native_mechanic": "founder/operator point of view plus a saveable document test; conversation starts from the reader's own release decision",
            "first_frame": "WE DELETED THE SENTENCE WE NEEDED MOST.",
            "cta": "Run the 30-second self-trial on one outcome claim; keep the verdict private.",
        },
        "tiktok": {
            "surface": "tiktok_private_upload_dry_run",
            "audience": "operators and creators who recognize overclaimed AI launch copy",
            "hook": "Your AI wrote the line. Now make it testify.",
            "caption": (
                "Your AI wrote the line. Now make it testify.\n\n"
                "Observation? Source? Population? Period? Limitation?\n"
                "Five blanks = delete.\n\n"
                "Run the 30-second witness check on one outcome claim before you watch our demo. Keep the verdict private.\n\n"
                "AI-generated campaign demonstration. " + boundary
            ),
            "title": "Your AI wrote it. Make it testify.",
            "single_action": "Pause on one homepage claim and test the five witness fields.",
            "participation_seconds": 30,
            "native_mechanic": "result-first visual deletion, five rapid prompts, no brand bumper, sound-optional comprehension",
            "first_frame": "YOUR AI WROTE THE LINE.",
            "cta": "Run the witness check on one outcome claim before watching the product demo.",
        },
        "instagram": {
            "surface": "instagram_organic_carousel",
            "audience": "visual operators who save reusable creative and review protocols",
            "hook": "Your homepage does not need another rewrite. It needs a witness.",
            "caption": (
                "Your homepage does not need another rewrite. It needs a witness.\n\n"
                "Swipe: sentence → docket → five blanks → deletion → 30-second self-trial.\n\n"
                "Save the test. Put one outcome claim on trial. Keep the verdict private.\n\n"
                "Not false forever. Unsupported today. " + boundary
            ),
            "single_action": "Save the five-field witness card and apply it to one claim.",
            "participation_seconds": 30,
            "native_mechanic": "visual redaction object plus a saveable five-frame diagnostic; caption does not repeat every slide",
            "first_frame": "WE DELETED THE SENTENCE WE NEEDED MOST.",
            "cta": "Save the witness card and test one outcome claim privately.",
        },
        "null_result_receipt": {
            "surface": "linkedin_organic_text",
            "audience": "campaign owners deciding whether to stop, repair or continue",
            "hook": "No victory post today.",
            "caption": (
                "No victory post today.\n\n"
                "The release room contains approved-shape drafts. The market has not answered.\n\n"
                "Impressions, likes and internal scores cannot promote this campaign. The next eligible signal is a named operator confirming that the witness check changed a real release decision.\n\n"
                "Until then: preference missing; breakout missing; conversion missing; revenue missing.\n\n"
                "Reuse the decision test—not our conclusion. " + boundary
            ),
            "single_action": "Record stop, repair or continue only after an eligible human decision signal.",
            "participation_seconds": 30,
            "native_mechanic": "public null-result receipt prevents a manufactured success recap",
            "first_frame": "NO VICTORY POST TODAY.",
            "cta": "Reuse the decision test, not the campaign conclusion.",
        },
    }
    hooks = [
        {"id": "h01", "text": platforms["linkedin"]["hook"], "surface": "linkedin", "decision": "selected", "mechanism": "buyer-side conflict plus category reversal"},
        {"id": "h02", "text": platforms["tiktok"]["hook"], "surface": "tiktok", "decision": "selected", "mechanism": "personified confrontation and visual verb"},
        {"id": "h03", "text": platforms["instagram"]["hook"], "surface": "instagram", "decision": "selected", "mechanism": "rewrite fatigue reversed into a visual diagnostic"},
        {"id": "h04", "text": "We built the world's most honest AI GTM employee.", "decision": "rejected", "reason": "brand-first, unproved superlative, no audience action"},
        {"id": "h05", "text": "AI marketing is broken.", "decision": "rejected", "reason": "category cliché with no proprietary tension"},
        {"id": "h06", "text": "Stop posting more content.", "decision": "rejected", "reason": "generic anti-volume posture; no mechanism"},
        {"id": "h07", "text": "This one prompt will change your marketing forever.", "decision": "rejected", "reason": "deceptive outcome framing and prompt-bait"},
        {"id": "h08", "text": "We deleted 99% of our launch.", "decision": "rejected", "reason": "numeric spectacle without a reader-useful decision rule"},
        {"id": "h09", "text": "The future of GTM is agents.", "decision": "rejected", "reason": "abstract prediction and no pattern interrupt"},
        {"id": "h10", "text": "What if your AI said no?", "decision": "rejected", "reason": "intriguing but too vague to self-select a qualified operator"},
        {"id": "h11", "text": "Your homepage is lying.", "decision": "rejected", "reason": "accusatory clickbait; collapses unsupported into false"},
        {"id": "h12", "text": "Five questions every marketer must ask.", "decision": "rejected", "reason": "listicle grammar removes the sacrifice and conflict"},
    ]
    audit = {
        "schema": "ProofLaunchGTMLastMileCreativeAuditV1",
        "evaluated_artifact": "postiz-dry-run-native-preview-v1",
        "before": [
            {"axis": "audience_as_subject", "status": "fail", "finding": "Primary LinkedIn copy opened with the brand's deletion story and explained the product before giving the reader an action."},
            {"axis": "concept_density", "status": "fail", "finding": "Witness, alibi, deletion, cohort, workroom and claim boundary competed in one caption."},
            {"axis": "participation_friction", "status": "fail", "finding": "Commenting with a claim class was abstract and did not complete the value exchange."},
            {"axis": "surface_divergence", "status": "fail", "finding": "TikTok and Instagram compressed the same explanation instead of assigning different platform behaviors."},
            {"axis": "null_result_design", "status": "pass", "finding": "The stop/repair/continue receipt already prevented manufactured victory language."},
        ],
        "repair": [
            "Make the buyer's release decision the first sentence.",
            "Give every surface one visual verb and one audience action.",
            "Set participation cost to thirty seconds and keep private copy private.",
            "Use LinkedIn for operator dialogue, TikTok for visible deletion, Instagram for a saved diagnostic.",
            "Compile every executable caption from one sealed fact and evidence contract.",
        ],
        "research_basis": [
            {"source": "LinkedIn Marketing Solutions", "url": "https://www.linkedin.com/business/marketing/blog/marketing-collective/how-to-create-high-impact-video-with-a-linkedin-expert", "used_for": "first 4–6 seconds, audience-first framing and no opening brand bumper"},
            {"source": "LinkedIn Marketing Solutions", "url": "https://www.linkedin.com/business/marketing/blog/trends-tips/b2b-insights-video-controls-conversation", "used_for": "human voice, trust and two-way conversation"},
            {"source": "TikTok For Business", "url": "https://ads.tiktok.com/business/en-US/blog/get-creative-6-storytelling-frameworks/", "used_for": "result-first narrative, user-centered story and low-cost native execution"},
        ],
    }
    contract = {
        "schema": "ProofLaunchGTMReleaseFactContractV1",
        "contract_id": "claim-trial-witness-check-release-v1",
        "approved_claim": "ProofLaunch Cortex-X compiles a rights-bound brief into review-ready GTM assets.",
        "approved_claim_source_id": "local-product-behavior-receipt-001",
        "quoted_rejected_claim": "An AI GTM employee that makes any brand go viral.",
        "quoted_rejected_claim_status": "unsupported_hypothesis_not_public_proof",
        "unobserved_outcomes": ["preference", "organic breakout", "conversion", "revenue", "named-product superiority"],
        "required_boundary_sentence": boundary,
        "human_release_required": True,
        "automatic_publish_enabled": False,
    }
    selected = [row for row in hooks if row["decision"] == "selected"]
    rejected = [row for row in hooks if row["decision"] == "rejected"]
    checks = {
        "selected_hook_count": len(selected),
        "rejected_hook_count": len(rejected),
        "every_surface_has_one_action": all(row["single_action"] for row in platforms.values()),
        "every_surface_under_30_second_participation": all(row["participation_seconds"] <= 30 for row in platforms.values()),
        "every_caption_has_required_boundary": all(boundary in row["caption"] for row in platforms.values()),
        "every_hook_is_caption_first_line": all(row["caption"].splitlines()[0] == row["hook"] for row in platforms.values()),
        "platform_hooks_are_lexically_distinct": max(
            len(tokens(left["hook"]) & tokens(right["hook"])) / max(1, len(tokens(left["hook"]) | tokens(right["hook"])))
            for index, left in enumerate(platforms.values())
            for right in list(platforms.values())[index + 1:]
        ) < 0.5,
        "external_market_effect_observed": False,
    }
    if not all(value for key, value in checks.items() if key != "external_market_effect_observed"):
        raise SystemExit(f"last-mile release copy failed contract: {checks}")
    payload = seal({
        "schema": "ProofLaunchGTMLastMileReleaseCopyV1",
        "campaign_id": "delete-one-line-organic-trial-v3",
        "strategy": "Make one unsupported outcome claim testify before the audience is asked to inspect the product.",
        "contract": contract,
        "audience_router": {
            "founder": "risk one memorable line rather than inherit a credibility debt",
            "vp_growth": "separate an attractive hypothesis from an eligible decision signal",
            "product_marketing": "turn claim review into a visible product behavior",
            "content_lead": "reduce review debt before increasing output volume",
        },
        "hook_tournament": hooks,
        "platforms": platforms,
        "checks": checks,
        "external_request_count": 0,
        "human_release_required": True,
        "truth_boundary": "This file seals platform-native release copy and its factual contract. It is authored campaign work, not evidence of human preference, organic breakout, conversion, revenue or superiority.",
    })
    atomic_write_text(OUTPUT / "release-copy.json", json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    audit_payload = seal(audit)
    atomic_write_text(OUTPUT / "creative-audit.json", json.dumps(audit_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT),
        "platform_count": len(platforms),
        "selected_hook_count": len(selected),
        "rejected_hook_count": len(rejected),
        "content_sha256": payload["content_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
