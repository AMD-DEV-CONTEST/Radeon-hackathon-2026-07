import json
import logging
import time
from typing import Dict, List, Optional, Callable, Any

from src.llm_client import LLMClient
from src.db import Store
from src.tools import (
    TOOL_RISK, get_tool_definitions,
    AUTO_TOOL_NAMES, FIX_TOOL_NAMES, CHAT_TOOL_NAMES
)
from src.config import (
    MAX_REACT_ITERATIONS, MAX_TOKENS, TEMPERATURE,
    AUTONOMY, PROMPT_LANGUAGE, CLUSTER_NODES, SERVICE_MAP, CLUSTER_BACKEND, HADOOP_BIN
)
from src.guardrails import Guardrail

try:
    from src.web.event_bus import bus
except ImportError:
    bus = None

logger = logging.getLogger(__name__)


# =============================================================================
# Bilingual Prompts (English default)
# =============================================================================

PROMPTS: Dict[str, Dict[str, str]] = {
    "en": {
        "auto": """You are a big data cluster inspection agent. Your job is to efficiently check cluster health and proactively report anomalies.

Cluster Overview:
- 3-node Apache Hadoop cluster (docker-compose): hadoop01, hadoop02, hadoop03
- Services: HDFS (NameNode HA/DataNode/JournalNode), YARN (ResourceManager HA/NodeManager/JobHistoryServer), Hive (MetaStore/Server2), HBase (Master/RegionServer), ZooKeeper
- Monitoring: Prometheus + Grafana (JMX Exporter metrics)

Available Tools: get_alerts, get_service_status, get_metrics, read_logs, search_kb, hdfs_admin, diagnose_node

Inspection Principles:
- Check alerts first (get_alerts): If alerts exist, investigate specifically; if no alerts, still perform spot checks
- Must check key metrics every inspection: call hdfs_admin(report) and get_metrics(disk) at least once
- Batch queries: Use get_service_status("all") to get all service states at once
- Analyze tool outputs: Don't just look at overall_health. Analyze specific values and text to identify anomalies. Common signals:
  * Disk usage >= 85% (warning) or >= 90% (critical)
  * Memory available < 10%
  * "Safe mode is ON", "Missing blocks" > 0, "Corrupt blocks" > 0 in hdfs_admin output
  * Service status not GOOD
  * ERROR/Exception/OOM/Timeout/Connection refused in logs
IMPORTANT: read_logs returns server_time. Compare it with log timestamps to distinguish recent errors from historical ones.
- If service status is RUNNING + GOOD: log errors (recent or historical) are likely non-fatal or already self-healed. Use as context only, do NOT report as current anomalies.
- If service status is NOT GOOD (STOPPED/STARTING/etc): use server_time and log timestamps to judge which errors are relevant to the current failure. Recent errors closer to server_time are more likely to be the active cause. Historical errors are context only.
- Flexible decisions: Prioritize batch queries, drill down when anomalies found
- Report anomalies clearly; brief summary when healthy

Rules:
- Inspection only, no repair actions
- Reply in English, concise and professional, no emojis
- IGNORE "Under replicated blocks" - this is normal during cluster startup and auto-heals

Output Format (strict):
- If anomaly detected: Start with "ANOMALY_DETECTED", one-line summary, then detailed report
- If healthy: Start with "HEALTHY", then brief summary
- This marker is parsed by orchestrator to trigger auto-fix""",

        "fix": """You are a big data platform autonomous operations agent. Your job is to diagnose and repair cluster failures.

Cluster Overview:
- 3-node Apache Hadoop cluster (docker-compose): hadoop01, hadoop02, hadoop03
- Services: HDFS (NameNode HA/DataNode/JournalNode), YARN (ResourceManager HA/NodeManager/JobHistoryServer), Hive (MetaStore/Server2), HBase (Master/RegionServer), ZooKeeper
- Monitoring: Prometheus + Grafana (JMX Exporter metrics)

Available Tools: get_alerts, get_service_status, get_metrics, read_logs, search_kb, hdfs_admin, restart_service, edit_remote_config, write_runbook, diagnose_node, file_ops

Diagnostic Principles:
- Precise targeting: Investigate based on alert info, don't follow fixed procedures
- Analyze tool outputs: Don't just look at overall_health. Identify anomalies from specific data.
- Minimal calls: Use fewest tool calls to locate root cause
- Verify before repair: Confirm root cause before fixing, reference knowledge base (search_kb) for prior experience
- Verification loop: After repair, verify recovery with get_service_status or corresponding tool, then write_runbook

Common Fault Patterns:
- Process stopped/crashed: Check status + logs for cause, restart_service
- OOM: Check logs for OOM keywords, check memory metrics, restart_service
- Disk full: Check disk metrics, clean logs/temp files
- GC issues: Check logs for GC keywords, adjust GC parameters
- Config errors: Check logs for errors, compare configs, edit_remote_config
- HDFS Safe Mode: hdfs_admin(safemode_get) to confirm, hdfs_admin(safemode_leave) if manually entered, check DataNode if auto-entered
- Disk usage high: get_metrics(disk) to confirm, diagnose_node(du_root/find_large) to locate, file_ops(delete/cleanup_logs) to clean
- HDFS corrupt blocks: hdfs_admin(fsck_list_corrupt) to list, hdfs_admin(fsck_delete) to remove, hdfs_admin(report) to verify
- Unknown faults: Analyze logs and metrics, combine architecture knowledge to reason root cause. Don't give up if no pattern matches.

Rules:
- DataNode/NodeManager/ZooKeeper/RegionServer/JournalNode are multi-node services, can specify node for targeted operations
- Wait a few seconds after restart before verification
- Reply in English, concise and professional, no emojis
- After successful repair, call write_runbook to capture experience (title concise, content includes symptoms/root cause/fix/verification, confidence 0.8-1.0)""",

        "chat": """You are a conversational operations assistant for the big data platform. Users ask questions or report issues via chat.

Cluster Overview:
- 3-node Apache Hadoop cluster (docker-compose): hadoop01, hadoop02, hadoop03
- Services: HDFS, YARN, Hive, HBase, ZooKeeper
- Monitoring: Prometheus + Grafana

Available Tools: get_alerts, get_service_status, get_metrics, read_logs, search_kb, hdfs_admin, restart_service, edit_remote_config, write_runbook, diagnose_node, file_ops

Work Modes:
1. Questions: User asks questions (e.g., "Why is HBase slow?")
   - Use read-only tools to investigate
   - Combine with knowledge base (search_kb) for analysis and recommendations
   - No repair operations, only advice

2. Issue Reports: User reports problems (e.g., "HDFS write quota exceeded")
   - Use tools to reproduce/diagnose (e.g., hdfs_admin(count_quota))
   - Confirm root cause then repair directly
   - High-risk operations trigger approval, user approves via Web UI
   - Verify after repair

3. Requests: User asks to do something (e.g., "Clean HDFS temp files")
   - Execute the requested operation directly
   - Briefly explain before executing, report results after

Rules:
- Reply in English, concise and professional, no emojis
- Multi-node services can specify node for targeted operations
- After successful repair, call write_runbook
- Clearly inform user if issue cannot be handled"""
    },
    
    "zh": {
        "auto": """你是一个大数据集群巡检 agent。你的职责是高效检查集群健康状态, 主动发现并上报异常。

集群概况:
- 3节点 Apache Hadoop 集群 (docker-compose): hadoop01, hadoop02, hadoop03
- 服务: HDFS(NameNode HA/DataNode/JournalNode), YARN(ResourceManager HA/NodeManager/JobHistoryServer), Hive(MetaStore/Server2), HBase(Master/RegionServer), ZooKeeper
- 监控: Prometheus + Grafana (JMX Exporter 采集各 daemon 指标)

可用工具: get_alerts, get_service_status, get_metrics, read_logs, search_kb, hdfs_admin, diagnose_node

巡检原则:
- 先看告警(get_alerts): 有告警则针对性排查, 无告警也不代表一切正常, 需主动抽查
- 巡检时必须抽查关键指标: 每次巡检至少调用一次 hdfs_admin(report) 和 get_metrics(disk)
- **批量查询**: 使用 get_service_status("all") 一次性获取所有服务状态, 避免逐个调用
- **分析工具输出**: 不要只看 overall_health 字段. 必须逐条分析工具返回的具体数值和文本, 识别异常信号. 你是集群健康的唯一判断者, 告警系统只做最基本的进程存活检测, 其余异常全靠你的分析. 常见异常信号包括但不限于:
  * 磁盘使用率 >= 85% (warning) 或 >= 90% (critical)
  * 内存可用 < 10%
  * hdfs_admin 输出中的 "Safe mode is ON", "Missing blocks" > 0, "Corrupt blocks" > 0
  * 服务状态异常 (非 GOOD 状态)
  * 日志中出现 ERROR/Exception/OOM/OutOfMemory/GC overhead/Timeout/Connection refused
重要: read_logs 返回 server_time, 请将其与日志时间戳对比, 区分新错误和历史错误
- 服务状态 RUNNING + GOOD 时: 日志中的 ERROR (无论新旧) 可能是非致命错误或已自愈, 仅作参考, 不要报告为当前异常
- 服务状态非 GOOD (STOPPED/STARTING 等) 时: 根据 server_time 和日志时间戳自行判断哪些错误与当前故障相关, 越接近 server_time 的错误越可能是活跃原因, 历史错误仅作参考
  * 任何不符合预期的数值或状态
- 灵活决策: 优先使用批量查询(get_service_status all), 发现异常再针对性深入排查
- 发现异常时: 针对性查日志和指标深入排查, 在巡检报告中明确标注异常项
- 无异常时简报即可, 有异常必须详细说明

规则:
- 只做检查, 不执行任何修复操作
- 回复用中文, 简洁专业, 不要使用emoji
- **忽略 "Under replicated blocks"** - 这是集群启动期间的正常现象, 会自动修复

输出格式 (严格遵守):
- 如果巡检发现任何异常, 你的回复必须以这行开头: ANOMALY_DETECTED
  第二行用一句话概括异常 (如: HDFS 存在 3 个坏块, 需要修复)
  然后是详细的巡检报告
- 如果巡检未发现异常, 你的回复以 HEALTHY 开头, 然后是简短的健康总结
- 这个标记会被调度器解析, 用于决定是否自动触发修复流程""",

        "fix": """你是一个大数据平台自治运维 agent。你的职责是诊断和修复集群故障。

集群概况:
- 3节点 Apache Hadoop 集群 (docker-compose): hadoop01, hadoop02, hadoop03
- 服务: HDFS(NameNode HA/DataNode/JournalNode), YARN(ResourceManager HA/NodeManager/JobHistoryServer), Hive(MetaStore/Server2), HBase(Master/RegionServer), ZooKeeper
- 监控: Prometheus + Grafana (JMX Exporter 采集各 daemon 指标)

可用工具: get_alerts, get_service_status, get_metrics, read_logs, search_kb, hdfs_admin, restart_service, edit_remote_config, write_runbook, diagnose_node, file_ops

诊断原则:
- 精准定位: 根据告警信息针对性排查, 不要走固定流程
- **分析工具输出**: 不要只看 overall_health 字段. 必须逐条分析工具返回的具体数值和文本, 识别异常信号. 告警系统不可能覆盖所有问题, 你需要根据工具返回的数据自行判断什么是异常
- 最少调用: 用最少的工具调用定位根因, 避免不必要的检查
- 先查后修: 确认根因后再修复, 修复前可参考知识库(search_kb)已有经验
- 验证闭环: 修复后用 get_service_status 或对应工具验证恢复, 成功后回写runbook(write_runbook)

常见故障模式 (供参考, 不限于此):
- 进程停止/崩溃: 查状态+日志确认原因, restart_service 重启
- OOM: 查日志确认OOM关键词, 查内存指标, restart_service 重启
- 磁盘满: 查磁盘指标, 清理日志/临时文件
- GC过长: 查日志GC关键词, 调整GC参数
- 配置错误: 查日志报错, 对比配置, edit_remote_config 修正
- HDFS Safe Mode: hdfs_admin(report/safemode_get) 确认状态, 若为手动进入则 hdfs_admin(safemode_leave) 退出, 若为自动进入则检查 DataNode 是否下线导致块不足
- 磁盘使用率过高: get_metrics(disk) 确认使用率, diagnose_node(du_root/find_large) 定位大文件, file_ops(delete/cleanup_logs) 清理, 确认服务恢复
- HDFS 坏块修复流程: hdfs_admin(fsck_list_corrupt) 列出坏块文件 → hdfs_admin(fsck_delete, path=/) 删除坏块文件 → hdfs_admin(report) 验证 Corrupt blocks=0
- **未知故障**: 仔细分析日志和指标中的异常信号, 结合集群架构和服务依赖关系推理根因. 不要因为没有匹配的故障模式就放弃, 要主动分析并尝试修复
- diagnose_node 可用于任意诊断场景: du_root(磁盘占用)/find_large(大文件)/top_procs(进程)/netstat(端口)/custom(自定义只读命令)
- file_ops 可用于修复: delete(删除文件)/truncate(截断日志)/cleanup_logs(清理旧日志). 注意安全限制, 仅允许删除日志/临时文件
- 磁盘满修复流程: diagnose_node(du_root/find_large) 定位大文件 → file_ops(delete/cleanup_logs) 清理 → get_metrics(disk) 验证

规则:
- DataNode/NodeManager/ZooKeeper/RegionServer/JournalNode 是多节点服务, 可指定 node 操作特定节点
- 重启后等待几秒再用 get_service_status 验证
- 回复用中文, 简洁专业, 不要使用emoji
- 修复成功后调用 write_runbook 回写经验 (标题简明, 内容含症状/根因/修复/验证, confidence 0.8-1.0)""",

        "chat": """你是大数据平台的对话式运维助手。用户会通过聊天框向你提问或汇报问题。

集群概况:
- 3节点 Apache Hadoop 集群 (docker-compose): hadoop01, hadoop02, hadoop03
- 服务: HDFS(NameNode HA/DataNode/JournalNode), YARN(ResourceManager HA/NodeManager/JobHistoryServer), Hive(MetaStore/Server2), HBase(Master/RegionServer), ZooKeeper
- 监控: Prometheus + Grafana (JMX Exporter 采集各 daemon 指标)

可用工具: get_alerts, get_service_status, get_metrics, read_logs, search_kb, hdfs_admin, restart_service, edit_remote_config, write_runbook, diagnose_node, file_ops

工作模式:
1. **提问类**: 用户问问题 (如"HBase 为什么慢?""上次 DataNode 掉线怎么修的?")
   - 调用只读工具 (get_service_status/get_metrics/read_logs/hdfs_admin/search_kb 等) 排查
   - 结合知识库 (search_kb) 给出分析和建议
   - 不执行修复操作, 只给建议

2. **报障类**: 用户汇报问题 (如"HDFS 写入报配额超限""Hive 查询报错")
   - 先用工具复现/诊断问题 (如 hdfs_admin(count_quota) 查配额)
   - 确认根因后直接修复 (如 hdfs_admin(set_space_quota) 调整配额)
   - 高危操作 (restart_service/edit_remote_config) 会触发审批, 用户在 Web 审批后继续执行
   - 修复后验证, 如调了配额再用 count_quota 确认生效

3. **请求类**: 用户要求做某事 (如"帮我清理 HDFS 临时文件""重启 RegionServer")
   - 直接执行请求的操作
   - 执行前简要说明将要做什么, 执行后报告结果

常见问题处理:
- HDFS 配额超限 (QuotaExceededException): hdfs_admin(count_quota, path=xxx) 查看配额和用量 → hdfs_admin(set_space_quota, path=xxx, quota=500g) 调整空间配额, 或 hdfs_admin(set_quota, path=xxx, quota=10000) 调整文件数配额 → count_quota 验证
- HDFS 权限问题 (PermissionDenied): search_kb 查权限修复方案 → 提供指导或执行修复
- HBase 慢: read_logs(service=HBase, filter=Slow) + get_metrics 查 RegionServer 状态
- 服务异常: get_service_status + read_logs 确认, restart_service 重启

规则:
- 回复用中文, 简洁专业, 不要使用emoji
- DataNode/NodeManager/ZooKeeper/RegionServer/JournalNode 是多节点服务, 可指定 node 操作特定节点
- 修复成功后调用 write_runbook 回写经验
- 无法处理的问题明确告知用户原因和建议"""
    }
}


