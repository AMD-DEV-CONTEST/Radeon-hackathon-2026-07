#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_all_subvertical_unified_review_v2 import (
    INTAKE_SCHEMA,
    review_packet_digest,
    verify_unified_review_ledger,
)
from prooflaunch_remix.gtm_case_candidate_binding_v2 import GATES
from prooflaunch_remix.gtm_case_candidate_review_workbench_v2 import REQUIRED_FIELD_BINDINGS, SIX_COST_COMPONENTS


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json"
OUTPUT = ROOT / "artifacts/gtm-all-subvertical-review-workbench-v2"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _script_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _html(ledger: dict) -> str:
    records = [{**row, "review_packet_sha256": review_packet_digest(row)} for row in ledger["records"]]
    payload = {
        "schema": "ProofLaunchGTMAllSubverticalReviewWorkbenchV2",
        "review_ledger_sha256": ledger["content_sha256"],
        "packet_count": len(records),
        "ready_count": ledger["machine_ready_for_named_review_count"],
        "gap_count": ledger["evidence_gap_count"],
        "subvertical_count": ledger["represented_subvertical_count"],
        "gates": list(GATES),
        "required_fields": list(REQUIRED_FIELD_BINDINGS),
        "cost_components": list(SIX_COST_COMPONENTS),
        "records": records,
        "truth_boundary": ledger["truth_boundary"],
    }
    data = _script_json(payload)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProofLaunch · 81-subvertical review room</title><style>
