#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
import secrets
import zipfile
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
NEW = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-last-mile-release-copy-v1/release-copy.json"
OLD_COPY = ROOT / "artifacts/gtm-last-mile-pk-v1/text-super-challenger-v2/channel-copy.json"
OLD_PLATFORMS = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v17/b2b-delete-one-line-receipt.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-last-mile-copy-ab-v1"
SURFACES = ("linkedin", "tiktok", "instagram", "null_result_receipt")
AXES = (
    "first-line stopping power",
    "audience self-selection",
    "platform-native craft",
    "single-action clarity",
    "evidence-boundary precision",
    "qualified-response potential",
    "direct publishability",
)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def seal(value: dict) -> dict:
    payload = dict(value)
    payload["content_sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
    return payload


def pair_hash(task: dict[str, Any]) -> str:
    unsigned = dict(task)
    unsigned.pop("pair_sha256", None)
    return hashlib.sha256(canonical(unsigned)).hexdigest()


def old_assets() -> dict[str, dict]:
    copy = json.loads(OLD_COPY.read_text(encoding="utf-8"))
    platforms = json.loads(OLD_PLATFORMS.read_text(encoding="utf-8"))
    surfaces = {row["surface_id"]: row for row in platforms["accepted_candidates"]}
    return {
        "linkedin": {
            "surface": "linkedin organic carousel",
            "caption": copy["primary"]["body"] + "\n\n" + copy["primary"]["cta"],
        },
        "tiktok": {
            "surface": "TikTok private-upload dry run",
            "caption": surfaces["tiktok"]["hook"] + "\n\n" + surfaces["tiktok"]["cta"] + "\n\nAI-generated campaign demonstration. Market response not observed.",
        },
        "instagram": {
            "surface": "Instagram organic carousel",
            "caption": surfaces["instagram"]["hook"] + "\n\n" + surfaces["instagram"]["cta"] + "\n\nNot false forever. Unsupported today. Market response not observed.",
        },
        "null_result_receipt": {
            "surface": "LinkedIn organic text",
            "caption": (
                "The campaign verdict is allowed to be: stop.\n\n"
                "We will publish no success recap from impressions, likes, or self-scores. The only eligible signal is a named operator confirming that the witness check changed a real release decision.\n\n"
                "Until that exists: preference missing; breakout missing; conversion missing; revenue missing.\n\n"
                "Reuse the decision format, not our conclusion."
            ),
        },
    }


def candidate_html(assets: dict[str, dict]) -> str:
    cards = []
    for surface_id in SURFACES:
        row = assets[surface_id]
        cards.append(
            f'<section><small>{html.escape(row["surface"])}</small>'
            f'<h3>{html.escape(surface_id.replace("_", " "))}</h3>'
            f'<div class="copy">{html.escape(row["caption"]).replace(chr(10), "<br>")}</div></section>'
        )
    return "".join(cards)


def review_html(task: dict[str, Any]) -> str:
    encoded = json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace("<", "\\u003c")
    axes = "".join(
        f'<fieldset><legend>{html.escape(axis)}</legend>'
        f'<label><input required type="radio" name="axis_{index}" value="left">LEFT</label>'
        f'<label><input required type="radio" name="axis_{index}" value="right">RIGHT</label>'
        f'<label><input required type="radio" name="axis_{index}" value="tie">TIE</label></fieldset>'
        for index, axis in enumerate(AXES)
    )
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Source-hidden release copy review</title><style>
:root{{--paper:#f5f0e6;--ink:#0c0d0b;--red:#ff4d38;--acid:#dfff2c}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 Inter,system-ui,sans-serif}}main{{width:min(1500px,calc(100% - 32px));margin:auto}}header{{padding:50px 0 30px;border-bottom:3px solid var(--ink)}}h1{{font-size:clamp(50px,8vw,110px);line-height:.84;letter-spacing:-.06em;margin:18px 0}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:24px 0}}article{{background:#fff;border:2px solid var(--ink);padding:20px}}article>h2{{font-size:58px;margin:0 0 20px}}article:nth-child(2)>h2{{color:var(--red)}}section{{border-top:1px solid #888;padding:18px 0}}small{{font:800 11px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.08em}}h3{{margin:6px 0 12px}}.copy{{font-size:17px}}.boundary{{border-left:9px solid var(--red);background:white;padding:12px 16px}}form{{padding:20px 0 70px}}fieldset{{border:2px solid var(--ink);margin:10px 0;padding:16px}}label{{display:inline-block;margin:6px 18px 6px 0}}input[type=text],textarea{{width:100%;border:2px solid var(--ink);padding:11px;background:#fff}}textarea{{min-height:110px}}button{{background:var(--acid);border:3px solid var(--ink);padding:16px 24px;font-weight:950}}@media(max-width:860px){{.pair{{grid-template-columns:1fr}}}}
</style></head><body><main><header><small>PROOFLAUNCH · SOURCE-HIDDEN LAST-MILE COPY GATE</small><h1>WHICH VERSION<br>EARNS RELEASE?</h1><p>Judge the four-surface campaign as one GTM system. Both sides use the same frozen idea and proof boundary. Identity and chronology are hidden.</p><p class="boundary">Do not reward length, confidence or a promise of virality. Reward audience fit, platform behavior, one usable action and release-ready craft. Nothing here publishes, promotes or records market effect.</p><p><code>{task['review_task_id']} · sha256:{task['pair_sha256']}</code></p></header><div class="pair"><article><h2>LEFT</h2>{candidate_html(task['left_assets'])}</article><article><h2>RIGHT</h2>{candidate_html(task['right_assets'])}</article></div><form id="review"><label>Stable reviewer pseudonym<input required id="pseudonym" type="text" minlength="3"></label><fieldset><legend>Stronger complete release system</legend><label><input required type="radio" name="choice" value="left">LEFT</label><label><input required type="radio" name="choice" value="right">RIGHT</label><label><input required type="radio" name="choice" value="abstain">ABSTAIN</label></fieldset>{axes}<fieldset><legend>Directly publishable after ordinary owner/fact/legal review</legend><label><input required type="radio" name="publishability" value="left_only">LEFT only</label><label><input required type="radio" name="publishability" value="right_only">RIGHT only</label><label><input required type="radio" name="publishability" value="both">BOTH</label><label><input required type="radio" name="publishability" value="neither">NEITHER</label></fieldset><fieldset><legend>Major rework required</legend><label><input required type="radio" name="rework" value="none">NONE</label><label><input required type="radio" name="rework" value="left">LEFT</label><label><input required type="radio" name="rework" value="right">RIGHT</label><label><input required type="radio" name="rework" value="both">BOTH</label></fieldset><fieldset><legend>Blocking defect</legend><label><input required type="radio" name="defect" value="none">NONE</label><label><input required type="radio" name="defect" value="left">LEFT</label><label><input required type="radio" name="defect" value="right">RIGHT</label><label><input required type="radio" name="defect" value="both">BOTH</label></fieldset><label>Located defect/rework reason<textarea id="defect_reason"></textarea></label><label>Why does the stronger system earn attention and one qualified next action?<textarea required id="rationale" minlength="48"></textarea></label><label><input required id="attest" type="checkbox"> I reviewed independently without the private mapping, another review or a model judge.</label><p><button type="submit">DOWNLOAD SEALED REVIEW JSON</button></p><p id="status">Nothing transmitted.</p></form><script id="task" type="application/json">{encoded}</script><script>
const task=JSON.parse(document.getElementById("task").textContent),pick=n=>document.querySelector(`input[name="${{n}}"]:checked`)?.value,stable=v=>Array.isArray(v)?`[${{v.map(stable).join(",")}}]`:v&&typeof v==="object"?`{{${{Object.keys(v).sort().map(k=>`${{JSON.stringify(k)}}:${{stable(v[k])}}`).join(",")}}}}`:JSON.stringify(v),hex=async v=>Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(stable(v)))),b=>b.toString(16).padStart(2,"0")).join("");document.getElementById("review").onsubmit=async e=>{{e.preventDefault();try{{const pseudonym=document.getElementById("pseudonym").value.trim(),choice=pick("choice"),publishability=pick("publishability"),rework=pick("rework"),defect=pick("defect"),defectReason=document.getElementById("defect_reason").value.trim(),rationale=document.getElementById("rationale").value.trim(),axisWinners=Object.fromEntries(task.quality_axes.map((axis,index)=>[axis,pick(`axis_${{index}}`)]));if(pseudonym.length<3||!choice||!publishability||!rework||!defect||Object.values(axisWinners).some(v=>!v)||rationale.length<48||!document.getElementById("attest").checked||((defect!=="none"||rework!=="none")&&defectReason.length<16))throw Error("Complete every field and locate any defect or major rework.");const review={{schema:"ProofLaunchLastMileCopyABHumanReviewV1",comparison_id:task.comparison_id,review_task_id:task.review_task_id,reviewer_slot:task.reviewer_slot,pair_sha256:task.pair_sha256,reviewer_pseudonym:pseudonym,choice,axis_winners:axisWinners,publishability,major_rework_side:rework,blocking_defect_side:defect,blocking_defect_reason:defectReason,rationale,human_attestation:"independent_source_hidden_no_model_judge",reviewed_at:new Date().toISOString()}};review.review_content_sha256=await hex(review);const blob=new Blob([JSON.stringify(review,null,2)+"\n"],{{type:"application/json"}}),a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`last-mile-copy-review-${{task.reviewer_slot}}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);document.getElementById("status").textContent=`Exported locally · ${{review.review_content_sha256}} · no promotion occurred.`}}catch(error){{document.getElementById("status").textContent="Blocked: "+error.message}}}};
</script></main></body></html>'''


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {OUTPUT}")
    for path in (NEW, OLD_COPY, OLD_PLATFORMS):
        if not path.is_file():
            raise SystemExit(f"missing A/B dependency: {path}")
    new_payload = json.loads(NEW.read_text(encoding="utf-8"))
    candidates = {
        "candidate_a": old_assets(),
        "candidate_b": {
            key: {"surface": row["surface"].replace("_", " "), "caption": row["caption"]}
            for key, row in new_payload["platforms"].items()
        },
    }
    public = OUTPUT / "public"
    private = OUTPUT / "private"
    kits = OUTPUT / "offline-kits"
    public.mkdir(parents=True, mode=0o700)
    private.mkdir(parents=True, mode=0o700)
    kits.mkdir(parents=True, mode=0o700)
    comparison_id = f"last-mile-copy-ab-{secrets.token_hex(12)}"
    slots = list(range(1, 6))
    secrets.SystemRandom().shuffle(slots)
    candidate_b_left = set(slots[:3])
    tasks, mappings, kit_rows = [], {}, []
    for slot in range(1, 6):
        left, right = ("candidate_b", "candidate_a") if slot in candidate_b_left else ("candidate_a", "candidate_b")
        task = {
            "comparison_id": comparison_id,
            "review_task_id": f"last-mile-copy-{secrets.token_hex(10)}-reviewer-{slot}",
            "reviewer_slot": slot,
            "quality_axes": list(AXES),
            "left_assets": candidates[left],
            "right_assets": candidates[right],
        }
        task["pair_sha256"] = pair_hash(task)
        tasks.append(task)
        mappings[task["review_task_id"]] = {"left": left, "right": right}
        page = review_html(task)
        atomic_write_text(public / f"reviewer-{slot:02d}.html", page)
        zip_path = kits / f"reviewer-{slot:02d}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, body in (
                ("review.html", page.encode()),
                ("task.json", json.dumps(task, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"),
            ):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, body)
        kit_rows.append({"reviewer_slot": slot, "sha256": sha256_file(zip_path), "bytes": zip_path.stat().st_size})
    public_packet = seal({
        "schema": "ProofLaunchLastMileCopyABPublicPacketV1",
        "comparison_id": comparison_id,
        "reviewer_count": 5,
        "expected_review_count": 5,
        "submitted_review_count": 0,
        "review_tasks": tasks,
        "source_roles_exposed": False,
        "model_judge_can_promote": False,
        "automatic_promotion_enabled": False,
        "market_effect_observed": False,
        "truth_boundary": "This packet enables source-hidden last-mile copy review only. Empty tasks prove no preference, publication, named-product victory, 4A quality or market effect.",
    })
    public_path = public / "packet.json"
    atomic_write_text(public_path, json.dumps(public_packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    private_packet = seal({
        "schema": "ProofLaunchLastMileCopyABPrivateMappingV1",
        "public_packet_sha256": sha256_file(public_path),
        "candidate_a_source_sha256": sha256_file(OLD_COPY),
        "candidate_a_platform_source_sha256": sha256_file(OLD_PLATFORMS),
        "candidate_b_source_sha256": sha256_file(NEW),
        "task_side_mapping": mappings,
        "candidate_b_left_count": len(candidate_b_left),
        "reviewer_kits": kit_rows,
        "automatic_promotion_enabled": False,
    })
    private_path = private / "mapping.json"
    atomic_write_text(private_path, json.dumps(private_packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    private_path.chmod(0o600)
    receipt = seal({
        "schema": "ProofLaunchLastMileCopyABPacketReceiptV1",
        "comparison_id": comparison_id,
        "public_packet_sha256": sha256_file(public_path),
        "private_mapping_sha256": sha256_file(private_path),
        "reviewer_kit_count": 5,
        "submitted_review_count": 0,
        "automatic_promotion_enabled": False,
        "truth_boundary": public_packet["truth_boundary"],
    })
    atomic_write_text(OUTPUT / "packet-receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "reviewer_kit_count": 5, "submitted_review_count": 0, "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
