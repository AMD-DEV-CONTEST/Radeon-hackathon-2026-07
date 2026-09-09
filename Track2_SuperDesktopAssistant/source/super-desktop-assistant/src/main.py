"""
🧠 Super Desktop Assistant —— 主控引擎

核心流程：
1. 用户输入 → 规划Agent 生成 DAG
2. Planner 清空公共记忆 → Allocator 初始化任务 + 注册 Agent + 分配 prompt
3. DAG 执行器并行调度各执行 Agent（Agent 通过 get_shared_memory 获取上下文）
4. 聚合结果返回
"""
import asyncio
from pathlib import Path
from loguru import logger

from .orchestration.dag import TaskDAG, NodeStatus, NodeType
from .orchestration.executor import execute_dag, ExecutionResult

# 确保 Agent 已注册（v3 主流程走工头路由，VISION 等节点在 v1 _AGENT_REGISTRY 兜底）
from .agents import (  # noqa: F401
    llm_agent,
    vision,
    speech,
    image_gen,
)


class AssistantEngine:
    """超级桌面助理引擎。"""

    def __init__(self):
        from .config import get_config
        self.output_dir = Path(get_config().settings.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def process(
        self,
        user_message: str,
        image_path: str | None = None,
        audio_path: str | None = None,
        video_path: str | None = None,
        conversation_history: list[dict] | None = None,
        session_id: str = "",
    ) -> dict:
        """
        v3 统一入口：Layer 1 → Layer 2(Planner) → Layer 3(工头路由) → Layer 4。

        融合 v1 LLM DAG 规划能力 + v2.0 四层架构：
        - Layer 1: 用户交互（截断摘要 / 实体提取 / 注入过滤）
        - Layer 2: LLM Planner 生成 DAG（失败回退规则拆分）+ Executor 编排
        - Layer 3: 按 DAG 节点类型路由到领域工头
        - Layer 4: MCP 契约（差异化超时 / 错误分类）

        返回格式统一兼容 v1 UI（dag / plan_summary / results / errors / skipped / outputs）。
        """
        from .layer1 import UserAgent
        from .layer2 import Supervisor
        from .memory.public_memory import reset_public_memory
        from .config import get_config as _get_cfg

        logger.info(f"[v3 REQ] {user_message[:100]}...")

        # Step 0: 初始化公共记忆（每次任务独立）
        reset_public_memory()

        # ── Layer 1: 用户交互层 ──
        s = _get_cfg().settings
        user_agent = UserAgent(
            max_turns=s.max_context_turns,
            max_summary_chars=s.truncation_summary_chars,
        )
        l1_output = user_agent.process(
            user_message=user_message,
            conversation_history=conversation_history,
            session_id=session_id,
        )

        # v3 P6b: 配置指令由 Layer 1 直接处理，不进入多 Agent 编排
        if l1_output.get("config_handled"):
            logger.info(f"[v3] 配置指令已由 Layer 1 处理，不进入编排: {l1_output.get('reply')}")
            return {
                "version": "3.0",
                "status": "ok",
                "config_reply": l1_output.get("reply", ""),
                "results": {},
                "errors": {},
                "skipped": {},
                "total_time_ms": 0,
                "outputs": {"images": [], "audio": []},
            }

        if image_path:
            l1_output["entities"]["_user_image"] = image_path
        if audio_path:
            l1_output["entities"]["_user_audio"] = audio_path
        if video_path:
            l1_output["entities"]["_user_video"] = video_path

        # ── Layer 2: 规划（LLM DAG + 规则拆分兜底） ──
        supervisor = Supervisor()
        try:
            dag, _used_fallback = await self._build_dag(
                user_message, image_path, audio_path, video_path, conversation_history, l1_output
            )
        except ValueError as e:
            # H6/M1：配置类错误返回结构化 error（UI/CLI 依赖顶层 "error" 键）
            logger.error(f"[v3] 规划阶段配置错误: {e}")
            return self._error_response(_format_plan_error(e))
        except Exception as e:
            logger.error(f"[v3] 规划阶段异常: {e}")
            return self._error_response(f"规划阶段异常: {_format_plan_error(e)}")

        # v3: 初始化任务内共享记忆（供工具 get_shared_memory 使用）。
        # asyncio.to_thread 会复制当前 context，工具回调能读到本实例。
        from .memory.task_memory import reset_shared_memory
        mem = reset_shared_memory()
        mem.init_task(
            task_id=dag.task_id,
            description=dag.description,
            user_input=user_message,
        )
        for node in dag.nodes:
            mem.register_agent(node.id, node.type.value)

        # M5/I3 修复：执行前强制 LLM 节点并发上限（max_llm_agents）。
        # register_agent 的返回曾被忽略，上限形同虚设——planner 可发射任意多 LLM 节点全并发。
        from .config import get_config as _cap_cfg
        _max_llm = _cap_cfg().settings.max_llm_agents
        _llm_seen = 0
        for node in dag.nodes:
            if node.type == NodeType.LLM:
                _llm_seen += 1
                if _llm_seen > _max_llm:
                    node.status = NodeStatus.SKIPPED
                    logger.warning(
                        f"[v3] LLM 节点数超上限 {_max_llm}，{node.id} 标记跳过（不执行）"
                    )

        # ── Executor 执行（工头路由） ──
        context = {}
        if image_path:
            context["_user_image"] = image_path
        if audio_path:
            context["_user_audio"] = audio_path
        if video_path:
            context["_user_video"] = video_path
        if conversation_history:
            context["_conversation_history"] = conversation_history

        try:
            result: ExecutionResult = await execute_dag(
                dag,
                initial_context=context,
                registry=self._build_foreman_registry(supervisor),
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[v3] 执行阶段异常: {e}")
            return self._error_response(f"执行阶段异常: {_format_plan_error(e)}")

        # ── 聚合统一返回格式 ──
        errors = result.errors or {}
        results = {nid: str(v) for nid, v in result.node_results.items()}
        skipped_ids = [n.id for n in dag.nodes if n.status.value == "skipped"]

        status = "ok"
        if errors and not results:
            status = "error"
        elif errors or skipped_ids:
            status = "partial"

        ret = {
            "version": "3.0",
            "status": status,
            "dag": dag.to_dict(),
            "plan_summary": dag.summary(),
            "results": results,
            "errors": errors,
            "skipped": {nid: "skipped" for nid in skipped_ids},
            "total_time_ms": result.total_time_ms,
            "timings": result.timings,  # 节点级耗时（供 UI/CLI 展示）
            "outputs": self._collect_outputs(result),
        }
        # H6：status=error 时补顶层 error 键（UI/CLI 用 `if "error" in r` 判断）
        if status == "error":
            ret["error"] = next(iter(errors.values()), "任务执行失败")
        return ret

    def _error_response(self, message: str) -> dict:
        """配置/阶段错误的结构化返回（与 process() 正常返回格式对齐）。"""
        return {
            "version": "3.0",
            "status": "error",
            "error": message,
            "dag": {},
            "plan_summary": "",
            "results": {},
            "errors": {"__global__": message},
            "skipped": {},
            "total_time_ms": 0,
            "timings": {},
            "outputs": {"images": [], "audio": []},
        }

    # ═══════════════════════════════════════════════════════════
    # v3: 规划与工头路由
    # ═══════════════════════════════════════════════════════════

    async def _build_dag(
        self, user_message, image_path, audio_path, video_path, conversation_history, l1_output
    ) -> tuple[TaskDAG, bool]:
        """LLM Planner 生成 DAG；失败/超时时回退到 v2.0 规则拆分。

        Returns:
            (TaskDAG, used_fallback: bool)
        """
        from .agents.planner import plan, parse_and_validate
        from .orchestration.dag import DAGNode, NodeType
        from .layer2.supervisor import IntentClassifier, TaskSplitter

        try:
            dag_json = await plan(
                user_message,
                has_image=image_path is not None,
                has_audio=audio_path is not None,
                has_video=video_path is not None,
                conversation_history=conversation_history,
            )
            validated = parse_and_validate(dag_json)
            if "error" not in validated:
                dag = TaskDAG.from_dict(validated)
                logger.info(f"[v3] LLM 规划成功: {dag.description} ({len(dag.nodes)} nodes)")
                return dag, False
            logger.warning(f"[v3] LLM 规划校验失败，回退规则拆分: {validated['error']}")
        except ValueError as e:
            # M1 修复：配置类错误（LLM 未分配/供应商缺失）不能静默回退到规则拆分——
            # 否则会用错误的规则拆分掩盖真实配置问题，且 UI 拿不到友好提示。
            logger.error(f"[v3] 规划阶段配置错误: {e}")
            raise
        except Exception as e:
            from .api.errors import is_permanent_error
            if is_permanent_error(str(e)):
                # 永久性 API 错误（401 鉴权/配额/模型不存在）同样不回退——
                # 回退只会用同一把坏 key 重试，最终给出一堆节点级报错而不是友好提示。
                logger.error(f"[v3] 规划阶段永久性 API 错误（不回退）: {e}")
                raise
            logger.warning(f"[v3] LLM 规划异常，回退规则拆分: {e}")

        # 回退：v2.0 意图分类 + 任务拆分
        entities = l1_output.get("entities", {})
        intents = IntentClassifier().classify(
            user_message,
            audio_uploaded=bool(entities.get("_user_audio")),
            image_uploaded=bool(entities.get("_user_image")),
        )
        subtasks = TaskSplitter().split(user_message, intents, entities)

        nodes = []
        for st in subtasks:
            if st.task_type == "image":
                ntype = NodeType.IMAGE_GEN
            elif st.task_type == "audio":
                ntype = NodeType.STT if entities.get("_user_audio") else NodeType.TTS
            else:
                ntype = NodeType.LLM
            nodes.append(DAGNode(
                id=st.task_id,
                type=ntype,
                prompt=st.prompt,
                depends_on=st.depends_on,
            ))

        # 回退兜底：用户上传了视频 → 追加 VISION 节点（v1 vision agent 处理媒体文件）
        if video_path:
            nodes.append(DAGNode(
                id="video_1",
                type=NodeType.VISION,
                prompt=f"分析用户上传的视频：{user_message}",
                depends_on=[],
            ))

        dag = TaskDAG(task_id="fallback_v2", description="规则拆分", nodes=nodes)
        logger.info(f"[v3] 回退规则拆分: {len(nodes)} nodes")
        return dag, True

    def _build_foreman_registry(self, supervisor) -> dict:
        """构建 DAG 节点类型 → Layer 3 工头执行函数的映射。

        VISION 未覆盖，回退到 v1 `_AGENT_REGISTRY` 的 vision agent。
        """
        from .orchestration.dag import NodeType
        from .layer2.supervisor import SubTask

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
                r = await supervisor._route_to_foreman(task, prompt)
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

    # ═══════════════════════════════════════════════════════════
    # v2.0: 四层架构流程
    # ═══════════════════════════════════════════════════════════

    async def process_v2(
        self,
        user_message: str,
        image_path: str | None = None,
        audio_path: str | None = None,
        conversation_history: list[dict] | None = None,
        session_id: str = "",
    ) -> dict:
        """
        v2.0 四层架构流程：Layer 1 → Layer 2 → Layer 3 → Layer 4

        Layer 1: 对话截断 + 实体提取 + 安全过滤
        Layer 2: 意图分类 + 任务粗分 + DAG 依赖声明 + 路由
        Layer 3: 工头执行（LLM/Image/Speech Foreman）
        Layer 4: MCP 原子 Worker（v1 已有，v2 增强错误契约）
        """
        from .layer1 import UserAgent
        from .layer2 import Supervisor
        from .layer4.mcp_contract import ErrorCode
        from .memory.public_memory import reset_public_memory, get_public_memory
        from .config import get_config as _get_cfg

        logger.info(f"[v2.0 REQ] {user_message[:100]}...")

        # Step 0: 初始化公共记忆
        mem = reset_public_memory()

        # ── Layer 1: 用户交互层 ──
        logger.info("[L1] 用户交互层处理...")
        s = _get_cfg().settings
        user_agent = UserAgent(
            max_turns=s.max_context_turns,
            max_summary_chars=s.truncation_summary_chars,
        )
        l1_output = user_agent.process(
            user_message=user_message,
            conversation_history=conversation_history,
            session_id=session_id,
        )

        # 注入用户文件到 l1 输出
        if image_path:
            l1_output["entities"]["_user_image"] = image_path
        if audio_path:
            l1_output["entities"]["_user_audio"] = audio_path

        logger.info(f"[L1] turns={len(l1_output.get('recent_dialogs', []))}, "
                     f"keywords={l1_output.get('entities', {}).get('keywords', [])}")

        # ── Layer 2: 中央调度层 ──
        logger.info("[L2] 中央调度层编排...")
        supervisor = Supervisor()
        # 重构修复（Bug 2/6）：显式传入当前用户消息与对话历史，
        # 修复 orchestrate 从 recent_dialogs 取上一轮/空消息的问题
        l2_result = await supervisor.orchestrate(
            l1_output,
            user_message=user_message,
            conversation_history=conversation_history,
        )

        total_ms = l2_result.get("total_time_ms", 0)
        results = l2_result.get("results", {})
        errors = l2_result.get("errors", {})
        skipped = l2_result.get("skipped", {})

        # ── 收集文件输出 ──
        images = []
        audio_files = []
        for val in results.values():
            if isinstance(val, str):
                from pathlib import Path
                ext = Path(val).suffix.lower()
                try:
                    exists = Path(val).exists()
                except OSError:
                    continue
                if exists:
                    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                        images.append(val)
                    elif ext in (".mp3", ".wav", ".ogg", ".m4a"):
                        audio_files.append(val)

        # ── 组装 v2.0 结果 ──
        status = "ok"
        if errors and not results:
            status = "error"
        elif errors or skipped:
            status = "partial"

        return {
            "version": "2.0",
            "status": status,
            "intents": l2_result.get("intents", []),
            "results": results,
            "errors": errors,
            "skipped": skipped,
            "total_time_ms": total_ms,
            "outputs": {"images": images, "audio": audio_files},
        }

    def _collect_outputs(self, result: ExecutionResult) -> dict:
        """收集生成的文件。"""
        images = []
        audio_files = []
        for node_id, val in result.node_results.items():
            if not isinstance(val, str):
                logger.debug(f"[OUT] [{node_id}] 跳过非字符串结果: {type(val).__name__}")
                continue
            # 只检查看起来像文件路径的结果（有已知媒体扩展名）
            ext = Path(val).suffix.lower()
            if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif",
                           ".mp3", ".wav", ".ogg", ".m4a"):
                continue
            try:
                exists = Path(val).exists()
            except OSError:
                logger.debug(f"[OUT] [{node_id}] 路径包含非法字符，跳过: {val[:60]}")
                continue
            if exists:
                if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                    images.append(val)
                elif ext in (".mp3", ".wav", ".ogg", ".m4a"):
                    audio_files.append(val)
            else:
                logger.warning(f"[OUT] [{node_id}] 文件路径指向不存在的文件: {val}")
        return {"images": images, "audio": audio_files}


def _format_plan_error(e: Exception) -> str:
    """将规划阶段的异常转化为用户友好的错误信息。"""
    from .api.errors import (
        AUTH_KEYWORDS, QUOTA_KEYWORDS, MODEL_KEYWORDS,
        RATE_LIMIT_KEYWORDS, TIMEOUT_KEYWORDS,
        NETWORK_KEYWORDS, SERVER_ERROR_KEYWORDS,
    )
    msg = str(e).lower()
    original = str(e)

    # 配置错误（来自 config 解析层，中文错误信息）
    if "供应商" in original and "不存在" in original:
        return f"配置错误: {original}"
    if "模型" in original and ("不存在" in original or "未分配" in original):
        return f"配置错误: {original}"
    if any(k in original for k in ("未分配", "未配置")):
        return original

    # 模型不存在（优先检测，避免被 invalid 误判为 API Key 错误）
    if "model" in msg and any(k in msg for k in MODEL_KEYWORDS):
        return "配置的模型不存在，请检查 config.json 中的模型名称。"
    # 鉴权错误
    if any(k in msg for k in AUTH_KEYWORDS):
        return "API Key 无效或未配置，请在 .env 文件中填入正确的 API Key。"
    # 余额不足
    if any(k in msg for k in QUOTA_KEYWORDS):
        return "API 余额不足或配额已用尽，请充值后重试。"
    # 频率限制
    if any(k in msg for k in RATE_LIMIT_KEYWORDS):
        return "API 调用频率过高，请稍后重试。"
    # 超时
    if any(k in msg for k in TIMEOUT_KEYWORDS):
        return "API 请求超时，请检查网络连接后重试。"
    # 网络连接
    if any(k in msg for k in NETWORK_KEYWORDS):
        return "无法连接到 API 服务器，请检查网络和代理设置。"
    # 服务端错误 (5xx)
    if any(k in msg for k in SERVER_ERROR_KEYWORDS):
        return "API 服务器暂时故障，请稍后重试。"
    return f"AI 服务调用失败: {original[:200]}"


# 单例
import threading

_engine: AssistantEngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> AssistantEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = AssistantEngine()
    return _engine
