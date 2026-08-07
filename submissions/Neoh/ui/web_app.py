# ---- ROCm 环境变量（必须在所有其他 import 之前设置）----
# W7900 / RX 7900 系列是 gfx1100，vLLM 需要 override 才能识别
import os
os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "11.0.0")
os.environ.setdefault("PYTORCH_ROCM_ARCH", "gfx1100")
os.environ.setdefault("HIP_VISIBLE_DEVICES", "0")
os.environ.setdefault("HSA_ENABLE_SDMA", "0")
# 多卡 TP 必需
os.environ.setdefault("VLLM_WORKER_MULTIPROC_METHOD", "spawn")
os.environ.setdefault("RCCL_NCCL_NCHANNELS", "4")
os.environ.setdefault("RCCL_NCCL_NSOCKETS_PERCHANNEL", "8")
os.environ.setdefault("NCCL_SOCKET_IFNAME", "lo")
os.environ.setdefault("HSA_ENABLE_INTERRUPTIBLE", "0")

import streamlit as st
import sys
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import tools  # noqa: F401  导入即触发所有工具注册到 registry
from inference.engine import InferenceEngine, InferenceConfig
from memory.manager import MemoryManager
from agent.core import RadeonAgent
from tools.registry import registry
from streamlit_extras.stylable_container import stylable_container

# 界面模式 -> agent prompt_mode
MODE_MAP = {
    "Hardware R&D": "hardware",
    "Generic": "generic",
}

# 14 项已注册技能的一句话示例（页面 Skills 网格，点一下即以 Agent Task 模式执行）
SKILL_EXAMPLES = [
    ("generate_verilog", "Generate a Verilog module for an I2C slave with an 8-bit register file"),
    ("generate_testbench", "Write a Verilog testbench for a 4-bit ALU named alu4"),
    ("read_file", "Read data/hardware_documents/W25Q128JV_SPI_Flash_Datasheet_sample.txt"),
    ("write_file", "Write a short TMP117 spec summary to generated/tmp117_summary.md"),
    ("list_directory", "List the files under data/hardware_documents"),
    ("create_directory", "Create a directory called generated/rtl"),
    ("delete_file", "Delete the file generated/scratch.txt"),
    ("execute_command", "Run the command rocm-smi --showproductname"),
    ("execute_python", "Run Python that prints the I2C addresses 0x48 to 0x4B in hex"),
    ("code_interpreter", "Compute the RC time constant for R = 10 kohm and C = 100 nF"),
    ("format_code", "Format the Python file scripts/benchmark.py with black"),
    ("get_gpu_info", "Show the GPU status of this machine"),
    ("get_system_info", "Report the system information of this machine"),
    ("get_process_list", "Show the top processes by memory usage"),
]

# 技能目录（含图标 / 分类 / 一句话说明），用于空状态与侧栏的 GitHub 风格浏览
SKILLS = [
    {"name": "generate_verilog",  "icon": "🧩", "cat": "HDL / Verilog",
     "desc": "生成 Verilog 模块（如 I2C 从机寄存器文件）"},
    {"name": "generate_testbench", "icon": "🧪", "cat": "HDL / Verilog",
     "desc": "为 RTL 写 testbench 并仿真验证"},
    {"name": "read_file",         "icon": "📄", "cat": "Filesystem",
     "desc": "读取本地文件内容"},
    {"name": "write_file",        "icon": "✍️", "cat": "Filesystem",
     "desc": "写入 / 生成文件（高风险）"},
    {"name": "list_directory",    "icon": "📁", "cat": "Filesystem",
     "desc": "列出目录下的文件"},
    {"name": "create_directory",  "icon": "📂", "cat": "Filesystem",
     "desc": "创建新目录"},
    {"name": "delete_file",       "icon": "🗑️", "cat": "Filesystem",
     "desc": "删除文件（高风险）"},
    {"name": "get_gpu_info",      "icon": "🎛️", "cat": "System / GPU",
     "desc": "查看 AMD GPU 状态与显存"},
    {"name": "get_system_info",   "icon": "💻", "cat": "System / GPU",
     "desc": "查看系统软硬件信息"},
    {"name": "get_process_list",  "icon": "📊", "cat": "System / GPU",
     "desc": "查看进程与内存占用"},
    {"name": "execute_command",   "icon": "⌨️", "cat": "System / GPU",
     "desc": "执行 shell 命令（高风险）"},
    {"name": "execute_python",    "icon": "🐍", "cat": "Code / Compute",
     "desc": "运行 Python 代码（高风险）"},
    {"name": "code_interpreter",  "icon": "🧮", "cat": "Code / Compute",
     "desc": "数值计算 / 符号求解"},
    {"name": "format_code",       "icon": "🎨", "cat": "Code / Compute",
     "desc": "用 black 格式化代码"},
]
SKILL_CATS = ["全部"] + sorted({s["cat"] for s in SKILLS})

# Web 模式无 CLI stdin，审批类工具（write_file/execute_command/execute_python 等）
# 不能走 CLI input()（Streamlit 单次脚本执行中阻塞读 stdin 会卡死），
# 因此改为「策略式审批」：由 Tool safety 决定放行还是拦截，决策同样写入审计日志。
SAFETY_AUTO = "Auto-approve (demo)"
SAFETY_BLOCK = "Block high-risk"


def web_approval_callback(tool_name: str, arguments: dict, description: str = "") -> bool:
    policy = st.session_state.get("tool_safety", SAFETY_AUTO)
    return policy == SAFETY_AUTO


st.set_page_config(
    page_title="Bedrock · Hardware R&D Assistant",
    page_icon="🤖",
    layout="wide",
    # 主题由 .streamlit/config.toml 设置（Streamlit 1.61+ 已从 set_page_config 移除
    # theme 参数）。亮/暗切换由下方 CSS 变量实现。
)

# ---------------------------------------------------------------------------
# Bedrock · Scope Workbench：以「示波器 / 逻辑分析仪」为设计语言的本地硬件研发
# 工作台。签名元素：(1) 常驻顶栏 + 欢迎页的实时示波器扫描轨迹（phosphor amber +
# logic cyan 双通道）；(2) 对话气泡作为 CH1(amber) / CH2(cyan) 双通道。底图是淡
# PCB 栅格。字体：Space Grotesk（display）/ 系统 sans（body）/ JetBrains Mono
# （仪表读数）。通过 CSS 变量实现 亮/暗 双色。刻意避开 AI 默认三件套（奶油+衬线+
# 陶土 / 近黑+荧光 / 报纸零圆角）——配色取自硬件本体世界而非模板。
# ---------------------------------------------------------------------------
THEMES = {
    "dark": {
        "bg_app": "#0E1622",
        "bg_sidebar": "#101A28",
        "bg_main": "#0E1622",
        "bg_surface": "#15202F",
        "bg_msg_user": "#1B2A3D",
        "bg_msg_asst": "#15202F",
        "border": "#223247",
        "border_strong": "#2E425C",
        "text": "#E6ECF3",
        "text_dim": "#8AA0B5",
        "accent": "#2D6CDF",
        "accent_blue": "#2D6CDF",
        "amber": "#FFB000",
        "cyan": "#34D0DB",
        "radeon": "#ED1C24",
        "grid": "rgba(120,160,200,.06)",
        "ink": "#0E1622",
        "paper": "#F3F6FA",
        "user_text": "#E6ECF3",
    },
    "light": {
        "bg_app": "#EEF2F7",
        "bg_sidebar": "#E4EAF2",
        "bg_main": "#F3F6FA",
        "bg_surface": "#FFFFFF",
        "bg_msg_user": "#FFFFFF",
        "bg_msg_asst": "#FFFFFF",
        "border": "#D5DEE9",
        "border_strong": "#C2CFDE",
        "text": "#16202B",
        "text_dim": "#5B6B7B",
        "accent": "#2D6CDF",
        "accent_blue": "#2D6CDF",
        "amber": "#C77D00",
        "cyan": "#1293A0",
        "radeon": "#D9302F",
        "grid": "rgba(43,108,176,.06)",
        "ink": "#16202B",
        "paper": "#F3F6FA",
        "user_text": "#16202B",
    },
}

if "theme" not in st.session_state:
    st.session_state.theme = "light"
if "sidebar_open" not in st.session_state:
    st.session_state.sidebar_open = True
# ChatGLM 风底部输入条的状态
if "rag_search" not in st.session_state:
    st.session_state.rag_search = True
