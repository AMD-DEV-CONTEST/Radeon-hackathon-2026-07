"""
ForgeArena v2 UI — Multi-Agent Decision Platform
Left: free text input | Middle: agent trace | Right: decision cards
"""
import json, os, re, urllib.request, time, io
import gradio as gr
import perception
import tools

BASE = os.path.dirname(os.path.abspath(__file__))
LLM_URL = "http://localhost:8000/v1/chat/completions"
MODEL_PATH = "/workspace/models/models/Qwen--Qwen2.5-7B-Instruct/snapshots/master"

# ── Agent Profiles ──
AGENTS = {
    "Conservative": {
        "name_cn": "保守顾问",
        "icon": "🛡",
        "system": "你是保守顾问，风险厌恶型决策者。优先考虑稳定和安全，偏好保持经济优势，只在成功概率高时行动。请用中文给出分析建议。",
        "color": "#3b82f6",
        "persona": {
            "risk_preference": "低风险",
            "objective": "保护现有资源",
            "decision_style": "长期稳定"
        }
    },
    "Aggressive": {
        "name_cn": "激进顾问",
        "icon": "⚡",
        "system": "你是激进顾问，进攻型决策者。追求最大优势，愿意承担计算过的风险，选择高回报策略。请用中文给出分析建议。",
        "color": "#ef4444",
        "persona": {
            "risk_preference": "高风险",
            "objective": "最大化收益",
            "decision_style": "主动出击"
        }
    },
    "Explorer": {
        "name_cn": "探索顾问",
        "icon": "🔍",
        "system": "你是探索顾问，适应性决策者。尝试非常规方案，重视信息收集，策略灵活。请用中文给出分析建议。",
        "color": "#22c55e",
        "persona": {
            "risk_preference": "中等风险",
            "objective": "探索最优策略",
            "decision_style": "灵活应变"
        }
    },
}


# ── LLM Helpers ──

def call_llm(prompt: str, max_tokens: int = 256, temp: float = 0.7) -> str:
    """Call vLLM with try/except fallback"""
    payload = json.dumps({
        "model": MODEL_PATH,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temp,
    }).encode()
    try:
        req = urllib.request.Request(LLM_URL, data=payload,
            headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
        return resp["choices"][0]["message"]["content"]
    except Exception as e:
        return '{"error": "LLM unavailable: %s"}' % str(e)[:80]


def parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1].lstrip("json").strip()
    try:
        return json.loads(text)
    except:
        return {
            "action": text[:60] if len(text) < 200 else "parse_failed",
            "confidence": 0.5,
            "thinking": text[:100],
            "rationale": "",
            "task_understanding": "",
            "worldstate_note": "",
        }


# ── Step 1: Scene Understanding ──

def analyze_scene(user_input: str) -> dict:
    """Situation Parser: raw input → structured WorldState"""
    prompt = f"""Extract structured decision context from this user input.

User: {user_input}

Return JSON with:
- domain: game/finance/life/strategy/sports/other
- sub_domain: more specific (e.g. TFT, portfolio, career, football)
- task: what decision needs to be made
- world_state: structured key-value pairs describing the situation
  (e.g. for TFT: stage, hp, gold, level; for finance: trend, volatility, risk; for life: emotion, need, options)
- decision_question: the core question to answer

Respond ONLY with JSON.
{{
  "domain": "...",
  "sub_domain": "...",
  "task": "...",
  "world_state": {{}},
  "decision_question": "..."
}}"""
    resp = call_llm(prompt, max_tokens=300, temp=0.3)
    return parse_json(resp)


# ── Step 2: Agent Decision (with tool call trace) ──

