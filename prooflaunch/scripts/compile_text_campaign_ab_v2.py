from __future__ import annotations

import hashlib
import html
import json
import secrets
import zipfile
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.visual_release_gate import seal


ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "evidence/v10/gtm-text-named-pk-super-challenger-v1.json"
V2 = ROOT / "evidence/v10/gtm-text-named-pk-super-challenger-v2.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/text-campaign-ab-v2"
ASSET_IDS = ("linkedin", "partner_community", "landing_hero", "lifecycle_email")
AXES = (
    "three-second conflict comprehension",
    "organizing-idea ownability",
    "platform-native psychological job",
    "senior copy craft and rhythm",
    "evidence-boundary precision",
    "qualified-response potential",
    "direct publishability",
)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def pair_hash(task: dict[str, Any]) -> str:
    unsigned = dict(task)
    unsigned.pop("pair_sha256", None)
    return hashlib.sha256(canonical(unsigned)).hexdigest()


def candidate_view(asset: dict[str, Any]) -> str:
    rows = []
    for key, value in asset.items():
        if key == "release_state":
            continue
        rendered = "<br>".join(html.escape(str(line)) for line in value) if isinstance(value, list) else html.escape(str(value)).replace("\n", "<br>")
        rows.append(f'<div class="field"><small>{html.escape(key.replace("_", " "))}</small><p>{rendered}</p></div>')
    return "".join(rows)


