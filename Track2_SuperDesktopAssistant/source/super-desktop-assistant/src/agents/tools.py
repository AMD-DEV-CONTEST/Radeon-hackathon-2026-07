"""
Agent 工具集 —— 每个执行 Agent 都可以平等调用这些工具。

v3: 对接 SharedMemory（公共记忆）架构。
- Allocator 管理公共记忆（创建/分配/清空）
- Agent 通过 get_shared_memory 读取任务上下文
- Agent 通过 add_note / add_discovery 向公共记忆追加发现
"""
import os
import re
import sys
from pathlib import Path
from loguru import logger

# ─── 安全沙箱配置 ───
# Agent 工具只能在白名单目录内读写文件。路径会在运行时动态更新。
#
# v3 P0：区分读写白名单与只读白名单
#   _ALLOWED_PATHS   = 可读可写（settings.workspace_dir，默认 outputs）
#   _READONLY_PATHS  = 只读追加（项目根目录，Agent 不得修改）
# read_file/search_code/list_files 允许两者；write_file 仅允许 _ALLOWED_PATHS。
_ALLOWED_PATHS: list[str] = []
_READONLY_PATHS: list[str] = []
_SANDBOX_READY = False             # H3 修复：沙箱初始化标志（不再用"两个列表都空"推断）
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB 读取上限
_MAX_WRITE_SIZE = 5 * 1024 * 1024  # 5 MB 写入上限
_MAX_NOTE_SIZE = 32 * 1024         # 32 KB 笔记/发现上限，防止共享记忆膨胀


def _to_int(value, default: int = 0) -> int:
    """安全转 int（mimo 文本式工具调用的参数可能是字符串）。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float = 0.0) -> float:
    """安全转 float。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

# ─── 工具定义（OpenAI Function Calling 格式） ───

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_shared_memory",
            "description": (
                "获取公共记忆中的任务上下文。包含：任务描述、用户原始输入、"
                "文件路径列表、Allocator 分配给你的定制 prompt、其他 Agent 的状态和发现。"
                "这是获取全局上下文的主要入口。每次执行任务时先调用此工具了解全局情况。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "你的 Agent ID（节点 ID），可省略——框架会自动绑定当前节点"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取指定文件的内容。支持 PDF（自动提取文本）、文本文件、代码等。可以指定起始行/页和行数/页数来分段读取大文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件的绝对路径（支持 .pdf .txt .json .py 等）"},
                    "start_line": {"type": "integer", "description": "从第几行/页开始读取（1-based），PDF 文件表示页码，默认 1"},
                    "line_count": {"type": "integer", "description": "读取多少行/页，PDF 文件表示页数，默认 200 行/20 页"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "在文件中搜索匹配正则表达式的内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要搜索的文件或目录的绝对路径"},
                    "pattern": {"type": "string", "description": "正则表达式搜索模式"},
                    "file_pattern": {"type": "string", "description": "文件名过滤 glob 模式，如 *.py"},
                    "max_results": {"type": "integer", "description": "最大返回结果数，默认 20"},
                },
                "required": ["path", "pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出目录中的文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录的绝对路径"},
                    "pattern": {"type": "string", "description": "文件过滤 glob 模式，默认 *"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_note",
            "description": "向公共记忆追加一条全局笔记。其他 Agent 可以看到。只能追加不能修改。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "笔记内容"},
                    "prefix": {"type": "string", "description": "标记前缀，如 发现/警告/建议"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "调用 ComfyUI + NoobAI 生成一张图片。需要提供英文提示词。"
                "生成后返回图片路径。支持参数：prompt（提示词）、size（分辨率如 832x1216）、"
                "cfg（默认4.5）、steps（默认30）、prefix（文件名前缀）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "英文提示词，NoobAI 格式"},
                    "size": {"type": "string", "description": "分辨率 WxH，默认 832x1216"},
                    "cfg": {"type": "number", "description": "CFG scale，默认 4.5"},
                    "steps": {"type": "integer", "description": "采样步数，默认 30"},
                    "prefix": {"type": "string", "description": "文件名前缀，如 scene1"},
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入文件。用于创建 HTML 页面、保存结果等。只能在允许的目录内操作。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "输出文件的绝对路径"},
                    "content": {"type": "string", "description": "文件内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_discovery",
            "description": "向公共记忆追加一个发现/洞察。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "发现的内容"},
                },
                "required": ["content"],
            },
        },
    },
]

# ─── 安全沙箱 ───

