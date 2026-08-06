#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-execution-room-v1"
CASE_SYSTEM = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-breakout-operator-v1/case-system-v2.json"
JURY_RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-release-jury-v1/receipt.json"
VIDEO = ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-video-v1/keep-the-unpostable-vertical-4k-v1.mp4"
CAROUSEL = [
    ROOT / f"artifacts/gtm-last-mile-pk-v1/keep-unpostable-carousel-v1/slide-{index:02d}-1080x1350.png"
    for index in range(1, 6)
]


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def seal(value: dict) -> dict:
    payload = dict(value)
    payload["content_sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
    return payload


def media(path: Path, provider: str, index: int) -> dict:
    return {
        "local_path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "postiz_upload_id": f"{{{{POSTIZ_{provider.upper()}_MEDIA_ID_{index}}}}}",
        "postiz_https_path": f"{{{{POSTIZ_{provider.upper()}_HTTPS_URL_{index}}}}}",
    }


def postiz_request(provider: str, caption: str, assets: list[dict], settings: dict) -> dict:
    return {
        "method": "POST",
        "endpoint": "/public/v1/posts",
        "headers": {"Authorization": "{{POSTIZ_API_KEY}}"},
        "payload": {
            "type": "schedule",
            "date": "{{HUMAN_APPROVED_SCHEDULED_AT_UTC}}",
            "shortLink": False,
            "tags": ["prooflaunch", "keep-the-unpostable", "organic-zero-budget", "human-approved"],
            "posts": [
                {
                    "integration": {"id": f"{{{{POSTIZ_{provider.upper()}_INTEGRATION_ID}}}}"},
                    "value": [
                        {
                            "content": caption,
                            "image": [
                                {"id": item["postiz_upload_id"], "path": item["postiz_https_path"]}
                                for item in assets
                            ],
                        }
                    ],
                    "settings": settings,
                }
            ],
        },
    }


def route_payload(route: dict) -> dict:
    provider = route["channel_id"]
    if provider == "tiktok":
        caption = (
            "Your camera roll remembers everything except why it mattered.\n\n"
            "Tonight, don’t document your day. Steal one useless detail from it:\n"
            "the wrong song in the grocery store; the cup nobody else would notice; the sentence you almost forgot.\n\n"
            "Keep it private. Do it for seven days. Then keep, edit, export or delete the card.\n"
            "No streak. No reveal. The memory has to earn another week.\n\n"
            "Try it tonight. Comment KEEP—not the detail itself.\n\n"
            "Synthetic concept. No app, user result or market effect exists."
        )
        assets = [media(VIDEO, provider, 1)]
        settings = {
            "__type": "tiktok",
            "title": "Your day is not a documentary.",
            "privacy_level": "SELF_ONLY",
            "duet": False,
            "stitch": False,
            "comment": True,
            "autoAddMusic": "no",
            "brand_content_toggle": False,
            "brand_organic_toggle": False,
            "video_made_with_ai": True,
            "content_posting_method": "UPLOAD",
        }
        release_condition = "Release first after five-human jury passes; public privacy must be explicitly changed by the named owner."
    elif provider == "instagram":
        caption = (
            "DO NOT POST THIS.\n\n"
            "Your camera roll can be full while your week still feels missing.\n\n"
            "Before you add another memory habit, ask what it will make you perform:\n"
            "Will I polish it? Find an audience? Protect a streak? Turn the moment into content?\n\n"
            "If yes, choose a lighter format—or choose not to capture it.\n"
            "The right memory ritual may leave no post behind.\n\n"
            "Save this only if the four checks change one real choice tonight.\n\n"
            "Synthetic concept. No app, user result or market effect exists."
        )
        assets = [media(path, provider, index) for index, path in enumerate(CAROUSEL, 1)]
        settings = {
            "__type": "instagram",
            "post_type": "post",
            "is_trial_reel": False,
            "collaborators": [],
        }
        release_condition = "Release only as the secondary route after the primary is approved and the owner accepts the frozen diagnostic baseline."
    else:
        raise SystemExit(f"unsupported execution route: {provider}")

    trace_id = f"ku-{provider}-organic-v1"
    return {
        "id": route["id"],
        "provider": provider,
        "role": route["role"],
        "status": "READY_FOR_AUTHORIZED_DRY_RUN",
        "release_condition": release_condition,
        "caption": caption,
        "first_comment": route["first_comment"],
        "conversation_tree": route["conversation_tree"],
        "conversion_path": route["conversion_path"],
        "experiment": route["experiment"],
        "tracking": {
            "trace_id": trace_id,
            "outbound_url": None,
            "utm_template_reserved_for_owned_destination": {
                "utm_source": provider,
                "utm_medium": "organic_social",
                "utm_campaign": "keep_the_unpostable_v1",
                "utm_content": trace_id,
            },
            "privacy_rule": "Never capture the private moment, journal text or identifying commenter content.",
        },
        "media_upload_manifest": assets,
        "postiz_request": postiz_request(provider, caption, assets, settings),
        "release_guard": {
            "jury_pass_required": True,
            "named_release_owner_required": True,
            "rights_and_claims_check_required": True,
            "integration_mapping_required": True,
            "schedule_confirmation_required": True,
            "automatic_publish_enabled": False,
            "external_request_executed": False,
        },
    }


def validate(payload: dict) -> None:
    routes = payload["routes"]
    if [row["provider"] for row in routes] != ["tiktok", "instagram"]:
        raise SystemExit("execution room must preserve one primary TikTok route and one secondary Instagram route")
    if [row["role"] for row in routes] != ["PRIMARY", "SECONDARY"]:
        raise SystemExit("execution role contract drifted")
    if any(row["release_guard"]["automatic_publish_enabled"] for row in routes):
        raise SystemExit("automatic publication is forbidden")
    if any(row["release_guard"]["external_request_executed"] for row in routes):
        raise SystemExit("dry-run package cannot claim an external request")
    for row in routes:
        if "Synthetic concept. No app, user result or market effect exists." not in row["caption"]:
            raise SystemExit(f"truth boundary missing: {row['id']}")
        if not row["first_comment"] or len(row["conversation_tree"]) < 2:
            raise SystemExit(f"conversation execution incomplete: {row['id']}")
        if row["postiz_request"]["endpoint"] != "/public/v1/posts":
            raise SystemExit(f"Postiz endpoint drifted: {row['id']}")
        if row["tracking"]["outbound_url"] is not None:
            raise SystemExit(f"synthetic product cannot carry an outbound conversion URL: {row['id']}")


def html_page(payload: dict) -> str:
    compact = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Keep the Unpostable — Execution Room</title>
<style>
:root{{--ink:#090a08;--paper:#f3efe5;--acid:#e7ff3f;--pink:#ff3b6b;--blue:#4931ff;--line:#aaa59a}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.45 Inter,system-ui,sans-serif}}main{{width:min(1400px,calc(100% - 36px));margin:auto}}header{{padding:64px 0 38px;border-bottom:3px solid var(--ink)}}header small,.eyebrow,.gate b{{font:900 11px ui-monospace,monospace;letter-spacing:.12em}}h1{{font-size:clamp(62px,10vw,148px);line-height:.78;letter-spacing:-.08em;margin:25px 0}}header p{{font-size:22px;max-width:880px}}.status{{display:flex;gap:8px;flex-wrap:wrap}}.status span{{border:2px solid var(--ink);padding:8px 10px;font:900 10px ui-monospace,monospace}}.status span:first-child{{background:var(--acid)}}.routes{{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:36px 0}}article{{border:2px solid var(--ink);background:#fffdf7}}article>div{{padding:22px;border-top:1px solid var(--line)}}article h2{{font-size:44px;line-height:.9;margin:12px 0}}.route-head{{background:var(--ink);color:white;border:0;display:flex;justify-content:space-between}}pre{{white-space:pre-wrap;font:14px/1.55 ui-monospace,monospace;margin:0}}ul,ol{{padding-left:22px}}details{{border-top:1px solid var(--line);padding:12px 0}}summary{{font-weight:900;cursor:pointer}}.assets{{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}}.assets a{{min-height:78px;border:1px solid var(--ink);display:grid;place-items:center;text-align:center;padding:8px;font:800 10px ui-monospace,monospace;text-decoration:none}}.gate{{background:var(--acid)}}.gate b{{display:block;margin-bottom:8px}}.workflow{{border-top:3px solid var(--ink);padding:46px 0 80px}}.workflow-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}.workflow-grid div{{border:2px solid var(--ink);padding:18px;min-height:190px}}.workflow-grid b{{font-size:28px}}.boundary{{background:var(--pink);padding:20px;border:2px solid var(--ink);font-weight:850}}a.button{{display:inline-flex;background:var(--ink);color:white;padding:14px 18px;margin:8px 8px 0 0;text-decoration:none;font-weight:900}}@media(max-width:900px){{.routes,.workflow-grid{{grid-template-columns:1fr}}.assets{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main>
<header><small>PROOFLAUNCH / ZERO-BUDGET ORGANIC EXECUTION / V1</small><h1>SHIP THE<br>DECISION.</h1><p>Finished media, platform-native copy, first comments, objection handling, measurement and Postiz request bodies—one primary route, one secondary route, and no automatic publication.</p><div class="status"><span>2 ROUTES READY FOR AUTHORIZED DRY RUN</span><span>0 EXTERNAL REQUESTS</span><span>0 MARKET RESULTS</span></div></header>
<section class="routes" id="routes"></section>
<section class="workflow"><p class="eyebrow">GRAPH / LOOP / HARNESS</p><h2>Seven days. One decision per stage.</h2><div class="workflow-grid" id="workflow"></div><p class="boundary">Synthetic product fixture. The package proves execution readiness only. It does not prove preference, organic breakout, conversion, revenue or named-product superiority.</p><a class="button" href="../keep-unpostable-release-jury-v1/public/reviewer-01.html">OPEN HUMAN RELEASE JURY</a><a class="button" href="execution-bundle.json">DOWNLOAD EXECUTION JSON</a><a class="button" href="observation-template.json">DOWNLOAD 7-DAY OBSERVATION TEMPLATE</a><a class="button" href="learning-decision.json">INSPECT CURRENT LEARNING DECISION</a></section>
</main><script>const data={compact};
const assetLink=a=>`<a href="../../../../${{a.local_path}}" target="_blank">${{a.local_path.split('/').pop()}}</a>`;
document.querySelector('#routes').innerHTML=data.routes.map(r=>`<article><div class="route-head"><span>${{r.role}} / ${{r.provider.toUpperCase()}}</span><b>${{r.status}}</b></div><div><p class="eyebrow">RELEASE COPY</p><h2>${{r.caption.split('\\n')[0]}}</h2><pre>${{r.caption}}</pre></div><div><p class="eyebrow">FINISHED MEDIA / SHA-BOUND</p><div class="assets">${{r.media_upload_manifest.map(assetLink).join('')}}</div></div><div><p class="eyebrow">FIRST COMMENT</p><p>${{r.first_comment}}</p></div><div><p class="eyebrow">REPLY TREE</p>${{r.conversation_tree.map(x=>`<details><summary>${{x.trigger}}</summary><p>${{x.reply}}</p><small>ADVANCE IF — ${{x.advance_if}}</small></details>`).join('')}}</div><div><p class="eyebrow">QUALIFIED PATH</p><ol>${{r.conversion_path.map(x=>`<li>${{x}}</li>`).join('')}}</ol></div><div><p class="eyebrow">MEASUREMENT / KILL</p><p><b>PRIMARY —</b> ${{r.experiment.primary_metric}}</p><p><b>SECONDARY —</b> ${{r.experiment.secondary_metric}}</p><p><b>KILL —</b> ${{r.experiment.kill_rule}}</p></div><div class="gate"><b>HUMAN RELEASE GATE</b>${{r.release_condition}}<br>Postiz integration, HTTPS media IDs and UTC schedule remain placeholders. No request was sent.</div></article>`).join('');
document.querySelector('#workflow').innerHTML=data.execution_graph.map(x=>`<div><span class="eyebrow">${{x.when}}</span><h3>${{x.stage}}</h3><p>${{x.action}}</p><b>${{x.decision}}</b></div>`).join('');</script></body></html>'''


def main() -> None:
    for path in (CASE_SYSTEM, JURY_RECEIPT, VIDEO, *CAROUSEL):
        if not path.is_file():
            raise SystemExit(f"missing execution dependency: {path}")
    case_system = json.loads(CASE_SYSTEM.read_text(encoding="utf-8"))
    b2c_routes = case_system["cases"]["b2c"]["activation_wave"]
    routes = [route_payload(route) for route in b2c_routes]
    observation = {
        "schema": "ProofLaunchKeepUnpostableObservationV1",
        "campaign_id": "keep-the-unpostable-organic-v1",
        "status": "EMPTY_AWAITING_AUTHORIZED_RELEASE",
        "privacy": "Aggregate counts only; never record the private moment or journal text.",
        "rows": [
            {
                "provider": provider,
                "release_url": None,
                "released_at_utc": None,
                "exposures": None,
                "qualified_comprehension_actions": None,
                "qualified_private_starts": None,
                "day_7_decisions": {"keep": None, "edit": None, "export": None, "delete": None},
                "continue_opt_ins": None,
                "misread_as_public_reveal": None,
                "streak_pressure_objections": None,
                "owner_decision": None,
                "evidence_urls": [],
            }
            for provider in ("tiktok", "instagram")
        ],
    }
    payload = seal(
        {
            "schema": "ProofLaunchKeepUnpostableExecutionBundleV1",
            "campaign_id": "keep-the-unpostable-organic-v1",
            "business_model": "b2c",
            "budget": 0,
            "activation_policy": "one_primary_tiktok_plus_one_secondary_instagram",
            "routes": routes,
            "execution_graph": [
                {"when": "T-24H", "stage": "JURY + RIGHTS", "action": "Import five independent human reviews; verify rights, hashes and claim boundary.", "decision": "PASS / REPAIR / KILL"},
                {"when": "T-2H", "stage": "POSTIZ DRY RUN", "action": "Resolve named owner, integration IDs, HTTPS media IDs and UTC schedule; inspect provider preview.", "decision": "APPROVE / HOLD"},
                {"when": "T+0", "stage": "PRIMARY", "action": "Release TikTok only; pin the privacy-safe first comment; answer from the frozen reply tree.", "decision": "CONTINUE / KILL"},
                {"when": "T+24H", "stage": "SECONDARY", "action": "Release Instagram only if the owner accepts the primary comprehension evidence and frozen baseline.", "decision": "RELEASE / HOLD"},
                {"when": "T+72H", "stage": "EARLY READ", "action": "Count reproducible ritual comprehension and privacy misreads; ignore vanity likes as success.", "decision": "KEEP / REPAIR / STOP"},
                {"when": "T+7D", "stage": "QUALIFIED OUTCOME", "action": "Count keep/edit/export/delete decisions and explicit continuation; attach evidence URLs.", "decision": "SCALE / ITERATE / RETIRE"},
                {"when": "T+8D", "stage": "SELF-EVOLUTION", "action": "Compile descriptive evidence; promote only a human-approved lesson into memory with provenance, scope and expiry.", "decision": "ADOPT / REJECT"},
            ],
            "observation_template": "observation-template.json",
            "learning_decision_compiler": "scripts/compile_keep_unpostable_learning_decision_v1.py",
            "release_jury": {
                "href": "../keep-unpostable-release-jury-v1/public/reviewer-01.html",
                "expected_human_review_count": 5,
                "submitted_human_review_count": 0,
                "release_inferred": False,
            },
            "external_request_count": 0,
            "automatic_publish_enabled": False,
            "market_effect_observed": False,
            "truth_boundary": "This is an executable local dry-run bundle for a synthetic B2C concept. No external request, publication, preference, organic breakout, conversion, revenue or named-product win is claimed.",
        }
    )
    validate(payload)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUTPUT / "execution-bundle.json", json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(OUTPUT / "observation-template.json", json.dumps(observation, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(OUTPUT / "index.html", html_page(payload))
    bindings = [CASE_SYSTEM, JURY_RECEIPT, VIDEO, *CAROUSEL, OUTPUT / "execution-bundle.json", OUTPUT / "observation-template.json", OUTPUT / "index.html"]
    receipt = seal(
        {
            "schema": "ProofLaunchKeepUnpostableExecutionRoomReceiptV1",
            "artifact_id": "keep-unpostable-execution-room-v1",
            "route_count": 2,
            "primary_route_count": 1,
            "secondary_route_count": 1,
            "finished_media_count": 6,
            "postiz_request_count": 2,
            "conversation_reply_count": sum(len(row["conversation_tree"]) for row in routes),
            "execution_stage_count": len(payload["execution_graph"]),
            "external_request_count": 0,
            "automatic_publish_enabled": False,
            "market_effect_observed": False,
            "bindings": [
                {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
                for path in bindings
            ],
            "truth_boundary": payload["truth_boundary"],
        }
    )
    atomic_write_text(OUTPUT / "receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "route_count": 2, "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
