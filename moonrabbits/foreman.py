# -*- coding: utf-8 -*-
"""
MoonRabbits Foreman（工头）模块
================================
职责：听懂用户问题 → 决定调用哪些工具（Tool Calling）→ 决定派哪些专家 → 输出带元数据的执行计划。

三级后端降级链（永不离线）：
  1. cloud  —— DeepSeek-V4-Flash，Radeon Cloud 免费共享 API（OpenAI 兼容，吃官方 +20 加分）
  2. local  —— 实例本地 vLLM @ http://localhost:8001/v1（Qwen AWQ，纯本地兜底）
  3. rules  —— 关键词规则路由（零依赖，永远可用）

集成方式（纯增量，不改现有函数）：
  from foreman import Foreman
  foreman = Foreman(handlers={
      "kb_search": my_chroma_search_fn,      # (query, top_k) -> list[{"id":..., "text":...}]
      "extract_colors": extract_colors,      # app.py 里已有的函数 (img_bytes) -> colors
  })
  plan = foreman.plan(user_query, session_ctx={"history": [...], "has_image": False})
  # plan["tool_calls"] 里每条都是一次可上镜的工具调用记录（🔧 badge 数据）
  # plan["context_injection"] 可直接拼进给 run_chain 的 prompt
"""

import json
import os
import re
import time
import urllib.request
import urllib.error

# ---------------------------------------------------------------- 配置

RADEON_BASE_URL = "https://developer.amd.com.cn/radeon/api/v1/chat/completions"
RADEON_MODEL = "DeepSeek-V4-Flash"
LOCAL_VLLM_URL = "http://localhost:8001/v1/chat/completions"
LOCAL_MODEL = "Qwen/Qwen2.5-14B-Instruct-AWQ"  # 实例 vLLM 实际 served-model-name（已核对）

DEFAULT_TIMEOUT = 45


def _load_key():
    """从环境变量或工作区文件读 key，优先环境变量。key 绝不进代码、不进 git。"""
    k = os.environ.get("RADEON_API_KEY", "").strip()
    if k:
        return k
    for p in (
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "radeon_api_key.txt"),
        "/persistent/moonrabbits/radeon_api_key.txt",
        "/workspace/persistent/moonrabbits/radeon_api_key.txt",
    ):
        try:
            with open(p, "r", encoding="utf-8") as f:
                k = f.read().strip()
                if k:
                    return k
        except OSError:
            continue
    return ""


# ---------------------------------------------------------------- 内置工具（纯 Python，零外部依赖）

_FIVE_COLORS = [
    # (名称, 五行, 色相范围[度], 象征)
    ("青", "木", (160, 290), "生长、东方、春——雨过天青"),
    ("赤", "火", ((0, 25), (330, 360)), "礼乐、南方、夏——丹心赤诚"),
    ("黄", "土", ((25, 70),), "中和、中央、长夏——厚德载物"),
    ("白", "金", None, "收敛、西方、秋——光而不耀"),   # 低饱和度高明度
    ("黑", "水", None, "藏蕴、北方、冬——玄之又玄"),   # 低明度
]


def five_color_map(hex_color):
    """hex → 中华五色观映射。内置实现，确定性工具。"""
    import colorsys

    h = hex_color.lstrip("#")
    if len(h) != 6:
        return {"ok": False, "error": f"bad hex: {hex_color}"}
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    hue, light, sat = hh * 360, ll, ss
    if light > 0.85 and sat < 0.25:
        name, elem, meaning = "白", "金", _FIVE_COLORS[3][3]
    elif light < 0.15:
        name, elem, meaning = "黑", "水", _FIVE_COLORS[4][3]
    else:
        name, elem, meaning = "黄", "土", _FIVE_COLORS[2][3]
        for cname, celem, ranges, cmean in _FIVE_COLORS[:3]:
            for rg in (ranges if isinstance(ranges, tuple) and isinstance(ranges[0], tuple) else (ranges,)):
                if rg[0] <= hue < rg[1]:
                    name, elem, meaning = cname, celem, cmean
                    break
            else:
                continue
            break
    return {
        "ok": True,
        "hex": f"#{h.lower()}",
        "five_color": name,
        "element": elem,
        "meaning": meaning,
        "hsv": {"h": round(hue, 1), "s": round(sat, 2), "l": round(light, 2)},
    }