def _get_allowed_paths() -> list[str]:
    """返回 Agent 工具可读写的白名单目录（缓存计算结果）。"""
    if not _SANDBOX_READY or not _ALLOWED_PATHS:
        _refresh_allowed_paths()
    return _ALLOWED_PATHS


def _get_readonly_paths() -> list[str]:
    """返回 Agent 工具只读的白名单目录（项目根，不可写入）。"""
    if not _SANDBOX_READY or not _READONLY_PATHS:
        _refresh_allowed_paths()
    return _READONLY_PATHS


def _refresh_allowed_paths():
    """刷新白名单目录（配置重载后调用）。

    v3 P0：工作目录可读可写（settings.workspace_dir），项目根目录只读。

    H3 修复：原实现用 `not _ALLOWED_PATHS and not _READONLY_PATHS` 判断懒初始化，
    若首次刷新进了 except 分支（配置解析错误），只有 _READONLY_PATHS 被设置，
    而 _ALLOWED_PATHS 永远空且不再重刷 → write_file 永久禁用。
    现改用 _SANDBOX_READY 标志 + except 分支补可写目录。
    """
    global _SANDBOX_READY
    _ALLOWED_PATHS.clear()
    _READONLY_PATHS.clear()
    _SANDBOX_READY = False
    try:
        from ..config import get_config
        cfg = get_config()

        # 工作目录：可读可写（默认 outputs，可用 settings.workspace_dir 配置）
        workspace_dir = os.path.abspath(cfg.settings.workspace_dir)
        if workspace_dir not in _ALLOWED_PATHS:
            _ALLOWED_PATHS.append(workspace_dir)

        # 兼容旧配置：output_dir 与 workspace_dir 不同时，也纳入可读写
        output_dir = os.path.abspath(cfg.settings.output_dir)
        if output_dir not in _ALLOWED_PATHS:
            _ALLOWED_PATHS.append(output_dir)

        # 项目根目录：只读（Agent 可读项目代码，但不能修改）
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        if project_root not in _READONLY_PATHS:
            _READONLY_PATHS.append(project_root)

        logger.info(
            f"[SANDBOX] 可读写: {_ALLOWED_PATHS} | 只读: {_READONLY_PATHS}"
        )
    except Exception:
        # 安全回退：项目根只读 + 默认 outputs 可写（保证 write_file 仍可用）
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        _READONLY_PATHS.append(root)
        _ALLOWED_PATHS.append(os.path.abspath("outputs"))
    finally:
        # 无论成败都置位，避免"永远重刷/永不重刷"两个极端
        _SANDBOX_READY = True


def _validate_path(target_path: str, must_exist: bool = False, write: bool = False) -> str:
    """验证路径是否在允许的目录内。返回规范化的绝对路径，或抛出 ValueError。

    write=True   → 仅允许可读写白名单（workspace_dir / output_dir），用于 write_file。
    write=False  → 允许可读写白名单 + 只读白名单（项目根），用于 read/search/list。

    安全：
    - realpath 解析 symlink/junction，防止目录内 junction 指向沙箱外被穿越
    - normcase 统一大小写（Windows 路径不区分大小写）
    """
    if not target_path:
        raise ValueError("路径不能为空")
    normalized = os.path.normpath(os.path.realpath(os.path.abspath(target_path)))
    if must_exist and not os.path.exists(normalized):
        raise ValueError(f"路径不存在: {target_path}")
    if write:
        allowed = _get_allowed_paths()
    else:
        allowed = _get_allowed_paths() + _get_readonly_paths()
    norm_normalized = os.path.normcase(normalized)
    for allowed_dir in allowed:
        norm_dir = os.path.normcase(os.path.realpath(os.path.abspath(allowed_dir)))
        if norm_normalized.startswith(norm_dir + os.sep) or norm_normalized == norm_dir:
            return normalized
    raise ValueError(f"拒绝访问: 路径 {target_path} 不在允许的目录范围内")


def _path_in_allowed(target: str) -> bool:
    """判断路径是否在可读白名单内（读写 + 只读）。

    用于过滤 glob/rglob 结果，防止 `..` 或 symlink 逃出沙箱。
    """
    try:
        _validate_path(target, must_exist=True)
        return True
    except ValueError:
        return False


# ─── 工具执行器 ───

