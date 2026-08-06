#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text, sha256_file  # noqa: E402
from prooflaunch_remix.gtm_named_product_pk import NamedProductPKReviewService  # noqa: E402


OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-blind-jury-console-v1"
REVIEW_ROOT = ROOT / "evidence/v10/named-product-pk-reviews-v1"
LANES = (
    {
        "id": "image",
        "label": "IMAGE / FEED GLANCE",
        "product": "Qwen-Image",
        "root": "named-product-pk-qwen-image-v2",
        "accent": "acid",
    },
    {
        "id": "image_openai",
        "label": "IMAGE / FEED GLANCE",
        "product": "OpenAI Image",
        "root": "named-product-pk-openai-image-v1",
        "accent": "acid",
    },
    {
        "id": "audio",
        "label": "AUDIO / HUMAN DELIVERY",
        "product": "Qwen3-TTS",
        "root": "named-product-pk-qwen3-tts-v1",
        "accent": "orange",
    },
    {
        "id": "memory",
        "label": "MEMORY / CROSS-DEVICE TRUTH",
        "product": "Mem0",
        "root": "named-product-pk-mem0-v2",
        "accent": "blue",
    },
    {
        "id": "memory_letta",
        "label": "MEMORY / STATEFUL AGENT",
        "product": "Letta",
        "root": "named-product-pk-letta-v1",
        "accent": "blue",
    },
    {
        "id": "memory_memos",
        "label": "MEMORY / EXPLICIT SUPERSESSION",
        "product": "MemOS",
        "root": "named-product-pk-memos-v2",
        "accent": "blue",
    },
    {
        "id": "scheduling_postiz",
        "label": "CONTENT SCHEDULING / HUMAN RELEASE",
        "product": "Postiz",
        "root": "named-product-pk-postiz-v1",
        "accent": "orange",
    },
)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def status_for(lane: dict[str, str]) -> dict[str, Any]:
    packet_root = ROOT / "artifacts/gtm-last-mile-pk-v1" / lane["root"] / "review-packet"
    receipt_path = packet_root / "packet-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    store = REVIEW_ROOT / receipt["capture_slot_id"]
    status = NamedProductPKReviewService(packet_root=packet_root, store_root=store).status()
    public = json.loads((packet_root / "public/packet.json").read_text(encoding="utf-8"))
    return {
        **lane,
        "category_id": receipt["category_id"],
        "comparison_id": receipt["comparison_id"],
        "capture_slot_id": receipt["capture_slot_id"],
        "expected_review_count": status["expected_review_count"],
        "submitted_review_count": status["submitted_review_count"],
        "remaining_review_count": status["remaining_review_count"],
        "review_complete": status["review_complete"],
        "candidate_win": status["candidate_won_same_brief_last_mile_pk"],
        "packet_receipt_path": receipt_path.relative_to(ROOT).as_posix(),
        "packet_receipt_sha256": sha256_file(receipt_path),
        "public_packet_sha256": public["content_sha256"],
        "reviewer_pages": [
            f"../{lane['root']}/review-packet/public/reviewer-{slot:02d}.html"
            for slot in range(1, 6)
        ],
        "import_command": (
            ".venv/bin/python scripts/import_named_product_jury_review_v1.py "
            f"--lane {lane['id']} --review artifacts/gtm-last-mile-pk-v1/"
            f"named-product-blind-jury-console-v1/inbox/{lane['id']}/REVIEW.json"
        ),
    }


