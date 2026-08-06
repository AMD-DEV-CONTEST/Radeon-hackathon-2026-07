#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.campaign_pack_blind_review import (  # noqa: E402
    CampaignPackBlindReviewService,
    DIMENSIONS,
    REVIEW_ATTESTATION,
)
from prooflaunch_remix.files import atomic_write_bytes, atomic_write_text, sha256_file  # noqa: E402
from prooflaunch_remix.gtm_unified_offline_review import (  # noqa: E402
    GENERIC_ATTESTATION,
    GENERIC_REVIEW_SCHEMA,
    KIT_SCHEMA,
    VISUAL_REVIEW_SCHEMA,
    generic_pair_sha256,
)


TEXT_PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/internal-text-review-v3"
MULTIMODAL_PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5"
VISUAL_PACKET = ROOT / "artifacts/campaign-pack-visual-blind-review-v1"
UNIFIED = MULTIMODAL_PACKET / "unified-last-mile-review.json"
DEFAULT_OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/unified-offline-review-kit-v2"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(payload)
    sealed["content_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    return sealed


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise SystemExit(f"invalid or empty JSONL: {path}")
    return rows


def _copy_public_stream(
    stream: str,
    source: Path,
    output: Path,
    *,
    lane_by_pair: dict[str, str],
) -> list[dict[str, Any]]:
    rows = _load_jsonl(source / "public/blind-pairs.jsonl")
    destination = output / "assets" / stream
    destination.mkdir(parents=True, mode=0o700)
    copied: set[str] = set()
    for row in rows:
        for side in ("left", "right"):
            relative = Path(str(row[f"{side}_artifact"]))
            if relative.is_absolute() or ".." in relative.parts:
                raise SystemExit("blind asset escaped its public packet")
            original = source / "public" / relative
            if not original.is_file() or original.is_symlink():
                raise SystemExit("blind asset is missing or unsafe")
            target = destination / original.name
            if target.name not in copied:
                atomic_write_bytes(target, original.read_bytes())
                copied.add(target.name)
            row[f"{side}_asset"] = f"assets/{stream}/{target.name}"
            row[f"{side}_sha256"] = sha256_file(target)
            if target.suffix.casefold() == ".json":
                row[f"{side}_payload"] = json.loads(target.read_text(encoding="utf-8"))
        row["stream_id"] = stream
        row["lane_id"] = lane_by_pair[str(row["pair_id"])]
        row["pair_sha256"] = generic_pair_sha256(row)
    return rows


def _generic_mapping(source: Path, *, lane: str | None = None) -> tuple[dict[str, str], str]:
    path = source / "private/role-mapping.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "ProofLaunchPrivateBlindRoleMappingV1":
        raise SystemExit("private role mapping schema drifted")
    pairs = payload.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise SystemExit("private role mapping is empty")
    lane_by_pair = {
        str(row["pair_id"]): lane or str(row["comparison_key"])
        for row in pairs
    }
    if len(lane_by_pair) != len(pairs):
        raise SystemExit("private role mapping contains duplicate pair IDs")
    return lane_by_pair, sha256_file(path)


def _visual_assignments(output: Path) -> dict[int, dict[str, Any]]:
    tokens = {slot: secrets.token_urlsafe(32) for slot in range(1, 6)}
    service = CampaignPackBlindReviewService(
        VISUAL_PACKET,
        project_root=ROOT,
        reviewer_tokens=tokens,
    )
    assets_root = output / "assets" / "visual"
    assets_root.mkdir(parents=True, mode=0o700)
    assignments: dict[int, dict[str, Any]] = {}
    copied: set[str] = set()
    for slot in range(1, 6):
        assignment = service.tasks_for_slot(slot, reviewer_token=tokens[slot])
        task = json.loads(json.dumps(assignment["tasks"][0], ensure_ascii=False))
        for side in ("left", "right"):
            for asset in task["pair"]["sides"][side]["assets"]:
                alias = str(asset["asset_alias"])
                source, media_type, digest = service.asset_for_alias(alias)
                if media_type != "image/png" or sha256_file(source) != digest:
                    raise SystemExit("visual blind asset integrity gate failed")
                target = assets_root / f"{alias}.png"
                if target.name not in copied:
                    atomic_write_bytes(target, source.read_bytes())
                    copied.add(target.name)
                asset["offline_path"] = f"assets/visual/{target.name}"
        assignments[slot] = task
    return assignments


def _review_html(slot: int, generic_pairs: list[dict[str, Any]], visual_task: dict[str, Any]) -> str:
    state = {
        "reviewer_slot": slot,
        "generic_pairs": generic_pairs,
        "visual_task": visual_task,
        "visual_dimensions": list(DIMENSIONS),
        "visual_attestation": REVIEW_ATTESTATION,
        "generic_attestation": GENERIC_ATTESTATION,
    }
    encoded = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace("<", "\\u003c")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProofLaunch unified blind review · slot {slot}</title>
<style>
:root{{--ink:#eff2ff;--muted:#a8b0ca;--panel:#0e1325;--line:#323b5d;--accent:#8e6cff;--good:#42d69b}}*{{box-sizing:border-box}}
body{{margin:0;background:#070a14;color:var(--ink);font:15px/1.5 system-ui,sans-serif}}main{{max-width:1500px;margin:auto;padding:28px}}
header,.pair,.visual{{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:22px;margin:0 0 22px}}h1,h2,h3{{line-height:1.15}}code{{color:#c7b8ff}}
.boundary{{border-left:4px solid var(--accent);padding:10px 14px;background:#0a0e1d;color:var(--muted)}}.sides{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
.side{{min-width:0;border:1px solid var(--line);border-radius:14px;padding:14px;background:#080c19}}pre{{white-space:pre-wrap;word-break:break-word;max-height:520px;overflow:auto}}
audio,video,img{{display:block;width:100%;margin:8px 0 14px}}img{{height:auto}}fieldset{{border:1px solid var(--line);margin:12px 0;padding:12px}}label{{margin-right:14px}}
textarea,input[type=text]{{width:100%;padding:10px;background:#070a14;color:var(--ink);border:1px solid var(--line)}}textarea{{min-height:90px}}
button{{background:var(--accent);color:white;border:0;border-radius:10px;padding:13px 20px;font-weight:800;cursor:pointer}}.sticky{{position:sticky;bottom:0;background:#070a14ee;padding:14px;border-top:1px solid var(--line)}}
@media(max-width:800px){{.sides{{grid-template-columns:1fr}}}}
</style></head><body><main>
<header><p><strong>ProofLaunch · qualified independent human evidence</strong></p><h1>Unified identity-hidden last-mile review</h1>
<p>Reviewer slot <code>{slot}</code> · 16 hash-bound comparison pairs · 11 text/decision + 3 audio + 1 video + 1 visual system.</p>
<p class="boundary">Identities and roles are hidden. Work offline and independently. This page exports local files only: it cannot submit, deblind, promote, publish, send or spend.</p>
<label>Stable reviewer ID / pseudonym<input id="rater" type="text" minlength="3" maxlength="120" required></label>
<p><label><input id="independent" type="checkbox"> I independently reviewed every identity-hidden same-brief pair without candidate, provider, model, private-mapping, or other-reviewer information.</label><label><input id="conflict" type="checkbox"> I completed conflict disclosure and have no undisclosed conflict.</label></p></header>
<section id="generic"></section><section id="visual"></section>
<div class="sticky"><button id="export" type="button">Validate all 16 pairs and download results</button> <span id="status" aria-live="polite">No review has been submitted.</span></div>
<script id="review-state" type="application/json">{encoded}</script>
<script>
const state=JSON.parse(document.getElementById("review-state").textContent), generic=document.getElementById("generic");
const escapeHtml=(v)=>String(v).replace(/[&<>\"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
const media=(pair,side)=>{{const path=pair[side+"_asset"],suffix=path.split(".").pop().toLowerCase();if(suffix==="json")return `<pre>${{escapeHtml(JSON.stringify(pair[side+"_payload"],null,2))}}</pre>`;if(suffix==="wav")return `<audio controls preload="metadata" src="${{path}}"></audio>`;return `<video controls preload="metadata" src="${{path}}"></video>`}};
const radios=(name,values)=>values.map(v=>`<label><input required type="radio" name="${{name}}" value="${{v}}"> ${{v.toUpperCase()}}</label>`).join("");
state.generic_pairs.forEach((pair,index)=>{{const article=document.createElement("article");article.className="pair";article.dataset.pair=pair.pair_id;article.innerHTML=`<h2>${{index+1}}. ${{escapeHtml(pair.capability)}}</h2><p><code>${{pair.pair_id}} · sha256:${{pair.pair_sha256}}</code></p><div class="sides"><div class="side"><h3>LEFT</h3>${{media(pair,"left")}}</div><div class="side"><h3>RIGHT</h3>${{media(pair,"right")}}</div></div><fieldset><legend>Overall choice</legend>${{radios("choice-"+index,["left","right","abstain"])}}</fieldset><div class="sides"><fieldset><legend>LEFT delivery status</legend>${{radios("left-pub-"+index,["publishable","not_publishable"])}}<br>${{radios("left-rework-"+index,["major_rework","no_major_rework"])}}</fieldset><fieldset><legend>RIGHT delivery status</legend>${{radios("right-pub-"+index,["publishable","not_publishable"])}}<br>${{radios("right-rework-"+index,["major_rework","no_major_rework"])}}</fieldset></div><fieldset><legend>Blocking production defect</legend>${{radios("defect-"+index,["none","left","right","both"])}}</fieldset><label>Located blocking-defect reason (required unless NONE)<textarea data-defect-reason maxlength="1200"></textarea></label><label>Located rationale (minimum 20 characters)<textarea data-rationale minlength="20" maxlength="2000" required></textarea></label>`;generic.append(article)}});
const visual=state.visual_task, visualRoot=document.getElementById("visual"), vArticle=document.createElement("article");vArticle.className="visual";let visualSides="";for(const side of ["left","right"]){{visualSides+=`<div class="side"><h3>${{side.toUpperCase()}}</h3>`;for(const asset of visual.pair.sides[side].assets)visualSides+=`<img src="${{asset.offline_path}}" alt="${{side}} ${{asset.role}}"><p>${{asset.role}} · ${{asset.width}}×${{asset.height}}</p>`;visualSides+="</div>"}}let dimensionHtml="";for(const dim of state.visual_dimensions)dimensionHtml+=`<fieldset data-dimension="${{dim}}"><legend>${{dim.replaceAll("_"," ")}}</legend>${{radios("visual-"+dim,["left","right","tie"])}}</fieldset>`;vArticle.innerHTML=`<h2>16. Visual campaign system</h2><p><code>${{visual.pair_id}} · sha256:${{visual.pair_sha256}}</code></p><div class="sides">${{visualSides}}</div><fieldset><legend>Overall stronger system</legend>${{radios("visual-overall",["left","right"])}}</fieldset>${{dimensionHtml}}<div class="sides"><fieldset><legend>LEFT delivery status</legend>${{radios("visual-left-pub",["publishable","not_publishable"])}}<br>${{radios("visual-left-rework",["major_rework","no_major_rework"])}}</fieldset><fieldset><legend>RIGHT delivery status</legend>${{radios("visual-right-pub",["publishable","not_publishable"])}}<br>${{radios("visual-right-rework",["major_rework","no_major_rework"])}}</fieldset></div><fieldset><legend>Blocking defect</legend>${{radios("visual-defect",["none","left","right","both"])}}</fieldset><label>Blocking-defect reason (required unless none)<textarea id="visual-defect-reason" maxlength="1200"></textarea></label><label>Visual rationale (minimum 24 characters)<textarea id="visual-notes" minlength="24" maxlength="2000" required></textarea></label>`;visualRoot.append(vArticle);
const checked=(name)=>document.querySelector(`input[name="${{name}}"]:checked`)?.value;
const stable=(v)=>Array.isArray(v)?`[${{v.map(stable).join(",")}}]`:v&&typeof v==="object"?`{{${{Object.keys(v).sort().map(k=>`${{JSON.stringify(k)}}:${{stable(v[k])}}`).join(",")}}}}`:JSON.stringify(v);
const hex=async(v)=>Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(stable(v)))),b=>b.toString(16).padStart(2,"0")).join("");
const download=(name,body,type)=>{{const blob=new Blob([body],{{type}}),a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}};
document.getElementById("export").onclick=async()=>{{try{{const rater=document.getElementById("rater").value.trim();if(rater.length<3||!document.getElementById("independent").checked||!document.getElementById("conflict").checked)throw Error("Provide a stable reviewer ID and complete both attestations.");const now=new Date().toISOString(),votes=[];for(let index=0;index<state.generic_pairs.length;index++){{const pair=state.generic_pairs[index],root=document.querySelector(`[data-pair="${{pair.pair_id}}"]`),rationale=root.querySelector("[data-rationale]").value.trim(),defectReason=root.querySelector("[data-defect-reason]").value.trim(),lp=checked("left-pub-"+index),lr=checked("left-rework-"+index),rp=checked("right-pub-"+index),rr=checked("right-rework-"+index),choice=checked("choice-"+index),defect=checked("defect-"+index);if(!choice||!lp||!lr||!rp||!rr||!defect||rationale.length<20||(defect!=="none"&&defectReason.length<16))throw Error(`Complete pair ${{index+1}}, its delivery verdicts, and located rationale.`);const leftPub=lp==="publishable",leftMajor=lr==="major_rework",rightPub=rp==="publishable",rightMajor=rr==="major_rework";if((leftPub&&leftMajor)||(rightPub&&rightMajor))throw Error(`Pair ${{index+1}} cannot mark a side publishable and major-rework.`);const vote={{schema:{json.dumps(GENERIC_REVIEW_SCHEMA)},reviewer_slot:state.reviewer_slot,pair_id:pair.pair_id,pair_sha256:pair.pair_sha256,choice,reviewer_pseudonym:rater,human_attestation:state.generic_attestation,independent_attestation:true,conflict_disclosed:true,reviewed_at:now,left_directly_publishable:leftPub,right_directly_publishable:rightPub,left_major_rework:leftMajor,right_major_rework:rightMajor,blocking_defect_side:defect,blocking_defect_reason:defectReason,rationale}};vote.review_content_sha256=await hex(vote);votes.push(vote)}}const defect=checked("visual-defect"),reason=document.getElementById("visual-defect-reason").value.trim(),notes=document.getElementById("visual-notes").value.trim(),overall=checked("visual-overall"),vlp=checked("visual-left-pub"),vlr=checked("visual-left-rework"),vrp=checked("visual-right-pub"),vrr=checked("visual-right-rework");if(!defect||!overall||!vlp||!vlr||!vrp||!vrr||notes.length<24||(defect!=="none"&&reason.length<16))throw Error("Complete the visual verdict, delivery statuses, rationale, and located defect reason.");const vlPub=vlp==="publishable",vlMajor=vlr==="major_rework",vrPub=vrp==="publishable",vrMajor=vrr==="major_rework";if((vlPub&&vlMajor)||(vrPub&&vrMajor))throw Error("Visual pair cannot mark a side publishable and major-rework.");const dimension_winners={{}};for(const dim of state.visual_dimensions){{const value=checked("visual-"+dim);if(!value)throw Error(`Complete visual dimension: ${{dim}}`);dimension_winners[dim]=value}}const visualReview={{schema:{json.dumps(VISUAL_REVIEW_SCHEMA)},review_task_id:visual.review_task_id,pair_id:visual.pair_id,pair_sha256:visual.pair_sha256,reviewer_slot:state.reviewer_slot,reviewer_pseudonym:rater,human_attestation:state.visual_attestation,overall_winner:overall,dimension_winners,left_directly_publishable:vlPub,right_directly_publishable:vrPub,left_major_rework:vlMajor,right_major_rework:vrMajor,blocking_defect_side:defect,blocking_defect_reason:reason,notes,reviewed_at:now}};visualReview.review_content_sha256=await hex(visualReview);download(`prooflaunch-reviewer-${{String(state.reviewer_slot).padStart(2,"0")}}-generic-votes.jsonl`,votes.map(v=>JSON.stringify(v)).join("\\n")+"\\n","application/x-ndjson");download(`prooflaunch-reviewer-${{String(state.reviewer_slot).padStart(2,"0")}}-visual-review.json`,JSON.stringify(visualReview,null,2)+"\\n","application/json");document.getElementById("status").textContent="Two hash-bound local result files downloaded. Nothing was transmitted or promoted."}}catch(error){{document.getElementById("status").textContent="Blocked: "+error.message}}}};
</script></main></body></html>'''


def _write_zip(root: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(root.rglob("*")):
            if path == target or not path.is_file():
                continue
            info = zipfile.ZipInfo(str(path.relative_to(root)), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def export(output: Path) -> dict[str, Any]:
    output.resolve().relative_to(ROOT)
    if output.exists() and any(output.iterdir()):
        raise SystemExit("output directory must be empty")
    output.mkdir(parents=True, mode=0o700)
    unified = json.loads(UNIFIED.read_text(encoding="utf-8"))
    if (unified["lane_count"], unified["comparison_pair_count"], unified["expected_human_review_count"]) != (14, 16, 80):
        raise SystemExit("unified review inventory drifted")
    text_lanes, text_mapping_sha = _generic_mapping(TEXT_PACKET)
    audio_lanes, audio_mapping_sha = _generic_mapping(MULTIMODAL_PACKET / "audio", lane="audio")
    video_lanes, video_mapping_sha = _generic_mapping(MULTIMODAL_PACKET / "video", lane="video")
    streams = [
        *_copy_public_stream("text-decision", TEXT_PACKET, output, lane_by_pair=text_lanes),
        *_copy_public_stream("audio", MULTIMODAL_PACKET / "audio", output, lane_by_pair=audio_lanes),
        *_copy_public_stream("video", MULTIMODAL_PACKET / "video", output, lane_by_pair=video_lanes),
    ]
    if len(streams) != 15:
        raise SystemExit("generic review pair inventory drifted")
    visual = _visual_assignments(output)
    for slot in range(1, 6):
        atomic_write_text(output / f"reviewer-{slot:02d}.html", _review_html(slot, streams, visual[slot]))
    atomic_write_text(
        output / "README.md",
        "# ProofLaunch unified offline review kit V2\n\nOpen only your assigned `reviewer-XX.html` file. "
        "Review all 16 hash-bound pairs independently and return the two downloaded result files. "
        "Do not open any private role mapping. No network submission, promotion, publication, send, or spend occurs.\n",
    )
    files = {
        str(path.relative_to(output)): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in sorted(output.rglob("*")) if path.is_file()
    }
    manifest = _seal(
        {
            "schema": KIT_SCHEMA,
            "reviewer_page_count": 5,
            "pair_count_per_reviewer": 16,
            "generic_pair_count_per_reviewer": 15,
            "visual_pair_count_per_reviewer": 1,
            "expected_human_review_count": 80,
            "submitted_human_review_count": 0,
            "source_unified_review_sha256": sha256_file(UNIFIED),
            "generic_private_mapping_commitments": {
                "text-decision": text_mapping_sha,
                "audio": audio_mapping_sha,
                "video": video_mapping_sha,
            },
            "visual_private_mapping_commitment": sha256_file(
                VISUAL_PACKET / "campaign-pack-blind-review-private.json"
            ),
            "generic_pairs": [
                {
                    key: row[key]
                    for key in (
                        "stream_id", "lane_id", "pair_id", "scenario_id", "capability",
                        "left_blind_id", "right_blind_id", "left_sha256", "right_sha256",
                        "pair_sha256",
                    )
                }
                for row in streams
            ],
            "visual_tasks": [
                {
                    "reviewer_slot": slot,
                    "review_task_id": visual[slot]["review_task_id"],
                    "pair_id": visual[slot]["pair_id"],
                    "pair_sha256": visual[slot]["pair_sha256"],
                    "comparison_id": "visual-system",
                    "lane_id": "visual-system",
                    "stream_id": "visual-system",
                }
                for slot in range(1, 6)
            ],
            "files": files,
            "candidate_identity_exposed": False,
            "provider_identity_exposed": False,
            "model_identity_exposed": False,
            "private_mapping_included": False,
            "invitation_token_included": False,
            "network_submission_enabled": False,
            "automatic_promotion_enabled": False,
            "automatic_publish_enabled": False,
            "truth_boundary": (
                "This portable kit makes eighty identity-hidden review tasks executable and exports "
                "local result files. It records no human observation by itself and proves no 4A, "
                "Top-product, publication, causal lift or revenue result."
            ),
        }
    )
    manifest_path = output / "manifest.json"
    atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    archive = output / "prooflaunch-unified-offline-review-kit-v2.zip"
    _write_zip(output, archive)
    receipt = _seal(
        {
            "schema": "ProofLaunchGTMUnifiedOfflineReviewKitExportReceiptV2",
            "manifest_sha256": sha256_file(manifest_path),
            "archive": {"path": str(archive.relative_to(ROOT)), "sha256": sha256_file(archive), "bytes": archive.stat().st_size},
            "reviewer_page_count": 5,
            "expected_human_review_count": 80,
            "submitted_human_review_count": 0,
            "network_calls": 0,
            "automatic_external_actions": 0,
        }
    )
    atomic_write_text(output / "export-receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    result = export(Path(args.output_dir).expanduser().resolve())
    print(json.dumps({"archive": result["archive"], "reviewer_pages": 5, "expected_reviews": 80, "submitted_reviews": 0, "content_sha256": result["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