def execute_tool(tool_name: str, args: dict, agent_id: str = "") -> str:
    """执行单个工具调用。agent_id 用于 get_shared_memory 和统计。"""
    if tool_name == "get_shared_memory":
        return _tool_get_shared_memory(args, agent_id)
    elif tool_name == "read_file":
        return _tool_read_file(args)
    elif tool_name == "search_code":
        return _tool_search_code(args)
    elif tool_name == "list_files":
        return _tool_list_files(args)
    elif tool_name == "add_note":
        return _tool_add_note(args, agent_id)
    elif tool_name == "generate_image":
        return _tool_generate_image(args)
    elif tool_name == "write_file":
        return _tool_write_file(args)
    elif tool_name == "add_discovery":
        return _tool_add_discovery(args, agent_id)
    else:
        return f"未知工具: {tool_name}"


# ════════════════════════════════════════
# 工具实现
# ════════════════════════════════════════

def _tool_get_shared_memory(args: dict, agent_id: str) -> str:
    """从 SharedMemory 获取当前 Agent 视角的上下文。"""
    from .shared_memory import get_shared_memory
    mem = get_shared_memory()

    # H7 修复：优先执行器绑定的 agent_id，LLM 传参不可覆盖（避免幻觉 id 读到他人槽位）
    aid = agent_id or args.get("agent_id", "")
    view = mem.get_agent_view(aid)

    result = f"=== 公共记忆 (Agent: {aid}) ===\n\n"
    # v3 P8: 注入可写工作目录，引导 Agent 正确落盘
    try:
        from ..config import get_config
        ws_dir = os.path.abspath(get_config().settings.workspace_dir)
        result += f"工作目录（可写，最终产物请用 write_file 保存到这里）: {ws_dir}\n\n"
    except Exception:
        pass
    result += f"任务: {view['task_description']}\n\n"

    if view["file_paths"]:
        result += "文件路径:\n"
        for name, path in view["file_paths"].items():
            result += f"  {name}: {path}\n"
        result += "\n"

    if view["custom_prompt"]:
        result += f"Allocator 定制 prompt:\n  {view['custom_prompt'][:500]}\n\n"

    if view["task_pointer"]:
        result += f"任务指针: {view['task_pointer']}\n\n"

    if view["user_input"]:
        result += f"用户输入 ({len(view['user_input'])} chars):\n{view['user_input'][:3000]}\n\n"

    if view["other_agents"]:
        result += "其他 Agent 状态:\n"
        for a in view["other_agents"]:
            result += f"  [{a['id']}] {a['type']} {a['status']}"
            if a["result_preview"]:
                result += f": {a['result_preview'][:100]}"
            result += "\n"
        result += "\n"

    if view["discoveries"]:
        result += "Agent 发现:\n"
        for d in view["discoveries"]:
            result += f"  - {d}\n"
        result += "\n"

    if view["global_notes"]:
        result += "全局笔记:\n"
        for n in view["global_notes"]:
            result += f"  - {n}\n"

    return result


def _tool_add_note(args: dict, agent_id: str) -> str:
    from .shared_memory import get_shared_memory
    mem = get_shared_memory()
    content = str(args.get("content", ""))[:_MAX_NOTE_SIZE]
    if not content.strip():
        return "错误：笔记内容不能为空"
    prefix = str(args.get("prefix", agent_id))[:100]
    mem.add_note(content, prefix)
    return f"已追加笔记 (Agent: {agent_id})"