_DYNASTIES = [
    ("夏", -2070, -1600), ("商", -1600, -1046), ("周", -1046, -256),
    ("秦", -221, -206), ("汉", -206, 220), ("三国", 220, 280),
    ("晋", 266, 420), ("南北朝", 420, 589), ("隋", 581, 618),
    ("唐", 618, 907), ("五代十国", 907, 979), ("宋", 960, 1279),
    ("辽", 907, 1125), ("金", 1115, 1234), ("元", 1271, 1368),
    ("明", 1368, 1644), ("清", 1636, 1912),
]

_REIGN_HINTS = {
    "永乐": ("明", 1403, 1424), "宣德": ("明", 1426, 1435), "成化": ("明", 1465, 1487),
    "康熙": ("清", 1662, 1722), "雍正": ("清", 1723, 1735), "乾隆": ("清", 1736, 1795),
    "开元": ("唐", 713, 741), "贞观": ("唐", 627, 649), "大观": ("宋", 1107, 1110),
}


def dynasty_lookup(query):
    """朝代/年号/公元年份 → 朝代纪年信息。内置实现，确定性工具。"""
    q = str(query).strip()
    for reign, (dyn, y1, y2) in _REIGN_HINTS.items():
        if reign in q:
            return {"ok": True, "query": q, "dynasty": dyn, "reign": reign,
                    "year_range": [y1, y2], "note": f"{reign}为{dyn}朝年号（{y1}–{y2}年）"}
    m = re.search(r"(1?\d{3})\s*年?", q)
    if m:
        y = int(m.group(1))
        for name, y1, y2 in _DYNASTIES:
            if y1 <= y <= y2:
                return {"ok": True, "query": q, "year": y, "dynasty": name,
                        "note": f"公元{y}年属{name}朝（{y1}–{y2}年）"}
        return {"ok": False, "query": q, "error": "年份超出内置朝代表范围"}
    for name, y1, y2 in _DYNASTIES:
        if name in q:
            return {"ok": True, "query": q, "dynasty": name, "year_range": [y1, y2]}
    return {"ok": False, "query": q, "error": "未识别朝代/年号/年份"}


