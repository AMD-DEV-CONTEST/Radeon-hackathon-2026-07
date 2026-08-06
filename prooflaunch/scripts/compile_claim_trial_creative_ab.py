from __future__ import annotations

import hashlib
import html
import json
import secrets
import zipfile
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_bytes, atomic_write_text, sha256_file
from prooflaunch_remix.gtm_named_product_pk import _artifact_metadata
from prooflaunch_remix.visual_release_gate import seal


ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1/share-card-1080x1350.png"
V2 = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-creative-v2/claim-trial-v2-1080x1350.png"
GATE = ROOT / "evidence/v10/claim-trial-visual-release-gate-v1.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-creative-ab-v1"
BRIEF = ROOT / "evidence/v10/prooflaunch-front-stage-brief-v1.json"
AXES = [
    "two-second stopping power",
    "conflict clarity",
    "copy precision",
    "evidence legibility",
    "distinctive art direction",
    "response-worthiness",
    "direct publishability",
]


def pair_hash(task: dict[str, Any]) -> str:
    unsigned = dict(task)
    unsigned.pop("pair_sha256", None)
    return hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def review_html(task: dict[str, Any]) -> str:
    encoded = json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace("<", "\\u003c")
    axis_rows = "".join(
        f'<fieldset><legend>{html.escape(axis)}</legend>'
        f'<label><input required type="radio" name="axis_{index}" value="left"> LEFT</label>'
        f'<label><input required type="radio" name="axis_{index}" value="right"> RIGHT</label>'
        f'<label><input required type="radio" name="axis_{index}" value="tie"> TIE</label></fieldset>'
        for index, axis in enumerate(task["quality_axes"])
    )
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Claim Trial creative A/B</title><style>
:root{{--ink:#f5f7ff;--muted:#adb5cf;--panel:#11162a;--line:#394362;--accent:#d9ff28}}*{{box-sizing:border-box}}body{{margin:0;background:#080b16;color:var(--ink);font:15px/1.5 system-ui,sans-serif}}main{{max-width:1500px;margin:auto;padding:28px}}header,form,.side{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px}}.sides{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:20px 0}}img{{width:100%;display:block}}fieldset{{margin:14px 0;border:1px solid var(--line)}}textarea,input[type=text]{{width:100%;padding:10px;background:#080b16;color:var(--ink);border:1px solid var(--line)}}textarea{{min-height:100px}}button{{padding:13px 18px;background:var(--accent);color:#080b16;border:0;border-radius:9px;font-weight:900}}.boundary{{border-left:4px solid var(--accent);padding-left:12px;color:var(--muted)}}@media(max-width:800px){{.sides{{grid-template-columns:1fr}}}}
</style></head><body><main><header><strong>ProofLaunch · Claim Trial creative evolution</strong><h1>Source-hidden V1/V2 review</h1><p>{html.escape(task['same_brief_task'])}</p><p><b>Decision:</b> {html.escape(task['effect_question'])}</p><p><code>{task['review_task_id']} · sha256:{task['pair_sha256']}</code></p><p class="boundary">Both assets passed deterministic release gates. Their version identity and side mapping are hidden. Judge actual feed performance potential; do not consult another reviewer or infer market results. Nothing here publishes or promotes an asset.</p></header><div class="sides"><section class="side"><h2>LEFT</h2><img src="assets/{task['left_asset']['alias']}" alt="source-hidden left candidate"></section><section class="side"><h2>RIGHT</h2><img src="assets/{task['right_asset']['alias']}" alt="source-hidden right candidate"></section></div><form id="review"><label>Stable reviewer pseudonym<input required id="pseudonym" type="text" minlength="3"></label><fieldset><legend>Stronger final feed asset</legend><label><input required type="radio" name="choice" value="left"> LEFT</label><label><input required type="radio" name="choice" value="right"> RIGHT</label><label><input required type="radio" name="choice" value="abstain"> ABSTAIN</label></fieldset>{axis_rows}<fieldset><legend>Direct publishability</legend><label><input required type="radio" name="publishability" value="left_only"> LEFT only</label><label><input required type="radio" name="publishability" value="right_only"> RIGHT only</label><label><input required type="radio" name="publishability" value="both"> BOTH</label><label><input required type="radio" name="publishability" value="neither"> NEITHER</label></fieldset><fieldset><legend>Blocking defect</legend><label><input required type="radio" name="defect" value="none"> NONE</label><label><input required type="radio" name="defect" value="left"> LEFT</label><label><input required type="radio" name="defect" value="right"> RIGHT</label><label><input required type="radio" name="defect" value="both"> BOTH</label></fieldset><label>Located defect reason (required unless NONE)<textarea id="defect_reason"></textarea></label><label>Why would the stronger asset stop, hold and earn a qualified response?<textarea required id="rationale" minlength="32"></textarea></label><label><input required id="attest" type="checkbox"> I reviewed independently without the private mapping, another review or a model judge.</label><p><button type="submit">DOWNLOAD REVIEW JSON</button></p><p id="status">Nothing transmitted.</p></form><script id="task" type="application/json">{encoded}</script><script>
const task=JSON.parse(document.getElementById("task").textContent),pick=n=>document.querySelector(`input[name="${{n}}"]:checked`)?.value,stable=v=>Array.isArray(v)?`[${{v.map(stable).join(",")}}]`:v&&typeof v==="object"?`{{${{Object.keys(v).sort().map(k=>`${{JSON.stringify(k)}}:${{stable(v[k])}}`).join(",")}}}}`:JSON.stringify(v),hex=async v=>Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(stable(v)))),b=>b.toString(16).padStart(2,"0")).join("");document.getElementById("review").onsubmit=async e=>{{e.preventDefault();try{{const pseudonym=document.getElementById("pseudonym").value.trim(),choice=pick("choice"),publishability=pick("publishability"),defect=pick("defect"),defectReason=document.getElementById("defect_reason").value.trim(),rationale=document.getElementById("rationale").value.trim(),axisWinners=Object.fromEntries(task.quality_axes.map((axis,index)=>[axis,pick(`axis_${{index}}`)]));if(pseudonym.length<3||!choice||!publishability||!defect||Object.values(axisWinners).some(v=>!v)||rationale.length<32||!document.getElementById("attest").checked||(defect!=="none"&&defectReason.length<16))throw Error("Complete every field, axis and attestation.");const review={{schema:"ProofLaunchCreativeABHumanReviewV1",comparison_id:task.comparison_id,review_task_id:task.review_task_id,reviewer_slot:task.reviewer_slot,pair_sha256:task.pair_sha256,reviewer_pseudonym:pseudonym,choice,axis_winners:axisWinners,publishability,blocking_defect_side:defect,blocking_defect_reason:defectReason,rationale,human_attestation:"independent_source_hidden_no_model_judge",reviewed_at:new Date().toISOString()}};review.review_content_sha256=await hex(review);const blob=new Blob([JSON.stringify(review,null,2)+"\\n"],{{type:"application/json"}}),a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`claim-trial-creative-review-${{task.reviewer_slot}}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);document.getElementById("status").textContent=`Exported locally · ${{review.review_content_sha256}} · no promotion occurred.`}}catch(error){{document.getElementById("status").textContent="Blocked: "+error.message}}}};
</script></main></body></html>'''


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {OUTPUT}")
    gate = json.loads(GATE.read_text(encoding="utf-8"))
    by_id = {row["artifact_id"]: row for row in gate["results"]}
    if not by_id["claim-trial-v1"]["gate"]["release_ready"] or not by_id["claim-trial-v2"]["gate"]["release_ready"]:
        raise SystemExit("both creative candidates must pass the deterministic release gate")
    public = OUTPUT / "public"
    private = OUTPUT / "private"
    assets = public / "assets"
    assets.mkdir(parents=True, mode=0o700)
    private.mkdir(parents=True, mode=0o700)
    aliases = {
        "v1": f"blind-{secrets.token_hex(12)}.png",
        "v2": f"blind-{secrets.token_hex(12)}.png",
    }
    atomic_write_bytes(assets / aliases["v1"], V1.read_bytes())
    atomic_write_bytes(assets / aliases["v2"], V2.read_bytes())
    metadata = {
        key: {**_artifact_metadata(assets / alias), "alias": alias}
        for key, alias in aliases.items()
    }
    comparison_id = f"creative-ab-{secrets.token_hex(12)}"
    slots = list(range(1, 6))
    secrets.SystemRandom().shuffle(slots)
    v2_left_slots = set(slots[: 2 + secrets.randbelow(2)])
    tasks = []
    mappings = {}
    for reviewer_slot in range(1, 6):
        v2_side = "left" if reviewer_slot in v2_left_slots else "right"
        left_key, right_key = ("v2", "v1") if v2_side == "left" else ("v1", "v2")
        task = {
            "comparison_id": comparison_id,
            "review_task_id": f"creative-ab-task-{secrets.token_hex(10)}-reviewer-{reviewer_slot}",
            "reviewer_slot": reviewer_slot,
            "same_brief_task": "Choose the stronger 4:5 Claim Trial feed asset for qualified B2B founder and growth-operator attention.",
            "effect_question": "Which asset is more likely to stop the intended audience, make the self-indictment instantly clear, preserve evidence truth and earn a qualified response without major rework?",
            "quality_axes": AXES,
            "left_asset": metadata[left_key],
            "right_asset": metadata[right_key],
        }
        task["pair_sha256"] = pair_hash(task)
        tasks.append(task)
        mappings[task["review_task_id"]] = {"left": left_key, "right": right_key}
        atomic_write_text(public / f"reviewer-{reviewer_slot:02d}.html", review_html(task))
    files = {
        str(path.relative_to(public)): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in sorted(public.rglob("*")) if path.is_file()
    }
    public_packet = seal({
        "schema": "ProofLaunchCreativeABPublicPacketV1",
        "comparison_id": comparison_id,
        "reviewer_count": 5,
        "expected_review_count": 5,
        "submitted_review_count": 0,
        "review_tasks": tasks,
        "files": files,
        "source_roles_exposed": False,
        "model_judge_can_promote": False,
        "automatic_promotion_enabled": False,
        "market_effect_observed": False,
        "truth_boundary": "This packet enables source-hidden creative preference review only. Empty tasks prove no preference, promotion, publication or market effect.",
    })
    public_path = public / "packet.json"
    atomic_write_text(public_path, json.dumps(public_packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    kits = []
    for task in tasks:
        slot = task["reviewer_slot"]
        target = OUTPUT / "offline-kits" / f"reviewer-{slot:02d}.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        members = {
            "review.html": review_html(task).encode(),
            "task.json": (json.dumps(task, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(),
            f"assets/{task['left_asset']['alias']}": (assets / task["left_asset"]["alias"]).read_bytes(),
            f"assets/{task['right_asset']['alias']}": (assets / task["right_asset"]["alias"]).read_bytes(),
        }
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, body in sorted(members.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, body)
        kits.append({"reviewer_slot": slot, "path": str(target.relative_to(OUTPUT)), "sha256": sha256_file(target), "bytes": target.stat().st_size})
    private_packet = seal({
        "schema": "ProofLaunchCreativeABPrivateMappingV1",
        "public_packet_sha256": sha256_file(public_path),
        "source_brief_sha256": sha256_file(BRIEF),
        "visual_release_gate_sha256": sha256_file(GATE),
        "v1_sha256": sha256_file(V1),
        "v2_sha256": sha256_file(V2),
        "task_side_mapping": mappings,
        "v2_left_count": len(v2_left_slots),
        "reviewer_kits": kits,
        "automatic_promotion_enabled": False,
    })
    private_path = private / "mapping.json"
    atomic_write_text(private_path, json.dumps(private_packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    private_path.chmod(0o600)
    receipt = seal({
        "schema": "ProofLaunchCreativeABPacketReceiptV1",
        "comparison_id": comparison_id,
        "public_packet_sha256": sha256_file(public_path),
        "private_mapping_sha256": sha256_file(private_path),
        "reviewer_kit_count": 5,
        "submitted_review_count": 0,
        "automatic_promotion_enabled": False,
        "truth_boundary": public_packet["truth_boundary"],
    })
    atomic_write_text(OUTPUT / "packet-receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "comparison_id": comparison_id, "reviewer_kit_count": 5, "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
