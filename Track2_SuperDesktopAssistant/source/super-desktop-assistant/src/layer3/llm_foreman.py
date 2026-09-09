"""
Layer 3: LLM 工头（v2.0）

管理 3 个基础 LLM 实例，负责：
- 模型路由：根据任务类型选择最合适的模型
- 动态提示词生成：为 LLM 实例生成专用 System/User Prompt
- 上下文管理：每个实例独立会话上下文，同任务内共享
- 结果校验：检查输出格式，不符合则触发重新生成
- 经验写入：失败时提炼经验写入公共记忆

对应第4层：3 个 LLM Worker 实例（推理强/文采好/便宜快）
"""
from __future__ import annotations

import asyncio
import os
from typing import Any
from loguru import logger

from .base_foreman import BaseForeman, Workspace
from ..layer4.mcp_contract import ErrorCode
from ..api.llm import chat, chat_json, chat_with_tools
from ..agents.tools import AGENT_TOOLS


# ── v3 P1: 工具调用指南（追加到每个 System Prompt） ──
_TOOL_GUIDE = (
    "你有以下工具：\n"
    "- get_shared_memory(agent_id): 获取任务上下文、工作目录路径、其他Agent状态\n"
    "- read_file(path): 读取文件内容（支持 PDF）\n"
    "- write_file(path, content): 写入文件（HTML/JSON/PY 等），自动创建父目录\n"
    "- search_code(path, pattern): 正则搜索文件内容\n"
    "- list_files(path): 列出目录文件\n"
    "- generate_image(prompt, size, cfg, steps, prefix): 生成动漫图片\n"
    "- add_note(content, prefix): 分享笔记给其他 Agent\n"
    "- add_discovery(content): 追加发现\n\n"
    "重要：\n"
    "1. 首先调用 get_shared_memory 获取任务上下文，其中包含工作目录路径\n"
    "2. 最终产出应是实际文件（HTML、py、JSON 等），用 write_file 保存到工作目录\n"
    "3. 工具调用完成后，最后一步必须用 write_file 保存成品\n"
    "4. 生图 prompt 必须用 NoobAI 标签格式（逗号分隔英文标签），前面加 "
    "very awa, masterpiece, best quality, newest, highres, absurdres。\n"
    "5. 生图时严格按用户指定的角色生成。若用户提到作品角色，使用标准标签"
    "（如 azusa (blue archive)、hoshino (blue archive)），按角色真实特征描述，"
    "不要臆造或套用其他角色的外貌。\n"
    "6. 如果任务仅需文字输出（写作/问答/翻译/写诗等），直接输出最终内容，"
    "不要描述步骤，不要调用工具，不要输出'1. 2. 3.'这类计划说明。"
)


