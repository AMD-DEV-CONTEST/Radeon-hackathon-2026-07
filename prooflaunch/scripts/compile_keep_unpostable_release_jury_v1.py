from __future__ import annotations

import hashlib
import html
import json
import shutil
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.visual_release_gate import seal


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/gtm-last-mile-pk-v1"
OUTPUT = BASE / "keep-unpostable-release-jury-v1"
VIDEO_RECEIPT = BASE / "keep-unpostable-video-v1/receipt.json"
CAROUSEL_RECEIPT = BASE / "keep-unpostable-carousel-v1/receipt.json"
AUDIO_RECEIPT = BASE / "keep-unpostable-audio-v1/audio-candidate-receipt.json"
REVIEWER_COUNT = 5
AXES = (
    "first_three_second_stop_power",
    "value_proposition_recall",
    "platform_nativeness",
    "visual_craft",
    "motion_pacing",
    "audio_naturalness",
    "sound_picture_fit",
    "privacy_boundary_comprehension",
    "qualified_action_clarity",
    "originality_without_imitation",
)


def blind_alias(path: Path, prefix: str) -> str:
    return f"{prefix}-{sha256_file(path)[:18]}{path.suffix.lower()}"


def copy_asset(source: Path, directory: Path, prefix: str) -> str:
    alias = blind_alias(source, prefix)
    target = directory / alias
    if not target.is_file() or sha256_file(target) != sha256_file(source):
        shutil.copyfile(source, target)
    return alias