def _tool_generate_image(args: dict) -> str:
    """生成图片。

    H4 修复：与生图工头降级链一致——先 API 生图，失败/空结果再回退本地 ComfyUI。
    本工具由 LLM 经 chat_with_tools 调用，运行在 asyncio.to_thread 工作线程内，
    同步 subprocess.run 不会阻塞事件循环。
    """
    import subprocess
    prompt = args.get("prompt", "")
    if not prompt:
        return "错误：缺少 prompt 参数"

    # 自动注入星野外貌标签（防止 LLM 瞎编发色/瞳色）
    pl = prompt.lower()
    if ("hoshino" in pl or "星野" in prompt) and "pink hair" not in pl:
        prompt = prompt.rstrip(",") + (
            ", very long pink hair, huge ahoge, heterochromia, blue eyes, yellow eyes, "
            "black plaid skirt, white collared shirt, chest harness, blue necktie"
        )
        logger.info("[TOOL] 自动注入星野标准外貌标签")

    from ..config import get_config
    s = get_config().settings

    # ── 后端 1: API 生图（DALL-E / SiliconFlow SD 等） ──
    try:
        from ..api.image_gen import generate, download_image
        urls = generate(prompt=prompt)
        if urls:
            output_dir = Path(get_config().settings.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            prefix0 = args.get("prefix", "tool")
            safe_p = "".join(c for c in prefix0 if c.isalnum() or c in "_-")[:20] or "tool"
            output_path = str(output_dir / f"tool_{safe_p}.png")
            download_image(urls[0], output_path)
            return f"图片已生成: {output_path}"
        logger.warning("[TOOL] API 生图返回空结果，回退 ComfyUI")
    except Exception as e:
        logger.warning(f"[TOOL] API 生图失败，回退 ComfyUI: {e}")

    # ── 后端 2: 本地 ComfyUI + NoobAI ──
    size = args.get("size", s.comfyui_default_size)
    cfg = _to_float(args.get("cfg"), s.comfyui_default_cfg)
    steps = _to_int(args.get("steps"), s.comfyui_default_steps)
    prefix = args.get("prefix", "agent_gen")
    prefix = "".join(c for c in prefix if c.isalnum() or c in "_-")[:20] or "safe"

    script = s.comfyui_script
    # 使用 sys.executable 代替硬编码 "python"，确保在 venv 中也能正确运行
    # 参数通过列表传递（非 shell 模式），subprocess 自动处理参数转义，防止命令注入
    python_exe = sys.executable or "python"
    cmd = [
        python_exe, script,
        prompt,
        "--size", str(size),
        "--cfg", str(cfg),
        "--steps", str(steps),
        "--prefix", str(prefix),
    ]

    logger.info(f"[TRACE-TOOL] ComfyUI prompt: {prompt[:300]}")
    logger.info(f"[TOOL] 调用 rp_gen: {prefix} ({size})")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=s.comfyui_timeout, cwd=s.comfyui_work_dir,
        )
        output = result.stdout + result.stderr
        # 跨平台图片路径匹配 (Windows + Linux/Mac)
        matches = re.findall(r"[A-Za-z]:[\\/][\w.\-\\/]+\.png", output)
        if not matches:
            matches = re.findall(r"/(?:[\w.-]+/)*[\w.-]+\.png", output)
        if matches:
            path = matches[-1]
            return f"图片已生成: {path}\n\n{output[-500:]}"
        return f"生成完成，但未找到输出路径。\n{output[-500:]}"
    except subprocess.TimeoutExpired:
        return f"错误：图片生成超时（>{s.comfyui_timeout}s）"
    except Exception as e:
        return f"图片生成失败: {e}"


