"""
Super Desktop Assistant — 多模型智能助手

启动（默认命令行交互）:
  python app.py              命令行交互（默认）
  python app.py --web        Web UI（可选，gradio 懒加载）
  python app.py --window     独立窗口（可选）
"""
import os, sys, time, asyncio, argparse, threading, traceback, urllib.request, html
from pathlib import Path


# ═══════════════════════════════════════════════════════
# 必须在任何 loguru import 之前执行编码修复！
# ═══════════════════════════════════════════════════════
def _fix_encoding():
    """修复 Windows 终端 UTF-8 编码问题（含 stdin，防止 input() 错解中文成代理字符）。"""
    if sys.platform == "win32":
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        for stream in (sys.stdin, sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_fix_encoding()

# 重新配置 loguru handler（必须在 loguru 首次导入后立即执行）
def _fix_loguru_encoding():
    """确保 loguru 输出使用 UTF-8 编码。"""
    try:
        from loguru import logger as _logger
        _logger.remove()
        _logger.add(
            sys.stderr,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            level="INFO",
            colorize=False,  # 禁用 ANSI 颜色避免 Windows 终端乱码
            encoding="utf-8",
        )
    except Exception:
        pass


from src.main import get_engine
from src.config import get_config
from src.conversations import get_store, Conversation

# 说明：Gradio Web UI 已降级为可选（--web/--window），默认纯命令行交互。
# gradio 改为懒加载（仅在使用 WebUI 时 import），保证 CLI 启动快速、无额外依赖。

Path(get_config().settings.output_dir).mkdir(parents=True, exist_ok=True)

# loguru 编码修复（必须在 src.main 导入后执行，因为 src.main 首次导入了 loguru）
# 注意：gradio 也依赖 loguru，放在它之后确保覆盖 gradio 的 handler 配置
_fix_loguru_encoding()


def safe_print(*args, **kwargs):
    """UTF-8 安全打印，自动处理 Windows 终端编码问题。"""
    # flush 保证管道/重定向下实时输出（CLI 交互友好）
    kwargs.setdefault("flush", True)
    try:
        print(*args, **kwargs)
    except (UnicodeEncodeError, OSError):
        try:
            safe = [str(a).encode('utf-8', errors='replace').decode('utf-8', errors='replace') for a in args]
            print(*safe, **kwargs)
        except Exception:
            # 最终降级：纯 ASCII
            try:
                safe = [str(a).encode('ascii', errors='replace').decode('ascii') for a in args]
                print(*safe, **kwargs)
            except Exception:
                sys.stderr.write("[WARN] safe_print 完全失败，输出被丢弃\n")


# ==================== ANSI 彩色输出 ====================

_ANSI_ENABLED = False
_COLORS = {
    "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
    "blue": "\033[34m", "magenta": "\033[35m", "cyan": "\033[36m",
    "bold": "\033[1m", "dim": "\033[2m", "reset": "\033[0m",
}


def _enable_ansi() -> bool:
    """尝试启用 Windows 虚拟终端序列；非 TTY 或失败则返回 False。"""
    global _ANSI_ENABLED
    if not sys.stdout.isatty():
        _ANSI_ENABLED = False
        return False
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            _ANSI_ENABLED = True
        except Exception:
            _ANSI_ENABLED = False
    else:
        _ANSI_ENABLED = True
    return _ANSI_ENABLED


def _c(text, color: str = "") -> str:
    """给文本上色（不支持 ANSI 时原样返回）。"""
    if not _ANSI_ENABLED or not color:
        return str(text)
    code = _COLORS.get(color, "")
    if not code:
        return str(text)
    return f"{code}{text}{_COLORS['reset']}"


# ==================== CSS ====================

CSS = """
* { font-family: 'Segoe UI', 'Microsoft YaHei', system-ui, sans-serif; }
.gradio-container { max-width: 100% !important; margin: 0 !important; padding: 0 !important; }
footer { display: none !important; }

/* ---- 全局亮色主题 ---- */
body, .gradio-container, .contain, .app {
    background: #ffffff !important;
    color: #1d1d1f !important;
}
.gradio-container .contain { background: #ffffff !important; }
.block { border: none !important; }

/* ---- 三栏布局：左会话 / 中聊天 / 右DAG ---- */
.main-row { gap: 0 !important; }
.main-row > .column:first-child {
    max-width: 280px !important; min-width: 280px !important;
    background: #f5f5f7; border-right: 1px solid #d1d1d6; padding: 0 !important;
}
.main-row > .column:nth-child(2) { flex: 1 !important; padding: 0 !important; }
.main-row > .column:last-child {
    flex: 0 0 380px !important; max-width: 380px !important; min-width: 380px !important;
    background: #ffffff; border-left: 1px solid #eceef1; padding: 0 !important;
}
.dag-col { display: flex; flex-direction: column; }
.dag-col .dag-panel-wrap { flex: 1; overflow-y: auto; }

/* ---- 侧边栏内部 ---- */
.sidebar-inner { padding: 16px 12px; }
.sb-title {
    font-size: 1.25em; font-weight: 700; margin: 0 0 2px 0;
    background: linear-gradient(135deg, #5b6af0, #a855f7);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.sb-sub { font-size: 0.75em; color: #86868b; margin-bottom: 14px; }
.sb-btn-row { margin-bottom: 10px; }
.sb-btn-row button {
    width: 100% !important; background: linear-gradient(135deg, #5b6af0, #a855f7) !important;
    border: none !important; color: #fff !important; border-radius: 10px !important;
    padding: 9px 0 !important; font-weight: 600 !important; font-size: 0.88em !important;
}
.sb-btn-row button:hover { opacity: 0.9; }

/* ---- 会话列表 (Radio) ---- */
#conv-list { border: none !important; background: transparent !important; }
#conv-list .wrap { gap: 2px !important; }
#conv-list label {
    padding: 10px 12px !important; margin: 0 !important;
    border-radius: 8px !important; cursor: pointer !important;
    transition: background 0.15s !important;
    background: transparent !important; border: none !important;
    color: #3a3a3c !important; font-size: 0.85em !important;
    line-height: 1.4 !important; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
}
#conv-list label:hover { background: #e5e5ea !important; color: #1d1d1f !important; }
#conv-list label.selected {
    background: #e5e5ea !important; color: #1d1d1f !important;
    font-weight: 500 !important;
}
#conv-list input[type="radio"] { display: none !important; }
#conv-list span { color: inherit !important; }
.sb-footer {
    display: flex; gap: 6px; padding: 10px 0; border-top: 1px solid #d1d1d6; margin-top: 8px;
}
.sb-footer button {
    flex: 1; background: #e5e5ea; border: none; color: #6e6e73;
    padding: 6px 0; border-radius: 7px; font-size: 0.78em; cursor: pointer;
}
.sb-footer button:hover { background: #d1d1d6; color: #1d1d1f; }

/* ---- 聊天区 ---- */
.chat-main { background: #ffffff; }
.chat-header-bar {
    padding: 14px 20px; border-bottom: 1px solid #e5e5ea;
    color: #1d1d1f; font-size: 1.05em; font-weight: 600;
    min-height: 48px; display: flex; align-items: center;
}

/* ---- Chatbot 消息气泡 (Gradio 4.x / 5.x / 6.x 兼容) ---- */
.chatbot { border: none !important; }
/* Gradio 4/5 bubble-wrap */
.chatbot .bubble-wrap { max-width: 96% !important; }
/* 通用 bubble 样式 */
.chatbot .bubble {
    padding: 12px 16px !important; border-radius: 16px !important;
    font-size: 0.9em !important; line-height: 1.5 !important;
    max-width: 72% !important;
}
/* 用户气泡 */
.chatbot .user .bubble,
.chatbot .bubble.user,
.chatbot [data-testid="user"] .bubble,
.chatbot .message-row.user .bubble {
    background: #4a4af0 !important; color: #fff !important;
    border-bottom-right-radius: 4px !important;
}
/* 机器人气泡 */
.chatbot .bot .bubble,
.chatbot .bubble.bot,
.chatbot [data-testid="bot"] .bubble,
.chatbot .message-row.bot .bubble {
    background: #f0f0f5 !important; color: #1d1d1f !important;
    border-bottom-left-radius: 4px !important;
}
/* 消息行间距 */
.chatbot .user, .chatbot .bot,
.chatbot .message-row { padding: 6px 12px !important; }

/* ---- 输入区 ---- */
.input-box { padding: 0 16px 12px 16px; }
.input-row { display: flex; gap: 8px; align-items: flex-end; }
.input-row textarea, .input-row input[type="text"] {
    background: #f0f0f5 !important; border: 1px solid #d1d1d6 !important;
    border-radius: 14px !important; color: #1d1d1f !important;
    padding: 12px 16px !important; font-size: 0.88em !important;
    resize: none !important;
}
.input-row textarea:focus, .input-row input[type="text"]:focus { border-color: #5b6af0 !important; }
.send-btn button {
    background: linear-gradient(135deg, #5b6af0, #a855f7) !important;
    border: none !important; color: #fff !important; border-radius: 14px !important;
    padding: 12px 20px !important; font-weight: 600 !important;
}

/* ---- 附件 ---- */
.attach-row { display: flex; gap: 8px; margin-top: 8px; }
.attach-row > .column { flex: 1; }

/* ---- DAG 任务流水线面板（左侧栏，深色显眼） ---- */
.dag-panel-wrap { padding: 0 8px 12px 8px; }
.dag-panel {
    background: linear-gradient(160deg, #1e293b, #0f172a);
    border: 1px solid #334155; border-radius: 14px;
    padding: 14px 16px; margin-top: 4px;
    box-shadow: 0 4px 18px rgba(0,0,0,0.30);
}
.dag-header {
    font-size: 0.9em; font-weight: 700; color: #e2e8f0;
    margin-bottom: 10px; display: flex; align-items: center; gap: 6px;
}
.dag-header .dag-timing { color: #38bdf8; font-weight: 800; }
.dag-node {
    display: flex; align-items: flex-start; gap: 8px;
    padding: 8px 10px; margin: 4px 0; border-radius: 10px;
    font-size: 0.86em; transition: background 0.15s;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.06);
}
.dag-node:hover { background: rgba(255,255,255,0.12); }
.dag-icon { font-size: 1.05em; flex-shrink: 0; line-height: 1.4; }
.dag-status { font-size: 0.8em; flex-shrink: 0; width: 16px; text-align: center; line-height: 1.5; }
.dag-prompt-text {
    flex: 1; color: #e2e8f0; white-space: normal; word-break: break-word;
    line-height: 1.4;
}
.dag-time {
    flex-shrink: 0; font-size: 0.82em; color: #38bdf8; font-variant-numeric: tabular-nums;
    min-width: 48px; text-align: right; line-height: 1.5;
}
.dag-node-failed { border-color: rgba(248,113,113,0.4); }
.dag-node-failed .dag-prompt-text { color: #f87171; }
.dag-node-failed .dag-time { color: #f87171; }
.dag-node-done .dag-prompt-text { color: #cbd5e1; }
.dag-node-done .dag-status { color: #4ade80; }
.dag-node-skipped .dag-prompt-text { color: #64748b; text-decoration: line-through; }
.dag-error-msg {
    font-size: 0.75em; color: #f87171; padding: 2px 8px 2px 32px; margin-bottom: 2px;
}
.dag-connector {
    width: 1px; height: 4px; background: #334155; margin-left: 11px;
}
.dag-deps {
    font-size: 0.72em; color: #94a3b8; margin-left: 32px; margin-bottom: 2px;
}
.dag-panel-empty {
    color: #64748b; font-size: 0.8em; padding: 8px 4px;
    text-align: center;
}

/* ---- 模型状态栏 ---- */
.model-status {
    font-size: 0.75em; color: #86868b; padding: 5px 20px;
    border-bottom: 1px solid #f0f0f5;
}
.model-status code { color: #5b6af0; background: none; }

/* ---- 停止按钮 ---- */
.stop-btn button {
    background: #f0f0f5 !important; border: 1px solid #d1d1d6 !important;
    color: #6e6e73 !important; border-radius: 14px !important;
    padding: 12px 12px !important; font-size: 0.8em !important;
}
.stop-btn button:hover { background: #ffecef !important; color: #d03050 !important; border-color: #d03050 !important; }
"""


# ==================== 会话列表 ====================

def _conv_label(c: Conversation) -> str:
    """构建 Radio 选项标签（纯文本，避免 HTML 转义问题）。"""
    pin = "📌 " if c.pinned else ""
    last = ""
    msgs = c.messages or []
    if msgs:
        m = (msgs[-1].get("content", "") if isinstance(msgs[-1], dict) else str(msgs[-1])).replace("\n", " ")
        last = m[:20] + ("..." if len(m) > 20 else "")
    elif c.last_message:
        # H5 修复：会话消息懒加载时，用索引中的预览展示
        last = str(c.last_message.get("preview", "")).replace("\n", " ")
        last = last[:20] + ("..." if len(last) > 20 else "")
    name = (c.title or "新对话")[:18]
    name = name + ("..." if len(c.title or "") > 18 else "")
    if last:
        return f"{pin}{name}  |  {last}"
    return f"{pin}{name}"


def build_conv_choices() -> tuple[list, str | None]:
    """返回 (choices 列表, 默认选中值)。choices 格式: [(label, value), ...]"""
    store = get_store()
    convs = store.list_all()
    choices = [(_conv_label(c), c.id) for c in convs]
    default = convs[0].id if convs else None
    return choices, default


def build_choice_list() -> list:
    """同步快捷：只返回 choices。"""
    choices, _ = build_conv_choices()
    return choices


def build_conv_update():
    """返回 Radio 组件的 update 对象（更新 choices + value）。

    注意：Gradio 6 的回调输出到 Radio 必须用 gr.update，直接返回裸 choices 列表
    会被当作 value 校验而报 "not in the list of choices" 崩溃。
    """
    import gradio as gr
    choices, default = build_conv_choices()
    return gr.update(choices=choices, value=default)


# ==================== 回调 ====================

def on_new_chat():
    try:
        conv = get_store().create()
        return conv.id, build_conv_update(), [], f"### {conv.title}", ""
    except Exception as e:
        safe_print(f"[ERROR] on_new_chat: {e}")
        traceback.print_exc()
        raise RuntimeError(f"新建会话失败: {e}")


def on_select_conv(conv_id: str):
    if not conv_id: return [], "", "", ""
    try:
        conv = get_store().get(conv_id)
        if not conv: return [], "", "", ""
        history = get_store().get_chat_history(conv_id)
        return history, conv.title, conv_id, ""
    except Exception as e:
        safe_print(f"[ERROR] on_select_conv: {e}")
        traceback.print_exc()
        raise RuntimeError(f"切换会话失败: {e}")


def on_delete_conv(conv_id: str):
    if not conv_id: return None, build_conv_update(), [], "", ""
    store = get_store()
    store.delete(conv_id)
    conv_upd = build_conv_update()
    _, default = build_conv_choices()
    if default:
        conv_default = store.get(default)
        title = f"### {conv_default.title}" if conv_default else "### 新对话"
        return default, conv_upd, store.get_chat_history(default), title, ""
    else:
        c = store.create()
        return c.id, build_conv_update(), [], f"### {c.title}", ""


def on_pin_conv(conv_id: str):
    if not conv_id: return build_conv_update()
    store = get_store()
    c = store.get(conv_id)
    if c: store.pin(conv_id, not c.pinned)
    return build_conv_update()


async def on_send_message(msg: str, image: str | None, audio: str | None,
                          video: str | None, conv_id: str, chat_history: list):
    if not msg and not image and not audio and not video:
        yield chat_history, conv_id, build_conv_update(), "", "", ""
        return

    store = get_store()
    conv = store.get(conv_id) if conv_id else None
    if not conv:
        conv = store.create()
        conv_id = conv.id

    user_display = msg or ""
    if image: user_display += "\n[图片]"
    if audio: user_display += "\n[音频]"
    if video: user_display += "\n[视频]"

    chat_history.append({"role": "user", "content": user_display})
    store.add_message(conv_id, "user", user_display)

    chat_history.append({"role": "assistant", "content": "思考中..."})
    yield chat_history, conv_id, build_conv_update(), "", "", ""

    dag_html_val = ""
    try:
        engine = get_engine()
        # 构建对话历史（不含当前用户消息 —— 它已在 user_message 参数中）
        full_history = store.get_chat_history(conv_id) or []
        # 去掉刚追加的当前用户消息，避免重复发送
        if full_history and full_history[-1]["role"] == "user":
            full_history = full_history[:-1]
        conv_history = [{"role": m["role"], "content": m["content"]}
                        for m in full_history]
        # 后端注入：把会话中最近生成的图片路径作为上下文插入（前端会检测路径并显示图片）
        last_img = _last_images.get(conv_id)
        if last_img and not image:
            conv_history = list(conv_history) + [
                {"role": "user", "content": f"[上下文] 最近生成的图片路径: {last_img}"}
            ]
        result = await engine.process(
            user_message=msg,
            image_path=image or last_img or None,
            audio_path=audio or None,
            video_path=video or None,
            conversation_history=conv_history,
            session_id=conv_id,
        )
        if "error" in result:
            reply = f"❌ {result['error']}"
        else:
            reply = _fmt(result)
            dag_html_val = _dag_html(result)
            # 记录本次生成的图片路径（供后续 vision 节点跨请求分析）
            for _nid, _val in (result.get("results") or {}).items():
                if (isinstance(_val, str)
                        and _val.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
                        and os.path.isfile(_val)):
                    _last_images[conv_id] = _val
        chat_history[-1] = {"role": "assistant", "content": reply}
        store.add_message(conv_id, "assistant", reply)
    except ValueError as e:
        err = _friendly(str(e))
        chat_history[-1] = {"role": "assistant", "content": err}
        store.add_message(conv_id, "assistant", err)
    except Exception as e:
        chat_history[-1] = {"role": "assistant", "content": f"❌ {str(e)}"}
        store.add_message(conv_id, "assistant", f"❌ {str(e)}")

    yield chat_history, conv_id, build_conv_update(), "", "", dag_html_val


def _friendly(msg: str) -> str:
    if "API Key" in msg or "供应商" in msg:
        return "⚠️ API 未配置，请在 .env 文件中填入 API Key。"
    if "未分配" in msg:
        return "⚠️ 模型未分配，请在 UI 配置中选择模型。"
    return f"❌ {msg}"


def _model_status_text() -> str:
    """构建当前模型/配置状态文本（顶部状态栏）。"""
    try:
        cfg = get_config()
        a = cfg.get_assignment("llm")
        parts = []
        if a:
            p = cfg.get_provider(a.provider)
            key_ok = "✅" if (p and p.api_key) else "⚠️无Key"
            parts.append(f"`[{a.provider}] {a.model}` {key_ok}")
        else:
            parts.append("`未配置`")
        pref = cfg.settings.api_preference
        parts.append("本地优先" if pref == "local_first" else "云端默认")
        return " · ".join(parts)
    except Exception:
        return "配置读取失败"


# 会话内"最后生成的图片"（供后续 vision 节点分析，跨请求传递）
_last_images: dict = {}


def _embed_image(path: str, nid: str) -> str:
    """把生图结果路径嵌入为 markdown 图片（base64，浏览器可直接显示）。"""
    import base64
    if os.path.isfile(path):
        ext = path.rsplit(".", 1)[-1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/png")
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            return f"🎨 **已生成图片** ({nid}):\n\n![result](data:{mime};base64,{b64})"
        except Exception:
            pass
    return f"✅ **已生成:** `{path}`"


def _embed_audio(path: str, nid: str) -> str:
    """把音频文件嵌入为可播放的 HTML <audio>（base64，浏览器可直接播放）。"""
    import base64
    if os.path.isfile(path):
        ext = path.rsplit(".", 1)[-1].lower()
        mime = {"mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
                "m4a": "audio/mp4", "flac": "audio/flac"}.get(ext, "audio/wav")
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            return (f"🔊 **已生成语音** ({nid}):\n\n"
                    f"<audio controls src=\"data:{mime};base64,{b64}\"></audio>")
        except Exception:
            pass
    return f"✅ **已生成音频:** `{path}`"


def _embed_paths_in_text(text: str) -> str:
    """检测文本中的图片路径，转成 markdown 图片（前端显示用）。"""
    import re as _re
    if not text:
        return text
    patterns = [
        r"[A-Za-z]:[\\/][\w.\-\\/]+\.(?:png|jpe?g|webp|gif)",
        r"/(?:[\w.\-]+/)*[\w.\-]+\.(?:png|jpe?g|webp|gif)",
    ]
    for pat in patterns:
        for p in _re.findall(pat, text):
            if os.path.isfile(p):
                text = text.replace(p, _embed_image(p, "img"))
    return text


def _fmt(result: dict) -> str:
    """格式化最终回复文本（给聊天区用，简洁版）。"""
    # v3 P6b: 配置指令确认
    if result.get("config_reply"):
        return f"⚙️ {result['config_reply']}"

    # 纯错误响应
    if "error" in result and not result.get("results"):
        return f"❌ {result['error']}"

    parts = []
    dag = result.get("dag", {})
    status = result.get("status")
    if status in ("partial", "error"):
        parts.append("⚠️ **任务部分失败**" if status == "partial" else "❌ **任务失败**")

    if dag.get("description"):
        parts.append(f"**📋 {dag['description']}**")

    for nid, val in result.get("results", {}).items():
        v = str(val)
        if v.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            parts.append(_embed_image(v, nid))
        elif v.endswith((".mp3", ".wav", ".ogg", ".m4a", ".flac")):
            parts.append(_embed_audio(v, nid))
        elif len(v) > 400:
            # 长文本折叠展示，避免刷屏
            parts.append(
                f"<details><summary>📄 `{nid}` 结果（{len(v)} 字符）</summary>\n\n"
                f"{_embed_paths_in_text(v[:2000])}\n\n</details>"
            )
        else:
            if v.strip():
                parts.append(_embed_paths_in_text(v.strip()))

    for nid, err in result.get("errors", {}).items():
        parts.append(f"⚠️ `{nid}`: {err}")

    # v3: 显示因依赖失败被跳过的节点
    for nid in result.get("skipped", {}):
        parts.append(f"⏭️ `{nid}`: 已跳过（依赖失败）")

    ms = result.get("total_time_ms", 0)
    parts.append(f"⏱ **{ms / 1000:.1f}s**")
    return "\n\n".join(parts)


def _dag_html(result: dict) -> str:
    """生成 DAG 任务流水线 HTML。"""
    dag = result.get("dag", {})
    nodes = dag.get("nodes", [])
    if not nodes:
        return ""

    results = result.get("results", {})
    errors = result.get("errors", {})
    skipped = result.get("skipped", {})
    timings = result.get("timings", {})
    total_ms = result.get("total_time_ms", 0)

    TYPE_ICON = {
        "llm": "💬", "vision": "👁️", "stt": "🎤",
        "tts": "🔊", "image_gen": "🎨", "image_edit": "✏️",
    }
    TYPE_NAME = {
        "llm": "推理", "vision": "视觉", "stt": "语音识别",
        "tts": "语音合成", "image_gen": "文生图", "image_edit": "图片编辑",
    }

    lines = ['<div class="dag-panel">']

    # 头部
    desc = dag.get("description", "任务流水线")
    lines.append(
        f'<div class="dag-header">'
        f'📋 {desc} '
        f'<span class="dag-timing">{total_ms / 1000:.1f}s</span>'
        f'</div>'
    )

    for i, node in enumerate(nodes):
        nid = html.escape(str(node.get("id", "?")))
        ntype = node.get("type", "?")
        full_prompt = html.escape(str(node.get("prompt", "") or ""))
        prompt = full_prompt[:200]
        icon = TYPE_ICON.get(ntype, "❓")
        type_name = html.escape(str(TYPE_NAME.get(ntype, ntype)))

        # 显示依赖关系
        deps = node.get("depends_on", [])
        if deps:
            dep_names = " · ".join(f"←{html.escape(str(d))}" for d in deps)
            lines.append(f'<div class="dag-deps">{dep_names}</div>')

        # 确定状态（v3：支持 skipped 与 pending）
        if nid in errors:
            cls = "dag-node-failed"
            status_icon = "❌"
            detail = html.escape(str(errors.get(nid, ""))[:80])
        elif nid in results:
            cls = "dag-node-done"
            status_icon = "✅"
            detail = ""
        elif nid in skipped:
            cls = "dag-node-skipped"
            status_icon = "⏭️"
            detail = ""
        else:
            cls = "dag-node-pending"
            status_icon = "⏳"
            detail = ""

        # 节点耗时（v3 timings 字段）
        timing_html = ""
        t_ms = timings.get(nid)
        if t_ms is not None:
            try:
                timing_html = f'<span class="dag-time">{float(t_ms) / 1000:.1f}s</span>'
            except (TypeError, ValueError):
                timing_html = ""

        lines.append(
            f'<div class="dag-node {cls}">'
            f'<span class="dag-icon">{icon}</span>'
            f'<span class="dag-status">{status_icon}</span>'
            f'<span class="dag-prompt-text" title="{full_prompt}">{type_name}: {prompt}</span>'
            f'{timing_html}'
            f'</div>'
        )

        if detail:
            lines.append(f'<div class="dag-error-msg">⚠️ {detail}</div>')

    lines.append('</div>')
    return "\n".join(lines)


# ==================== UI ====================

def create_ui():
    import gradio as gr  # 懒加载：仅 WebUI 模式才依赖 gradio

    store = get_store()
    initial_convs = store.list_all()
    initial_id = initial_convs[0].id if initial_convs else None
    initial_title = initial_convs[0].title if initial_convs else "新对话"
    initial_choices = [(_conv_label(c), c.id) for c in initial_convs]

    with gr.Blocks(title="Super Desktop Assistant") as demo:
        conv_state = gr.State(value=initial_id)

        with gr.Row(equal_height=True, elem_classes="main-row"):
            # ====== 左栏：会话列表 ======
            with gr.Column(scale=0, min_width=280, elem_classes="sb-column"):
                gr.HTML(f"""
                <div style="padding:16px 12px;">
                    <div class="sb-title">Super Desktop</div>
                    <div class="sb-sub">多模型智能助手</div>
                </div>
                """)

                with gr.Row(elem_classes="sb-btn-row"):
                    new_btn = gr.Button("+ 新建对话", size="sm")

                # 会话列表
                conv_list = gr.Radio(
                    choices=initial_choices,
                    value=initial_id,
                    label="",
                    interactive=True,
                    elem_id="conv-list",
                    container=False,
                )

                with gr.Row(elem_classes="sb-footer"):
                    pin_btn = gr.Button("置顶", size="sm")
                    del_btn = gr.Button("删除", size="sm")

            # ====== 中栏：聊天区 ======
            with gr.Column(scale=1, elem_classes="chat-main"):
                chat_title = gr.Markdown(f"### {initial_title}", elem_classes="chat-header-bar")
                model_status = gr.Markdown(_model_status_text(), elem_classes="model-status")

                chatbot = gr.Chatbot(
                    value=store.get_chat_history(initial_id) if initial_id else [],
                    label="", height=420,
                    elem_classes="chatbot",
                )

                with gr.Group(elem_classes="input-box"):
                    with gr.Row(elem_classes="input-row"):
                        msg_input = gr.Textbox(
                            placeholder="输入消息，Enter 发送（Shift+Enter 换行）...",
                            show_label=False, lines=2, scale=8,
                        )
                        with gr.Column(scale=0, min_width=60, elem_classes="stop-btn"):
                            stop_btn = gr.Button("停止", size="sm")
                        with gr.Column(scale=0, min_width=70, elem_classes="send-btn"):
                            send_btn = gr.Button("发送", variant="primary")

                    with gr.Row(elem_classes="attach-row"):
                        image_input = gr.Image(label="图片", type="filepath", show_label=False, container=False)
                        audio_input = gr.Audio(label="音频", type="filepath", show_label=False, container=False)
                        video_input = gr.Video(label="视频", show_label=False, container=False)

            # ====== 右栏：DAG 任务流水线面板 ======
            with gr.Column(scale=0, min_width=380, elem_classes="dag-col"):
                dag_panel = gr.HTML(value="", elem_classes="dag-panel-wrap")

        # ==== 事件绑定 ====

        # 新建
        new_btn.click(
            fn=on_new_chat,
            outputs=[conv_state, conv_list, chatbot, chat_title, dag_panel],
        )

        # 切换会话
        def on_conv_change(cid):
            hist, title, cid_out, dag = on_select_conv(cid)
            return hist, f"### {title}", cid_out, dag

        conv_list.change(
            fn=on_conv_change,
            inputs=[conv_list],
            outputs=[chatbot, chat_title, conv_state, dag_panel],
        )

        # 删除
        del_btn.click(
            fn=on_delete_conv,
            inputs=[conv_state],
            outputs=[conv_state, conv_list, chatbot, chat_title, dag_panel],
        )

        # 置顶
        pin_btn.click(
            fn=on_pin_conv,
            inputs=[conv_state],
            outputs=[conv_list],
        )

        # 发送消息
        async def on_send(msg, img, aud, vid, cid, hist):
            async for h, new_cid, choices, new_title, _, dag_h in on_send_message(msg, img, aud, vid, cid, hist):
                if new_cid:
                    conv = get_store().get(new_cid)
                    title_out = f"### {conv.title}" if conv else "### 新对话"
                else:
                    title_out = "### 新对话"
                yield h, new_cid, choices, title_out, "", dag_h

        send_events = [
            send_btn.click(
                fn=on_send,
                inputs=[msg_input, image_input, audio_input, video_input, conv_state, chatbot],
                outputs=[chatbot, conv_state, conv_list, chat_title, msg_input, dag_panel],
            ),
            msg_input.submit(
                fn=on_send,
                inputs=[msg_input, image_input, audio_input, video_input, conv_state, chatbot],
                outputs=[chatbot, conv_state, conv_list, chat_title, msg_input, dag_panel],
            ),
        ]

        # 停止生成：取消运行中的发送事件（生成器被取消 → process 传播 CancelledError）
        stop_btn.click(
            fn=None,
            inputs=None,
            outputs=None,
            cancels=send_events,
        )

    return demo


# ==================== 启动 ====================

def _start_gradio_server(port: int, open_browser: bool):
    create_ui().launch(
        server_port=port, share=False, css=CSS,         inbrowser=open_browser, quiet=True,
    )


def window_mode(port: int = 7860):
    try:
        import webview
    except ImportError:
        safe_print("[ERROR] pip install pywebview")
        return _start_gradio_server(port, True)
    t = threading.Thread(target=_start_gradio_server, args=(port, False), daemon=True)
    t.start()
    max_wait = 15  # 最长等待秒数
    for i in range(max_wait * 2):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}"); break
        except Exception:
            if i == max_wait * 2 - 1:
                safe_print(f"[ERROR] Gradio 服务器启动超时（{max_wait}s），请检查端口 {port} 是否被占用")
                return
            continue
    webview.create_window(
        title="Super Desktop Assistant",
        url=f"http://127.0.0.1:{port}",
        width=1100, height=750, resizable=True, min_size=(900, 600),
    )
    webview.start()


async def cli_mode():
    # UTF-8 编码已在模块加载时通过 _fix_encoding() 修复，此处无需重复调用
    store = get_store(); engine = get_engine()
    convs = store.list_all()
    cid = convs[0].id if convs else store.create().id
    _enable_ansi()
    safe_print(_c("\n  Super Desktop Assistant - CLI 模式", "bold"))
    safe_print(_c("  ─────────────────────────────────", "dim"))
    safe_print("  命令: /new  /list  /switch <id>  /clear  /config  /help  /quit")
    safe_print("  直接输入文字即可与 AI 对话~\n")

    # 启动时配置预检查
    try:
        cfg = get_config()
        llm_assign = cfg.get_assignment("llm")
        if llm_assign:
            provider = cfg.get_provider(llm_assign.provider)
            if not provider or not provider.api_key:
                safe_print(f"  ⚠️  LLM 供应商 '{llm_assign.provider}' 的 API Key 未配置")
                safe_print(f"     请在 .env 文件中设置 {provider.env_api_key if provider else 'API Key'}")
                safe_print(f"     或修改 config.json 中的 assignments.llm")
                safe_print()
            else:
                safe_print(f"  ✅ LLM: [{llm_assign.provider}] {llm_assign.model}")
        else:
            safe_print(f"  ⚠️  未分配 LLM 模型，请在 config.json -> assignments 中配置")
            safe_print()
    except Exception:
        pass  # 配置检查失败不阻止启动

    while True:
        try:
            conv = store.get(cid)
            # 如果当前会话已被删除，自动创建新会话
            if conv is None:
                safe_print(f"\n  ⚠ 会话 {cid[:8]} 不存在，已自动创建新会话")
                new_conv = store.create()
                cid = new_conv.id
                conv = new_conv
            title = (conv.title if conv else "新对话")[:20]
            user_input = input(f"\n{_c(f'[{title}]', 'cyan')}> ").strip()
        except (EOFError, KeyboardInterrupt):
            safe_print(f"\n  {_c('再见~', 'yellow')}")
            break

        if not user_input:
            continue
        if user_input in ("/quit", "/q", "/exit"):
            safe_print(f"  {_c('再见~', 'yellow')}")
            break
        if user_input in ("/help", "/h", "/?"):
            _cli_help()
            continue
        if user_input in ("/config", "/cfg"):
            _cli_config()
            continue
        if user_input == "/new":
            conv = store.create()
            cid = conv.id
            safe_print(f"  ✓ 已创建新会话: {conv.id[:8]} - {conv.title}")
            continue
        if user_input == "/list":
            _cli_list(store, cid)
            continue
        if user_input == "/clear":
            _cli_clear(store, cid)
            continue
        if user_input.startswith("/switch"):
            target_id = user_input.split(maxsplit=1)[1] if len(user_input.split(maxsplit=1)) > 1 else ""
            if not target_id:
                safe_print("  ⚠ 用法: /switch <会话ID前缀>")
                continue
            # 前缀匹配：在所有会话中查找以 target_id 开头的会话
            all_convs = store.list_all()
            matches = [c for c in all_convs if c.id.startswith(target_id)]
            if not matches:
                safe_print(f"  ⚠ 未找到以 '{target_id[:20]}' 开头的会话")
                continue
            if len(matches) > 1:
                safe_print(f"  ⚠ 多个会话匹配 '{target_id}':")
                for c in matches:
                    safe_print(f"      {c.id[:8]}... {c.title[:30]}")
                continue
            target = matches[0]
            cid = target.id
            safe_print(f"  ✓ 已切换到: {target.title[:35]}")
            continue

        # 发送消息
        safe_print(f"  {_c('处理中...', 'dim')}")
        t_start = time.time()

        try:
            # 先存用户消息
            store.add_message(cid, "user", user_input)

            # 获取对话历史，让 planner 理解上下文
            history = store.get_chat_history(cid)
            # 去掉刚加的这条用户消息（它已经在 planner 的 user_message 中了）
            if history and history[-1]["role"] == "user":
                history = history[:-1]

            r = await engine.process(
                user_message=user_input,
                conversation_history=history,
                session_id=cid,
            )

            if "error" in r:
                err_msg = r["error"]
                safe_print(f"\n  {_c('❌', 'red')} {err_msg}")
                # 如果是 API Key 相关错误，给出提示
                if "Key" in err_msg or "未配置" in err_msg:
                    safe_print(f"  {_c('💡 提示: 请在 .env 文件中填入有效的 API Key', 'yellow')}")
                store.add_message(cid, "assistant", f"[错误] {err_msg}")
            else:
                _cli_print_result(r)
                store.add_message(cid, "assistant", _fmt(r))

            elapsed = time.time() - t_start
            if "error" not in r:
                status = _c("✅", "green") if not r.get("errors") else _c("⚠️ (部分失败)", "yellow")
                safe_print(f"\n  {status} 总耗时: {elapsed:.1f}s")

        except ValueError as e:
            elapsed = time.time() - t_start
            safe_print(f"\n  {_c('❌', 'red')} 配置错误 ({elapsed:.1f}s): {e}")
            safe_print(f"  {_c('💡 提示: 请检查 .env 和 config.json 配置', 'yellow')}")
            store.add_message(cid, "assistant", f"[配置错误] {e}")
        except Exception as e:
            elapsed = time.time() - t_start
            safe_print(f"\n  {_c('❌', 'red')} 运行异常 ({elapsed:.1f}s): {e}")
            store.add_message(cid, "assistant", f"[异常] {e}")


def _cli_config():
    """CLI 查看当前配置。"""
    try:
        cfg = get_config()
        safe_print(f"\n  {_c('📋 当前配置', 'bold')}")
        for cap in ("llm", "llm_reasoning", "llm_creative", "llm_summary",
                    "vision", "stt", "tts", "image_gen"):
            a = cfg.get_assignment(cap)
            if a:
                p = cfg.get_provider(a.provider)
                key = _c("✅", "green") if (p and p.api_key) else _c("⚠️无Key", "yellow")
                safe_print(f"    {cap:<14} → [{a.provider}] {a.model} {key}")
        pref = cfg.settings.api_preference
        pref_txt = _c("本地优先", "cyan") if pref == "local_first" else "云端默认"
        safe_print(f"    api_preference = {pref_txt}")
        safe_print(f"    workspace_dir  = {cfg.settings.workspace_dir}")
        safe_print(f"    output_dir     = {cfg.settings.output_dir}")
        safe_print(f"  {_c('提示: 直接说\"把视觉换成 xxx\"即可切换模型', 'dim')}\n")
    except Exception as e:
        safe_print(f"  {_c('❌ 读取配置失败', 'red')}: {e}")


def _cli_help():
    """CLI 帮助信息。"""
    safe_print(r"""
  ┌─────────────────────────────────────────┐
  │  Super Desktop Assistant - CLI 帮助     │
  ├─────────────────────────────────────────┤
  │  /new              新建会话             │
  │  /list             列出所有会话         │
  │  /switch <id>      切换到指定会话       │
  │  /clear            清空当前会话         │
  │  /config           查看当前模型配置     │
  │  /help, /h, /?     显示此帮助           │
  │  /quit, /q, /exit  退出                 │
  │                                         │
  │  直接输入文字即可与 AI 对话             │
  │  支持：问答、翻译、写作、代码等         │
  ├─────────────────────────────────────────┤
  │  图片/音频功能请在 Web UI 中使用        │
  └─────────────────────────────────────────┘
""")


def _cli_list(store, current_id: str):
    """CLI 列出所有会话。"""
    convs = store.list_all()
    if not convs:
        safe_print("  (暂无会话)")
        return
    safe_print(f"  {_c('ID', 'bold'):<10} {_c('置顶', 'bold'):<4} {_c('消息', 'bold'):<6} 标题")
    safe_print(f"  {_c('─'*10, 'dim')} {_c('─'*4, 'dim')} {_c('─'*6, 'dim')} {_c('─'*30, 'dim')}")
    for c in convs:
        pin = '📌' if c.pinned else ' '
        marker = _c('← 当前', 'cyan') if c.id == current_id else ''
        msg_count = len(c.messages) if c.messages else 0
        safe_print(f"  {c.id[:8]:<10} {pin:<4} {msg_count:<6} {c.title[:35]} {marker}")


def _cli_clear(store, conv_id: str):
    """CLI 清空当前会话消息。"""
    conv = store.get(conv_id)
    if not conv:
        safe_print("  ⚠ 当前会话不存在")
        return
    store.clear_messages(conv_id)
    safe_print(f"  ✓ 已清空会话: {conv_id[:8]}")


def _cli_print_result(result: dict):
    """在 CLI 中友好地输出处理结果（含节点耗时与彩色）。"""
    dag = result.get("dag", {})

    # 显示 DAG 任务信息
    if dag.get("description"):
        safe_print(f"\n  {_c('📋 ' + str(dag['description']), 'bold')}")

    # 显示每个节点的结果
    results = result.get("results", {})
    errors = result.get("errors", {})
    timings = result.get("timings", {})
    nodes = dag.get("nodes", [])

    for node in nodes:
        nid = node.get("id", "?")
        ntype = node.get("type", "?")
        type_emoji = {
            "llm": "💬", "vision": "👁️", "stt": "🎤",
            "tts": "🔊", "image_gen": "🎨", "image_edit": "✏️",
        }.get(ntype, "❓")

        # 节点耗时
        timing = ""
        t_ms = timings.get(nid)
        if t_ms is not None:
            try:
                timing = f" ({float(t_ms) / 1000:.1f}s)"
            except (TypeError, ValueError):
                timing = ""

        if nid in errors:
            safe_print(f"  {type_emoji} [{nid}]{timing} {_c('❌', 'red')} {errors[nid][:100]}")
        elif nid in results:
            val = str(results[nid])
            # 截断长文本
            if len(val) > 500 and not any(val.endswith(e) for e in (".png", ".jpg", ".mp3", ".wav")):
                safe_print(f"  {type_emoji} [{nid}]{timing} {_c('✅', 'green')}")
                safe_print(f"  {val[:500]}...")
            else:
                if any(val.endswith(e) for e in (".png", ".jpg", ".webp", ".mp3", ".wav")):
                    safe_print(f"  {type_emoji} [{nid}]{timing} {_c('✅', 'green')} 已生成: {val}")
                else:
                    safe_print(f"  {type_emoji} [{nid}]{timing} {_c('✅', 'green')}")
                    if val.strip():
                        safe_print(f"  {_c('─' * 30, 'dim')}")
                        safe_print(f"  {val}")
                        safe_print(f"  {_c('─' * 30, 'dim')}")
        else:
            safe_print(f"  {type_emoji} [{nid}]{timing} {_c('⏭ 已跳过', 'yellow')}")


def main():
    _fix_encoding()
    p = argparse.ArgumentParser(
        prog="python app.py",
        description="Super Desktop Assistant — 多模型智能助手（默认命令行交互）",
    )
    # 默认进入 CLI；WebUI/窗口已降级为可选（需显式 --web/--window，gradio 懒加载）
    p.add_argument("--web", action="store_true", help="（可选）启动 Web UI")
    p.add_argument("--cli", action="store_true", help="（可选）显式进入命令行交互模式（默认模式）")
    p.add_argument("--window", action="store_true", help="（可选）启动桌面窗口")
    p.add_argument("--browser", action="store_true", help="WebUI 启动后自动打开浏览器")
    p.add_argument("--port", type=int, default=int(os.environ.get("GRADIO_SERVER_PORT", "7860")),
                   help="WebUI 端口（默认 7860）")
    p.add_argument("--host", type=str, default=os.environ.get("GRADIO_SERVER_HOST", "127.0.0.1"),
                   help="WebUI 监听地址 (Docker 用 0.0.0.0)")
    p.add_argument("--share", action="store_true", default=os.environ.get("GRADIO_SHARE", "false").lower() == "true",
                   help="创建 Gradio 公共分享链接")
    p.add_argument("--init-ai-coin", action="store_true",
                   help="一次性迁移 config.json 的 providers/assignments 到 ai-coin（SQLite），并瘦身 config.json")
    p.add_argument("--resync-ai-coin", action="store_true",
                   help="把 state.json 的模型元数据回填到 ai-coin DB（修复 0.3.1+ 预设空 capabilities）并剪除噪音模型")
    args = p.parse_args()

    if args.init_ai_coin:
        try:
            from src.api.ai_coin_bridge import migrate_and_slim
            state = migrate_and_slim()
            from src.config import reload_config
            reload_config()
            safe_print(f"✅ ai-coin 迁移完成: {len(state.get('providers', {}))} 供应商 "
                       f"→ data/ai_coin.db + data/ai_coin_state.json")
            safe_print(f"   config.json 已瘦身（只保留 settings）")
            return
        except Exception as e:
            safe_print(f"❌ ai-coin 迁移失败: {e}")
            sys.exit(1)

    if args.resync_ai_coin:
        try:
            from src.api.ai_coin_bridge import resync_models_from_state
            from src.config import reload_config
            r = resync_models_from_state()
            reload_config()
            safe_print(f"✅ ai-coin 模型元数据已同步: 更新 {len(r['updated'])} / "
                       f"剪除 {len(r['removed'])} / 保留 {r['kept']}")
            if r["updated"]:
                safe_print(f"   更新: {', '.join(r['updated'][:20])}")
            if r["removed"]:
                safe_print(f"   剪除: {', '.join(r['removed'][:20])}")
            return
        except Exception as e:
            safe_print(f"❌ ai-coin 元数据同步失败: {e}")
            sys.exit(1)

    if args.window:
        window_mode(args.port)
    elif args.web:
        safe_print(f"Web UI: http://{args.host}:{args.port}")
        import gradio as gr  # 懒加载
        create_ui().launch(
            server_name=args.host, server_port=args.port,
            share=args.share, css=CSS,
            theme=gr.themes.Base(), inbrowser=args.browser,
        )
    else:
        # 默认：纯命令行交互
        asyncio.run(cli_mode())


if __name__ == "__main__":
    main()