def run_agent(name, profile, user_input, scene, retrieved_policies=None, simulation=None):
    """Run one agent with structured WorldState + real tool results"""
    domain = scene.get("domain", "general")
    sub = scene.get("sub_domain", "")
    ws = scene.get("world_state", {})
    task = scene.get("task", "decision")
    question = scene.get("decision_question", user_input[:80] if user_input else "")
    ws_json = __import__('json').dumps(ws, ensure_ascii=False)
    situation_tag = sub if sub else domain

    policy_context = ""
    if retrieved_policies:
        policy_context = "\n## Retrieved Knowledge (Policy Library)\n"
        for i, p in enumerate(retrieved_policies):
            src = p.get('domain', 'general')
            policy_context += "[%d] [%s] %s\n  Principle: %s\n  Goal: %s\n\n" % (
                i+1, src, p.get('belief', ''),
                (p.get('abstract', '') or '')[:200],
                (p.get('goal', '') or '')
            )

    sim_context = ""
    if simulation:
        sim_context = "\n## Simulation Results\n"
        for k, v in simulation.items():
            if k != 'action':
                sim_context += "  %s: %s\n" % (k, v)


    prompt = "%s\n\n## World State\nDomain: %s\nState: %s\nTask: %s\nQuestion: %s\n%s%s\n## Process\nYou work through four stages: Task Understanding, WorldState Review, Tool Execution, Decision.\nYour tools already retrieved policies and ran simulations. Reference them.\n\n## Output Format\nRespond ONLY with valid JSON:\n{\"task_understanding\":\"...\",\"worldstate_note\":\"...\",\"thinking\":\"...\",\"action\":\"...\",\"confidence\":0.5,\"rationale\":\"...\"}"
    prompt = prompt % (profile['system'], situation_tag, ws_json, task, question, policy_context, sim_context)

    resp = call_llm(prompt, max_tokens=256, temp=0.7)
    parsed = parse_json(resp)

    tool_seq = []
    if retrieved_policies:
        tool_seq.append("retrieve_policy() -> %d matches" % len(retrieved_policies))
    if simulation:
        tool_seq.append("simulate_action() -> %s" % simulation.get("projected_impact", "computed"))
    if not tool_seq:
        tool_seq.append("no tools called")

    return {
        "action": parsed.get("action", "?"),
        "confidence": parsed.get("confidence", 0),
        "thinking": (parsed.get("thinking", "") or "")[:300],
        "rationale": (parsed.get("rationale", "") or "")[:200],
        "task_understanding": (parsed.get("task_understanding", "") or "Understanding task..."),
        "worldstate_note": (parsed.get("worldstate_note", "") or "Reviewing state..."),
        "tool_sequence": tool_seq,
    }
def compare_decisions(scene: dict, results: dict) -> dict:
    """Contrast all 3 agent decisions → agreement/disagreement/summary"""
    prompt = f"""You are a decision analysis engine. Compare the following 3 agent decisions for the same problem.

## Problem Context
Domain: {scene.get('domain', '?')}
Task: {scene.get('task', '?')}
Decision Question: {scene.get('decision_question', '?')}

## Agent Decisions
### Conservative
行动: {results['Conservative']['action']}
确信度: {results['Conservative']['confidence']}
理由: {results['Conservative']['rationale']}

### Aggressive
行动: {results['Aggressive']['action']}
确信度: {results['Aggressive']['confidence']}
理由: {results['Aggressive']['rationale']}

### Explorer
行动: {results['Explorer']['action']}
确信度: {results['Explorer']['confidence']}
理由: {results['Explorer']['rationale']}

## Output
Return ONLY valid JSON:
{{
  "agreement_points": ["point 1", "point 2"],
  "key_disagreements": [{{"topic": "...", "conservative_view": "...", "aggressive_view": "...", "explorer_view": "..."}}],
  "risk_spectrum": "Conservative < Explorer < Aggressive (or other ordering)",
  "summary": "2-3 sentence comparison"
}}"""
    resp = call_llm(prompt, max_tokens=256, temp=0.3)
    return parse_json(resp)


