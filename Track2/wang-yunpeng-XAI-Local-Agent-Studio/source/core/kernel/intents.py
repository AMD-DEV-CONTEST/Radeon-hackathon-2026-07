"""V4 内核：意图分类与执行处理器（Task #193 Phase C）。

从 engine_xai.py 上帝类外移 _classify_intent + 全部 _execute_*。逻辑不变。
"""

import os
import re
import sys
import json
import time
import uuid
import inspect
import threading
import concurrent.futures
import urllib.parse
import urllib.request
from ..ir import WorkflowNode, WorkflowEdge, NodeResult  # noqa: F401  V2 类型定义
from ..node_registry import NODE_HANDLER_MAP   # V2 节点注册表
from ..executor import WorkflowExecutor        # V2 工作流执行器
from ..adapters.base import AdapterResult
from ..adapters.openclaw_adapter import OpenClawAdapter
from ..adapters.hermes_adapter import HermesAdapter
from ..guardian import RiskLevel, Action, classify, ApprovalResult
from ..model_backend import StubBackend
from ..deepseek_backend import DeepSeekBackend
from ..session_store import SessionStore
from ..memory_core import default_core as default_memory_core
from ..cognition.intent_router import IntentRouter
from ..cognition.planner import Planner
from ..cognition.verifier import Verifier
from ..canvas.context import build_canvas_context  # Canvas-as-Context：对话注入画布上下文
from ..execution.action_bus import ActionBus
from ..grok_build_engine import GrokBuildBridge, default_bridge, resolve_grok_model
from ..coordination import CoordinationBus
from ..control_loop import ControlLoop
from ..distill import GepaEvolver, GepaScheduler
from ..model_registry import default_registry as default_model_registry
from ..provider_fallback import default_fallback
from ..loop_safety import default_safety
from ..project import default_project_manager
from .base import SlashCommand, Intent, _AdapterResultShim, SLASH_COMMANDS, INTENT_TYPES

from typing import Any, Dict, Generator, List, Optional
from .base import Intent, INTENT_TYPES

def classify_intent(engine, text: str) -> Intent:
    """意图分类：优先 IntentRouter 关键词打分，低于阈值退回规则。"""
    # 优先走 IntentRouter（5类意图 + 关键词 + 置信度）
    ir_result = engine.intent_router.classify(text)
    if ir_result.confidence >= 0.5 and ir_result.intent.value != "general":
        # 高置信度非通用意图：直接用路由结果
        routing_map = {
            "code_dev": "code_dev",
            "office_automation": "office",
            "long_term_business": "automation",
            "research": "research",
            "general": "general",
        }
        itype = routing_map.get(ir_result.intent.value, "general")
        conf = min(0.95, ir_result.confidence)
        return Intent(itype, conf, ir_result.rationale)

    # 低置信度或 general：退回内置规则分类
    t = text.lower()
    rules = {
        "code_dev": {
            "权重": 1.0,
            "关键词": ["def ", "class ", "import ", "函数", "类", "python代码", "生成代码",
                     "bug", "修复bug", "重构", "单元测试", "代码审查", "写代码", "写个脚本", "脚本",
                     "编写", "开发", "编程", "写一个", "实现一个", "算法", "排序",
                     "API", "接口", "前端", "后端", "数据库", "SQL",
                     "设计模式", "微服务", "部署", "Docker", "K8s",
                     "Java", "Rust", "Go", "TypeScript", "React", "Vue", "CSS", "HTML"],
        },
        "browser": {
            "权重": 0.9,
            "关键词": ["搜索", "搜一下", "查一下", "查查", "谷歌", "百度", "必应", "联网", "新闻", "最新"],
        },
        "office": {
            "权重": 0.8,
            "关键词": ["文件", "保存", "读取文件", "目录", "文件夹", "桌面", "截图", "邮件", "表格", "重命名"],
        },
        "research": {
            "权重": 0.95,
            "关键词": ["分析", "调研", "总结", "报告", "对比", "评估", "研究", "综述", "梳理", "解读",
                     "架构", "执行器", "能力", "是什么"],
        },
        "memory": {
            "权重": 0.9,
            "关键词": ["记住", "回忆", "之前", "上次", "过去", "你记得"],
        },
    }
    best = None; best_score = 0.0
    for intent, cfg in rules.items():
        hits = sum(1 for kw in cfg["关键词"] if kw in t)
        if hits and hits * cfg["权重"] > best_score:
            best_score = hits * cfg["权重"]; best = intent
    if best is None:
        return Intent("general", 0.60, "通用对话")
    conf = min(0.95, 0.6 + best_score * 0.1)
    return Intent(best, conf, f"命中「{best}」关键词")

