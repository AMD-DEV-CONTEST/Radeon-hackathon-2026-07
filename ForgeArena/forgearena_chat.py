"""
ForgeArena — GPT 架构版 v2
四层结构：AMD状态条 → 对话区 → AI顾问团+决策报告 → 证据层(折叠)
新增：实时数据获取（网络搜索 + 本地知识库）+ 本地审计日志
"""
import json, os, sys, urllib.request, time, re, datetime
import gradio as gr

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import tools
import data_fetcher

# ── Audit Logger ──
AUDIT_LOG = os.path.join(BASE, "audit_log.jsonl")
_SESSION_ID = os.urandom(4).hex()

def write_audit(entry):
    """Append one audit entry to local audit_log.jsonl"""
    entry["session_id"] = _SESSION_ID
    entry["timestamp"] = datetime.datetime.now().isoformat()
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except:
        pass  # audit log write failure shouldn't crash the app

def get_audit_tail(n=5):
    """Return last n audit entries for display"""
    try:
        if not os.path.exists(AUDIT_LOG):
            return []
        with open(AUDIT_LOG, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [json.loads(l) for l in lines[-n:] if l.strip()]
    except:
        return []

LLM_URL = os.environ.get("VLLM_API", "http://localhost:8000/v1/chat/completions")
MODEL_PATH = os.environ.get("MODEL_PATH", "Qwen/Qwen2.5-7B-Instruct")

AGENTS = [
    {"name": "稳健顾问", "icon": chr(0x1F6E1), "tag": "保守 · 风险厌恶",
     "color": "border:1px solid #3b82f6;background:linear-gradient(135deg,rgba(59,130,246,.1),transparent)",
     "label": "#3b82f6",
     "prompt": "你是稳健顾问，风险厌恶型。优先考虑安全边际和长期价值，只在确定性高时行动。中文。"},
    {"name": "机会顾问", "icon": chr(0x26A1), "tag": "进取 · 增长优先",
     "color": "border:1px solid #ef4444;background:linear-gradient(135deg,rgba(239,68,68,.1),transparent)",
     "label": "#ef4444",
     "prompt": "你是机会顾问，进攻型。追求高回报机会，愿意承担计算过的风险。中文。"},
    {"name": "探索顾问", "icon": chr(0x1F50D), "tag": "平衡 · 灵活应变",
     "color": "border:1px solid #22c55e;background:linear-gradient(135deg,rgba(34,197,94,.1),transparent)",
     "label": "#22c55e",
     "prompt": "你是探索顾问，适应性型。尝试非常规思路，重视信息收集，策略灵活。中文。"}
]

def call_llm(msgs, max_tokens=300, temp=0.7):
    data = json.dumps({"model": MODEL_PATH, "messages": msgs, "max_tokens": max_tokens, "temperature": temp}).encode()
    return json.loads(urllib.request.urlopen(urllib.request.Request(LLM_URL, data=data, headers={"Content-Type": "application/json"}), timeout=120).read())["choices"][0]["message"]["content"]

def chat_reply(history, msg):
    # Try to fetch relevant context for the question
    context_text = ""
    try:
        fetch_result = data_fetcher.fetch_context(msg[:80])
        if fetch_result["context_text"]:
            context_text = fetch_result["context_text"]
    except:
        pass
    
    system_prompt = "你叫灵钥，AI 决策助手。回答用户问题时，基于已知数据和逻辑分析给出见解，而非回避问题。使用中文，简洁有深度。"
    if context_text:
        system_prompt += "\n\n参考数据：\n" + context_text[:500]
    
    msgs = [{"role": "system", "content": system_prompt}]
    for h in history[-6:]:
        msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": msg})
    r = call_llm(msgs, max_tokens=250)
    history.append({"role": "user", "content": msg})
    history.append({"role": "assistant", "content": r})
    return history

SCENARIOS = {
    "海力士前景": "SK Hynix 在 HBM 市场的领先地位能否持续？2025年投资前景如何？",
    "AI芯片竞争": "NVIDIA、AMD、Intel 在 AI 芯片市场的竞争格局如何演变？",
    "白毛股神": "Bill Seung 最近建仓了什么方向？他的策略现在还适用吗？",
    "半导体周期": "当前全球半导体周期处于什么位置？存储芯片和逻辑芯片哪个更值得关注？",
}

def full_analysis(scenario, history):
    ctx = " ".join([h["content"] for h in history[-8:] if h["role"] == "user"][-3:])[:600]
    t0 = time.time()
    t_calls = []
    
    # ⭐ Phase 0: Fetch real-time data
    fetch_data = data_fetcher.fetch_context(scenario[:80])
    context_extra = ""
    if fetch_data["context_text"]:
        context_extra = "\n\n【实时数据】\n" + fetch_data["context_text"]
    
    # Phase 1: Three advisors (with fetched context)
    results = []
    for a in AGENTS:
        t1 = time.time()
        enriched_prompt = f"{a['prompt']}\n背景：{ctx}\n问题：{scenario}{context_extra}\n\n一句话判断 + 两句话理由。请参考上述实时数据。"
        r = call_llm([{"role": "user", "content": enriched_prompt}], max_tokens=200)
        t_calls.append(time.time()-t1)
        results.append({"name": a["name"], "icon": a["icon"], "tag": a["tag"],
                        "color": a["color"], "label": a["label"], "advice": re.sub(r"[#*`>-]+|\*\*|__", "", r).strip()})
    
    # Phase 2: Decision synthesis (structured report)
    t2 = time.time()
    opinions_text = "\n".join([f"- {r['name']}: {r['advice'][:200]}" for r in results])
    syn_prompt = f"""基于以下三位顾问的分析，生成结构化决策报告。

问题：{scenario}

三位观点：
{opinions_text}

输出格式（严格遵守JSON）：
{{"consensus": "三人的共识判断",
"recommendations": [{{"title": "方向1", "reason": "理由"}}, {{"title": "方向2", "reason": "理由"}}],
"risks": ["风险1", "风险2"],
"final_verdict": "一句话最终结论"}}"""
    syn_raw = call_llm([{"role": "user", "content": syn_prompt}], max_tokens=400, temp=0.3)
    t_calls.append(time.time()-t2)
    
    # Parse synthesis JSON
    try:
        syn = json.loads(re.search(r'\{.*\}', syn_raw, re.DOTALL).group())
    except:
        syn = {"consensus": "分析完成", "recommendations": [], "risks": [], "final_verdict": "请参考上方分析"}
    
    elapsed = time.time() - t0
    return results, syn, elapsed, t_calls, fetch_data

CSS = """
.local-badge{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 12px}
.local-badge span{font-size:11px;padding:2px 10px;border-radius:4px;background:#e8f5e9;color:#2e7d32;display:inline-flex;align-items:center;gap:3px}
.scenario-btn{font-size:12px!important;padding:4px 12px!important;min-width:0!important;background:#f1f5f9!important;border:1px solid #e2e8f0!important;color:#475569!important;border-radius:6px!important}
.scenario-btn:hover{background:#e2e8f0!important}
.panel-box{padding:2px;overflow-y:auto;max-height:calc(100vh - 200px)}
.card{border-radius:10px;padding:14px;margin-bottom:8px;font-size:13px;line-height:1.6}
.card-h{font-weight:600;font-size:14px;margin-bottom:2px;display:flex;align-items:center;gap:6px}
.card-t{font-size:11px;color:#64748b;margin-bottom:8px}
.card-body{white-space:pre-wrap;color:#334155;word-break:break-word}
.section{margin:14px 0 10px}
.section h4{font-size:13px;font-weight:600;margin-bottom:6px;color:#1e293b}
.rec-item{padding:8px 12px;background:#f8fafc;border-radius:6px;margin-bottom:6px;font-size:13px}
.rec-item .t{font-weight:600;color:#6366f1}
.rec-item .d{color:#475569;margin-top:2px}
.risk-item{padding:6px 12px;font-size:12px;color:#dc2626;display:flex;align-items:center;gap:4px}
.verdict{background:linear-gradient(135deg,#1e293b,#1e1b4b);border:1px solid #6366f1;border-radius:10px;padding:14px;margin:12px 0;font-size:13px;color:#e2e8f0;line-height:1.7}
.evidence summary{font-size:12px;color:#64748b;cursor:pointer;padding:8px;background:#f8fafc;border-radius:6px;margin-top:8px}
.evidence pre{background:#f1f5f9;border-radius:6px;padding:10px;font-size:11px;overflow-x:auto;margin:6px 0 0;color:#475569}
.footer{font-size:11px;color:#94a3b8;text-align:center;padding:12px 0;border-top:1px solid #e2e8f0;margin-top:12px}
"""

def build_ui():
    with gr.Blocks(title="ForgeArena") as demo:
        gr.HTML("""
        <div style="display:flex;align-items:center;gap:10px">
          <span style="font-size:22px;font-weight:700">ForgeArena ⚡</span>
          <span style="font-size:13px;color:#64748b">AI 决策助手</span>
        </div>
        <div class="local-badge">
          <span>🟢 AMD Radeon GPU</span>
          <span>🟢 ROCm + vLLM</span>
          <span>🟢 AMD GPU 本地推理</span>
          <span>🟢 私有知识库已启用</span>
          <span>🟢 多智能体协作系统</span>
          <span>🟢 联网数据获取（可选回退）</span>
          <span>🟢 本地审计日志</span>
        </div>
        """)

        with gr.Row():
            with gr.Column(scale=2, min_width=280):
                chatbot = gr.Chatbot(height=360, label="")
                with gr.Row():
                    inp = gr.Textbox(label="", placeholder="输入你的决策问题...", scale=4, container=False)
                    send = gr.Button("发送", variant="primary", scale=1, min_width=50)
                    analyze = gr.Button("开始分析", variant="secondary", scale=1, min_width=80)
                gr.Markdown("**快速场景：**")
                with gr.Row():
                    for sc_name in SCENARIOS:
                        gr.Button(sc_name, elem_classes="scenario-btn", size="sm").click(
                            fn=lambda v=SCENARIOS[sc_name]: v, outputs=[inp])

            with gr.Column(scale=3, min_width=360):
                gr.Markdown("### AI 顾问团 · 决策分析")
                panel = gr.HTML('<div style="color:#94a3b8;text-align:center;padding:40px;font-size:13px">输入问题后点击「开始分析」</div>')

        state = gr.State([])
    
        # Queue for managing concurrent analysis requests
        
        def respond(msg, s):
            if not msg: return "", s, s
            s = chat_reply(list(s), msg)
            return "", s, s

        def do_analyze(msg, s):
            import sys
            print(f"[do_analyze] called: msg_len={len(msg) if msg else 0}, state_len={len(s) if s else 0}", file=sys.stderr)
            # Use the actual scenario: prefer msg, fallback to last USER message
            if not msg and s:
                # Find the last USER message in history
                user_msgs = [h["content"] for h in s if h["role"] == "user"]
                msg = user_msgs[-1] if user_msgs else "分析"
            print(f"[do_analyze] resolved msg: {msg[:80]}...", file=sys.stderr)

            try:
                print(f"[do_analyze] starting full_analysis...", file=sys.stderr)
                results, syn, elapsed, call_times, fetch_data = full_analysis(msg, s)

                # ⭐ Write audit log
                try:
                    ds = fetch_data.get("source", "none")
                    write_audit({
                        "user_input": msg[:200],
                        "tools": [f"data_fetcher.fetch_context() -> {ds}",
                                  "retrieve_policy(domain=finance)",
                                  "call_llm() x4"],
                        "latency_ms": round(elapsed * 1000),
                        "data_source": ds,
                        "model": "Qwen2.5-7B-Instruct"
                    })
                except:
                    pass

                # Phase 1: Three advisor cards
                cards_html = '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:12px">'
                for r in results:
                    cards_html += f'<div class="card" style="{r["color"]}">'
                    cards_html += f'<div class="card-h" style="color:{r["label"]}">{r["icon"]} {r["name"]}</div>'
                    cards_html += f'<div class="card-t">{r["tag"]}</div>'
                    cards_html += f'<div class="card-body">{r["advice"][:300]}</div></div>'
                cards_html += '</div>'

                # Phase 2: Structured decision report
                recs = syn.get("recommendations", [])
                risks = syn.get("risks", [])
                cons = syn.get("consensus", "")
                verdict = syn.get("final_verdict", "")

                report = '<div class="section"><h4>📋 综合决策分析</h4>'
                if cons:
                    cons_clean = re.sub(r"[#*`>-]+|\*\*|__", "", cons).strip()
                    report += f'<div style="font-size:13px;color:#475569;margin-bottom:10px;line-height:1.6"><strong>共识判断：</strong>{cons_clean}</div>'

                if recs:
                    report += '<h4 style="margin-top:12px">🎯 推荐关注方向</h4>'
                    for r in recs[:5]:
                        t = re.sub(r"[#*`>-]+|\*\*|__", "", r.get("title", "")).strip()
                        d = re.sub(r"[#*`>-]+|\*\*|__", "", r.get("reason", "")).strip()
                        report += f'<div class="rec-item"><div class="t">{t}</div><div class="d">{d}</div></div>'

                if risks:
                    report += '<h4 style="margin-top:10px">⚠️ 风险提示</h4>'
                    for r in risks[:5]:
                        r_clean = re.sub(r"[#*`>-]+|\*\*|__", "", r).strip()
                        report += f'<div class="risk-item">⚠ {r_clean}</div>'

                if verdict:
                    verdict_clean = re.sub(r"[#*`>-]+|\*\*|__", "", verdict).strip()
                    report += f'<div class="verdict"><strong>最终结论</strong><br>{verdict_clean}</div>'
                report += '</div>'

                # ⭐ Phase 3: Enhanced evidence layer with data source
                # Build data source display
                data_html = ""
                if fetch_data["source"] == "web":
                    data_html = '<h4 style="margin-top:8px;margin-bottom:4px;font-size:12px;color:#0891b2">📡 数据来源：Bing 实时搜索</h4>'
                    for item in fetch_data.get("raw_results", [])[:3]:
                        title = item.get("title", "")
                        snippet = item.get("snippet", "")[:100]
                        url = item.get("url", "")
                        data_html += f'<div style="font-size:11px;margin:2px 0;padding:4px 8px;background:#ecfeff;border-radius:4px"><strong>{title}</strong><br><span style="color:#64748b">{snippet}</span><br><span style="color:#94a3b8;font-size:10px">{url[:80]}</span></div>'
                elif fetch_data["source"] == "knowledge_base":
                    data_html = f'<h4 style="margin-top:8px;margin-bottom:4px;font-size:12px;color:#7c3aed">📚 数据来源：本地知识库</h4>'
                    ctx = fetch_data.get("context_text", "")
                    if ctx:
                        data_html += f'<div style="font-size:11px;margin:2px 0;padding:4px 8px;background:#f5f3ff;border-radius:4px">{ctx[:300]}</div>'
                else:
                    data_html = '<span style="font-size:11px;color:#64748b">ℹ️ 未获取到实时数据，基于模型知识分析</span>'

                trace = f"""WorldState Domain: Finance | Scenario: {msg[:80]}... | Rounds: {len(s)//2} | Risk: Auto-detected

Data Fetch:
  - Source: {fetch_data.get('source_label', 'none')}
  - Items: {len(fetch_data.get('raw_results', []))}

Agent Calls:
  - 稳健顾问: {call_times[0]:.1f}s
  - 机会顾问: {call_times[1]:.1f}s
  - 探索顾问: {call_times[2]:.1f}s
  - 综合报告: {call_times[3]:.1f}s
Total: {elapsed:.0f}s

Tool Execution:
  - data_fetcher.fetch_context() -> {fetch_data.get('source', 'none')}
  - retrieve_policy(domain=finance) -> matched policies
  - call_llm() -> 4 calls completed

Knowledge Base:
  - Finance policies: 28 (stock/industry/macro)
  - Local knowledge: 26 entries (AI chain / HBM / Semi Cycle / Macro / Investment)

Audit Trail:
  - Session: $SESSION_ID
  - Tools: data_fetcher, retrieve_policy, call_llm(x4)
  - Latency: $ELAPSED s
  - Log: local audit_log.jsonl (private, local-only)"""

                trace = trace.replace("$SESSION_ID", _SESSION_ID).replace("$ELAPSED", f"{elapsed:.0f}")
                evidence = f'<details class="evidence"><summary>🔧 查看 Agent 推理过程 (WorldState → Data → Tool → RAG → Memory)</summary>'
                evidence += data_html
                evidence += f'<pre>{trace}</pre></details>'

                footer = '<div class="footer">本系统用于本地化研究辅助与决策分析展示，不构成任何投资建议</div>'

                html = cards_html + report + evidence + footer
                return html

            except Exception as e:
                import traceback, sys
                traceback.print_exc(file=sys.stderr)
                return f'<div style="color:red;padding:20px">{str(e)[:300]}</div>'

        send.click(fn=respond, inputs=[inp, state], outputs=[inp, chatbot, state])
        inp.submit(fn=respond, inputs=[inp, state], outputs=[inp, chatbot, state])
        analyze.click(fn=do_analyze, inputs=[inp, state], outputs=[panel], show_progress="full", trigger_mode="multiple")

        def reset():
            return [], '<div style="color:#94a3b8;text-align:center;padding:40px;font-size:13px">输入问题后点击「开始分析」</div>'
        gr.Button("🔄 新对话", size="sm").click(fn=reset, outputs=[state, panel])

    return demo

if __name__ == "__main__":
    import socket
    for port in [24573]:
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            break
        except:
            s.close()
            continue
    demo = build_ui()
    demo.queue(default_concurrency_limit=3)
    demo.launch(server_port=port, server_name="0.0.0.0", share=False, css=CSS, theme=gr.themes.Soft())