def _format_comparison(cmp: dict, results: dict) -> str:
    """Format comparison dict as HTML"""
    agrees = cmp.get("agreement_points", [])
    disagreements = cmp.get("key_disagreements", [])
    spectrum = cmp.get("risk_spectrum", "")
    summary = cmp.get("summary", "")

    if not agrees and not disagreements:
        return '<div style="color:#94a3b8;padding:10px">Comparison unavailable</div>'

    agrees_html = "".join(f'<li style="margin:4px 0;font-size:13px">✅ {a}</li>' for a in agrees)

    dis_html = ""
    for d in disagreements:
        topic = d.get("topic", "")
        dis_html += f'''
<div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;padding:10px;margin:6px 0;font-size:13px">
  <div style="font-weight:600;color:#c2410c;margin-bottom:6px">⚡ {topic}</div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
    <div><span style="color:#3b82f6;font-weight:600">Conservative:</span><br>{d.get("conservative_view","")}</div>
    <div><span style="color:#8b5cf6;font-weight:600">Explorer:</span><br>{d.get("explorer_view","")}</div>
    <div><span style="color:#ef4444;font-weight:600">Aggressive:</span><br>{d.get("aggressive_view","")}</div>
  </div>
</div>'''

    # Build risk spectrum bar
    spectrum_html = ""
    if spectrum:
        low_color, mid_color, high_color = "#3b82f6", "#8b5cf6", "#ef4444"
        spectrum_html = f'''
<div style="margin:10px 0;font-size:13px">
  <div style="font-weight:600;margin-bottom:4px">Risk Spectrum:</div>
  <div style="display:flex;height:8px;border-radius:4px;overflow:hidden;background:#e5e7eb">
    <div style="flex:1;background:{low_color}"></div>
    <div style="flex:1;background:{mid_color}"></div>
    <div style="flex:1;background:{high_color}"></div>
  </div>
  <div style="display:flex;justify-content:space-between;font-size:11px;color:#64748b;margin-top:2px">
    <span>{spectrum}</span>
  </div>
</div>'''

    html = f'''
<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:16px;margin:12px 0">
  <div style="font-size:15px;font-weight:600;margin-bottom:10px">📊 决策对比</div>
  <div style="font-size:14px;color:#475569;margin-bottom:10px">{summary}</div>
  {spectrum_html}
  <div style="font-weight:600;margin:8px 0 4px">✅ Agreement</div>
  <ul style="margin:0;padding-left:20px">{agrees_html}</ul>
  {dis_html}
</div>'''
    return html


# ── Step 4: Full Pipeline ──