def _build_cluster_context(lang: str = "en") -> str:
    """Build cluster context string from SERVICE_MAP + CLUSTER_NODES."""
    from .config import (
        CLUSTER_NODES, SERVICE_MAP, CLUSTER_BACKEND,
        HADOOP_BIN, JPS_BIN, PROMETHEUS_URL, GRAFANA_URL,
    )

    is_ha = len(CLUSTER_NODES) >= 3
    L = lang == "zh"

    lines = []

    # ---- Section 1: Environment ----
    if L:
        lines.append("集群运维上下文:")
        lines.append(f"- 部署: {'Docker-compose 多节点 HA' if is_ha else '单节点直装'} ({CLUSTER_BACKEND})")
        lines.append(f"- 节点: {', '.join(CLUSTER_NODES.keys())}")
        lines.append(f"- Hadoop: {HADOOP_BIN} | jps: {JPS_BIN}")
        lines.append(f"- 监控: Prometheus @ {PROMETHEUS_URL} | Grafana @ {GRAFANA_URL}")
    else:
        lines.append("Cluster Ops Context:")
        lines.append(f"- Deployment: {'Docker-compose multi-node HA' if is_ha else 'Single-node direct install'} ({CLUSTER_BACKEND})")
        lines.append(f"- Nodes: {', '.join(CLUSTER_NODES.keys())}")
        lines.append(f"- Hadoop: {HADOOP_BIN} | jps: {JPS_BIN}")
        lines.append(f"- Monitoring: Prometheus @ {PROMETHEUS_URL} | Grafana @ {GRAFANA_URL}")

    # ---- Section 2: Service mapping table (only from SERVICE_MAP) ----
    lines.append("")
    if L:
        lines.append("服务映射 (read_logs / restart_service 参数参考):")
        lines.append(f"{'服务':<16} {'节点':<22} {'日志文件':<16} {'supervisor程序名'}")
        lines.append("-" * 70)
    else:
        lines.append("Service mapping (for read_logs / restart_service):")
        lines.append(f"{'Service':<16} {'Nodes':<22} {'Log file':<16} {'supervisor program'}")
        lines.append("-" * 70)

    for svc_name, svc_info in SERVICE_MAP.items():
        nodes = svc_info.get("nodes", [])
        if not nodes:
            continue
        log_file = svc_info.get("log_file", "-")
        sup_prog = svc_info.get("supervisor_program", "-")
        nodes_str = ", ".join(nodes)
        lines.append(f"{svc_name:<16} {nodes_str:<22} {log_file:<16} {sup_prog}")

    return "\n".join(lines)