# ---- 意图执行 ----



def execute_intent(engine, intent: Intent, text: str, session_id: str, history: List[dict], attachments=None, vision_parts=None) -> Generator[Dict[str, Any], None, None]:
    """根据意图路由到相应的适配器执行"""
    if intent.type == "code_dev":
        yield from execute_code(engine, text, attachments)
    elif intent.type == "browser":
        yield from execute_browser(engine, text)
    elif intent.type == "research":
        yield from execute_browser(engine, text)
    elif intent.type == "memory":
        yield from execute_memory_query(engine, text)
    elif intent.type in ("office", "file", "automation"):
        # 文件/桌面/自动化 → OpenClaw 执行网关（工具层）
        yield from execute_office(engine, text, history)
    else:
        yield from execute_general(engine, text, history, attachments, vision_parts=vision_parts, session_id=session_id)

# ---- 办公自动化 · OpenClaw 工具层 ----

def execute_office(engine, text: str, history: List[dict]) -> Generator[Dict[str, Any], None, None]:
    """文件/桌面/终端操作：通过 OpenClaw 执行网关调用工具。

    OpenClaw 在此降级为共享工具层（非独立执行器），
    Hermes 判断任务意图后，由 OpenClaw 执行实际操作，Hermes 负责推理与回复。
    """
    # 第一步：用 Hermes 先理解任务需求
    yield {"type": "progress", "stage": "plan", "text": "Hermes 正在理解任务需求..."}
    plan_prompt = (
        f"用户想要执行以下办公操作：{text}\n\n"
        "请用一句简短的话判断这个操作具体需要做什么（如：'列出桌面文件'、'创建文档'、'执行终端命令'），"
        "并在句末标注最可能需要的工具：file_list / file_read / file_write / exec / browser_open。仅输出一句话。"
    )
    plan_acc: List[str] = []
    try:
        for piece in engine._backend.stream_complete(plan_prompt, max_tokens=150):
            plan_acc.append(piece)
        engine.record_backend_usage(source="chat")
    except Exception:
        pass
    plan_text = "".join(plan_acc).strip() or f"处理办公请求：{text[:80]}"
    yield {"type": "progress", "stage": "exec", "text": f"OpenClaw 正在执行：{plan_text[:80]}"}

    # 第二步：检测关键词并调用 OpenClaw 工具
    t = text.lower()
    tool_result = ""
    try:
        if any(kw in t for kw in ["列出文件", "目录", "ls", "文件夹", "桌面文件", "list"]):
            res = engine.openclaw.execute({"tool": "file_list", "path": os.path.expanduser("~/Desktop")})
            tool_result = f"📂 桌面文件列表：\n{res.output[:800]}" if res and res.ok else "❌ 无法读取桌面文件"
        elif any(kw in t for kw in ["写入", "保存", "创建文件", "新建", "write", "save", "create"]):
            # Hermes 先生成内容，再写入
            gen_result = engine._infer_with_fallback(
                prompt=f"生成以下内容：{text}",
                system="你是文档助手。直接输出要写入文件的内容，不要多余解释。",
                max_tokens=1000,
            )
            content = gen_result.output if gen_result and gen_result.ok else text
            filename = f"generated_{uuid.uuid4().hex[:8]}.md"
            write_res = engine.openclaw.execute({"tool": "file_write", "path": filename, "content": content})
            tool_result = f"✅ 已写入文件 {filename}" if write_res and write_res.ok else f"❌ 写入失败"
        elif any(kw in t for kw in ["运行", "执行命令", "终端", "exec", "run", "shell", "脚本"]):
            # 提取命令（Hermes 推断）
            cmd_result = engine._infer_with_fallback(
                prompt=f"从以下请求中提取要执行的 shell 命令（只输出命令，不要解释）：{text}",
                system="只输出纯 shell 命令。",
                max_tokens=150,
            )
            cmd = (cmd_result.output or "").strip() if cmd_result and cmd_result.ok else ""
            if cmd:
                exec_res = engine.openclaw.execute({"tool": "exec", "command": cmd})
                tool_result = f"🖥️ 命令 `{cmd}` 输出：\n{exec_res.output[:500]}" if exec_res and exec_res.ok else f"❌ 执行失败"
            else:
                tool_result = "❌ 无法解析命令"
        elif any(kw in t for kw in ["打开浏览器", "浏览", "open url", "网址"]):
            import re as _re; urls = _re.findall(r'https?://\S+', text)
            if urls:
                engine.openclaw.execute({"tool": "browser_open", "url": urls[0]})
                tool_result = f"🌐 已打开 {urls[0]}"
            else:
                tool_result = "🔗 未找到可打开的 URL"
    except Exception as e:
        tool_result = f"❌ OpenClaw 执行异常：{e}"

    # 第三步：Hermes 基于工具结果做解释
    yield {"type": "progress", "stage": "answer", "text": "Hermes 正在整理执行结果..."}
    final_prompt = (
        f"办公任务：{text}\n工具执行结果：{tool_result}\n\n"
        "请基于以上结果用中文简要回复用户（3-5句话），说明做了什么操作、结果如何。"
    )
    final_acc: List[str] = []
    try:
        for piece in engine._backend.stream_complete(final_prompt, max_tokens=600):
            final_acc.append(piece)
            yield {"type": "token", "text": piece}
        engine.record_backend_usage(source="chat")
    except Exception:
        yield {"type": "answer", "answer": tool_result}