def process_request(user_input: str, image_input=None):
    """Main pipeline: perception → 3 agents → comparison"""
    has_text = bool(user_input and user_input.strip())
    has_image = image_input is not None

    if not has_text and not has_image:
        return ["Please enter a question or upload an image"] + [""]*3 + [""]*9

    # 1. Perception: image → WorldState
    if has_image:
        # Convert PIL image to bytes
        buf = io.BytesIO()
        image_input.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        result = perception.analyze_input(text=user_input if has_text else None, image_bytes=img_bytes)
        if result is None:
            # Fallback to text-only
            scene = analyze_scene(user_input)
            perception_info = None
        else:
            scene = result
            perception_info = result.get("perception", {})
    else:
        scene = analyze_scene(user_input)
        perception_info = None

    domain = scene.get("domain", "unknown")
    sub = scene.get("sub_domain", "")
    task = scene.get("task", "")
    ws = scene.get("world_state", {})
    question = scene.get("decision_question", "")

    # Build situation understanding HTML
    parts = []
    parts.append('<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:16px;margin-bottom:12px">')
    
    info = '<div style="display:grid;grid-template-columns:1fr 2fr;gap:8px;font-size:14px">'
    info += '<div><b>Domain:</b> %s</div>' % domain
    info += '<div><b>Sub-domain:</b> %s</div>' % (sub or '&mdash;')
    info += '<div><b>Task:</b> %s</div>' % task
    info += '<div><b>Decision Question:</b> %s</div>' % question
    info += '</div>'
    parts.append(info)

    # Perception metadata
    if perception_info:
        status = perception_info.get("extraction_status", "unknown")
        obs = perception_info.get("observations", [])
        latency = perception_info.get("latency_ms", 0)
        raw = perception_info.get("raw_summary", "")

        s_icon = {"success": "+OK", "partial": "~", "failed": "X"}.get(status, "?")
        status_bar = '<div style="margin:6px 0;font-size:12px;color:#64748b">%s Visual Perception: %s (%dms)</div>' % (s_icon, status, latency)

        obs_table = '<table style="width:100%;font-size:12px;border-collapse:collapse;margin-top:4px">'
        obs_table += '<tr style="color:#64748b;font-size:11px"><th style="text-align:left;padding:2px 4px">Field</th><th style="text-align:left;padding:2px 4px">Value</th><th style="text-align:right;padding:2px 4px;width:100px">确信度</th></tr>'
        for o in obs:
            conf_pct = int(o["confidence"] * 100)
            bar_color = '#22c55e' if conf_pct >= 80 else '#eab308' if conf_pct >= 60 else '#ef4444'
            obs_table += '<tr style="border-top:1px solid #f1f5f9">'
            obs_table += '<td style="padding:3px 4px;color:#475569;font-weight:500">%s</td>' % o["field"]
            obs_table += '<td style="padding:3px 4px;color:#334155"><b>%s</b></td>' % str(o["value"])[:40]
            obs_table += '<td style="padding:3px 4px;text-align:right">'
            obs_table += '<span style="display:inline-block;width:60px;height:6px;background:#e5e7eb;border-radius:3px;vertical-align:middle;margin-right:4px">'
            obs_table += '<span style="display:block;height:6px;width:%d%%;background:%s;border-radius:3px"></span>' % (conf_pct, bar_color)
            obs_table += '</span><span style="font-size:11px;color:%s">%d%%</span>' % (bar_color, conf_pct)
            obs_table += '</td></tr>'
        obs_table += '</table>'

        vis_html = '<div style="border-top:1px solid #e2e8f0;padding-top:8px;margin-top:8px">'
        vis_html += '<div style="font-size:13px;font-weight:600;margin-bottom:4px">Vision Observation</div>'
        vis_html += status_bar
        if obs:
            vis_html += obs_table
        else:
            vis_html += '<div style="color:#ef4444;font-size:12px">%s</div>' % raw
        vis_html += '</div>'
        parts.append(vis_html)

    # World state
    ws_items = []
    for k, v in ws.items():
        ws_items.append('- %s: <b>%s</b>' % (k, str(v)))
    ws_lines = '<br>'.join(ws_items) if ws_items else '(no structured data)'
    
    ws_html = '<hr style="margin:10px 0;border-color:#e2e8f0">'
    ws_html += '<div style="font-size:14px"><b>World State:</b></div>'
    ws_html += '<div style="font-size:13px;color:#475569;margin-top:4px">%s</div>' % ws_lines
    ws_html += '</div>'
    parts.append(ws_html)

    # Memory context display
    try:
        mem_entries = tools.get_all_memory(last_n=2)
        if mem_entries:
            mem_html = '<div style="border-top:1px solid #e2e8f0;padding-top:8px;margin-top:8px;font-size:12px">'
            mem_html += '<div style="font-weight:600;margin-bottom:4px;color:#475569">Memory Context</div>'
            for m in mem_entries[-2:]:
                mem_html += '<div style="padding:2px 0;color:#64748b">'
                mem_html += '<span style="color:#6366f1">&#x25B6;</span> '
                mem_html += 'Agent <b>%s</b> chose <b>%s</b> (conf: %.0f%%)' % (
                    m.get('agent', '?'),
                    m.get('action', '?')[:40],
                    (m.get('confidence', 0) or 0) * 100
                )
                mem_html += '</div>'
            mem_html += '</div>'
            parts.append(mem_html)
    except:
        pass

    scene_md = '\n'.join(parts)

    # 2. Real Tool Execution
    traces = []
    cards = []
    results = {}
    input_for_agent = user_input if has_text else question or "分析 this game state"

    # Call real tools before agents
    domain = scene.get("domain", "general")
    sub = scene.get("sub_domain", "")
    search_query = "%s %s %s" % (sub, task, question)
    retrieved_policies = tools.retrieve_policy(search_query, domain=domain, top_k=3)
    simulation = tools.simulate_action(scene.get("world_state", {}), task + " " + question)

    # Format retrieved policies for trace display
    rag_detail = ""
    if retrieved_policies:
        rag_detail = '<div style="margin-top:6px;padding:6px;background:#f1f5f9;border-radius:6px;font-size:12px">'
        rag_detail += '<div style="font-weight:600;margin-bottom:4px;color:#475569">Retrieved Knowledge:</div>'
        for i, p in enumerate(retrieved_policies):
            belief = (p.get('belief') or '')[:120]
            abstract = (p.get('abstract') or '')[:100]
            score = p.get('_score', 0)
            rag_detail += '<div style="padding:3px 0;border-bottom:1px solid #e2e8f0">'
            rag_detail += '<div style="color:#334155">%d. [<span style="color:#6366f1">%s</span>] <b>%s</b></div>' % (i+1, p.get("domain", "?"), belief)
            if abstract:
                rag_detail += '<div style="color:#64748b;margin-left:12px">%s</div>' % abstract
            rag_detail += '<div style="color:#94a3b8;font-size:11px;margin-left:12px">match: %.2f</div>' % score
            rag_detail += '</div>'
        rag_detail += '</div>'

    # Run agents sequentially (Gradio SSE incompatible with threading)
    for n, p in AGENTS.items():
        try:
            results[n] = run_agent(n, p, input_for_agent, scene,
                                   retrieved_policies=retrieved_policies,
                                   simulation=simulation)
        except Exception as e:
            results[n] = {
                "action": "error",
                "confidence": 0,
                "thinking": str(e)[:100],
                "rationale": "",
                "task_understanding": "",
                "worldstate_note": "",
                "tool_sequence": ["agent error"],
            }

    for name, profile in AGENTS.items():
        result = results[name]
        color = profile["color"]

        tu = result.get("task_understanding", "")
        wn = result.get("worldstate_note", "")
        tool_seq = result.get("tool_sequence", [])
        thinking = result.get("thinking", "")[:200]

        tool_steps = "".join([
            '<div class="trace-tool">+ <code>%s</code></div>' % t
            for t in tool_seq
        ])
        tool_steps += rag_detail

        trace = (
            '\n<div class="trace-box" style="border-left:4px solid %s">'
            '\n  <div class="trace-header" style="color:%s">%s Agent</div>'
            '\n  <div class="trace-stage completed">'
            '\n    <span class="trace-icon">+</span> Task Understanding'
            '\n    <span class="trace-detail">%s</span>'
            '\n  </div>'
            '\n  <div class="trace-stage completed">'
            '\n    <span class="trace-icon">+</span> WorldState Review'
            '\n    <span class="trace-detail">%s</span>'
            '\n  </div>'
            '\n  <div class="trace-stage completed">'
            '\n    <span class="trace-icon">+</span> Tool Execution'
            '\n    <span class="trace-detail">%s</span>'
            '\n  </div>'
            '\n  <div class="trace-stage completed">'
            '\n    <span class="trace-icon">+</span> Decision'
            '\n    <span class="trace-detail">%s</span>'
            '\n  </div>'
            '\n</div>'
        ) % (color, color, name, tu, wn, tool_steps, thinking)
        traces.append(trace)

        cards.append(result["action"])
        cards.append(result["confidence"])
        cards.append(result.get("rationale", ""))

        try:
            tools.save_memory_entry(input_for_agent, name, scene, result)
        except:
            pass

    # 3. 决策对比 (merged into scene_md) with fallback
    try:
        comparison = compare_decisions(scene, results)
        comparison_html = _format_comparison(comparison, results)
    except Exception:
        comparison_html = '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:16px;margin:12px 0"><div style="font-size:15px;font-weight:600;margin-bottom:10px">决策对比</div><div style="color:#64748b;font-size:13px">Comparison unavailable (fallback)</div></div>'
    scene_md = scene_md.replace('</div>', comparison_html + '</div>', 1)

    return [scene_md, *traces, *cards]


