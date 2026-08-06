#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-four-case-batch-review-v2/index.html"
MANIFEST = ROOT / "artifacts/gtm-four-case-batch-review-v2/manifest.json"


def _load(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def main() -> int:
    specs = (
        ("EmailOctopus", "emailoctopus"),
        ("Buffer", "buffer"),
        ("Flodesk", "flodesk"),
        ("Post Bridge", "postbridge"),
    )
    cases = []
    for company, slug in specs:
        proposal = _load(f"evidence/v10/gtm-{slug}-named-review-proposal-v2.json")
        dossier = _load(f"evidence/v10/gtm-{slug}-admission-dossier-v2.json")
        sources = [{
            "role": row["source_role"],
            "url": row["source_url"],
            "independent": bool(row.get("independent")),
        } for row in dossier["sources"]]
        cases.append({"company": company, "slug": slug, "proposal": proposal, "sources": sources})

    sections = []
    for index, case in enumerate(cases, start=1):
        proposal = case["proposal"]
        links = "".join(
            f'<li><a target="_blank" rel="noopener" href="{html.escape(row["url"], quote=True)}">{html.escape(row["role"])}{" · independent" if row["independent"] else ""}</a></li>'
            for row in case["sources"]
        )
        costs = "".join(
            f'<tr><th>{html.escape(name)}</th><td>{html.escape(value)}</td></tr>'
            for name, value in proposal["cost_components"].items()
        )
        fields = "".join(
            f'<tr><th>{html.escape(name)}</th><td>{html.escape(json.dumps(value, ensure_ascii=False) if isinstance(value, list) else str(value))}</td></tr>'
            for name, value in proposal["field_bindings"].items()
        )
        sections.append(f'''<section data-case="{index - 1}"><div class="case-head"><span>{index}/4</span><h2>{html.escape(case["company"])}</h2><b>10/11</b></div><p>逐一打开全部 7 个公开来源，再确认字段、六项成本及非因果边界。</p><ol>{links}</ol><details><summary>查看 15 个字段绑定</summary><table>{fields}</table></details><details><summary>查看六项成本</summary><table>{costs}</table></details><label>本案复核备注（至少 20 字）<textarea rows="4" data-notes placeholder="说明你检查了哪些关键原文、保留了哪些未知项"></textarea></label><label class="check"><input type="checkbox" data-inspected>我已逐一打开并检查本案全部绑定来源。</label><label class="check"><input type="checkbox" data-bound>我确认主体、episode、结果措辞、六项成本与非因果边界。</label><div class="status" data-status>待检查</div></section>''')

    embedded = json.dumps(cases, ensure_ascii=False).replace("</", "<\\/")
    page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>4 案批量实名复核</title><style>
body{{margin:0;background:#09101f;color:#f4f7ff;font:15px/1.55 ui-sans-serif,system-ui}}main{{max-width:1040px;margin:auto;padding:42px 22px}}h1{{font-size:42px;line-height:1.08}}.lead{{color:#b7c2dd;max-width:820px}}.identity,section{{border:1px solid #2a3b63;background:#111a32;border-radius:18px;padding:22px;margin:18px 0}}section.done{{border-color:#49c786}}.case-head{{display:flex;gap:14px;align-items:center}}.case-head h2{{flex:1;margin:0}}.case-head b{{font-size:26px;color:#8eb3ff}}label{{display:block;margin:16px 0}}input[type=text],textarea{{box-sizing:border-box;width:100%;background:#091226;color:white;border:1px solid #3a4d78;border-radius:10px;padding:12px}}.check{{display:flex;gap:10px;align-items:flex-start}}a{{color:#9cc0ff}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid #273758;padding:10px}}th{{width:180px}}button{{background:#356dff;color:white;border:0;border-radius:12px;padding:14px 20px;font-weight:800;font-size:16px}}button:disabled{{opacity:.4}}.status{{color:#f1bd62;font-weight:700}}section.done .status{{color:#63d89c}}code{{display:block;background:#07101f;padding:14px;border-radius:10px;white-space:pre-wrap}}details{{margin:14px 0}}summary{{cursor:pointer;font-weight:750}}
</style></head><body><main><p>ProofLaunch · 一次填写身份，四案仍逐案实质复核</p><h1>把 4 个 10/11 案例一次送入原子准入</h1><p class="lead">这不是自动批准。你仍需逐案打开 28 个公开来源并确认；页面只合并姓名、导出和服务器命令。四案必须全部通过才会写入，任何一案失败都保持 0 新增。</p><div class="identity"><label>实名 Reviewer<input type="text" id="reviewer" autocomplete="name" placeholder="你的真实姓名"></label><p id="summary">0/4 案完成实质检查</p></div>{''.join(sections)}<div class="identity"><button id="download" disabled>下载 4 案批量 Intake JSON</button><p>下载后运行：</p><code>PYTHONPATH=src .venv/bin/python scripts/admit_gtm_four_case_batch_v2.py --intake /absolute/path/gtm-four-case-batch-review-intake-v2.json</code><p id="message"></p></div></main><script id="payload" type="application/json">{embedded}</script><script>
const cases=JSON.parse(document.getElementById('payload').textContent),reviewer=document.getElementById('reviewer'),button=document.getElementById('download'),summary=document.getElementById('summary'),sections=[...document.querySelectorAll('section')];
function state(section){{const notes=section.querySelector('[data-notes]').value.trim(),inspected=section.querySelector('[data-inspected]').checked,bound=section.querySelector('[data-bound]').checked;return {{notes,inspected,bound,ready:notes.length>=20&&inspected&&bound}}}}
function refresh(){{const states=sections.map(state),done=states.filter(x=>x.ready).length;sections.forEach((section,i)=>{{section.classList.toggle('done',states[i].ready);section.querySelector('[data-status]').textContent=states[i].ready?'本案已可提交':'待检查'}});summary.textContent=`${{done}}/4 案完成实质检查`;button.disabled=!(reviewer.value.trim()&&done===4)}}
reviewer.addEventListener('input',refresh);sections.forEach(section=>section.addEventListener('input',refresh));
button.addEventListener('click',()=>{{const now=new Date().toISOString(),records=cases.map((item,i)=>{{const p=item.proposal,s=state(sections[i]);return {{review_packet_id:p.review_packet_id,source_url:p.source_url,review_packet_sha256:p.review_packet_sha256,reviewer_name:reviewer.value.trim(),reviewed_at:now,source_inspected:true,field_bindings:p.field_bindings,cost_components:p.cost_components,gate_decisions:Object.fromEntries(Object.keys(p.gate_evidence).map(k=>[k,true])),exact_claim_bindings:p.exact_primary_claim_bindings,decision:'submit_for_admission_gate',decision_notes:s.notes,automatic_promotion_allowed:false,formal_candidate_quota_credit:0}}}}),intake={{schema:'ProofLaunchGTMAllSubverticalUnifiedReviewIntakeV2',review_ledger_sha256:cases[0].proposal.source_unified_review_ledger_sha256,created_at:now,review_count:records.length,records,automatic_promotion_allowed:false,formal_candidate_quota_credit:0}},blob=new Blob([JSON.stringify(intake,null,2)],{{type:'application/json'}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='gtm-four-case-batch-review-intake-v2.json';a.click();URL.revokeObjectURL(a.href);document.getElementById('message').textContent='批量 Intake 已下载；服务器仍会重新校验四案并原子写入。'}});refresh();
</script></body></html>'''
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUTPUT, page)
    manifest = {
        "schema": "ProofLaunchGTMFourCaseBatchReviewManifestV2",
        "case_count": 4,
        "companies": [row["company"] for row in cases],
        "source_link_count": sum(len(row["sources"]) for row in cases),
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
        "output": str(OUTPUT.relative_to(ROOT)),
        "truth_boundary": "The page only exports a named-human intake after four substantive per-case checks; server admission remains mandatory.",
    }
    manifest["content_sha256"] = _digest(manifest)
    atomic_write_text(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "manifest": str(MANIFEST), "source_link_count": manifest["source_link_count"], "content_sha256": manifest["content_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
