#!/usr/bin/env python3
"""Build a human-confirmed blind-review page from anonymous AI suggestions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from award_evaluation import BLIND_DRAFT_SCHEMA, atomic_text
from build_ai_blind_prescore import SCHEMA as PRESCORE_SCHEMA, read_pack


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import goboard  # noqa: E402


ASSISTANCE_TYPE = "ai_prescore"
COLS = "ABCDEFGHJKLMNOPQRST"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def gtp_to_sgf(move: str, size: int) -> str:
    value = move.strip().upper()
    if value in {"PASS", ""}:
        return ""
    column = COLS.index(value[0])
    row = size - int(value[1:])
    if not (0 <= column < size and 0 <= row < size):
        raise ValueError(f"coordinate outside {size}x{size} board: {move}")
    return chr(97 + column) + chr(97 + row)


def board_lists(board: goboard.Board) -> dict[str, list[str]]:
    stones = {"black": [], "white": []}
    for row in range(board.size):
        for column in range(board.size):
            color = board.get(column, row)
            if color == goboard.BLACK:
                stones["black"].append(f"{COLS[column]}{board.size - row}")
            elif color == goboard.WHITE:
                stones["white"].append(f"{COLS[column]}{board.size - row}")
    return stones


def build_review_evidence(pack: dict[str, Any], cases_path: Path, queries_path: Path) -> dict[str, Any]:
    cases = {row["caseId"]: row for row in read_jsonl(cases_path)}
    # Keep the query file in the trusted input contract, but a blind comparison
    # must render the pre-move board.  Replaying through the actual move would
    # put the red stone on the board and compare it with the opponent's turn.
    _queries = {row["id"]: row for row in read_jsonl(queries_path)}
    result: dict[str, Any] = {}
    for blind_case in pack.get("cases") or []:
        case_id = blind_case["caseId"]
        case = cases.get(case_id)
        if case is None:
            raise ValueError(f"missing evidence case: {case_id}")
        evidence = case.get("evidence") or {}
        board_data = evidence.get("board") or {}
        size = int(board_data.get("boardSize") or evidence.get("boardSize") or 19)
        before = board_data.get("before")
        if not isinstance(before, dict):
            raise ValueError(f"blind review requires a pre-move board: {case_id}")
        stones = {
            "black": list(before.get("black") or []),
            "white": list(before.get("white") or []),
        }
        actual_move = str(evidence.get("actualMove") or board_data.get("questionTargetMove") or "").upper()
        best_move = str(evidence.get("bestMove") or (evidence.get("katago") or {}).get("bestMove") or "").upper()
        occupied = {str(move).upper() for move in stones["black"] + stones["white"]}
        for label, move in (("actual", actual_move), ("best", best_move)):
            if move and move != "PASS" and move in occupied:
                raise ValueError(f"{label} move is already on the pre-move board: {case_id}/{move}")
        actual_color = evidence.get("actualColor") or board_data.get("subjectColor") or evidence.get("toPlay")
        to_play = evidence.get("toPlay") or board_data.get("subjectColor") or actual_color
        if actual_color not in {"B", "W"} or to_play != actual_color:
            raise ValueError(f"blind review turn/color mismatch: {case_id}/{to_play}/{actual_color}")
        board_note = "同一行棋方落子前的局面；红圈与绿圈均为尚未落盘的同回合候选。"
        katago = evidence.get("katago") or {}
        rule_facts = evidence.get("ruleFacts") or {}
        result[case_id] = {
            "boardSize": size,
            "stones": stones,
            "toPlay": to_play,
            "actualColor": actual_color,
            "actualMove": actual_move,
            "bestMove": best_move,
            "sameTurnAlternatives": True,
            "visits": katago.get("visits"),
            "candidates": list(katago.get("candidates") or [])[:4],
            "claimBoundary": evidence.get("claimBoundary"),
            "referenceAnswer": (case.get("expected") or {}).get("referenceAnswer"),
            "legalMove": rule_facts.get("legalMove"),
            "capturedByTarget": rule_facts.get("capturedByTarget") if "capturedByTarget" in rule_facts else rule_facts.get("capturedByActual"),
            "targetGroupLibertiesAfter": rule_facts.get("targetGroupLibertiesAfter") if "targetGroupLibertiesAfter" in rule_facts else rule_facts.get("actualGroupLibertiesAfter"),
            "boardNote": board_note,
        }
    if len(result) != 30:
        raise ValueError(f"review evidence must contain 30 cases, got {len(result)}")
    return result


def read_prescore(path: Path, pack: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schemaVersion") != PRESCORE_SCHEMA:
        raise ValueError("AI pre-score schema is not supported")
    if value.get("status") != "machine_suggestions_only" or value.get("humanReviewRequired") is not True:
        raise ValueError("AI pre-score must remain non-authoritative")
    if value.get("packSha256") != pack.get("packSha256"):
        raise ValueError("AI pre-score does not match the blind pack")
    suggestions = value.get("suggestions") or []
    if len(suggestions) != 30:
        raise ValueError("AI pre-score must contain exactly 30 cases")
    pack_cases = {row["caseId"]: row for row in pack.get("cases") or []}
    suggestion_cases = {row.get("caseId"): row for row in suggestions}
    if len(pack_cases) != 30 or set(suggestion_cases) != set(pack_cases):
        raise ValueError("AI pre-score case IDs do not match the blind pack")
    for case_id, suggestion in suggestion_cases.items():
        ratings = suggestion.get("ratings") or []
        by_alias = {row.get("alias"): row for row in ratings}
        expected_aliases = {row["alias"] for row in pack_cases[case_id].get("answers") or []}
        if set(by_alias) != expected_aliases or len(ratings) != 3:
            raise ValueError(f"{case_id} must score A, B, and C exactly once")
        for alias, row in by_alias.items():
            for field in ("evidence", "depth", "actionability"):
                score = row.get(field)
                if not isinstance(score, int) or not 1 <= score <= 5:
                    raise ValueError(f"{case_id}/{alias}/{field} is not a 1-5 score")
            if not isinstance(row.get("severe"), bool):
                raise ValueError(f"{case_id}/{alias}/severe must be boolean")
    return value


def render_assisted_html(
    pack: dict[str, Any], prescore: dict[str, Any], prescore_sha256: str,
    review_evidence: dict[str, Any], evidence_sha256: str,
) -> str:
    payload = {
        "pack": pack,
        "prescore": prescore,
        "prescoreSha256": prescore_sha256,
        "evidence": review_evidence,
        "evidenceSha256": evidence_sha256,
    }
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>弈鉴 · AI 辅助匿名盲评</title>
<style>
:root{{--ink:#20302d;--jade:#285f54;--paper:#f4efe5;--card:#fffaf1;--line:#d8cdbb;--hint:#eef4f1;--warn:#8b4a2f}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}}
header,main{{max-width:1220px;margin:auto;padding:18px}} header{{position:sticky;top:0;z-index:10;background:rgba(244,239,229,.97);border-bottom:1px solid var(--line)}}
header h1{{margin:0 0 4px}} .notice{{margin:8px 0;padding:10px 12px;border-left:4px solid var(--warn);background:#fff4e7}}
#progress{{display:inline-block;margin-left:12px;font-weight:800}} section{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:14px 0}}
section.confirmed{{border:2px solid #4b8777}} .answers{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}} article{{border:1px solid #ddd0bc;border-radius:10px;padding:12px;background:#fff}}
pre{{white-space:pre-wrap;word-break:break-word;min-height:90px}} .ai-reason{{background:var(--hint);padding:9px;border-radius:8px;margin:10px 0;color:#35534d}}
.evidence-panel{{display:grid;grid-template-columns:minmax(300px,520px) 1fr;gap:16px;background:#f8f4e9;border:1px solid #d8cdbb;border-radius:12px;padding:12px;margin:12px 0}}
.board-wrap{{max-width:520px}} canvas.board{{display:block;width:100%;height:auto;background:#d5b26e;border-radius:9px}} .facts{{display:grid;grid-template-columns:repeat(4,minmax(90px,1fr));gap:8px}}
.fact{{background:white;border:1px solid #ded4c3;border-radius:8px;padding:7px}} .fact strong{{display:block;font-size:17px}} .legend span{{display:inline-block;margin-right:14px}} .red{{color:#c7463b}} .green{{color:#16805f}}
.candidate-table{{width:100%;border-collapse:collapse;font-size:13px}} .candidate-table th,.candidate-table td{{border-bottom:1px solid #ddd0bc;padding:5px;text-align:left}}
label{{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:7px 0}} select,input,button{{font:inherit}} select{{min-width:76px;padding:4px}}
button{{background:var(--jade);color:white;border:0;border-radius:9px;padding:10px 15px;cursor:pointer}} button.case-confirm{{display:block;width:100%;margin-top:14px}}
button.case-confirm.done{{background:#4b8777}} .small{{color:#65716e;font-size:13px}} @media(max-width:850px){{.answers,.evidence-panel{{grid-template-columns:1fr}} .facts{{grid-template-columns:repeat(2,1fr)}} header{{position:static}}}}
</style></head><body>
<header><h1>弈鉴 · 30 题匿名三方盲评</h1>
<div class="notice"><strong>身份说明：</strong>下方分数是 AI 证据预审建议，不是职业棋手评分，也不是人工签发。A/B/C 的模型身份保持隐藏。请你核对、必要时修改，然后逐题点击确认。</div>
<button id="export">30 题确认后导出</button><strong id="progress"></strong><div class="small">每题只需确认一次；修改已确认题目后，该题会自动恢复为“待确认”。</div></header>
<main id="cases"></main>
<script id="payload" type="application/json">{data}</script>
<script>
const root=JSON.parse(document.getElementById('payload').textContent),p=root.pack,s=root.prescore;
const storageKey='yijian-blind-assisted-'+p.packSha256+'-'+root.prescoreSha256;
const saved=JSON.parse(localStorage.getItem(storageKey)||'{{}}');
let d=saved.records||{{}}, confirmed=new Set(saved.confirmed||[]);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const suggestions=new Map(s.suggestions.map(row=>[row.caseId,new Map(row.ratings.map(r=>[r.alias,r]))]));
const ev=root.evidence;
const options=selected=>[1,2,3,4,5].map(x=>`<option value="${{x}}" ${{x===selected?'selected':''}}>${{x}}</option>`).join('');
const pct=value=>value===null||value===undefined?'—':(Number(value)*100).toFixed(2)+'%';
const pts=value=>value===null||value===undefined?'—':Number(value).toFixed(2);
const candidateRows=e=>(e.candidates||[]).map(x=>`<tr><td><b>${{esc(x.move)}}</b></td><td>${{pct(x.subjectWinrate??x.winrate)}}</td><td>${{pts(x.subjectScoreLead??x.scoreLead)}}</td><td>${{esc(x.visits??'—')}}</td><td>${{esc((x.pv||[]).slice(0,8).join(' → '))}}</td></tr>`).join('');
const evidenceHtml=caseId=>{{const e=ev[caseId],color=e.actualColor==='B'?'黑':e.actualColor==='W'?'白':'—';return `<div class="evidence-panel"><div class="board-wrap"><canvas class="board" data-case="${{esc(caseId)}}" width="620" height="620"></canvas><div class="legend"><span class="red">● 红圈：${{color}}棋实战候选 ${{esc(e.actualMove)}}</span><span class="green">● 绿圈：同回合 KataGo 首选 ${{esc(e.bestMove)}}</span></div><div class="small">${{esc(e.boardNote)}}</div></div><div><div class="facts"><div class="fact">棋盘<strong>${{e.boardSize}} 路</strong></div><div class="fact">当前行棋方<strong>${{e.toPlay==='B'?'黑':e.toPlay==='W'?'白':'—'}}</strong></div><div class="fact">${{color}}棋实战候选<strong>${{esc(e.actualMove||'—')}}</strong></div><div class="fact">同回合 AI 首选<strong>${{esc(e.bestMove||'—')}}</strong></div></div><p><b>KataGo：</b>${{esc(e.visits||'—')}} visits</p><table class="candidate-table"><thead><tr><th>候选</th><th>本方胜率</th><th>本方目差</th><th>访问</th><th>主变化</th></tr></thead><tbody>${{candidateRows(e)}}</tbody></table>${{e.referenceAnswer?`<p><b>官方/项目判分依据：</b>${{esc(e.referenceAnswer)}}</p>`:''}}<p><b>规则事实：</b>${{e.legalMove===null||e.legalMove===undefined?'未单列':e.legalMove?'目标手合法':'目标手异常'}}${{Array.isArray(e.capturedByTarget)?`；提子 ${{e.capturedByTarget.length}} 枚`:''}}${{e.targetGroupLibertiesAfter!==null&&e.targetGroupLibertiesAfter!==undefined?`；落子后目标棋块 ${{e.targetGroupLibertiesAfter}} 气`:''}}</p><p><b>证据边界：</b>${{esc(e.claimBoundary||'仅限当前重建局面与登记分析。')}}</p></div></div>`;}};
for(const c of p.cases) for(const a of c.answers){{const id=c.caseId+'|'+a.alias, ai=suggestions.get(c.caseId).get(a.alias);d[id]=d[id]||{{caseId:c.caseId,alias:a.alias,evidence:ai.evidence,depth:ai.depth,actionability:ai.actionability,severe:ai.severe}};}}
document.getElementById('cases').innerHTML=p.cases.map((c,i)=>`<section id="case-${{esc(c.caseId)}}" data-case="${{esc(c.caseId)}}"><h2>${{i+1}}. ${{esc(c.question)}}</h2>${{evidenceHtml(c.caseId)}}<div class="answers">${{c.answers.map(a=>{{const ai=suggestions.get(c.caseId).get(a.alias),row=d[c.caseId+'|'+a.alias];return `<article><h3>回答 ${{esc(a.alias)}}</h3><pre>${{esc(a.answer)}}</pre><div class="ai-reason"><strong>AI 预审理由：</strong>${{esc(ai.reason||'未提供理由')}}</div>${{[['evidence','证据正确性'],['depth','教学深度'],['actionability','可执行性']].map(([f,l])=>`<label>${{l}}<select class="rating" data-case="${{esc(c.caseId)}}" data-alias="${{esc(a.alias)}}" data-field="${{f}}">${{options(row[f])}}</select></label>`).join('')}}<label><span>严重坐标/首选/数值矛盾</span><input type="checkbox" class="severe" data-case="${{esc(c.caseId)}}" data-alias="${{esc(a.alias)}}" ${{row.severe?'checked':''}}></label></article>`}}).join('')}}</div><button class="case-confirm" data-case="${{esc(c.caseId)}}">确认本题三份评分</button></section>`).join('');
const drawBoard=canvas=>{{const e=ev[canvas.dataset.case],ctx=canvas.getContext('2d'),size=e.boardSize,cols='ABCDEFGHJKLMNOPQRST'.slice(0,size),pad=48,gap=(canvas.width-pad*2)/(size-1);ctx.clearRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#d5b26e';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.strokeStyle='#554b38';ctx.lineWidth=1.5;for(let i=0;i<size;i++){{const v=pad+i*gap;ctx.beginPath();ctx.moveTo(pad,v);ctx.lineTo(canvas.width-pad,v);ctx.stroke();ctx.beginPath();ctx.moveTo(v,pad);ctx.lineTo(v,canvas.height-pad);ctx.stroke();}}ctx.fillStyle='#263934';ctx.font=`${{size===19?14:18}}px system-ui`;ctx.textAlign='center';ctx.textBaseline='middle';for(let i=0;i<size;i++){{const v=pad+i*gap;ctx.fillText(cols[i],v,22);ctx.fillText(cols[i],v,canvas.height-20);ctx.fillText(String(size-i),22,v);ctx.fillText(String(size-i),canvas.width-22,v);}}const stars=size===19?[3,9,15]:size===9?[2,4,6]:[];for(const x of stars)for(const y of stars){{ctx.beginPath();ctx.arc(pad+x*gap,pad+y*gap,size===19?3.4:4.2,0,Math.PI*2);ctx.fill();}}const xy=coord=>{{if(!coord||coord==='PASS')return null;const x=cols.indexOf(coord[0]),row=Number(coord.slice(1));return x<0||row<1||row>size?null:[pad+x*gap,pad+(size-row)*gap];}};const stone=(coord,color)=>{{const pos=xy(coord);if(!pos)return;ctx.beginPath();ctx.arc(pos[0],pos[1],Math.max(9,gap*.44),0,Math.PI*2);ctx.fillStyle=color;ctx.fill();ctx.strokeStyle=color==='#111'?'#333':'#777';ctx.lineWidth=1.2;ctx.stroke();}};(e.stones.black||[]).forEach(x=>stone(x,'#111'));(e.stones.white||[]).forEach(x=>stone(x,'#fafafa'));const ring=(coord,color,radius)=>{{const pos=xy(coord);if(!pos)return;ctx.beginPath();ctx.arc(pos[0],pos[1],radius,0,Math.PI*2);ctx.strokeStyle=color;ctx.lineWidth=5;ctx.stroke();}};ring(e.actualMove,'#c7463b',Math.max(12,gap*.51));ring(e.bestMove,'#16805f',Math.max(16,gap*.60));}};
document.querySelectorAll('canvas.board').forEach(drawBoard);
const persist=()=>localStorage.setItem(storageKey,JSON.stringify({{records:d,confirmed:[...confirmed]}}));
const completeCase=caseId=>['A','B','C'].every(alias=>{{const row=d[caseId+'|'+alias];return row&&['evidence','depth','actionability'].every(f=>Number.isInteger(row[f])&&row[f]>=1&&row[f]<=5);}});
const update=()=>{{for(const section of document.querySelectorAll('section[data-case]')){{const ok=confirmed.has(section.dataset.case);section.classList.toggle('confirmed',ok);const b=section.querySelector('.case-confirm');b.classList.toggle('done',ok);b.textContent=ok?'✓ 本题已由你确认':'确认本题三份评分';}}document.getElementById('progress').textContent=`已确认 ${{confirmed.size}} / 30 题`;}};
const invalidate=caseId=>{{confirmed.delete(caseId);persist();update();}};
document.querySelectorAll('.rating').forEach(x=>x.onchange=()=>{{const id=x.dataset.case+'|'+x.dataset.alias;d[id][x.dataset.field]=Number(x.value);invalidate(x.dataset.case);}});
document.querySelectorAll('.severe').forEach(x=>x.onchange=()=>{{const id=x.dataset.case+'|'+x.dataset.alias;d[id].severe=x.checked;invalidate(x.dataset.case);}});
document.querySelectorAll('.case-confirm').forEach(button=>button.onclick=()=>{{const caseId=button.dataset.case;if(!completeCase(caseId)){{alert('本题仍有未完成评分。');return;}}confirmed.add(caseId);persist();update();const section=button.closest('section');const next=section.nextElementSibling;if(next&&!next.classList.contains('confirmed'))next.scrollIntoView({{behavior:'smooth',block:'start'}});}});
document.getElementById('export').onclick=()=>{{const allCases=new Set(p.cases.map(c=>c.caseId));if(confirmed.size!==30||[...allCases].some(id=>!confirmed.has(id))){{alert('请先逐题确认全部 30 题。');return;}}const records=Object.values(d);if(records.length!==90||records.some(row=>!['evidence','depth','actionability'].every(f=>Number.isInteger(row[f])&&row[f]>=1&&row[f]<=5))){{alert('评分记录不完整，无法导出。');return;}}const value={{schemaVersion:'{BLIND_DRAFT_SCHEMA}',status:'human_scored',packSha256:p.packSha256,reviewMode:'ai_assisted_human_confirmation',assistance:{{type:'{ASSISTANCE_TYPE}',schemaVersion:s.schemaVersion,prescoreSha256:root.prescoreSha256,reviewEvidenceSha256:root.evidenceSha256,humanFinalDecision:true}},humanConfirmedCases:[...confirmed].sort(),records}};const blob=new Blob([JSON.stringify(value,null,2)],{{type:'application/json'}}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='yijian-blind-review-assisted.json';a.click();URL.revokeObjectURL(a.href);}};
persist();update();
</script></body></html>"""


def build(
    review: Path, prescore_path: Path, cases_path: Path,
    queries_path: Path, output: Path,
) -> dict[str, Any]:
    pack = read_pack(review)
    prescore = read_prescore(prescore_path, pack)
    prescore_sha256 = hashlib.sha256(prescore_path.read_bytes()).hexdigest()
    # The judging model name is provenance for the private evidence file, not
    # review-page content.  Embedding it would leak one competing identity.
    public_prescore = {
        key: prescore[key]
        for key in (
            "schemaVersion", "status", "humanReviewRequired", "packSha256",
            "completed", "suggestions",
        )
    }
    review_evidence = build_review_evidence(pack, cases_path, queries_path)
    evidence_bytes = json.dumps(
        review_evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    evidence_sha256 = hashlib.sha256(evidence_bytes).hexdigest()
    atomic_text(output, render_assisted_html(
        pack, public_prescore, prescore_sha256, review_evidence, evidence_sha256,
    ))
    return {
        "output": str(output), "packSha256": pack["packSha256"],
        "prescoreSha256": prescore_sha256, "evidenceSha256": evidence_sha256,
        "cases": 30, "answers": 90, "boards": 30,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--prescore", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(
        args.review, args.prescore, args.cases, args.queries, args.output,
    ), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
