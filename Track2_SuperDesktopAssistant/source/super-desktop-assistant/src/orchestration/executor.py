"""
DAG 并行执行器（v2.0 增强）。

v2.0 增强：
- 按节点类型差异化超时（image 120s / llm 30s / tts 20s / stt 15s）
- 增强错误处理：使用 Layer 4 MCP 错误契约
- 依赖失败传播：上游 FAILED → 下游 SKIPPED
- reset_context 信号处理

按拓扑序遍历 DAG，依赖满足的节点并发执行（通过 asyncio.gather）。
支持超时、重试、降级、运行时 prompt 调整。
"""
import asyncio
import time
from collections.abc import Callable as CallableType, Awaitable
from loguru import logger
from .dag import TaskDAG, DAGNode, NodeStatus, NodeType

# ── v2.0: 按节点类型的默认超时映射 ──
# v3 P1/P8: LLM 节点接入工具链（chat_with_tools 最多 8 轮）。
# 实测 mimo 单轮工具调用可达 10-30s，8 轮可能超 120s，故给足 240s。
_DEFAULT_TIMEOUT_BY_TYPE: dict[NodeType, float] = {
    NodeType.IMAGE_GEN: 120.0,
    NodeType.IMAGE_EDIT: 120.0,
    NodeType.LLM: 240.0,
    NodeType.VISION: 30.0,
    NodeType.TTS: 20.0,
    NodeType.STT: 15.0,
}


def _timeout_from_config(node_type: NodeType) -> float | None:
    """读取 config 中按类型的超时（L2 修复：此前配置项是死配置，被硬编码覆盖）。

    映射：image_gen/image_edit→timeout_image，llm/vision→timeout_text，tts/stt→timeout_audio。
    未配置/解析失败返回 None（由调用方用硬编码默认兜底）。
    """
    try:
        from ..config import get_config
        s = get_config().settings
        m = {
            NodeType.IMAGE_GEN: s.timeout_image,
            NodeType.IMAGE_EDIT: s.timeout_image,
            NodeType.LLM: s.timeout_text,
            NodeType.VISION: s.timeout_text,
            NodeType.TTS: s.timeout_audio,
            NodeType.STT: s.timeout_audio,
        }
        return m.get(node_type)
    except Exception:
        return None


# 运行时 prompt 调整回调类型
# (node, task_description, upstream_results) -> adjusted_prompt
RuntimeAllocator = CallableType[[DAGNode, str, dict[str, str]], Awaitable[str]]


class ExecutionResult:
    """执行结果聚合。"""

    def __init__(self):
        self.node_results: dict[str, object] = {}
        self.errors: dict[str, str] = {}
        self.timings: dict[str, float] = {}
        self.total_time_ms: float = 0

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def get(self, node_id: str, default=None):
        return self.node_results.get(node_id, default)


# Agent 执行函数注册表
_AGENT_REGISTRY: dict[NodeType, CallableType] = {}


def register_agent(node_type: NodeType):
    """装饰器：注册执行函数到对应节点类型。"""
    def decorator(func):
        _AGENT_REGISTRY[node_type] = func
        return func
    return decorator


async def execute_node(
    node: DAGNode,
    dag: TaskDAG,
    context: dict[str, object],
    runtime_allocator: RuntimeAllocator | None = None,
    registry: dict[NodeType, CallableType] | None = None,
) -> object:
    """执行单个节点，自动注入依赖节点的上下文。

    Args:
        registry: 可选，节点类型 → 执行函数的覆盖映射。
            未覆盖的类型回退到全局 _AGENT_REGISTRY（v1 Agent 注册表）。
            v3 P2/P3：由 Layer 3 工头路由注册表传入。
    """
    active_registry = registry if registry is not None else _AGENT_REGISTRY
    func = active_registry.get(node.type)
    if func is None:
        func = _AGENT_REGISTRY.get(node.type)
    if func is None:
        raise ValueError(f"未注册的节点类型: {node.type}")

    # 解析上下文变量引用（如 ${vision_1.output}）
    resolved_prompt = node.prompt
    for var_name, var_ref in node.context_vars.items():
        ref = var_ref.strip("${}")
        ref_node_id = ref.split(".")[0]
        ref_value = context.get(ref_node_id)
        if ref_value is not None:
            resolved_prompt = resolved_prompt.replace(
                f"${{{ref}}}", str(ref_value)
            )

    # === 运行时 prompt 调整 ===
    # 由 runtime_allocator 回调统一处理；以下节点类型跳过调整：
    # - image_gen/image_edit: 静态 Allocator 已优化，运行时调整会破坏视觉描述
    # - 无依赖的根节点: 没有上游结果可参考
    _SKIP_RUNTIME_ALLOC = frozenset(("image_gen", "image_edit"))
    if runtime_allocator and node.depends_on and node.type.value not in _SKIP_RUNTIME_ALLOC:
        upstream = {}
        for dep_id in node.depends_on:
            dep_val = context.get(dep_id)
            if dep_val is not None:
                upstream[dep_id] = str(dep_val)
        if upstream:
            try:
                adjusted = await runtime_allocator(
                    node, dag.description, upstream
                )
                if adjusted and adjusted != resolved_prompt:
                    # [CLEAR_CONTEXT] 标记：Allocator 判定需要全新任务，先清空旧上下文
                    if adjusted.startswith("[CLEAR_CONTEXT]"):
                        adjusted = adjusted[len("[CLEAR_CONTEXT]"):].strip()
                        try:
                            from ..agents.shared_memory import get_shared_memory
                            get_shared_memory().clear_agent_context(node.id)
                            logger.info(f"[ALLOC-RT] [{node.id}] 上下文已清空（全新任务）")
                        except Exception:
                            pass
                    logger.info(f"[ALLOC-RT] [{node.id}] prompt 实时调整: "
                                f"{len(resolved_prompt)}→{len(adjusted)} chars")
                    resolved_prompt = adjusted
            except Exception as e:
                logger.warning(f"[ALLOC-RT] [{node.id}] 调整失败: {e}")

    logger.info(f"[TRACE-EXEC] [{node.id}] type={node.type.value} prompt({len(resolved_prompt)}c): {resolved_prompt[:300]}")
    return await func(node=node, prompt=resolved_prompt, context=context)


