#!/usr/bin/env python3
"""Doubao-style UI: history · modes · image OCR upload · Enter to send."""

from __future__ import annotations

import html
import json
import os
import re
import sys
import threading
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.apps.modes import DEFAULT_MODE, UI_MODES, get_app_mode
from src.apps.judge_script import prompts_for_mode

SESSIONS: dict[str, dict] = {}
CURRENT_ID = ""
MODE = DEFAULT_MODE
READY = False
LOADING = False
LOAD_ERROR = ""
ORCH = None
UPLOAD_DIR: Path | None = None
_lock = threading.Lock()
_MODE_IDS = {m.id for m in UI_MODES}


class LazyVectorStore:
    def __init__(self, settings) -> None:
        self._settings = settings
        self._inner = None
        self._lock = threading.Lock()

    def _get(self):
        if self._inner is not None:
            return self._inner
        with self._lock:
            if self._inner is not None:
                return self._inner
            from src.rag.store import VectorStore

            print("[boot] loading knowledge base embedder (background/first use)...", flush=True)
            store = VectorStore(self._settings)
            sample = self._settings.resolve(self._settings.paths.sample_docs)
            store.ensure_sample_docs(sample)
            self._inner = store
            print("[boot] knowledge base ready", flush=True)
            return self._inner

    def warm(self) -> None:
        try:
            self._get()
        except Exception as exc:  # noqa: BLE001
            print(f"[boot] kb warm failed: {exc}", flush=True)

    def search(self, *args, **kwargs):
        return self._get().search(*args, **kwargs)

    def count(self) -> int:
        return self._get().count()

    def add_directory(self, *args, **kwargs):
        return self._get().add_directory(*args, **kwargs)

    def add_file(self, *args, **kwargs):
        return self._get().add_file(*args, **kwargs)


def _new_session(mode: str = DEFAULT_MODE) -> str:
    global CURRENT_ID, MODE
    sid = uuid.uuid4().hex  # full 128-bit hex
    MODE = mode if mode in _MODE_IDS else DEFAULT_MODE
    with _lock:
        SESSIONS[sid] = {"title": "新对话", "mode": MODE, "messages": []}
        CURRENT_ID = sid
    return sid


def _ensure_session() -> str:
    global CURRENT_ID
    if CURRENT_ID and CURRENT_ID in SESSIONS:
        return CURRENT_ID
    return _new_session(MODE)


def _load_runtime() -> None:
    global READY, LOADING, LOAD_ERROR, ORCH, UPLOAD_DIR
    with _lock:
        if READY or LOADING:
            return
        LOADING = True
    try:
        from src.agent.agent import PrivateAgent
        from src.agent.multi_agent import MultiAgentOrchestrator
        from src.agent.tools import ToolRegistry
        from src.config import load_settings
        from src.llm.backend import build_llm
        from src.memory.memory import SessionMemory
        from src.privacy.audit import AuditTrail
        from src.skills import SkillRegistry

        settings = load_settings()
        UPLOAD_DIR = settings.resolve(settings.paths.upload_dir)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        try:
            from src.apps.judge_script import ensure_judge_ocr_image

            ensure_judge_ocr_image(UPLOAD_DIR)
        except Exception as exc:  # noqa: BLE001
            print(f"[boot] sample OCR image skipped: {exc}", flush=True)
        memory = SessionMemory(settings.resolve(settings.agent.memory_path))
        skills = SkillRegistry(settings.resolve(settings.paths.generated_projects))
        audit = AuditTrail(settings.resolve("data/memory/audit.jsonl"))

        print("[boot] loading local model on Radeon/ROCm...", flush=True)
        llm = build_llm(settings.llm)

        store = LazyVectorStore(settings)
        tools = ToolRegistry(store, memory, UPLOAD_DIR, skill_registry=skills)
        agent = PrivateAgent(llm, tools, memory, settings.agent.max_steps, audit=audit)
        ORCH = MultiAgentOrchestrator(agent, tools)
        READY = True
        print("[boot] ready (chat/vision available; KB warms in background)", flush=True)
        threading.Thread(target=store.warm, daemon=True).start()
    except Exception:  # noqa: BLE001
        LOAD_ERROR = traceback.format_exc()
        print("[boot] failed:\n", LOAD_ERROR)
    finally:
        LOADING = False


