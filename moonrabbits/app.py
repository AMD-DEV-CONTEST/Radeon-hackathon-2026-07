#!/usr/bin/env python3
"""MoonRabbits Web MVP — single-file server, stdlib only (+ optional Pillow for color).

Endpoints:
  GET  /            -> index.html
  POST /api/chat    -> {message, session_id, image_colors?} -> 4-agent chain JSON
  POST /api/upload  -> image file -> dominant colors + five-color mapping

Run:  /workspace/persistent/venv/bin/python app.py
Open: http://<host>:8000/  (or via Jupyter /proxy/8000/)
"""
import json, re, time, uuid, io, os
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

BASE = Path("/workspace/persistent/moonrabbits")
PORT = 8000

import sys
sys.path.insert(0, str(BASE))
import moonrabbits_agents as ma  # reuse retrieve/chat/kb_block
from foreman import Foreman  # [kimi-08] 工头模块（纯增量，回滚=删本行+B/C三处+foreman.py）

SESSIONS = {}  # session_id -> [{"user":..., "story":...}]

# ---------------- [kimi-09] SESSIONS 落盘持久化（JSON 文件，原子写，纯增量） ----------------
SESSIONS_FILE = BASE / "sessions_store.json"

def _sessions_load():
    try:
        if SESSIONS_FILE.exists():
            data = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                SESSIONS.update(data)
    except Exception:
        pass

def _sessions_save():
    try:
        tmp = SESSIONS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(SESSIONS, ensure_ascii=False), encoding="utf-8")
        tmp.replace(SESSIONS_FILE)
    except Exception:
        pass

_sessions_load()

FIVE_COLORS = {
    "青": (70, 130, 120), "赤": (180, 60, 50), "黄": (210, 170, 60),
    "白": (235, 230, 220), "黑": (40, 40, 45),
}

# ---------------------------------------------------------------------------
# Dual-gate safety layer (input gate + output gate).
# Keyword-based v1; roadmap: swap in a semantic classifier (e.g. NeMo-style
# rail or a small local model) — the gate interface stays identical.
# ---------------------------------------------------------------------------
SENSITIVE_TOPICS = {
    "politics": [
        "政治", "政党", "领导人", "主席", "总统", "首相", "政权", "革命",
        "选举", "投票", "议员", "国会", "参议院", "众议院",
        "共产党", "共和党", "民主党", "民进党", "国民党",
        "美国政府", "中国政府", "英国政府", "日本政府",
        "特朗普", "川普", "拜登", "奥巴马", "普京", "泽连斯基",
        "军费", "制裁", "政变", "游行", "示威",
        "politics", "president", "election", "regime", "propaganda",
        "trump", "biden", "putin", "congress", "senate", "vote",
        "communist party", "democrat", "republican", "sanctions",
        "government of", "us government", "chinese government",
    ],
    "religion_extremism": [
        "邪教", "极端组织", "恐怖袭击", "自杀式", "圣战",
        "cult", "terrorist", "terrorism", "extremist", "jihad",
    ],
    "violence": [
        "杀人", "炸弹", "制毒", "毒品配方", "武器制作", "枪支",
        "kill", "bomb", "murder", "weapon", "explosive", "drug recipe",
    ],
    "adult": [
        "色情", "裸体", "约炮",
        "porn", "nude", "nsfw", "explicit sexual",
    ],
    "harm": [
        "自残", "自杀方法", "伤害他人",
        "suicide method", "self-harm how", "hurt someone",
    ],
}

# Flat lookup for the output gate (keep the old variable name for compat).
SENSITIVE = [w for words in SENSITIVE_TOPICS.values() for w in words]

# ---------------- [kimi-10] cult 误杀修复：仅集合内词条按 \b 词边界匹配，其余词条逻辑不变 ----------------
WORD_BOUNDARY = {"cult"}
bs = chr(92)  # 反斜杠（避开传输层转义吞字）

def _word_hit(w, low_text):
    if w in WORD_BOUNDARY:
        pat = bs + "b" + re.escape(w) + bs + "b"
        return re.search(pat, low_text, flags=re.IGNORECASE) is not None
    return w.lower() in low_text

def _word_pattern(w):
    if w in WORD_BOUNDARY:
        return bs + "b" + re.escape(w) + bs + "b"
    return re.escape(w)