async def execute_dag(
    dag: TaskDAG,
    timeout_per_node: float | None = None,
    max_retries: int | None = None,
    initial_context: dict[str, object] | None = None,
    runtime_allocator: RuntimeAllocator | None = None,
    registry: dict[NodeType, CallableType] | None = None,
) -> ExecutionResult:
    """
    并行执行整个 DAG。

    每轮：收集依赖已满足的节点 → 实时调整 prompt → asyncio.gather 并发执行 → 下一轮。

    Args:
        runtime_allocator: 可选，运行时 prompt 调整回调。
            在每个有依赖的节点执行前调用，观察上游输出来优化 prompt。
        registry: 可选，节点类型 → 执行函数映射。v3 由 Layer 3 工头路由提供。
    """
    result = ExecutionResult()
    context: dict[str, object] = dict(initial_context or {})
    retry_count: dict[str, int] = {}
    t_start = time.perf_counter()

    # 从 config 读取默认值（调用方可覆盖）
    if timeout_per_node is None or max_retries is None:
        try:
            from ..config import get_config
            s = get_config().settings
            if timeout_per_node is None:
                timeout_per_node = s.timeout_per_node
            if max_retries is None:
                max_retries = s.max_retries
        except Exception:
            if timeout_per_node is None:
                timeout_per_node = 120.0
            if max_retries is None:
                max_retries = 1

    node_index = {n.id: n for n in dag.nodes}

    if runtime_allocator:
        logger.info(f"[EXEC] {dag.description} ({len(dag.nodes)} nodes) [runtime-alloc enabled]")
    else:
        logger.info(f"[EXEC] {dag.description} ({len(dag.nodes)} nodes)")

    while not dag.all_done():
        ready = dag.get_ready_nodes()

        if not ready:
            if dag.any_failed():
                # 递归标记：依赖 FAILED 或 SKIPPED 节点的都标为 SKIPPED
                # 单次循环只标记直接子节点，多轮迭代完成传递性传播
                skipped_any = False
                for node in dag.nodes:
                    if node.status == NodeStatus.PENDING:
                        if any(
                            node_index.get(dep)
                            and node_index[dep].status in (NodeStatus.FAILED, NodeStatus.SKIPPED)
                            for dep in node.depends_on
                        ):
                            node.status = NodeStatus.SKIPPED
                            logger.warning(f"[EXEC] [{node.id}] 因前置失败而跳过")
                            skipped_any = True
                if not skipped_any:
                    pending = [n.id for n in dag.nodes if n.status == NodeStatus.PENDING]
                    if pending:
                        logger.error(
                            f"[EXEC] DAG 死锁：{len(pending)} 个节点无法调度: {pending}"
                        )
                        # 将所有悬挂节点标记为失败，防止静默部分完成
                        for node in dag.nodes:
                            if node.status == NodeStatus.PENDING:
                                node.status = NodeStatus.FAILED
                                node.error = "DAG deadlock: unsatisfiable dependencies"
                                result.errors[node.id] = node.error
                    # 所有节点已是终端状态(DONE/SKIPPED/FAILED)，正常退出
                    break
                continue
            else:
                pending = [n.id for n in dag.nodes if n.status == NodeStatus.PENDING]
                logger.error(f"[EXEC] DAG 死锁：{len(pending)} 个节点无法调度: {pending}")
                for node in dag.nodes:
                    if node.status == NodeStatus.PENDING:
                        node.status = NodeStatus.FAILED
                        node.error = "DAG deadlock: no ready nodes, no failures"
                        result.errors[node.id] = node.error
                break

        logger.debug(f"[EXEC] 批次: {[n.id for n in ready]}")

        # 并发执行本批次
        tasks = []
        for node in ready:
            node.status = NodeStatus.RUNNING
            t_node = time.perf_counter()
            tasks.append(
                _run_node_with_retry(
                    node, dag, context, result, retry_count,
                    t_node, timeout_per_node, max_retries,
                    runtime_allocator=runtime_allocator,
                    registry=registry,
                )
            )

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            result.total_time_ms = (time.perf_counter() - t_start) * 1000
            # 标记所有运行中/待处理节点为已取消
            for node in dag.nodes:
                if node.status in (NodeStatus.RUNNING, NodeStatus.PENDING):
                    node.status = NodeStatus.FAILED
                    node.error = "DAG 执行被取消"
                    if node.id not in result.errors:
                        result.errors[node.id] = "DAG 执行被取消"
            logger.warning(f"[EXEC] DAG 被取消 ({result.total_time_ms:.0f}ms) — "
                          f"{len(result.errors)} 个节点未完成")
            raise

    result.total_time_ms = (time.perf_counter() - t_start) * 1000
    status = "[OK]" if result.success else "[WARN]"
    logger.info(f"{status} DAG 完成 ({result.total_time_ms:.0f}ms)")
    return result


