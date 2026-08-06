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

from prooflaunch_remix.files import atomic_write_text, sha256_file  # noqa: E402
from prooflaunch_remix.gtm_platform_craft_review import (  # noqa: E402
    DIMENSIONS,
    HUMAN_ATTESTATION,
    build_platform_craft_review_bundle,
    verify_platform_craft_review_bundle,
)


DEFAULT_ROOT = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v1"
DEFAULT_AUDIT = ROOT / "evidence/v10/gtm-platform-native-publication-audit-v2.json"
DEFAULT_OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-v1"


def _inside_project(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return path


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


def _html(slot: int, public_packet: dict[str, Any]) -> str:
    tasks = [
        task for task in public_packet["review_tasks"] if task["reviewer_slot"] == slot
    ]
    state = {
        "reviewer_slot": slot,
        "artifacts": public_packet["artifacts"],
        "tasks": tasks,
        "dimensions": list(DIMENSIONS),
        "human_attestation": HUMAN_ATTESTATION,
    }
    encoded = json.dumps(state, ensure_ascii=False).replace("<", "\\u003c")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProofLaunch platform craft review · reviewer {slot:02d}</title>
<style>
:root{{font-family:Inter,ui-sans-serif,system-ui;color:#172033;background:#f3f5f8}}body{{margin:0}}main{{max-width:1180px;margin:auto;padding:28px}}header,.card{{background:#fff;border:1px solid #dfe4ec;border-radius:16px;padding:22px;margin-bottom:20px;box-shadow:0 8px 30px #1720330d}}h1{{margin-top:0}}code{{overflow-wrap:anywhere}}.artifact{{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(310px,.75fr);gap:22px}}.copy{{background:#f7f9fc;border-radius:12px;padding:16px}}.copy p,.copy li{{line-height:1.55}}fieldset{{border:1px solid #dfe4ec;border-radius:10px;margin:12px 0;padding:12px}}label{{display:block;margin:8px 0}}select,input,textarea{{font:inherit}}select{{min-width:76px}}textarea{{width:100%;min-height:84px;box-sizing:border-box}}.sticky{{position:sticky;bottom:0;background:#172033;color:#fff;padding:16px;border-radius:14px}}button{{font:inherit;font-weight:700;padding:12px 18px;border:0;border-radius:9px;background:#7df0c4;color:#10251d}}@media(max-width:800px){{.artifact{{grid-template-columns:1fr}}}}
</style></head><body><main>
<header><h1>Source-hidden platform craft review</h1><p>Reviewer slot {slot:02d} · 13 hash-bound artifacts. Provider, model, private mapping and other reviews are hidden.</p>
<label>Stable reviewer pseudonym <input id="reviewer" minlength="3" maxlength="120" required></label>
<label><input id="independent" type="checkbox"> I reviewed independently without provider, model, private mapping or other-reviewer information.</label>
<label><input id="conflict" type="checkbox"> I disclosed conflicts and have no undisclosed conflict.</label></header>
<section id="artifacts"></section>
<div class="sticky"><button id="export" type="button">Validate 13 reviews and download JSONL</button> <span id="status" aria-live="polite">Nothing submitted.</span></div>
<script id="state" type="application/json">{encoded}</script>
<script>
const state=JSON.parse(document.getElementById('state').textContent),root=document.getElementById('artifacts');
const esc=v=>String(v).replace(/[&<>\"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
const blocks=v=>Array.isArray(v)?`<ol>${{v.map(x=>`<li>${{esc(x)}}</li>`).join('')}}</ol>`:`<p>${{esc(v)}}</p>`;
const radio=(name,yes,no)=>`<label><input required type="radio" name="${{name}}" value="true"> ${{yes}}</label><label><input required type="radio" name="${{name}}" value="false"> ${{no}}</label>`;
state.artifacts.forEach((a,i)=>{{const card=document.createElement('article');card.className='card';card.dataset.id=a.blind_artifact_id;let scores='';for(const d of state.dimensions)scores+=`<label>${{d.replaceAll('_',' ')}} <select data-score="${{d}}" required><option value="">—</option>${{[1,2,3,4,5].map(n=>`<option>${{n}}</option>`).join('')}}</select></label>`;card.innerHTML=`<h2>${{i+1}}. ${{esc(a.surface_id)}}</h2><p><code>${{a.blind_artifact_id}} · sha256:${{a.artifact_sha256}}</code></p><div class="artifact"><div class="copy"><p><strong>Native contract:</strong> ${{esc(a.native_format_contract)}}</p><p><strong>Audience:</strong> ${{esc(a.review_context.audience)}}</p><p><strong>Problem:</strong> ${{esc(a.review_context.problem)}}</p><h3>${{esc(a.artifact.hook)}}</h3>${{blocks(a.artifact.progression)}}${{blocks(a.artifact.body)}}<p><strong>CTA:</strong> ${{esc(a.artifact.cta)}}</p><p><strong>Participation:</strong> ${{esc(a.artifact.participation_mechanism)}}</p><p><strong>Proof:</strong> ${{esc(a.artifact.proof_integration)}}</p><p><strong>Falsifier:</strong> ${{esc(a.artifact.falsifier)}}</p></div><div><fieldset><legend>1–5 craft scores</legend>${{scores}}</fieldset><fieldset><legend>Directly publishable?</legend>${{radio('publishable-'+i,'Yes','No')}}</fieldset><fieldset><legend>Major rework?</legend>${{radio('major-'+i,'Yes','No')}}</fieldset><fieldset><legend>Blocking defect?</legend>${{radio('blocker-'+i,'Yes','No')}}</fieldset><label>Located blocker reason (required if yes)<textarea data-blocker maxlength="1200"></textarea></label><label>Independent rationale (40–2400 chars)<textarea data-rationale minlength="40" maxlength="2400" required></textarea></label></div></div>`;root.append(card)}});
const selected=n=>document.querySelector(`input[name="${{n}}"]:checked`)?.value;
const stable=v=>Array.isArray(v)?`[${{v.map(stable).join(',')}}]`:v&&typeof v==='object'?`{{${{Object.keys(v).sort().map(k=>`${{JSON.stringify(k)}}:${{stable(v[k])}}`).join(',')}}}}`:JSON.stringify(v);
const sha=async v=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(stable(v)))),b=>b.toString(16).padStart(2,'0')).join('');
const download=(name,body)=>{{const blob=new Blob([body],{{type:'application/x-ndjson'}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}};
document.getElementById('export').onclick=async()=>{{try{{const reviewer=document.getElementById('reviewer').value.trim();if(reviewer.length<3||!document.getElementById('independent').checked||!document.getElementById('conflict').checked)throw Error('Provide reviewer pseudonym and both attestations.');const now=new Date().toISOString(),rows=[];for(let i=0;i<state.artifacts.length;i++){{const a=state.artifacts[i],task=state.tasks.find(t=>t.blind_artifact_id===a.blind_artifact_id),card=document.querySelector(`[data-id="${{a.blind_artifact_id}}"]`),scores={{}};for(const d of state.dimensions){{const value=card.querySelector(`[data-score="${{d}}"]`).value;if(!value)throw Error(`Score every dimension for artifact ${{i+1}}.`);scores[d]=Number(value)}}const pub=selected('publishable-'+i),major=selected('major-'+i),blocker=selected('blocker-'+i),reason=card.querySelector('[data-blocker]').value.trim(),rationale=card.querySelector('[data-rationale]').value.trim();if(pub===undefined||major===undefined||blocker===undefined||rationale.length<40||(blocker==='true'&&reason.length<16))throw Error(`Complete delivery verdicts and located rationale for artifact ${{i+1}}.`);if(pub==='true'&&major==='true')throw Error(`Artifact ${{i+1}} cannot be publishable and major-rework.`);const row={{schema:task.schema,review_task_id:task.review_task_id,blind_artifact_id:task.blind_artifact_id,artifact_sha256:task.artifact_sha256,reviewer_slot:state.reviewer_slot,reviewer_pseudonym:reviewer,human_attestation:state.human_attestation,conflict_disclosed:true,dimension_scores:scores,directly_publishable:pub==='true',major_rework:major==='true',blocking_defect:blocker==='true',blocking_defect_reason:reason,rationale,reviewed_at:now}};row.review_content_sha256=await sha(row);rows.push(row)}}download(`prooflaunch-platform-craft-reviewer-${{String(state.reviewer_slot).padStart(2,'0')}}.jsonl`,rows.map(x=>JSON.stringify(x)).join('\n')+'\n');document.getElementById('status').textContent='13 local hash-bound rows downloaded. Nothing transmitted or promoted.'}}catch(error){{document.getElementById('status').textContent='Blocked: '+error.message}}}};
</script></main></body></html>'''


def _write_public_zip(public_root: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(public_root.rglob("*")):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo(
                str(path.relative_to(public_root)), date_time=(1980, 1, 1, 0, 0, 0)
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def export(
    *,
    plan_path: Path,
    receipt_path: Path,
    audit_path: Path,
    output: Path,
) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise SystemExit("output directory must be empty")
    public_root = output / "public"
    private_root = output / "private"
    public_root.mkdir(parents=True, mode=0o700)
    private_root.mkdir(parents=True, mode=0o700)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    bundle = build_platform_craft_review_bundle(
        plan=plan,
        receipt=receipt,
        publication_audit=audit,
        randomization_secret=secrets.token_urlsafe(48),
    )
    public_packet = bundle["public_packet"]
    private_mapping = bundle["private_mapping"]
    verify_platform_craft_review_bundle(public_packet, private_mapping)
    public_packet_path = public_root / "platform-craft-review-public.json"
    private_mapping_path = private_root / "platform-craft-review-private.json"
    atomic_write_text(
        public_packet_path,
        json.dumps(public_packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    atomic_write_text(
        private_mapping_path,
        json.dumps(private_mapping, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    private_mapping_path.chmod(0o600)
    for slot in range(1, 6):
        atomic_write_text(public_root / f"reviewer-{slot:02d}.html", _html(slot, public_packet))
    atomic_write_text(
        public_root / "README.md",
        "# ProofLaunch platform craft review kit V1\n\nOpen only your assigned `reviewer-XX.html`. "
        "Review all 13 artifacts independently and return the downloaded JSONL. The public package "
        "contains no private source mapping and performs no network submission, promotion, publication, send or spend.\n",
    )
    inventory = {
        str(path.relative_to(public_root)): {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(public_root.rglob("*"))
        if path.is_file()
    }
    manifest = _seal(
        {
            "schema": "ProofLaunchPlatformCraftOfflineKitManifestV1",
            "public_packet_sha256": public_packet["content_sha256"],
            "private_mapping_commitment": private_mapping["content_sha256"],
            "reviewer_page_count": 5,
            "artifact_count_per_reviewer": 13,
            "expected_human_review_count": 65,
            "submitted_human_review_count": 0,
            "files": inventory,
            "private_mapping_included_in_public_package": False,
            "randomization_secret_persisted": False,
            "network_submission_enabled": False,
            "automatic_scoring_enabled": False,
            "automatic_publish_enabled": False,
            "truth_boundary": (
                "This kit makes sixty-five source-hidden craft reviews executable but records no human result. "
                "It proves no named-product preference, 4A status, organic breakout, conversion or revenue."
            ),
        }
    )
    atomic_write_text(
        public_root / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    archive = output / "prooflaunch-platform-craft-review-kit-v1.zip"
    _write_public_zip(public_root, archive)
    receipt_payload = _seal(
        {
            "schema": "ProofLaunchPlatformCraftOfflineKitExportReceiptV1",
            "public_packet_sha256": public_packet["content_sha256"],
            "private_mapping_sha256": sha256_file(private_mapping_path),
            "archive": {
                "path": str(archive.relative_to(ROOT)),
                "sha256": sha256_file(archive),
                "bytes": archive.stat().st_size,
            },
            "reviewer_page_count": 5,
            "expected_human_review_count": 65,
            "submitted_human_review_count": 0,
            "network_calls": 0,
            "automatic_external_actions": 0,
        }
    )
    atomic_write_text(
        output / "export-receipt.json",
        json.dumps(receipt_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return receipt_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=_inside_project, default=DEFAULT_ROOT / "b2b-plan.json")
    parser.add_argument(
        "--receipt",
        type=_inside_project,
        default=DEFAULT_ROOT / "b2b-publication-repaired-receipt.json",
    )
    parser.add_argument("--audit", type=_inside_project, default=DEFAULT_AUDIT)
    parser.add_argument("--output-dir", type=_inside_project, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = export(
        plan_path=args.plan,
        receipt_path=args.receipt,
        audit_path=args.audit,
        output=args.output_dir,
    )
    print(
        json.dumps(
            {
                "archive": result["archive"],
                "reviewer_pages": 5,
                "expected_reviews": 65,
                "submitted_reviews": 0,
                "content_sha256": result["content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
