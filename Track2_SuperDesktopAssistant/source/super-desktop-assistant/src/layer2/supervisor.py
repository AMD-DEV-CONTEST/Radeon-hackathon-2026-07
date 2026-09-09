"""
Layer 2: 中央调度层（HR/Supervisor）（v2.0）

核心职责：
1. 意图分类（粗粒度）：image / text / audio，识别复合意图
2. 任务粗分与依赖声明：多意图拆为独立子任务包，显式声明 DAG 依赖
3. 路由分发：根据意图路由给第3层工头，依赖满足后触发
4. 结果汇总：等待所有子任务完成（或超时），组装统一回复格式
5. 公共记忆管理：检索 Top-K 相关记忆，以 Manifest 形式下发
6. 上下文重置信号：检测语义突变，标记 reset_context

v2.0 新增：显式 DAG 依赖编排、分解传播规则、差异化超时、记忆 Manifest
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from loguru import logger

from ..orchestration.dag import TaskDAG, DAGNode, NodeStatus, NodeType
from ..orchestration.executor import execute_dag, ExecutionResult
from ..memory.public_memory import get_public_memory, PublicMemoryService, MemoryType


# ═══════════════════════════════════════════════════════════════
# 任务定义
# ═══════════════════════════════════════════════════════════════

@dataclass
class SubTask:
    """第2层拆分的子任务。"""
    task_id: str
    task_type: str                    # "image" | "text" | "audio"
    description: str                  # 简要描述
    prompt: str                       # 下发给工头的用户描述
    depends_on: list[str] = field(default_factory=list)   # 依赖的 task_id
    entities: dict = field(default_factory=dict)
    memory_manifest: dict | None = None
    # v3 修复：executor 路径下注入的上下文（H1/H2）
    upstream_results: dict = field(default_factory=dict)      # 依赖节点输出 {dep_id: text}
    conversation_history: list | None = None                  # 多轮对话历史
    executor_managed: bool = False                            # True=由 Executor 统一重试，工头不再自试
    # 重构修复（Bug 1/3）：DAG 节点类型派生的音频子类型 + 重置上下文信号
    sub_type: str | None = None                               # "stt" | "tts"（audio 任务）
    reset_context: bool = False                               # 语义突变 → 重置工头工作区


@dataclass
class TaskResult:
    """子任务执行结果。"""
    task_id: str
    status: str                       # "success" | "error" | "timeout" | "skipped"
    data: Any = None
    error: dict | None = None
    elapsed_ms: float = 0


# ═══════════════════════════════════════════════════════════════
# 意图分类
# ═══════════════════════════════════════════════════════════════

class IntentClassifier:
    """
    粗粒度意图分类器。

    将用户输入分为 image / text / audio 三类，
    并识别复合意图（如"画猫 + 写诗 + 朗读"）。
    """

    # 关键词→意图映射
    _IMAGE_KEYWORDS = [
        "画", "图片", "生成图", "生成一张", "绘制", "画一张",
        "做一张图", "画图", "插图", "配图", "generate image",
        "画一幅", "生成图片", "帮我画", "画个", "画一个",
        "image", "picture", "illustration", "draw",
    ]
    _AUDIO_KEYWORDS = [
        "朗读", "读出来", "读一下", "念出来", "语音",
        "转成语音", "合成语音", "tts", "speak", "read aloud",
        "用语音", "音频", "播放", "读给我", "说给我",
        "read it", "read this", "read out", "read the",
    ]

    def classify(self, user_message: str,
                 audio_uploaded: bool = False,
                 image_uploaded: bool = False) -> list[str]:
        """
        分类意图，返回按顺序排列的意图列表。

        例如："画一只猫，写首诗，朗读出来" → ["image", "text", "audio"]

        Args:
            audio_uploaded: 用户是否上传了音频（触发 STT 兜底）
            image_uploaded: 用户是否上传了图片（触发 image 兜底）
        """
        intents = []
        msg_lower = user_message.lower()

        # 显式关键词匹配
        has_image_kw = any(kw in msg_lower for kw in self._IMAGE_KEYWORDS)
        has_audio_kw = any(kw in msg_lower for kw in self._AUDIO_KEYWORDS)
        if has_image_kw:
            intents.append("image")
        if has_audio_kw:
            intents.append("audio")

        # text 是默认兜底意图（没有显式触发词但有内容）
        if audio_uploaded:
            # STT 场景：只用强文本指示词，避免"转写"里的"写"、"识读"等误判
            text_indicators = ["写诗", "写一首", "写个", "写一篇", "写代码",
                               "翻译", "分析", "总结", "解释", "代码",
                               "write", "translate", "analyze", "code"]
        else:
            text_indicators = ["写", "翻译", "分析", "总结", "解释", "代码", "查",
                               "写诗", "写一首", "写个", "写一篇",
                               "write", "translate", "analyze", "code"]
        has_text_kw = any(kw in msg_lower for kw in text_indicators)

        if has_text_kw:
            intents.insert(0, "text")
        elif not intents:
            # 无任何显式关键词 → 依据上传文件兜底
            if audio_uploaded:
                intents.append("audio")
            elif image_uploaded:
                intents.append("image")
            else:
                intents.append("text")

        # 上传文件强制对应意图（STT/图片分析）
        if audio_uploaded and "audio" not in intents:
            intents.append("audio")
        if image_uploaded and "image" not in intents:
            intents.append("image")

        # 纯文本兜底
        if not intents:
            intents = ["text"]

        logger.info(f"[L2:Intent] 意图分类: {intents}")
        return intents


# ═══════════════════════════════════════════════════════════════
# 任务拆分
# ═══════════════════════════════════════════════════════════════

class TaskSplitter:
    """
    任务粗分 + 依赖声明。

    将用户输入按意图拆分为独立子任务，并声明依赖关系。
    """

    def split(self, user_message: str, intents: list[str],
              entities: dict) -> list[SubTask]:
        """
        拆分任务并声明依赖。

        规则：
        - image 和 text 通常并行（无依赖）
        - audio 通常依赖 text（需要文本内容来朗读）
        - 最终文本汇总节点依赖所有上游
        """
        tasks = []
        task_counter = [0]

        def _next_id(prefix: str = "task") -> str:
            task_counter[0] += 1
            return f"{prefix}_{task_counter[0]}"

        # 按意图创建子任务
        text_task_id = None

        for intent in intents:
            if intent == "image":
                tasks.append(SubTask(
                    task_id=_next_id("img"),
                    task_type="image",
                    description="生成图片",
                    prompt=self._extract_image_part(user_message),
                    entities=entities,
                ))

            elif intent == "audio":
                # 区分 STT（用户上传音频）与 TTS（朗读文本）
                is_stt = bool(entities.get("_user_audio"))
                if is_stt:
                    # STT：转写用户上传的音频，不依赖其他任务
                    deps = []
                    description = "语音转文字"
                else:
                    # TTS：需要文本结果来朗读，依赖 text 任务
                    deps = [text_task_id] if text_task_id else []
                    description = "语音合成"
                tasks.append(SubTask(
                    task_id=_next_id("audio"),
                    task_type="audio",
                    description=description,
                    prompt=user_message,
                    depends_on=deps,
                    entities=entities,
                ))

            elif intent == "text":
                tid = _next_id("text")
                text_task_id = tid
                tasks.append(SubTask(
                    task_id=tid,
                    task_type="text",
                    description="文本处理",
                    prompt=self._extract_text_part(user_message),
                    entities=entities,
                ))

        logger.info(f"[L2:Split] 拆分为 {len(tasks)} 个子任务: "
                     f"{[(t.task_id, t.task_type, t.depends_on) for t in tasks]}")
        return tasks

    def _extract_image_part(self, user_message: str) -> str:
        """提取生图相关的部分。"""
        # 简单策略：找到"画"相关的句子
        for kw in ["画", "生成", "绘制", "generate"]:
            pos = user_message.find(kw)
            if pos != -1:
                # 向后取到下一个句子边界
                end = len(user_message)
                for sep in ["。", "，", "；", ".", ",", "然后", "并且", "and"]:
                    sep_pos = user_message.find(sep, pos)
                    if sep_pos != -1 and sep_pos < end:
                        end = sep_pos
                return user_message[pos:end].strip()
        return user_message

    def _extract_text_part(self, user_message: str) -> str:
        """提取文本处理相关的部分。"""
        # 去掉生图和语音相关的部分（注意不用单字"念"，避免误伤"概念/想念"等）
        text = user_message
        for kw in ["画", "生成图片", "朗读", "读出来", "念出来"]:
            pos = text.find(kw)
            if pos != -1:
                end = len(text)
                for sep in ["。", ".", "然后", "并且", "and"]:
                    sep_pos = text.find(sep, pos)
                    if sep_pos != -1:
                        end = sep_pos + 1
                text = text[:pos] + text[end:]
        return text.strip() or user_message


# ═══════════════════════════════════════════════════════════════
# 上下文重置检测
# ═══════════════════════════════════════════════════════════════

class ContextResetDetector:
    """
    检测是否需要重置上下文（语义突变）。

    触发规则（v2.0 定义的3条）：
    1. 任务类型变更 → 不重置（天然隔离）
    2. 同一工头内，用户主语完全改变 → 重置
    3. 用户明确说"重新来"/"换一个"/"不相关的" → 重置
    """

    _RESET_INDICATORS = [
        "重新来", "换个", "换一个", "不相关", "新的", "重来",
        "restart", "reset", "fresh start", "new topic",
    ]

    def __init__(self):
        self._last_subject: dict[str, str] = {}  # 工头类型 → 上次主题

    def should_reset(self, task_type: str, user_input: str) -> bool:
        """判断是否需要重置该类型工头的上下文。"""
        # 规则3：用户明确说重置
        input_lower = user_input.lower()
        if any(ind in input_lower for ind in self._RESET_INDICATORS):
            logger.info(f"[L2:Reset] [{task_type}] 检测到重置信号: {user_input[:50]}")
            return True

        # 规则2：同一工头内，主语完全改变
        if task_type in self._last_subject:
            last = self._last_subject[task_type]
            # 简单检测：核心主题词是否完全变化
            current_main = self._extract_main_subject(user_input)
            if current_main and last and current_main != last:
                logger.info(f"[L2:Reset] [{task_type}] 主题变更: {last} → {current_main}")
                # 不立即重置，除非主题变化极大
                # （这里保守策略：主题变→标记但不重置）

        # 更新记录
        self._last_subject[task_type] = self._extract_main_subject(user_input)

        return False

    def _extract_main_subject(self, text: str) -> str:
        """提取核心主题（前几个名词）。"""
        import re
        cn_chars = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
        return cn_chars[0] if cn_chars else text[:10]


# ═══════════════════════════════════════════════════════════════
# 中央调度器
# ═══════════════════════════════════════════════════════════════

class Supervisor:
    """
    中央调度层 —— 编排整个多智能体协作流程。

    v2.0 流程：
    1. 意图分类
    2. 任务粗分 + DAG 依赖声明
    3. 检索公共记忆 → 生成 Manifest
    4. 路由到第3层工头（按拓扑顺序下发）
    5. 依赖等待 + 结果汇总
    6. 超时/失败时返回部分结果
    """

    def __init__(self):
        self.classifier = IntentClassifier()
        self.splitter = TaskSplitter()
        self.reset_detector = ContextResetDetector()

        # 全局任务超时（按任务类型差异化）
        self._timeout_map = {
            "image": 120.0,
            "text": 30.0,
            "audio": 20.0,
            "default": 30.0,
        }

        # ── v2.0: 工头实例缓存（跨任务复用，保持工作区/策略缓存持久） ──
        self._foremen: dict[str, object] = {}

    # ── 主入口 ──

    async def orchestrate(
        self, layer1_output: dict, use_executor: bool = False,
        user_message: str | None = None,
        conversation_history: list | None = None,
    ) -> dict:
        """
        编排执行。

        Args:
            layer1_output: 第1层输出 {session_id, recent_dialogs, original_goal, entities}
            use_executor: v3 P3 起为 True 时走 v1 Executor 统一编排；
                默认 False 走旧手写循环（仅 process_v2 兼容，已标记退役）。
            user_message: 当前用户消息。重构修复（Bug 2）：优先使用它，
                取不到再回退 recent_dialogs（recent_dialogs 是剔除当前消息后的截断历史）。
            conversation_history: 多轮对话历史（Bug 6）。

        Returns:
            {
                "results": {task_id: data},
                "errors": {task_id: error},
                "total_time_ms": float,
                "partial": bool,   # 是否部分成功
            }
        """
        # 重构修复（Bug 2）：优先使用显式传入的当前消息；
        # 取不到（None/空）再回退到 recent_dialogs 里最后一条用户消息。
        # 修复前：首轮 recent_dialogs 为空字符串 → 意图分类得 ["text"] + 空 prompt 任务；
        # 多轮时取到的是上一轮的 user 消息。
        last_user_msg = (user_message or "").strip()
        if not last_user_msg:
            recent_dialogs = layer1_output.get("recent_dialogs", [])
            if isinstance(recent_dialogs, list):
                for msg in reversed(recent_dialogs):
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        last_user_msg = str(msg.get("content", ""))
                        break
            else:
                last_user_msg = str(recent_dialogs)

        original_goal = layer1_output.get("original_goal", last_user_msg)
        entities = layer1_output.get("entities", {})

        t_start = time.perf_counter()

        # 1. 意图分类（上传文件影响兜底逻辑）
        has_audio_upload = bool(entities.get("_user_audio"))
        has_image_upload = bool(entities.get("_user_image"))
        intents = self.classifier.classify(
            last_user_msg,
            audio_uploaded=has_audio_upload,
            image_uploaded=has_image_upload,
        )

        # 2. 任务粗分 + 依赖声明
        subtasks = self.splitter.split(last_user_msg, intents, entities)

        # 3. 检索公共记忆 + 生成 Manifest
        mem = get_public_memory()

        for task in subtasks:
            snapshot = mem.retrieve(
                task_type=task.task_type,
                keywords=entities.get("keywords", []),
                memory_types=[MemoryType.RESULT, MemoryType.EXPERIENCE],
                limit=5,
            )
            task.memory_manifest = mem.get_manifest(snapshot)

        # 4. 上下文重置检测（重构修复 Bug 3：should_reset 写入 SubTask，
        #    由 _route_to_foreman / DAG 透传到工头，不再丢弃）
        for task in subtasks:
            task.reset_context = self.reset_detector.should_reset(
                task.task_type, last_user_msg
            )

        # 重构修复（Bug 6）：对话历史注入所有子任务——
        # 旧手写循环路径经 _route_to_foreman → task.conversation_history 读取；
        # executor 路径额外由 _execute_via_executor 注入 _conversation_history。
        if conversation_history:
            for task in subtasks:
                task.conversation_history = conversation_history

        # 5. 拓扑排序 + 依赖下发 + 执行
        if use_executor:
            # v3 P3: 统一使用 v1 Executor（拓扑/重试/超时/死锁/取消/失败传播）
            results = await self._execute_via_executor(
                subtasks, entities, conversation_history
            )
        else:
            # [DEPRECATED] 旧手写循环（process_v2 兼容路径）
            results = await self._execute_with_dependencies(subtasks, last_user_msg)

        total_ms = (time.perf_counter() - t_start) * 1000

        # 6. 组装结果
        return {
            "results": {r.task_id: r.data for r in results if r.status == "success"},
            "errors": {r.task_id: r.error for r in results if r.status in ("error", "timeout")},
            "skipped": {r.task_id: r.status for r in results if r.status == "skipped"},
            "total_time_ms": total_ms,
            "partial": any(r.status != "success" for r in results),
            "intents": intents,
        }

    # ── 依赖编排执行 ──
    # v3 P3：官方路径统一走 v1 Executor（见 _execute_via_executor）；
    # 旧手写循环 _execute_with_dependencies 已标记退役，仅 process_v2 兼容。

    def _subtasks_to_dag(self, subtasks: list[SubTask], entities: dict | None = None) -> TaskDAG:
        """把 SubTask 列表转换为 TaskDAG（供 Executor 统一编排）。"""
        entities = entities or {}
        nodes = []
        for st in subtasks:
            if st.task_type == "image":
                ntype = NodeType.IMAGE_GEN
            elif st.task_type == "audio":
                # 重构修复（Bug 1）：sub_type 优先于"是否上传音频"推断节点类型
                if st.sub_type == "tts":
                    ntype = NodeType.TTS
                elif st.sub_type == "stt":
                    ntype = NodeType.STT
                else:
                    ntype = NodeType.STT if entities.get("_user_audio") else NodeType.TTS
            else:
                ntype = NodeType.LLM
            nodes.append(DAGNode(
                id=st.task_id,
                type=ntype,
                prompt=st.prompt,
                depends_on=st.depends_on,
                # 重构修复（Bug 3）：透传重置上下文信号到 DAG 节点
                reset_context=st.reset_context,
            ))
        return TaskDAG(task_id="subtasks_v3", description="规则拆分", nodes=nodes)

    async def _execute_via_executor(
        self, subtasks: list[SubTask], entities: dict | None = None,
        conversation_history: list | None = None,
    ) -> list[TaskResult]:
        """用 v1 Executor + Layer 3 工头路由执行子任务。

        v3 P3：官方统一编排路径（拓扑批次/重试/超时/死锁检测/取消传播/失败→SKIPPED）。
        """
        entities = entities or {}
        dag = self._subtasks_to_dag(subtasks, entities)

        context = {}
        if entities.get("_user_image"):
            context["_user_image"] = entities["_user_image"]
        if entities.get("_user_audio"):
            context["_user_audio"] = entities["_user_audio"]
        # 重构修复（Bug 6）：对齐 main.py 主路径，注入对话历史
        if conversation_history:
            context["_conversation_history"] = conversation_history

        registry = self._build_foreman_registry()
        exec_result = await execute_dag(
            dag, initial_context=context, registry=registry
        )

        # 转成统一 TaskResult 列表
        task_results: list[TaskResult] = []
        for n in dag.nodes:
            if n.id in exec_result.node_results:
                task_results.append(TaskResult(
                    task_id=n.id, status="success",
                    data=exec_result.node_results[n.id],
                    elapsed_ms=exec_result.timings.get(n.id, 0),
                ))
            elif n.status.value == "skipped":
                task_results.append(TaskResult(
                    task_id=n.id, status="skipped",
                    error={"code": "E400", "message": "dependency_failed"},
                ))
            elif n.id in exec_result.errors:
                task_results.append(TaskResult(
                    task_id=n.id, status="error",
                    error={"code": "E100", "message": str(exec_result.errors[n.id])[:500]},
                    elapsed_ms=exec_result.timings.get(n.id, 0),
                ))
            else:
                task_results.append(TaskResult(
                    task_id=n.id, status="error",
                    error={"code": "E000", "message": "unknown"},
                ))
        return task_results

    def _build_foreman_registry(self) -> dict:
        """DAG 节点类型 → Layer 3 工头执行函数（v3 P3）。

        与 main.py 的 AssistantEngine._build_foreman_registry 同构；
        VISION 未覆盖，回退 v1 `_AGENT_REGISTRY` 的 vision agent。
        """
        from ..orchestration.dag import NodeType

        def _make_runner(task_type: str):
            async def _run(node, prompt, context):
                entities = {}
                if context.get("_user_image"):
                    entities["_user_image"] = context["_user_image"]
                if context.get("_user_audio"):
                    entities["_user_audio"] = context["_user_audio"]
                # 重构修复（Bug 1）：按 DAG 节点类型派生音频子类型，
                # 避免 TTS/STT 都映射成 "audio" 丢失节点语义
                sub_type = None
                if node.type == NodeType.STT:
                    sub_type = "stt"
                elif node.type == NodeType.TTS:
                    sub_type = "tts"
                task = SubTask(
                    task_id=node.id,
                    task_type=task_type,
                    description=node.prompt[:80],
                    prompt=prompt,
                    depends_on=node.depends_on,
                    entities=entities,
                    # v3 修复：注入依赖节点输出 + 对话历史 + 单重试权威（H1/H2/H4）
                    upstream_results={
                        dep: str(context[dep]) for dep in node.depends_on
                        if context.get(dep) is not None
                    },
                    conversation_history=context.get("_conversation_history"),
                    executor_managed=True,
                    # 重构修复（Bug 1/3）：透传音频子类型与重置上下文信号
                    sub_type=sub_type,
                    reset_context=node.reset_context,
                )
                r = await self._route_to_foreman(task, prompt)
                if not isinstance(r, dict) or r.get("status") != "success":
                    err = r.get("error") or {} if isinstance(r, dict) else {}
                    msg = err.get("message", "工头执行失败") if isinstance(err, dict) else str(r)
                    raise RuntimeError(msg)
                return r.get("data")
            return _run

        return {
            NodeType.LLM: _make_runner("text"),
            NodeType.IMAGE_GEN: _make_runner("image"),
            NodeType.IMAGE_EDIT: _make_runner("image"),
            NodeType.TTS: _make_runner("audio"),
            NodeType.STT: _make_runner("audio"),
        }

    async def _execute_with_dependencies(
        self, subtasks: list[SubTask], user_message: str
    ) -> list[TaskResult]:
        """
        [DEPRECATED] 按依赖拓扑顺序执行子任务。

        v3 P3：主入口 `AssistantEngine.process()` 已改用 `orchestration/executor.py`
        （v1 Executor）统一编排（拓扑批次/重试/超时/死锁/取消传播/失败→SKIPPED）。
        本方法仅为 process_v2 兼容保留，新代码请使用 Executor + 工头路由。

        规则：
        - 无依赖的任务并行执行
        - 有依赖的任务等待上游完成后执行
        - 上游失败 → 下游标记为 skipped(dependency_failed)
        """
        logger.warning(
            "[DEPRECATED] Supervisor._execute_with_dependencies 已退役，"
            "请使用 orchestration.executor.execute_dag + 工头路由"
        )
        completed: dict[str, TaskResult] = {}
        pending: dict[str, SubTask] = {t.task_id: t for t in subtasks}
        all_results: list[TaskResult] = []
        subtask_by_id: dict[str, SubTask] = {t.task_id: t for t in subtasks}

        while pending:
            # 找可立即执行的任务（所有依赖已满足）
            ready = []
            for tid, task in list(pending.items()):
                deps_satisfied = True
                dep_failed = False
                for dep_id in task.depends_on:
                    if dep_id not in completed:
                        deps_satisfied = False
                        break
                    dep_result = completed[dep_id]
                    if dep_result.status in ("error", "timeout"):
                        dep_failed = True
                        break
                    # 依赖成功 → 将结果注入到当前任务
                    # （若上游是 text 类型任务，将其文本输出拼入下游 prompt）
                    dep_subtask = subtask_by_id.get(dep_id)
                    if (dep_result.data and dep_subtask
                            and dep_subtask.task_type == "text"):
                        task.prompt = (
                            f"{task.prompt}\n\n[上游文本输出] {str(dep_result.data)[:500]}"
                        )

                if dep_failed:
                    # 依赖失败 → 标记为 skipped
                    result = TaskResult(
                        task_id=tid,
                        status="skipped",
                        error={"code": "E400", "message": "dependency_failed"},
                    )
                    all_results.append(result)
                    completed[tid] = result
                    del pending[tid]
                    logger.warning(f"[L2:DAG] [{tid}] 因依赖失败而跳过")
                elif deps_satisfied:
                    ready.append((tid, task))

            if not ready:
                # 死锁检测：有 pending 但没有 ready
                if pending:
                    stuck = list(pending.keys())
                    logger.error(f"[L2:DAG] 死锁: {len(stuck)} 个任务无法调度: {stuck}")
                    for tid in stuck:
                        result = TaskResult(
                            task_id=tid,
                            status="error",
                            error={"code": "E000", "message": "DAG deadlock"},
                        )
                        all_results.append(result)
                        completed[tid] = result
                        del pending[tid]
                break

            # 并行执行所有就绪任务
            logger.info(f"[L2:DAG] 并行执行 {len(ready)} 个任务: {[t[0] for t in ready]}")
            batch_tasks = []
            for tid, task in ready:
                batch_tasks.append(self._execute_single_task(tid, task, user_message))
                del pending[tid]

            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

            for i, (tid, _) in enumerate(ready):
                r = batch_results[i]
                if isinstance(r, Exception):
                    result = TaskResult(
                        task_id=tid,
                        status="error",
                        error={"code": "E000", "message": str(r)},
                    )
                else:
                    result = r
                all_results.append(result)
                completed[tid] = result

        return all_results

    async def _execute_single_task(
        self, task_id: str, task: SubTask, user_message: str
    ) -> TaskResult:
        """执行单个子任务（路由到第3层工头）。"""
        t_start = time.perf_counter()
        timeout = self._timeout_map.get(task.task_type, self._timeout_map["default"])

        try:
            # 路由到对应工头
            result = await asyncio.wait_for(
                self._route_to_foreman(task, user_message),
                timeout=timeout,
            )

            elapsed = (time.perf_counter() - t_start) * 1000

            # 检查工头返回状态：工头可能返回 status="error"（内部已处理错误）
            if not isinstance(result, dict):
                return TaskResult(
                    task_id=task_id,
                    status="error",
                    error={"code": "E000", "message": f"工头返回异常: {result}"},
                    elapsed_ms=elapsed,
                )
            if result.get("status") != "success":
                err_info = result.get("error", {}) or {}
                return TaskResult(
                    task_id=task_id,
                    status="error",
                    error=err_info if isinstance(err_info, dict) else {"message": str(err_info)},
                    elapsed_ms=elapsed,
                )

            return TaskResult(
                task_id=task_id,
                status="success",
                data=result.get("data"),
                elapsed_ms=elapsed,
            )

        except asyncio.TimeoutError:
            elapsed = (time.perf_counter() - t_start) * 1000
            logger.warning(f"[L2] [{task_id}] 超时 ({timeout}s, {elapsed:.0f}ms)")
            return TaskResult(
                task_id=task_id,
                status="timeout",
                error={"code": "E200", "message": f"超时 ({timeout}s)"},
                elapsed_ms=elapsed,
            )

        except Exception as e:
            elapsed = (time.perf_counter() - t_start) * 1000
            logger.error(f"[L2] [{task_id}] 执行失败: {e}")
            return TaskResult(
                task_id=task_id,
                status="error",
                error={"code": "E000", "message": str(e)[:500]},
                elapsed_ms=elapsed,
            )

    async def _route_to_foreman(self, task: SubTask, user_message: str) -> dict:
        """路由任务到对应的第3层工头。

        工头实例在 Supervisor 内缓存复用（跨任务保持工作区/策略缓存）。
        """
        # 提取用户上传文件（存于 entities，映射到任务包顶层）
        entities = task.entities or {}
        user_image = entities.get("_user_image") or ""
        user_audio = entities.get("_user_audio") or ""

        # 构建第3层任务包
        task_package = {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "user_input": task.prompt or user_message,
            "entities": entities,
            # 重构修复（Bug 3）：透传重置上下文信号，替换硬编码 False
            "reset_context": getattr(task, "reset_context", False),
            "memory_manifest": task.memory_manifest,
            "depends_on": task.depends_on,
            # v3 修复：executor 路径注入上下文（H1/H2） + 单重试权威（H4）
            "upstream_results": getattr(task, "upstream_results", {}) or {},
            "conversation_history": getattr(task, "conversation_history", None),
            "no_retry": getattr(task, "executor_managed", False),
        }
        # 用户上传文件映射到顶层字段（供 STT/生图等工头使用）
        if user_image:
            task_package["image_path"] = user_image
        if user_audio:
            task_package["audio_path"] = user_audio
        # 重构修复（Bug 1）：sub_type 以 DAG 节点类型派生的 task.sub_type 为权威，
        # 仅当缺失且存在用户上传音频时才兜底推断 "stt"。
        # 修复前：audio 任务的 sub_type 由"本请求是否上传了用户音频"决定，
        # 导致 TTS 节点被误标为 stt（再次转写）、未上传音频时 STT 节点落入 TTS 分支。
        sub_type = getattr(task, "sub_type", None) or None
        if not sub_type and user_audio:
            sub_type = "stt"
        if sub_type:
            task_package["sub_type"] = sub_type

        # 路由到工头（复用缓存的实例）
        foreman = self._get_foreman(task.task_type)
        logger.info(f"[L2:Route] [{task.task_id}] → {foreman.foreman_type}")
        return await foreman.execute(task_package)

    def _get_foreman(self, task_type: str):
        """获取（或创建）对应类型的工头实例。跨任务复用。"""
        if task_type in self._foremen:
            return self._foremen[task_type]

        if task_type == "text":
            from ..layer3.llm_foreman import LLMForeman
            foreman = LLMForeman()
        elif task_type == "image":
            from ..layer3.image_foreman import ImageForeman
            foreman = ImageForeman()
        elif task_type == "audio":
            from ..layer3.speech_foreman import SpeechForeman
            foreman = SpeechForeman()
        else:
            raise ValueError(f"未知任务类型: {task_type}")

        self._foremen[task_type] = foreman
        return foreman