def reviewer_page(task: dict) -> str:
    encoded = json.dumps(task, ensure_ascii=False).replace("</", "<\\/")
    carousel = "".join(
        f'<figure><img src="assets/{html.escape(row["alias"])}" alt="source-hidden carousel slide {index}"><figcaption>{index:02d}</figcaption></figure>'
        for index, row in enumerate(task["carousel_assets"], start=1)
    )
    audio = "".join(
        f'<article><b>VOICE {index}</b><audio controls preload="metadata" src="assets/{html.escape(row["alias"])}"></audio></article>'
        for index, row in enumerate(task["audio_assets"], start=1)
    )
    axes = "".join(
        f'''<fieldset class="axis"><legend>{html.escape(axis.replace("_", " ").upper())}</legend>
        {''.join(f'<label><input required type="radio" name="axis_{index}" value="{score}">{score}</label>' for score in range(1, 6))}</fieldset>'''
        for index, axis in enumerate(AXES)
    )
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Keep the Unpostable release jury</title><style>
:root{{--paper:#eee9de;--ink:#0b0b0a;--acid:#dcff32;--blue:#345cff;--red:#ff6048}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 Arial,sans-serif}}main{{max-width:1240px;margin:auto;padding:28px}}header,.panel,form{{margin-bottom:18px;padding:24px;border:2px solid var(--ink);background:#fff}}h1{{max-width:900px;margin:.25em 0;font-size:clamp(42px,7vw,92px);line-height:.84;letter-spacing:-.065em}}h2{{font-size:32px;letter-spacing:-.035em}}.boundary{{padding:14px;background:var(--ink);color:#fff;font:800 12px/1.45 ui-monospace,monospace}}video{{display:block;width:min(100%,420px);max-height:760px;margin:auto;background:#000}}.slides{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}}figure{{margin:0}}figure img{{display:block;width:100%;border:1px solid var(--ink)}}figcaption{{padding:5px;background:var(--ink);color:#fff;font:900 11px ui-monospace,monospace}}.audios{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.audios article{{padding:16px;border:2px solid var(--ink)}}audio{{width:100%;margin-top:10px}}fieldset{{margin:14px 0;padding:14px;border:1px solid #777}}legend{{font-weight:900}}.axis{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}}.axis legend{{grid-column:1/-1}}.axis label{{padding:10px;text-align:center;border:1px solid #999}}input[type=text],textarea{{display:block;width:100%;margin-top:6px;padding:10px;font:inherit}}textarea{{min-height:110px}}button{{padding:15px 18px;border:2px solid var(--ink);background:var(--acid);font-weight:900}}#status{{font-family:ui-monospace,monospace}}@media(max-width:760px){{.slides{{grid-template-columns:1fr 1fr}}.audios{{grid-template-columns:1fr}}}}
</style></head><body><main><header><b>INDEPENDENT HUMAN RELEASE GATE · SLOT {task['reviewer_slot']}</b><h1>Would you release this work without major repair?</h1><p>Review the complete 15-second vertical, five-slide carousel and three source-hidden voice candidates. Judge the actual artifact—not the model, framework or author.</p><div class="boundary">SYNTHETIC PRODUCT CONCEPT · NO USER RESULT · NO MARKET EFFECT · NO NAMED-PRODUCT PK CLAIM · NOTHING IS TRANSMITTED</div></header>
<section class="panel"><h2>01 / 15-second vertical</h2><video controls playsinline preload="metadata" src="assets/{html.escape(task['video_asset']['alias'])}"></video></section>
<section class="panel"><h2>02 / Five-slide carousel</h2><div class="slides">{carousel}</div></section>
<section class="panel"><h2>03 / Same-script voice candidates</h2><p>Listen independently. Select the delivery that best protects the private-memory idea without becoming sentimental or salesy.</p><div class="audios">{audio}</div></section>
<form id="review"><label>Stable reviewer pseudonym<input required id="pseudonym" type="text" minlength="3"></label>
<fieldset><legend>Preferred voice</legend>{''.join(f'<label><input required type="radio" name="voice" value="voice_{index}"> VOICE {index}</label>' for index in range(1, 4))}<label><input required type="radio" name="voice" value="abstain"> ABSTAIN</label></fieldset>
<fieldset><legend>Direct release readiness</legend><label><input required type="radio" name="video_release" value="yes"> VIDEO yes</label><label><input required type="radio" name="video_release" value="no"> VIDEO no</label><label><input required type="radio" name="carousel_release" value="yes"> CAROUSEL yes</label><label><input required type="radio" name="carousel_release" value="no"> CAROUSEL no</label></fieldset>
{axes}
<fieldset><legend>Blocking defect</legend><label><input required type="radio" name="defect" value="none"> NONE</label><label><input required type="radio" name="defect" value="video"> VIDEO</label><label><input required type="radio" name="defect" value="carousel"> CAROUSEL</label><label><input required type="radio" name="defect" value="audio"> AUDIO</label><label><input required type="radio" name="defect" value="multiple"> MULTIPLE</label></fieldset>
<label>Located defect or major repair needed<textarea id="defect_reason" placeholder="Required unless NONE"></textarea></label>
<label>Independent rationale<textarea required id="rationale" minlength="80" placeholder="Locate concrete evidence in the work. Explain hook, comprehension, craft, platform fit and qualified action."></textarea></label>
<label><input required id="attest" type="checkbox"> I reviewed independently, did not consult the private mapping or another review, and understand this is not proof of market effect.</label>
<p><button type="submit">DOWNLOAD REVIEW JSON</button></p><p id="status">Nothing transmitted.</p></form></main>
<script id="task" type="application/json">{encoded}</script><script>
const task=JSON.parse(document.getElementById("task").textContent);const pick=n=>document.querySelector(`input[name="${{n}}"]:checked`)?.value;const stable=v=>Array.isArray(v)?`[${{v.map(stable).join(",")}}]`:v&&typeof v==="object"?`{{${{Object.keys(v).sort().map(k=>`${{JSON.stringify(k)}}:${{stable(v[k])}}`).join(",")}}}}`:JSON.stringify(v);const hex=async v=>Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(stable(v)))),b=>b.toString(16).padStart(2,"0")).join("");document.getElementById("review").onsubmit=async e=>{{e.preventDefault();try{{const pseudonym=document.getElementById("pseudonym").value.trim(),voice=pick("voice"),videoRelease=pick("video_release"),carouselRelease=pick("carousel_release"),defect=pick("defect"),defectReason=document.getElementById("defect_reason").value.trim(),rationale=document.getElementById("rationale").value.trim(),scores=Object.fromEntries(task.quality_axes.map((axis,index)=>[axis,Number(pick(`axis_${{index}}`))]));if(pseudonym.length<3||!voice||!videoRelease||!carouselRelease||!defect||Object.values(scores).some(v=>!v)||rationale.length<80||!document.getElementById("attest").checked||(defect!=="none"&&defectReason.length<20))throw Error("Complete every field, score, rationale and attestation.");const review={{schema:"ProofLaunchKeepUnpostableHumanReleaseReviewV1",review_task_id:task.review_task_id,reviewer_slot:task.reviewer_slot,task_sha256:task.task_sha256,reviewer_pseudonym:pseudonym,preferred_voice:voice,video_direct_release:videoRelease,carousel_direct_release:carouselRelease,axis_scores:scores,blocking_defect:defect,blocking_defect_reason:defectReason,rationale,human_attestation:"independent_source_hidden_generation_route_no_model_judge",reviewed_at:new Date().toISOString()}};review.review_content_sha256=await hex(review);const blob=new Blob([JSON.stringify(review,null,2)+"\n"],{{type:"application/json"}}),a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`keep-unpostable-release-review-${{task.reviewer_slot}}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);document.getElementById("status").textContent=`Exported locally · ${{review.review_content_sha256}} · no release occurred.`}}catch(error){{document.getElementById("status").textContent="Blocked: "+error.message}}}};
</script></body></html>'''


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise SystemExit("release-jury output must be empty")
    public = OUTPUT / "public"
    private = OUTPUT / "private"
    assets = public / "assets"
    assets.mkdir(parents=True)
    private.mkdir(parents=True)

    video_receipt = json.loads(VIDEO_RECEIPT.read_text(encoding="utf-8"))
    carousel_receipt = json.loads(CAROUSEL_RECEIPT.read_text(encoding="utf-8"))
    audio_receipt = json.loads(AUDIO_RECEIPT.read_text(encoding="utf-8"))
    if any(
        receipt.get("human_preference_observed")
        for receipt in (video_receipt, carousel_receipt, audio_receipt)
    ):
        raise SystemExit("source preference boundary drifted")

    video_source = ROOT / video_receipt["video"]["path"]
    video_asset = {"alias": copy_asset(video_source, assets, "blind-video"), "sha256": sha256_file(video_source)}
    carousel_assets = []
    for row in carousel_receipt["files"]:
        source = BASE / "keep-unpostable-carousel-v1" / row["png"]["path"]
        carousel_assets.append({"alias": copy_asset(source, assets, "blind-slide"), "sha256": sha256_file(source)})
    original_audio = []
    for row in audio_receipt["candidates"]:
        source = ROOT / row["master"]["project_relative_path"]
        original_audio.append(
            {
                "candidate_id": row["candidate_id"],
                "alias": copy_asset(source, assets, "blind-voice"),
                "sha256": sha256_file(source),
            }
        )

    mappings = []
    task_files = []
    for slot_number in range(1, REVIEWER_COUNT + 1):
        slot = f"reviewer-{slot_number:02d}"
        ordered_audio = sorted(
            original_audio,
            key=lambda row: hashlib.sha256(f"{slot}:{row['sha256']}".encode()).hexdigest(),
        )
        task = {
            "schema": "ProofLaunchKeepUnpostableReleaseTaskV1",
            "review_task_id": f"keep-unpostable-release-v1-{slot}",
            "reviewer_slot": slot,
            "quality_axes": AXES,
            "video_asset": video_asset,
            "carousel_assets": carousel_assets,
            "audio_assets": [{"alias": row["alias"], "sha256": row["sha256"]} for row in ordered_audio],
            "external_publish_executed": False,
        }
        task["task_sha256"] = hashlib.sha256(
            json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        filename = f"{slot}.html"
        atomic_write_text(public / filename, reviewer_page(task))
        task_files.append({"reviewer_slot": slot, "path": f"public/{filename}", "sha256": sha256_file(public / filename)})
        mappings.append(
            {
                "reviewer_slot": slot,
                "task_sha256": task["task_sha256"],
                "voice_mapping": {
                    f"voice_{index}": row["candidate_id"] for index, row in enumerate(ordered_audio, start=1)
                },
            }
        )

    atomic_write_text(private / "mapping.json", json.dumps({"mappings": mappings}, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    receipt = seal(
        {
            "schema": "ProofLaunchKeepUnpostableReleaseJuryReceiptV1",
            "reviewer_count": REVIEWER_COUNT,
            "expected_human_review_count": REVIEWER_COUNT,
            "submitted_human_review_count": 0,
            "quality_axis_count": len(AXES),
            "audio_candidate_count": len(original_audio),
            "carousel_slide_count": len(carousel_assets),
            "video_count": 1,
            "task_files": task_files,
            "asset_files": [
                {"path": str(path.relative_to(OUTPUT)), "sha256": sha256_file(path), "bytes": path.stat().st_size}
                for path in sorted(assets.iterdir())
            ],
            "private_mapping_sha256": sha256_file(private / "mapping.json"),
            "generation_route_hidden": True,
            "named_product_baseline_present": False,
            "human_review_completed": False,
            "release_approved": False,
            "external_publish_executed": False,
            "market_effect_observed": False,
            "truth_boundary": (
                "This packet makes five independent human release reviews executable for one synthetic B2C campaign system. "
                "It is not a named-product comparison and empty tasks prove no preference, direct publishability, release approval, 4A quality or market effect."
            ),
        }
    )
    atomic_write_text(OUTPUT / "receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "reviewer_count": REVIEWER_COUNT, "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