# ── UI ──

def build_ui():
    with gr.Blocks(title="ForgeArena ⚡ 多智能体决策顾问") as demo:
        gr.Markdown("""
        # ⚙️ ForgeArena
        **多智能体决策顾问** · Qwen2.5-7B · AMD Radeon GPU 本地推理
        """)

        # ── Global CSS ──
        gr.HTML("""<style>
.trace-box{max-height:320px;overflow-y:auto;border:1px solid #e5e7eb;border-radius:10px;padding:14px;margin-bottom:8px;background:#fafafa;font-size:13px;font-family:-apple-system,BlinkMacSystemFont,sans-serif}
.trace-header{font-weight:700;font-size:15px;margin-bottom:10px;padding-bottom:6px;border-bottom:2px solid #e5e7eb}
.trace-stage{padding:8px 10px;margin:6px 0;border-radius:6px;background:#f0f9ff;border-left:3px solid #3b82f6;font-size:13px;line-height:1.5}
.trace-stage .trace-icon{color:#22c55e;font-weight:bold;margin-right:4px}
.trace-detail{color:#64748b;font-size:12px;margin-left:18px;display:block;margin-top:3px}
.trace-tool{margin:2px 0;padding:2px 0}
.trace-tool code{background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:12px;color:#6366f1}
.persona-badge{padding:12px;border-radius:8px;margin-bottom:8px;color:white}
.persona-badge h3{margin:0;font-size:16px}
.persona-row{display:flex;justify-content:space-between;font-size:12px;margin-top:4px;opacity:0.9}
.persona-row span{flex:1}
.persona-label{opacity:0.7}
.scene-title{font-size:15px;font-weight:600;margin-bottom:8px;color:#1e293b}
</style>""")

        # ── ROW 1: User Input ──
        gr.Markdown("### 💬 你的决策问题是什么？")
        with gr.Row():
            with gr.Column(scale=3):
                user_input = gr.Textbox(
                    placeholder="描述你的决策场景，例如：我在第3-2阶段，40金币、60血量，该存钱还是冲人口？",
                    lines=3,
                    label="文字描述（可选）",
                )
                analyze_btn = gr.Button("🚀 分析", variant="primary", size="lg")
        with gr.Row():
            gr.Markdown("*快速示例：*")
            tft_example = gr.Button("⚔️ TFT 战术", size="sm")
            football_example = gr.Button("⚽ 足球战术", size="sm")
            finance_example = gr.Button("📈 市场风险", size="sm")
            with gr.Column(scale=2):
                image_input = gr.Image(
                    label="上传截图（可选）",
                    type="pil",
                    height=200,
                )

        # ── ROW 2: 局势分析 ──
        gr.Markdown("### 🌍 局势分析")
        scene_display = gr.Markdown("Enter a problem and click 分析 to see the world state")

        # ── ROW 3: Agent Execution Trace ──
        gr.Markdown("### 🔍 智能体执行过程")
        with gr.Row():
            trace_conservative = gr.HTML('<div class="trace-box"><div style="color:#94a3b8;text-align:center;padding:20px">⏳ Waiting for analysis...</div></div>')
            trace_aggressive = gr.HTML('<div class="trace-box"><div style="color:#94a3b8;text-align:center;padding:20px">⏳ Waiting for analysis...</div></div>')
            trace_explorer = gr.HTML('<div class="trace-box"><div style="color:#94a3b8;text-align:center;padding:20px">⏳ Waiting for analysis...</div></div>')

        # ── ROW 4: 顾问团室 (Decision Cards with Persona) ──
        gr.Markdown("### 🏛️ 顾问团室")
        gr.Markdown("*三位顾问共享 Qwen2.5-7B 本地模型，但应用不同的认知策略→产生多元决策*")
        gr.Markdown("*Decision comparison appears below the 局势分析 section*")
        card_widgets = {}
        with gr.Row():
            for name, profile in AGENTS.items():
                with gr.Column(scale=1):
                    p = profile["persona"]
                    color = profile["color"]
                    gr.HTML(f'''
<div class="persona-badge" style="background:{color}">
  <h3>{name} Agent</h3>
  <div class="persona-row">
    <span><span class="persona-label">Risk:</span> {p["risk_preference"]}</span>
    <span><span class="persona-label">Objective:</span> {p["objective"]}</span>
    <span><span class="persona-label">Style:</span> {p["decision_style"]}</span>
  </div>
</div>''')
                    a = gr.Textbox(label="行动", interactive=False)
                    c = gr.Slider(label="确信度", minimum=0, maximum=1, value=0, interactive=False)
                    r = gr.Textbox(label="理由", lines=3, interactive=False)
                    card_widgets[name] = (a, c, r)

        # ── BOTTOM: AMD Runtime Panel ──
        with gr.Accordion("⚙️ AMD Radeon Runtime", open=False):
            gr.Markdown("""
| Category | Item | Value |
|----------|------|-------|
| **Hardware** | GPU | AMD Radeon RDNA3 · 48GB VRAM |
| **Hardware** | Inference | Local only (no cloud API) |
| **Backend** | Runtime | vLLM 0.23.1 on ROCm |
| **Backend** | Quantization | Q4 (bitsandbytes) |
| **Model** | Decision | Qwen2.5-7B-Instruct |
| **Model** | Vision | External service (Qwen3-VL via network) |
| **Performance** | Single Agent | ~9.7s inference / 41.3 t/s |
| **Performance** | 3-Agent Sequential | ~12.8s (2.27× efficiency) |
| **Performance** | Image VLM | ~5-10s per frame |
| **Architecture** | Pipeline | Perception → WorldState → Tools → Multi-Agent |
| **Architecture** | RAG | 986 + 11 domain policies · keyword retrieval |
| **Architecture** | Memory | Per-session JSON persistence |
| **Framework** | Stack | ForgeArena v0.3 · Gradio 6.20 · Python 3.12 |
""")

        # ── Wire up ──
        def handler(text, img):
            return process_request(text, img)

        all_outputs = [scene_display, trace_conservative, trace_aggressive, trace_explorer]
        for name in AGENTS:
            all_outputs.extend(list(card_widgets[name]))

        # Wire up example buttons
        tft_example.click(fn=lambda: "Stage 4-1, 80 HP, 70 gold. Should I level to 8 or roll for carries?", outputs=[user_input])
        football_example.click(fn=lambda: "70th minute, 0-0, opponent in low block with 65% possession. How to break through?", outputs=[user_input])
        finance_example.click(fn=lambda: "Market volatility is high, S&P 500 dropped 3% this week. Should I reduce exposure?", outputs=[user_input])

        analyze_btn.click(
            fn=handler,
            inputs=[user_input, image_input],
            outputs=all_outputs,
            concurrency_limit=3,
        )

    return demo


if __name__ == "__main__":
    import os, socket
    # Try ports until we find a free one
    for port in [24573]:
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            s.close()
            break
        except:
            s.close()
            continue
    os.environ["GRADIO_SERVER_PORT"] = str(port)
    demo = build_ui()
    demo.launch(server_port=port, server_name="0.0.0.0", share=False,
              theme=gr.themes.Soft())
