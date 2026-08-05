import json
import time
import logging
import threading

from .llm_client import LLMClient
from .db import Store
from .agent import ReActAgent
from .tools import get_pending_alerts, get_cluster_snapshot
from .config import get_lang

logger = logging.getLogger(__name__)


class Orchestrator:
    """master 调度器 - 纯规则, 不调 LLM。管理 /auto 巡检 + /fix 抢占。

    两层故障发现机制:
    1. 快速路径: get_pending_alerts() 检测进程存活 (Prometheus target down / supervisor STOPPED)
       → 立即触发 /fix, 无需等巡检周期
    2. 巡检升级: /auto session 中 LLM 分析工具输出 (hdfs report / metrics / logs)
       → 发现异常时输出 ANOMALY_DETECTED 标记 → 自动触发 /fix
       → 覆盖告警系统无法预编码的故障 (Safe Mode / 磁盘满 / 坏块 / OOM / 未知故障)

    故障注入由用户手动操作（kill 进程 / 篡改数据 / 填满磁盘等）。
    """

    def __init__(self, llm: LLMClient, store: Store,
                 inspect_interval=15, auto_fault_inject=False, fault_delay=20):
        self.llm = llm
        self.store = store
        self.inspect_interval = inspect_interval
        self.auto_fault_inject = auto_fault_inject
        self.fault_delay = fault_delay
        self.last_inspect = 0
        self.master_sid = None
        self.start_time = time.time()
        # 重启后等几秒再验证 (supervisorctl/CM API 状态更新有延迟)
        self.post_fix_delay = 5
        # 停止标志: 信号 handler 设置后, 巡检循环自然退出 (优雅关闭)
        self._stop = False

        # chat 独立线程 (与巡检并行, 不阻塞)
        self._chat_thread = None

    def stop(self):
        """请求常驻循环优雅停止 (由信号 handler 调用)。"""
        self._stop = True

    def run(self, max_cycles=None):
        """常驻巡检循环。max_cycles=None 表示无限运行 (24h 无人值守),
        传入正整数仅用于测试/演示限制轮数。收到信号调用 stop() 后优雅退出。"""
        self._stop = False  # 重置 (支持 run 被多次调用)
        # 关闭旧的 running master session (避免多个 master 并存)
        with self.store.lock:
            self.store.conn.execute(
                "UPDATE sessions SET status='done', ended_at=? "
                "WHERE type='master' AND status='running'",
                (int(time.time()),)
            )
            self.store.conn.commit()
        self.master_sid = self.store.create_session(
            session_type="master", trigger="orchestrator")
        print(f"\n{'='*60}")
        print(f"  AIOps Agent Started (master={self.master_sid})")
        print(f"  Inspect interval: {self.inspect_interval}s")
        print(f"  Backend: {self._backend_info()}")
        print(f"  Mode: Auto inspection with LLM-driven anomaly detection")
        print(f"{'='*60}\n")

        # 启动 chat 消费线程 (独立于巡检循环)
        self._chat_thread = threading.Thread(
            target=self._chat_loop, daemon=True, name="chat-worker")
        self._chat_thread.start()

        cycle = 0
        while not self._stop and (max_cycles is None or cycle < max_cycles):
            cycle += 1
            elapsed = int(time.time() - self.start_time)

            try:
                # Check alerts -> trigger fix
                alerts = get_pending_alerts()
                if alerts:
                    alert = alerts[0]
                    print(f"\n>>> [T+{elapsed}s] Alert: {alert['alertname']} ({alert['severity']})")
                    self._run_fix(alert, elapsed)
                    time.sleep(self.post_fix_delay)
                    self.last_inspect = 0
                    continue

                # Scheduled inspection
                if time.time() - self.last_inspect >= self.inspect_interval:
                    print(f"\n>>> [T+{elapsed}s] Starting inspection /auto\n")
                    self._run_auto(elapsed)
                    self.last_inspect = time.time()
                    continue
            except Exception as e:
                logger.exception(f"[T+{elapsed}s] Cycle error: {e}")
                time.sleep(5)
                continue

            time.sleep(2)

        if self.master_sid:
            self.store.finish_session(self.master_sid, summary="stopped", status="done")
        reason = "stopped" if self._stop else "max cycles"
        print(f"\n{'='*60}")
        print(f"  Agent stopped ({reason}, {cycle} cycles)")
        print(f"{'='*60}")

    def _run_auto(self, elapsed):
        """巡检子session - 一次性 context, 只读工具.
        
        如果巡检 LLM 发现异常 (回复以 ANOMALY_DETECTED 开头),
        自动触发 /fix 修复流程, 无需预编码告警规则.
        """
        state_card = self.store.get_latest_state_card()
        lang = get_lang()
        if lang == "zh":
            prompt = "执行例行集群巡检。"
        else:
            prompt = "Perform routine cluster inspection."
        if state_card:
            label = "上次巡检状态卡" if lang == "zh" else "Last inspection state card"
            prompt += f"\n{label}: {json.dumps(state_card, ensure_ascii=False)}"

        # 注入最近 session 历史 (巡检+修复), 让 Agent 了解近期发生了什么
        recent_sessions = self.store.get_recent_session_summaries(limit=5, minutes=10)
        if recent_sessions:
            if lang == "zh":
                prompt += "\n\n近期 session 记录 (供参考, 了解集群近期状态变化):"
            else:
                prompt += "\n\nRecent session history (for reference, to understand recent cluster changes):"
            for s in recent_sessions:
                age = int(time.time()) - s["started_at"]
                prompt += f"\n- [{s['type']}] {s['summary']} ({age}s ago)"

        agent = ReActAgent(self.llm, self.store, mode="auto", lang=get_lang())
        result = agent.run(prompt, parent_id=self.master_sid, trigger="cron")

        # 保存状态卡 (结构化快照 + 巡检摘要)
        snapshot_after = get_cluster_snapshot()
        self.store.save_state_card({
            "inspect_time": f"T+{elapsed}s",
            "cluster": snapshot_after,
            "summary": result[:200],
        })
        print(f"\n>>> [T+{elapsed}s] Inspection done <<<\n")

        # Auto-upgrade to /fix if anomaly detected
        if result and result.strip().startswith("ANOMALY_DETECTED"):
            lines = result.strip().split("\n", 2)
            anomaly_brief = lines[1].strip() if len(lines) > 1 else "Anomaly detected"
            anomaly_detail = lines[2].strip() if len(lines) > 2 else result[:500]
            print(f"\n>>> [T+{elapsed}s] Anomaly: {anomaly_brief}")

            synthetic_alert = {
                "alertname": "INSPECTION_ANOMALY",
                "severity": "critical",
                "summary": anomaly_brief,
                "detail": anomaly_detail,
            }
            self._run_fix(synthetic_alert, elapsed)
            time.sleep(self.post_fix_delay)
            self.last_inspect = 0

    def _run_fix(self, alert, elapsed):
        """修复子session - 一次性 context, 全工具(含高危)"""
        lang = get_lang()
        node_info = alert.get('node', '')
        state_info = alert.get('roleState', '') or alert.get('healthSummary', '')
        if lang == "zh":
            prompt = (f"告警: {alert['alertname']} on {node_info} "
                      f"(severity={alert['severity']}")
            if state_info:
                prompt += f", 状态={state_info}"
            prompt += f")\n摘要: {alert.get('summary','')}"
            # 巡检升级的告警携带详细分析上下文
            if alert.get('detail'):
                prompt += f"\n巡检分析: {alert['detail']}"
            prompt += "\n请诊断并修复此故障。"
        else:
            prompt = (f"Alert: {alert['alertname']} on {node_info} "
                      f"(severity={alert['severity']}")
            if state_info:
                prompt += f", state={state_info}"
            prompt += f")\nSummary: {alert.get('summary','')}"
            if alert.get('detail'):
                prompt += f"\nInspection analysis: {alert['detail']}"
            prompt += "\nPlease diagnose and repair this issue."

        agent = ReActAgent(self.llm, self.store, mode="fix", lang=get_lang())
        result = agent.run(prompt, parent_id=self.master_sid, trigger=f"alert:{alert['alertname']}")
        print(f"\n>>> [T+{elapsed}s] Fix done <<<\n")

    def _chat_loop(self):
        """chat 消费线程: 独立于巡检主循环, 轮询 pending 消息并处理.

        - 与 /auto /fix 并行, 不排队
        - 支持多轮上下文: 按 chat_session_id 拉取历史
        - 预创 agent session, 前端可实时获取思考链
        """
        logger.info("Chat worker thread started")

        # 启动恢复: 重启后可能有残留的 processing 消息, 重置为 pending
        with self.store.lock:
            row = self.store.conn.execute(
                "UPDATE chat_messages SET status='pending', session_id='' "
                "WHERE status='processing'"
            )
            if row.rowcount > 0:
                logger.info(f"Recovered {row.rowcount} stuck chat messages (processing -> pending)")
            self.store.conn.commit()
        while not self._stop:
            try:
                msgs = self.store.get_pending_chat_messages(limit=1)
                if not msgs:
                    time.sleep(1)
                    continue

                msg = msgs[0]
                msg_id = msg["id"]
                user_msg = msg["user_msg"]
                chat_session_id = msg.get("chat_session_id")
                elapsed = int(time.time() - self.start_time)
                print(f"\n>>> [T+{elapsed}s] [CHAT] {user_msg[:80]}")

                # 预创 agent session, 前端可立即获取 session_id 拉取思考链
                agent_sid = self.store.create_session(
                    session_type="chat", parent_id=self.master_sid,
                    trigger=f"user_chat:{msg_id}")

                # 标记 processing (绑定 agent_sid)
                self.store.mark_chat_processing(msg_id, agent_sid)

                # 按 chat_session 拉取多轮历史
                history = []
                if chat_session_id:
                    history = self.store.get_chat_history_by_session(chat_session_id, limit=20)

                # 运行 agent (使用预创 session)
                agent = ReActAgent(self.llm, self.store, mode="chat", lang=get_lang())
                result = agent.run_with_history(
                    user_msg, history,
                    parent_id=self.master_sid,
                    trigger=f"user_chat:{msg_id}",
                    session_id=agent_sid)

                # 写入回复
                self.store.finish_chat_message(msg_id, result[:8000])

                print(f">>> [T+{elapsed}s] [CHAT] Done <<<\n")
            except Exception as e:
                logger.exception(f"Chat worker error: {e}")
                time.sleep(3)

        logger.info("Chat worker thread stopped")

    @staticmethod
    def _backend_info():
        from .config import CLUSTER_BACKEND, PROMETHEUS_URL, CM_HOST, CM_PORT, CM_CLUSTER
        if CLUSTER_BACKEND == "cdh":
            return f"CDH CM API @ http://{CM_HOST}:{CM_PORT} cluster={CM_CLUSTER}"
        else:
            return f"Apache Hadoop (docker-compose) + Prometheus @ {PROMETHEUS_URL}"