def review_html(task: dict[str, Any]) -> str:
    encoded = json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace("<", "\\u003c")
    sections = []
    for asset_id in ASSET_IDS:
        sections.append(
            f'<section><div class="section-title"><span>{html.escape(asset_id.replace("_", " "))}</span>'
            f'<strong>Judge the job, not copy length.</strong></div><div class="pair">'
            f'<article><h2>LEFT</h2>{candidate_view(task["left_assets"][asset_id])}</article>'
            f'<article><h2>RIGHT</h2>{candidate_view(task["right_assets"][asset_id])}</article></div></section>'
        )
    axis_rows = "".join(
        f'<fieldset><legend>{html.escape(axis)}</legend><label><input required type="radio" name="axis_{index}" value="left"> LEFT</label><label><input required type="radio" name="axis_{index}" value="right"> RIGHT</label><label><input required type="radio" name="axis_{index}" value="tie"> TIE</label></fieldset>'
        for index, axis in enumerate(AXES)
    )
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Source-hidden campaign copy A/B</title><style>
:root{{--paper:#f3efe5;--ink:#090a08;--red:#ff4e38;--acid:#dfff2d;--line:#77756d}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.45 Inter,system-ui,sans-serif}}main{{width:min(1500px,calc(100% - 36px));margin:auto}}header{{padding:52px 0 34px;border-bottom:3px solid var(--ink)}}header h1{{font-size:clamp(54px,8vw,120px);line-height:.82;letter-spacing:-.065em;margin:24px 0}}header p{{max-width:940px;font-size:20px}}code,small,.section-title span{{font:800 12px/1.2 ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase}}.boundary{{border-left:10px solid var(--red);padding:14px 18px;background:#fff}}section{{padding:40px 0;border-bottom:2px solid var(--ink)}}.section-title{{display:flex;justify-content:space-between;margin-bottom:14px}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}article{{background:#fff;border:2px solid var(--ink);padding:24px}}article h2{{font-size:54px;line-height:.8;margin:0 0 24px}}article:nth-child(2) h2{{color:var(--red)}}.field{{border-top:1px solid var(--line);padding:15px 0}}.field:first-of-type{{border-top:0}}.field small{{color:#5a5b55}}.field p{{font-size:18px;margin:8px 0 0}}form{{padding:44px 0 80px}}fieldset{{border:2px solid var(--ink);margin:10px 0;padding:18px}}legend{{font-weight:900}}label{{display:inline-block;margin:8px 18px 8px 0}}input[type=text],textarea{{width:100%;border:2px solid var(--ink);padding:12px;background:white}}textarea{{min-height:110px}}button{{background:var(--acid);border:3px solid var(--ink);padding:18px 26px;font-weight:950;font-size:18px}}@media(max-width:800px){{.pair{{grid-template-columns:1fr}}.section-title{{display:block}}}}
</style></head><body><main><header><code>PROOFLAUNCH / SOURCE-HIDDEN COPY EVOLUTION</code><h1>WHICH ONE<br>EARNS THE PAGE?</h1><p>Both candidates answer the same frozen brief through LinkedIn, a partner community, the landing page and one requested email. Judge the complete system—not the quantity of copy.</p><p><strong>Decision:</strong> Which campaign is more ownable, platform-native and immediately usable while preserving the exact evidence boundary?</p><p class="boundary">LEFT/RIGHT identity is hidden and counterbalanced. Do not consult another reviewer, infer market performance, or use a model judge. No response publishes, promotes, sends or spends.</p><p><code>{task['review_task_id']} · sha256:{task['pair_sha256']}</code></p></header>{''.join(sections)}<form id="review"><h2>Independent decision</h2><label>Stable reviewer pseudonym<input required id="pseudonym" type="text" minlength="3"></label><fieldset><legend>Stronger complete campaign</legend><label><input required type="radio" name="choice" value="left"> LEFT</label><label><input required type="radio" name="choice" value="right"> RIGHT</label><label><input required type="radio" name="choice" value="abstain"> ABSTAIN</label></fieldset>{axis_rows}<fieldset><legend>Directly publishable after ordinary fact/legal review</legend><label><input required type="radio" name="publishability" value="left_only"> LEFT only</label><label><input required type="radio" name="publishability" value="right_only"> RIGHT only</label><label><input required type="radio" name="publishability" value="both"> BOTH</label><label><input required type="radio" name="publishability" value="neither"> NEITHER</label></fieldset><fieldset><legend>Major rework required</legend><label><input required type="radio" name="rework" value="none"> NONE</label><label><input required type="radio" name="rework" value="left"> LEFT</label><label><input required type="radio" name="rework" value="right"> RIGHT</label><label><input required type="radio" name="rework" value="both"> BOTH</label></fieldset><fieldset><legend>Blocking defect</legend><label><input required type="radio" name="defect" value="none"> NONE</label><label><input required type="radio" name="defect" value="left"> LEFT</label><label><input required type="radio" name="defect" value="right"> RIGHT</label><label><input required type="radio" name="defect" value="both"> BOTH</label></fieldset><label>Located defect or rework reason<textarea id="defect_reason"></textarea></label><label>Why does the stronger system earn attention and a qualified next action?<textarea required id="rationale" minlength="48"></textarea></label><label><input required id="attest" type="checkbox"> I reviewed independently without the private mapping, another review, or a model judge.</label><p><button type="submit">DOWNLOAD SEALED REVIEW JSON</button></p><p id="status">Nothing transmitted.</p></form><script id="task" type="application/json">{encoded}</script><script>
const task=JSON.parse(document.getElementById("task").textContent),pick=n=>document.querySelector(`input[name="${{n}}"]:checked`)?.value,stable=v=>Array.isArray(v)?`[${{v.map(stable).join(",")}}]`:v&&typeof v==="object"?`{{${{Object.keys(v).sort().map(k=>`${{JSON.stringify(k)}}:${{stable(v[k])}}`).join(",")}}}}`:JSON.stringify(v),hex=async v=>Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(stable(v)))),b=>b.toString(16).padStart(2,"0")).join("");document.getElementById("review").onsubmit=async e=>{{e.preventDefault();try{{const pseudonym=document.getElementById("pseudonym").value.trim(),choice=pick("choice"),publishability=pick("publishability"),majorRework=pick("rework"),defect=pick("defect"),defectReason=document.getElementById("defect_reason").value.trim(),rationale=document.getElementById("rationale").value.trim(),axisWinners=Object.fromEntries(task.quality_axes.map((axis,index)=>[axis,pick(`axis_${{index}}`)]));if(pseudonym.length<3||!choice||!publishability||!majorRework||!defect||Object.values(axisWinners).some(v=>!v)||rationale.length<48||!document.getElementById("attest").checked||((defect!=="none"||majorRework!=="none")&&defectReason.length<16))throw Error("Complete every field and locate any defect or major rework.");const review={{schema:"ProofLaunchTextCampaignABHumanReviewV1",comparison_id:task.comparison_id,review_task_id:task.review_task_id,reviewer_slot:task.reviewer_slot,pair_sha256:task.pair_sha256,reviewer_pseudonym:pseudonym,choice,axis_winners:axisWinners,publishability,major_rework_side:majorRework,blocking_defect_side:defect,blocking_defect_reason:defectReason,rationale,human_attestation:"independent_source_hidden_no_model_judge",reviewed_at:new Date().toISOString()}};review.review_content_sha256=await hex(review);const blob=new Blob([JSON.stringify(review,null,2)+"\n"],{{type:"application/json"}}),a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`text-campaign-review-${{task.reviewer_slot}}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);document.getElementById("status").textContent=`Exported locally · ${{review.review_content_sha256}} · no promotion occurred.`}}catch(error){{document.getElementById("status").textContent="Blocked: "+error.message}}}};
</script></main></body></html>'''


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {OUTPUT}")
    candidates = {
        "v1": json.loads(V1.read_text(encoding="utf-8"))["candidate"],
        "v2": json.loads(V2.read_text(encoding="utf-8"))["candidate"],
    }
    public = OUTPUT / "public"
    private = OUTPUT / "private"
    kits = OUTPUT / "offline-kits"
    public.mkdir(parents=True, mode=0o700)
    private.mkdir(parents=True, mode=0o700)
    kits.mkdir(parents=True, mode=0o700)
    comparison_id = f"text-campaign-ab-{secrets.token_hex(12)}"
    shuffled = list(range(1, 6))
    secrets.SystemRandom().shuffle(shuffled)
    v2_left_slots = set(shuffled[:3])
    tasks, mappings, kit_rows = [], {}, []
    for slot in range(1, 6):
        left, right = ("v2", "v1") if slot in v2_left_slots else ("v1", "v2")
        task = {
            "comparison_id": comparison_id,
            "review_task_id": f"text-ab-{secrets.token_hex(10)}-reviewer-{slot}",
            "reviewer_slot": slot,
            "quality_axes": list(AXES),
            "left_assets": candidates[left]["assets"],
            "right_assets": candidates[right]["assets"],
        }
        task["pair_sha256"] = pair_hash(task)
        tasks.append(task)
        mappings[task["review_task_id"]] = {"left": left, "right": right}
        page = review_html(task)
        atomic_write_text(public / f"reviewer-{slot:02d}.html", page)
        zip_path = kits / f"reviewer-{slot:02d}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, body in (("review.html", page.encode()), ("task.json", json.dumps(task, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n")):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, body)
        kit_rows.append({"reviewer_slot": slot, "sha256": sha256_file(zip_path), "bytes": zip_path.stat().st_size})
    public_packet = seal({
        "schema": "ProofLaunchTextCampaignABPublicPacketV1",
        "comparison_id": comparison_id,
        "reviewer_count": 5,
        "expected_review_count": 5,
        "submitted_review_count": 0,
        "review_tasks": tasks,
        "source_roles_exposed": False,
        "model_judge_can_promote": False,
        "automatic_promotion_enabled": False,
        "market_effect_observed": False,
        "truth_boundary": "This packet enables source-hidden V1/V2 craft review only. Empty tasks prove no preference, publication, named-product victory or market effect.",
    })
    public_path = public / "packet.json"
    atomic_write_text(public_path, json.dumps(public_packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    private_packet = seal({
        "schema": "ProofLaunchTextCampaignABPrivateMappingV1",
        "public_packet_sha256": sha256_file(public_path),
        "v1_portfolio_sha256": sha256_file(V1),
        "v2_portfolio_sha256": sha256_file(V2),
        "task_side_mapping": mappings,
        "v2_left_count": len(v2_left_slots),
        "reviewer_kits": kit_rows,
        "automatic_promotion_enabled": False,
    })
    private_path = private / "mapping.json"
    atomic_write_text(private_path, json.dumps(private_packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    private_path.chmod(0o600)
    receipt = seal({
        "schema": "ProofLaunchTextCampaignABPacketReceiptV1",
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