def ensure_runtime_async() -> None:
    if READY or LOADING:
        return
    threading.Thread(target=_load_runtime, daemon=True).start()


def suggestions_for(mode: str) -> list[str]:
    """Prefer judge/video prompts so Web page matches Demo video."""
    primary = prompts_for_mode(mode)
    m = get_app_mode(mode)
    extra = list(m.demo_prompts) if m else []
    out: list[str] = []
    for s in primary + extra:
        if s not in out:
            out.append(s)
    return out[:4]


MAX_UPLOAD_BYTES = int(os.getenv("PLA_MAX_UPLOAD_MB", "10")) * 1024 * 1024
DEMO_TOKEN = os.getenv("PLA_DEMO_TOKEN", "").strip()


def _check_token(handler: BaseHTTPRequestHandler, data: dict | None = None) -> bool:
    if not DEMO_TOKEN:
        return True
    hdr = (handler.headers.get("X-PLA-Token") or "").strip()
    body_tok = ""
    if isinstance(data, dict):
        body_tok = str(data.get("token") or "").strip()
    return hdr == DEMO_TOKEN or body_tok == DEMO_TOKEN


def _save_upload(filename: str, data: bytes) -> Path:
    assert UPLOAD_DIR is not None
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"file too large (max {MAX_UPLOAD_BYTES // (1024*1024)}MB)")
    safe = re.sub(r"[^\w.\-]+", "_", Path(filename).name) or f"img_{uuid.uuid4().hex[:8]}.png"
    if ".." in safe:
        raise ValueError("invalid filename")
    path = UPLOAD_DIR / safe
    path.write_bytes(data)
    return path


