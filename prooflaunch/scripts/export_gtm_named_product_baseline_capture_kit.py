#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import zipfile
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_bytes, atomic_write_text, sha256_file
from prooflaunch_remix.gtm_named_product_baseline import KIT_SCHEMA, canonical_json_bytes


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
DEFAULT_OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1"
SHARED_INPUTS = (
    "artifacts/run-bound-multimodal-demo-v1/gtm-cockpit.json",
    "artifacts/run-bound-multimodal-demo-v1/demo-receipt.json",
    "artifacts/run-bound-multimodal-demo-v1/production-deliverables/gtm-strategy.json",
    "artifacts/run-bound-multimodal-demo-v1/production-deliverables/big-idea-and-message-hierarchy.json",
    "evidence/v10/prooflaunch-front-stage-brief-v1.json",
)
DOCUMENT_EXTENSIONS = [".json", ".md", ".txt", ".html", ".pdf", ".zip"]
CATEGORY_MEDIA = {
    "image_generation_editing": ([".png", ".jpg", ".jpeg", ".webp", ".html", ".pdf", ".zip"], 300_000_000),
    "video_generation_production": ([".mp4", ".mov", ".webm", ".html", ".pdf", ".zip"], 1_500_000_000),
    "audio_voice_music": ([".wav", ".mp3", ".flac", ".m4a", ".html", ".pdf", ".zip"], 500_000_000),
}


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(payload)
    sealed["content_sha256"] = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return sealed