# ---- 流式通用对话 ----



_NARR_PREFIXES = ("思考要点", "【思考要点】", "我们",
                  "首先", "让我", "好的，用户", "用户要求", "用户问", "用户让我", "用户提供",
                  "面向用户", "根据提示词", "根据之前", "先看", "先分析", "现在看", "接下来看",
                  "现在用户", "这是一个", "嗯，用户")


def _clean_head(rest: str) -> str:
    """清洗答案头部：重复的答案标记 + 格式回显文字 + 残留标点。"""
    rest = rest.lstrip("\n：:。， ")
    # 模型偶发重复输出【最终答案】标记 → 循环剥净
    while rest.startswith(("【最终答案】", "最终答案")):
        rest = rest[len("【最终答案】") if rest.startswith("【") else len("最终答案"):].lstrip("\n：:。， ")
    for _echo in ("面向用户的答案本身", "面向用户的答案"):
        if rest.startswith(_echo):
            rest = rest[len(_echo):].lstrip("\n：:。， ")
            break
    return rest


def _split_narration(text: str) -> tuple[str, str]:
    """按段落把开头的自述推演段分出来：返回 (自述部分, 剩余答案)。

    模型无论是否遵守【最终答案】标记，答案区开头常见"我们被问到""根据之前的记忆"
    等推演段落——逐段判断前缀，自述段归思考，首个正常段落起为答案。
    """
    h = _clean_head(text)
    paras = h.split("\n\n")
    moved: list = []
    while paras and len("\n\n".join(moved)) < 900:
        p0 = paras[0].strip()
        head10 = p0.lstrip("【")[:10]
        # 短元语段落（"直接回答。""答案如下："）→ 丢弃，继续检查下一段
        if len(p0) <= 12 and any(k in p0 for k in ("直接回答", "答案如下", "回答如下", "如下")):
            paras.pop(0)
            continue
        if any(head10.startswith(n) for n in _NARR_PREFIXES):
            moved.append(paras.pop(0))
        else:
            break
    import re as _re3
    narr = _re3.sub(r"【?最终答案】?[:：]?", "", "\n\n".join(moved)).strip()
    return narr, _clean_head("\n\n".join(paras))


