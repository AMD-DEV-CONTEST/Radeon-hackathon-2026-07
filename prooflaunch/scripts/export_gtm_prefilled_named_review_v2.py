#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a prefilled, source-inspection-first named review page.")
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--dossier", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    proposal = json.loads(args.proposal.read_text())
    dossier = json.loads(args.dossier.read_text())
    company = proposal.get("company") or dossier["company"]
    sources = "".join(
        f'<li><a href="{html.escape(row["source_url"], quote=True)}" target="_blank" rel="noreferrer">{html.escape(row["source_role"])}</a> · {html.escape(row["capture_status"])}</li>'
        for row in dossier["sources"]
    )
    fields = "".join(
        f'<tr><th>{html.escape(key)}</th><td>{html.escape(json.dumps(value, ensure_ascii=False) if isinstance(value, list) else str(value))}</td></tr>'
        for key, value in proposal["field_bindings"].items()
    )
    costs = "".join(f'<tr><th>{html.escape(key)}</th><td>{html.escape(value)}</td></tr>' for key, value in proposal["cost_components"].items())
    claims = "".join(f'<blockquote><code>{html.escape(row["field"])}</code> {html.escape(row["exact_excerpt"])}</blockquote>' for row in proposal["exact_primary_claim_bindings"])
    embedded = json.dumps(proposal, ensure_ascii=False).replace("</", "<\\/")
    filename = company.casefold().replace(" ", "-") + "-named-review-intake-v2.json"
    page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(company)} named review</title><style>
body{{font:15px/1.55 ui-sans-serif,system-ui;background:#f4f5f7;color:#17191d;margin:0}}main{{max-width:1080px;margin:32px auto;padding:0 20px}}section{{background:white;border:1px solid #dfe3e8;border-radius:16px;padding:22px;margin:16px 0}}h1{{font-size:32px}}.status{{display:inline-block;background:#fff3cd;color:#6d4c00;padding:7px 12px;border-radius:999px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;border-top:1px solid #eee;padding:10px}}th{{width:230px}}input,textarea{{width:100%;box-sizing:border-box;padding:10px;border:1px solid #aeb6c2;border-radius:8px}}button{{background:#145cf5;color:white;border:0;border-radius:9px;padding:12px 18px;font-weight:700}}button:disabled{{opacity:.4}}blockquote{{border-left:4px solid #145cf5;margin:12px 0;padding:8px 14px;background:#f7f9ff}}.warn{{color:#9b2c2c}}label.check{{display:flex;gap:10px;align-items:flex-start}}label.check input{{width:auto;margin-top:5px}}</style></head><body><main>
<p class="status">运营闭环 10/11 · 只差 1 次实名签收</p><h1>{html.escape(company)} 实名准入复核</h1><p>机器侧证据、字段、成本与去重已闭环；逐一打开来源完成最后的人类核对。本页不会自动批准，也不会把未签收案例冒充正式分数。</p>
<section><h2>公开来源</h2><ul>{sources}</ul></section><section><h2>15 个字段</h2><table>{fields}</table></section><section><h2>六项成本</h2><table>{costs}</table><p class="warn">未知金额必须保持未知；历史月度成本不得冒充当前预算。</p></section><section><h2>主来源精确片段</h2>{claims}</section>
<section><h2>实名确认</h2><label>Reviewer name<input id="reviewer" autocomplete="name"></label><label>Decision notes<textarea id="notes" rows="5"></textarea></label><p><label class="check"><input id="inspected" type="checkbox">我已逐一检查全部绑定来源及上下文。</label></p><p><label class="check"><input id="bind" type="checkbox">我确认主体、episode、六项成本、结果措辞和非因果边界。</label></p><button id="download" disabled>下载待服务器验证的实名 Intake JSON</button><p id="message"></p></section></main>
<script id="proposal" type="application/json">{embedded}</script><script>const p=JSON.parse(document.getElementById('proposal').textContent),r=document.getElementById('reviewer'),n=document.getElementById('notes'),i=document.getElementById('inspected'),b=document.getElementById('bind'),d=document.getElementById('download'),m=document.getElementById('message');function ready(){{d.disabled=!(r.value.trim()&&n.value.trim().length>=20&&i.checked&&b.checked)}}[r,n,i,b].forEach(x=>x.addEventListener('input',ready));d.addEventListener('click',()=>{{const now=new Date().toISOString(),g=Object.fromEntries(Object.keys(p.gate_evidence).map(k=>[k,true])),intake={{schema:'ProofLaunchGTMAllSubverticalUnifiedReviewIntakeV2',review_ledger_sha256:p.source_unified_review_ledger_sha256,created_at:now,review_count:1,records:[{{review_packet_id:p.review_packet_id,source_url:p.source_url,review_packet_sha256:p.review_packet_sha256,reviewer_name:r.value.trim(),reviewed_at:now,source_inspected:true,field_bindings:p.field_bindings,cost_components:p.cost_components,gate_decisions:g,exact_claim_bindings:p.exact_primary_claim_bindings,decision:'submit_for_admission_gate',decision_notes:n.value.trim(),automatic_promotion_allowed:false,formal_candidate_quota_credit:0}}],automatic_promotion_allowed:false,formal_candidate_quota_credit:0}};const blob=new Blob([JSON.stringify(intake,null,2)],{{type:'application/json'}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='{filename}';a.click();URL.revokeObjectURL(a.href);m.textContent='Intake 已生成；仍需严格服务器准入。'}});</script></body></html>'''
    args.output.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.output / "index.html", page)
    manifest = {
        "schema": "ProofLaunchGTMPrefilledNamedReviewWorkbenchManifestV2",
        "company": company,
        "source_proposal_sha256": proposal["content_sha256"],
        "source_dossier_sha256": dossier["content_sha256"],
        "html_sha256": _sha(page),
        "reviewer_prefilled": False,
        "automatic_promotion_allowed": False,
        "formal_candidate_quota_credit": 0,
    }
    manifest["content_sha256"] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    atomic_write_text(args.output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "company": company, "content_sha256": manifest["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