def page(notice: str = "", q: str = "") -> bytes:
    sid = _ensure_session()
    sess = SESSIONS[sid]
    mode = sess.get("mode") or MODE
    m = get_app_mode(mode)
    title = m.title if m else "对话"
    messages = sess.get("messages") or []

    hist_items = []
    for s_id, s in reversed(list(SESSIONS.items())):
        on = " on" if s_id == sid else ""
        label = html.escape(s.get("title") or "新对话")
        hist_items.append(f'<a class="nav{on}" href="?sid={s_id}">{label}</a>')
    if not hist_items:
        hist_items.append('<div class="nav muted">暂无对话记录</div>')

    if not READY:
        status = notice or ("模型加载中，请稍候自动刷新…" if LOADING else "正在准备模型…")
        if LOAD_ERROR:
            status = "模型加载失败，请查看终端日志后重试。"
        stage = (
            f'<div class="hero"><h1>PrivateLocalAgent</h1>'
            f'<p>{html.escape(status)}</p></div>'
        )
    elif messages:
        rows = []
        for item in messages:
            u = item[0] if isinstance(item, (list, tuple)) else item.get("q", "")
            a = item[1] if isinstance(item, (list, tuple)) else item.get("a", "")
            rows.append(f'<div class="row user"><div class="bubble user">{html.escape(u)}</div></div>')
            rows.append(f'<div class="row bot"><div class="bubble bot">{html.escape(a)}</div></div>')
        stage = f'<div class="chat" id="chat">{"".join(rows)}</div>'
    else:
        chips = "".join(
            f'<button type="button" class="sug" data-q="{html.escape(s, quote=True)}">{html.escape(s)}</button>'
            for s in suggestions_for(mode)
        )
        hint = "可上传图片做本地 OCR" if mode == "vision" else html.escape(title)
        stage = f"""
        <div class="hero">
          <h1>有什么我能帮你的吗？</h1>
          <p>PrivateLocalAgent · {hint}</p>
          <div class="sugs">{chips}</div>
        </div>"""

    mode_bar = []
    for app in UI_MODES:
        on = " on" if app.id == mode else ""
        mode_bar.append(
            f'<a class="skill{on}" href="?sid={sid}&mode={html.escape(app.id)}">{html.escape(app.title)}</a>'
        )

    disabled = "disabled" if not READY else ""
    refresh = "" if READY or LOAD_ERROR else '<meta http-equiv="refresh" content="3"/>'
    body = f"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>PrivateLocalAgent</title>
{refresh}
<style>
:root {{
  --bg:#f4f6f8; --panel:#fff; --line:#e6ebf0; --text:#1f2329; --muted:#8a9199;
  --accent:#0f766e; --soft:#ccfbf1; --chip:#f0f3f6;
}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;color:var(--text);background:var(--bg);
font-family:"PingFang SC","Microsoft YaHei","Segoe UI",sans-serif}}
.layout{{display:grid;grid-template-columns:240px 1fr;min-height:100vh}}
.side{{background:var(--panel);border-right:1px solid var(--line);padding:16px 12px;display:flex;flex-direction:column;gap:8px}}
.brand{{font-weight:800;font-size:18px;padding:6px 8px 4px;letter-spacing:-.03em}}
.brand small{{display:block;color:var(--muted);font-size:11px;font-weight:500;margin-top:3px}}
.btn-new{{display:block;text-align:center;text-decoration:none;background:var(--soft);color:var(--accent);
font-weight:700;border-radius:10px;padding:10px 12px;margin:4px 0 10px}}
.side h3{{margin:8px 8px 4px;font-size:12px;color:var(--muted);font-weight:600}}
a.nav,.nav{{display:block;text-decoration:none;padding:10px 12px;border-radius:10px;margin:0 0 4px;color:var(--text);
font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
a.nav.on{{background:var(--soft);color:var(--accent);font-weight:700}}
.nav.muted{{color:var(--muted)}}
.main{{display:flex;flex-direction:column;min-height:100vh}}
.top{{display:flex;justify-content:space-between;align-items:center;padding:14px 20px;
border-bottom:1px solid var(--line);background:rgba(255,255,255,.85)}}
.top h2{{margin:0;font-size:14px}} .top span{{color:var(--muted);font-size:12px}}
.stage{{flex:1;overflow:auto;padding:28px 20px 12px}}
.hero{{text-align:center;padding:56px 8px 20px}}
.hero h1{{margin:0 0 10px;font-size:34px;letter-spacing:-.04em}}
.hero p{{margin:0;color:var(--muted)}}
.hero .sync{{margin-top:8px;font-size:12px;color:var(--accent)}}
.boot{{text-align:left;max-width:560px;margin:16px auto 0;background:#0f172a;color:#e2e8f0;
padding:12px 14px;border-radius:10px;font-size:12px;overflow:auto}}
.guide{{max-height:48vh;overflow:auto;padding:0 4px}}
.gitem{{margin:0 0 8px;padding:8px;border-radius:10px;background:#f8fafc;border:1px solid var(--line)}}
.ggo{{display:block;width:100%;text-align:left;border:0;background:transparent;font:inherit;
font-weight:700;font-size:12px;color:var(--accent);cursor:pointer;padding:0}}
.gq{{margin-top:4px;font-size:11px;color:var(--muted);line-height:1.4}}
.glink{{font-size:11px;margin:8px;color:var(--muted)}}
.glink a{{color:var(--accent)}}
.gtip{{font-size:11px;margin:4px 8px 12px;color:var(--muted);line-height:1.45}}
.sugs{{max-width:760px;margin:22px auto 0;display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.sug{{cursor:pointer;text-align:left;background:var(--panel);border:1px solid var(--line);
border-radius:12px;padding:12px 14px;font:inherit;color:#334155}}
.sug:hover{{border-color:#99f6e4}}
.chat{{max-width:820px;margin:0 auto;display:flex;flex-direction:column;gap:12px}}
.row{{display:flex}} .row.user{{justify-content:flex-end}}
.bubble{{max-width:78%;padding:12px 14px;border-radius:16px;line-height:1.55;font-size:14px;
white-space:pre-wrap;word-break:break-word}}
.bubble.user{{background:var(--accent);color:#ecfdf5;border-bottom-right-radius:4px}}
.bubble.bot{{background:var(--panel);border:1px solid var(--line);border-bottom-left-radius:4px}}
.bottom{{padding:8px 18px 18px}}
.composer{{max-width:860px;margin:0 auto;background:var(--panel);border:1px solid var(--line);
border-radius:18px;padding:12px;box-shadow:0 10px 30px rgba(15,23,42,.04)}}
.composer textarea{{width:100%;border:0;outline:none;resize:none;min-height:78px;font:inherit;background:transparent}}
.actions{{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:4px;flex-wrap:wrap}}
.left-acts{{display:flex;gap:8px;align-items:center}}
button.send,button.ghost,label.filebtn{{border:0;border-radius:999px;padding:10px 16px;font:inherit;font-weight:700;cursor:pointer}}
button:disabled,label.filebtn.disabled{{opacity:.5;cursor:not-allowed}}
.send{{background:var(--accent);color:#fff}} .ghost{{background:#eef2f8;color:#516084}}
.filebtn{{background:#eef2f8;color:#516084;display:inline-block}}
.filebtn input{{display:none}}
#filehint{{font-size:12px;color:var(--muted)}}
.skillbar{{max-width:860px;margin:12px auto 0;display:flex;flex-wrap:wrap;gap:8px}}
a.skill{{text-decoration:none;background:var(--chip);border-radius:999px;padding:8px 12px;font-size:12px;color:#475569}}
a.skill.on{{background:var(--soft);color:var(--accent);font-weight:700}}
@media (max-width:860px){{.layout{{grid-template-columns:1fr}}.side{{display:none}}.sugs{{grid-template-columns:1fr}}}}
</style></head><body>
<div class="layout">
  <aside class="side">
    <div class="brand">PrivateLocalAgent<small>Track 2 · 私有本地 Agent</small></div>
    <a class="btn-new" href="?new=1">＋ 新对话</a>
    <h3>对话记录</h3>
    {''.join(hist_items)}
  </aside>
  <section class="main">
    <div class="top">
      <h2>{html.escape(title)}</h2>
      <span>内容本地处理 · 支持图文解析</span>
    </div>
    <div class="stage" id="stage">{stage}</div>
    <div class="bottom">
      <div class="composer">
        <input type="hidden" id="sid" value="{html.escape(sid)}"/>
        <input type="hidden" id="mode" value="{html.escape(mode)}"/>
        <textarea id="q" placeholder="发消息… Enter 发送，Shift+Enter 换行" {disabled}>{html.escape(q)}</textarea>
        <div class="actions">
          <div class="left-acts">
            <label class="filebtn {'disabled' if disabled else ''}">上传图片
              <input id="file" type="file" accept="image/*" {disabled}/>
            </label>
            <span id="filehint"></span>
          </div>
          <div class="left-acts">
            <button class="ghost" type="button" id="clear" {disabled}>清空本对话</button>
            <button class="send" type="button" id="send" {disabled}>发送</button>
          </div>
        </div>
      </div>
      <div class="skillbar">{''.join(mode_bar)}</div>
    </div>
  </section>
</div>
<script>
const sid = document.getElementById('sid').value;
const mode = document.getElementById('mode').value;
const qEl = document.getElementById('q');
const stage = document.getElementById('stage');
const hint = document.getElementById('filehint');
let pendingFile = null;

function ensureChat() {{
  let chat = document.getElementById('chat');
  if (!chat) {{
    stage.innerHTML = '<div class="chat" id="chat"></div>';
    chat = document.getElementById('chat');
  }}
  return chat;
}}
function addBubble(role, text) {{
  const chat = ensureChat();
  const row = document.createElement('div');
  row.className = 'row ' + (role === 'user' ? 'user' : 'bot');
  const b = document.createElement('div');
  b.className = 'bubble ' + (role === 'user' ? 'user' : 'bot');
  b.textContent = text;
  row.appendChild(b);
  chat.appendChild(row);
  stage.scrollTop = stage.scrollHeight;
}}
async function sendText(text) {{
  const q = (text || qEl.value || '').trim();
  if (!q) return;
  qEl.value = '';
  addBubble('user', q);
  addBubble('bot', '处理中…');
  const bubbles = document.querySelectorAll('.bubble.bot');
  const last = bubbles[bubbles.length - 1];
  try {{
    const res = await fetch('api/chat', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{sid, mode, q}})
    }});
    const data = await res.json();
    last.textContent = data.answer || data.error || '无回复';
  }} catch (e) {{
    last.textContent = '发送失败，请重试';
  }}
}}
document.getElementById('send').onclick = () => sendText();
document.getElementById('clear').onclick = async () => {{
  await fetch('api/clear', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{sid}})}});
  location.href = '?sid=' + encodeURIComponent(sid) + '&mode=' + encodeURIComponent(mode);
}};
qEl.addEventListener('keydown', (e) => {{
  if (e.key === 'Enter' && !e.shiftKey) {{
    e.preventDefault();
    sendText();
  }}
}});
document.querySelectorAll('.sug').forEach(btn => {{
  btn.addEventListener('click', () => sendText(btn.dataset.q || btn.textContent));
}});
document.querySelectorAll('.ggo').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const m = btn.dataset.mode || mode;
    const q = btn.dataset.q || '';
    if (m && m !== mode) {{
      location.href = '?sid=' + encodeURIComponent(sid) + '&mode=' + encodeURIComponent(m) + '&q=' + encodeURIComponent(q);
      return;
    }}
    sendText(q);
  }});
}});
// Prefill from judge checklist navigation — auto send once ready
if (qEl.value && qEl.value.trim() && !document.getElementById('send').disabled) {{
  const pre = qEl.value.trim();
  qEl.value = '';
  setTimeout(() => sendText(pre), 300);
}}
document.getElementById('file').addEventListener('change', async (e) => {{
  const f = e.target.files && e.target.files[0];
  if (!f) return;
  hint.textContent = '上传中: ' + f.name;
  const fd = new FormData();
  fd.append('file', f);
  fd.append('sid', sid);
  fd.append('mode', mode === 'vision' ? mode : 'vision');
  try {{
    const res = await fetch('api/upload', {{method:'POST', body: fd}});
    const data = await res.json();
    hint.textContent = data.ok ? ('已上传: ' + data.name) : (data.error || '上传失败');
    if (data.ok) {{
      // Exact judge/video prompt
      if (mode !== 'vision') {{
        location.href = '?sid=' + encodeURIComponent(sid) + '&mode=vision&q=' + encodeURIComponent('解析刚上传的图片');
        return;
      }}
      await sendText('解析刚上传的图片');
    }}
  }} catch (err) {{
    hint.textContent = '上传失败';
  }}
}});
</script>
</body></html>"""
    return body.encode("utf-8")


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length > MAX_UPLOAD_BYTES:
        return {"_error": "payload too large"}
    raw = handler.rfile.read(length).decode("utf-8", errors="ignore") if length else "{}"
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


def _read_multipart(handler: BaseHTTPRequestHandler) -> tuple[str, bytes, dict]:
    """Return filename, file bytes, form fields."""
    ctype = handler.headers.get("Content-Type", "")
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length > MAX_UPLOAD_BYTES + 64_000:
        return "", b"", {"_error": "payload too large"}
    body = handler.rfile.read(length)
    m = re.search(r"boundary=(.+)", ctype)
    if not m:
        return "", b"", {}
    boundary = m.group(1).strip().encode()
    parts = body.split(b"--" + boundary)
    fields: dict[str, str] = {}
    filename, data = "", b""
    for part in parts:
        if b"Content-Disposition" not in part:
            continue
        head, _, content = part.partition(b"\r\n\r\n")
        content = content.rstrip(b"\r\n--")
        hm = re.search(br'name="([^"]+)"', head)
        if not hm:
            continue
        name = hm.group(1).decode()
        fm = re.search(br'filename="([^"]*)"', head)
        if fm:
            filename = fm.group(1).decode(errors="ignore") or "upload.bin"
            data = content
        else:
            fields[name] = content.decode("utf-8", errors="ignore")
    return filename, data, fields


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        global CURRENT_ID, MODE
        path = urlparse(self.path).path
        if path.startswith("/healthz"):
            self._text(200, "ok")
            return
        ensure_runtime_async()
        if not SESSIONS:
            _new_session(DEFAULT_MODE)
        qs = parse_qs(urlparse(self.path).query)
        if qs.get("new", [""])[0] == "1":
            _new_session(qs.get("mode", [MODE])[0] if qs.get("mode") else DEFAULT_MODE)
        if "sid" in qs and qs["sid"][0] in SESSIONS:
            CURRENT_ID = qs["sid"][0]
            MODE = SESSIONS[CURRENT_ID].get("mode") or MODE
        if "mode" in qs and qs["mode"][0] in _MODE_IDS:
            MODE = qs["mode"][0]
            sid = _ensure_session()
            SESSIONS[sid]["mode"] = MODE
        prefill = (qs.get("q") or [""])[0]
        self._html(page(q=prefill))

    def do_POST(self):  # noqa: N802
        global CURRENT_ID, MODE
        ensure_runtime_async()
        path = urlparse(self.path).path

        if path == "/api/clear":
            data = _read_json(self)
            if not _check_token(self, data):
                self._json({"ok": False, "error": "unauthorized"}, 401)
                return
            with _lock:
                sid = data.get("sid") or CURRENT_ID
                if sid in SESSIONS:
                    SESSIONS[sid]["messages"] = []
                    SESSIONS[sid]["title"] = "新对话"
                    CURRENT_ID = sid
            self._json({"ok": True})
            return

        if path == "/api/upload":
            if UPLOAD_DIR is None or not READY:
                self._json({"ok": False, "error": "服务未就绪"}, 503)
                return
            filename, data, fields = _read_multipart(self)
            if fields.get("_error"):
                self._json({"ok": False, "error": fields["_error"]}, 413)
                return
            if not _check_token(self, fields):
                self._json({"ok": False, "error": "unauthorized"}, 401)
                return
            if not data:
                self._json({"ok": False, "error": "空文件"}, 400)
                return
            try:
                saved = _save_upload(filename, data)
            except ValueError as exc:
                self._json({"ok": False, "error": str(exc)}, 400)
                return
            with _lock:
                sid = fields.get("sid") or CURRENT_ID
                mode = fields.get("mode") or MODE
                if sid in SESSIONS:
                    CURRENT_ID = sid
                if mode in _MODE_IDS:
                    MODE = mode
                    if sid in SESSIONS:
                        SESSIONS[sid]["mode"] = mode
            self._json({"ok": True, "name": saved.name})
            return

        if path == "/api/chat":
            data = _read_json(self)
            if data.get("_error"):
                self._json({"error": data["_error"]}, 413)
                return
            if not _check_token(self, data):
                self._json({"error": "unauthorized"}, 401)
                return
            with _lock:
                sid = data.get("sid") or CURRENT_ID
                mode = data.get("mode") or MODE
                q = (data.get("q") or "").strip()
                if sid in SESSIONS:
                    CURRENT_ID = sid
                else:
                    sid = _ensure_session()
                if mode in _MODE_IDS:
                    MODE = mode
                    SESSIONS[sid]["mode"] = mode
            if not READY or ORCH is None:
                self._json({"error": "模型还在加载，请稍后再发送。"}, 503)
                return
            if not q:
                self._json({"answer": ""})
                return
            if len(q) > 8000:
                self._json({"error": "问题过长"}, 400)
                return
            result = ORCH.run(q, mode=MODE)
            with _lock:
                SESSIONS[sid]["messages"].append((q, result.answer))
                if SESSIONS[sid]["title"] in {"", "新对话"}:
                    SESSIONS[sid]["title"] = q[:18] + ("…" if len(q) > 18 else "")
            self._json({"answer": result.answer})
            return

        # legacy form POST fallback
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
        data = parse_qs(raw)
        action = (data.get("action") or [""])[0]
        sid = (data.get("sid") or [CURRENT_ID])[0]
        mode = (data.get("mode") or [MODE])[0]
        if sid in SESSIONS:
            CURRENT_ID = sid
        else:
            sid = _ensure_session()
        if mode in _MODE_IDS:
            MODE = mode
            SESSIONS[sid]["mode"] = mode
        q = (data.get("q") or [""])[0].strip()
        if action == "clear":
            SESSIONS[sid]["messages"] = []
            SESSIONS[sid]["title"] = "新对话"
            self._html(page())
            return
        if not READY or ORCH is None:
            self._html(page(notice="模型还在加载，请稍后再发送。", q=q))
            return
        if q:
            result = ORCH.run(q, mode=MODE)
            SESSIONS[sid]["messages"].append((q, result.answer))
            if SESSIONS[sid]["title"] in {"", "新对话"}:
                SESSIONS[sid]["title"] = q[:18] + ("…" if len(q) > 18 else "")
        self._html(page())

    def log_message(self, fmt: str, *args) -> None:
        print("[http]", fmt % args)

    def _html(self, content: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _json(self, obj: dict, code: int = 200) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _text(self, code: int, text: str) -> None:
        raw = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    # Default localhost-only. Set PLA_ALLOW_PUBLIC=1 (and preferably PLA_DEMO_TOKEN) for tunnel demos.
    allow_public = os.getenv("PLA_ALLOW_PUBLIC", "0").lower() in {"1", "true", "yes"}
    host = os.getenv("HTTP_HOST", "0.0.0.0" if allow_public else "127.0.0.1")
    if host in {"0.0.0.0", "::"} and not allow_public:
        print("[security] refusing public bind without PLA_ALLOW_PUBLIC=1; using 127.0.0.1", flush=True)
        host = "127.0.0.1"
    port = int(os.getenv("HTTP_PORT", "7900"))
    _new_session(DEFAULT_MODE)
    print("=" * 60, flush=True)
    print("PrivateLocalAgent Web UI", flush=True)
    print(f">>> http://127.0.0.1:{port}", flush=True)
    print("=" * 60, flush=True)
    if DEMO_TOKEN:
        print("[security] PLA_DEMO_TOKEN enabled — send header X-PLA-Token on API calls")
    if allow_public:
        print("[security] PLA_ALLOW_PUBLIC=1 — also use Cloudflare URL from run_cloudflare_tunnel.py")
    ensure_runtime_async()
    if os.getenv("PLA_OPEN_BROWSER", "1").lower() in {"1", "true", "yes"} and host in {"127.0.0.1", "localhost"}:
        try:
            import webbrowser

            webbrowser.open(f"http://127.0.0.1:{port}")
        except Exception:
            pass
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