def check_input(text):
    """Input gate: return [(word, category), ...] for sensitive hits."""
    low = text.lower()
    hits = []
    for cat, words in SENSITIVE_TOPICS.items():
        for w in words:
            if _word_hit(w, low):  # [kimi-10]
                hits.append((w, cat))
    return hits


def scrub_output(text):
    """Output gate: mask sensitive words, return (cleaned_text, hits)."""
    hits = []
    cleaned = text
    for cat, words in SENSITIVE_TOPICS.items():
        for w in words:
            if _word_hit(w, cleaned.lower()):  # [kimi-10]
                hits.append((w, cat))
                mask = "＊" * len(w) if any('一' <= c <= '鿿' for c in w) else "*" * len(w)
                cleaned = re.sub(_word_pattern(w), mask, cleaned, flags=re.IGNORECASE)  # [kimi-10]
    return cleaned, hits


def refusal_message(zh):
    if zh:
        return ("这个问题超出了文化遗产叙事系统的服务范围。"
                "MoonRabbits 专注于器物、色彩与文明的故事——"
                "不如问我一件瓷器、一种颜色，或者一段中西互鉴的往事？")
    return ("That topic is outside the scope of this cultural-heritage "
            "narrative system. MoonRabbits is dedicated to the stories of "
            "artifacts, colors and civilizations — ask me about a piece of "
            "porcelain, a color, or a moment of East-West exchange instead.")


def extract_colors(img_bytes, k=5):
    try:
        from PIL import Image
    except ImportError:
        return None
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    im.thumbnail((200, 200))
    q = im.quantize(colors=k, method=2).convert("RGB")
    counts = {}
    for px in q.getdata():
        counts[px] = counts.get(px, 0) + 1
    top = sorted(counts.items(), key=lambda x: -x[1])[:k]
    out = []
    for (r, g, b), cnt in top:
        nearest = min(FIVE_COLORS, key=lambda c: (r - FIVE_COLORS[c][0]) ** 2 + (g - FIVE_COLORS[c][1]) ** 2 + (b - FIVE_COLORS[c][2]) ** 2)
        out.append({"rgb": [r, g, b], "hex": "#%02x%02x%02x" % (r, g, b),
                    "five_color": nearest, "share": round(cnt / (q.width * q.height), 3)})
    return out


# ---------------- [kimi-08] 工头全局初始化（kb_search 接 ma.retrieve 真名已核对） ----------------
try:
    FOREMAN = Foreman(handlers={
        "kb_search": lambda q, k=5: ma.retrieve(q, k),
        "extract_colors": extract_colors,
    })
except Exception:
    FOREMAN = None


