# ============================================================
# ChatGPT 风格设计系统 — 配色 / 字体 / 间距 / 组件样式
# 亮暗双主题，CSS 变量驱动
# ============================================================

THEMES = {
    "light": {
        "bg_app": "#FFFFFF",
        "bg_sidebar": "#F9F9F9",
        "bg_hover": "#ECECEC",
        "bg_active": "#E3E3E3",
        "bg_input": "#FFFFFF",
        "bg_code": "#1E1E1E",
        "bg_code_header": "#2D2D2D",
        "bg_tool": "#F7F7F8",
        "bg_tool_hover": "#ECECEC",
        "border": "#E5E5E5",
        "border_strong": "#D4D4D4",
        "text": "#0D0D0D",
        "text_dim": "#6E6E80",
        "text_faint": "#9B9BA5",
        "text_on_code": "#ECECEC",
        "accent": "#FFB000",       # 琥珀色 — 硬件基因，用于工具调用/状态高亮
        "accent_dim": "#C77D00",
        "accent_bg": "rgba(255,176,0,0.10)",
        "user_bubble": "#F4F4F4",  # ChatGPT 用户消息极淡底（可选，默认无气泡）
        "danger": "#EF4444",
        "success": "#10B981",
        "shadow": "rgba(0,0,0,0.06)",
        "shadow_strong": "rgba(0,0,0,0.12)",
    },
    "dark": {
        "bg_app": "#212121",
        "bg_sidebar": "#171717",
        "bg_hover": "#2A2A2A",
        "bg_active": "#353535",
        "bg_input": "#2F2F2F",
        "bg_code": "#1E1E1E",
        "bg_code_header": "#2D2D2D",
        "bg_tool": "#1F1F1F",
        "bg_tool_hover": "#2A2A2A",
        "border": "#2F2F2F",
        "border_strong": "#3D3D3D",
        "text": "#ECECEC",
        "text_dim": "#B4B4B4",
        "text_faint": "#8E8E8E",
        "text_on_code": "#ECECEC",
        "accent": "#FFB000",
        "accent_dim": "#FFC940",
        "accent_bg": "rgba(255,176,0,0.14)",
        "user_bubble": "#2F2F2F",
        "danger": "#F87171",
        "success": "#34D399",
        "shadow": "rgba(0,0,0,0.3)",
        "shadow_strong": "rgba(0,0,0,0.5)",
    },
}


