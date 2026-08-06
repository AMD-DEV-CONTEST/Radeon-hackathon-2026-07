#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/40-asset-interview-execution-room-v1"
CASE_SYSTEM = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-breakout-operator-v1/case-system-v2.json"
VIDEO = ROOT / "artifacts/gtm-last-mile-pk-v1/video-challenger-v8-40-asset-interview/vertical_4k/prooflaunch-40-asset-interview-vertical_4k.mp4"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def seal(value: dict) -> dict:
    payload = dict(value)
    payload["content_sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
    return payload


def main() -> None:
    for path in (CASE_SYSTEM, VIDEO):
        if not path.is_file():
            raise SystemExit(f"missing B2B execution dependency: {path}")
    case_system = json.loads(CASE_SYSTEM.read_text(encoding="utf-8"))
    source_routes = {row["channel_id"]: row for row in case_system["cases"]["b2b"]["activation_wave"]}
    linkedin_source = source_routes["linkedin"]
    reddit_source = source_routes["reddit"]
    linkedin_caption = (
        "Your AI GTM employee is not a colleague until it can fire its own best sentence.\n\n"
        "We asked ours for 40 launch assets. It gave us 40. So we changed the interview:\n\n"
        "Delete 39. Defend the survivor. Show the witness for every claim.\n\n"
        "The prettiest line died first: ‘turns interest into qualified pipeline.’\n"
        "Not because it was bad copy. Because nobody could produce the event that made it true.\n\n"
        "The survivor was less impressive—and more useful: ‘compiles a rights-bound brief into review-ready GTM assets.’\n\n"
        "Steal the interview. Take the smoothest outcome sentence in your launch. Mark it FACT / INFERENCE / HYPOTHESIS / BLOCKED. Ask who owns the evidence. If the room goes quiet, fire the sentence.\n\n"
        "What line would your agent have to fire?\n\n"
        "ProofLaunch compiles a rights-bound brief into review-ready GTM assets. This synthetic capability case reports no customer result, market lift, conversion, revenue or superiority."
    )
    reddit_caption = (
        "Builder disclosure: we built ProofLaunch Cortex-X. This is an operator teardown, not an independent recommendation.\n\n"
        "We stopped our AI GTM demo one screen before the ‘magic’—at the point where the agent should refuse the sentence ‘turns interest into qualified pipeline.’ The brief contains no audience response, opportunity or revenue event.\n\n"
        "Our proposed test is narrow: CLAUSE + EVIDENCE + HYPOTHESIS + OWNER. If those four fields cannot clarify or reject a real release decision, the framework should be killed.\n\n"
        "What common release case breaks this rule? Please do not paste private campaign content. This synthetic capability case reports no reach, preference, conversion, revenue or competitor superiority."
    )
    video = {
        "local_path": VIDEO.relative_to(ROOT).as_posix(),
        "sha256": sha256_file(VIDEO),
        "bytes": VIDEO.stat().st_size,
        "postiz_upload_id": "{{POSTIZ_LINKEDIN_MEDIA_ID_1}}",
        "postiz_https_path": "{{POSTIZ_LINKEDIN_HTTPS_URL_1}}",
    }
    routes = [
        {
            "id": linkedin_source["id"], "provider": "linkedin", "role": "PRIMARY",
            "connector_mode": "postiz_local_dry_run_no_network", "caption": linkedin_caption,
            "first_comment": linkedin_source["first_comment"], "conversation_tree": linkedin_source["conversation_tree"],
            "conversion_path": linkedin_source["conversion_path"], "experiment": linkedin_source["experiment"],
            "media_upload_manifest": [video],
            "postiz_request": {
                "method": "POST", "endpoint": "/public/v1/posts",
                "payload": {"type": "schedule", "date": "{{HUMAN_APPROVED_SCHEDULED_AT_UTC}}", "shortLink": False,
                    "tags": ["prooflaunch", "40-asset-interview", "human-approved"],
                    "posts": [{"integration": {"id": "{{POSTIZ_LINKEDIN_INTEGRATION_ID}}"},
                        "value": [{"content": linkedin_caption, "image": [{"id": video["postiz_upload_id"], "path": video["postiz_https_path"]}]}],
                        "settings": {"__type": "linkedin", "post_as_images_carousel": False}}]},
            },
            "release_guard": {"named_owner_required": True, "baseline_required": True, "automatic_publish_enabled": False, "external_request_executed": False},
        },
        {
            "id": reddit_source["id"], "provider": "reddit", "role": "SECONDARY",
            "connector_mode": "manual_community_release_after_rules_and_moderator_fit", "caption": reddit_caption,
            "first_comment": reddit_source["first_comment"], "conversation_tree": reddit_source["conversation_tree"],
            "conversion_path": reddit_source["conversion_path"], "experiment": reddit_source["experiment"],
            "media_upload_manifest": [], "postiz_request": None,
            "release_guard": {"builder_disclosure_first": True, "community_rules_check_required": True, "moderator_fit_required": True, "named_owner_required": True, "automatic_publish_enabled": False, "external_request_executed": False},
        },
    ]
    payload = seal({
        "schema": "ProofLaunch40AssetInterviewExecutionBundleV1", "campaign_id": "40-asset-interview-organic-v1",
        "business_model": "b2b", "budget": 0, "routes": routes,
        "execution_graph": [
            {"when": "T-24H", "stage": "CLAIMS + RIGHTS", "decision": "PASS / REPAIR / KILL"},
            {"when": "T-2H", "stage": "LINKEDIN POSTIZ DRY RUN", "decision": "APPROVE / HOLD"},
            {"when": "T+0", "stage": "LINKEDIN PRIMARY", "decision": "RELEASE / HOLD"},
            {"when": "T+24H", "stage": "QUALIFIED REPLY READ", "decision": "CONTINUE / KILL"},
            {"when": "T+48H", "stage": "REDDIT RULES + MOD FIT", "decision": "MANUAL RELEASE / HOLD"},
            {"when": "T+7D", "stage": "DECISION-CHANGE REVIEW", "decision": "SCALE / ITERATE / RETIRE"},
        ],
        "external_request_count": 0, "automatic_publish_enabled": False, "market_effect_observed": False,
        "truth_boundary": "This B2B bundle is executable locally but has not sent, scheduled or published anything. No preference, organic breakout, conversion, revenue or named-product win is claimed.",
    })
    if routes[0]["postiz_request"]["endpoint"] != "/public/v1/posts" or routes[1]["postiz_request"] is not None:
        raise SystemExit("B2B connector boundary drifted")
    if any(row["release_guard"]["automatic_publish_enabled"] or row["release_guard"]["external_request_executed"] for row in routes):
        raise SystemExit("B2B execution bundle overstates an external action")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUTPUT / "execution-bundle.json", json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    route_html = "".join(
        f'<article><header><span>{row["role"]} / {row["provider"].upper()}</span><b>{row["connector_mode"]}</b></header><h2>{row["caption"].splitlines()[0]}</h2><pre>{row["caption"]}</pre><h3>FIRST COMMENT</h3><p>{row["first_comment"]}</p><h3>REPLY TREE</h3>' + "".join(f'<details><summary>{item["trigger"]}</summary><p>{item["reply"]}</p></details>' for item in row["conversation_tree"]) + f'<h3>KILL RULE</h3><p>{row["experiment"]["kill_rule"]}</p></article>'
        for row in routes
    )
    graph_html = "".join(f'<div><small>{row["when"]}</small><h3>{row["stage"]}</h3><b>{row["decision"]}</b></div>' for row in payload["execution_graph"])
    html = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>40-Asset Interview Execution Room</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#eee9df;color:#080907;font:16px/1.5 Inter,system-ui}}main{{width:min(1400px,calc(100% - 36px));margin:auto}}.hero{{padding:70px 0;border-bottom:3px solid}}h1{{font-size:clamp(64px,10vw,145px);line-height:.78;letter-spacing:-.08em;margin:24px 0}}.hero p{{font-size:22px;max-width:850px}}.routes{{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:36px 0}}article{{border:2px solid;background:#fffdf8;padding:24px}}article header{{background:#080907;color:white;margin:-24px -24px 24px;padding:16px;display:flex;justify-content:space-between;gap:20px}}h2{{font-size:42px;line-height:.95}}h3,small{{font:900 11px ui-monospace,monospace;letter-spacing:.1em}}pre{{white-space:pre-wrap;font:14px/1.55 ui-monospace,monospace}}details{{border-top:1px solid;padding:10px 0}}.graph{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding-bottom:70px}}.graph div{{border:2px solid;padding:18px;min-height:140px}}.boundary{{background:#d8ff35;border:2px solid;padding:18px;font-weight:900}}@media(max-width:850px){{.routes,.graph{{grid-template-columns:1fr}}}}</style></head><body><main><section class="hero"><small>PROOFLAUNCH / B2B EXECUTION / ZERO PAID MEDIA</small><h1>MAKE THE<br>AGENT REFUSE.</h1><p>One LinkedIn operator test, one community-native Reddit falsification request, one existing 4K challenger and no automatic publication.</p><p class="boundary">{payload["truth_boundary"]}</p></section><section class="routes">{route_html}</section><section class="graph">{graph_html}</section></main></body></html>'''
    atomic_write_text(OUTPUT / "index.html", html)
    receipt = seal({
        "schema": "ProofLaunch40AssetInterviewExecutionRoomReceiptV1", "artifact_id": "40-asset-interview-execution-room-v1",
        "route_count": 2, "postiz_request_count": 1, "manual_community_route_count": 1, "finished_media_count": 1,
        "external_request_count": 0, "automatic_publish_enabled": False, "market_effect_observed": False,
        "bindings": [{"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path), "bytes": path.stat().st_size} for path in (CASE_SYSTEM, VIDEO, OUTPUT / "execution-bundle.json", OUTPUT / "index.html")],
        "truth_boundary": payload["truth_boundary"],
    })
    atomic_write_text(OUTPUT / "receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "route_count": 2, "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