def _stream_split_thinking(pieces) -> Generator[Dict[str, Any], None, None]:
    """流式双段解析（思考透明化，2026-07-27）：
    - 【最终答案】标记前的内容 → progress(stage=thinking) 事件，前端过程可见；
      思考较长时每 ~300 字透出一次中途进度，避免用户全黑盒等待。
    - 标记后的内容 → token 流，答案干净无思考残留（含答案段开头自述段落的二次分流）。
    - 模型不守格式兜底：缓冲超 2400 字直接放行；流结束仍无标记 → 按段落分流后放行。
    """
    _MARK = "【最终答案】"
    buf = ""; state = "thinking"; hold = ""; emitted = 0
    # state: thinking(标记前) → hold(标记后短暂缓冲，防模型在答案段重复写思考) → answer(直通)
    for piece in pieces:
        if state == "answer":
            yield {"type": "token", "text": piece}
            continue
        if state == "thinking":
            buf += piece
            idx = buf.find(_MARK)
            if idx >= 0:
                thinking = buf[:idx].replace("【思考要点】", "").strip()
                if thinking:
                    yield {"type": "progress", "stage": "thinking", "text": f"💭 思考要点:\n{thinking[:800]}"}
                hold = _clean_head(buf[idx + len(_MARK):])
                state = "hold"
            elif len(buf) - emitted >= 300 and emitted < 1200:
                part = buf.replace("【思考要点】", "").strip()
                yield {"type": "progress", "stage": "thinking", "text": f"💭 思考中…\n{part[-300:]}"}
                emitted = len(buf)
            elif len(buf) > 2400:
                yield {"type": "token", "text": buf}
                state = "answer"
            continue
        # state == "hold"：答案段头部缓冲。模型常在答案段开头继续自述推演
        # （"我们被问到""首先看结果""面向用户，带引用"…），按段落分流：
        # 开头的自述段落一律归入思考进度，从第一个正常段落起才是答案。
        hold += piece
        h = _clean_head(hold)
        if "\n\n" not in h and len(h) < 900:
            continue  # 攒够一个完整段落再判断
        narr, rest2 = _split_narration(h)
        if not rest2 and len(h) < 1800:
            continue  # 全是自述且还不长 → 继续攒，等正常段落出现
        if narr:
            yield {"type": "progress", "stage": "thinking", "text": f"💭 思考要点(补):\n{narr[:600]}"}
        if rest2:
            yield {"type": "token", "text": rest2}
        state = "answer"
    # 流结束的收尾：无论哪种状态，都过一次段落分流，防自述全量漏出
    tail = buf if state == "thinking" else (hold if state == "hold" else "")
    if tail:
        narr, rest3 = _split_narration(tail)
        if narr:
            yield {"type": "progress", "stage": "thinking", "text": f"💭 思考要点:\n{narr[:600]}"}
        # 全是自述没有正常段落时，把自述当答案放行（宁多勿丢）
        yield {"type": "token", "text": rest3 if rest3 else _clean_head(tail)}


# 双段输出格式指令（通用对话/搜索作答共用）
_TWO_STAGE_FORMAT = (
    "\n\n输出格式要求（必须遵守）：\n"
    "【思考要点】\n- 先用 2-5 条要点概括你的关键思考节点（问题理解/依据/取舍/不确定点）\n"
    "【最终答案】\n再输出面向用户的答案本身。此段禁止出现'好的，用户''让我''我们需''首先分析'等自述性推演文字。"
)


