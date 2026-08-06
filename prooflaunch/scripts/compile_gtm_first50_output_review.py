#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_first50_output_review import (  # noqa: E402
    HUMAN_ATTESTATION,
    compile_first50_level1_seed_manifest,
    compile_first50_codex_prereview,
    compile_first50_output_review_queue,
    compile_named_human_read_receipt,
)


PORTFOLIO = ROOT / "evidence/v10/gtm-codex-lighthouse-portfolio-v1.json"
QUALITY = ROOT / "evidence/v10/gtm-codex-lighthouse-quality-audit-v1.json"
OUTPUT_DIR = ROOT / "artifacts/gtm-first-50-human-read-v1"
QUEUE_OUTPUT = ROOT / "evidence/v10/gtm-first-50-output-review-queue-v1.json"
SEEDS_OUTPUT = ROOT / "evidence/v10/gtm-first-50-level1-seeds-v1.json"
PREREVIEW_OUTPUT = ROOT / "evidence/v10/gtm-first-50-codex-prereview-v1.json"
RECEIPT_OUTPUT = ROOT / "evidence/v10/gtm-first-50-named-human-read-receipt-v1.json"


def _page(queue: dict) -> str:
    embedded = json.dumps(queue, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    options = "".join(
        f'<option value="{html.escape(row["bucket_id"])}">{html.escape(row["bucket_id"])}</option>'
        for row in queue["allowed_failure_buckets"]
    )
    attestation = html.escape(HUMAN_ATTESTATION)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProofLaunch First 50 — Named Human Read</title>
<style>
:root{{--ink:#111827;--muted:#667085;--line:#d0d5dd;--panel:#fff;--bg:#f4f6f8;--accent:#5b3df5;--good:#067647;--warn:#b54708}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}}
header{{position:sticky;top:0;z-index:4;background:rgba(255,255,255,.96);border-bottom:1px solid var(--line);padding:16px 24px;backdrop-filter:blur(12px)}}
h1{{font-size:20px;margin:0 0 4px}} .sub,.meta{{color:var(--muted)}} main{{max-width:1180px;margin:24px auto;padding:0 18px 100px}}
.identity,.card{{background:var(--panel);border:1px solid var(--line);border-radius:16px;box-shadow:0 6px 22px rgba(16,24,40,.05)}}
.identity{{padding:18px;margin-bottom:18px;display:grid;grid-template-columns:1fr 1fr;gap:12px}} label{{display:block;font-weight:650}}
input,select,textarea{{width:100%;margin-top:6px;border:1px solid var(--line);border-radius:9px;padding:10px;background:#fff;color:var(--ink)}}
textarea{{min-height:86px;resize:vertical}} .attest{{grid-column:1/-1;font-weight:500;background:#f8f7ff;padding:12px;border-radius:10px}}
.progress{{height:8px;background:#eaecf0;border-radius:999px;overflow:hidden;margin-top:10px}} .bar{{height:100%;width:0;background:var(--accent)}}
.card{{padding:20px;margin:16px 0}} .card h2{{font-size:17px;margin:0 0 8px}} .tags{{display:flex;gap:7px;flex-wrap:wrap;margin:8px 0 14px}}
.tag{{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:3px 8px;background:#f9fafb}} pre{{white-space:pre-wrap;word-break:break-word;background:#101828;color:#f9fafb;padding:16px;border-radius:11px;max-height:430px;overflow:auto;font-size:12px}}
.checks{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0}} .checks label{{border:1px solid var(--line);padding:10px;border-radius:9px;font-weight:500}}
.checks input{{width:auto;margin:0 7px 0 0}} .grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.machine{{color:var(--good);font-size:13px}} .boundary{{color:var(--warn);font-weight:650}} footer{{position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid var(--line);padding:12px 18px;display:flex;justify-content:center;gap:12px}}
button{{border:0;border-radius:10px;padding:11px 18px;font-weight:700;cursor:pointer}} .primary{{background:var(--accent);color:#fff}} .secondary{{background:#eef2f6;color:var(--ink)}}
@media(max-width:760px){{.identity,.grid,.checks{{grid-template-columns:1fr}}}}
</style></head><body>
<header><h1>First 50 Output Read</h1><div class="sub">One named human · 50 frozen outputs · machine preflight is non-authoritative</div><div class="progress"><div class="bar" id="bar"></div></div><div class="meta" id="progressText">0 / 50 complete</div></header>
<main><section class="identity"><label>Reviewer legal/display name<input id="reviewerName" autocomplete="name"></label><label>Reviewer work email<input id="reviewerEmail" type="email" autocomplete="email"></label><label class="attest"><input id="attestation" type="checkbox" style="width:auto;margin-right:8px">{attestation}</label></section><div class="boundary">This console does not claim T073 complete until all 50 located judgments are sealed by the compiler.</div><div id="cards"></div></main>
<footer><button class="secondary" id="save">Save locally</button><button class="primary" id="download">Download review submission</button></footer>
<script id="queue" type="application/json">{embedded}</script><script>
const queue=JSON.parse(document.getElementById('queue').textContent); const key='prooflaunch-first50-'+queue.content_sha256; const state=JSON.parse(localStorage.getItem(key)||'{{"reviews":{{}}}}');
const esc=s=>String(s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
document.getElementById('reviewerName').value=state.reviewer_name||''; document.getElementById('reviewerEmail').value=state.reviewer_email||'';
function card(row,i){{const r=state.reviews[row.output_id]||{{}}; return `<section class="card" data-id="${{esc(row.output_id)}}"><h2>${{i+1}}. ${{esc(row.artifact_kind)}} · ${{esc(row.selector.industry_archetype)}}</h2><div class="tags"><span class="tag">${{esc(row.selector.business_model)}}</span><span class="tag">${{esc(row.selector.lifecycle)}}</span><span class="tag">${{esc(row.selector.budget)}}</span><span class="tag">${{esc(row.surface||'campaign')}}</span><span class="tag">${{esc(row.artifact_sha256.slice(0,12))}}</span></div><div class="machine">Level-1 mechanical preflight: PASS · does not count as human quality</div><pre>${{esc(JSON.stringify(row.artifact_payload,null,2))}}</pre><div class="checks"><label><input type="checkbox" data-f="direct_publishable" ${{r.direct_publishable?'checked':''}}>Directly publishable</label><label><input type="checkbox" data-f="major_rework" ${{r.major_rework?'checked':''}}>Major rework</label><label><input type="checkbox" data-f="blocking_defect" ${{r.blocking_defect?'checked':''}}>Blocking defect</label></div><div class="grid"><label>Primary observed bucket<select data-f="failure_bucket"><option value="">Select…</option><option value="no_material_failure">no_material_failure</option>{options}</select></label><label>Exact evidence span<input data-f="evidence_span" value="${{esc(r.evidence_span||'')}}" placeholder="Quote or locate the observed phrase/field"></label></div><label>Written reason<textarea data-f="written_reason" placeholder="Why this is or is not publishable; minimum 20 characters">${{esc(r.written_reason||'')}}</textarea></label></section>`}}
document.getElementById('cards').innerHTML=queue.outputs.map(card).join(''); document.querySelectorAll('.card').forEach(el=>{{const r=state.reviews[el.dataset.id]||{{}}; const sel=el.querySelector('[data-f=failure_bucket]'); if(r.failure_bucket)sel.value=r.failure_bucket; el.addEventListener('input',()=>{{const out={{}}; el.querySelectorAll('[data-f]').forEach(x=>out[x.dataset.f]=x.type==='checkbox'?x.checked:x.value.trim()); state.reviews[el.dataset.id]=out; update();}})}});
function complete(r){{return typeof r.direct_publishable==='boolean'&&typeof r.major_rework==='boolean'&&typeof r.blocking_defect==='boolean'&&r.failure_bucket&&String(r.evidence_span||'').length>=3&&String(r.written_reason||'').length>=20}}
function update(){{state.reviewer_name=document.getElementById('reviewerName').value.trim();state.reviewer_email=document.getElementById('reviewerEmail').value.trim();const n=queue.outputs.filter(x=>complete(state.reviews[x.output_id]||{{}})).length;document.getElementById('bar').style.width=(n/50*100)+'%';document.getElementById('progressText').textContent=n+' / 50 complete';}}
document.getElementById('reviewerName').addEventListener('input',update);document.getElementById('reviewerEmail').addEventListener('input',update);document.getElementById('save').onclick=()=>{{update();localStorage.setItem(key,JSON.stringify(state));alert('Saved in this browser.');}};
document.getElementById('download').onclick=()=>{{update();const reviews=queue.outputs.map(x=>Object.assign({{output_id:x.output_id}},state.reviews[x.output_id]||{{}}));if(!state.reviewer_name||!state.reviewer_email||!document.getElementById('attestation').checked||!reviews.every(complete)){{alert('Complete identity, attestation and all 50 located reviews first.');return}}const payload={{schema:'ProofLaunchFirst50HumanReadSubmissionV1',source_queue_sha256:queue.content_sha256,reviewer_name:state.reviewer_name,reviewer_email:state.reviewer_email,attestation:{json.dumps(HUMAN_ATTESTATION)},reviews}};const blob=new Blob([JSON.stringify(payload,null,2)+'\\n'],{{type:'application/json'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='gtm-first-50-human-read-submission.json';a.click();URL.revokeObjectURL(a.href)}}; update();
</script></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile the frozen first-50 human-read queue.")
    parser.add_argument("--submission", type=Path, help="Optional completed human submission to validate and seal.")
    args = parser.parse_args()
    portfolio = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    quality = json.loads(QUALITY.read_text(encoding="utf-8"))
    queue = compile_first50_output_review_queue(portfolio, quality)
    seeds = compile_first50_level1_seed_manifest(queue)
    prereview = compile_first50_codex_prereview(queue)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(QUEUE_OUTPUT, json.dumps(queue, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(SEEDS_OUTPUT, json.dumps(seeds, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(PREREVIEW_OUTPUT, json.dumps(prereview, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(OUTPUT_DIR / "index.html", _page(queue))
    result = {
        "queue": str(QUEUE_OUTPUT),
        "queue_sha256": queue["content_sha256"],
        "output_count": queue["output_count"],
        "machine_preflight_pass_count": queue["machine_preflight_pass_count"],
        "named_human_read_count": queue["named_human_read_count"],
        "level1_seed_manifest": str(SEEDS_OUTPUT),
        "level1_seed_count": seeds["seed_case_count"],
        "ci_admitted_seed_count": seeds["ci_admitted_case_count"],
        "codex_prereview": str(PREREVIEW_OUTPUT),
        "codex_prereview_sha256": prereview["content_sha256"],
        "codex_prereview_finding_count": prereview["finding_count"],
        "codex_prereview_bucket_count": prereview["observed_primary_bucket_count"],
        "review_console": str(OUTPUT_DIR / "index.html"),
    }
    if args.submission:
        submission = json.loads(args.submission.read_text(encoding="utf-8"))
        receipt = compile_named_human_read_receipt(queue, submission)
        atomic_write_text(RECEIPT_OUTPUT, json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        result.update(
            {
                "receipt": str(RECEIPT_OUTPUT),
                "receipt_sha256": receipt["content_sha256"],
                "t073_complete": receipt["t073_complete"],
            }
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
