"""
安全护栏 — §21 双轴四档分级自治 (替代原 §5/§9 初版)

轴1 AUTONOMY (config): supervised (人工审批) / autonomous (无人值守)
轴2 tier (classify):    low / medium / recover / reversible / irreversible

定级权归规则(DB), 不归模型。模型只选工具 + 给理由, 理由不参与定级。
fail-closed: 未知工具一律 irreversible + 不可自动执行。
"""
import json
import time
import uuid
import logging
import threading

from .config import CLUSTER_BACKEND
from .tools import execute_tool, cm_get, CM_CLUSTER, SERVICE_MAP, ssh_exec

logger = logging.getLogger(__name__)

# ---- 档位常量 ----
TIER_LOW = "low"
TIER_MEDIUM = "medium"
TIER_RECOVER = "recover"
TIER_REVERSIBLE = "reversible"
TIER_IRREVERSIBLE = "irreversible"


class Guardrail:
    """§21 安全护栏 — 双轴四档分级自治"""

    # 类级共享: 跨 Guardrail 实例 (跨 /fix 会话) 累积失败计数
    _failure_counts = {}
    _last_failure_ts = {}
    # 保护上面两个类级 dict 的读-改-写 (多 fix 会话并发时避免竞态)
    _circuit_lock = threading.Lock()

    def __init__(self, store, autonomy="supervised"):
        self.store = store
        self.autonomy = autonomy  # "supervised" / "autonomous"
        # 熔断 (失败侧, §9 保留) — 用类级共享状态
        self.max_failures = 3
        self.circuit_cooldown = 300
        # attempt 节流 (尝试侧, §21.5)
        self.max_attempts = 2
        self.attempt_cooldown = 60   # 两次自动执行最小间隔
        self.attempt_window = 600   # 观察窗口 10min
        # classify 缓存 (§21.3 TTL)
        self._rules_cache = {"data": None, "ts": 0}
        self._rules_cache_ttl = 30  # 30s 缓存
        # _refine_restart 缓存 (避免每次 restart 都打 CM API)
        self._refine_cache = {}  # {svc+node: (tier, autonomous, ts)}
        self._refine_cache_ttl = 10  # 10s

    # ============================================================
    # §21.3 classify — 纯规则 + DB + fail-closed
    # ============================================================

    def classify(self, tool_name, args):
        """定级: 查 risk_rules -> match_json 命中 -> 运行时精炼 -> fail-closed

        Returns: (tier, autonomous_allowed)
        """
        rules = self._get_rules_cached()
        tier, autonomous = self._match_rules(rules, tool_name, args)

        # §21.4 运行时精炼 (restart_service: 检查角色状态)
        if tool_name == "restart_service" and tier == TIER_RECOVER:
            tier, autonomous = self._refine_restart(args, tier, autonomous)

        # autonomous 标志保留规则原意, 分支用 self.autonomy 决策
        return tier, autonomous

    def _get_rules_cached(self):
        """从 DB 读取 risk_rules, 带 TTL 缓存"""
        now = time.time()
        if self._rules_cache["data"] is not None and now - self._rules_cache["ts"] < self._rules_cache_ttl:
            return self._rules_cache["data"]
        rules = self.store.get_risk_rules(enabled_only=True)
        self._rules_cache["data"] = rules
        self._rules_cache["ts"] = now
        return rules

    def _match_rules(self, rules, tool_name, args):
        """匹配规则: tool_name 命中 + match_json 命中, 取 priority 最高"""
        best = None
        for r in rules:
            if r["tool_name"] != tool_name and r["tool_name"] != "*":
                continue
            if r["match_json"]:
                if not self._match_json(r["match_json"], args):
                    continue
            if best is None or r["priority"] > best["priority"]:
                best = r
        if best:
            return best["tier"], bool(best["autonomous"])
        # fail-closed: 未知工具
        return TIER_IRREVERSIBLE, False

    @staticmethod
    def _match_json(match_spec, args):
        """检查 args 是否满足 match_json 条件 (所有 key-value 匹配)"""
        if not isinstance(match_spec, dict):
            return True
        for k, v in match_spec.items():
            if args.get(k) != v:
                return False
        return True

    def _refine_restart(self, args, tier, autonomous):
        """§21.4 运行时精炼: restart_service 时检查角色状态

        - STOPPED/DOWN/UNKNOWN → 维持 recover (重启不会更糟)
        - RUNNING 但不健康 → 降为 irreversible (不主动制造中断)
        - 带 10s 缓存避免每次都打 CM API / supervisorctl

        CDH: CM API role state
        Apache: supervisorctl status
        """
        svc = args.get("service", "")
        svc_info = SERVICE_MAP.get(svc, {})

        # 缓存检查
        cache_key = svc + ":" + (args.get("node", "") or "")
        now = time.time()
        cached = self._refine_cache.get(cache_key)
        if cached and now - cached[2] < self._refine_cache_ttl:
            return cached[0], cached[1]

        if CLUSTER_BACKEND == "cdh":
            result = self._cdh_refine_restart(svc, svc_info, args, tier, autonomous)
        else:
            result = self._apache_refine_restart(svc, svc_info, args, tier, autonomous)

        self._refine_cache[cache_key] = (result[0], result[1], now)
        return result

    def _cdh_refine_restart(self, svc, svc_info, args, tier, autonomous):
        """CDH: 通过 CM API 检查角色状态"""
        cm_svc = svc_info.get("cm_service", "")
        role_type = svc_info.get("cm_role_type", "")
        if not cm_svc:
            return tier, autonomous

        data = cm_get(f"/clusters/{CM_CLUSTER}/services/{cm_svc}/roles")
        target_node = args.get("node", "")
        for role in data.get("items", []):
            if role.get("type") != role_type:
                continue
            if target_node:
                from .tools import _resolve_hostname
                hostname = _resolve_hostname(role.get("hostRef", {}))
                if hostname != target_node:
                    continue
            state = role.get("roleState", "UNKNOWN")
            if state in ("STOPPED", "DOWN", "UNKNOWN"):
                continue  # 维持 recover
            # RUNNING 但不健康 → 不主动制造中断
            return TIER_IRREVERSIBLE, False
        return tier, autonomous

    def _apache_refine_restart(self, svc, svc_info, args, tier, autonomous):
        """Apache: 通过 supervisorctl + jps 检查服务状态

        - STOPPED/EXITED/FATAL/UNKNOWN/STARTING → 维持 recover (重启不会更糟)
        - RUNNING + jps 检测到进程 → 降为 irreversible (不主动制造中断)
        - RUNNING 但 jps 未检测到进程 → 维持 recover (僵尸状态, 需重启清理)

        多节点服务(不指定 node): 只要有任一节点需要恢复, 就维持 recover
        """
        sup_prog = svc_info.get("supervisor_program")
        if not sup_prog:
            return tier, autonomous

        java_class = svc_info.get("java_class")
        target_node = args.get("node", "")
        target_nodes = [target_node] if target_node else svc_info.get("nodes", [])

        from .config import CLUSTER_NODES, JPS_BIN
        from .tools import _node_supervisor_conf
        all_running_healthy = True  # 所有节点都 RUNNING+进程存在 → IRREVERSIBLE
        for n in target_nodes:
            sup_conf = _node_supervisor_conf(n)
            stdout, _, _ = ssh_exec(n, f"supervisorctl -c {sup_conf} status {sup_prog} 2>&1")
            if stdout:
                parts = stdout.split()
                status = parts[1] if len(parts) >= 2 else "UNKNOWN"
                if status in ("STOPPED", "EXITED", "FATAL", "UNKNOWN", "STARTING"):
                    # 至少有一个节点需要恢复 → 维持 recover
                    return tier, autonomous
                if status == "RUNNING":
                    # RUNNING 但需进一步检查进程是否真正存在
                    # RunJar 类型 (Hive) 无法通过 jps 区分具体服务, 信任 supervisor
                    if java_class and java_class != "RunJar":
                        jps_out, _, _ = ssh_exec(n, f"{JPS_BIN} -l 2>/dev/null || jps -l 2>/dev/null")
                        jps_short = java_class.rsplit(".", 1)[-1]
                        process_found = any(java_class in l or jps_short in l
                                           for l in (jps_out or "").split("\n") if l.strip())
                        if not process_found:
                            # 僵尸状态: supervisor 说 RUNNING 但进程不存在 → 允许重启
                            logger.warning(f"{svc} on {n}: supervisor=RUNNING but process not detected (zombie), allowing restart")
                            return tier, autonomous
                    # 该节点 RUNNING + 进程存在 → 继续检查下一个节点
                    continue
            # 无法获取状态 → 维持 recover (保守)
            all_running_healthy = False

        # 所有节点都 RUNNING + 进程存在 → 不主动制造中断
        if all_running_healthy:
            return TIER_IRREVERSIBLE, False
        return tier, autonomous

    # ============================================================
    # §21.4 execute — 四档分支
    # ============================================================

    def execute(self, tool_name, args, session_id=""):
        """安全执行工具 — classify 定级 → 四档分支执行"""
        tier, autonomous = self.classify(tool_name, args)
        self._audit(session_id, tool_name, args, "classified", tier,
                     {"tier": tier, "autonomous": autonomous, "autonomy": self.autonomy})
        print(f"  [GUARDRAIL] {tool_name} tier={tier} autonomous={autonomous} autonomy={self.autonomy}")

        if tier in (TIER_LOW, TIER_MEDIUM):
            return self._exec_low_medium(tool_name, args, tier, session_id)

        if tier == TIER_RECOVER:
            return self._exec_recover(tool_name, args, tier, session_id, autonomous)

        if tier == TIER_REVERSIBLE:
            return self._exec_reversible(tool_name, args, tier, session_id, autonomous)

        if tier == TIER_IRREVERSIBLE:
            return self._exec_irreversible(tool_name, args, tier, session_id, autonomous)

        # 不该到这里
        return self._exec_irreversible(tool_name, args, TIER_IRREVERSIBLE, session_id, False)

    def _exec_low_medium(self, tool_name, args, tier, session_id):
        """低危/中危: 直接执行, 中危事后通知"""
        result = self._do_execute(tool_name, args, tier, session_id)
        if tier == TIER_MEDIUM:
            self._notify(f"[MEDIUM] {tool_name}({args.get('service', '')}) "
                         f"executed, result={result.get('result', 'ok')}")
        return result

    def _exec_recover(self, tool_name, args, tier, session_id, autonomous):
        """recover: 可恢复幂等操作 (如重启已 DOWN 服务)

        autonomous 模式 + 规则允许 → attempt 节流 → 自动执行
        autonomous 模式 + 规则禁止 → 立即拒绝 + 升级告警 (无人审, 不等)
        supervised 模式 → 走审批门 → 等人工
        """
        svc = args.get("service", "")

        # 熔断检查 (§9 保留)
        if self._is_circuit_broken(svc):
            msg = f"熔断: {svc} 连续失败 {self._failure_counts.get(svc, 0)} 次, 已升级人工处理"
            self._audit(session_id, tool_name, args, "circuit_broken", tier)
            logger.warning(msg)
            return {"error": msg, "circuit_broken": True}

        if self.autonomy == "autonomous" and autonomous:
            # §21.5 attempt 节流 → 自动执行
            blocked = self._check_attempt_throttle(tool_name, svc)
            if blocked:
                self._audit(session_id, tool_name, args, "attempt_throttled", tier, blocked)
                return blocked
        elif self.autonomy == "supervised":
            # supervised: 走审批门
            approval = self._request_approval(session_id, tool_name, args, tier,
                                               self._dry_run(tool_name, args))
            if approval["status"] != "approved":
                self._audit(session_id, tool_name, args, "rejected", tier, approval)
                return {"error": "审批未通过", "approval": approval}
        else:
            # autonomous 模式但规则禁止自动执行 → 立即拒绝 + 升级
            msg = f"规则禁止自动执行 {tool_name}({svc}), autonomous 模式下拒绝, 已升级告警"
            self._audit(session_id, tool_name, args, "auto_rejected", tier)
            self._notify(msg)
            return {"error": msg, "escalated": True}

        # 执行
        result = self._do_execute(tool_name, args, tier, session_id)

        # 熔断计数 + attempt 节流副作用
        if self._is_failed(result):
            self._increment_failure(svc)
            count = self._failure_counts.get(svc, 0)
            self._notify(f"[RECOVER] {tool_name}({svc}) 执行失败, "
                         f"连续失败 {count}/{self.max_failures}")
            if count >= self.max_failures:
                self._notify(f"[ALERT] 熔断触发: {svc} 连续失败 {count} 次, "
                             f"后续操作将升级人工处理")
        else:
            self._reset_failure(svc)
        return result

    def _exec_reversible(self, tool_name, args, tier, session_id, autonomous):
        """reversible: 可回撤操作 (先备份→改→reload)

        autonomous 模式 + 规则允许 → attempt 节流 → 自动执行 (强制先备份)
        autonomous 模式 + 规则禁止 → 立即拒绝 + 升级告警
        supervised 模式 → 走审批门
        """
        svc = args.get("service", "")

        if self.autonomy == "autonomous" and autonomous:
            blocked = self._check_attempt_throttle(tool_name, svc)
            if blocked:
                self._audit(session_id, tool_name, args, "attempt_throttled", tier, blocked)
                return blocked
        elif self.autonomy == "supervised":
            approval = self._request_approval(session_id, tool_name, args, tier,
                                               self._dry_run(tool_name, args))
            if approval["status"] != "approved":
                self._audit(session_id, tool_name, args, "rejected", tier, approval)
                return {"error": "审批未通过", "approval": approval}
        else:
            # autonomous 模式但规则禁止自动执行 → 立即拒绝 + 升级
            msg = f"规则禁止自动执行 {tool_name}({svc}), autonomous 模式下拒绝, 已升级告警"
            self._audit(session_id, tool_name, args, "auto_rejected", tier)
            self._notify(msg)
            return {"error": msg, "escalated": True}

        result = self._do_execute(tool_name, args, tier, session_id)
        if self._is_failed(result):
            self._increment_failure(svc)
        else:
            self._reset_failure(svc)
        return result

    def _exec_irreversible(self, tool_name, args, tier, session_id, autonomous):
        """irreversible: 不可逆操作 (永不自动执行)

        autonomous 模式 → 直接放弃 + 升级告警 (不等审批, 无人审)
        supervised 模式 → 走审批门, 超时=拒绝
        """
        svc = args.get("service", "")

        if self.autonomy == "supervised":
            # supervised: 等人工审批
            approval = self._request_approval(session_id, tool_name, args, tier,
                                               self._dry_run(tool_name, args))
            if approval["status"] != "approved":
                self._audit(session_id, tool_name, args, "rejected", tier, approval)
                return {"error": "审批未通过", "approval": approval}
            return self._do_execute(tool_name, args, tier, session_id)
        else:
            # autonomous: 永不自动执行不可逆操作 → 立即拒绝 + 升级
            msg = (f"[IRREVERSIBLE] {tool_name}({svc}) 属不可逆操作, "
                   f"autonomous 模式下拒绝自动执行, 已升级告警")
            self._audit(session_id, tool_name, args, "auto_rejected", tier)
            self._notify(msg)
            logger.warning(msg)
            return {"error": "不可逆操作, autonomous 模式拒绝", "escalated": True}

    # ============================================================
    # §21.5 attempt 节流 (尝试侧, 与熔断互补)
    # ============================================================

    def _check_attempt_throttle(self, tool_name, target):
        """检查 attempt 节流: 观察窗口内执行次数 + 冷却间隔

        Returns: {"error": ..., "throttled": True} 或 None (允许)
        """
        count, last_ts = self.store.count_audit_attempts(
            tool_name, target, self.attempt_window)

        if count >= self.max_attempts:
            msg = (f"attempt 节流: {tool_name}({target}) 在 {self.attempt_window}s 内"
                   f"已执行 {count}/{self.max_attempts} 次, 升级人工处理")
            logger.warning(msg)
            return {"error": msg, "throttled": True, "escalated": True}

        if last_ts and time.time() - last_ts < self.attempt_cooldown:
            remaining = int(self.attempt_cooldown - (time.time() - last_ts))
            msg = (f"attempt 冷却: {tool_name}({target}) 上次执行 "
                   f"{int(time.time()-last_ts)}s 前, 需等待 {remaining}s")
            return {"error": msg, "throttled": True, "cooldown_remaining": remaining}

        return None

    # ============================================================
    # 通用: 执行 + 审计 + 审批 + 熔断 + dry-run
    # ============================================================

    def _do_execute(self, tool_name, args, tier, session_id):
        """执行工具 + 记录审计"""
        # M5: write_runbook 需要关联 session_id (用于追溯回写来源)
        if tool_name == "write_runbook" and session_id:
            args = {**args, "session_id": session_id}
        result = execute_tool(tool_name, args)
        self._audit(session_id, tool_name, args, "executed", tier, result)
        return result

    def _dry_run(self, tool_name, args):
        """dry-run 预览"""
        svc = args.get("service", "")
        node = args.get("node", "")
        svc_info = SERVICE_MAP.get(svc, {})
        nodes = [node] if node else svc_info.get("nodes", [])
        if tool_name == "restart_service":
            if CLUSTER_BACKEND == "cdh":
                action = f"CM API commands/start → 启动 {svc}"
                impact = "仅启动 STOPPED 角色, 不影响运行中的"
            else:
                action = f"supervisorctl restart → 重启 {svc}"
                impact = "重启指定节点的服务进程"
            return {
                "tool": tool_name,
                "action": action,
                "target_nodes": nodes,
                "tier": TIER_RECOVER,
                "reversible": True,
                "impact": impact,
                "message": f"将重启 {svc} (nodes={nodes})",
            }
        if tool_name == "edit_remote_config":
            return {
                "tool": tool_name,
                "action": f"备份 → 修改 {args.get('file', '')} → reload {svc}",
                "tier": TIER_REVERSIBLE,
                "reversible": True,
                "impact": "修改前自动备份 .bak.<ts>, 可回滚",
                "message": f"将修改 {args.get('file', '')} 并 reload {svc}",
            }
        return {"tool": tool_name, "tier": TIER_IRREVERSIBLE,
                "message": f"dry-run preview for {tool_name}"}

    def _request_approval(self, session_id, tool_name, args, tier, dry_run, timeout=600):
        """请求审批 — supervised 模式阻塞等待人工审批
        
        去重：如果相同工具+相同参数已有pending审批，直接等待该审批结果
        """
        svc = args.get("service", "")
        node = args.get("node", "")
        
        # 检查是否已有相同工具+相同参数的pending审批
        with self.store.lock:
            existing = self.store.conn.execute(
                "SELECT id FROM approvals WHERE tool_name=? AND status='pending' "
                "AND json_extract(args_json, '$.service')=? "
                "AND json_extract(args_json, '$.node')=? "
                "ORDER BY ts DESC LIMIT 1",
                (tool_name, svc, node)
            ).fetchone()
            if existing:
                approval_id = existing[0]
                logger.info(f"复用已有pending审批 {approval_id} for {tool_name}({svc})")
            else:
                approval_id = str(uuid.uuid4())[:8]
                self.store.conn.execute(
                    "INSERT INTO approvals(id,session_id,tool_name,args_json,"
                    "risk_level,dry_run_json,status,ts) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (approval_id, session_id, tool_name,
                     json.dumps(args, ensure_ascii=False), tier,
                     json.dumps(dry_run, ensure_ascii=False),
                     "pending", int(time.time()))
                )
                self.store.conn.commit()

        # 等待审批结果 (新创建或复用已有 pending 审批)
        poll_interval = 2
        waited = 0
        while waited < timeout:
            with self.store.lock:
                row = self.store.conn.execute(
                    "SELECT status, decided_by FROM approvals WHERE id=?",
                    (approval_id,)
                ).fetchone()
            if row and row[0] != "pending":
                return {"id": approval_id, "status": row[0],
                        "decided_by": row[1] or ""}
            time.sleep(poll_interval)
            waited += poll_interval
        with self.store.lock:
            self.store.conn.execute(
                "UPDATE approvals SET status=?, decided_by=?, decided_at=? WHERE id=?",
                ("rejected", "timeout", int(time.time()), approval_id)
            )
            self.store.conn.commit()
        return {"id": approval_id, "status": "rejected",
                "decided_by": "timeout", "message": "审批超时, 已自动拒绝"}

    # ---- 熔断 (§9 保留, 失败侧; 类级共享跨会话) ----

    def _is_circuit_broken(self, service):
        with Guardrail._circuit_lock:
            count = Guardrail._failure_counts.get(service, 0)
            if count >= self.max_failures:
                last_ts = Guardrail._last_failure_ts.get(service, 0)
                if time.time() - last_ts < self.circuit_cooldown:
                    return True
                else:
                    Guardrail._failure_counts[service] = 0
                    Guardrail._last_failure_ts.pop(service, None)
            return False

    def _increment_failure(self, service):
        with Guardrail._circuit_lock:
            Guardrail._failure_counts[service] = \
                Guardrail._failure_counts.get(service, 0) + 1
            Guardrail._last_failure_ts[service] = time.time()

    def _reset_failure(self, service):
        with Guardrail._circuit_lock:
            Guardrail._failure_counts.pop(service, None)
            Guardrail._last_failure_ts.pop(service, None)

    @staticmethod
    def _is_failed(result):
        if not result:
            return True
        if isinstance(result, dict):
            if result.get("error"):
                return True
            if result.get("circuit_broken"):
                return True
            if result.get("throttled"):
                return True
            r = result.get("result", "")
            return r in ("failed", "error", "unsupported")
        return False

    # ---- 审计日志 ----

    def _audit(self, session_id, tool_name, args, status, tier, result=None):
        """审计日志 — 每次工具调用写 SQLite"""
        with self.store.lock:
            self.store.conn.execute(
                "INSERT INTO audit_log(session_id,tool_name,args_json,"
                "risk_level,status,result_json,ts) VALUES(?,?,?,?,?,?,?)",
                (session_id, tool_name,
                 json.dumps(args, ensure_ascii=False), tier, status,
                 json.dumps(result, ensure_ascii=False) if result else "",
                 int(time.time()))
            )
            self.store.conn.commit()

    # ---- 通知 ----

    @staticmethod
    def _notify(message):
        print(f"  [GUARDRAIL] {message}")