def _verify_ledger(payload: dict[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if (
        payload.get("schema") != "ProofLaunchConcreteProductEffectPKLedgerV1"
        or payload.get("category_count") != 13
        or payload.get("reference_product_row_count") != 130
        or hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest() != supplied
    ):
        raise SystemExit("product/effect PK ledger failed closed")


def _slot_id(category_id: str, product: str) -> str:
    digest = hashlib.sha256(f"{category_id}\0{product}".encode("utf-8")).hexdigest()
    return f"pk-{digest[:16]}"


def _brief(category: dict[str, Any], shared: list[dict[str, Any]]) -> dict[str, Any]:
    category_id = category["category_id"]
    extensions, maximum = CATEGORY_MEDIA.get(category_id, (DOCUMENT_EXTENSIONS, 50_000_000))
    return _seal(
        {
            "schema": "ProofLaunchNamedProductFrozenBriefV1",
            "category_id": category_id,
            "task": category["same_brief_task"],
            "effect_pk_question": category["effect_pk_question"],
            "quality_axes": category["quality_axes"],
            "shared_inputs": shared,
            "execution_protocol": {
                "use_exact_shared_inputs": True,
                "use_product_default_or_recommended_quality_mode": True,
                "record_product_model_and_version": True,
                "retain_original_export_without_post_editing": True,
                "one_product_run_per_capture": True,
                "external_publication_or_activation": False,
            },
            "artifact_contract": {
                "allowed_extensions": extensions,
                "maximum_artifact_bytes": maximum,
                "original_product_export_required": True,
                "self_contained_html_or_pdf_dossier_allowed_for_multi_asset_outputs": True,
                "hash_before_review": "sha256",
            },
            "truth_boundary": (
                "The same brief controls inputs and task intent. Product defaults may differ and must be "
                "recorded; this brief does not claim identical hidden inference settings."
            ),
        }
    )


def _capture_html(category: dict[str, Any], slots: list[dict[str, Any]], brief: dict[str, Any]) -> str:
    state = json.dumps(
        {"category": category, "slots": slots, "brief": brief},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProofLaunch named-product baseline capture · {html.escape(category["category_id"])}</title>
<style>:root{{--ink:#eff4ff;--muted:#a9b4cc;--panel:#10172b;--line:#334061;--accent:#8b72ff;--warn:#f5c76f}}*{{box-sizing:border-box}}body{{margin:0;background:#070b16;color:var(--ink);font:15px/1.5 system-ui,sans-serif}}main{{max-width:1180px;margin:auto;padding:28px}}header,.brief,.capture{{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:22px;margin-bottom:20px}}h1,h2{{line-height:1.15}}.boundary{{border-left:4px solid var(--warn);padding:12px;background:#151525;color:var(--muted)}}label{{display:block;margin:13px 0}}input,select{{width:100%;padding:11px;border:1px solid var(--line);border-radius:8px;background:#080d1b;color:var(--ink)}}input[type=checkbox]{{width:auto;margin-right:8px}}button{{padding:13px 18px;background:var(--accent);border:0;border-radius:9px;color:white;font-weight:800}}code{{color:#cbbfff;word-break:break-all}}a{{color:#b8a9ff}}</style></head><body><main>
<header><p><a href="index.html">← all categories</a></p><h1>{html.escape(category["category_id"].replace("_", " ").title())}</h1><p>{html.escape(category["effect_pk_question"])}</p><p class="boundary">A capture is not a win. This page makes local receipts only; it never calls a product, uploads a file, publishes, spends, starts review, or declares a winner.</p></header>
<section class="brief"><h2>Frozen same-brief protocol</h2><p>{html.escape(category["same_brief_task"])}</p><p>Brief SHA-256: <code>{brief["content_sha256"]}</code></p><p>Quality axes: {html.escape(" · ".join(category["quality_axes"]))}</p><p>Use every file in <code>shared-inputs/</code>, preserve the original product export, and record the actual provider/model/version.</p></section>
<section class="capture"><h2>Bind one authorized product output</h2><label>Reference product<select id="product"></select></label><label>Provider / model / version<input id="version" maxlength="240" placeholder="Exact displayed product, model, plan or build"></label><label>Named operator ID<input id="operator" maxlength="120" placeholder="Stable reviewer/operator identity"></label><label>Acquisition method<select id="method"><option value="authorized_product_use">Authorized product use</option><option value="user_owned_export">User-owned export</option><option value="official_public_demo">Official public demo with retention permission</option></select></label><label>Original artifact<input id="artifact" type="file"></label>
<label><input id="rights" type="checkbox">I am authorized to evaluate and retain this output.</label><label><input id="same" type="checkbox">I used the frozen brief and did not hide post-editing.</label><label><input id="versionTruth" type="checkbox">I recorded the provider/model/version truthfully.</label>
<button id="export" type="button">Validate and download capture receipt</button><p id="status" aria-live="polite">No baseline captured.</p></section>
<script id="state" type="application/json">{state}</script><script>
const state=JSON.parse(document.getElementById("state").textContent),sel=document.getElementById("product");for(const slot of state.slots){{const o=document.createElement("option");o.value=slot.capture_slot_id;o.textContent=slot.reference_product;sel.append(o)}}
const stable=v=>Array.isArray(v)?`[${{v.map(stable).join(",")}}]`:v&&typeof v==="object"?`{{${{Object.keys(v).sort().map(k=>`${{JSON.stringify(k)}}:${{stable(v[k])}}`).join(",")}}}}`:JSON.stringify(v);const hex=async bytes=>Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),b=>b.toString(16).padStart(2,"0")).join("");const download=(name,body)=>{{const blob=new Blob([body],{{type:"application/json"}}),a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}};
document.getElementById("export").onclick=async()=>{{try{{const slot=state.slots.find(v=>v.capture_slot_id===sel.value),file=document.getElementById("artifact").files[0],version=document.getElementById("version").value.trim(),operator=document.getElementById("operator").value.trim();if(!file||!version||operator.length<3)throw Error("Select an original artifact and provide version plus named operator.");const ext="."+file.name.split(".").pop().toLowerCase();if(!slot.allowed_extensions.includes(ext)||file.size<1||file.size>slot.maximum_artifact_bytes)throw Error("Artifact extension or size violates the frozen contract.");if(!document.getElementById("rights").checked||!document.getElementById("same").checked||!document.getElementById("versionTruth").checked)throw Error("All three attestations are required.");const receipt={{schema:"ProofLaunchNamedProductBaselineCaptureV1",capture_slot_id:slot.capture_slot_id,category_id:slot.category_id,reference_product:slot.reference_product,reference_product_url:slot.reference_product_url,frozen_brief_sha256:slot.frozen_brief_sha256,operator_id:operator,captured_at:new Date().toISOString(),provider_model_or_version:version,acquisition_method:document.getElementById("method").value,rights_attestation:{{authorized_to_evaluate_and_retain:true,same_frozen_brief_without_hidden_editing:true,provider_and_version_recorded_truthfully:true}},artifact:{{name:file.name,mime_type:file.type||"application/octet-stream",bytes:file.size,sha256:await hex(await file.arrayBuffer())}}}};receipt.content_sha256=await hex(new TextEncoder().encode(stable(receipt)));download(`${{slot.capture_slot_id}}-capture.json`,JSON.stringify(receipt,null,2)+"\\n");document.getElementById("status").textContent="Receipt downloaded. Keep it beside the unchanged original artifact for guarded import."}}catch(error){{document.getElementById("status").textContent="Blocked: "+error.message}}}};
</script></main></body></html>'''


def _index_html(categories: list[dict[str, Any]]) -> str:
    cards = "".join(
        f'<li><a href="category-{index:02d}.html"><strong>{html.escape(category["category_id"].replace("_", " ").title())}</strong><span>10 named products · 0 captured</span></a></li>'
        for index, category in enumerate(categories, 1)
    )
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ProofLaunch named-product PK capture</title><style>body{{margin:0;background:#070b16;color:#edf3ff;font:16px/1.5 system-ui,sans-serif}}main{{max-width:1100px;margin:auto;padding:36px}}.boundary{{border-left:4px solid #f5c76f;padding:14px;background:#12182a}}ul{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;padding:0;list-style:none}}a{{display:flex;flex-direction:column;gap:7px;padding:20px;border:1px solid #334061;border-radius:15px;background:#10172b;color:#edf3ff;text-decoration:none}}span{{color:#a9b4cc}}</style></head><body><main><h1>Named-product same-brief capture</h1><p>13 categories · 130 independent product slots · frozen input hashes · local-only receipts.</p><p class="boundary">A capture is not a win. Five qualified identity-hidden reviews and every predeclared gate remain required.</p><ul>{cards}</ul></main></body></html>'''


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
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    _verify_ledger(ledger)
    inputs_root = output / "shared-inputs"
    inputs_root.mkdir(mode=0o700)
    shared: list[dict[str, Any]] = []
    for index, relative in enumerate(SHARED_INPUTS, 1):
        source = ROOT / relative
        target = inputs_root / f"{index:02d}-{source.name}"
        atomic_write_bytes(target, source.read_bytes())
        shared.append({"path": str(target.relative_to(output)), "source_path": relative, "bytes": target.stat().st_size, "sha256": sha256_file(target)})
    rows_by_category: dict[str, list[dict[str, Any]]] = {}
    for row in ledger["product_pk_rows"]:
        rows_by_category.setdefault(row["category_id"], []).append(row)
    slots: list[dict[str, Any]] = []
    briefs: list[dict[str, Any]] = []
    for index, category in enumerate(ledger["categories"], 1):
        brief = _brief(category, shared)
        brief_path = output / f"brief-{index:02d}-{category['category_id']}.json"
        atomic_write_text(brief_path, json.dumps(brief, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        extensions = brief["artifact_contract"]["allowed_extensions"]
        maximum = brief["artifact_contract"]["maximum_artifact_bytes"]
        category_slots = []
        for row in rows_by_category[category["category_id"]]:
            slot = {
                "capture_slot_id": _slot_id(row["category_id"], row["reference_product"]),
                "category_id": row["category_id"],
                "reference_product": row["reference_product"],
                "reference_product_url": row["reference_product_url"],
                "reference_capability": row["reference_capability"],
                "frozen_brief_path": str(brief_path.relative_to(output)),
                "frozen_brief_sha256": brief["content_sha256"],
                "allowed_extensions": extensions,
                "maximum_artifact_bytes": maximum,
                "status": "awaiting_authorized_baseline",
            }
            slots.append(slot)
            category_slots.append(slot)
        atomic_write_text(output / f"category-{index:02d}.html", _capture_html(category, category_slots, brief))
        briefs.append({"category_id": category["category_id"], "path": str(brief_path.relative_to(output)), "sha256": sha256_file(brief_path)})
    atomic_write_text(output / "index.html", _index_html(ledger["categories"]))
    atomic_write_text(output / "README.md", "# ProofLaunch named-product baseline capture kit\n\nOpen `index.html`, choose one category, run the exact frozen brief in a product you are authorized to use, and export a local receipt beside the unchanged original output. Import with `scripts/import_gtm_named_product_baseline.py`. Capturing a baseline does not start review or prove a win.\n")
    files = {
        str(path.relative_to(output)): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in sorted(output.rglob("*")) if path.is_file()
    }
    manifest = _seal(
        {
            "schema": KIT_SCHEMA,
            "source_ledger_sha256": ledger["content_sha256"],
            "category_count": 13,
            "capture_slot_count": 130,
            "authorized_baseline_count": 0,
            "capture_slots": slots,
            "frozen_briefs": briefs,
            "shared_inputs": shared,
            "files": files,
            "network_submission_enabled": False,
            "automatic_product_execution_enabled": False,
            "automatic_pairing_enabled": False,
            "automatic_pk_promotion_enabled": False,
            "human_review_required": True,
            "truth_boundary": "This kit makes 130 rights-attested same-brief baseline captures executable. Empty slots and exported receipt templates are not product outputs, human observations, 4A proof or effect evidence.",
        }
    )
    manifest_path = output / "manifest.json"
    atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    archive = output / "prooflaunch-named-product-baseline-capture-kit-v1.zip"
    _write_zip(output, archive)
    receipt = _seal(
        {
            "schema": "ProofLaunchNamedProductBaselineCaptureKitExportReceiptV1",
            "manifest_sha256": sha256_file(manifest_path),
            "archive": {"path": str(archive.relative_to(ROOT)), "sha256": sha256_file(archive), "bytes": archive.stat().st_size},
            "category_count": 13,
            "capture_slot_count": 130,
            "authorized_baseline_count": 0,
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
    receipt = export(Path(args.output_dir).expanduser().resolve())
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