def execute_general(engine, text: str, history: List[dict], attachments=None, vision_parts=None, session_id: str = "") -> Generator[Dict[str, Any], None, None]:
    """通用对话：流式输出 + 多轮上下文 + 记忆检索 + 画布上下文（Canvas-as-Context）。"""
    engine.action_bus.model_call("deepseek", len(text))

    # 检索相关记忆作为上下文
    memory_context = engine._retrieve_memory_context(text)

    # Canvas-as-Context：把当前会话关联的画布序列化注入系统提示词（无画布则为空串，不注入）
    canvas_context = build_canvas_context(session_id) if session_id else ""

    system = engine._build_system_prompt(memory_context, canvas_context=canvas_context) + _TWO_STAGE_FORMAT

    # 构造多轮 messages：system + 历史 + 当前（含上传附件内容）
    messages = [{"role": "system", "content": system}]
    # 历史可能含 system？不，历史只有 user/assistant
    messages.extend(history)
    user_content = text
    if attachments:
        user_content += engine._attachment_context(attachments)
        yield {"type": "progress", "stage": "attach", "text": f"已载入 {len(attachments)} 个上传文件作为上下文"}
    messages.append({"role": "user", "content": user_content})

    # 视觉多模态：路由层已构造 vision_parts（文本+图片）时，覆盖最后一条 user 消息为 content 数组
    if vision_parts:
        messages[-1]["content"] = vision_parts
        yield {"type": "progress", "stage": "vision", "text": f"已附带 {len([p for p in vision_parts if p.get('type') == 'image_url'])} 张图片发送给视觉模型"}

    try:
        yield from _stream_split_thinking(
            engine._backend.stream_complete(text, messages=messages, max_tokens=1800, vision_parts=vision_parts)
        )
        engine.record_backend_usage(source="chat")
    except Exception as e:
        # 故障轮换：切到备用模型重试（视觉内容在备用模型上可能不支持，降级为纯文本）
        yield {"type": "reset", "reason": "fallback"}
        yield {"type": "progress", "stage": "fallback", "text": f"主模型异常，尝试切换备用..."}
        fb = engine.provider_fallback
        next_model = fb._find_next(engine.model_registry.active()) if engine.model_registry.active() else None
        if next_model:
            engine.model_registry.activate(next_model.id)
            engine._rebuild_backend()
            try:
                yield from _stream_split_thinking(
                    engine._backend.stream_complete(text, messages=messages, max_tokens=1800)
                )
                engine.record_backend_usage(source="chat")
                return
            except Exception:
                pass
        yield {"type": "error", "error": f"推理失败: {e}"}

# ---- 代码开发 ----



def execute_code(engine, text: str, attachments=None) -> Generator[Dict[str, Any], None, None]:
    """代码开发意图：按 Grok Build 自有框架执行。不做人为能力分类，全部交给 Grok 内部处理。

    Grok 自带完整的工程框架（规划→Agent分配→工具执行→自验证），
    我们只决定：是否加 --check（自验证）或 --best-of-n（并行探索）。
    """
    # 第一阶段：Grok Build（无我臆想的能力分类）
    if engine.grok_build.available:
        attach_ctx = engine._attachment_context(attachments) if attachments else ""
        full_task = text + attach_ctx

        # 决定 Grok CLI 额外参数（基于任务特征，仅这两种）
        extra = engine._grok_task_flags(text)

        yield {"type": "progress", "stage": "code_gen",
               "text": f"Grok Build 代码引擎 · 正在执行{'（自验证）' if '--check' in extra else ''}{'（并行探索）' if '--best-of-n' in extra else ''}..."}

        try:
            # 统一映射：优先用户显式 Grok 偏好，否则由当前激活引擎模型推导
            # （覆盖 DeepSeek→deepseek-flash/pro、含 grok 的模型原样透传等）
            gb_model = resolve_grok_model(engine)
            gb_result = engine.grok_build.run(full_task, extra_flags=extra, model=gb_model)
        except Exception as e:
            yield {"type": "progress", "stage": "gb_fallback",
                   "text": f"Grok Build 异常，退回通用引擎: {e}"}
            gb_result = {"ok": False}

        if gb_result.get("ok") or gb_result.get("text"):
            result_text = gb_result.get("text") or gb_result.get("raw", "")
            yield {"type": "answer",
                   "answer": f"[Grok Build] {result_text[:3000]}"}
            yield {"type": "deliverable", "name": "grok_build_result",
                   "stored": "grok_build_result", "lang": "text",
                   "content": json.dumps(gb_result, ensure_ascii=False, indent=2)}
            # 第二阶段：记忆反思（事后优化，不阻断主流程）
            engine._reflect_grok_result(full_task, gb_result)
            return
        else:
            fallback_err = gb_result.get('error', '')[:100]
            yield {"type": "progress", "stage": "gb_fallback",
                   "text": f"Grok Build 未能完成，退回通用引擎: {fallback_err}"}

    # 回退：Hermes 推理
    attach_ctx = engine._attachment_context(attachments) if attachments else ""
    yield {"type": "progress", "stage": "code_gen", "text": "正在生成代码（Hermes）..."}
    result = engine._infer_with_fallback(
        prompt=text + attach_ctx,
        system="你是一个专业的软件工程师。用 Python 编写高质量、可运行的代码。仅输出代码和简要注释，使用 ```python 代码块包裹。",
        max_tokens=2000,
    )
    if not result.ok:
        yield {"type": "error", "error": result.error or "代码生成失败"}
        return

    code = engine._extract_code(result.output)
    if not code:
        code = result.output.strip()

    yield {"type": "progress", "stage": "code_check", "text": "正在校验语法..."}

    code_filename = f"generated_{uuid.uuid4().hex[:8]}.py"
    abs_path = engine.openclaw.workspace_path(code_filename)
    write_result = engine.openclaw.execute({"tool": "file_write", "path": code_filename, "content": code})
    if not write_result.ok:
        yield {"type": "error", "error": write_result.error or "代码写入失败"}
        return

    exec_result = engine.openclaw.execute(
        {"tool": "exec", "command": f"{sys.executable} -m py_compile {abs_path}"}
    )

    yield {
        "type": "deliverable",
        "name": code_filename,
        "stored": code_filename,
        "lang": "python",
        "content": code,
    }

    if exec_result.ok:
        yield {"type": "answer", "answer": f"✅ 代码已生成并校验通过：**{code_filename}**\n\n可在右侧「交付物」面板中 打开 / 复制 / 下载。"}
    else:
        yield {"type": "answer", "answer": f"代码已生成，但语法检查未通过（**{code_filename}**）：\n```\n{exec_result.output[:1000]}\n```\n\n完整代码见右侧「交付物」面板。"}