def get_prompt(mode: str, lang: Optional[str] = None) -> str:
    """Get prompt for given mode and language."""
    if lang is None:
        lang = PROMPT_LANGUAGE
    
    # Fallback to English if language not supported
    if lang not in PROMPTS:
        lang = "en"
    
    # Fallback to fix prompt if mode not found
    if mode not in PROMPTS[lang]:
        mode = "fix"
    
    prompt = PROMPTS[lang][mode]
    
    # Dynamically replace hardcoded cluster node line with actual topology
    node_count = len(CLUSTER_NODES)
    node_names = ", ".join(CLUSTER_NODES.keys())
    is_ha = node_count >= 3

    if lang == "zh":
        old_line = "- 3节点 Apache Hadoop 集群 (docker-compose): hadoop01, hadoop02, hadoop03"
        if is_ha:
            new_line = f"- {node_count}节点 Apache Hadoop 集群: {node_names}"
        else:
            new_line = f"- 单节点 Apache Hadoop 集群: {node_names}"
    else:
        old_line = "- 3-node Apache Hadoop cluster (docker-compose): hadoop01, hadoop02, hadoop03"
        if is_ha:
            new_line = f"- {node_count}-node Apache Hadoop cluster: {node_names}"
        else:
            new_line = f"- Single-node Apache Hadoop cluster: {node_names}"
    
    prompt = prompt.replace(old_line, new_line)
    
    # Remove JournalNode mentions in single-node mode
    if not is_ha:
        prompt = prompt.replace("/JournalNode", "")
        prompt = prompt.replace("NameNode HA", "NameNode")
        prompt = prompt.replace("ResourceManager HA", "ResourceManager")
    
    # Inject dynamic cluster context (service-node-log mapping)
    prompt = prompt + "\n\n" + _build_cluster_context(lang)
    
    return prompt