def run_chain(query, session_id, color_ctx="", lang="zh"):
    cjk = any('一' <= ch <= '鿿' for ch in query)
    zh_mode = (lang == "zh") or (lang == "auto" and cjk)
    en = (lang == "en")
    auto = (lang == "auto") and not zh_mode
    hits = ma.retrieve(query)
    kb = ma.kb_block(hits)
    hist = SESSIONS.get(session_id, [])
    hist_ctx = ""
    if hist:
        if en or auto:
            prev = "\n".join(f"User asked: {h['user']}\nNarrator answered: {h['story'][:120]}..." for h in hist[-3:])
            hist_ctx = f"\n\nConversation history (stay coherent):\n{prev}"
        else:
            prev = "\n".join(f"用户曾问：{h['user']}\n讲述者曾答：{h['story'][:120]}..." for h in hist[-3:])
            hist_ctx = f"\n\n对话历史（保持连贯）：\n{prev}"

    if en or auto:
        L = ("answer in the SAME language as the user's question (French question → French answer, German → German, Japanese → Japanese)"
             if auto else "answer in English")
        sys_hist = (
            "You are the Historian of MoonRabbits, gatekeeper of cultural-heritage facts. "
            "IRON RULE: every factual sentence must end with a knowledge-base entry id in brackets, e.g. [ocr_0043_c195]. "
            "An answer with zero citations is a failed answer. "
            "Rules: 1) entries marked as keyword matches are exact full-text evidence — cite them first; "
            "2) mark unsupported content as '(no documentary evidence, speculation only)'; "
            f"3) never invent facts beyond the entries; 4) {L}, max 350 words; entry ids stay unchanged.")
        sys_sci = (
            "You are the Scientist of MoonRabbits, in charge of physics/chemistry principles and fact-checking. "
            "Rules: 1) check the Historian's dynasties, kilns, crafts and chemistry — mark each 'correct' or 'wrong + reason'; "
            f"2) add one science point a layperson can grasp; 3) {L}, max 250 words.")
        sys_muse = (
            "You are the Muse of MoonRabbits, finding emotional angles for creators. "
            "Rules: 1) based on the two experts above, give 2-3 warm narrative angles "
            "(the object and the human spirit, East-West exchange, the quiet aesthetics of 'light that does not dazzle'); "
            f"2) introduce no new 'facts'; 3) {L}, max 200 words, restrained, never hollow.")
        sys_narr = (
            "You are the Narrator of MoonRabbits, the only voice facing the user. "
            "Rules: 1) weave the three experts into a story ordinary people understand and want to share; "
            "2) facts follow the Historian — keep key [id] citations; never include anything the Scientist flagged as wrong; "
            "3) stay coherent with the conversation history if provided; "
            f"4) warm, vivid, small detail to big theme, never preachy; 5) {L}, 200-350 words.")
    else:
        sys_hist = (
            "你是 MoonRabbits 的考据官（Historian），文化遗产事实守门人。"
            "铁律：你的每一个事实句的句尾必须挂知识库条目编号，格式 [编号]。一个编号都没有的回答 = 失败回答。"
            "示范：德化白瓷始于宋代 [ocr_0043_c195]。其象牙白釉色温润 [kb_core_white_03]。"
            "其余规则：1) '命中方式：关键词'的条目是全文精确匹配证据，引用优先级最高；"
            "2) 没有依据的内容标注'（暂无文献支撑，仅为推测）'；3) 不调用外部记忆编造；"
            "4) 用中文，不超过 400 字。")
        sys_sci = (
            "你是 MoonRabbits 的格物官（Scientist），负责物理化学原理与事实核查。"
            "规则：1) 检查考据官回答中朝代、窑口、工艺、化学成分等硬伤，逐条指出'无误'或'有误+理由'；"
            "2) 补充一个普通人能听懂的科学原理点；3) 用中文，不超过 300 字。")
        sys_muse = (
            "你是 MoonRabbits 的灵感官（Muse），为创作者找感性角度。"
            "规则：1) 基于前两位的 factual 内容，给 2-3 个有温度的叙事角度（如器物与人的精神、东西方互鉴、光而不耀静水流深式美学）；"
            "2) 不得引入新的'事实'；3) 用中文，不超过 250 字，克制不空洞。")
        sys_narr = (
            "你是 MoonRabbits 的讲述者（Narrator），唯一面向用户的声音。"
            "规则：1) 把三位专家的内容织成一个普通人听得懂、愿意传播的故事；"
            "2) 事实以考据官为准，关键结论保留 [编号] 引用；格物官指出过有误的不得出现；"
            "3) 若提供了对话历史，保持话题连贯；"
            "4) 口吻轻松有温度、以小见大，不说教；5) 用中文，200-350 字。")

    if en or auto:
        historian = ma.chat(sys_hist, f"Knowledge-base entries:\n{kb}\n\nUser question: {query}{color_ctx}")
        scientist = ma.chat(sys_sci, f"User question: {query}\n\nHistorian's answer:\n{historian}")
        muse = ma.chat(sys_muse, f"User question: {query}\n\nHistorian:\n{historian}\n\nScientist:\n{scientist}")
        narrator = ma.chat(sys_narr,
            f"User question: {query}{color_ctx}{hist_ctx}\n\nHistorian:\n{historian}\n\nScientist:\n{scientist}\n\nMuse:\n{muse}\n\nFinal reminder: {L}.")
    else:
        historian = ma.chat(sys_hist, f"知识库条目：\n{kb}\n\n用户问题：{query}{color_ctx}")
        scientist = ma.chat(sys_sci, f"用户问题：{query}\n\n考据官的回答：\n{historian}")
        muse = ma.chat(sys_muse, f"用户问题：{query}\n\n考据官：\n{historian}\n\n格物官：\n{scientist}")
        narrator = ma.chat(sys_narr,
            f"用户问题：{query}{color_ctx}{hist_ctx}\n\n考据官：\n{historian}\n\n格物官：\n{scientist}\n\n灵感官：\n{muse}")

    # Output gate: scrub every expert + narrator voice before it leaves.
    all_flags = []
    historian, h = scrub_output(historian)
    all_flags += h
    scientist, h = scrub_output(scientist)
    all_flags += h
    muse, h = scrub_output(muse)
    all_flags += h
    narrator, h = scrub_output(narrator)
    all_flags += h
    flagged = [f"output-scrubbed: {w} ({cat})" for w, cat in all_flags]
    SESSIONS.setdefault(session_id, []).append({"user": query, "story": narrator})
    _sessions_save()  # [kimi-09] 落盘
    return {
        "retrieval": [{"id": h["id"], "via": h["via"], "similarity": h.get("similarity"),
                       "source": h["source"], "preview": h["content"][:120]} for h in hits],
        "historian": historian, "scientist": scientist, "muse": muse,
        "narrator": narrator, "safety_flags": flagged,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            p = BASE / "index.html"
            body = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        if self.path == "/api/chat":
            try:
                d = json.loads(raw or b"{}")
                q = (d.get("message") or "").strip()
                if not q:
                    return self._json({"error": "empty message"}, 400)
                sid = d.get("session_id") or uuid.uuid4().hex[:8]
                colors = d.get("image_colors")
                color_ctx = ""
                if colors:
                    chips = "、".join(f"{c['five_color']}({c['hex']})" for c in colors)
                    color_ctx = f"\n\n（用户上传图片的提取色彩基因：{chips}，请结合色彩线索作答）"
                t0 = time.time()
                lang = (d.get("lang") or "zh").lower()
                # Input gate: refuse sensitive topics before burning the 4-expert chain.
                in_hits = check_input(q)
                if in_hits:
                    zh = (lang == "zh") or (lang != "en" and any('一' <= ch <= '鿿' for ch in q))
                    result = {
                        "retrieval": [],
                        "historian": "", "scientist": "", "muse": "",
                        "narrator": refusal_message(zh),
                        "safety_flags": [f"input-blocked: {w} ({cat})" for w, cat in in_hits],
                        "session_id": sid, "lang": lang,
                        "elapsed_sec": round(time.time() - t0, 1),
                    }
                    return self._json(result)
                # ---------------- [kimi-08] 工头计划：工具调用 + 上下文注入（失败不致命） ----------------
                foreman_meta = None
                if FOREMAN is not None:
                    try:
                        plan = FOREMAN.plan(q, session_ctx={
                            "history": SESSIONS.get(sid, []),
                            "has_image": bool(colors),
                            "last_hex": (colors[0]["hex"] if colors else None),
                        })
                        if plan.get("context_injection"):
                            # [kimi-08b] 注入走 color_ctx 而非 query：避免中文工具结果翻转 auto 语种的 CJK 判定（法语 Q6 会变中文回答）
                            color_ctx = color_ctx + "\n\n[工头工具结果]\n" + plan["context_injection"]
                        foreman_meta = {"backend": plan.get("backend"),
                                        "badges": plan.get("ui_badges", []),
                                        "route": plan.get("route")}
                    except Exception as fe:
                        foreman_meta = {"backend": "error:" + str(fe)[:80], "badges": [], "route": None}
                result = run_chain(q, sid, color_ctx, lang)
                result["session_id"] = sid
                result["lang"] = lang
                result["elapsed_sec"] = round(time.time() - t0, 1)
                if foreman_meta:
                    result["foreman"] = foreman_meta
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)}, 500)
        elif self.path == "/api/upload":
            try:
                d = json.loads(raw or b"{}")
                import base64
                img = base64.b64decode(d.get("image_b64", ""))
                colors = extract_colors(img)
                if colors is None:
                    return self._json({"error": "Pillow not installed"}, 500)
                self._json({"colors": colors})
            except Exception as e:
                self._json({"error": str(e)}, 500)
        else:
            self.send_error(404)


if __name__ == "__main__":
    print(f"MoonRabbits web listening on 0.0.0.0:{PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