def execute_browser(engine, text: str) -> Generator[Dict[str, Any], None, None]:
    """浏览器意图：真实联网搜索 + 基于结果作答。"""
    yield {"type": "progress", "stage": "search", "text": "正在联网搜索..."}
    query = re.sub(r"(搜索|搜一下|查一下|查查|谷歌|百度|必应|联网|新闻|最新|帮我)", "", text, flags=re.IGNORECASE).strip()
    if not query:
        query = text

    sr = engine.tool_bus.dispatch("search", query=query, max_results=5)
    results = sr.data if sr.status == "ok" else []
    if not results:
        yield {"type": "progress", "stage": "fallback", "text": "实时搜索不可用，转为通用作答（基于模型知识）"}
        yield from execute_general(engine, text, [])
        return

    # 构造带引用的上下文，让模型基于结果回答
    ctx = "\n".join(f"[{i+1}] {r['title']}\nURL: {r['url']}\n摘要: {r['snippet']}" for i, r in enumerate(results[:5]))
    prompt = (
        f"用户问题：{text}\n\n"
        f"以下是实时搜索结果，请基于这些结果用中文回答，并在句末标注引用编号（如 [1]）：\n\n{ctx}\n\n"
        f"如果搜索结果不足以回答，请诚实说明。\n"
        f"请严格按以下两段格式输出：\n"
        f"【思考要点】\n- 用 2-4 条要点概括：哪些结果可信、哪些矛盾、你的取舍依据\n"
        f"【最终答案】\n面向用户的答案本身（带 [n] 引用），禁止出现'我们需根据''先分析'等分析过程自述。"
    )
    yield {"type": "progress", "stage": "answer", "text": "正在整理搜索结果..."}
    try:
        yield from _stream_split_thinking(engine._backend.stream_complete(prompt, max_tokens=1400))
        engine.record_backend_usage(source="search")
    except Exception as e:
        yield {"type": "error", "error": f"搜索结果作答失败: {e}"}



_MEM_WRITE_KW = ("记住", "记一下", "记下来", "帮我记", "存一下", "备忘", "别忘了")
_MEM_QUERY_KW = ("回忆", "之前", "上次", "过去", "查查", "你记得", "想起", "还记得")


