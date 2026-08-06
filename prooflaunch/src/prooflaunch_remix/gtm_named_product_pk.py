from __future__ import annotations

import hashlib
import html
import json
import math
import mimetypes
import re
import secrets
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .files import atomic_write_bytes, atomic_write_text, sha256_file
from .gtm_challenger_dossier import (
    ChallengerDossierError,
    admitted_dossier_for_category,
    validate_challenger_admission,
)
from .gtm_named_product_baseline import (
    NamedProductBaselineError,
    validate_capture,
    validate_kit_manifest,
)
from .gtm_unified_offline_review import canonical_json_bytes, seal, sha256_json


PREPARATION_SCHEMA = "ProofLaunchNamedProductBlindPairPreparationV1"
PUBLIC_PACKET_SCHEMA = "ProofLaunchNamedProductBlindPKPublicPacketV1"
PRIVATE_PACKET_SCHEMA = "ProofLaunchNamedProductBlindPKPrivatePacketV1"
REVIEW_SCHEMA = "ProofLaunchNamedProductBlindHumanReviewV2"
AGGREGATE_SCHEMA = "ProofLaunchNamedProductBlindPKAggregateV2"
PORTFOLIO_SCHEMA = "ProofLaunchNamedProductBlindPKPortfolioV1"
REVIEW_ATTESTATION = (
    "I independently reviewed this source-hidden same-brief pair without using "
    "the private mapping, another review, or outside product identity information."
)
PREPARATION_ATTESTATIONS = (
    "same_frozen_brief_outputs",
    "provider_and_candidate_identity_removed_or_intrinsically_absent",
    "meaning_and_quality_preserved",
    "review_assets_authorized_to_retain",
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SLOT_ID = re.compile(r"^pk-[0-9a-f]{16}$")
_TASK_ID = re.compile(r"^named-pk-task-[0-9a-f]{20}-reviewer-[1-5]$")
_COMPARISON_ID = re.compile(r"^named-pk-[0-9a-f]{24}$")
_REVIEWABLE_EXTENSIONS = {
    ".json", ".md", ".txt", ".html", ".pdf",
    ".png", ".jpg", ".jpeg", ".webp",
    ".mp4", ".mov", ".webm",
    ".wav", ".mp3", ".flac", ".m4a",
}


class NamedProductPKError(ValueError):
    pass


class NamedProductPKConflictError(NamedProductPKError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise NamedProductPKError(f"unsafe or missing JSON input: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NamedProductPKError(f"invalid JSON input: {path}") from error
    if not isinstance(payload, dict):
        raise NamedProductPKError(f"JSON input must be an object: {path}")
    return payload


def _verify_seal(payload: object, *, schema: str, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        raise NamedProductPKError(f"{label} schema is invalid")
    supplied = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if not isinstance(supplied, str) or not _DIGEST.fullmatch(supplied) or supplied != sha256_json(unsigned):
        raise NamedProductPKError(f"{label} digest is invalid")
    return payload


def _inside(path: Path, root: Path) -> Path:
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root.resolve(strict=True))
    except ValueError as error:
        raise NamedProductPKError("candidate source escaped the project root") from error
    if resolved.is_symlink() or not resolved.is_file():
        raise NamedProductPKError("artifact input is missing or unsafe")
    return resolved


def _family(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in {".json", ".md", ".txt", ".html", ".pdf"}:
        return "document"
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image"
    if suffix in {".mp4", ".mov", ".webm"}:
        return "video"
    if suffix in {".wav", ".mp3", ".flac", ".m4a"}:
        return "audio"
    raise NamedProductPKError("review artifact type is not directly inspectable")


def _artifact_metadata(path: Path) -> dict[str, Any]:
    suffix = path.suffix.casefold()
    if suffix not in _REVIEWABLE_EXTENSIONS:
        raise NamedProductPKError("review artifact type is not directly inspectable")
    return {
        "name": path.name,
        "extension": suffix,
        "media_family": _family(path),
        "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _validate_timestamp(value: object, *, label: str) -> None:
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise NamedProductPKError(f"{label} timestamp is invalid") from error
    if timestamp.tzinfo is None:
        raise NamedProductPKError(f"{label} timestamp must include a timezone")


def _validate_ledger(payload: object) -> dict[str, Any]:
    ledger = _verify_seal(
        payload,
        schema="ProofLaunchConcreteProductEffectPKLedgerV1",
        label="product-effect PK ledger",
    )
    if ledger.get("category_count") != 13 or ledger.get("reference_product_row_count") != 130:
        raise NamedProductPKError("product-effect PK ledger coverage drifted")
    rows = ledger.get("product_pk_rows")
    if not isinstance(rows, list) or len(rows) != 130:
        raise NamedProductPKError("product-effect PK rows are incomplete")
    return ledger


def _stored_capture(
    *, manifest: Mapping[str, Any], baseline_store_root: Path, capture_slot_id: str
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    slot_dir = baseline_store_root.resolve(strict=True) / capture_slot_id
    capture_path = slot_dir / "capture.json"
    capture = _load_json(capture_path)
    artifacts = [
        path for path in slot_dir.iterdir()
        if path.is_file() and path.name != "capture.json"
    ]
    if len(artifacts) != 1:
        raise NamedProductPKError("stored baseline artifact inventory is invalid")
    try:
        validated, slot = validate_capture(capture, manifest=manifest, artifact_path=artifacts[0])
    except NamedProductBaselineError as error:
        raise NamedProductPKError(str(error)) from error
    return validated, artifacts[0], slot


def validate_preparation(
    payload: object,
    *,
    manifest: Mapping[str, Any],
    ledger: Mapping[str, Any],
    challenger_admission: Mapping[str, Any],
    capture: Mapping[str, Any],
    baseline_source_path: Path,
    baseline_review_path: Path,
    candidate_source_path: Path,
    candidate_review_path: Path,
    project_root: Path,
) -> dict[str, Any]:
    prep = _verify_seal(payload, schema=PREPARATION_SCHEMA, label="blind-pair preparation")
    if prep.get("capture_slot_id") != capture.get("capture_slot_id"):
        raise NamedProductPKError("blind-pair preparation is bound to another capture")
    if prep.get("automatic_pairing_authorized") is not False:
        raise NamedProductPKError("blind-pair preparation cannot grant automatic pairing authority")
    category_id = capture["category_id"]
    row = next(
        (
            item for item in ledger["product_pk_rows"]
            if item.get("category_id") == category_id
            and item.get("reference_product") == capture.get("reference_product")
        ),
        None,
    )
    if row is None:
        raise NamedProductPKError("named-product ledger row is missing")
    if prep.get("frozen_brief_sha256") != capture.get("frozen_brief_sha256"):
        raise NamedProductPKError("preparation is not bound to the frozen brief")
    if prep.get("challenger_admission_sha256") != challenger_admission.get("content_sha256"):
        raise NamedProductPKError("preparation is not bound to the challenger admission")
    operator = prep.get("operator_id")
    if not isinstance(operator, str) or not 3 <= len(operator.strip()) <= 120:
        raise NamedProductPKError("named preparation operator is required")
    _validate_timestamp(prep.get("prepared_at"), label="preparation")
    attestations = prep.get("attestations")
    if not isinstance(attestations, dict) or any(attestations.get(key) is not True for key in PREPARATION_ATTESTATIONS):
        raise NamedProductPKError("all blind-pair preparation attestations are required")
    baseline_source = _artifact_metadata(baseline_source_path)
    candidate_source = _artifact_metadata(candidate_source_path)
    baseline_review = _artifact_metadata(baseline_review_path)
    candidate_review = _artifact_metadata(candidate_review_path)
    if prep.get("baseline_source") != baseline_source or baseline_source["sha256"] != capture["artifact"]["sha256"]:
        raise NamedProductPKError("baseline source binding is invalid")
    candidate_relative = candidate_source_path.resolve(strict=True).relative_to(project_root.resolve(strict=True)).as_posix()
    if prep.get("candidate_source") != {**candidate_source, "project_relative_path": candidate_relative}:
        raise NamedProductPKError("candidate source binding is invalid")
    try:
        admitted_path = admitted_dossier_for_category(
            challenger_admission,
            category_id=category_id,
            project_root=project_root,
        )
    except ChallengerDossierError as error:
        raise NamedProductPKError(str(error)) from error
    if admitted_path != candidate_source_path.resolve(strict=True):
        raise NamedProductPKError("candidate source is not the admitted complete challenger dossier")
    if prep.get("baseline_review_artifact") != baseline_review or prep.get("candidate_review_artifact") != candidate_review:
        raise NamedProductPKError("review artifact binding is invalid")
    if baseline_review["media_family"] != baseline_source["media_family"]:
        raise NamedProductPKError("baseline anonymization changed the media family")
    admitted_category = next(
        (
            item for item in challenger_admission.get("categories", [])
            if item.get("category_id") == category_id
        ),
        None,
    )
    admitted_hashes = {
        str(item.get("sha256"))
        for item in (admitted_category or {}).get("source_artifacts", [])
        if isinstance(item, Mapping)
    }
    if (
        candidate_review["sha256"] != candidate_source["sha256"]
        and candidate_review["sha256"] not in admitted_hashes
    ):
        raise NamedProductPKError("candidate review artifact is not bound to the admitted dossier")
    if candidate_review["media_family"] != baseline_review["media_family"]:
        raise NamedProductPKError("same-brief review artifacts do not share a comparable media family")
    return prep


def create_preparation(
    *,
    project_root: Path,
    capture_manifest_path: Path,
    ledger_path: Path,
    challenger_admission_path: Path,
    baseline_store_root: Path,
    capture_slot_id: str,
    baseline_review_path: Path,
    candidate_review_path: Path,
    operator_id: str,
    prepared_at: str,
    attestations: Mapping[str, bool],
) -> dict[str, Any]:
    manifest = validate_kit_manifest(
        _load_json(capture_manifest_path), kit_root=capture_manifest_path.parent
    )
    ledger = _validate_ledger(_load_json(ledger_path))
    if manifest.get("source_ledger_sha256") != ledger["content_sha256"]:
        raise NamedProductPKError("capture kit and product-effect ledger are not bound")
    try:
        challenger_admission = validate_challenger_admission(
            _load_json(challenger_admission_path),
            ledger=ledger,
            project_root=project_root,
        )
    except ChallengerDossierError as error:
        raise NamedProductPKError(str(error)) from error
    capture, baseline_source_path, _ = _stored_capture(
        manifest=manifest,
        baseline_store_root=baseline_store_root,
        capture_slot_id=capture_slot_id,
    )
    try:
        candidate_source_path = admitted_dossier_for_category(
            challenger_admission,
            category_id=capture["category_id"],
            project_root=project_root,
        )
    except ChallengerDossierError as error:
        raise NamedProductPKError(str(error)) from error
    if baseline_review_path.is_symlink() or candidate_review_path.is_symlink():
        raise NamedProductPKError("symlinked review artifacts are not admitted")
    baseline_review_path = baseline_review_path.resolve(strict=True)
    candidate_review_path = candidate_review_path.resolve(strict=True)
    candidate_source = _artifact_metadata(candidate_source_path)
    candidate_relative = candidate_source_path.relative_to(project_root.resolve(strict=True)).as_posix()
    core = {
        "schema": PREPARATION_SCHEMA,
        "capture_slot_id": capture_slot_id,
        "frozen_brief_sha256": capture["frozen_brief_sha256"],
        "challenger_admission_sha256": challenger_admission["content_sha256"],
        "operator_id": operator_id,
        "prepared_at": prepared_at,
        "baseline_source": _artifact_metadata(baseline_source_path),
        "candidate_source": {**candidate_source, "project_relative_path": candidate_relative},
        "baseline_review_artifact": _artifact_metadata(baseline_review_path),
        "candidate_review_artifact": _artifact_metadata(candidate_review_path),
        "attestations": dict(attestations),
        "automatic_pairing_authorized": False,
        "truth_boundary": (
            "This named operator attests only that the two review artifacts are source-hidden, "
            "same-brief and materially faithful to their hash-bound originals. It is not a review "
            "vote, product victory, 4A claim, publication, lift or revenue evidence."
        ),
    }
    prep = seal(core)
    return validate_preparation(
        prep,
        manifest=manifest,
        ledger=ledger,
        challenger_admission=challenger_admission,
        capture=capture,
        baseline_source_path=baseline_source_path,
        baseline_review_path=baseline_review_path,
        candidate_source_path=candidate_source_path,
        candidate_review_path=candidate_review_path,
        project_root=project_root,
    )


def _public_pair_hash(task: Mapping[str, Any]) -> str:
    core = {
        key: task[key]
        for key in (
            "comparison_id", "review_task_id", "reviewer_slot", "category_id",
            "frozen_brief_sha256", "same_brief_task", "quality_axes", "effect_pk_question",
            "left_asset", "right_asset",
        )
    }
    for key in ("review_program_label", "review_heading", "review_boundary", "review_schema"):
        if key in task:
            core[key] = task[key]
    return sha256_json(core)


def _render_asset(asset: Mapping[str, Any]) -> str:
    path = str(asset["offline_path"])
    family = asset["media_family"]
    if asset.get("extension") in {".json", ".md", ".txt", ".csv"} and isinstance(asset.get("inline_text"), str):
        return f'<pre>{html.escape(str(asset["inline_text"]))}</pre>'
    if family == "image":
        return f'<img src="{path}" alt="identity-hidden review artifact">'
    if family == "video":
        return f'<video controls preload="metadata" src="{path}"></video>'
    if family == "audio":
        return f'<audio controls preload="metadata" src="{path}"></audio>'
    if asset["extension"] == ".pdf":
        return f'<iframe sandbox title="identity-hidden PDF" src="{path}"></iframe>'
    if asset["extension"] == ".html":
        return f'<iframe sandbox title="identity-hidden review dossier" src="{path}"></iframe>'
    return f'<pre data-text-path="{path}">Loading local text artifact…</pre>'


def _review_html(task: Mapping[str, Any]) -> str:
    encoded = json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace("<", "\\u003c")
    left = _render_asset(task["left_asset"])
    right = _render_asset(task["right_asset"])
    axis_rows = "".join(
        f'<fieldset><legend>{html.escape(str(axis))}</legend>'
        f'<label><input required type="radio" name="axis_{index}" value="left"> LEFT stronger</label>'
        f'<label><input required type="radio" name="axis_{index}" value="right"> RIGHT stronger</label>'
        f'<label><input required type="radio" name="axis_{index}" value="tie"> TIE</label></fieldset>'
        for index, axis in enumerate(task["quality_axes"])
    )
    program_label = html.escape(str(task.get("review_program_label") or "ProofLaunch · named-product last-mile PK"))
    review_heading = html.escape(str(task.get("review_heading") or "Source-hidden same-brief review"))
    review_boundary = html.escape(str(task.get("review_boundary") or (
        "Source roles are hidden by a named operator and hash-bound to the captured baseline and sealed challenger. "
        "Intrinsic style may still be recognizable. Do not research identities or consult another reviewer. "
        "This page exports locally and cannot promote, publish, send, or spend."
    )))
    review_schema = json.dumps(str(task.get("review_schema") or REVIEW_SCHEMA))
    text_loader = (
        'for(const node of document.querySelectorAll("pre[data-text-path]"))fetch(node.dataset.textPath)'
        '.then(r=>r.text()).then(t=>node.textContent=t)'
        '.catch(()=>node.textContent="Open the adjacent local asset directly; browser file policy blocked inline text loading.");'
        if "data-text-path" in left or "data-text-path" in right
        else ""
    )
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProofLaunch named-product source-hidden PK</title><style>
:root{{--ink:#f5f7ff;--muted:#aeb7d4;--panel:#11162a;--line:#384163;--accent:#8d6cff}}*{{box-sizing:border-box}}body{{margin:0;background:#080b16;color:var(--ink);font:15px/1.5 system-ui,sans-serif}}main{{max-width:1500px;margin:auto;padding:28px}}header,form,.side{{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px}}header,form{{margin-bottom:20px}}.sides{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:20px 0}}img,video,audio,iframe{{width:100%;display:block}}iframe{{height:650px;background:white}}pre{{white-space:pre-wrap;overflow:auto;max-height:650px}}fieldset{{margin:14px 0;border:1px solid var(--line)}}textarea,input[type=text]{{width:100%;padding:10px;background:#080b16;color:var(--ink);border:1px solid var(--line)}}textarea{{min-height:100px}}button{{padding:13px 18px;background:var(--accent);color:white;border:0;border-radius:9px;font-weight:800}}.boundary{{border-left:4px solid var(--accent);padding-left:12px;color:var(--muted)}}@media(max-width:800px){{.sides{{grid-template-columns:1fr}}}}
</style></head><body><main><header><p><strong>{program_label}</strong></p><h1>{review_heading}</h1>
<p>{task['same_brief_task']}</p><p><strong>Decision question:</strong> {task['effect_pk_question']}</p><p><strong>Quality axes:</strong> {' · '.join(task['quality_axes'])}</p>
<p><code>{task['review_task_id']} · sha256:{task['pair_sha256']}</code></p><p class="boundary">{review_boundary}</p></header>
<div class="sides"><section class="side"><h2>LEFT</h2>{left}</section><section class="side"><h2>RIGHT</h2>{right}</section></div>
<form id="review"><label>Stable qualified-reviewer pseudonym<input required id="pseudonym" type="text" minlength="3" maxlength="120"></label>
<fieldset><legend>Stronger final delivery</legend><label><input required type="radio" name="choice" value="left"> LEFT</label><label><input required type="radio" name="choice" value="right"> RIGHT</label><label><input required type="radio" name="choice" value="abstain"> ABSTAIN</label></fieldset>
<h2>Mandatory quality-axis decisions</h2><p>Judge every frozen axis independently. Per-axis ties are allowed.</p>{axis_rows}
<div class="sides"><fieldset><legend>LEFT delivery status</legend><label><input required type="radio" name="left_pub" value="yes"> directly publishable</label><label><input required type="radio" name="left_pub" value="no"> not publishable</label><br><label><input required type="radio" name="left_rework" value="yes"> major rework</label><label><input required type="radio" name="left_rework" value="no"> no major rework</label></fieldset><fieldset><legend>RIGHT delivery status</legend><label><input required type="radio" name="right_pub" value="yes"> directly publishable</label><label><input required type="radio" name="right_pub" value="no"> not publishable</label><br><label><input required type="radio" name="right_rework" value="yes"> major rework</label><label><input required type="radio" name="right_rework" value="no"> no major rework</label></fieldset></div>
<fieldset><legend>Blocking defect</legend><label><input required type="radio" name="defect" value="none"> NONE</label><label><input required type="radio" name="defect" value="left"> LEFT</label><label><input required type="radio" name="defect" value="right"> RIGHT</label><label><input required type="radio" name="defect" value="both"> BOTH</label></fieldset>
<label>Located blocking-defect reason (required unless none)<textarea id="defect_reason" maxlength="1200"></textarea></label><label>Located rationale (24–2000 characters)<textarea required id="rationale" minlength="24" maxlength="2000"></textarea></label>
<label><input required id="attest" type="checkbox"> I reviewed independently without private mapping, another review, outside identity research, or model-judge substitution.</label><p><button type="submit">Download immutable review JSON</button></p><p id="status">Nothing transmitted.</p></form>
<script id="task" type="application/json">{encoded}</script><script>
const task=JSON.parse(document.getElementById("task").textContent),stable=v=>Array.isArray(v)?`[${{v.map(stable).join(",")}}]`:v&&typeof v==="object"?`{{${{Object.keys(v).sort().map(k=>`${{JSON.stringify(k)}}:${{stable(v[k])}}`).join(",")}}}}`:JSON.stringify(v),hex=async v=>Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(stable(v)))),b=>b.toString(16).padStart(2,"0")).join(""),checked=n=>document.querySelector(`input[name="${{n}}"]:checked`)?.value;
{text_loader}
document.getElementById("review").onsubmit=async e=>{{e.preventDefault();try{{const pseudonym=document.getElementById("pseudonym").value.trim(),choice=checked("choice"),lp=checked("left_pub"),lr=checked("left_rework"),rp=checked("right_pub"),rr=checked("right_rework"),defect=checked("defect"),reason=document.getElementById("defect_reason").value.trim(),rationale=document.getElementById("rationale").value.trim(),axisWinners=Object.fromEntries(task.quality_axes.map((axis,index)=>[axis,checked(`axis_${{index}}`)]));if(pseudonym.length<3||!choice||!lp||!lr||!rp||!rr||!defect||Object.values(axisWinners).some(value=>!value)||rationale.length<24||!document.getElementById("attest").checked||(defect!=="none"&&reason.length<16))throw Error("Complete every quality axis, field, attestation, and located rationale.");const leftPub=lp==="yes",leftMajor=lr==="yes",rightPub=rp==="yes",rightMajor=rr==="yes";if((leftPub&&leftMajor)||(rightPub&&rightMajor))throw Error("A side cannot be directly publishable and require major rework.");const review={{schema:{json.dumps(REVIEW_SCHEMA)},review_task_id:task.review_task_id,comparison_id:task.comparison_id,pair_sha256:task.pair_sha256,reviewer_slot:task.reviewer_slot,reviewer_pseudonym:pseudonym,human_attestation:{json.dumps(REVIEW_ATTESTATION)},choice,axis_winners:axisWinners,left_directly_publishable:leftPub,right_directly_publishable:rightPub,left_major_rework:leftMajor,right_major_rework:rightMajor,blocking_defect_side:defect,blocking_defect_reason:reason,rationale,reviewed_at:new Date().toISOString()}};review.review_content_sha256=await hex(review);const blob=new Blob([JSON.stringify(review,null,2)+"\\n"],{{type:"application/json"}}),a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`named-product-pk-review-slot-${{task.reviewer_slot}}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);document.getElementById("status").textContent=`Local review exported · sha256:${{review.review_content_sha256}} · no promotion occurred.`}}catch(error){{document.getElementById("status").textContent="Blocked: "+error.message}}}};
</script></main></body></html>'''


def _zip_reviewer_kit(
    *, output: Path, task: Mapping[str, Any], left_source: Path, right_source: Path
) -> tuple[Path, str, int]:
    slot = int(task["reviewer_slot"])
    target = output / "offline-kits" / f"reviewer-{slot:02d}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    left_asset = {**task["left_asset"], "offline_path": f"assets/{task['left_asset']['alias']}"}
    right_asset = {**task["right_asset"], "offline_path": f"assets/{task['right_asset']['alias']}"}
    if task["left_asset"]["extension"] in {".json", ".md", ".txt", ".csv"}:
        left_asset["inline_text"] = left_source.read_text(encoding="utf-8")
    if task["right_asset"]["extension"] in {".json", ".md", ".txt", ".csv"}:
        right_asset["inline_text"] = right_source.read_text(encoding="utf-8")
    members = {
        "review.html": _review_html({
            **task,
            "left_asset": left_asset,
            "right_asset": right_asset,
        }).encode("utf-8"),
        "task.json": (json.dumps(task, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        f"assets/{task['left_asset']['alias']}": left_source.read_bytes(),
        f"assets/{task['right_asset']['alias']}": right_source.read_bytes(),
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, body in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, body)
    return target, sha256_file(target), target.stat().st_size


def compile_named_product_blind_packet(
    *,
    project_root: Path,
    capture_manifest_path: Path,
    ledger_path: Path,
    challenger_admission_path: Path,
    baseline_store_root: Path,
    capture_slot_id: str,
    preparation_path: Path,
    baseline_review_path: Path,
    candidate_review_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    if not _SLOT_ID.fullmatch(capture_slot_id):
        raise NamedProductPKError("capture slot ID is invalid")
    manifest = validate_kit_manifest(
        _load_json(capture_manifest_path), kit_root=capture_manifest_path.parent
    )
    ledger = _validate_ledger(_load_json(ledger_path))
    if manifest.get("source_ledger_sha256") != ledger["content_sha256"]:
        raise NamedProductPKError("capture kit and product-effect ledger are not bound")
    try:
        challenger_admission = validate_challenger_admission(
            _load_json(challenger_admission_path),
            ledger=ledger,
            project_root=project_root,
        )
    except ChallengerDossierError as error:
        raise NamedProductPKError(str(error)) from error
    capture, baseline_source_path, slot = _stored_capture(
        manifest=manifest,
        baseline_store_root=baseline_store_root,
        capture_slot_id=capture_slot_id,
    )
    candidate_row = next(
        row for row in ledger["product_pk_rows"]
        if row["category_id"] == capture["category_id"]
        and row["reference_product"] == capture["reference_product"]
    )
    try:
        candidate_source_path = admitted_dossier_for_category(
            challenger_admission,
            category_id=capture["category_id"],
            project_root=project_root,
        )
    except ChallengerDossierError as error:
        raise NamedProductPKError(str(error)) from error
    if baseline_review_path.is_symlink() or candidate_review_path.is_symlink():
        raise NamedProductPKError("symlinked review artifacts are not admitted")
    baseline_review_path = baseline_review_path.resolve(strict=True)
    candidate_review_path = candidate_review_path.resolve(strict=True)
    prep = validate_preparation(
        _load_json(preparation_path),
        manifest=manifest,
        ledger=ledger,
        challenger_admission=challenger_admission,
        capture=capture,
        baseline_source_path=baseline_source_path,
        baseline_review_path=baseline_review_path,
        candidate_source_path=candidate_source_path,
        candidate_review_path=candidate_review_path,
        project_root=project_root,
    )
    output = output_root.resolve()
    if output.exists() and any(output.iterdir()):
        raise NamedProductPKConflictError("named-product PK packet output must be empty")
    public = output / "public"
    private = output / "private"
    assets = public / "assets"
    assets.mkdir(parents=True, mode=0o700)
    private.mkdir(parents=True, mode=0o700)
    comparison_id = f"named-pk-{secrets.token_hex(12)}"
    baseline_alias = f"blind-{secrets.token_hex(12)}{baseline_review_path.suffix.casefold()}"
    candidate_alias = f"blind-{secrets.token_hex(12)}{candidate_review_path.suffix.casefold()}"
    atomic_write_bytes(assets / baseline_alias, baseline_review_path.read_bytes())
    atomic_write_bytes(assets / candidate_alias, candidate_review_path.read_bytes())
    baseline_public = {**_artifact_metadata(assets / baseline_alias), "alias": baseline_alias}
    candidate_public = {**_artifact_metadata(assets / candidate_alias), "alias": candidate_alias}
    randomizer = secrets.SystemRandom()
    slots = list(range(1, 6))
    randomizer.shuffle(slots)
    left_candidate_count = 2 + secrets.randbelow(2)
    candidate_left_slots = set(slots[:left_candidate_count])
    tasks: list[dict[str, Any]] = []
    mappings: dict[str, dict[str, str]] = {}
    for reviewer_slot in range(1, 6):
        candidate_side = "left" if reviewer_slot in candidate_left_slots else "right"
        left = candidate_public if candidate_side == "left" else baseline_public
        right = baseline_public if candidate_side == "left" else candidate_public
        task_id = f"named-pk-task-{secrets.token_hex(10)}-reviewer-{reviewer_slot}"
        task: dict[str, Any] = {
            "comparison_id": comparison_id,
            "review_task_id": task_id,
            "reviewer_slot": reviewer_slot,
            "category_id": capture["category_id"],
            "frozen_brief_sha256": capture["frozen_brief_sha256"],
            "same_brief_task": candidate_row["same_brief_task"],
            "quality_axes": candidate_row["quality_axes"],
            "effect_pk_question": candidate_row["effect_pk_question"],
            "left_asset": left,
            "right_asset": right,
        }
        task["pair_sha256"] = _public_pair_hash(task)
        tasks.append(task)
        mappings[task_id] = {
            "left": "candidate" if candidate_side == "left" else "named_product_baseline",
            "right": "named_product_baseline" if candidate_side == "left" else "candidate",
        }
        left_display = {**left, "offline_path": f"assets/{left['alias']}"}
        right_display = {**right, "offline_path": f"assets/{right['alias']}"}
        if left["extension"] in {".json", ".md", ".txt", ".csv"}:
            left_display["inline_text"] = (assets / left["alias"]).read_text(encoding="utf-8")
        if right["extension"] in {".json", ".md", ".txt", ".csv"}:
            right_display["inline_text"] = (assets / right["alias"]).read_text(encoding="utf-8")
        atomic_write_text(public / f"reviewer-{reviewer_slot:02d}.html", _review_html({
            **task,
            "left_asset": left_display,
            "right_asset": right_display,
        }))
    files = {
        str(path.relative_to(public)): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in sorted(public.rglob("*")) if path.is_file()
    }
    public_packet = seal({
        "schema": PUBLIC_PACKET_SCHEMA,
        "comparison_id": comparison_id,
        "category_id": capture["category_id"],
        "reviewer_count": 5,
        "expected_review_count": 5,
        "submitted_review_count": 0,
        "review_tasks": tasks,
        "files": files,
        "source_roles_exposed": False,
        "intrinsic_style_may_be_recognizable": True,
        "private_mapping_included": False,
        "model_judge_can_promote": False,
        "automatic_pairing_enabled": False,
        "automatic_promotion_enabled": False,
        "automatic_external_actions": 0,
        "truth_boundary": (
            "This public packet contains five source-hidden, hash-bound same-brief review tasks. "
            "A named operator attested that identity removal preserved meaning and quality, but "
            "intrinsic style may remain recognizable. Empty review tasks prove no product victory."
        ),
    })
    public_path = public / "packet.json"
    atomic_write_text(public_path, json.dumps(public_packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    kits = []
    for task in tasks:
        left_source = assets / task["left_asset"]["alias"]
        right_source = assets / task["right_asset"]["alias"]
        kit_path, digest, size = _zip_reviewer_kit(
            output=output, task=task, left_source=left_source, right_source=right_source
        )
        kits.append({
            "reviewer_slot": task["reviewer_slot"],
            "path": str(kit_path.relative_to(output)),
            "sha256": digest,
            "bytes": size,
        })
    private_packet = seal({
        "schema": PRIVATE_PACKET_SCHEMA,
        "public_packet_sha256": sha256_file(public_path),
        "source_capture_kit_sha256": manifest["content_sha256"],
        "source_ledger_sha256": ledger["content_sha256"],
        "preparation_sha256": prep["content_sha256"],
        "capture_slot_id": capture_slot_id,
        "category_id": capture["category_id"],
        "reference_product": capture["reference_product"],
        "reference_product_url": capture["reference_product_url"],
        "provider_model_or_version": capture["provider_model_or_version"],
        "baseline_source_sha256": capture["artifact"]["sha256"],
        "candidate_source": prep["candidate_source"],
        "baseline_review_sha256": prep["baseline_review_artifact"]["sha256"],
        "candidate_review_sha256": prep["candidate_review_artifact"]["sha256"],
        "task_side_mapping": mappings,
        "randomized_left_right": True,
        "balanced_candidate_left_count": left_candidate_count,
        "randomization_seed_persisted": False,
        "reviewer_kits": kits,
        "automatic_promotion_enabled": False,
    })
    private_path = private / "mapping.json"
    atomic_write_text(private_path, json.dumps(private_packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    private_path.chmod(0o600)
    receipt = seal({
        "schema": "ProofLaunchNamedProductBlindPKPacketReceiptV1",
        "capture_slot_id": capture_slot_id,
        "category_id": capture["category_id"],
        "comparison_id": comparison_id,
        "public_packet_sha256": sha256_file(public_path),
        "private_packet_sha256": sha256_file(private_path),
        "reviewer_kit_count": 5,
        "expected_review_count": 5,
        "submitted_review_count": 0,
        "automatic_external_actions": 0,
        "truth_boundary": public_packet["truth_boundary"],
    })
    atomic_write_text(output / "packet-receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return receipt


def validate_public_packet(payload: object, *, public_root: Path) -> dict[str, Any]:
    packet = _verify_seal(payload, schema=PUBLIC_PACKET_SCHEMA, label="named-product public packet")
    tasks = packet.get("review_tasks")
    if (
        packet.get("reviewer_count") != 5
        or packet.get("expected_review_count") != 5
        or packet.get("submitted_review_count") != 0
        or not isinstance(tasks, list)
        or len(tasks) != 5
        or packet.get("source_roles_exposed") is not False
        or packet.get("private_mapping_included") is not False
        or packet.get("automatic_promotion_enabled") is not False
    ):
        raise NamedProductPKError("named-product public packet contract is incomplete")
    slots: set[int] = set()
    task_ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise NamedProductPKError("named-product review task is invalid")
        slot = task.get("reviewer_slot")
        task_id = task.get("review_task_id")
        if (
            type(slot) is not int or slot not in range(1, 6) or slot in slots
            or not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id) or task_id in task_ids
            or task.get("comparison_id") != packet.get("comparison_id")
            or task.get("pair_sha256") != _public_pair_hash(task)
        ):
            raise NamedProductPKError("named-product review task binding is invalid")
        slots.add(slot)
        task_ids.add(task_id)
    if slots != set(range(1, 6)):
        raise NamedProductPKError("named-product reviewer slots are incomplete")
    root = public_root.resolve(strict=True)
    for relative, metadata in packet.get("files", {}).items():
        path = (root / relative).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as error:
            raise NamedProductPKError("public packet file escaped its root") from error
        if path.is_symlink() or not path.is_file() or path.stat().st_size != metadata.get("bytes") or sha256_file(path) != metadata.get("sha256"):
            raise NamedProductPKError("public packet file integrity failed")
    return packet


def _validate_review(review: Mapping[str, Any], *, packet: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema", "review_task_id", "comparison_id", "pair_sha256", "reviewer_slot",
        "reviewer_pseudonym", "human_attestation", "choice", "axis_winners",
        "left_directly_publishable", "right_directly_publishable",
        "left_major_rework", "right_major_rework", "blocking_defect_side",
        "blocking_defect_reason", "rationale", "reviewed_at", "review_content_sha256",
    }
    if set(review) != required or review.get("schema") != REVIEW_SCHEMA:
        raise NamedProductPKError("named-product human review schema or fields are invalid")
    task = next(
        (item for item in packet["review_tasks"] if item["review_task_id"] == review.get("review_task_id")),
        None,
    )
    if task is None or any(review.get(key) != task.get(key) for key in ("comparison_id", "pair_sha256", "reviewer_slot")):
        raise NamedProductPKError("named-product review is not task-bound")
    if review.get("human_attestation") != REVIEW_ATTESTATION or review.get("choice") not in {"left", "right", "abstain"}:
        raise NamedProductPKError("named-product review decision or attestation is invalid")
    axis_winners = review.get("axis_winners")
    if (
        not isinstance(axis_winners, dict)
        or set(axis_winners) != set(task["quality_axes"])
        or any(value not in {"left", "right", "tie"} for value in axis_winners.values())
    ):
        raise NamedProductPKError(
            "every named-product quality axis requires a valid decision"
        )
    pseudonym = review.get("reviewer_pseudonym")
    rationale = review.get("rationale")
    if not isinstance(pseudonym, str) or not 3 <= len(pseudonym.strip()) <= 120:
        raise NamedProductPKError("reviewer pseudonym is invalid")
    if not isinstance(rationale, str) or not 24 <= len(rationale.strip()) <= 2000:
        raise NamedProductPKError("review rationale must contain 24 to 2000 characters")
    for side in ("left", "right"):
        publishable = review.get(f"{side}_directly_publishable")
        major = review.get(f"{side}_major_rework")
        if type(publishable) is not bool or type(major) is not bool or (publishable and major):
            raise NamedProductPKError("review delivery fields are inconsistent")
    defect = review.get("blocking_defect_side")
    reason = review.get("blocking_defect_reason")
    if defect not in {"none", "left", "right", "both"} or not isinstance(reason, str) or len(reason) > 1200:
        raise NamedProductPKError("review blocking-defect fields are invalid")
    if defect != "none" and len(reason.strip()) < 16:
        raise NamedProductPKError("a blocking defect requires a located reason")
    _validate_timestamp(review.get("reviewed_at"), label="review")
    supplied = review.get("review_content_sha256")
    unsigned = dict(review)
    unsigned.pop("review_content_sha256", None)
    if supplied != sha256_json(unsigned):
        raise NamedProductPKError("named-product review digest is invalid")
    return dict(review)


def _wilson_lower(successes: int, total: int, z: float = 1.959963984540054) -> float:
    if total <= 0:
        return 0.0
    p = successes / total
    denominator = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return (centre - margin) / denominator


class NamedProductPKReviewService:
    def __init__(self, *, packet_root: Path, store_root: Path) -> None:
        self.packet_root = packet_root.resolve(strict=True)
        self.public_path = self.packet_root / "public/packet.json"
        self.private_path = self.packet_root / "private/mapping.json"
        self.public = validate_public_packet(_load_json(self.public_path), public_root=self.public_path.parent)
        self.private = _verify_seal(
            _load_json(self.private_path), schema=PRIVATE_PACKET_SCHEMA, label="named-product private packet"
        )
        if self.private.get("public_packet_sha256") != sha256_file(self.public_path):
            raise NamedProductPKError("public and private named-product packets are not bound")
        expected_tasks = {task["review_task_id"] for task in self.public["review_tasks"]}
        if set(self.private.get("task_side_mapping", {})) != expected_tasks:
            raise NamedProductPKError("private task mapping coverage is invalid")
        self.store = store_root.resolve()
        self.store.mkdir(parents=True, exist_ok=True)
        self.aggregate_path = self.store / "aggregate.json"

    def _review_path(self, slot: int) -> Path:
        return self.store / f"reviewer-{slot:02d}.json"

    def _reviews(self) -> list[dict[str, Any]]:
        reviews = []
        for path in sorted(self.store.glob("reviewer-*.json")):
            review = _validate_review(_load_json(path), packet=self.public)
            if path != self._review_path(int(review["reviewer_slot"])):
                raise NamedProductPKError("persisted review path is not slot-bound")
            reviews.append(review)
        if len({row["reviewer_slot"] for row in reviews}) != len(reviews) or len(
            {row["reviewer_pseudonym"] for row in reviews}
        ) != len(reviews):
            raise NamedProductPKConflictError("reviewer slots or identities are duplicated")
        return reviews

    def submit(self, review_path: Path) -> dict[str, Any]:
        review = _validate_review(_load_json(review_path), packet=self.public)
        slot = int(review["reviewer_slot"])
        existing = self._reviews()
        if any(row["reviewer_pseudonym"] == review["reviewer_pseudonym"] and row["reviewer_slot"] != slot for row in existing):
            raise NamedProductPKConflictError("one reviewer pseudonym cannot occupy multiple slots")
        target = self._review_path(slot)
        if target.exists():
            if canonical_json_bytes(_load_json(target)) != canonical_json_bytes(review):
                raise NamedProductPKConflictError("named-product review is immutable")
            idempotent = True
        else:
            atomic_write_text(target, json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            target.chmod(0o600)
            idempotent = False
        status = self.status()
        if status["review_complete"]:
            self.aggregate()
        return {"schema": "ProofLaunchNamedProductBlindPKReviewReceiptV1", "idempotent": idempotent, **status}

    def _compute(self, reviews: list[dict[str, Any]]) -> dict[str, Any]:
        candidate_votes = publishable = major = defects = 0
        quality_axes = list(self.public["review_tasks"][0]["quality_axes"])
        axis_votes = {
            axis: {"candidate": 0, "named_product_baseline": 0, "tie": 0}
            for axis in quality_axes
        }
        for review in reviews:
            mapping = self.private["task_side_mapping"][review["review_task_id"]]
            candidate_side = next(side for side, role in mapping.items() if role == "candidate")
            if review["choice"] == candidate_side:
                candidate_votes += 1
            publishable += int(review[f"{candidate_side}_directly_publishable"])
            major += int(review[f"{candidate_side}_major_rework"])
            defects += int(review["blocking_defect_side"] in {candidate_side, "both"})
            for axis, side in review["axis_winners"].items():
                role = "tie" if side == "tie" else mapping[side]
                axis_votes[axis][role] += 1
        total = len(reviews)
        preference_rate = candidate_votes / total if total else 0.0
        publishable_rate = publishable / total if total else 0.0
        major_rate = major / total if total else 1.0
        wilson = _wilson_lower(candidate_votes, total)
        candidate_axis_losses = [
            axis
            for axis, votes in axis_votes.items()
            if votes["candidate"] < votes["named_product_baseline"]
        ]
        checks = {
            "five_distinct_reviewers": total == 5,
            "candidate_preference_rate_at_least_0_75": preference_rate >= 0.75,
            "candidate_wilson_lower_95_above_0_5": wilson > 0.5,
            "candidate_publishable_rate_at_least_0_95": publishable_rate >= 0.95,
            "candidate_major_rework_rate_at_most_0_05": major_rate <= 0.05,
            "candidate_blocking_defects_zero": defects == 0,
            "candidate_loses_no_declared_quality_axis": not candidate_axis_losses,
        }
        won = all(checks.values())
        return seal({
            "schema": AGGREGATE_SCHEMA,
            "public_packet_file_sha256": sha256_file(self.public_path),
            "private_packet_file_sha256": sha256_file(self.private_path),
            "source_capture_kit_sha256": self.private["source_capture_kit_sha256"],
            "source_ledger_sha256": self.private["source_ledger_sha256"],
            "preparation_sha256": self.private["preparation_sha256"],
            "baseline_source_sha256": self.private["baseline_source_sha256"],
            "candidate_source_sha256": self.private["candidate_source"]["sha256"],
            "baseline_review_sha256": self.private["baseline_review_sha256"],
            "candidate_review_sha256": self.private["candidate_review_sha256"],
            "capture_slot_id": self.private["capture_slot_id"],
            "category_id": self.private["category_id"],
            "reference_product": self.private["reference_product"],
            "provider_model_or_version": self.private["provider_model_or_version"],
            "comparison_id": self.public["comparison_id"],
            "review_complete": total == 5,
            "review_count": total,
            "distinct_reviewer_count": len({row["reviewer_pseudonym"] for row in reviews}),
            "candidate_preference_votes": candidate_votes,
            "candidate_preference_rate": round(preference_rate, 6),
            "candidate_preference_wilson_lower_95": round(wilson, 6),
            "candidate_publishable_rate": round(publishable_rate, 6),
            "candidate_major_rework_rate": round(major_rate, 6),
            "candidate_blocking_defect_count": defects,
            "quality_axis_votes": axis_votes,
            "candidate_quality_axis_losses": candidate_axis_losses,
            "gate_checks": checks,
            "named_product_pk_row_completed": total == 5,
            "candidate_won_same_brief_last_mile_pk": won,
            "effect_alignment_achieved": won,
            "automatic_runtime_switch_enabled": False,
            "automatic_publish_enabled": False,
            "automatic_send_enabled": False,
            "automatic_spend_enabled": False,
            "four_a_quality_proven": False,
            "causal_business_effect_proven": False,
            "review_bindings": sorted(
                ({"reviewer_slot": row["reviewer_slot"], "review_content_sha256": row["review_content_sha256"]} for row in reviews),
                key=lambda row: row["reviewer_slot"],
            ),
            "truth_boundary": (
                "This aggregate proves only the recorded source-hidden human preference against one "
                "authorized named-product output on one frozen brief. It does not automatically "
                "generalize to the whole product, 4A quality, publication, causal lift, or revenue."
            ),
        })

    def aggregate(self) -> dict[str, Any]:
        reviews = self._reviews()
        if len(reviews) != 5 or {row["reviewer_slot"] for row in reviews} != set(range(1, 6)):
            raise NamedProductPKConflictError("named-product aggregate requires all five reviewer slots")
        aggregate = self._compute(reviews)
        if self.aggregate_path.exists():
            if canonical_json_bytes(_load_json(self.aggregate_path)) != canonical_json_bytes(aggregate):
                raise NamedProductPKConflictError("named-product aggregate drifted after sealing")
        else:
            atomic_write_text(self.aggregate_path, json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            self.aggregate_path.chmod(0o600)
        return aggregate

    def status(self) -> dict[str, Any]:
        reviews = self._reviews()
        complete = len(reviews) == 5 and {row["reviewer_slot"] for row in reviews} == set(range(1, 6))
        aggregate = self._compute(reviews) if complete else None
        return {
            "capture_slot_id": self.private["capture_slot_id"],
            "expected_review_count": 5,
            "submitted_review_count": len(reviews),
            "remaining_review_count": 5 - len(reviews),
            "review_complete": complete,
            "candidate_won_same_brief_last_mile_pk": bool(aggregate and aggregate["candidate_won_same_brief_last_mile_pk"]),
            "automatic_external_actions": 0,
        }


def compile_named_product_pk_portfolio(
    *, capture_manifest_path: Path, ledger_path: Path, aggregate_root: Path
) -> dict[str, Any]:
    manifest = validate_kit_manifest(
        _load_json(capture_manifest_path), kit_root=capture_manifest_path.parent
    )
    ledger = _validate_ledger(_load_json(ledger_path))
    slot_index = {slot["capture_slot_id"]: slot for slot in manifest["capture_slots"]}
    aggregates: list[dict[str, Any]] = []
    if aggregate_root.exists():
        for path in sorted(aggregate_root.glob("pk-*/aggregate.json")):
            aggregate = _verify_seal(_load_json(path), schema=AGGREGATE_SCHEMA, label="named-product aggregate")
            slot = slot_index.get(aggregate.get("capture_slot_id"))
            if slot is None or aggregate.get("category_id") != slot.get("category_id") or aggregate.get("reference_product") != slot.get("reference_product"):
                raise NamedProductPKError("named-product aggregate does not match its capture slot")
            if path.parent.name != aggregate["capture_slot_id"]:
                raise NamedProductPKError("named-product aggregate path is not slot-bound")
            checks = aggregate.get("gate_checks")
            won = aggregate.get("candidate_won_same_brief_last_mile_pk")
            if (
                aggregate.get("source_capture_kit_sha256") != manifest["content_sha256"]
                or aggregate.get("source_ledger_sha256") != ledger["content_sha256"]
                or any(not _DIGEST.fullmatch(str(aggregate.get(key, ""))) for key in (
                    "public_packet_file_sha256", "private_packet_file_sha256", "preparation_sha256",
                    "baseline_source_sha256", "candidate_source_sha256", "baseline_review_sha256",
                    "candidate_review_sha256",
                ))
                or aggregate.get("review_complete") is not True
                or aggregate.get("review_count") != 5
                or aggregate.get("distinct_reviewer_count") != 5
                or aggregate.get("named_product_pk_row_completed") is not True
                or not isinstance(checks, dict)
                or set(checks) != {
                    "five_distinct_reviewers",
                    "candidate_preference_rate_at_least_0_75",
                    "candidate_wilson_lower_95_above_0_5",
                    "candidate_publishable_rate_at_least_0_95",
                    "candidate_major_rework_rate_at_most_0_05",
                    "candidate_blocking_defects_zero",
                    "candidate_loses_no_declared_quality_axis",
                }
                or type(won) is not bool
                or won != all(checks.values())
                or aggregate.get("effect_alignment_achieved") is not won
                or aggregate.get("automatic_runtime_switch_enabled") is not False
                or aggregate.get("automatic_publish_enabled") is not False
                or aggregate.get("automatic_send_enabled") is not False
                or aggregate.get("automatic_spend_enabled") is not False
                or aggregate.get("four_a_quality_proven") is not False
                or aggregate.get("causal_business_effect_proven") is not False
            ):
                raise NamedProductPKError("named-product aggregate contract is inconsistent")
            aggregates.append(aggregate)
    if len({row["capture_slot_id"] for row in aggregates}) != len(aggregates):
        raise NamedProductPKError("named-product aggregate slot is duplicated")
    categories = []
    for category in ledger["categories"]:
        category_id = category["category_id"]
        rows = [row for row in aggregates if row["category_id"] == category_id]
        completed = sum(1 for row in rows if row["named_product_pk_row_completed"])
        won = sum(1 for row in rows if row["candidate_won_same_brief_last_mile_pk"])
        categories.append({
            "category_id": category_id,
            "reference_product_count": 10,
            "completed_product_pk_rows": completed,
            "candidate_won_product_pk_rows": won,
            "remaining_product_pk_rows": 10 - completed,
            "category_named_product_last_mile_alignment_achieved": completed == 10 and won == 10,
        })
    completed_total = sum(row["completed_product_pk_rows"] for row in categories)
    won_total = sum(row["candidate_won_product_pk_rows"] for row in categories)
    aligned_categories = sum(1 for row in categories if row["category_named_product_last_mile_alignment_achieved"])
    return seal({
        "schema": PORTFOLIO_SCHEMA,
        "source_capture_kit_sha256": manifest["content_sha256"],
        "source_ledger_sha256": ledger["content_sha256"],
        "category_count": 13,
        "reference_product_row_count": 130,
        "completed_product_pk_rows": completed_total,
        "candidate_won_product_pk_rows": won_total,
        "remaining_product_pk_rows": 130 - completed_total,
        "effect_aligned_category_count": aligned_categories,
        "categories": categories,
        "named_product_last_mile_alignment_achieved": completed_total == 130 and won_total == 130 and aligned_categories == 13,
        "automatic_runtime_switch_enabled": False,
        "automatic_strategy_mutation_enabled": False,
        "automatic_publish_enabled": False,
        "four_a_quality_proven": False,
        "causal_business_effect_proven": False,
        "truth_boundary": (
            "A category aligns only when the candidate passes all ten authorized named-product "
            "same-brief human PK rows. Global alignment requires 130/130 wins. Even that is scoped "
            "human preference evidence, not automatic 4A, publication, causal lift, or revenue proof."
        ),
    })
