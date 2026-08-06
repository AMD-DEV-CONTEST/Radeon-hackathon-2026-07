#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "artifacts/gtm-seven-case-batch-review-v2"


def _load(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text())


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    specs = (("EmailOctopus", "emailoctopus"), ("Buffer", "buffer"), ("Flodesk", "flodesk"), ("Post Bridge", "postbridge"), ("Parqet", "parqet"), ("Spendbase", "spendbase"), ("Barn2", "barn2"))
    cases = []
    for company, slug in specs:
        proposal = _load(f"evidence/v10/gtm-{slug}-named-review-proposal-v2.json")
        dossier = _load(f"evidence/v10/gtm-{slug}-admission-dossier-v2.json")
        cases.append({"company": company, "slug": slug, "proposal": proposal, "sources": [{"role": row["source_role"], "url": row["source_url"], "independent": bool(row.get("independent"))} for row in dossier["sources"]], "truth_boundary": dossier["truth_boundary"]})
    sections = []
    for index, case in enumerate(cases, start=1):
        p = case["proposal"]
        links = "".join(f'<li><a target="_blank" rel="noopener" href="{html.escape(row["url"], quote=True)}">{html.escape(row["role"])}{" · independent" if row["independent"] else ""}</a></li>' for row in case["sources"])
        fields = "".join(f'<tr><th>{html.escape(name)}</th><td>{html.escape(json.dumps(value, ensure_ascii=False) if isinstance(value, list) else str(value))}</td></tr>' for name, value in p["field_bindings"].items())
        costs = "".join(f'<tr><th>{html.escape(name)}</th><td>{html.escape(value)}</td></tr>' for name, value in p["cost_components"].items())
        sections.append(f'''<section><div class="head"><span>{index}/7</span><h2>{html.escape(case["company"])}</h2><b>10/11</b></div><p class="truth">{html.escape(case["truth_boundary"])}</p><ol>{links}</ol><details><summary>15 个字段绑定</summary><table>{fields}</table></details><details><summary>六项成本</summary><table>{costs}</table></details><label>本案逐源复核备注（至少 20 字）<textarea rows="4" data-notes></textarea></label><label class="check"><input type="checkbox" data-inspected>我已打开并检查本案全部 7 个来源。</label><label class="check"><input type="checkbox" data-bound>我确认字段、episode、成本、结果类型与非因果边界。</label><div class="state" data-state>待检查</div></section>''')
    embedded = json.dumps(cases, ensure_ascii=False).replace("</", "<\\/")
    page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>7 案批量实名复核</title><style>body{{margin:0;background:#08101f;color:#f5f7ff;font:15px/1.55 system-ui}}main{{max-width:1060px;margin:auto;padding:44px 22px}}h1{{font-size:42px;line-height:1.08}}.lead,.truth{{color:#b5c1dd}}.identity,section{{border:1px solid #2c3d61;background:#111a31;border-radius:18px;padding:22px;margin:18px 0}}section.done{{border-color:#43c786}}.head{{display:flex;gap:14px;align-items:center}}.head h2{{flex:1;margin:0}}.head b{{font-size:25px;color:#91b7ff}}input[type=text],textarea{{width:100%;box-sizing:border-box;background:#091226;color:white;border:1px solid #40547e;border-radius:10px;padding:12px}}label{{display:block;margin:14px 0}}.check{{display:flex;gap:10px}}a{{color:#9fc2ff}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid #273657;padding:9px}}th{{width:180px}}button{{background:#356dff;color:white;border:0;border-radius:11px;padding:14px 20px;font-weight:800}}button:disabled{{opacity:.4}}.state{{color:#f0ba62;font-weight:750}}section.done .state{{color:#64d99c}}code{{display:block;background:#07101f;padding:14px;border-radius:10px;white-space:pre-wrap}}</style></head><body><main><p>ProofLaunch · 七案一次导出，仍逐案实质检查</p><h1>7 个 10/11 案例，一次原子准入</h1><p class="lead">逐案检查 49 个公开来源。任何一案失败都不写注册表；页面不能自动批准、不能替你署名。</p><div class="identity"><label>实名 Reviewer<input type="text" id="reviewer" autocomplete="name"></label><p id="summary">0/7 案完成实质检查</p></div>{''.join(sections)}<div class="identity"><button id="download" disabled>下载 7 案批量 Intake JSON</button><p>下载后运行：</p><code>PYTHONPATH=src .venv/bin/python scripts/admit_gtm_seven_case_batch_v2.py --intake /absolute/path/gtm-seven-case-batch-review-intake-v2.json</code><p id="message"></p></div></main><script id="payload" type="application/json">{embedded}</script><script>const cases=JSON.parse(document.getElementById('payload').textContent),reviewer=document.getElementById('reviewer'),button=document.getElementById('download'),summary=document.getElementById('summary'),sections=[...document.querySelectorAll('section')];function state(s){{const notes=s.querySelector('[data-notes]').value.trim(),inspected=s.querySelector('[data-inspected]').checked,bound=s.querySelector('[data-bound]').checked;return {{notes,ready:notes.length>=20&&inspected&&bound}}}}function refresh(){{const states=sections.map(state),done=states.filter(x=>x.ready).length;sections.forEach((s,i)=>{{s.classList.toggle('done',states[i].ready);s.querySelector('[data-state]').textContent=states[i].ready?'本案已可提交':'待检查'}});summary.textContent=`${{done}}/7 案完成实质检查`;button.disabled=!(reviewer.value.trim()&&done===7)}}reviewer.addEventListener('input',refresh);sections.forEach(s=>s.addEventListener('input',refresh));button.addEventListener('click',()=>{{const now=new Date().toISOString(),records=cases.map((item,i)=>{{const p=item.proposal;return {{review_packet_id:p.review_packet_id,source_url:p.source_url,review_packet_sha256:p.review_packet_sha256,reviewer_name:reviewer.value.trim(),reviewed_at:now,source_inspected:true,field_bindings:p.field_bindings,cost_components:p.cost_components,gate_decisions:Object.fromEntries(Object.keys(p.gate_evidence).map(k=>[k,true])),exact_claim_bindings:p.exact_primary_claim_bindings,decision:'submit_for_admission_gate',decision_notes:state(sections[i]).notes,automatic_promotion_allowed:false,formal_candidate_quota_credit:0}}}}),intake={{schema:'ProofLaunchGTMAllSubverticalUnifiedReviewIntakeV2',review_ledger_sha256:cases[0].proposal.source_unified_review_ledger_sha256,created_at:now,review_count:7,records,automatic_promotion_allowed:false,formal_candidate_quota_credit:0}},blob=new Blob([JSON.stringify(intake,null,2)],{{type:'application/json'}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='gtm-seven-case-batch-review-intake-v2.json';a.click();URL.revokeObjectURL(a.href);document.getElementById('message').textContent='批量 Intake 已下载；服务器仍会重新校验七案并原子写入。'}});refresh();</script></body></html>'''
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUTPUT_DIR / "index.html", page)
    manifest = {"schema": "ProofLaunchGTMSevenCaseBatchReviewManifestV2", "case_count": 7, "companies": [row["company"] for row in cases], "source_link_count": sum(len(row["sources"]) for row in cases), "formal_candidate_quota_credit": 0, "automatic_promotion_allowed": False, "output": str((OUTPUT_DIR / "index.html").relative_to(ROOT)), "truth_boundary": "The page exports one seven-record named-human intake only after seven substantive per-case checks; server admission remains mandatory."}
    manifest["content_sha256"] = _digest(manifest)
    atomic_write_text(OUTPUT_DIR / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT_DIR / "index.html"), "source_link_count": manifest["source_link_count"], "content_sha256": manifest["content_sha256"]}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