def execute_memory_query(engine, text: str) -> Generator[Dict[str, Any], None, None]:
    """记忆意图 —— 写入 / 检索 双分支，统一走 memory_core（V4 单一事实源）。

    修复（2026-08-04）：
      1) 原实现调用 memory_core.query_cross_engine(q=..., limit=...)，
         但该方法签名是 (engine, limit) —— 传 q 必抛 TypeError，
         导致任何命中"记忆"意图的对话直接 500 且会话不落库。
         改为走 query(keyword=...)，关键词下推 SQL（key/value 双字段）。
      2) 原实现只有"检索"一条路：用户说"记住 X"时不会真的写入，
         只会拿"记住 X"去检索并回一句"未找到"，功能等于没有。
         现按写入/检索关键词分流，写入落 long_term 层。
    """
    raw = (text or "").strip()
    hit_write = any(k in raw for k in _MEM_WRITE_KW)
    hit_query = any(k in raw for k in _MEM_QUERY_KW)

    # ---- 写入分支 ----
    if hit_write and not hit_query:
        content = raw
        for k in _MEM_WRITE_KW:
            content = content.replace(k, "")
        content = content.strip(" ：:，,。.、;；\n") or raw
        try:
            engine.memory_core.store(
                layer="long_term",
                key=content[:40],
                value=content,
                engine="hermes",
                importance=0.7,
                project_id=engine._project_id(),
            )
            yield {"type": "answer",
                   "answer": f"✅ 已记住：{content}\n\n（写入长期记忆层，之后可用「回忆…」检索）"}
        except Exception as e:
            yield {"type": "error", "error": f"记忆写入失败: {e}"}
        return

    # ---- 检索分支 ----
    q = raw
    for kw in _MEM_QUERY_KW + _MEM_WRITE_KW:
        q = q.replace(kw, "")
    q = q.strip(" ：:，,。.、?？;；\n")
    entries = engine.memory_core.query(keyword=q or None, limit=10)
    if entries:
        lines = [f"[{e.layer}|{e.engine}] {e.value[:200]}" for e in entries]
        yield {"type": "answer", "answer": "检索到的记忆:\n" + "\n".join(lines)}
    else:
        yield {"type": "answer", "answer": f"未找到与「{q or raw}」相关的记忆"}

# ---- 系统提示词（动态，去假数字） ----



def execute_planned(engine, text: str, session_id: str, history: List[dict],
                     attachments=None) -> Generator[Dict[str, Any], None, None]:
    """V4 唯一执行链路: Plan → Execute → Verify → Memory。"""
    plan = engine.planner.plan(text)
    yield {"type": "progress", "stage": "plan", "text": f"Planner: {len(plan.steps)} 步骤 — {plan.rationale[:80]}"}
    yield {"type": "plan", "steps": plan.to_dict()["steps"]}

    all_outputs: List[str] = []
    while True:
        step = plan.next_pending()
        if step is None:
            break
        step.status = "running"
        yield {"type": "progress", "stage": "exec", "text": f"Step {step.step_id}: [{step.agent}] {step.task[:60]}"}

        output_parts: List[str] = []
        if step.agent == "hermes":
            for ev in execute_general(engine, step.task, history, attachments):
                if ev.get("type") == "token": output_parts.append(ev.get("text", ""))
                yield ev
        elif step.agent == "grok":
            for ev in execute_code(engine, step.task, attachments):
                if ev.get("type") in ("answer", "token"): output_parts.append(ev.get(ev.get("type"), ""))
                yield ev
        else:
            for ev in execute_general(engine, f"审查: {all_outputs[-1][:300] if all_outputs else step.task}", history):
                if ev.get("type") == "token": output_parts.append(ev.get("text", ""))
                yield ev

        output = "".join(output_parts)
        vresult = engine.verifier.verify(step.task, output, step.step_id)
        yield {"type": "verify", "step": step.step_id, "passed": vresult.passed, "score": vresult.score, "issues": vresult.issues}
        if vresult.passed:
            step.status = "done"; all_outputs.append(output)
        else:
            step.status = "failed"

    yield {"type": "answer", "answer": f"## 完成 ({sum(1 for s in plan.steps if s.status=='done')}/{len(plan.steps)} 步)"}