async def _run_node_with_retry(
    node: DAGNode,
    dag: TaskDAG,
    context: dict,
    result: ExecutionResult,
    retry_count: dict,
    t_start: float,
    timeout: float,
    max_retries: int,
    runtime_allocator: RuntimeAllocator | None = None,
    registry: dict[NodeType, CallableType] | None = None,
):
    node_id = node.id
    retry_count.setdefault(node_id, 0)

    # ── v2.0: 按节点类型差异化超时 ──
    # L2 修复：优先级 timeout_override > config 类型超时 > 硬编码兜底。
    # 此前硬编码 _DEFAULT_TIMEOUT_BY_TYPE 无条件覆盖 config，改配置无效。
    effective_timeout = timeout
    if node.timeout_override is not None:
        effective_timeout = node.timeout_override
    elif node.type in _DEFAULT_TIMEOUT_BY_TYPE:
        effective_timeout = (
            _timeout_from_config(node.type) or _DEFAULT_TIMEOUT_BY_TYPE[node.type]
        )

    # ── v2.0: 上下文重置 ──
    if node.reset_context:
        try:
            from ..agents.shared_memory import get_shared_memory
            get_shared_memory().clear_agent_context(node.id)
            logger.info(f"[EXEC] [{node_id}] reset_context → 上下文已清空")
        except Exception:
            pass

    while retry_count[node_id] <= max_retries:
        try:
            node_result = await asyncio.wait_for(
                execute_node(node, dag, context,
                            runtime_allocator=runtime_allocator,
                            registry=registry),
                timeout=effective_timeout,
            )
            node.status = NodeStatus.DONE
            node.result = node_result
            context[node_id] = node_result
            result.node_results[node_id] = node_result
            elapsed = (time.perf_counter() - t_start) * 1000
            result.timings[node_id] = elapsed
            logger.info(f"  [OK] [{node_id}] {node.type.value} ({elapsed:.0f}ms)")
            return

        except asyncio.CancelledError:
            node.status = NodeStatus.FAILED
            node.error = "任务被取消"
            result.errors[node_id] = "任务被取消"
            logger.warning(f"  [CANCEL] [{node_id}]")
            raise  # 传播取消信号

        except asyncio.TimeoutError:
            retry_count[node_id] += 1
            if retry_count[node_id] > max_retries:
                _fail_node(node, result, f"超时 ({effective_timeout}s, type={node.type.value})", t_start)
                return
            delay = 0.5 * (2 ** (retry_count[node_id] - 1))  # 指数退避
            logger.warning(f"  [TIMEOUT] [{node_id}] 重试 {retry_count[node_id]}/{max_retries} ({delay:.1f}s 后)")
            await asyncio.sleep(delay)

        except Exception as e:
            retry_count[node_id] += 1
            # ── v2.0: 使用增强错误分类 ──
            from ..layer4.mcp_contract import ErrorCode, mcp_error_factory
            mcp_err = mcp_error_factory(e, node_id=node.id)

            # 永久错误不重试
            if not mcp_err.retryable:
                _fail_node(node, result, f"[{mcp_err.code}] {mcp_err.message} → {mcp_err.suggested_action}", t_start)
                return
            if retry_count[node_id] > max_retries:
                _fail_node(node, result, f"[{mcp_err.code}] {mcp_err.message}", t_start)
                return
            delay = 0.5 * (2 ** (retry_count[node_id] - 1))
            logger.warning(f"  [RETRY] [{node_id}] [{mcp_err.code}] {e}, "
                           f"重试 {retry_count[node_id]}/{max_retries} ({delay:.1f}s 后)")
            await asyncio.sleep(delay)


def _fail_node(node: DAGNode, result: ExecutionResult, error: str, t_start: float):
    node.status = NodeStatus.FAILED
    node.error = error
    result.errors[node.id] = error
    elapsed = (time.perf_counter() - t_start) * 1000
    result.timings[node.id] = elapsed
    logger.error(f"  [FAIL] [{node.id}]: {error}")
