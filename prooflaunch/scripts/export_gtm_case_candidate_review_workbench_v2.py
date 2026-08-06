#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_case_candidate_binding_v2 import (
    GATES,
    verify_case_candidate_binding_packets,
)
from prooflaunch_remix.gtm_case_candidate_review_workbench_v2 import (
    INTAKE_SCHEMA,
    REQUIRED_FIELD_BINDINGS,
    SIX_COST_COMPONENTS,
    packet_digest,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "artifacts/gtm-case-candidate-review-workbench-v2"


def _json_for_script(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _build_html(payload: dict) -> str:
    packet_rows = []
    for packet in payload["records"]:
        row = dict(packet)
        row["packet_sha256"] = packet_digest(packet)
        packet_rows.append(row)
    embedded = {
        "schema": "ProofLaunchGTMCaseCandidateReviewWorkbenchV2",
        "binding_packet_set_sha256": payload["content_sha256"],
        "packet_count": len(packet_rows),
        "gates": list(GATES),
        "required_fields": list(REQUIRED_FIELD_BINDINGS),
        "cost_components": list(SIX_COST_COMPONENTS),
        "records": packet_rows,
        "truth_boundary": (
            "A saved or exported review remains zero-credit intake. It cannot admit a candidate, satisfy a 200-case "
            "quota, establish a causal result, publish content or authorize spend."
        ),
    }
    data = _json_for_script(embedded)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProofLaunch · Source-bound case review</title>
<style>
:root{{--ink:#151513;--muted:#716f68;--paper:#f5f1e8;--card:#fffdf8;--line:#d9d2c4;--red:#b53326;--green:#176b4d;--amber:#9b6412;--blue:#274d83;--shadow:0 18px 45px rgba(42,35,23,.08)}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}}button,input,select,textarea{{font:inherit}}button{{cursor:pointer}}header{{position:sticky;top:0;z-index:5;background:rgba(245,241,232,.94);backdrop-filter:blur(18px);border-bottom:1px solid var(--line)}}
.top{{max-width:1500px;margin:auto;padding:18px 24px;display:grid;grid-template-columns:1fr auto;gap:20px;align-items:end}}.eyebrow{{font:700 11px/1.2 ui-monospace,monospace;letter-spacing:.16em;text-transform:uppercase;color:var(--red)}}h1{{font:600 clamp(25px,3vw,44px)/1.02 Georgia,serif;margin:5px 0}}.boundary{{max-width:780px;color:var(--muted)}}.metrics{{display:flex;gap:10px;flex-wrap:wrap;justify-content:flex-end}}.metric{{min-width:108px;padding:10px 12px;border:1px solid var(--line);background:var(--card);border-radius:10px}}.metric b{{display:block;font-size:20px}}.metric span{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}}
.shell{{max-width:1500px;margin:auto;padding:20px 24px 60px;display:grid;grid-template-columns:360px minmax(0,1fr);gap:18px}}.panel{{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}}.sidebar{{position:sticky;top:124px;height:calc(100vh - 146px);display:flex;flex-direction:column;overflow:hidden}}.filters{{padding:14px;border-bottom:1px solid var(--line);display:grid;gap:9px}}input,select,textarea{{width:100%;border:1px solid var(--line);background:#fff;padding:9px 10px;border-radius:8px;color:var(--ink)}}textarea{{min-height:90px;resize:vertical}}.queue{{overflow:auto}}.queue button{{width:100%;text-align:left;border:0;border-bottom:1px solid #ebe5d9;background:transparent;padding:13px 14px}}.queue button:hover,.queue button.active{{background:#f1eadc}}.queue strong{{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.queue small{{display:flex;gap:8px;margin-top:4px;color:var(--muted)}}.dot{{width:8px;height:8px;border-radius:50%;background:#aaa;display:inline-block}}.dot.saved{{background:var(--amber)}}.dot.submitted{{background:var(--green)}}
.main{{padding:22px}}.record-head{{display:flex;justify-content:space-between;gap:20px;border-bottom:1px solid var(--line);padding-bottom:18px}}.record-head h2{{font:600 31px/1.1 Georgia,serif;margin:4px 0}}.score{{font:700 28px/1 ui-monospace,monospace;color:var(--blue)}}.chips{{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}}.chip{{padding:4px 8px;border-radius:999px;background:#eee8dc;font-size:11px}}.chip.gap{{background:#fae5df;color:#8e261c}}.source{{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;margin:18px 0;padding:14px;border:1px solid var(--line);border-radius:10px}}.source code{{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted)}}a.btn,button.primary,button.secondary{{display:inline-flex;align-items:center;justify-content:center;padding:9px 13px;border-radius:8px;text-decoration:none;font-weight:700}}a.btn,button.primary{{background:var(--ink);color:white;border:1px solid var(--ink)}}button.secondary{{background:transparent;color:var(--ink);border:1px solid var(--line)}}
.section{{padding:18px 0;border-top:1px solid var(--line)}}.section:first-of-type{{border-top:0}}.section h3{{margin:0 0 12px;font-size:14px;text-transform:uppercase;letter-spacing:.08em}}.fragments{{display:grid;gap:8px}}.fragment{{padding:10px 12px;background:#f4efe5;border-left:3px solid var(--blue);border-radius:5px}}.fragment small{{display:block;color:var(--muted);margin-top:5px}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}label span{{display:block;font-size:11px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.06em;margin-bottom:5px}}.checks{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}.check{{display:flex;align-items:flex-start;gap:8px;padding:8px;border:1px solid var(--line);border-radius:8px}}.check input{{width:auto;margin-top:3px}}.check span{{font:12px/1.35 ui-monospace,monospace;text-transform:none;letter-spacing:0;color:var(--ink);margin:0}}.actions{{position:sticky;bottom:0;background:rgba(255,253,248,.96);border-top:1px solid var(--line);margin:18px -22px -22px;padding:14px 22px;display:flex;gap:8px;align-items:center}}.actions .spacer{{flex:1}}.notice{{padding:11px 13px;background:#fff3d8;border:1px solid #e8c984;border-radius:8px;color:#704a0c;font-size:12px}}.empty{{padding:40px;color:var(--muted)}}
@media(max-width:900px){{.top{{grid-template-columns:1fr}}.metrics{{justify-content:flex-start}}.shell{{grid-template-columns:1fr}}.sidebar{{position:relative;top:auto;height:420px}}.grid,.checks{{grid-template-columns:1fr}}}}
</style></head><body>
<header><div class="top"><div><div class="eyebrow">CaseCandidateV2 / evidence binding room</div><h1>Inspect the source. Bind the claim. Mint nothing.</h1><div class="boundary">{len(packet_rows)} public leads are queued for named human inspection. This workbench makes the hard evidence gaps visible; it never converts a directory label or plausible excerpt into quota credit.</div></div><div class="metrics"><div class="metric"><b id="packet-count">0</b><span>packets</span></div><div class="metric"><b id="saved-count">0</b><span>saved</span></div><div class="metric"><b id="submit-count">0</b><span>gate submissions</span></div><div class="metric"><b>0</b><span>quota credit</span></div></div></div></header>
<div class="shell"><aside class="panel sidebar"><div class="filters"><input id="reviewer" placeholder="Named reviewer (required)"><input id="search" placeholder="Search company, title, URL"><select id="status"><option value="all">All machine states</option><option value="ready">Ready for human binding</option><option value="gap">Evidence gap</option></select><select id="subvertical"><option value="all">All routed subverticals</option></select></div><div id="queue" class="queue"></div></aside><main id="main" class="panel main"></main></div>
<script id="workbench-data" type="application/json">{data}</script>
<script>
const WB=JSON.parse(document.getElementById('workbench-data').textContent);const key='prooflaunch-case-review:'+WB.binding_packet_set_sha256;let drafts=JSON.parse(localStorage.getItem(key)||'{{}}');let current=null;
const q=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const fieldLabel=s=>s.replaceAll('_',' '); const val=(id)=>q('#'+id)?.value.trim()||'';
const iso=()=>new Date().toISOString(); async function sha(s){{const b=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s));return [...new Uint8Array(b)].map(x=>x.toString(16).padStart(2,'0')).join('')}}
function init(){{q('#packet-count').textContent=WB.packet_count;const subs=[...new Set(WB.records.flatMap(r=>r.proposed_fields.subvertical_ids.value||[]))].sort();q('#subvertical').innerHTML+=[...subs].map(s=>`<option value="${{esc(s)}}">${{esc(s)}}</option>`).join('');q('#reviewer').value=localStorage.getItem(key+':reviewer')||'';['search','status','subvertical'].forEach(id=>q('#'+id).addEventListener('input',renderQueue));q('#reviewer').addEventListener('input',e=>localStorage.setItem(key+':reviewer',e.target.value));renderQueue();select(WB.records[0]?.packet_id)}}
function filtered(){{const term=q('#search').value.toLowerCase(),status=q('#status').value,sub=q('#subvertical').value;return WB.records.filter(r=>(!term||JSON.stringify([r.packet_id,r.source_url,r.proposed_fields.company.value,r.proposed_fields.campaign_or_motion.value]).toLowerCase().includes(term))&&(status==='all'||(status==='ready')===r.machine_ready_for_human_binding)&&(sub==='all'||(r.proposed_fields.subvertical_ids.value||[]).includes(sub)))}}
function renderQueue(){{const rows=filtered();q('#queue').innerHTML=rows.length?rows.map(r=>{{const d=drafts[r.packet_id],state=d?.decision==='submit_for_admission_gate'?'submitted':d?'saved':'';return `<button data-id="${{r.packet_id}}" class="${{current===r.packet_id?'active':''}}"><strong><i class="dot ${{state}}"></i> ${{esc(r.proposed_fields.company.value||r.packet_id)}}</strong><small><span>${{r.review_priority_score}} score</span><span>${{r.claim_surface_status}}</span></small></button>`}}).join(''):'<div class="empty">No packets match these filters.</div>';q('#queue').querySelectorAll('button').forEach(b=>b.onclick=()=>select(b.dataset.id));updateMetrics()}}
function select(id){{current=id;renderQueue();const r=WB.records.find(x=>x.packet_id===id);if(!r){{q('#main').innerHTML='<div class="empty">Select a packet.</div>';return}}const d=drafts[id]||{{}};const proposed=r.proposed_fields;const frag=Object.entries(r.claim_fragments).flatMap(([cat,rows])=>rows.map(x=>`<div class="fragment"><b>${{esc(cat)}}</b> · ${{esc(x.bounded_exact_excerpt)}}<small>SHA ${{esc(x.excerpt_sha256)}}</small></div>`)).join('')||'<div class="notice">No bounded claim fragments were captured. Keep the evidence gates false.</div>';const fields=WB.required_fields.map(name=>`<label><span>${{fieldLabel(name)}}</span><input id="field-${{name}}" value="${{esc(d.field_bindings?.[name]??(name==='mechanism_summary'?'':proposed[name]?.value||''))}}"></label>`).join('');const costs=WB.cost_components.map(name=>`<label><span>${{name}} cost evidence</span><input id="cost-${{name}}" value="${{esc(d.cost_components?.[name]||'')}}" placeholder="Exact source-bound evidence or explicit unknown"></label>`).join('');const gates=WB.gates.map(name=>`<label class="check"><input type="checkbox" id="gate-${{name}}" ${{d.gate_decisions?.[name]?'checked':''}}><span>${{name}}</span></label>`).join('');q('#main').innerHTML=`<div class="record-head"><div><div class="eyebrow">${{esc(r.packet_id)}}</div><h2>${{esc(proposed.company.value||'Identity unresolved')}}</h2><div class="chips"><span class="chip">${{r.machine_ready_for_human_binding?'human-binding priority':'evidence gap'}}</span>${{r.blocking_requirements.map(x=>`<span class="chip gap">${{esc(x)}}</span>`).join('')}}</div></div><div class="score">${{r.review_priority_score}}</div></div><div class="source"><div><b>Inspect the public source before entering judgment</b><code>${{esc(r.source_url)}}</code><small>${{esc(r.capture_receipt.capture_status)}} · ${{esc(r.capture_receipt.captured_at)}} · SHA ${{esc(r.capture_receipt.content_sha256)}}</small></div><a class="btn" href="${{esc(r.source_url)}}" target="_blank" rel="noopener noreferrer">Open source ↗</a></div><section class="section"><h3>Machine-bound exact fragments</h3><div class="fragments">${{frag}}</div></section><section class="section"><h3>Human field bindings</h3><div class="grid">${{fields}}</div></section><section class="section"><h3>Six-component budget evidence</h3><div class="grid">${{costs}}</div></section><section class="section"><h3>Exact claim bindings</h3><label><span>One per line: field TAB exact excerpt</span><textarea id="exact-bindings" placeholder="result_summary\tExact words copied from the inspected source">${{esc(d.exact_bindings_text||'')}}</textarea></label></section><section class="section"><h3>Explicit admission gates</h3><div class="checks">${{gates}}</div></section><section class="section"><div class="grid"><label><span>Decision</span><select id="decision"><option value="needs_more_evidence">Needs more evidence</option><option value="reject_episode">Reject episode</option><option value="submit_for_admission_gate">Submit for independent admission gate</option></select></label><label><span>Decision notes</span><textarea id="decision-notes" placeholder="State the observed evidence, conflicts, and unresolved risk.">${{esc(d.decision_notes||'')}}</textarea></label></div><label class="check"><input id="source-inspected" type="checkbox" ${{d.source_inspected?'checked':''}}><span>I personally opened and inspected the public source. This statement is attributable to the named reviewer.</span></label><div class="notice">Submitting here is not admission. Quota remains 0 until the separate CaseCandidateV2 gate rechecks identity, independence, deduplication and every marginal quota.</div></section><div class="actions"><button class="secondary" id="save">Save local draft</button><button class="secondary" id="clear">Clear this draft</button><span class="spacer"></span><button class="primary" id="export">Export reviewed intake</button></div>`;q('#decision').value=d.decision||'needs_more_evidence';q('#save').onclick=save;q('#clear').onclick=clearDraft;q('#export').onclick=exportIntake}}
function collect(){{const r=WB.records.find(x=>x.packet_id===current);return {{packet_id:r.packet_id,source_url:r.source_url,packet_sha256:r.packet_sha256,reviewer_name:q('#reviewer').value.trim(),reviewed_at:drafts[current]?.reviewed_at||iso(),source_inspected:q('#source-inspected').checked,field_bindings:Object.fromEntries(WB.required_fields.map(n=>[n,val('field-'+n)])),cost_components:Object.fromEntries(WB.cost_components.map(n=>[n,val('cost-'+n)])),gate_decisions:Object.fromEntries(WB.gates.map(n=>[n,q('#gate-'+n).checked])),exact_bindings_text:val('exact-bindings'),decision:q('#decision').value,decision_notes:val('decision-notes'),automatic_candidate_promotion_allowed:false,candidate_quota_credit:0}}}}
function save(){{const d=collect();if(!d.reviewer_name){{alert('Enter the named reviewer before saving.');return false}}drafts[current]=d;localStorage.setItem(key,JSON.stringify(drafts));renderQueue();updateMetrics();return true}}
function clearDraft(){{if(!confirm('Clear this local draft?'))return;delete drafts[current];localStorage.setItem(key,JSON.stringify(drafts));select(current)}}
function updateMetrics(){{const rows=Object.values(drafts);q('#saved-count').textContent=rows.length;q('#submit-count').textContent=rows.filter(x=>x.decision==='submit_for_admission_gate').length}}
async function exportIntake(){{if(!save())return;const records=[];for(const d of Object.values(drafts)){{if(!d.source_inspected)continue;const exact=[];for(const line of (d.exact_bindings_text||'').split('\\n').filter(Boolean)){{const [field,...rest]=line.split('\\t');const excerpt=rest.join('\\t').trim();if(field&&excerpt)exact.push({{field:field.trim(),source_url:d.source_url,exact_excerpt:excerpt,excerpt_sha256:await sha(excerpt)}})}}const out={{...d,exact_claim_bindings:exact}};delete out.exact_bindings_text;records.push(out)}}const payload={{schema:'{INTAKE_SCHEMA}',binding_packet_set_sha256:WB.binding_packet_set_sha256,created_at:iso(),review_count:records.length,records,automatic_candidate_promotion_allowed:false,candidate_quota_credit:0,truth_boundary:WB.truth_boundary}};const blob=new Blob([JSON.stringify(payload,null,2)+'\\n'],{{type:'application/json'}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='gtm-case-candidate-human-review-intake-v2.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}}
init();
</script></body></html>'''


def main() -> int:
    source = ROOT / "evidence/v10/gtm-case-candidate-binding-packets-v2.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    verify_case_candidate_binding_packets(payload)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    index = _build_html(payload)
    atomic_write_text(OUTPUT_DIR / "index.html", index)
    manifest = {
        "schema": "ProofLaunchGTMCaseCandidateReviewWorkbenchManifestV2",
        "binding_packet_set_sha256": payload["content_sha256"],
        "packet_count": payload["packet_count"],
        "machine_ready_for_human_binding_count": payload["status_counts"].get(
            "machine_ready_for_human_binding", 0
        ),
        "evidence_gap_count": payload["status_counts"].get("evidence_gap", 0),
        "observed_human_review_count": 0,
        "candidate_quota_credit": 0,
        "automatic_candidate_promotion_allowed": False,
        "index_sha256": hashlib.sha256(index.encode("utf-8")).hexdigest(),
        "import_command": (
            ".venv/bin/python scripts/import_gtm_case_candidate_reviews_v2.py "
            "<downloaded-intake.json> --output evidence/v10/gtm-case-candidate-human-review-receipt-v2.json"
        ),
        "truth_boundary": (
            "This offline workbench stages named, source-bound human intake. No human review is present at export, "
            "and neither a browser draft nor an imported receipt grants CaseCandidateV2 quota credit."
        ),
    }
    manifest["content_sha256"] = _digest(manifest)
    atomic_write_text(
        OUTPUT_DIR / "workbench-manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    readme = f"""# GTM case candidate review workbench V2

Open `index.html` locally. The queue contains {payload['packet_count']} source-bound packets: {manifest['machine_ready_for_human_binding_count']} prioritized for human binding and {manifest['evidence_gap_count']} explicit evidence gaps.

The reviewer must open the public source, bind every asserted field to inspected evidence, classify all six cost components, decide every admission gate, and export the intake. Browser state stays in local storage until export.

Validate and seal an exported intake with:

```bash
{manifest['import_command']}
```

The importer remains fail-closed. It rejects anonymous reviews, stale packet hashes, incomplete gate submissions, missing exact excerpts, and any attempt to mint quota or auto-promote a candidate. A valid receipt still carries `candidate_quota_credit: 0`; independent CaseCandidateV2 admission remains mandatory.
"""
    atomic_write_text(OUTPUT_DIR / "README.md", readme)
    print(json.dumps({
        "output_dir": str(OUTPUT_DIR),
        "packet_count": manifest["packet_count"],
        "machine_ready_for_human_binding_count": manifest["machine_ready_for_human_binding_count"],
        "evidence_gap_count": manifest["evidence_gap_count"],
        "observed_human_review_count": 0,
        "candidate_quota_credit": 0,
        "content_sha256": manifest["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