:root{{--ink:#171714;--muted:#716f68;--paper:#f2eee5;--card:#fffdf8;--line:#d8d0c2;--red:#b52f24;--green:#166748;--blue:#244f87;--amber:#8a5a12}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.45 Inter,system-ui,sans-serif}}button,input,select,textarea{{font:inherit}}header{{position:sticky;top:0;z-index:8;background:rgba(242,238,229,.95);border-bottom:1px solid var(--line);backdrop-filter:blur(15px)}}.top{{max-width:1540px;margin:auto;padding:17px 22px;display:flex;gap:24px;justify-content:space-between;align-items:end}}.eyebrow{{color:var(--red);font:700 11px ui-monospace,monospace;letter-spacing:.15em;text-transform:uppercase}}h1{{font:600 clamp(25px,3vw,42px)/1 Georgia,serif;margin:5px 0}}.boundary{{max-width:840px;color:var(--muted)}}.metrics{{display:flex;gap:8px;flex-wrap:wrap}}.metric{{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:8px 11px;min-width:88px}}.metric b{{display:block;font-size:20px}}.metric small{{color:var(--muted);text-transform:uppercase}}.shell{{max-width:1540px;margin:auto;padding:18px 22px 60px;display:grid;grid-template-columns:380px minmax(0,1fr);gap:16px}}.panel{{background:var(--card);border:1px solid var(--line);border-radius:13px;box-shadow:0 15px 38px rgba(40,32,20,.07)}}aside{{position:sticky;top:116px;height:calc(100vh - 137px);overflow:hidden;display:flex;flex-direction:column}}.filters{{padding:13px;display:grid;grid-template-columns:1fr 1fr;gap:8px;border-bottom:1px solid var(--line)}}.filters .wide{{grid-column:1/-1}}input,select,textarea{{width:100%;padding:9px;border:1px solid var(--line);border-radius:7px;background:white}}textarea{{min-height:86px}}.queue{{overflow:auto}}.queue button{{width:100%;border:0;border-bottom:1px solid #ebe4d7;background:transparent;text-align:left;padding:11px 13px;cursor:pointer}}.queue button:hover,.queue button.active{{background:#f1e9db}}.queue strong{{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.queue small{{display:flex;gap:8px;color:var(--muted)}}.dot{{display:inline-block;width:8px;height:8px;border-radius:50%;background:#999}}.dot.ready{{background:var(--green)}}.dot.saved{{background:var(--amber)}}main{{padding:21px}}.head{{display:flex;justify-content:space-between;gap:15px;padding-bottom:15px;border-bottom:1px solid var(--line)}}h2{{font:600 30px/1.1 Georgia,serif;margin:4px 0}}.score{{font:700 28px ui-monospace,monospace;color:var(--blue)}}.chips{{display:flex;gap:6px;flex-wrap:wrap}}.chip{{font-size:11px;padding:4px 7px;border-radius:999px;background:#eee7da}}.chip.gap{{background:#f9dfda;color:#8b281e}}.source{{margin:15px 0;padding:13px;border:1px solid var(--line);border-radius:9px;display:grid;grid-template-columns:1fr auto;gap:10px}}.source code{{display:block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted)}}.btn,.primary,.secondary{{padding:9px 12px;border-radius:7px;font-weight:700;text-decoration:none;cursor:pointer}}.btn,.primary{{background:var(--ink);color:white;border:1px solid var(--ink)}}.secondary{{background:transparent;border:1px solid var(--line)}}section{{padding:15px 0;border-top:1px solid var(--line)}}section h3{{font-size:12px;text-transform:uppercase;letter-spacing:.09em}}.grid,.checks{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}}label>span{{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;font-weight:700;margin-bottom:4px}}.check{{display:flex;gap:7px;border:1px solid var(--line);border-radius:7px;padding:7px}}.check input{{width:auto}}.check span{{color:var(--ink);font:11px ui-monospace,monospace;text-transform:none}}.note{{background:#fff1d2;border:1px solid #e7c87b;padding:10px;border-radius:7px;color:#69470f}}.actions{{position:sticky;bottom:0;margin:15px -21px -21px;padding:12px 21px;background:rgba(255,253,248,.97);border-top:1px solid var(--line);display:flex;gap:8px}}.spacer{{flex:1}}@media(max-width:900px){{.top{{display:block}}.shell{{grid-template-columns:1fr}}aside{{position:relative;top:0;height:420px}}.grid,.checks{{grid-template-columns:1fr}}}}
</style></head><body><header><div class="top"><div><div class="eyebrow">{len(records)} source-bound packets · 81/81 subverticals</div><h1>One review room. No invented credit.</h1><div class="boundary">Filter every provisional route, inspect the public source, bind exact claims and export named-human intake. A browser draft, an export and even a valid receipt always keep formal candidate quota at zero.</div></div><div class="metrics"><div class="metric"><b>{len(records)}</b><small>packets</small></div><div class="metric"><b>{ledger['machine_ready_for_named_review_count']}</b><small>ready</small></div><div class="metric"><b>{ledger['evidence_gap_count']}</b><small>gaps</small></div><div class="metric"><b>81/81</b><small>routes</small></div><div class="metric"><b>0</b><small>credit</small></div></div></div></header>
<div class="shell"><aside class="panel"><div class="filters"><input class="wide" id="reviewer" placeholder="Named human reviewer"><input class="wide" id="search" placeholder="Search company, title or URL"><select id="status"><option value="all">All states</option><option value="ready">Ready</option><option value="gap">Gap</option></select><select id="origin"><option value="all">All origins</option><option value="gold_candidate_binding_packet">Gold packets</option><option value="targeted_subvertical_review_packet">Targeted waves</option></select><select class="wide" id="route"><option value="all">All 81 subverticals</option></select></div><div id="queue" class="queue"></div></aside><main class="panel" id="main"></main></div>
<script id="workbench-data" type="application/json">{data}</script><script>
const WB=JSON.parse(document.querySelector('#workbench-data').textContent),key='prooflaunch-unified-review:'+WB.review_ledger_sha256;let drafts=JSON.parse(localStorage.getItem(key)||'{{}}'),current=null;const q=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])),val=id=>q('#'+id)?.value.trim()||'',iso=()=>new Date().toISOString();async function sha(s){{const b=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s));return [...new Uint8Array(b)].map(x=>x.toString(16).padStart(2,'0')).join('')}}
function init(){{q('#reviewer').value=localStorage.getItem(key+':reviewer')||'';q('#route').innerHTML+=WB.records.flatMap(r=>r.provisional_subvertical_ids).filter((v,i,a)=>a.indexOf(v)===i).sort().map(v=>`<option value="${{esc(v)}}">${{esc(v)}}</option>`).join('');['search','status','origin','route'].forEach(id=>q('#'+id).addEventListener('input',renderQueue));q('#reviewer').addEventListener('input',e=>localStorage.setItem(key+':reviewer',e.target.value));renderQueue();select(WB.records[0].review_packet_id)}}
function filtered(){{const term=val('search').toLowerCase(),status=val('status'),origin=val('origin'),route=val('route');return WB.records.filter(r=>(!term||JSON.stringify([r.company,r.title,r.source_url]).toLowerCase().includes(term))&&(status==='all'||(status==='ready')===r.machine_ready_for_named_review)&&(origin==='all'||origin===r.origin_kind)&&(route==='all'||r.provisional_subvertical_ids.includes(route)))}}
function renderQueue(){{q('#queue').innerHTML=filtered().map(r=>`<button data-id="${{r.review_packet_id}}" class="${{current===r.review_packet_id?'active':''}}"><strong><i class="dot ${{drafts[r.review_packet_id]?'saved':r.machine_ready_for_named_review?'ready':''}}"></i> ${{esc(r.company||r.title)}}</strong><small><span>${{r.review_priority_score}}</span><span>${{r.provisional_subvertical_ids[0]}}</span></small></button>`).join('');q('#queue').querySelectorAll('button').forEach(b=>b.onclick=()=>select(b.dataset.id))}}
function select(id){{current=id;renderQueue();const r=WB.records.find(x=>x.review_packet_id===id),d=drafts[id]||{{}},p=r.proposed_field_values;const fields=WB.required_fields.map(n=>`<label><span>${{n.replaceAll('_',' ')}}</span><input id="field-${{n}}" value="${{esc(d.field_bindings?.[n]??p[n]??'')}}"></label>`).join(''),costs=WB.cost_components.map(n=>`<label><span>${{n}} cost evidence</span><input id="cost-${{n}}" value="${{esc(d.cost_components?.[n]||'')}}" placeholder="exact evidence or explicit unknown"></label>`).join(''),gates=WB.gates.map(n=>`<label class="check"><input type="checkbox" id="gate-${{n}}" ${{d.gate_decisions?.[n]?'checked':''}}><span>${{n}}</span></label>`).join('');q('#main').innerHTML=`<div class="head"><div><div class="eyebrow">${{r.origin_kind}} · ${{r.review_packet_id}}</div><h2>${{esc(r.company||'Identity unresolved')}}</h2><div class="chips">${{r.provisional_subvertical_ids.map(x=>`<span class="chip">${{esc(x)}}</span>`).join('')}}${{r.candidate_gate_blockers.map(x=>`<span class="chip gap">${{esc(x)}}</span>`).join('')}}</div></div><div class="score">${{r.review_priority_score}}</div></div><div class="source"><div><b>${{esc(r.title)}}</b><code>${{esc(r.source_url)}}</code><small>${{esc(r.source_capture_status)}} · SHA ${{esc(r.source_capture_sha256)}}</small></div><a class="btn" href="${{esc(r.source_url)}}" target="_blank" rel="noopener noreferrer">Inspect source ↗</a></div><section><h3>Captured bounded surface</h3><div class="note">${{esc(r.source_excerpt||'No bounded excerpt captured; preserve the evidence gap.')}}</div></section><section><h3>15 CaseCandidateV2 field bindings</h3><div class="grid">${{fields}}</div></section><section><h3>Six-component cost evidence</h3><div class="grid">${{costs}}</div></section><section><h3>Exact source bindings</h3><label><span>one per line: field TAB exact excerpt</span><textarea id="exact">${{esc(d.exact_bindings_text||'')}}</textarea></label></section><section><h3>Eleven fail-closed gates</h3><div class="checks">${{gates}}</div></section><section><div class="grid"><label><span>decision</span><select id="decision"><option value="needs_more_evidence">Needs more evidence</option><option value="reject_episode">Reject episode</option><option value="submit_for_admission_gate">Submit for independent admission gate</option></select></label><label><span>decision notes</span><textarea id="notes">${{esc(d.decision_notes||'')}}</textarea></label></div><label class="check"><input id="inspected" type="checkbox" ${{d.source_inspected?'checked':''}}><span>I personally opened and inspected this public source.</span></label><div class="note">Submit is not admission. Independent identity, outcome, budget, deduplication and all marginal quotas must be rechecked.</div></section><div class="actions"><button class="secondary" id="save">Save local draft</button><button class="secondary" id="clear">Clear</button><span class="spacer"></span><button class="primary" id="export">Export named-human intake</button></div>`;q('#decision').value=d.decision||'needs_more_evidence';q('#save').onclick=save;q('#clear').onclick=()=>{{delete drafts[current];localStorage.setItem(key,JSON.stringify(drafts));select(current)}};q('#export').onclick=exportAll}}
function collect(){{const r=WB.records.find(x=>x.review_packet_id===current);return {{review_packet_id:r.review_packet_id,source_url:r.source_url,review_packet_sha256:r.review_packet_sha256,reviewer_name:val('reviewer'),reviewed_at:drafts[current]?.reviewed_at||iso(),source_inspected:q('#inspected').checked,field_bindings:Object.fromEntries(WB.required_fields.map(n=>[n,val('field-'+n)])),cost_components:Object.fromEntries(WB.cost_components.map(n=>[n,val('cost-'+n)])),gate_decisions:Object.fromEntries(WB.gates.map(n=>[n,q('#gate-'+n).checked])),exact_bindings_text:val('exact'),decision:val('decision'),decision_notes:val('notes'),automatic_promotion_allowed:false,formal_candidate_quota_credit:0}}}}
function save(){{const d=collect();if(!d.reviewer_name){{alert('A named human reviewer is required.');return false}}drafts[current]=d;localStorage.setItem(key,JSON.stringify(drafts));renderQueue();return true}}
async function exportAll(){{if(!save())return;const records=[];for(const d of Object.values(drafts)){{if(!d.source_inspected)continue;const exact=[];for(const line of (d.exact_bindings_text||'').split('\n').filter(Boolean)){{const [field,...rest]=line.split('\t'),excerpt=rest.join('\t').trim();if(field&&excerpt)exact.push({{field:field.trim(),source_url:d.source_url,exact_excerpt:excerpt,excerpt_sha256:await sha(excerpt)}})}}const row={{...d,exact_claim_bindings:exact}};delete row.exact_bindings_text;records.push(row)}}const out={{schema:'{INTAKE_SCHEMA}',review_ledger_sha256:WB.review_ledger_sha256,created_at:iso(),review_count:records.length,records,automatic_promotion_allowed:false,formal_candidate_quota_credit:0,truth_boundary:WB.truth_boundary}},blob=new Blob([JSON.stringify(out,null,2)+'\n'],{{type:'application/json'}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='gtm-all-subvertical-named-human-intake-v2.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}}init();
</script></body></html>'''


def main() -> int:
    ledger = json.loads(SOURCE.read_text(encoding="utf-8"))
    verify_unified_review_ledger(ledger)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    page = _html(ledger)
    atomic_write_text(OUTPUT / "index.html", page)
    manifest = {
        "schema": "ProofLaunchGTMAllSubverticalReviewWorkbenchManifestV2",
        "review_ledger_sha256": ledger["content_sha256"],
        "review_packet_count": ledger["review_packet_count"],
        "machine_ready_for_named_review_count": ledger["machine_ready_for_named_review_count"],
        "evidence_gap_count": ledger["evidence_gap_count"],
        "represented_subvertical_count": ledger["represented_subvertical_count"],
        "observed_named_human_review_count": 0,
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
        "index_sha256": hashlib.sha256(page.encode()).hexdigest(),
        "import_command": ".venv/bin/python scripts/import_gtm_all_subvertical_reviews_v2.py <downloaded-intake.json>",
        "truth_boundary": ledger["truth_boundary"],
    }
    manifest["content_sha256"] = _digest(manifest)
    atomic_write_text(OUTPUT / "workbench-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(
        OUTPUT / "README.md",
        "# Unified 81-subvertical review workbench V2\n\n"
        f"Open `index.html` locally. It contains {ledger['review_packet_count']} zero-credit packets across all 81 "
        "subverticals. Inspect sources, save local drafts, export intake, then run the manifest import command. "
        "A validated receipt still grants no candidate quota.\n",
    )
    print(json.dumps({"output_dir": str(OUTPUT), **{k: manifest[k] for k in ("review_packet_count", "machine_ready_for_named_review_count", "evidence_gap_count", "represented_subvertical_count", "formal_candidate_quota_credit", "content_sha256")}}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
