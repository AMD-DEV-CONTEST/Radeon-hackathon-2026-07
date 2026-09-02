#!/usr/bin/env python3
"""
ForgeArena Web UI — 多智能体决策顾问展示界面
三层结构：用户输入 → 三位 AI 顾问卡片 → 综合决策总结
依赖：Flask, vLLM (ROCm)
"""
import sys, os, json, urllib.request
sys.path.insert(0, os.path.dirname(__file__))

VLLM_API = os.environ.get("VLLM_API", "http://localhost:8000/v1/chat/completions")
MODEL = os.environ.get("MODEL_PATH", "")

PERSONAS = [
    {"id": "conservative", "name": "保守顾问", "icon": "🛡️", "style": "blue",
     "tagline": "稳扎稳打，安全第一",
     "prompt": "你是保守顾问，风险厌恶型决策者。优先考虑稳定和安全，偏好保持经济优势，只在成功概率高时行动。请用中文分析。"},
    {"id": "aggressive", "name": "激进顾问", "icon": "⚡", "style": "red",
     "tagline": "主动出击，优势最大化",
     "prompt": "你是激进顾问，进攻型决策者。追求最大优势，愿意承担计算过的风险，选择高回报策略。请用中文分析。"},
    {"id": "explorer", "name": "探索顾问", "icon": "🔍", "style": "green",
     "tagline": "灵活应变，探索最优解",
     "prompt": "你是探索顾问，适应性决策者。尝试非常规方案，重视信息收集，策略灵活。请用中文分析。"}
]

def llm_call(messages, max_tokens=512):
    if not MODEL:
        return "（请先设置 MODEL_PATH 环境变量指向本地模型路径）"
    data = json.dumps({"model": MODEL, "messages": messages,
                       "max_tokens": max_tokens, "temperature": 0.7}).encode()
    req = urllib.request.Request(VLLM_API, data=data,
                                 headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
    return resp["choices"][0]["message"]["content"]

def ask_agents(scenario, stage, hp, gold):
    context = f"局势：{stage}阶段，血量{hp}，金币{gold}"
    results = []
    for p in PERSONAS:
        reply = llm_call([
            {"role": "system", "content": p["prompt"]},
            {"role": "user", "content": f"{context}\n问题：{scenario}\n分析后给出建议。"}
        ])
        results.append({"name": p["name"], "icon": p["icon"],
                        "style": p["style"], "tagline": p["tagline"],
                        "advice": reply})
    return results

def synthesize(agents, scenario):
    opinions = "\n".join([f"## {a['name']}: {a['advice']}" for a in agents])
    return llm_call([
        {"role": "system", "content": "你是首席分析师。综合三位顾问意见给出最终建议：共识点、分歧点、最终建议。中文。"},
        {"role": "user", "content": f"问题：{scenario}\n\n{opinions}"}
    ])

# ── Flask App ──
try:
    from flask import Flask, request, jsonify, send_file
    app = Flask(__name__)

    @app.route("/")
    def index():
        return send_file(os.path.join(os.path.dirname(__file__), "forgearena_ui.html"))

    @app.route("/api/analyze", methods=["POST"])
    def analyze():
        body = request.get_json(silent=True) or {}
        try:
            agents = ask_agents(
                body.get("scenario", ""),
                body.get("stage", "2-5"),
                int(body.get("hp", 60)),
                int(body.get("gold", 40))
            )
            summary = synthesize(agents, body.get("scenario", ""))
            return jsonify({"agents": agents, "summary": summary})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    if __name__ == "__main__":
        import socket
        s = socket.socket(); s.settimeout(2)
        if s.connect_ex(("localhost", 8000)) != 0:
            print("WARNING: vLLM not running on port 8000")
        s.close()
        app.run(host="0.0.0.0", port=24680, debug=False)

except ImportError:
    print("Flask not installed. Install: pip install flask")
    print("Or use: python forgearena.py  (CLI mode)")