if "deep_think" not in st.session_state:
    st.session_state.deep_think = False
if "show_upload" not in st.session_state:
    st.session_state.show_upload = False
if "interaction" not in st.session_state:
    st.session_state.interaction = "Chat (RAG)"
if "mode" not in st.session_state:
    st.session_state.mode = "Hardware R&D"
_theme = st.session_state.theme
if _theme not in THEMES:
    _theme = "light"
_p = THEMES[_theme]

VARS = """
:root {{
  --bg-app: {bg_app};
  --bg-sidebar: {bg_sidebar};
  --bg-main: {bg_main};
  --bg-surface: {bg_surface};
  --bg-msg-user: {bg_msg_user};
  --bg-msg-asst: {bg_msg_asst};
  --border: {border};
  --border-strong: {border_strong};
  --text: {text};
  --text-dim: {text_dim};
  --accent: {accent};
  --accent-blue: {accent_blue};
  --amber: {amber};
  --cyan: {cyan};
  --radeon: {radeon};
  --grid: {grid};
  --ink: {ink};
  --paper: {paper};
  --user-text: {user_text};
}}
""".format(**_p)

CSS = "<style>\n" + VARS + """
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
  --font-display: 'Space Grotesk', ui-sans-serif, system-ui, 'Segoe UI', Roboto, sans-serif;
  --font-body: ui-sans-serif, system-ui, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;

  /* 统一间距刻度（8px 基准），保证全站垂直节奏一致 */
  --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px; --sp-4: 16px;
  --sp-5: 24px; --sp-6: 32px; --sp-7: 48px; --sp-8: 64px;
  /* 圆角刻度 */
  --r-sm: 8px; --r-md: 12px; --r-lg: 16px; --r-pill: 22px;
  /* 统一的焦点/悬浮描边色 */
  --ring: color-mix(in srgb, var(--accent) 55%, transparent);
  --ease: cubic-bezier(.22,.61,.36,1);
}

/* 彻底隐藏 Streamlit 默认头部/页脚 */
#MainMenu, footer, header[data-testid="stHeader"] { display: none !important; }

/* 应用底：PCB 栅格 substrate + 主题色 */
.stApp {
  background:
    linear-gradient(var(--grid) 1px, transparent 1px) 0 0 / 28px 28px,
    linear-gradient(90deg, var(--grid) 1px, transparent 1px) 0 0 / 28px 28px,
    var(--bg-app) !important;
  color: var(--text) !important;
  font-family: var(--font-body) !important;
}

/* 主对话列：居中列，带 PCB 栅格底与左右细边 */
.block-container {
    max-width: 920px;
    margin: 0 auto;
    padding-top: 0 !important;
    padding-bottom: var(--sp-5) !important;
    padding-left: var(--sp-5) !important;
    padding-right: var(--sp-5) !important;
    background:
      linear-gradient(var(--grid) 1px, transparent 1px) 0 0 / 28px 28px,
      linear-gradient(90deg, var(--grid) 1px, transparent 1px) 0 0 / 28px 28px,
      var(--bg-main) !important;
    border-left: 1px solid var(--border) !important;
    border-right: 1px solid var(--border) !important;
}

/* 细滚动条，融入示波器主题 */
.block-container ::-webkit-scrollbar,
.stApp ::-webkit-scrollbar { width: 9px; height: 9px; }
.block-container ::-webkit-scrollbar-thumb,
.stApp ::-webkit-scrollbar-thumb {
    background: color-mix(in srgb, var(--border-strong) 85%, transparent);
    border-radius: 10px;
}
.block-container ::-webkit-scrollbar-thumb:hover,
.stApp ::-webkit-scrollbar-thumb:hover { background: var(--border-strong); }
.block-container ::-webkit-scrollbar-track,
.stApp ::-webkit-scrollbar-track { background: transparent; }

/* ---------- 顶栏：示波器屏 + 品牌（主区顶部常驻行，不用 fixed，避免与侧栏重叠）---------- */
.topbar-brand {
    display: flex; align-items: center; gap: 12px;
    font-family: var(--font-display); font-size: 18px; font-weight: 700; letter-spacing: .2px;
}
.topbar-brand svg { flex: 0 0 auto; }
.topbar-brand > div:not(.topbar-pill) { line-height: 1.15; }
.topbar-brand span { color: var(--text-dim); font-weight: 500;
    font-family: var(--font-mono); font-size: 11px; letter-spacing: .4px; text-transform: uppercase; }
.topbar-pill {
    margin-left: auto;
    font-family: var(--font-mono); font-size: 11px; font-weight: 600; color: var(--accent);
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
    border-radius: 20px; padding: 3px 12px; letter-spacing: .3px;
    white-space: nowrap;
}

/* 顶栏「模型选择」下拉（仿 ChatGLM）：做成一行紧凑的模型 picker */
.st-key-mode_select_top { margin-top: 4px !important; }
.st-key-mode_select_top [data-testid="stSelectbox"] { background: var(--bg-surface) !important;
    border: 1px solid var(--border-strong) !important; border-radius: 10px !important; }
.st-key-mode_select_top [data-testid="stSelectbox"]:hover { border-color: var(--accent) !important; }
.st-key-mode_select_top [data-testid="stSelectbox"] > div { color: var(--text) !important;
    font-family: var(--font-display); font-weight: 600; font-size: 14px; }
.st-key-mode_select_top svg { fill: var(--text-dim) !important; }
.st-key-mode_select_top .stCaption { color: var(--text-dim) !important; }

/* 示波器屏（顶栏 + 欢迎页共用） */
.scope {
  display: block; border-radius: 5px;
  border: 1px solid #1d2c40;
  box-shadow: inset 0 0 12px rgba(0,0,0,.55);
  background:
    repeating-linear-gradient(0deg, rgba(52,208,219,.05) 0 1px, transparent 1px 6px),
    repeating-linear-gradient(90deg, rgba(52,208,219,.05) 0 1px, transparent 1px 6px),
    #0B1320;
}
.scope .tr-amber { fill: none; stroke: var(--amber); stroke-width: 1.4;
  filter: drop-shadow(0 0 2px color-mix(in srgb, var(--amber) 70%, transparent)); }
.scope .tr-cyan { fill: none; stroke: var(--cyan); stroke-width: 1.4;
  filter: drop-shadow(0 0 2px color-mix(in srgb, var(--cyan) 70%, transparent)); }
.scope-trace { animation: scope-scroll 5s linear infinite; }
@keyframes scope-scroll { from { transform: translateX(0); } to { transform: translateX(-120px); } }
@media (prefers-reduced-motion: reduce) { .scope-trace { animation: none; } }

/* ---------- 侧栏 ---------- */
section[data-testid="stSidebar"] { background: var(--bg-sidebar) !important;
    width: 248px !important; min-width: 248px !important; }
section[data-testid="stSidebar"] > div:first-child {
    background: var(--bg-sidebar) !important;
    border-right: 1px solid var(--border) !important;
    width: 248px !important; min-width: 248px !important;
}
section[data-testid="stSidebar"] * { color: var(--text) !important; }

.sb-brand { font-family: var(--font-display); font-size: 16px; font-weight: 700; color: var(--text); }
.sb-brand .sub { font-family: var(--font-mono); font-size: 10px; letter-spacing: .4px;
    text-transform: uppercase; color: var(--text-dim); font-weight: 500; }
.sb-section { font-family: var(--font-mono); font-size: 11px; font-weight: 600; color: var(--text-dim);
    text-transform: uppercase; letter-spacing: .6px; margin: 4px 0; }

section[data-testid="stSidebar"] .streamlit-expanderHeader {
    font-size: 13px !important; font-weight: 600 !important; color: var(--text-dim) !important;
    background: transparent !important;
}
section[data-testid="stSidebar"] .stButton > button:not([kind="primary"]) {
    background: var(--bg-main); color: var(--text);
    border: 1px solid var(--border); border-radius: 10px; font-weight: 600;
    text-align: center; white-space: nowrap; width: 100%;
    transition: all .15s ease;
}
section[data-testid="stSidebar"] .stButton > button:not([kind="primary"]):hover {
    border-color: var(--border-strong); background: var(--bg-app);
}
section[data-testid="stSidebar"] .stRadio label,
section[data-testid="stSidebar"] .stToggle label,
section[data-testid="stSidebar"] .stCheckbox label { color: var(--text) !important; }
section[data-testid="stSidebar"] .stFileUploader { border-color: var(--border) !important; }
section[data-testid="stSidebar"] .stCaption { color: var(--text-dim) !important; }
section[data-testid="stSidebar"] .stDivider { border-color: var(--border) !important; }

.kb-badge {
    display: inline-block;
    font-family: var(--font-mono);
    background: color-mix(in srgb, var(--accent-blue) 16%, transparent);
    color: var(--accent-blue);
    border: 1px solid color-mix(in srgb, var(--accent-blue) 38%, transparent);
    border-radius: 20px; padding: 2px 12px; font-size: 13px; font-weight: 600;
}

.stChatMessage [data-testid="stChatMessageAvatarUser"],
.stChatMessage [data-testid="stChatMessageAvatarAssistant"] { display: none !important; }

/* ---------- 对话气泡 = 示波器双通道 ---------- */
.stChatMessage {
    position: relative;
    border-radius: var(--r-md) !important; padding: 14px 18px !important;
    margin-bottom: var(--sp-4) !important; border: 1px solid var(--border) !important;
    background: var(--bg-msg-asst) !important; color: var(--text) !important;
    box-shadow: 0 1px 2px rgba(0,0,0,.18) !important;
    transition: border-color .2s var(--ease), box-shadow .2s var(--ease),
                transform .2s var(--ease);
}
.stChatMessage:hover { border-color: var(--border-strong) !important; }
.stChatMessage [data-testid="stChatMessageContent"] { background: transparent !important;
    line-height: 1.7 !important; }
.stChatMessage [data-testid="stChatMessageContent"] p { margin: 0 0 10px !important; }
.stChatMessage [data-testid="stChatMessageContent"] p:last-child { margin-bottom: 0 !important; }
.stChatMessage [data-testid="stChatMessageContent"] pre {
    background: var(--bg-app) !important; border: 1px solid var(--border) !important;
    border-radius: var(--r-sm) !important; padding: 12px 14px !important;
}
.stChatMessage [data-testid="stChatMessageContent"] code {
    font-family: var(--font-mono); font-size: .9em; }

/* CH1 = 用户 = amber 通道（右偏，更贴近「我发的」直觉） */
.stChatMessage:has([data-testid="stChatMessageAvatarUser"]) {
    border-left: 3px solid var(--amber) !important;
    border-right: 3px solid color-mix(in srgb, var(--amber) 28%, transparent) !important;
    background: color-mix(in srgb, var(--amber) 9%, var(--bg-surface)) !important;
    margin-left: auto !important; margin-right: 0 !important; max-width: 88% !important;
}
/* CH2 = 助手 = cyan 通道（左对齐，占满） */
.stChatMessage:has([data-testid="stChatMessageAvatarAssistant"]) {
    border-left: 3px solid var(--cyan) !important;
    background: color-mix(in srgb, var(--cyan) 9%, var(--bg-surface)) !important;
    margin-right: 44px !important; max-width: 96% !important;
}
/* 通道标签（CH1 / CH2）统一为右上角小徽标 */
.stChatMessage:has([data-testid="stChatMessageAvatarUser"])::after,
.stChatMessage:has([data-testid="stChatMessageAvatarAssistant"])::after {
    content: "CH1"; position: absolute; top: -11px; right: 12px;
    font-family: var(--font-mono); font-size: 10px; font-weight: 600; line-height: 1;
    background: var(--bg-main); padding: 2px 7px; border-radius: 6px;
}
.stChatMessage:has([data-testid="stChatMessageAvatarUser"])::after {
    content: "CH1"; color: var(--amber);
    border: 1px solid color-mix(in srgb, var(--amber) 45%, transparent);
}
.stChatMessage:has([data-testid="stChatMessageAvatarAssistant"])::after {
    content: "CH2"; color: var(--cyan);
    border: 1px solid color-mix(in srgb, var(--cyan) 45%, transparent);
}

.stChatInput {
    background: var(--bg-surface) !important; border: 1px solid var(--border-strong) !important;
    border-radius: 24px !important; padding: 8px 14px !important;
}
.stChatInput:focus-within { border-color: var(--accent) !important; }
.stChatInput textarea { background: transparent !important; color: var(--text) !important;
    border: none !important; font-size: 15px !important; }

/* ---------- 页面卡片（Skills / 系统面板）---------- */
.deck {
    border: 1px solid var(--border);
    border-radius: 16px;
    background: var(--bg-surface);
    padding: 14px 16px;
    margin-bottom: 16px;
}
.skills-title { font-family: var(--font-display); font-size: 15px; font-weight: 700; color: var(--text);
    margin: 2px 0 8px; display: flex; align-items: center; gap: 8px; }
.skills-title .cnt {
    font-family: var(--font-mono); font-size: 11px; font-weight: 600; color: var(--accent);
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
    border-radius: 20px; padding: 1px 9px;
}
/* 主区域里的技能按钮 = 建议卡风格 */
.stButton > button {
    background: var(--bg-sidebar) !important; color: var(--text) !important;
    border: 1px solid var(--border) !important; border-radius: 12px !important;
    text-align: left !important; font-weight: 500 !important; font-size: 13px !important;
    padding: 10px 12px !important; line-height: 1.35 !important; width: 100% !important;
    white-space: normal !important; height: auto !important;
    display: flex !important; align-items: center; gap: 6px;
    transition: all .15s ease;
}
.stButton > button:hover {
    background: color-mix(in srgb, var(--accent) 10%, var(--bg-sidebar)) !important;
    border-color: var(--accent) !important; color: var(--accent) !important;
}
.stButton > button::before { content: "▸ "; color: var(--accent); flex: 0 0 auto;
    font-family: var(--font-mono); }

/* ---------- 欢迎页 hero（克制版：以问答为核心，大量留白）---------- */
.hero { text-align: center; margin-top: 6vh; color: var(--text-dim); }
.hero .hero-scope { display: flex; justify-content: center; margin-bottom: 18px; }
.hero .hero-scope svg { width: 280px; height: 58px; }
.hero .hero-title { font-family: var(--font-display); font-size: 40px; font-weight: 700;
    color: var(--text); letter-spacing: .5px; margin-bottom: 4px; }
.hero .hero-sub { font-family: var(--font-mono); font-size: 12px; letter-spacing: .6px;
    text-transform: uppercase; color: var(--accent); margin-bottom: 14px; }
.hero .hero-hint { font-size: 14px; color: var(--text-dim); max-width: 460px; margin: 0 auto; }

/* 克制版：更小的示波器 + 更大留白 + 标题缩小 */
.hero.hero-qna { margin-top: 5vh; }
.hero.hero-qna .hero-scope { margin-bottom: 22px; }
.hero.hero-qna .hero-scope svg { width: 240px; height: 50px; }
.hero.hero-qna .hero-title { font-size: 32px; }
.hero.hero-qna .hero-hint { font-size: 13px; }

/* 空状态分区标签（GitHub 风格小标题） */
.sec-label { font-family: var(--font-mono); font-size: 11px; letter-spacing: .5px;
    text-transform: uppercase; color: var(--text-dim); text-align: left;
    margin: var(--sp-6) 0 var(--sp-3); }
/* 空状态命令提示行 */
.hint-line { font-size: 12px; color: var(--text-dim); margin: var(--sp-2) 0 var(--sp-3);
    line-height: 1.5; }
.hint-line code { font-family: var(--font-mono); background: var(--bg-surface);
    border: 1px solid var(--border); border-radius: var(--r-sm); padding: 1px 6px;
    color: var(--accent); }

/* 空状态「添加文件」拖拽区卡片 */
.st-key-upload_card { border: 1px dashed var(--border-strong) !important;
    border-radius: var(--r-lg) !important; padding: 16px 18px !important;
    background: color-mix(in srgb, var(--accent) 5%, var(--bg-surface)) !important;
    margin-bottom: var(--sp-4) !important; }
.st-key-upload_card .dropzone-head { display: flex; align-items: center; gap: 8px;
    font-family: var(--font-display); font-weight: 700; font-size: 15px; color: var(--text);
    margin-bottom: 2px; }
.st-key-upload_card .stFileUploader { border-color: var(--border) !important; }
.st-key-upload_card .stCaption { color: var(--text-dim) !important; }
/* 上传卡片内的「清空文档索引」按钮：小尺寸幽灵化，避免大横条 */
.st-key-upload_card .stButton > button {
    background: transparent !important; border: 1px solid var(--border) !important;
    color: var(--text-dim) !important; border-radius: var(--r-sm) !important;
    font-size: 12px !important; font-weight: 500 !important;
    padding: 5px 10px !important; width: auto !important; height: auto !important;
    line-height: 1 !important;
}
.st-key-upload_card .stButton > button::before { content: "" !important; display: none !important; }
.st-key-upload_card .stButton > button:hover {
    border-color: var(--radeon) !important; color: var(--radeon) !important;
    background: color-mix(in srgb, var(--radeon) 8%, transparent) !important; }

/* GitHub 风格技能卡片（空状态网格 + 侧栏窄栏共用） */
[class*="skills_grid_"] .stVerticalBlock {
    border: 1px solid var(--border); border-radius: var(--r-md);
    padding: 10px 12px; background: var(--bg-surface); width: 100% !important;
    transition: border-color .16s var(--ease), transform .16s var(--ease), box-shadow .16s var(--ease);
}
[class*="skills_grid_"] .stVerticalBlock:hover {
    border-color: var(--accent); transform: translateY(-2px);
    box-shadow: 0 6px 16px rgba(0,0,0,.18);
}
[class*="skills_grid_"] .stButton > button {
    background: transparent !important; border: none !important;
    text-align: left !important; font-weight: 600 !important; font-size: 13.5px !important;
    padding: 0 !important; color: var(--text) !important; width: 100% !important;
    font-family: var(--font-mono); word-break: break-word !important;
}
[class*="skills_grid_"] .stButton > button::before { content: "" !important; display: none !important; }
[class*="skills_grid_"] .stButton > button:hover {
    color: var(--accent) !important; background: transparent !important; }
[class*="skills_grid_"] .stCaption { color: var(--text-dim) !important;
    margin-top: 2px !important; line-height: 1.4 !important; }

/* 文档引用（Sources）显式展示 —— 文档解读是核心 */
.cite-head { font-family: var(--font-mono); font-size: 11px; font-weight: 600;
    color: var(--accent); letter-spacing: .3px; margin: 16px 0 8px; padding-left: 2px; }
.cite-item { border-left: 2px solid var(--cyan);
    background: color-mix(in srgb, var(--cyan) 7%, var(--bg-surface));
    border-radius: 0 8px 8px 0; padding: 6px 10px; margin-bottom: 8px;
    font-size: 12px; font-weight: 600; color: var(--text); }
.cite-idx { font-family: var(--font-mono); font-size: 10px; color: var(--cyan);
    border: 1px solid color-mix(in srgb, var(--cyan) 40%, transparent); border-radius: 5px;
    padding: 1px 6px; margin-right: 8px; }

/* ---------- 空状态：精选示例 chips（参考 Kimi / DeepSeek 的「建议」卡）---------- */
.st-key-st-key-eg_chips { max-width: 640px; margin: 0 auto; }
.st-key-st-key-eg_chips .stButton > button {
    background: var(--bg-surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r-md) !important;
    text-align: left !important; font-weight: 500 !important; font-size: 13.5px !important;
    padding: 12px 14px !important; line-height: 1.4 !important;
    color: var(--text) !important;
    box-shadow: 0 1px 2px rgba(0,0,0,.12);
    transition: all .16s var(--ease);
}
.st-key-st-key-eg_chips .stButton > button::before { content: "" !important; display: none !important; }
.st-key-st-key-eg_chips .stButton > button:hover {
    border-color: var(--accent) !important; color: var(--accent) !important;
    background: color-mix(in srgb, var(--accent) 8%, var(--bg-surface)) !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0,0,0,.18);
}

/* ---------- 悬浮控件：主题切换（右上） ---------- */
/* 注意：stylable_container 实际生成的 class 是 st-key-st-key-<key>（下划线） */
.st-key-st-key-ctl_theme { z-index: 100000 !important; }
.st-key-st-key-ctl_theme label, .st-key-st-key-ctl_theme [data-testid="stWidgetLabel"] {
  color: var(--text) !important; font-size: 12px !important; }

/* 侧栏开关「☰」：主区顶部常驻小按钮（不 fixed，避免与侧栏重叠/点不到） */
.st-key-st-key-ctl_sidebar { display: inline-block; margin: 0 0 6px; }
.st-key-st-key-ctl_sidebar button {
  background: var(--bg-surface) !important; border: 1px solid var(--border) !important;
  color: var(--text) !important; border-radius: 8px !important;
  padding: 4px 14px !important; width: auto !important; height: auto !important;
  line-height: 1 !important; font-size: 16px !important;
}
.st-key-st-key-ctl_sidebar button::before { content: "" !important; display: none !important; }
.st-key-st-key-ctl_sidebar button:hover { border-color: var(--accent) !important; color: var(--accent) !important; }

/* 顶栏「清空对话」：小尺寸幽灵按钮 */
.st-key-clear_top button {
  background: transparent !important; border: 1px solid var(--border) !important;
  color: var(--text-dim) !important; border-radius: var(--r-sm) !important;
  font-size: 13px !important; font-weight: 500 !important;
  padding: 7px 14px !important; width: auto !important; height: auto !important;
  line-height: 1 !important; transition: all .16s var(--ease);
}
.st-key-clear_top button::before { content: "" !important; display: none !important; }
.st-key-clear_top button:hover {
  border-color: var(--radeon) !important; color: var(--radeon) !important;
  background: color-mix(in srgb, var(--radeon) 8%, transparent) !important; }

/* 收起态的「展开」入口：醒目、居中、自动宽度 */
.st-key-st-key-expand_hint button {
  width: auto !important; background: var(--bg-surface) !important;
  border: 1px solid var(--accent) !important; color: var(--accent) !important;
  border-radius: 10px !important; padding: 6px 18px !important; font-weight: 600 !important;
}
.st-key-st-key-expand_hint button::before { content: "" !important; display: none !important; }
.st-key-st-key-expand_hint button:hover { background: color-mix(in srgb, var(--accent) 12%, var(--bg-surface)) !important; }

/* ---------- 底部输入条（仿 ChatGLM）：＋上传 / 深度思考 / RAG 检索 / 发送 ---------- */
/* 控制行：＋按钮 + 两个 toggle，左对齐成组，右侧信任提示 */
.st-key-st-key-ctl_row { display: flex !important; align-items: center; gap: var(--sp-2);
    margin-bottom: var(--sp-2); flex-wrap: wrap; }
.st-key-st-key-ctl_row .stButton > button {
    width: auto !important; min-width: 40px !important; height: 38px !important;
    border-radius: var(--r-sm) !important; font-size: 18px !important; padding: 0 12px !important;
    background: var(--bg-surface) !important; border: 1px solid var(--border) !important;
    color: var(--text) !important; transition: all .16s var(--ease);
}
.st-key-st-key-ctl_row .stButton > button::before { content: "" !important; display: none !important; }
.st-key-st-key-ctl_row .stButton > button:hover {
    border-color: var(--accent) !important; color: var(--accent) !important;
    background: color-mix(in srgb, var(--accent) 10%, var(--bg-surface)) !important; }
.st-key-st-key-ctl_row .stButton > button:active { transform: scale(.94); }
.st-key-st-key-ctl_row .stToggle { background: var(--bg-surface); border: 1px solid var(--border);
    border-radius: var(--r-sm); padding: 2px 10px !important; transition: all .16s var(--ease); }
.st-key-st-key-ctl_row .stToggle:hover { border-color: var(--border-strong); }
.st-key-st-key-ctl_row .stToggle[aria-checked="true"],
.st-key-st-key-ctl_row .stToggle[data-baseweb="checkbox"][aria-checked="true"] {
    border-color: var(--accent) !important;
    background: color-mix(in srgb, var(--accent) 12%, var(--bg-surface)) !important; }
.st-key-st-key-ctl_row .stToggle label { color: var(--text) !important; font-weight: 600; font-size: 13px; }
/* 控制行最右的信任提示：淡化、右对齐 */
.st-key-st-key-ctl_row > div:last-child { margin-left: auto !important; }
.st-key-st-key-ctl_row .stCaption { color: var(--text-dim) !important; font-size: 11px !important; }

/* 上传面板（点 ＋ 展开） */
.st-key-st-key-upload_panel { border: 1px dashed var(--border-strong) !important;
    border-radius: var(--r-md) !important; padding: 10px 14px !important; margin-bottom: var(--sp-2) !important;
    background: color-mix(in srgb, var(--accent) 5%, var(--bg-surface)); }
.st-key-st-key-upload_panel .stCaption { color: var(--text-dim) !important; }

/* 输入框 + 发送（圆角药丸，仿 ChatGLM 底部条） */
.st-key-st-key-input_bar .stForm { background: transparent !important; }
.st-key-st-key-input_bar [data-testid="stWidgetLabel"] { display: none !important; }
.st-key-st-key-input_bar input {
  font-size: 15px !important; height: 50px !important; border-radius: var(--r-pill) !important;
  background: var(--bg-surface) !important; color: var(--text) !important;
  border: 1px solid var(--border-strong) !important; padding: 0 18px !important;
  box-shadow: 0 4px 16px rgba(0,0,0,.14);
  transition: border-color .18s var(--ease), box-shadow .18s var(--ease);
}
.st-key-st-key-input_bar input:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 3px var(--ring), 0 4px 16px rgba(0,0,0,.14) !important;
}
.st-key-st-key-input_bar button {
  height: 50px !important; width: 50px !important; min-width: 50px !important;
  max-width: 60px !important;
  border-radius: var(--r-pill) !important; font-size: 19px !important; line-height: 1 !important;
  background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 70%, #000)) !important;
  color: #fff !important; border: none !important;
  padding: 0 !important; text-align: center !important;
  box-shadow: 0 4px 14px color-mix(in srgb, var(--accent) 40%, transparent);
  transition: transform .12s var(--ease), box-shadow .18s var(--ease), filter .18s var(--ease);
}
.st-key-st-key-input_bar button::before { content: "" !important; display: none !important; }
.st-key-st-key-input_bar button:hover { filter: brightness(1.08); box-shadow: 0 6px 18px color-mix(in srgb, var(--accent) 50%, transparent); }
.st-key-st-key-input_bar button:active { transform: scale(.92); }

/* 侧栏：拉开上下间距，首项避开原生「☰」 */
section[data-testid="stSidebar"] { padding-top: 8px !important; }
section[data-testid="stSidebar"] > div:first-child { padding-left: 44px !important; }
.sb-section { margin: 14px 0 6px !important; }
section[data-testid="stSidebar"] .stDivider { margin: 16px 0 !important; }
section[data-testid="stSidebar"] .stRadio { margin: 2px 0 10px !important; }

/* ---------- 响应式：窄屏收边、降噪 ---------- */
@media (max-width: 1100px) {
  section[data-testid="stSidebar"] { width: 220px !important; min-width: 220px !important; }
  section[data-testid="stSidebar"] > div:first-child { width: 220px !important; min-width: 220px !important; }
}
@media (max-width: 820px) {
  .block-container { padding-left: 16px !important; padding-right: 16px !important;
    border-left: none !important; border-right: none !important; }
  .hero.hero-qna { margin-top: 5vh; }
  .hero.hero-qna .hero-title { font-size: 26px; }
  .topbar-brand span { display: none; }
  .st-key-st-key-topbar_wrap { padding-right: 96px !important; }
}
@media (max-width: 560px) {
  .stChatMessage:has([data-testid="stChatMessageAvatarUser"]) { max-width: 100% !important; }
  .stChatMessage:has([data-testid="stChatMessageAvatarAssistant"]) { margin-right: 0 !important; max-width: 100% !important; }
  .st-key-st-key-ctl_row { gap: 6px; }
}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 签名元素：实时示波器轨迹（amber + cyan 双通道）
# 路径坐标宽 240、viewBox 宽 120，周期 40 整除 120 → 平移 -120 无缝循环。
# ---------------------------------------------------------------------------
import math


def _scope_points(amp, period, phase, base=16, w=240, n=240):
    pts = []
    for i in range(n + 1):
        x = w * i / n
        y = base - amp * math.sin(2 * math.pi * (x / period) + phase)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def scope_svg():
    amber_pts = _scope_points(amp=7, period=40, phase=0.0)
    cyan_pts = _scope_points(amp=5, period=40, phase=math.pi)
    return (
        '<svg class="scope" viewBox="0 0 120 32" width="120" height="32" '
        'preserveAspectRatio="none" aria-hidden="true">'
        '<g class="scope-trace">'
        f'<polyline class="tr-cyan" points="{cyan_pts}"/>'
        f'<polyline class="tr-amber" points="{amber_pts}"/>'
        "</g></svg>"
    )


# 顶栏：左为「☰」侧栏开关（常驻、不 fixed，避免与侧栏重叠/点不到），
# 右为 品牌 + 示波器 + 状态 pill。整行底部统一一条贯穿边框。
# 主题切换固定在右上角（见下方 ctl_theme）。
with stylable_container(
    key="topbar_wrap",
    css_styles="{border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 10px; padding-right: 130px;}",
):
    top_l, top_m, top_r = st.columns([0.12, 0.63, 0.25])
    with top_l:
        with stylable_container(key="ctl_sidebar", css_styles="{}"):
            is_open = st.session_state.get("sidebar_open", True)
            label = "☰ 收起侧栏" if is_open else "☰ 展开侧栏"
            if st.button(label, key="sidebar_toggle"):
                st.session_state.sidebar_open = not is_open
                st.rerun()

        # 收起时，主区顶部额外放一个醒目的「展开」入口，保证一定点得到
        if not st.session_state.get("sidebar_open", True):
            with stylable_container(
                key="expand_hint",
                css_styles="{text-align:center; margin:2px 0 10px;}",
            ):
                if st.button(
                    "☰ 展开左侧调试面板", key="expand_sidebar", use_container_width=False
                ):
                    st.session_state.sidebar_open = True
                    st.rerun()
    with top_m:
        st.markdown(
            f'<div class="topbar-brand">{scope_svg()}'
            f'<div>Bedrock <span>· HW-R&D Scope Workbench</span></div>'
            f'<div class="topbar-pill">本地 · ROCm · gfx1100</div></div>',
            unsafe_allow_html=True,
        )
        # 顶栏「模型选择」：仿 ChatGLM 顶栏的下拉（Assistant mode）
        mk = list(MODE_MAP.keys())
        sel = st.selectbox(
            "Assistant mode",
            mk,
            index=mk.index(st.session_state.get("mode", "Hardware R&D")),
            label_visibility="collapsed",
            key="mode_select_top",
        )
        if sel != st.session_state.get("mode"):
            st.session_state.mode = sel
            st.cache_resource.clear()
            st.rerun()
        st.caption("模型 / Mode：Hardware R&D（磐石·硬件研发）· Generic（通用）")
    with top_r:
        if st.button(
            "🗑 清空对话", use_container_width=True, key="clear_top"
        ):
            archive_current_chat()
            if runtime_state().get("model_loaded"):
                init_agent().clear_memory()
            st.session_state.messages = []
            st.rerun()

# 右上角固定悬浮主题切换（黑白切换）
# 注意：stylable_container 的格式是 `.st-key-X {style}`，style 必须自带花括号。
# 必须显式 width: max-content，否则容器被撑成整宽、内容落到左上角。
with stylable_container(
    key="ctl_theme",
    css_styles="{position: fixed !important; top: 6px !important; right: 14px !important; "
    "width: max-content !important; z-index: 999 !important;}",
):
    dark_on = st.session_state.theme == "dark"
    new_dark = st.toggle("Dark mode", value=dark_on, key="theme_toggle")
    if new_dark != dark_on:
        st.session_state.theme = "dark" if new_dark else "light"
        st.rerun()


# ---------------------------------------------------------------------------
# 资源初始化
# ---------------------------------------------------------------------------
@st.cache_resource
def runtime_state():
    """跨 rerun 存活的运行时状态（模型是否已加载、加载耗时、模型名）。"""
    return {"model_loaded": False, "load_seconds": None, "model_name": None}


@st.cache_resource
def init_engine():
    import time as _time

    with open(os.path.join(REPO_ROOT, "config.yaml"), "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    model_config = config.get("model", {})
    inference_config = InferenceConfig(
        model_path=model_config.get("path", "./models/Qwen2.5-14B-Instruct"),
        n_ctx=model_config.get("n_ctx", 8192),
        temperature=model_config.get("temperature", 0.7),
        max_tokens=model_config.get("max_tokens", 4096),
        dtype=model_config.get("dtype", "float16"),
        gpu_memory_utilization=model_config.get("gpu_memory_utilization", 0.90),
        tensor_parallel_size=model_config.get("tensor_parallel_size", 1),
        pipeline_parallel_size=model_config.get("pipeline_parallel_size", 1),
    )

    if not os.path.exists(inference_config.model_path):
        raise RuntimeError(
            f"Model not found: {inference_config.model_path}\n"
            f"Run first: python scripts/download_model.py --model qwen2.5-14b"
        )

    t0 = _time.time()
    engine = InferenceEngine(inference_config)
    state = runtime_state()
    state["model_loaded"] = True
    state["load_seconds"] = round(_time.time() - t0, 1)
    state["model_name"] = os.path.basename(
        os.path.normpath(inference_config.model_path)
    )
    state["dtype"] = inference_config.dtype
    state["n_ctx"] = inference_config.n_ctx
    return engine


@st.cache_resource
def init_memory():
    # RAG 参数以 config.yaml 为准，避免 UI 与 CLI / 建库脚本用不同的切块与 top_k
    with open(os.path.join(REPO_ROOT, "config.yaml"), "r", encoding="utf-8") as f:
        rag_config = (yaml.safe_load(f) or {}).get("rag", {})
    memory_manager = MemoryManager(
        index_path=os.path.join(REPO_ROOT, "data", "faiss_index"),
        embedding_model=rag_config.get("embedding_model", "all-MiniLM-L6-v2"),
        chunk_size=rag_config.get("chunk_size", 512),
        chunk_overlap=rag_config.get("chunk_overlap", 50),
        top_k=rag_config.get("top_k", 5),
    )
    return memory_manager


@st.cache_resource
def init_agent():
    engine = init_engine()
    memory_manager = init_memory()

    prompt_mode = "hardware"
    try:
        mode = st.session_state.get("mode", "Hardware R&D")
        prompt_mode = MODE_MAP.get(mode, "hardware")
    except Exception:
        pass

    agent = RadeonAgent(
        engine, memory_manager, prompt_mode=prompt_mode,
        approval_callback=web_approval_callback,
    )
    return agent


def read_gpu_status() -> dict:
    """读取 GPU 名称与显存占用（rocm-smi），失败则返回空字典。"""
    import subprocess

    info = {}
    try:
        out = subprocess.run(
            ["rocm-smi", "--showproductname", "--showmemuse", "--csv"],
            capture_output=True, text=True, timeout=8,
        ).stdout
        for line in out.splitlines():
            if "," not in line:
                continue
            if "Card Series" in line or "Device Name" in line:
                info["name"] = line.split(",")[-1].strip()
            if "VRAM%" in line or "Memory Allocated" in line:
                info["vram"] = line.split(",")[-1].strip()
    except Exception:
        pass
    if not info:
        try:
            out = subprocess.run(
                ["rocm-smi", "--showmemuse"], capture_output=True, text=True, timeout=8
            ).stdout
            for line in out.splitlines():
                if "VRAM%" in line:
                    info["vram"] = line.split(":")[-1].strip()
        except Exception:
            pass
    return info


def read_audit_tail(n: int = 15) -> list:
    """读取审计日志尾部若干条记录。"""
    import json as _json

    path = os.path.join(REPO_ROOT, "logs", "audit.log")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-n:]
    except Exception:
        return []
    records = []
    for line in lines:
        try:
            records.append(_json.loads(line))
        except Exception:
            continue
    return records


def archive_current_chat():
    """把当前对话存入侧栏历史列表（标题取首条用户消息）。"""
    msgs = st.session_state.get("messages", [])
    if not msgs:
        return
    title = next(
        (m["content"] for m in msgs if m.get("role") == "user"), "Untitled"
    )
    title = (title[:38] + "…") if len(title) > 38 else title
    st.session_state.setdefault("chat_history", []).append(
        {"title": title, "messages": list(msgs)}
    )


# (侧栏内容已下移：在渲染函数定义之后、对话区之前重新挂载，见下方 `with st.sidebar`)



# ---------------------------------------------------------------------------
# 页面内的「技能 + 系统」面板（从侧栏搬上页面）
# ---------------------------------------------------------------------------
def render_skills_browser(compact=False, prefix="main"):
    """GitHub 风格技能浏览：搜索 + 分类筛选 + 带说明的卡片网格。
    点一下即以 Agent Task 模式执行对应示例。compact 用于侧栏窄栏。"""
    fk = f"skill_filter_{prefix}"
    ck = f"skill_cat_{prefix}"
    q = st.session_state.get(fk, "")
    q = st.text_input(
        "Filter skills", value=q, placeholder="搜索技能…",
        label_visibility="collapsed", key=fk,
    )
    if q != st.session_state.get(fk, ""):
        st.session_state[fk] = q
        st.rerun()
    cur = st.session_state.get(ck, "全部")
    cat = st.selectbox(
        "Category", SKILL_CATS, index=SKILL_CATS.index(cur),
        label_visibility="collapsed", key=ck,
    )
    if cat != cur:
        st.session_state[ck] = cat
        st.rerun()

    fq = q.strip().lower()
    items = [
        s for s in SKILLS
        if (cat == "全部" or s["cat"] == cat)
        and (not fq or fq in s["name"].lower() or fq in s["desc"].lower())
    ]
    if not items:
        st.caption("无匹配的技能")
        return

    ncol = 1 if compact else 3
    with stylable_container(
        key=f"skills_grid_{prefix}",
        css_styles="{display: grid; grid-template-columns: repeat(%d, 1fr); gap: 10px;}" % ncol,
    ):
        cols = st.columns(ncol)
        for i, s in enumerate(items):
            with cols[i % ncol]:
                if st.button(
                    f'{s["icon"]}  {s["name"]}',
                    key=f'sk_{prefix}_{s["name"]}',
                    use_container_width=True,
                ):
                    st.session_state.show_skills = False
                    st.session_state.interaction = "Agent Task (tools)"
                    st.session_state.pending_prompt = dict(SKILL_EXAMPLES).get(
                        s["name"], s["name"]
                    )
                    st.rerun()
                st.caption(s["desc"])


def render_upload_card():
    """空状态「添加文件」独立卡片（拖拽区风格），放在搜索栏下方。"""
    with stylable_container(key="upload_card", css_styles="{}"):
        st.markdown(
            '<div class="dropzone-head">📎 添加硬件手册 / 文档</div>',
            unsafe_allow_html=True,
        )
        st.caption("支持 PDF / DOCX / MD / TXT，自动索引到本地知识库")
        handle_doc_upload()



def render_runtime():
    rs = runtime_state()
    loaded = rs.get("model_loaded")
    with stylable_container(
        key="rt_stat",
        css_styles="""
        { border-left: 3px solid var(--accent); border-radius: 8px;
          background: color-mix(in srgb, var(--accent) 8%, var(--bg-surface));
          padding: 8px 12px; margin-bottom: 8px; }
        """,
    ):
        st.markdown(
            f"**{'🟢 Loaded' if loaded else '⚪ Lazy (loads on first message)'}**  \n"
            f"{rs.get('model_name') or 'Qwen2.5-14B-Instruct'} · "
            f"{rs.get('dtype', 'float16')} · {rs.get('n_ctx', 8192)} tok  \n"
            f"Engine: vLLM + ROCm (gfx1100)"
        )
    if rs.get("load_seconds"):
        st.caption(f"Weight load took {rs['load_seconds']} s")
    if st.button("Refresh GPU status", use_container_width=True):
        st.session_state.gpu_status = read_gpu_status()
    gpu = st.session_state.get("gpu_status")
    if gpu:
        st.markdown(
            f"**GPU:** {gpu.get('name', 'AMD Radeon')}  \n"
            f"**VRAM allocated:** {gpu.get('vram', 'n/a')}"
        )


def render_tool_safety():
    policy = st.session_state.get("tool_safety", SAFETY_AUTO)
    opts = [SAFETY_AUTO, SAFETY_BLOCK]
    new_safety = st.radio(
        "Tool safety", opts, index=opts.index(policy),
        horizontal=True, label_visibility="collapsed",
    )
    if new_safety != policy:
        st.session_state.tool_safety = new_safety
        st.rerun()
    st.caption(
        "High-risk tools: delete_file · write_file · execute_command · "
        "execute_python · code_interpreter. "
        "`Block high-risk` refuses them and records the refusal in the audit log."
    )


def render_audit():
    records = read_audit_tail(15)
    if not records:
        st.caption("No audit records yet.")
        return
    for r in reversed(records):
        ts = (r.get("timestamp") or "")[11:19]
        event = r.get("event", "?")
        detail = r.get("tool") or (
            f"{r.get('message_length', '?')}→{r.get('response_length', '?')} chars"
            if event == "chat" else r.get("task", "")
        )
        flag = ""
        if "approved" in r:
            flag = " ✅" if r["approved"] else " ⛔"
        elif "success" in r:
            flag = " ✅" if r["success"] else " ⚠️"
        st.caption(f"`{ts}` **{event}** {detail}{flag}")
    st.caption("logs/audit.log — chat bodies are stored as lengths only.")


# ---------------------------------------------------------------------------
# 侧栏：精简控制面板（Skills / 系统面板收进折叠区，主页面只留对话）
# 侧栏【始终渲染】；收起仅用 CSS 隐藏 section[data-testid="stSidebar"]，
# 由顶部「☰」按钮控制 st.session_state.sidebar_open。这样 Streamlit 的侧栏
# 机制不会因条件渲染而“丢失”，重开只需去掉隐藏 CSS，绝对可靠。
# ---------------------------------------------------------------------------
def render_sidebar():
    with st.sidebar:
        st.markdown(
            '<div class="sb-brand">🤖 Bedrock'
            '<div class="sub">Hardware R&D Assistant</div></div>',
            unsafe_allow_html=True,
        )
        st.divider()

        # ---- New chat ----
        if st.button("+ New chat", type="primary", use_container_width=True):
            archive_current_chat()
            # 模型未加载时不要调用 init_agent()，否则一点「New chat」就会触发 28GB 权重加载
            if runtime_state().get("model_loaded"):
                init_agent().clear_memory()
            st.session_state.messages = []
            st.rerun()

        # ---- 历史会话 ----
        history = st.session_state.get("chat_history", [])
        if history:
            with st.expander(f"History ({len(history)})", expanded=False):
                for i, item in enumerate(reversed(history)):
                    idx = len(history) - 1 - i
                    if st.button(item["title"], key=f"hist_{idx}", use_container_width=True):
                        archive_current_chat()
                        st.session_state.messages = list(item["messages"])
                        st.rerun()
                if st.button("Clear history", use_container_width=True):
                    st.session_state.chat_history = []
                    st.rerun()

        st.divider()

        # ---- Knowledge base（只读信息；上传入口已移到底部输入条「＋」）----
        with st.expander("Knowledge base", expanded=False):
            try:
                doc_count = init_memory().get_document_count()
            except Exception:
                doc_count = 0
            st.markdown(
                f'Indexed chunks: <span class="kb-badge">{doc_count}</span>',
                unsafe_allow_html=True,
            )
            st.caption(
                "上传文档请点底部输入条的「＋」。RAG 检索开关也在底部输入条。"
            )
            if st.button("Clear document index", use_container_width=True):
                init_memory().clear_long_term_memory()
                st.session_state.processed_docs = set()
                st.success("Document index cleared.")
                st.rerun()

        # ---- Functions (14) · 调试：列出本地工具与说明，方便调试 ----
        with st.expander("Functions (14) · 调试", expanded=False):
            st.caption("本地 14 个硬件工具；在 Skills 面板点名字即可直接执行。")
            for t in registry.list_tools():
                badge = " ⚠️需审批" if t.get("requires_approval") else ""
                st.markdown(f"**`{t['name']}`**{badge}")
                st.caption(t["description"])

        # ---- Hardware skills：不再以折叠墙展示，改由 / 命令 + 🧰 弹窗唤起 ----
        st.caption("技能：输入 / 或点 🧰 打开选择页")


        # ---- System · Runtime · Audit（默认折叠）----
        with st.expander("System · Runtime · Audit", expanded=False):
            render_runtime()
            st.divider()
            render_tool_safety()
            st.divider()
            render_audit()

        # ---- Actions ----
        with st.expander("Actions", expanded=False):
            if st.button("Reload model", use_container_width=True):
                st.cache_resource.clear()
                st.rerun()
            transcript = "\n\n".join(
                f"### {m['role']}\n\n{m['content']}"
                for m in st.session_state.get("messages", [])
            )
            st.download_button(
                "Export conversation (.md)",
                data=transcript or "(empty conversation)",
                file_name="bedrock_conversation.md",
                mime="text/markdown",
                disabled=not transcript,
                use_container_width=True,
            )

        st.divider()
        st.caption("100% local · AMD Radeon · vLLM + ROCm · 14 skills")


# 侧栏始终渲染（DOM 永远存在），收起仅用 CSS 隐藏，避免 Streamlit 条件渲染导致
# 侧栏「丢失 / 重开不了」的问题。重开即不再注入这段 CSS。
render_sidebar()
if not st.session_state.get("sidebar_open", True):
    st.markdown(
        '<style>section[data-testid="stSidebar"]{display:none !important;}</style>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# 对话区
# ---------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []


def render_sources(sources):
    if not sources:
        return
    st.markdown(
        f'<div class="cite-head">📄 引用自本地文档 · {len(sources)} 处</div>',
        unsafe_allow_html=True,
    )
    for s in sources:
        st.markdown(
            f'<div class="cite-item">'
            f'<span class="cite-idx">DOC {s["index"]}</span> {s["source"]}'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.caption(s["content"][:500])


def _step_output(res: dict) -> tuple:
    """把 executor 的一步结果转成 (代码块语言, 文本)。"""
    import json as _json

    if res.get("skipped"):
        return "", f"⛔ Blocked by the Tool safety policy: {res.get('output')}"
    if res.get("error"):
        return "", f"⚠️ {res['error']}"
    out = res.get("output")
    if isinstance(out, dict):
        if out.get("code"):
            return out.get("language", "verilog"), out["code"]
        for key in ("content", "message", "stdout", "output"):
            value = out.get(key)
            if isinstance(value, str) and value.strip():
                return "", value
        payload = {k: v for k, v in out.items() if k != "success"}
        return "json", _json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if isinstance(out, list):
        return "json", _json.dumps(out, ensure_ascii=False, indent=2, default=str)
    return "", str(out) if out else "(no output)"


def render_task(result: dict) -> str:
    """Render an Agent Task (Planner->Executor->Reflector) result as markdown."""
    md = []
    ok = result.get("success", False)
    md.append(f"**Task status:** {'✅ completed' if ok else '⚠️ not completed'}")
    if result.get("error"):
        md.append(f"\n⚠️ {result['error']}")
    steps = result.get("steps", []) or []
    results = result.get("results", []) or []
    for i, step in enumerate(steps):
        res = results[i] if i < len(results) else {}
        tool = step.get("tool") or "—"
        lang, out = _step_output(res)
        mark = "✅" if res.get("success") else ("⛔" if res.get("skipped") else "⚠️")
        if len(out) > 6000:
            out = out[:6000] + "\n… (truncated)"
        md.append(
            f"\n**Step {step.get('step')}: {step.get('description')}** "
            f"`{tool}` {mark}\n```{lang}\n{out}\n```"
        )
    refl = result.get("reflection") or {}
    if refl.get("reason"):
        md.append(f"\n_{refl.get('reason')}_")
    text = "\n".join(md)
    st.markdown(text)
    return text


def respond(query: str):
    """Append user message, render response (Chat RAG or Agent Task)."""
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    mode = st.session_state.get("interaction", "Chat (RAG)")
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                agent = init_agent()
                if mode == "Agent Task (tools)":
                    text = render_task(agent.run_task(query))
                    st.session_state.messages.append(
                        {"role": "assistant", "content": text}
                    )
                else:
                    response, sources = agent.chat(
                        query,
                        use_rag=st.session_state.get("rag_search", True),
                        return_sources=True,
                    )
                    st.markdown(response)
                    render_sources(sources)
                    st.session_state.messages.append(
                        {"role": "assistant", "content": response, "sources": sources}
                    )
            except Exception as e:
                st.error(f"Error: {str(e)}")


# ---------------------------------------------------------------------------
# Codex 风格「/」命令 + WorkBuddy 风格技能选择弹窗
# ---------------------------------------------------------------------------
def _help_markdown():
    """/help 的助手消息：命令清单 + 按分类组织的技能，避免把技能“硬塞”到页面。"""
    lines = [
        "## 命令",
        "- `/help` — 显示本帮助",
        "- `/skills` — 打开技能选择页（弹窗）",
        "- `/upload` — 打开文档上传面板",
        "- `/clear` — 清空当前对话",
        "- `/<技能名>` — 直接运行某技能，如 `/generate_verilog`",
        "",
        "## 硬件技能 · 14 项（点 🧰 或直接 `/<技能名>`）",
    ]
    for cat in SKILL_CATS[1:]:
        lines.append(f"**{cat}**")
        for s in SKILLS:
            if s["cat"] == cat:
                lines.append(f"- {s['icon']} `{s['name']}` — {s['desc']}")
        lines.append("")
    return "\n".join(lines)


def handle_command(q: str):
    """处理以 / 开头的命令。返回要追加的助手消息 dict，或 None 表示已处理（弹窗/跳转）。"""
    parts = q.strip().lstrip("/").split()
    if not parts:
        return {"role": "assistant", "content": _help_markdown()}
    cmd = parts[0].lower()
    if cmd in ("help", "?", "h"):
        return {"role": "assistant", "content": _help_markdown()}
    if cmd == "skills":
        st.session_state.show_skills = True
        st.rerun()
    if cmd == "upload":
        st.session_state.show_upload = True
        st.rerun()
    if cmd in ("clear", "new"):
        st.session_state.messages = []
        st.rerun()
    skill = next((s for s in SKILLS if s["name"].lower() == cmd), None)
    if skill:
        st.session_state.show_skills = False
        st.session_state.interaction = "Agent Task (tools)"
        st.session_state.pending_prompt = dict(SKILL_EXAMPLES).get(skill["name"], skill["name"])
        st.rerun()
    return {"role": "assistant", "content": f"未知命令 `/{cmd}`。\n\n" + _help_markdown()}


def render_skills_dialog():
    """WorkBuddy 风格：技能选择弹窗（modal）。点技能即以 Agent Task 运行。"""
    if not st.session_state.get("show_skills"):
        return

    @st.dialog("🧰 选择硬件技能", width="large")
    def _dlg():
        st.caption("点一下技能即以 Agent Task 模式运行；也可输入 `/<技能名>`")
        render_skills_browser(compact=False, prefix="dlg")
        if st.button("关闭", use_container_width=True, key="dlg_close"):
            st.session_state.show_skills = False
            st.rerun()

    _dlg()


def handle_doc_upload():
    """把上传的文档写入 data/documents/ 并增量索引到本地知识库（文档解读核心入口）。"""
    try:
        doc_count = init_memory().get_document_count()
    except Exception:
        doc_count = 0
    st.markdown(
        f'已索引 chunks: <span class="kb-badge">{doc_count}</span>',
        unsafe_allow_html=True,
    )
    st.markdown("上传 PDF / DOCX / MD / TXT — 自动索引到本地知识库。")
    uploaded_files = st.file_uploader(
        "Upload documents",
        type=["pdf", "docx", "md", "txt"],
        accept_multiple_files=True,
        key="bottom_uploader",
    )
    if "processed_docs" not in st.session_state:
        st.session_state.processed_docs = set()
    if uploaded_files:
        new_files = [
            f for f in uploaded_files
            if os.path.basename(f.name) not in st.session_state.processed_docs
        ]
        if new_files:
            memory_manager = init_memory()
            save_dir = os.path.join(REPO_ROOT, "data", "documents")
            os.makedirs(save_dir, exist_ok=True)
            for uploaded_file in new_files:
                safe_name = os.path.basename(uploaded_file.name)
                file_path = os.path.join(save_dir, safe_name)
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                added = memory_manager.add_document(file_path)
                if added > 0:
                    st.success(f"Indexed {uploaded_file.name}: {added} chunks")
                    st.session_state.processed_docs.add(safe_name)
                else:
                    st.warning(
                        f"Could not extract text from {uploaded_file.name} "
                        "(likely a scanned / image-only PDF)."
                    )
            st.rerun()
    if st.button("清空文档索引", use_container_width=True, key="clear_kb_bottom"):
        init_memory().clear_long_term_memory()
        st.session_state.processed_docs = set()
        st.success("Document index cleared.")
        st.rerun()


def render_input_bar():
    """对话视图底部输入条（仿 ChatGLM）：＋上传 / 深度思考 / RAG 检索 / 发送。"""
    # 控制行：＋上传 / 🧰技能 / 两个 toggle（左对齐成组），最右为信任提示
    with stylable_container(key="ctl_row", css_styles="{}"):
        cr = st.columns([0.07, 0.07, 0.25, 0.23, 0.30])
        with cr[0]:
            if st.button(
                "＋", key="attach_btn", use_container_width=True,
                help="上传硬件手册 / 文档到本地知识库",
            ):
                st.session_state.show_upload = not st.session_state.get(
                    "show_upload", False
                )
                st.rerun()
        with cr[1]:
            if st.button(
                "🧰", key="skills_btn", use_container_width=True,
                help="选择硬件技能（弹窗）",
            ):
                st.session_state.show_skills = True
                st.rerun()
        with cr[2]:
            deep = st.toggle(
                "深度思考",
                value=st.session_state.get("deep_think", False),
                key="deep_toggle",
            )
            if deep != st.session_state.get("deep_think", False):
                st.session_state.deep_think = deep
                st.session_state.interaction = (
                    "Agent Task (tools)" if deep else "Chat (RAG)"
                )
                st.rerun()
        with cr[3]:
            rag = st.toggle(
                "RAG 检索",
                value=st.session_state.get("rag_search", True),
                key="rag_toggle",
            )
            if rag != st.session_state.get("rag_search", True):
                st.session_state.rag_search = rag
                st.rerun()
        with cr[4]:
            st.caption("🔒 本地推理 · 数据不上传")

    if st.session_state.get("show_upload", False):
        with stylable_container(
            key="upload_panel",
            css_styles="{border: 1px dashed var(--border-strong); border-radius: 12px; "
            "padding: 10px 14px; margin-bottom: 10px; "
            "background: color-mix(in srgb, var(--accent) 5%, var(--bg-surface));}",
        ):
            handle_doc_upload()

    with stylable_container(
        key="input_bar",
        css_styles="{max-width: 920px; margin: 0 auto;}",
    ):
        with st.form(key="bottom_form", clear_on_submit=True):
            ic = st.columns([0.92, 0.08])
            with ic[0]:
                q = st.text_input(
                    "q",
                    placeholder="问你的硬件手册，或描述一个设计任务…",
                    label_visibility="collapsed",
                    key="bottom_q",
                )
            with ic[1]:
                sent = st.form_submit_button("➤", use_container_width=True)
    if sent and q and q.strip():
        q = q.strip()
        if q.startswith("/"):
            msg = handle_command(q)
            if msg is not None:
                st.session_state.messages.append(msg)
            st.rerun()
        else:
            respond(q)
            st.rerun()


# 渲染历史消息
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("sources"):
            render_sources(message["sources"])

# 空对话：欢迎页（克制版 —— 以问答为核心，大量留白；提问框居中，参考 Kimi/DeepSeek）
if len(st.session_state.messages) == 0:
    st.markdown(
        f"""
        <div class="hero hero-qna">
          <div class="hero-scope">{scope_svg()}</div>
          <div class="hero-title">问你的硬件手册</div>
          <div class="hero-sub">Local Hardware R&D Assistant · 基于你的 datasheet / 手册作答</div>
          <div class="hero-hint">全部在本地 AMD Radeon 上推理 · 不上传任何数据</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# 输入条【始终】在底部（仿 ChatGLM：空状态也有 ＋上传 / 深度思考 / RAG 检索 / 发送）
render_input_bar()

# 空状态：搜索栏下方保留「添加文件」卡片；技能改为 / 命令 + 🧰 弹窗唤起
if len(st.session_state.messages) == 0:
    st.markdown(
        '<div class="sec-label">📎 添加文件 · 拖入硬件手册即自动入库</div>',
        unsafe_allow_html=True,
    )
    render_upload_card()
    st.markdown(
        '<div class="hint-line">输入 <code>/</code> 唤起命令与技能 · 点 🧰 打开技能选择页 · '
        '<code>/help</code> 查看全部</div>',
        unsafe_allow_html=True,
    )

# 技能选择弹窗（WorkBuddy 风格）
render_skills_dialog()

# 侧栏 Skills 目录点击的示例：切换模式后由这里执行
pending = st.session_state.pop("pending_prompt", None)
if pending:
    respond(pending)
    st.rerun()