def _tool_write_file(args: dict) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    # H6 修复：允许写入空内容（合法 0 字节文件），只要求 path
    if not path:
        return "错误：缺少 path 参数"
    # 大小限制
    content_size = len(content.encode("utf-8"))
    if content_size > _MAX_WRITE_SIZE:
        return f"错误：内容过大 ({content_size} bytes > {_MAX_WRITE_SIZE} limit)"
    try:
        safe_path = _validate_path(path, write=True)
        parent_dir = os.path.dirname(safe_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"文件已写入: {safe_path} ({len(content)} chars, {content_size} bytes)"
    except ValueError as e:
        return f"安全限制: {e}"
    except Exception as e:
        return f"写入文件失败: {e}"


def _tool_add_discovery(args: dict, agent_id: str) -> str:
    from .shared_memory import get_shared_memory
    mem = get_shared_memory()
    content = str(args.get("content", ""))[:_MAX_NOTE_SIZE]
    if not content.strip():
        return "错误：发现内容不能为空"
    mem.add_discovery(content, agent_id)
    return f"已追加发现 (Agent: {agent_id})"


def _tool_read_file(args: dict) -> str:
    path = args.get("path", "")
    if not path:
        return "错误：缺少 path 参数"
    try:
        safe_path = _validate_path(path, must_exist=True)
    except ValueError as e:
        return f"安全限制: {e}"
    if not os.path.isfile(safe_path):
        return f"文件不存在: {safe_path}"

    # 文件大小限制
    try:
        file_size = os.path.getsize(safe_path)
        if file_size > _MAX_FILE_SIZE:
            return f"文件过大: {safe_path} ({file_size} bytes > {_MAX_FILE_SIZE} limit)"
    except OSError as e:
        return f"无法读取文件大小: {e}"

    # PDF 文件用 PyPDF2 解析
    if safe_path.lower().endswith(".pdf"):
        return _read_pdf(safe_path, args)

    start = max(1, _to_int(args.get("start_line"), 1))
    count = min(_to_int(args.get("line_count"), 200), 500)

    try:
        with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return f"读取文件失败: {e}"

    total = len(lines)
    if start > total:
        return f"文件: {safe_path} (共 {total} 行)，请求起始行 {start} 超出文件范围"
    end = min(start + count - 1, total)
    selected = lines[start-1:end]

    result = f"文件: {safe_path} (共 {total} 行，显示 {start}-{end} 行)\n"
    for i, line in enumerate(selected, start):
        result += f"{i:4d}| {line}"
    return result


def _read_pdf(path: str, args: dict) -> str:
    """使用 PyPDF2 提取 PDF 文本内容。"""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(path)
        total_pages = len(reader.pages)
        start_page = max(1, _to_int(args.get("start_line"), 1))
        max_pages = min(_to_int(args.get("line_count"), 20), 50)
        end_page = min(start_page + max_pages - 1, total_pages)

        lines = []
        for i in range(start_page - 1, end_page):
            page = reader.pages[i]
            text = page.extract_text() or ""
            lines.append(f"--- 第 {i+1} 页 ---\n{text}")

        result = f"PDF: {path} (共 {total_pages} 页，显示第 {start_page}-{end_page} 页)\n\n"
        result += "\n\n".join(lines)
        return result
    except ImportError:
        return "PyPDF2 未安装，无法解析 PDF。请运行: pip install PyPDF2"
    except Exception as e:
        return f"PDF 解析失败: {e}"


# 搜索时排除的噪声目录（避免 .git/__pycache__/venv 拖慢或占满上限）
_NOISE_DIR_PARTS = {".git", "__pycache__", "node_modules", ".venv", "venv",
                    "dist", "build", ".tox", ".idea", ".vscode"}


def _tool_search_code(args: dict) -> str:
    path = args.get("path", "")
    pattern = args.get("pattern", "")
    # H1 修复：默认匹配所有文件（原 "*.py" 导致 .html/.js/.css 中的匹配永远搜不到）
    file_pattern = args.get("file_pattern", "*")
    max_results = min(_to_int(args.get("max_results"), 20), 50)

    if not path or not pattern:
        return "错误：缺少 path 或 pattern 参数"

    try:
        safe_path = _validate_path(path, must_exist=True)
    except ValueError as e:
        return f"安全限制: {e}"

    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return f"正则表达式错误: {e}"

    results = []
    target = Path(safe_path)

    try:
        if target.is_file():
            files = [target]
        elif target.is_dir():
            # H2 修复：先过滤沙箱外/噪声目录，再截断。
            # 原实现先 rglob[:100] 再过滤，前 100 个命中若全被排除则有效匹配被排空。
            files = []
            for f in target.rglob(file_pattern):
                if any(part in _NOISE_DIR_PARTS for part in f.parts):
                    continue
                if not _path_in_allowed(str(f)):
                    continue
                files.append(f)
                if len(files) >= 100:
                    break
        else:
            return f"路径不存在: {safe_path}"
    except Exception as e:
        return f"搜索路径失败: {e}"

    # 安全：过滤 glob 逃逸（`..`/symlink 可能命中白名单外文件）——上面已过滤，这里兜底
    files = [f for f in files if _path_in_allowed(str(f))]

    for f in files:
        if len(results) >= max_results:
            break
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    if compiled.search(line):
                        results.append(f"{f}:{i}: {line.rstrip()[:200]}")
                        if len(results) >= max_results:
                            break
        except Exception:
            continue

    if not results:
        return f"未找到匹配 '{pattern}' 的结果"
    return f"找到 {len(results)} 个匹配:\n" + "\n".join(results)


def _tool_list_files(args: dict) -> str:
    path = args.get("path", "")
    pattern = args.get("pattern", "*")

    try:
        safe_path = _validate_path(path, must_exist=True)
    except ValueError as e:
        return f"安全限制: {e}"
    if not os.path.isdir(safe_path):
        return f"不是目录: {safe_path}"

    try:
        files = sorted(Path(safe_path).glob(pattern))[:50]
    except Exception as e:
        return f"列出文件失败: {e}"

    # 安全：过滤 glob 逃逸（`..`/symlink 可能命中白名单外文件）
    files = [f for f in files if _path_in_allowed(str(f))]

    if not files:
        return f"目录 {safe_path} 中没有匹配 '{pattern}' 的文件"

    result = f"目录: {safe_path} ({len(files)} 个文件)\n"
    for f in files:
        suffix = "/" if f.is_dir() else f" ({f.stat().st_size} bytes)"
        result += f"  {f.name}{suffix}\n"
    return result