def lane_html(lane: dict[str, Any]) -> str:
    slots = "".join(
        f'<a class="slot" href="{html.escape(page)}"><span>R{slot}</span><b>OPEN BRIEF</b></a>'
        for slot, page in enumerate(lane["reviewer_pages"], 1)
    )
    command = html.escape(lane["import_command"])
    return f'''<article class="lane {lane['accent']}">
      <div class="lane-top"><p>{html.escape(lane['label'])}</p><span>{lane['submitted_review_count']}/5 RECEIVED</span></div>
      <h2>ProofLaunch <i>vs.</i> {html.escape(lane['product'])}</h2>
      <p class="question">One frozen brief. Identity hidden. Five independent humans. No model judge can promote the result.</p>
      <div class="slots">{slots}</div>
      <div class="command"><small>IMPORT AN EXPORTED REVIEW</small><code>{command}</code><button data-copy="{command}">COPY</button></div>
      <div class="lane-state"><b>{'DECIDED' if lane['review_complete'] else 'NOT DECIDED'}</b><span>{lane['remaining_review_count']} independent review{'s' if lane['remaining_review_count'] != 1 else ''} still required</span><em>{'WIN' if lane['candidate_win'] else 'NO WIN RECORDED'}</em></div>
    </article>'''


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for lane in LANES:
        (OUTPUT / "inbox" / lane["id"]).mkdir(parents=True, exist_ok=True)
    lanes = [status_for(lane) for lane in LANES]
    totals = {
        "lane_count": len(lanes),
        "expected_review_count": sum(row["expected_review_count"] for row in lanes),
        "submitted_review_count": sum(row["submitted_review_count"] for row in lanes),
        "completed_comparison_count": sum(row["review_complete"] for row in lanes),
        "candidate_win_count": sum(row["candidate_win"] for row in lanes),
    }
    status = {
        "schema": "ProofLaunchNamedProductBlindJuryConsoleStatusV1",
        **totals,
        "lanes": lanes,
        "automatic_publish_enabled": False,
        "automatic_send_enabled": False,
        "automatic_spend_enabled": False,
        "truth_boundary": (
            "The console exposes seven authorized same-task comparisons and their real immutable review state. "
            "An open packet is not a vote. Fewer than five distinct valid reviews cannot decide a row. "
            "A row result does not prove 4A quality, virality, conversion, revenue or category-wide superiority."
        ),
    }
    status["content_sha256"] = hashlib.sha256(canonical(status)).hexdigest()
    atomic_write_text(OUTPUT / "status.json", json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    css = '''
:root{--ink:#11110f;--paper:#f5f1e8;--acid:#d8ff37;--orange:#ff7a00;--blue:#6e8cff;--line:#292923;--muted:#6d6b62}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,sans-serif}nav{position:sticky;top:0;z-index:3;background:rgba(245,241,232,.94);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}.wrap{width:min(1240px,calc(100% - 40px));margin:auto}.nav{height:68px;display:flex;align-items:center;justify-content:space-between}.nav b,.eyebrow,.lane-top,.command small,.lane-state{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.06em}.nav a{color:inherit;text-decoration:none;border-bottom:2px solid}.hero{padding:82px 0 64px;border-bottom:1px solid}.eyebrow{font-size:12px;margin:0 0 25px}.hero h1{font-size:clamp(58px,9vw,132px);line-height:.82;letter-spacing:-.075em;margin:0;max-width:1100px}.hero h1 span{color:var(--orange)}.hero-foot{display:grid;grid-template-columns:1.4fr 1fr;gap:50px;margin-top:42px}.hero-foot p{font-size:20px;line-height:1.45;margin:0}.score{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid}.score div{padding:18px;border-right:1px solid}.score div:last-child{border:0}.score b{font-size:34px;display:block}.score small{color:var(--muted)}main{padding:52px 0 80px}.intro{display:flex;justify-content:space-between;gap:30px;align-items:end;margin-bottom:24px}.intro h2{font-size:34px;letter-spacing:-.04em;margin:0}.intro p{max-width:580px;margin:0;color:var(--muted);line-height:1.5}.lane{border:1px solid var(--line);padding:28px;margin:18px 0;background:#fff;box-shadow:8px 8px 0 var(--line)}.lane.acid{border-top:12px solid var(--acid)}.lane.orange{border-top:12px solid var(--orange)}.lane.blue{border-top:12px solid var(--blue)}.lane-top{display:flex;justify-content:space-between;font-size:12px}.lane-top p{margin:0}.lane-top span{background:var(--ink);color:white;padding:5px 8px}.lane h2{font-size:clamp(34px,5vw,66px);letter-spacing:-.055em;margin:28px 0 12px}.lane h2 i{font-family:Georgia,serif;font-weight:400;color:var(--muted)}.question{max-width:720px;font-size:18px;line-height:1.5}.slots{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:26px 0}.slot{display:flex;justify-content:space-between;align-items:center;border:1px solid;color:inherit;text-decoration:none;padding:16px;transition:.16s}.slot:hover{transform:translateY(-3px);background:var(--acid)}.slot span{font-size:24px;font-weight:900}.slot b{font-size:10px}.command{display:grid;grid-template-columns:170px 1fr auto;align-items:center;background:#181816;color:#f8f5ea;padding:14px;gap:15px}.command code{font-size:11px;overflow:auto;white-space:nowrap;color:#d8ff37}.command button{border:1px solid white;background:transparent;color:white;padding:8px 12px;cursor:pointer}.lane-state{display:flex;gap:18px;align-items:center;margin-top:18px;font-size:11px}.lane-state b{background:#dedbd2;padding:7px}.lane-state span{color:var(--muted);flex:1}.lane-state em{font-style:normal}.protocol{margin-top:50px;border-top:1px solid;padding-top:25px;display:grid;grid-template-columns:1fr 1fr;gap:40px}.protocol h3{font-size:30px;margin:0}.protocol ol{margin:0;padding-left:20px;line-height:1.8}.boundary{margin-top:48px;background:#ffdfd2;border:1px solid;padding:18px;font-family:ui-monospace,monospace;font-size:12px;line-height:1.6}footer{border-top:1px solid;padding:24px 0;color:var(--muted);font-size:12px}@media(max-width:760px){.wrap{width:min(100% - 24px,1240px)}.hero{padding:50px 0}.hero-foot,.protocol{grid-template-columns:1fr}.score{margin-top:6px}.slots{grid-template-columns:1fr}.command{grid-template-columns:1fr}.command code{overflow:visible;white-space:normal;overflow-wrap:anywhere;line-height:1.45}.lane-state{align-items:flex-start;flex-direction:column;gap:8px}.intro{display:block}.intro p{margin-top:12px}.lane{padding:18px;box-shadow:4px 4px 0}.hero h1{font-size:58px}}
'''.strip()
    js = '''document.querySelectorAll("[data-copy]").forEach((button)=>{button.addEventListener("click",async()=>{await navigator.clipboard.writeText(button.dataset.copy);button.textContent="COPIED";setTimeout(()=>button.textContent="COPY",1200)})});'''
    body = "\n".join(lane_html(row) for row in lanes)
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ProofLaunch / Blind Jury Console</title><link rel="stylesheet" href="jury.css"></head><body>
<nav><div class="wrap nav"><b>PROOFLAUNCH / BLIND JURY 01</b><a href="../../gtm-breakout-operator-v1/index.html#pk">BACK TO OPERATOR</a></div></nav>
<header class="hero"><div class="wrap"><p class="eyebrow">LAST-MILE EVIDENCE · SOURCE HIDDEN · HUMAN DECISION</p><h1>STOP GRADING<br>OUR OWN <span>HOMEWORK.</span></h1><div class="hero-foot"><p>Seven comparisons are ready now. Each reviewer sees the same frozen brief and anonymous pair. The system may validate and aggregate; it may not invent a vote.</p><div class="score"><div><b>{totals['submitted_review_count']}/{totals['expected_review_count']}</b><small>real reviews</small></div><div><b>{totals['completed_comparison_count']}/{totals['lane_count']}</b><small>decided rows</small></div><div><b>{totals['candidate_win_count']}</b><small>wins recorded</small></div></div></div></div></header>
<main><div class="wrap"><div class="intro"><h2>The seven fights that actually exist.</h2><p>Send one reviewer link to one independent person. They export a sealed JSON. Copy that file into the matching inbox and run the shown import command.</p></div>{body}
<section class="protocol"><h3>Five people or no verdict.</h3><ol><li>Assign each slot to a different human.</li><li>Do not reveal product identity or private mapping.</li><li>Import the exported hash-bound JSON once.</li><li>At review five, the service computes Wilson confidence, publishability, rework, defects and every declared craft axis.</li><li>No result can publish, send, spend, or switch a model.</li></ol></section>
<div class="boundary">TRUTH BOUNDARY — {html.escape(status['truth_boundary'])}</div></div></main><footer><div class="wrap">Immutable imports · duplicate identity rejected · tamper rejected · private mappings never exposed in this console</div></footer><script src="jury.js"></script></body></html>'''
    atomic_write_text(OUTPUT / "index.html", document)
    atomic_write_text(OUTPUT / "jury.css", css + "\n")
    atomic_write_text(OUTPUT / "jury.js", js + "\n")

    artifacts = []
    for name in ("index.html", "jury.css", "jury.js", "status.json"):
        path = OUTPUT / name
        artifacts.append({
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    receipt = {
        "schema": "ProofLaunchNamedProductBlindJuryConsoleReceiptV1",
        **totals,
        "reviewer_link_count": totals["expected_review_count"],
        "source_hidden": True,
        "distinct_human_reviewers_required_per_lane": 5,
        "private_mapping_exposed": False,
        "model_judge_can_promote": False,
        "artifact_files": artifacts,
        "packet_bindings": [
            {"path": row["packet_receipt_path"], "sha256": row["packet_receipt_sha256"]}
            for row in lanes
        ],
        "truth_boundary": status["truth_boundary"],
    }
    receipt["content_sha256"] = hashlib.sha256(canonical(receipt)).hexdigest()
    atomic_write_text(OUTPUT / "receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({**totals, "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