def build_css(theme: str) -> str:
    """根据主题名生成完整 CSS 字符串。"""
    t = THEMES.get(theme, THEMES["light"])

    vars_css = f"""
:root {{
  --bg-app: {t['bg_app']};
  --bg-sidebar: {t['bg_sidebar']};
  --bg-hover: {t['bg_hover']};
  --bg-active: {t['bg_active']};
  --bg-input: {t['bg_input']};
  --bg-code: {t['bg_code']};
  --bg-code-header: {t['bg_code_header']};
  --bg-tool: {t['bg_tool']};
  --bg-tool-hover: {t['bg_tool_hover']};
  --border: {t['border']};
  --border-strong: {t['border_strong']};
  --text: {t['text']};
  --text-dim: {t['text_dim']};
  --text-faint: {t['text_faint']};
  --text-on-code: {t['text_on_code']};
  --accent: {t['accent']};
  --accent-dim: {t['accent_dim']};
  --accent-bg: {t['accent_bg']};
  --user-bubble: {t['user_bubble']};
  --danger: {t['danger']};
  --success: {t['success']};
  --shadow: {t['shadow']};
  --shadow-strong: {t['shadow_strong']};

  /* 间距刻度 4px 基准 */
  --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px; --sp-4: 16px;
  --sp-5: 24px; --sp-6: 32px; --sp-7: 48px; --sp-8: 64px;
  /* 圆角 */
  --r-sm: 6px; --r-md: 8px; --r-lg: 12px; --r-pill: 28px;
  /* 字体：不依赖任何远程字体，全用系统字体 + 中文 fallback */
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
               "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC",
               "Helvetica Neue", Arial, ui-sans-serif, sans-serif;
  --font-mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas,
               "Noto Sans Mono CJK SC", "PingFang SC", monospace;
  --ease: cubic-bezier(.22,.61,.36,1);
}}
"""

    components_css = """
/* 注：原版 @import Google Fonts JetBrains Mono 已被移除。
   旧版本在用户浏览器卡住会导致整张 CSS 不渲染，且在受限网络中
   fonts.googleapis.com / fonts.gstatic.com 直接连接失败。
   现在直接用系统等宽字体（macOS/Linux/Windows 都自带等价物）。 */

/* ===== 隐藏 Streamlit 默认装饰 ===== */
#MainMenu, footer, header[data-testid="stHeader"] { display: none !important; }
.stApp > header { background: transparent !important; }
.stApp { background: var(--bg-app) !important; color: var(--text) !important;
         font-family: var(--font-sans) !important; }

/* 隐藏 stMarkdown 的默认容器 padding，让自定义布局贴边 */
.stApp .block-container { padding-top: 0 !important; padding-bottom: 0 !important;
                          max-width: 100% !important; }

/* ===== 侧栏 ===== */
section[data-testid="stSidebar"] {
  background: var(--bg-sidebar) !important;
  border-right: 1px solid var(--border) !important;
  width: 260px !important;
}
section[data-testid="stSidebar"] > div { padding-top: 8px !important; }
section[data-testid="stSidebar"] .stMarkdown { font-size: 14px !important; }

/* 侧栏收起态 */
.sidebar-collapsed section[data-testid="stSidebar"] {
  width: 0 !important; min-width: 0 !important; border: none !important;
}
.sidebar-collapsed section[data-testid="stSidebar"] > div { display: none !important; }

/* 侧栏品牌区 */
.sb-brand {
  font-size: 18px; font-weight: 600; color: var(--text);
  padding: 8px 12px; display: flex; align-items: center; gap: 8px;
}
.sb-brand .sub { font-size: 11px; font-weight: 400; color: var(--text-dim); }

/* 新对话按钮 */
.sb-new-chat button {
  width: 100% !important; border: 1px solid var(--border) !important;
  background: var(--bg-app) !important; color: var(--text) !important;
  border-radius: var(--r-md) !important; padding: 10px 12px !important;
  font-size: 14px !important; font-weight: 500 !important;
  justify-content: flex-start !important; gap: 8px !important;
  transition: background .15s var(--ease) !important;
}
.sb-new-chat button:hover { background: var(--bg-hover) !important; }

/* 历史会话分组标题 */
.sb-group-title {
  font-size: 12px; font-weight: 600; color: var(--text-faint);
  padding: 16px 12px 4px; text-transform: none; letter-spacing: 0;
}

/* 历史会话条目 */
.sb-chat-item button {
  width: 100% !important; background: transparent !important;
  color: var(--text-dim) !important; border: none !important;
  border-radius: var(--r-sm) !important; padding: 8px 12px !important;
  font-size: 14px !important; text-align: left !important;
  justify-content: flex-start !important; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
  transition: background .12s var(--ease) !important;
}
.sb-chat-item button:hover { background: var(--bg-hover) !important; color: var(--text) !important; }
.sb-chat-item.active button { background: var(--bg-active) !important; color: var(--text) !important; }

/* 侧栏底部功能区 */
.sb-footer {
  margin-top: auto; padding: 8px; border-top: 1px solid var(--border);
}
.sb-footer .stButton > button {
  width: 100% !important; background: transparent !important;
  color: var(--text-dim) !important; border: none !important;
  border-radius: var(--r-sm) !important; padding: 8px 12px !important;
  font-size: 13px !important; text-align: left !important;
  justify-content: flex-start !important; gap: 8px !important;
  transition: background .12s var(--ease) !important;
}
.sb-footer .stButton > button:hover { background: var(--bg-hover) !important; color: var(--text) !important; }

/* ===== 顶栏 ===== */
.topbar {
  position: sticky; top: 0; z-index: 100;
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px; border-bottom: 1px solid var(--border);
  background: var(--bg-app);
}
.topbar-left, .topbar-right { display: flex; align-items: center; gap: 8px; }
.topbar-model {
  font-size: 18px; font-weight: 600; color: var(--text);
  display: flex; align-items: center; gap: 4px; cursor: pointer;
  padding: 6px 10px; border-radius: var(--r-sm);
  transition: background .12s var(--ease);
}
.topbar-model:hover { background: var(--bg-hover); }
.topbar-model .chev { color: var(--text-dim); font-size: 14px; }
.topbar-mode-tag {
  font-size: 12px; color: var(--text-dim); padding: 4px 10px;
  border: 1px solid var(--border); border-radius: var(--r-pill);
}
.topbar-icon-btn {
  width: 36px; height: 36px; border-radius: var(--r-sm);
  border: none !important; background: transparent !important;
  color: var(--text-dim) !important; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background .12s var(--ease);
}
.topbar-icon-btn:hover { background: var(--bg-hover) !important; color: var(--text) !important; }

/* ===== 对话区 ===== */
.chat-container {
  max-width: 768px; margin: 0 auto; padding: 24px 16px 160px;
}
.chat-container .stMarkdown { font-size: 16px !important; line-height: 1.75 !important; }

/* 用户消息：无气泡，右对齐容器，文字左对齐 */
.msg-user {
  display: flex; justify-content: flex-end; padding: 12px 0;
}
.msg-user .bubble {
  max-width: 85%; background: var(--user-bubble);
  padding: 14px 18px; border-radius: var(--r-lg);
  font-size: 16px; line-height: 1.75; color: var(--text);
  white-space: pre-wrap; word-break: break-word;
}

/* AI 消息：头像 + 名字 + 正文，无气泡 */
.msg-ai { display: flex; gap: 16px; padding: 12px 0; }
.msg-ai .avatar {
  width: 32px; height: 32px; border-radius: 50%; flex-shrink: 0;
  background: var(--accent); display: flex; align-items: center; justify-content: center;
  font-size: 16px; color: #1a1a1a; font-weight: 700;
}
.msg-ai .body { flex: 1; min-width: 0; }
.msg-ai .name { font-size: 14px; font-weight: 600; color: var(--text);
                margin-bottom: 4px; }
.msg-ai .content { font-size: 16px; line-height: 1.75; color: var(--text); }
.msg-ai .content p { margin: 0 0 12px; }
.msg-ai .content p:last-child { margin-bottom: 0; }
.msg-ai .content ul, .msg-ai .content ol { margin: 0 0 12px; padding-left: 24px; }
.msg-ai .content li { margin: 4px 0; }
.msg-ai .content h1, .msg-ai .content h2, .msg-ai .content h3 {
  margin: 20px 0 10px; font-weight: 600; line-height: 1.3;
}
.msg-ai .content h1 { font-size: 22px; }
.msg-ai .content h2 { font-size: 19px; }
.msg-ai .content h3 { font-size: 17px; }

/* ===== 代码块 ===== */
.code-block {
  background: var(--bg-code); border-radius: var(--r-md);
  margin: 12px 0; overflow: hidden; border: 1px solid var(--bg-code-header);
}
.code-header {
  display: flex; align-items: center; justify-content: space-between;
  background: var(--bg-code-header); padding: 8px 14px;
  font-size: 12px; color: var(--text-faint);
  font-family: var(--font-mono);
}
.code-lang { font-weight: 500; }
.code-copy {
  background: transparent; border: none; color: var(--text-faint);
  cursor: pointer; font-size: 12px; padding: 2px 8px; border-radius: 4px;
  font-family: var(--font-mono); transition: background .12s, color .12s;
}
.code-copy:hover { background: rgba(255,255,255,0.08); color: var(--text-on-code); }
.code-block pre {
  margin: 0; padding: 14px 16px; overflow-x: auto;
  font-family: var(--font-mono); font-size: 13.5px; line-height: 1.6;
  color: var(--text-on-code);
}
.code-block pre code { font-family: inherit; background: transparent; padding: 0; }

/* ===== 工具调用折叠卡片 ===== */
.tool-call {
  background: var(--bg-tool); border: 1px solid var(--border);
  border-radius: var(--r-md); margin: 10px 0; overflow: hidden;
  transition: border-color .15s var(--ease);
}
.tool-call:hover { border-color: var(--accent); }
.tool-call-header {
  display: flex; align-items: center; gap: 8px; padding: 10px 14px;
  cursor: pointer; font-size: 14px; color: var(--text-dim);
  font-family: var(--font-mono);
}
.tool-call-header .arrow {
  font-size: 10px; transition: transform .15s var(--ease); color: var(--accent);
}
.tool-call.expanded .tool-call-header .arrow { transform: rotate(90deg); }
.tool-call-header .tool-name { color: var(--accent); font-weight: 500; }
.tool-call-header .tool-status { margin-left: auto; font-size: 12px; }
.tool-call-header .tool-status.ok { color: var(--success); }
.tool-call-header .tool-status.err { color: var(--danger); }
.tool-call-body {
  display: none; padding: 0 14px 12px; border-top: 1px solid var(--border);
  font-size: 13px; color: var(--text-dim); font-family: var(--font-mono);
}
.tool-call.expanded .tool-call-body { display: block; }
.tool-call-body pre {
  background: var(--bg-code); color: var(--text-on-code);
  padding: 10px 12px; border-radius: var(--r-sm); margin: 8px 0 0;
  font-size: 12.5px; overflow-x: auto;
}

/* ===== RAG 引用 ===== */
.rag-sources {
  margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border);
}
.rag-sources-title {
  font-size: 12px; font-weight: 600; color: var(--text-dim);
  margin-bottom: 8px; display: flex; align-items: center; gap: 6px;
}
.rag-source-item {
  background: var(--bg-tool); border: 1px solid var(--border);
  border-left: 3px solid var(--accent); border-radius: var(--r-sm);
  padding: 8px 12px; margin-bottom: 6px; font-size: 13px;
  color: var(--text-dim);
}
.rag-source-item .src-name { color: var(--text); font-weight: 500;
                             font-family: var(--font-mono); font-size: 12px; }

/* ===== 底部输入框（药丸形） ===== */
.input-bar-wrap {
  position: fixed; bottom: 0; left: 0; right: 0;
  background: linear-gradient(to top, var(--bg-app) 60%, transparent);
  padding: 16px 16px 20px; z-index: 90;
}
.input-bar {
  max-width: 768px; margin: 0 auto;
  background: var(--bg-input); border: 1px solid var(--border-strong);
  border-radius: var(--r-pill); padding: 8px 8px 8px 20px;
  display: flex; align-items: flex-end; gap: 8px;
  box-shadow: 0 2px 12px var(--shadow);
  transition: border-color .15s var(--ease), box-shadow .15s var(--ease);
}
.input-bar:focus-within {
  border-color: var(--text-faint);
  box-shadow: 0 2px 16px var(--shadow-strong);
}
.input-bar textarea {
  flex: 1; border: none !important; background: transparent !important;
  color: var(--text) !important; resize: none !important;
  font-size: 16px !important; line-height: 1.5 !important;
  font-family: var(--font-sans) !important; padding: 8px 0 !important;
  max-height: 200px; outline: none !important; box-shadow: none !important;
}
.input-bar textarea::placeholder { color: var(--text-faint); }
.input-controls { display: flex; align-items: center; gap: 4px; }
.input-icon-btn {
  width: 36px; height: 36px; border-radius: 50%;
  border: none !important; background: transparent !important;
  color: var(--text-dim) !important; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; transition: background .12s, color .12s;
}
.input-icon-btn:hover { background: var(--bg-hover) !important; color: var(--text) !important; }
.input-icon-btn.active { color: var(--accent) !important; background: var(--accent-bg) !important; }
.send-btn {
  width: 36px; height: 36px; border-radius: 50%;
  border: none !important; background: var(--text) !important;
  color: var(--bg-app) !important; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; transition: opacity .12s, transform .12s;
}
.send-btn:hover { opacity: 0.85; }
.send-btn:disabled { opacity: 0.3; cursor: not-allowed; transform: none; }
.send-btn:active { transform: scale(0.92); }

/* 输入框下方提示 */
.input-hint {
  max-width: 768px; margin: 6px auto 0; text-align: center;
  font-size: 12px; color: var(--text-faint);
}

/* ===== 空状态欢迎页 ===== */
.welcome {
  max-width: 768px; margin: 0 auto; padding: 12vh 16px 0; text-align: center;
}
.welcome-title {
  font-size: 30px; font-weight: 600; color: var(--text);
  margin-bottom: 32px; letter-spacing: -0.01em;
}
.welcome-cards {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
  max-width: 640px; margin: 0 auto;
}
.welcome-card {
  text-align: left; padding: 14px 16px; border: 1px solid var(--border);
  border-radius: var(--r-md); cursor: pointer; background: var(--bg-app);
  transition: background .12s var(--ease), border-color .12s;
  font-size: 14px; color: var(--text-dim);
}
.welcome-card:hover { background: var(--bg-hover); border-color: var(--border-strong); }
.welcome-card .wc-title { color: var(--text); font-weight: 500; margin-bottom: 2px; }

/* ===== 流式光标 ===== */
.stream-cursor::after {
  content: '▍'; display: inline-block; color: var(--accent);
  animation: blink 1s steps(2) infinite; margin-left: 1px;
}
@keyframes blink { 50% { opacity: 0; } }

/* ===== 思考中指示器 ===== */
.thinking-dots { display: inline-flex; gap: 4px; align-items: center; }
.thinking-dots span {
  width: 6px; height: 6px; border-radius: 50%; background: var(--text-faint);
  animation: bounce 1.4s infinite ease-in-out both;
}
.thinking-dots span:nth-child(1) { animation-delay: -0.32s; }
.thinking-dots span:nth-child(2) { animation-delay: -0.16s; }
@keyframes bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* ===== 模式切换标签（输入框内） ===== */
.mode-pill {
  font-size: 12px; padding: 4px 10px; border-radius: var(--r-pill);
  border: 1px solid var(--border); color: var(--text-dim);
  cursor: pointer; transition: all .12s; white-space: nowrap;
  font-family: var(--font-mono);
}
.mode-pill:hover { background: var(--bg-hover); color: var(--text); }
.mode-pill.active { background: var(--accent-bg); color: var(--accent-dim);
                    border-color: var(--accent); }

/* ===== 折叠区通用 ===== */
.stExpander {
  background: transparent !important; border: none !important;
}
.stExpander > details {
  background: transparent !important; border: none !important;
}
.stExpander > details > summary {
  font-size: 13px !important; color: var(--text-dim) !important;
  padding: 6px 0 !important;
}

/* ===== 滚动条 ===== */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-faint); }

/* ===== 响应式 ===== */
@media (max-width: 768px) {
  .chat-container, .input-bar, .welcome, .input-hint { max-width: 100%; }
  .welcome-cards { grid-template-columns: 1fr; }
  .msg-user .bubble { max-width: 95%; }
}
"""

    return f"<style>\n{vars_css}\n{components_css}\n</style>"