# =============================================================================
# ReAct Agent
# =============================================================================

class ReActAgent:
    """ReAct agent for cluster inspection and repair."""
    
    def __init__(
        self,
        llm: LLMClient,
        store: Store,
        mode: str = "fix",
        guardrail: Optional[Guardrail] = None,
        lang: Optional[str] = None
    ):
        self.llm = llm
        self.store = store
        self.mode = mode
        self.lang = lang or PROMPT_LANGUAGE
        self.guardrail = guardrail or Guardrail(store, autonomy=AUTONOMY)
        
        # Set tool names and prompt based on mode
        if mode == "auto":
            self.tool_names = AUTO_TOOL_NAMES
        elif mode == "chat":
            self.tool_names = CHAT_TOOL_NAMES
        else:
            self.tool_names = FIX_TOOL_NAMES
        
        self.system_prompt = get_prompt(mode, self.lang)
        self.tool_defs = get_tool_definitions(self.tool_names)
    
    def run(
        self,
        user_message: str,
        parent_id: Optional[str] = None,
        trigger: str = ""
    ) -> str:
        """Standard ReAct loop (no history)."""
        return self._run_react(user_message, [], parent_id, trigger)
    
    def run_with_history(
        self,
        user_message: str,
        history: List[Dict],
        parent_id: Optional[str] = None,
        trigger: str = "",
        session_id: Optional[str] = None
    ) -> str:
        """ReAct loop with conversation history (chat mode)."""
        return self._run_react(user_message, history, parent_id, trigger, session_id)
    
    def _run_react(
        self,
        user_message: str,
        history: List[Dict],
        parent_id: Optional[str] = None,
        trigger: str = "",
        session_id: Optional[str] = None
    ) -> str:
        """Core ReAct loop implementation."""
        # Create or use existing session
        sid = session_id or self.store.create_session(
            session_type=self.mode,
            parent_id=parent_id,
            trigger=trigger
        )
        seq = 0
        tag = f"[/{self.mode} {sid}]"
        
        # Build messages: system + history + current user message
        messages = [{"role": "system", "content": self.system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        
        # Log user input
        self._log_event(sid, seq, "user_input", {"message": user_message})
        seq += 1
        
        # ReAct iteration loop
        for iteration in range(MAX_REACT_ITERATIONS):
            logger.info(f"{tag} --- iteration {iteration + 1}/{MAX_REACT_ITERATIONS} ---")
            
            # Stream handling setup
            stream_buffer = {"reasoning": "", "content": ""}
            last_send_time = time.time()
            BATCH_SIZE = 10
            BATCH_INTERVAL = 0.05
            
            def _on_chunk(chunk: Dict, _sid: str = sid) -> None:
                """Handle streaming chunks from LLM."""
                if not bus:
                    return
                
                chunk_type = chunk.get("type", "")
                text = chunk.get("text", "")
                
                if chunk_type == "reasoning":
                    stream_buffer["reasoning"] += text
                else:
                    stream_buffer["content"] += text
                
                nonlocal last_send_time
                current_time = time.time()
                buffer_text = stream_buffer.get(chunk_type, "")
                
                if len(buffer_text) >= BATCH_SIZE or (current_time - last_send_time) >= BATCH_INTERVAL:
                    if buffer_text:
                        kind = "stream_reasoning" if chunk_type == "reasoning" else "stream_content"
                        bus.publish({
                            "type": "agent_event",
                            "session_id": _sid,
                            "kind": kind,
                            "content": {"text": buffer_text}
                        })
                        stream_buffer[chunk_type] = ""
                        last_send_time = current_time
            
            # Call LLM with streaming
            try:
                resp = self.llm.chat_stream(
                    messages=messages,
                    tools=self.tool_defs,
                    max_tokens=MAX_TOKENS,
                    temperature=TEMPERATURE,
                    on_chunk=_on_chunk
                )
                
                # Flush remaining stream buffer
                if bus:
                    if stream_buffer["reasoning"]:
                        bus.publish({
                            "type": "agent_event",
                            "session_id": sid,
                            "kind": "stream_reasoning",
                            "content": {"text": stream_buffer["reasoning"]}
                        })
                    if stream_buffer["content"]:
                        bus.publish({
                            "type": "agent_event",
                            "session_id": sid,
                            "kind": "stream_content",
                            "content": {"text": stream_buffer["content"]}
                        })
            
            except Exception as e:
                logger.warning(f"{tag} chat_stream failed ({e}), fallback to chat")
                try:
                    resp = self.llm.chat(
                        messages=messages,
                        tools=self.tool_defs,
                        max_tokens=MAX_TOKENS,
                        temperature=TEMPERATURE
                    )
                except Exception as e2:
                    logger.error(f"{tag} chat fallback also failed: {e2}")
                    self._log_event(sid, seq, "error", {"error": f"LLM unavailable: {e2}"})
                    self.store.finish_session(sid, summary=f"LLM error: {e2}", status="error")
                    return f"LLM error: {e2}"
            
            # Process LLM response
            content = resp.get("content", "")
            reasoning = resp.get("reasoning", "")
            tool_calls = resp.get("tool_calls", [])
            
            # Log reasoning
            if reasoning:
                print(f"  {tag} [思考] {reasoning.strip()[:150]}")
                self._log_event(sid, seq, "reasoning", {"text": reasoning})
                seq += 1
                if bus:
                    bus.publish({
                        "type": "agent_event",
                        "session_id": sid,
                        "kind": "reasoning",
                        "content": {"text": reasoning}
                    })
            
            # Build assistant message
            assistant_msg = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False)
                        }
                    }
                    for tc in tool_calls
                ]
            messages.append(assistant_msg)
            
            # Log assistant response
            self._log_event(sid, seq, "assistant", {"text": content, "tool_calls": tool_calls})
            seq += 1
            if bus and (content or tool_calls):
                bus.publish({
                    "type": "agent_event",
                    "session_id": sid,
                    "kind": "assistant",
                    "content": {"text": content or "", "tool_calls": tool_calls}
                })
            
            # Check if done (no tool calls)
            if not tool_calls:
                # Fallback to reasoning if content is empty
                if not content.strip() and reasoning:
                    content = reasoning.strip()
                if not content.strip():
                    content = "(Agent completed analysis but generated no text response. Please check the thinking process.)"
                
                print(f"  {tag} [完成] {content[:200]}")
                self._log_event(sid, seq, "final_answer", {"text": content})
                if bus:
                    bus.publish({
                        "type": "agent_event",
                        "session_id": sid,
                        "kind": "final_answer",
                        "content": {"text": content}
                    })
                
                # Maybe prompt for runbook in fix/chat mode
                if self.mode in ("fix", "chat"):
                    if not self._session_used_tool(sid, "write_runbook"):
                        self._maybe_prompt_runbook(sid, seq, messages, content, tag)
                        seq += 10
                
                self.store.finish_session(sid, summary=content[:300])
                return content
            
            # Execute tool calls
            for tc in tool_calls:
                name = tc.get("name", "")
                args = tc.get("arguments", {})
                risk = TOOL_RISK.get(name, "low")
                
                print(f"  {tag} [工具] {name}({args}) risk={risk}")
                self._log_event(sid, seq, "tool_call", {"name": name, "args": args, "risk": risk})
                if bus:
                    bus.publish({
                        "type": "agent_event",
                        "session_id": sid,
                        "kind": "tool_call",
                        "content": {"name": name, "args": args, "risk": risk}
                    })
                seq += 1
                
                # Execute via guardrail
                result = self.guardrail.execute(name, args, session_id=sid)
                print(f"  {tag} [结果] {json.dumps(result, ensure_ascii=False)[:200]}")
                self._log_event(sid, seq, "tool_result", {"name": name, "result": result})
                if bus:
                    bus.publish({
                        "type": "agent_event",
                        "session_id": sid,
                        "kind": "tool_result",
                        "content": {"name": name, "result": result}
                    })
                seq += 1
                
                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False)
                })
        
        # Max iterations reached
        print(f"  {tag} [达到最大迭代数, 终止]")
        self.store.finish_session(sid, summary="max iterations", status="aborted")
        return "max iterations"
    
    def _log_event(self, sid: str, seq: int, kind: str, content: Dict) -> None:
        """Log event to store and publish to bus."""
        self.store.log_event(sid, seq, kind, content)
    
    def _session_used_tool(self, session_id: str, tool_name: str) -> bool:
        """Check if session has used a specific tool."""
        try:
            with self.store.lock:
                row = self.store.conn.execute(
                    """SELECT COUNT(*) FROM session_events 
                       WHERE session_id=? AND kind='tool_call' 
                       AND json_extract(content_json, '$.name')=?""",
                    (session_id, tool_name)
                ).fetchone()
            return row and row[0] > 0
        except Exception:
            return False
    
    def _session_has_repair_action(self, session_id: str) -> bool:
        """Check if session has executed repair actions."""
        try:
            with self.store.lock:
                row = self.store.conn.execute(
                    """SELECT COUNT(*) FROM session_events 
                       WHERE session_id=? AND kind='tool_call' 
                       AND (json_extract(content_json, '$.name')='restart_service' 
                            OR json_extract(content_json, '$.name')='edit_remote_config')""",
                    (session_id,)
                ).fetchone()
            return row and row[0] > 0
        except Exception:
            return False
    
    def _maybe_prompt_runbook(
        self,
        sid: str,
        seq: int,
        messages: List[Dict],
        final_content: str,
        tag: str
    ) -> None:
        """Prompt agent to write runbook after successful repair."""
        if not self._session_has_repair_action(sid):
            return
        
        # Check for success keywords
        success_keywords = [
            "成功", "恢复", "正常", "已启动", "已修复", "GOOD", "RUNNING",
            "已解决", "验证通过", "health", "success", "recovered", "fixed",
            "restored", "completed", "verified"
        ]
        content_lower = final_content.lower()
        is_success = any(kw.lower() in content_lower for kw in success_keywords)
        if not is_success:
            return
        
        # Build prompt based on language
        if self.lang == "zh":
            prompt = (
                "检测到本次故障已成功修复。请调用 write_runbook 工具, 将本次排查和修复经验回写知识库, "
                "供未来遇到相同问题时快速复用。要求:\n"
                "- title: 简明描述故障场景 (如 'DataNode OOM 崩溃修复')\n"
                "- content: 结构化描述, 包含 症状/排查步骤/根因/修复方法/验证方式\n"
                "- tags: 相关标签 (逗号分隔, 如 hdfs,datanode,oom)\n"
                "- confidence: 0.8-1.0 (根据修复把握度)"
            )
        else:
            prompt = (
                "Fault has been successfully repaired. Please call write_runbook tool to capture "
                "this troubleshooting and repair experience to the knowledge base for future reuse. "
                "Requirements:\n"
                "- title: Concise description of fault scenario (e.g., 'DataNode OOM Crash Repair')\n"
                "- content: Structured description including symptoms/investigation steps/root cause/repair method/verification\n"
                "- tags: Relevant tags (comma-separated, e.g., hdfs,datanode,oom)\n"
                "- confidence: 0.8-1.0 (based on repair confidence)"
            )
        
        messages.append({"role": "user", "content": prompt})
        self._log_event(sid, seq, "runbook_prompt", {"text": prompt})
        if bus:
            bus.publish({
                "type": "agent_event",
                "session_id": sid,
                "kind": "runbook_prompt",
                "content": {"text": prompt}
            })
        
        # Run LLM to generate runbook
        try:
            resp = self.llm.chat(
                messages=messages,
                tools=self.tool_defs,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE
            )
            tool_calls = resp.get("tool_calls", [])
            for tc in tool_calls:
                if tc.get("name") == "write_runbook":
                    args = tc.get("arguments", {})
                    print(f"  {tag} [学习闭环] 自动回写 runbook: {args.get('title', '')}")
                    result = self.guardrail.execute("write_runbook", args, session_id=sid)
                    self._log_event(sid, seq + 1, "tool_call", {"name": "write_runbook", "args": args, "auto": True})
                    self._log_event(sid, seq + 2, "tool_result", {"name": "write_runbook", "result": result})
                    if bus:
                        bus.publish({
                            "type": "agent_event",
                            "session_id": sid,
                            "kind": "tool_call",
                            "content": {"name": "write_runbook", "args": args, "auto": True}
                        })
                        bus.publish({
                            "type": "agent_event",
                            "session_id": sid,
                            "kind": "tool_result",
                            "content": {"name": "write_runbook", "result": result}
                        })
                    logger.info(f"{tag} Runbook written: {result.get('id', '')}")
        except Exception as e:
            logger.warning(f"{tag} Auto write runbook failed: {e}")