# ---------------------------------------------------------------- 工具注册表（OpenAI function-calling schema）

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "kb_search",
            "description": "检索 MoonRabbits 本地 ChromaDB 文化知识库（陶瓷史/五色观，约4万条），返回带 [KB-id] 的引用条目。涉及任何文化、历史、工艺事实时必须先调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索语句"},
                    "top_k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_colors",
            "description": "从用户上传的图片提取主色（色彩基因），返回 hex 色值列表。用户传图或提到图片/器物颜色时调用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "five_color_map",
            "description": "把 hex 色值映射到中华五色观（青赤黄白黑/五行），返回象征意义。拿到色值后调用。",
            "parameters": {
                "type": "object",
                "properties": {"hex_color": {"type": "string"}},
                "required": ["hex_color"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dynasty_lookup",
            "description": "朝代/年号/公元年份换算（如 永乐→明1403-1424）。涉及年代、朝代、纪年时调用。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]

BUILTIN_TOOLS = {"five_color_map": five_color_map, "dynasty_lookup": dynasty_lookup}


# ---------------------------------------------------------------- 后端调用

def _chat(url, model, messages, key=None, tools=None, timeout=DEFAULT_TIMEOUT):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload = {"model": model, "messages": messages, "temperature": 0.2}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ---------------------------------------------------------------- 工头

_PLAN_PROMPT = """你是 MoonRabbits 的工头（Foreman），负责给四个文化专家（考据官Historian、格物官Scientist、灵感官Muse、讲述者Narrator）派活。
根据用户问题，输出一个 JSON 计划（只输出 JSON，不要任何解释）：
{
  "route": "full_pipeline" | "quick_answer",
  "tool_calls": [{"tool": "kb_search"|"dynasty_lookup"|"five_color_map", "args": {...}}],
  "experts": ["historian","scientist","muse","narrator"] 或其子集,
  "reason": "一句话说明"
}
规则：涉及文化/历史/工艺事实 → 必须含 kb_search；涉及年代 → 含 dynasty_lookup；涉及颜色/五色 → 含 five_color_map；
简单寒暄/追问语气词 → quick_answer 且 tool_calls 可为空。full_pipeline 时 experts 必须是全员。
用户问题：{query}
会话上下文摘要：{ctx}"""


class Foreman:
    def __init__(self, handlers=None, key=None):
        self.handlers = handlers or {}
        self.key = key if key is not None else _load_key()
        self.backend = None  # 最近一次实际用的后端

    # ---- 工具执行 ----
    def _run_tool(self, name, args, session_ctx):
        t0 = time.time()
        rec = {"tool": name, "args": args, "status": "ok", "latency_ms": 0}
        try:
            if name in BUILTIN_TOOLS:
                result = BUILTIN_TOOLS[name](**args)
            elif name == "kb_search":
                fn = self.handlers.get("kb_search")
                if not fn:
                    raise RuntimeError("kb_search handler 未接入")
                result = fn(args.get("query", ""), int(args.get("top_k", 5)))
            elif name == "extract_colors":
                fn = self.handlers.get("extract_colors")
                img = session_ctx.get("image_bytes")
                if not fn or img is None:
                    raise RuntimeError("无图片或 extract_colors handler 未接入")
                result = fn(img)
            else:
                raise RuntimeError(f"未知工具 {name}")
            rec["result"] = result
            rec["badge"] = f"🔧 {name}({', '.join(f'{k}={v}' for k, v in args.items())})"
        except Exception as e:  # 工具失败不致命，记录后继续
            rec["status"] = "error"
            rec["error"] = str(e)[:200]
        rec["latency_ms"] = round((time.time() - t0) * 1000)
        return rec

    # ---- 计划生成：三级降级 ----
    def plan(self, query, session_ctx=None):
        session_ctx = session_ctx or {}
        ctx_brief = str(session_ctx.get("history", ""))[:400]
        if session_ctx.get("has_image"):
            ctx_brief += " [用户上传了图片]"

        # 1) 云端 DeepSeek（原生 function calling 优先）
        if self.key:
            try:
                plan = self._plan_cloud_native(query, ctx_brief)
                self.backend = "cloud:DeepSeek-V4-Flash(native-tools)"
                return self._execute(plan, session_ctx)
            except Exception:
                pass
            try:
                plan = self._plan_json_mode(RADEON_BASE_URL, RADEON_MODEL,
                                            query, ctx_brief, key=self.key)
                self.backend = "cloud:DeepSeek-V4-Flash(json-mode)"
                return self._execute(plan, session_ctx)
            except Exception:
                pass
        # 2) 本地 vLLM
        try:
            plan = self._plan_json_mode(LOCAL_VLLM_URL, LOCAL_MODEL, query, ctx_brief)
            self.backend = "local:vllm-awq(json-mode)"
            return self._execute(plan, session_ctx)
        except Exception:
            pass
        # 3) 规则兜底（永远可用）
        self.backend = "rules:fallback"
        return self._execute(self._plan_rules(query, session_ctx), session_ctx)

    def _plan_cloud_native(self, query, ctx_brief):
        messages = [
            {"role": "system", "content": "你是 MoonRabbits 工头。先调用你需要的工具，工具结果会用于后续专家流水线。"},
            {"role": "user", "content": f"{query}\n\n[上下文] {ctx_brief}"},
        ]
        resp = _chat(RADEON_BASE_URL, RADEON_MODEL, messages,
                     key=self.key, tools=TOOL_SCHEMAS)
        msg = resp["choices"][0]["message"]
        calls = []
        for tc in (msg.get("tool_calls") or []):
            calls.append({"tool": tc["function"]["name"],
                          "args": json.loads(tc["function"].get("arguments") or "{}")})
        if not calls and not session_ctx_neutral(query):
            calls = [{"tool": "kb_search", "args": {"query": query, "top_k": 5}}]
        return {"route": "full_pipeline", "tool_calls": calls,
                "experts": ["historian", "scientist", "muse", "narrator"],
                "reason": "cloud native tool-calling"}

    def _plan_json_mode(self, url, model, query, ctx_brief, key=None):
        prompt_text = (_PLAN_PROMPT.replace("{query}", query)
                                  .replace("{ctx}", ctx_brief))  # [kimi-fix] 模板含字面 JSON 花括号，str.format 会 KeyError；改用 replace
        resp = _chat(url, model,
                     [{"role": "user", "content": prompt_text}],
                     key=key)
        text = resp["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", text, re.S)
        plan = json.loads(m.group(0))
        plan.setdefault("route", "full_pipeline")
        plan.setdefault("tool_calls", [])
        plan.setdefault("experts", ["historian", "scientist", "muse", "narrator"])
        return plan

    def _plan_rules(self, query, session_ctx):
        q = query.lower()
        calls = []
        culture_kw = ("瓷", "青花", "白瓷", "敦煌", "壁", "釉", "窑", "丝", "故宫",
                      "china", "porcelain", "blanc", "dunhuang", "silk", "glaze")
        era_kw = ("朝", "年号", "永乐", "康熙", "乾隆", "唐", "宋", "明", "清",
                  "dynasty", "reign", "世纪", "bc", "ad")
        color_kw = ("颜色", "色彩", "五色", "hex", "color", "青", "赤", "黄", "白", "黑")
        if any(k in q for k in culture_kw):
            calls.append({"tool": "kb_search", "args": {"query": query, "top_k": 5}})
        if any(k in q for k in era_kw):
            calls.append({"tool": "dynasty_lookup", "args": {"query": query}})
        if any(k in q for k in color_kw) and session_ctx.get("last_hex"):
            calls.append({"tool": "five_color_map",
                          "args": {"hex_color": session_ctx["last_hex"]}})
        if session_ctx.get("has_image"):
            calls.insert(0, {"tool": "extract_colors", "args": {}})
        chatty = len(query) < 12 and not calls
        return {"route": "quick_answer" if chatty else "full_pipeline",
                "tool_calls": calls,
                "experts": ["narrator"] if chatty else ["historian", "scientist", "muse", "narrator"],
                "reason": "rule-based routing"}

    # ---- 执行工具并汇总 ----
    def _execute(self, plan, session_ctx):
        records, snippets = [], []
        for c in plan.get("tool_calls", []):
            rec = self._run_tool(c["tool"], c.get("args", {}), session_ctx)
            records.append(rec)
            if rec["status"] == "ok":
                snippets.append(f"[{rec['tool']}] {json.dumps(rec['result'], ensure_ascii=False)[:600]}")
        plan["tool_calls"] = records
        plan["backend"] = self.backend
        plan["context_injection"] = "\n".join(snippets)
        plan["ui_badges"] = [r.get("badge", f"🔧 {r['tool']}") for r in records]
        return plan


def session_ctx_neutral(query):
    return len(query.strip()) < 4


# ---------------------------------------------------------------- 自测
if __name__ == "__main__":
    f = Foreman(handlers={})
    print("key found:", bool(f.key))
    print(json.dumps(f._plan_rules("永乐年间的青花瓷有什么特点？",
                                   {"last_hex": "#4a6fa5"}), ensure_ascii=False, indent=2))
    print(json.dumps(five_color_map("#4a6fa5"), ensure_ascii=False))
    print(json.dumps(dynasty_lookup("永乐"), ensure_ascii=False))
    if f.key:
        plan = f.plan("德化白瓷和景德镇白瓷有什么区别？")
        print("backend:", plan["backend"])
        print("badges:", plan["ui_badges"])