class LLMForeman(BaseForeman):
    """
    LLM 工头 —— 管理多个 LLM 模型实例。

    模型路由策略：
    - "reasoning" (推理/代码) → 模型A（混元/DeepSeek-R1）
    - "creative" (创意/写作) → 模型B（DeepSeek-V3/Qwen）
    - "summary" (摘要/问答) → 模型C（GPT-mini/便宜模型）
    """

    foreman_type = "text"

    def __init__(self):
        super().__init__()
        self.max_retries = 2
        self.base_timeout = 30.0

        # 模型路由配置（从 config 读取，这里给默认值）
        self._model_routing = {
            "reasoning": "llm",
            "creative": "llm",
            "summary": "llm",
        }

        # 策略缓存：常用 Prompt 模板
        self.set_cached_strategy("creative_writing", (
            "你是一位创意写作专家。请根据以下要求创作内容。\n"
            "要求：语言优美、富有想象力、符合用户指定的风格。"
        ))
        self.set_cached_strategy("code_generation", (
            "你是一位资深软件工程师。请基于以下需求编写代码。\n"
            "要求：代码规范、注释清晰、考虑边界条件和错误处理。"
        ))
        self.set_cached_strategy("summary", (
            "请简洁概括以下内容的核心要点，不超过200字。"
        ))

    # ── 执行入口 ──

    async def _execute_impl(self, task: dict, ws: Workspace) -> str:
        """LLM 工头执行逻辑。"""
        user_input = self._sanitize_input(task.get("user_input", ""))
        task_id = task.get("task_id", "")

        # 1. 任务分类 → 模型路由
        task_category = self._classify_task(user_input)
        model_key = self._route_model(task_category)

        # 2. 动态生成 System Prompt + 注入可写工作目录
        system_prompt = self._generate_system_prompt(task_category, task)
        # 重构修复（Bug 7）：把上一轮压缩摘要并入 system_prompt（消息开头），
        # 而非以 system 角色插入 ws.context 对话中部（部分 API 拒绝非开头的 system 角色）。
        if ws.last_summary:
            system_prompt = f"{system_prompt}\n\n[历史摘要] {ws.last_summary[:1000]}"
        from ..config import get_config as _gc
        ws_abs = os.path.abspath(_gc().settings.workspace_dir)
        user_prompt = (
            f"工作目录（可写，请把最终产物用 write_file 保存到这里）: {ws_abs}\n\n"
            f"任务：{user_input}"
        )

        # 3. 上下文管理：最多保留 N 轮
        context = ws.context[-self.max_context_turns * 2:]  # user+assistant 对

        # 4. 构建消息
        messages = [{"role": "system", "content": system_prompt}]

        # v3 修复 H1：注入多轮对话历史（v3 路径此前丢失历史，导致"把喵改成汪"类追问失效）。
        # 只放行 user/assistant 角色，跳过 tool/system 残留（防止 API 拒绝）。
        hist = task.get("conversation_history") or []
        for h in hist[-self.max_context_turns * 2:]:
            if not isinstance(h, dict):
                continue
            role = h.get("role")
            content = h.get("content")
            if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                messages.append({"role": role, "content": content[:1000]})

        if context:
            messages.extend(context)

        # v3 修复 H2：注入依赖节点输出（"写诗→朗读"里 LLM 能看到上游生成内容）
        upstream = task.get("upstream_results") or {}
        if upstream:
            parts = [
                f"[上游节点 {nid} 输出]:\n{val[:2000]}"
                for nid, val in upstream.items()
            ]
            user_prompt = user_prompt + "\n\n" + "\n\n".join(parts)

        messages.append({"role": "user", "content": user_prompt})

        # 5. 调用第4层 LLM Worker（v3 P0b: 单次单 API 锁定；P1: chat_with_tools + 降级）
        from ..config import get_config
        s = get_config().settings

        # 任务生命周期内锁定 provider/model，禁止中途切换
        provider_name = ws.api_provider
        model_name = ws.api_model
        if not provider_name or not model_name:
            provider_name, model_name = await self._pick_provider(model_key)
            ws.api_provider = provider_name
            ws.api_model = model_name
            logger.info(f"[FM:text] [{task_id}] 锁定 API: {provider_name}/{model_name}")

        # 工具回调：绑定 agent_id（节点/任务 ID）
        def _tool_handler(tool_name: str, args: dict) -> str:
            from ..agents.tools import execute_tool
            return execute_tool(tool_name, args, agent_id=task_id)

        try:
            result = await asyncio.to_thread(
                chat_with_tools,
                messages=messages,
                tools=AGENT_TOOLS,
                on_tool_call=_tool_handler,
                capability=model_key,
                provider=provider_name,
                model=model_name,
                temperature=s.llm_agent_temperature,
                max_tokens=s.llm_agent_max_tokens,
                max_tool_rounds=s.max_tool_rounds,
            )
        except Exception as e:
            # 永久错误直接抛出，不降级
            from ..api.errors import is_permanent_error
            if is_permanent_error(str(e)):
                raise
            err_msg = str(e).lower()
            if any(k in err_msg for k in ("tool", "function", "not support",
                                          "unknown parameter", "unrecognized",
                                          "invalid")):
                logger.info(f"[FM:text] [{task_id}] 工具调用不支持，降级为普通对话")
                result = await asyncio.to_thread(
                    chat,
                    messages=messages,
                    capability=model_key,
                    provider=provider_name,
                    model=model_name,
                    temperature=s.llm_agent_temperature,
                    max_tokens=s.llm_agent_max_tokens,
                )
            else:
                raise

        # 6. 结果校验
        validated = self._validate_output(result, task_category)

        # 7. 更新工作区上下文
        ws.context.append({"role": "user", "content": user_prompt[:500]})
        ws.context.append({"role": "assistant", "content": validated[:500]})

        # 8. 压缩旧上下文（超过最大轮次）
        # M8 修复：原来只算摘要不截断，ws.context 无界增长导致 API payload 越来越大。
        # 现在真正截断到最近 N 轮，摘要存入 ws.last_summary（下次调用并入 system_prompt）。
        # 重构修复（Bug 7）：不再以 system 角色插入 ws.context —— 该条目既会被
        # 切片 [-(N*2):] 切掉、又会在幸存时出现在对话中部违反 system 须置顶的约定。
        if len(ws.context) > self.max_context_turns * 2:
            old = ws.context[:-(self.max_context_turns * 2)]
            ws.last_summary = self._compress_context(old)
            ws.context = ws.context[-(self.max_context_turns * 2):]

        return validated

    # ── 任务分类 ──

    def _classify_task(self, user_input: str) -> str:
        """粗分类用户任务类型。"""
        input_lower = user_input.lower()

        # 代码/推理关键词
        code_keywords = [
            "代码", "编程", "写一个", "实现", "函数", "class", "def",
            "bug", "调试", "算法", "重构", "code", "program",
            "python", "javascript", "html", "css", "sql",
        ]
        # 创意/写作关键词
        creative_keywords = [
            "写诗", "故事", "小说", "创意", "文案", "润色",
            "改一改", "优化一下", "翻译", "poem", "story",
            "创作", "写一篇", "改写", "想象",
        ]

        if any(k in input_lower for k in code_keywords):
            return "reasoning"
        if any(k in input_lower for k in creative_keywords):
            return "creative"
        return "summary"

    def _route_model(self, task_category: str) -> str:
        """模型路由（v3 P0b：子能力路由，未配置时回退 llm）。"""
        capability_map = {
            "reasoning": "llm_reasoning",   # 推理/代码 → deepseek
            "creative": "llm_creative",     # 创意/写作 → qwen
            "summary": "llm_summary",       # 摘要/问答 → mimo
        }
        return capability_map.get(task_category, "llm")

    async def _pick_provider(self, capability: str) -> tuple[str, str]:
        """选择本次任务锁定的 (provider, model)。

        - 子能力路由 + 禁用过滤（ConfigManager.resolve）
        - api_preference=local_first 时：本地首选不可达 → 降级到云端候选
        """
        from ..config import get_config
        cfg = get_config()

        resolved = cfg.resolve(capability)
        if not resolved:
            raise RuntimeError(f"功能 '{capability}' 未分配可用的供应商/模型")

        p, m = resolved

        # local_first：首选本地不可达 → 降级到云端候选
        # M7 修复：socket 连通性探测是同步阻塞的，放进 to_thread，避免阻塞事件循环
        if cfg.settings.api_preference == "local_first" and p.is_local:
            from ..api._client import provider_is_reachable
            reachable = await asyncio.to_thread(provider_is_reachable, p)
            if not reachable:
                logger.warning(f"[FM:text] 本地供应商 {p.name} 不可达，降级到其他候选")
                for cand_p, cand_m in cfg.resolve_candidates(capability):
                    if not cand_p.is_local:
                        logger.info(f"[FM:text] 降级 → {cand_p.name}/{cand_m.id}")
                        return cand_p.name, cand_m.id

        return p.name, m.id

    # ── Prompt 生成 ──

    def _generate_system_prompt(self, task_category: str, task: dict) -> str:
        """根据任务类型生成专用 System Prompt。

        v3 P1：基础类别 prompt（可缓存）+ 工具调用指南，输出可观测性日志。
        """
        # 优先命中缓存（基础类别 prompt；reasoning↔code_generation 等键名映射）
        cache_key = {
            "reasoning": "code_generation",
            "creative": "creative_writing",
            "summary": "summary",
        }.get(task_category, task_category)
        cached = self.get_cached_strategy(cache_key)
        if cached:
            base_prompt = cached
        else:
            # 默认 Prompt
            prompts = {
                "reasoning": (
                    "你是一位资深技术专家。请基于用户的需求提供准确、详细的回答。\n"
                    "如果需要编写代码，确保代码规范、有注释、考虑边界情况。"
                ),
                "creative": (
                    "你是一位创意写作专家。请根据用户的需求创作内容。\n"
                    "注重语言的美感和表达的精准性。"
                ),
                "summary": (
                    "请简洁准确地回答用户的问题。言简意赅，直击要点。"
                ),
            }
            base_prompt = prompts.get(task_category, prompts["summary"])

        # v3 P1: 追加工具调用指南
        full_prompt = base_prompt + "\n\n" + _TOOL_GUIDE

        # 可观测性：记录动态提示词生成（类别、长度、内容前 200 字）
        logger.info(
            f"[FM:text][prompt-gen] category={task_category} "
            f"len={len(full_prompt)} head={full_prompt[:200]!r}"
        )
        return full_prompt

    # ── 输出校验 ──

    def _validate_output(self, output: str, task_category: str) -> str:
        """校验输出是否符合预期格式。"""
        if not output or not output.strip():
            raise RuntimeError(f"[LLMForeman] 空输出，任务类别: {task_category}")

        # 代码任务：检查是否有实质性内容
        if task_category == "reasoning":
            if len(output.strip()) < 20:
                raise RuntimeError(f"[LLMForeman] 推理输出过短: {len(output)} chars")

        return output.strip()

    # ── 上下文压缩 ──

    def _compress_context(self, old_context: list[dict]) -> str:
        """压缩旧上下文为一句摘要。"""
        if not old_context:
            return ""

        # 简单策略：提取最后几条的关键信息
        messages = [m.get("content", "")[:100] for m in old_context[-6:]]
        summary = " | ".join(messages)
        return f"[历史摘要] {summary[:200]}"

    # ── 历史记忆检索 ──

    def get_relevant_experiences(self, task: dict) -> list[dict]:
        """检索相关的历史经验，用于优化当前 prompt。"""
        from ..memory.public_memory import get_public_memory

        mem = get_public_memory()
        experiences = mem.get_experiences_for_task(
            task_type="text",
            keywords=[task.get("user_input", "")[:30]],
            limit=3,
        )

        return [
            {"subject": e.subject, "content": e.content, "tags": e.tags}
            for e in experiences
        ]
