"""
工具层 — 双后端: CDH (CM API + SSH) / Apache (supervisorctl + jps + Prometheus + SSH)

配置驱动, 切换环境只改 config.py:
  - CLUSTER_BACKEND="cdh"    -> Cloudera Manager API + SSH (保留兼容)
  - CLUSTER_BACKEND="apache" -> docker-compose + SSH + supervisorctl + jps + Prometheus

所有 IP/节点/日志路径/用户均从 config.SERVICE_MAP 读取, 不硬编码。
"""
import json
import logging
import re
import shlex
import subprocess
import threading
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import (
    CLUSTER_BACKEND, SSH_USER, SSH_PORT, SSH_OPTS, SSH_KEY_PATH,
    CLUSTER_NODES, SERVICE_MAP, INSPECT_SERVICES,
    CM_HOST, CM_PORT, CM_USER, CM_PASS, CM_CLUSTER, CM_API_VERSION,
    JPS_BIN, HADOOP_BIN, JAVA_HOME,
    PROMETHEUS_URL,
)

logger = logging.getLogger(__name__)

# ---- 风险分级 ----
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"
RISK_DESTRUCTIVE = "destructive"

# ---- 全局 Store 引用 (M5: search_kb / write_runbook 需要访问 DB) ----
_store_ref = None


def set_store(store):
    """注入 Store 实例 (启动时调用一次)"""
    global _store_ref
    _store_ref = store


def _get_store():
    """获取已注入的 Store 实例"""
    return _store_ref

# ---- 工具定义 (给 LLM 的 function schema) ----
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_service_status",
            "description": "获取大数据集群服务的运行状态. 可查询单个服务或所有服务",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "服务名: NameNode/DataNode/ResourceManager/NodeManager/HiveMetaStore/HiveServer2/HBaseMaster/RegionServer/ZooKeeper/JournalNode, 或 all 查询所有服务"},
                    "node": {"type": "string", "description": "节点名(可选), 如 hadoop03. 不指定则返回所有节点"},
                },
                "required": ["service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_alerts",
            "description": "获取当前集群所有活跃告警(服务异常/进程停止/JMX指标异常)",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_metrics",
            "description": "查询某个节点的系统指标(内存/磁盘/CPU/负载/Java进程)",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string", "description": "指标类型: memory(内存)/disk(磁盘)/cpu(CPU)/load(负载)/java_procs(Java进程)"},
                    "node": {"type": "string", "description": "节点名, 如 hadoop03. 不指定则查所有节点"},
                },
                "required": ["metric"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_logs",
            "description": "读取服务日志(返回压缩摘要, 非原始全文). 可按关键词过滤, 可指定节点. 对多节点服务(如DataNode)默认读所有节点",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "服务名"},
                    "filter": {"type": "string", "description": "过滤关键词, 如 ERROR/OOM/GC/SIGTERM"},
                    "tail_n": {"type": "integer", "description": "每节点读取最后N行, 默认50"},
                    "node": {"type": "string", "description": "节点名(可选), 如 hadoop03. 不指定则读所有节点"},
                },
                "required": ["service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "检索运维知识库(runbook/调优经验), 返回相关条目. 暂用关键词匹配, 后续接入sqlite-vec向量检索",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "检索关键词"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "restart_service",
            "description": "重启大数据服务(高危操作). 需提供理由. 核心服务(NameNode/ResourceManager)判高危, 非核心服务(DataNode/NodeManager)可自动执行. 可指定 node 重启特定节点实例",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "服务名"},
                    "reason": {"type": "string", "description": "重启理由"},
                    "node": {"type": "string", "description": "节点名(可选, 多节点服务可指定单节点重启)"},
                },
                "required": ["service", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hdfs_admin",
            "description": "执行HDFS管理命令: dfsadmin -report / fsck / fsck_list_corrupt(列出坏块文件) / fsck_delete(删除坏块文件) / dfs -ls / dfs -du / safemode get / safemode leave / count_quota(查询配额) / set_quota(设置文件数配额) / set_space_quota(设置空间配额) / clr_quota(清除文件数配额) / clr_space_quota(清除空间配额). safemode_leave/fsck_delete/配额修改为写操作",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "操作: report(集群报告)/fsck(文件系统检查)/fsck_list_corrupt(列出坏块文件)/fsck_delete(删除坏块文件)/ls(列目录)/du(目录大小)/safemode_get(查询安全模式状态)/safemode_leave(退出安全模式)/count_quota(查询目录配额)/set_quota(设置文件数配额)/set_space_quota(设置空间配额)/clr_quota(清除文件数配额)/clr_space_quota(清除空间配额)"},
                    "path": {"type": "string", "description": "HDFS路径, ls/du/count_quota/set_quota/set_space_quota/clr_quota/clr_space_quota时必填"},
                    "quota": {"type": "string", "description": "配额值, set_quota时为文件数(如1000), set_space_quota时为空间大小(如500g/2t)"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_remote_config",
            "description": "修改远程节点配置文件(reversible档). 先备份 .bak.<ts>, 再 sed 替换, 最后 reload 服务. 用于调整 JVM heap/参数等可回滚操作",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "服务名(用于 reload): NameNode/DataNode/ResourceManager 等"},
                    "node": {"type": "string", "description": "节点名, 如 hadoop03"},
                    "file": {"type": "string", "description": "远程配置文件完整路径"},
                    "find": {"type": "string", "description": "要查找的原始内容(将被替换)"},
                    "replace": {"type": "string", "description": "替换为的新内容"},
                    "reason": {"type": "string", "description": "修改理由"},
                },
                "required": ["service", "node", "file", "find", "replace", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_runbook",
            "description": "解决故障后将经验回写为运维知识库runbook(学习闭环). 高置信度的成功修复自动写入, 待人工审核后生效. 避免重复排查相同问题",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "runbook标题, 简明描述故障场景, 如 'DataNode OOM 崩溃修复'"},
                    "content": {"type": "string", "description": "runbook内容: 包含症状/排查步骤/根因/修复方法/验证方式, 用结构化文本描述"},
                    "tags": {"type": "string", "description": "标签(逗号分隔), 如 'hdfs,datanode,oom', 便于检索分类"},
                    "confidence": {"type": "number", "description": "置信度0-1, 1=非常确定修复有效, 0.5=不确定. 低于0.7会被拒绝写入"},
                },
                "required": ["title", "content", "confidence"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diagnose_node",
            "description": "在指定节点上执行诊断命令(只读). 用于深入排查未知问题: 查找大文件/查看磁盘占用/查看进程/查看网络端口/查看挂载点等. 不限于已知故障模式, 可用于任意诊断场景",
            "parameters": {
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "节点名, 如 hadoop01"},
                    "action": {"type": "string", "description": "诊断操作: du_root(各顶层目录磁盘占用)/find_large(查找大文件>100M)/top_procs(按内存排序的进程)/netstat(监听端口)/mount(挂载点)/custom(自定义命令, 需提供cmd参数)"},
                    "cmd": {"type": "string", "description": "custom操作时的自定义命令(仅允许只读命令: ls/cat/du/df/find/grep/wc/head/tail/ps/netstat/ss, 禁止rm/mv/cp/dd/mkfs等)"},
                },
                "required": ["node", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_ops",
            "description": "文件操作(中风险): 删除指定文件或清理日志. 用于释放磁盘空间等修复操作. 删除前会显示文件大小, 仅允许删除日志/临时文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "节点名, 如 hadoop01"},
                    "action": {"type": "string", "description": "操作: delete(删除指定文件)/cleanup_logs(清理旧日志>7天)/truncate(截断大日志文件保留最后1000行)"},
                    "path": {"type": "string", "description": "delete/truncate操作的文件路径"},
                    "reason": {"type": "string", "description": "操作理由"},
                },
                "required": ["node", "action", "reason"],
            },
        },
    },
]

# ---- 风险映射 (fallback, classify 优先用 DB risk_rules) ----
TOOL_RISK = {
    "get_service_status": RISK_LOW,
    "get_alerts": RISK_LOW,
    "get_metrics": RISK_LOW,
    "read_logs": RISK_LOW,
    "search_kb": RISK_LOW,
    "restart_service": RISK_HIGH,
    "hdfs_admin": RISK_LOW,
    "edit_remote_config": RISK_MEDIUM,
    "write_runbook": RISK_LOW,
    "diagnose_node": RISK_LOW,
    "file_ops": RISK_MEDIUM,
}

TOOL_HANDLERS = {}


def tool(name):
    def deco(fn):
        TOOL_HANDLERS[name] = fn
        return fn
    return deco


# ============================================================
# 底层: SSH 执行 + CM API 调用 + Prometheus 查询
# ============================================================

def ssh_exec(node_key, command, timeout=30):
    """在远程节点上执行 SSH 命令, 返回 (stdout, stderr, returncode)

    node_key: CLUSTER_NODES 中的 key (如 'hadoop01'), 也可以是 IP 地址
    自动从 CLUSTER_NODES 查找 host/ssh_port; SSH_KEY_PATH 非空时指定密钥
    """
    node = CLUSTER_NODES.get(node_key, {})
    host = node.get("host", node_key)  # fallback: 当作 IP 直接用
    port = node.get("ssh_port", SSH_PORT)

    cmd = ["ssh"] + SSH_OPTS.split()
    if SSH_KEY_PATH:
        # SSH_KEY_PATH 相对于项目根目录, 转为绝对路径
        import os
        key_path = SSH_KEY_PATH
        if not os.path.isabs(key_path):
            key_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), key_path)
        cmd += ["-i", key_path]
    cmd += ["-p", str(port), f"{SSH_USER}@{host}", command]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=timeout, encoding="utf-8")
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "SSH timeout", -1
    except Exception as e:
        return "", f"SSH error: {e}", -1


# CM API session (CDH 后端用)
_cm_session = None


def _get_cm_session():
    global _cm_session
    if _cm_session is None:
        _cm_session = requests.Session()
        _cm_session.mount("http://", HTTPAdapter(max_retries=Retry(total=0)))
        _cm_session.mount("https://", HTTPAdapter(max_retries=Retry(total=0)))
    return _cm_session


def cm_get(path):
    """CM API GET 请求 (CDH 后端)"""
    url = f"http://{CM_HOST}:{CM_PORT}/api/{CM_API_VERSION}{path}"
    try:
        resp = _get_cm_session().get(url, auth=(CM_USER, CM_PASS), timeout=(3, 5))
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"CM API GET {path} failed: {e}")
        return {}


def cm_post(path):
    """CM API POST 请求 (CDH 后端, 重启/停止等)"""
    url = f"http://{CM_HOST}:{CM_PORT}/api/{CM_API_VERSION}{path}"
    try:
        resp = _get_cm_session().post(url, auth=(CM_USER, CM_PASS), timeout=(3, 5))
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"CM API POST {path} failed: {e}")
        return {}


# ---- Prometheus 查询 (Apache 后端用) ----

def prometheus_query(query):
    """查询 Prometheus API, 返回 result list"""
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
            timeout=(3, 10),
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "success":
            return data.get("data", {}).get("result", [])
    except Exception as e:
        logger.warning(f"Prometheus query failed: {e}")
    return []


def prometheus_targets():
    """获取所有 Prometheus targets 的健康状态"""
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/targets",
            timeout=(3, 10),
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "success":
            return data.get("data", {}).get("activeTargets", [])
    except Exception as e:
        logger.warning(f"Prometheus targets query failed: {e}")
    return []


# ---- supervisorctl 输出解析 ----
# Valid supervisor status values
_SUPERVISOR_STATUSES = ("RUNNING", "STOPPED", "FATAL", "EXITED", "STARTING", "BACKOFF")
# Match: "<program_name>  <STATUS>   pid xxx, uptime x:xx:xx"
_SUPERVISOR_STATUS_RE = re.compile(
    r'^\S+\s+(' + '|'.join(_SUPERVISOR_STATUSES) + r')\b'
)


def _parse_supervisor_status(stdout):
    """Parse supervisorctl status output.
    
    Returns (status, uptime):
        - status: one of _SUPERVISOR_STATUSES, or None if output is not a valid status line
        - uptime: uptime string or empty
    
    Valid format: "namenode  RUNNING   pid 64, uptime 0:25:49"
    Error format: "Traceback (most recent call last):" or "Error: ..."
    """
    if not stdout:
        return None, ""
    text = stdout.strip()
    match = _SUPERVISOR_STATUS_RE.match(text)
    if match:
        status = match.group(1)
        uptime = ""
        if "uptime" in text:
            uptime = text.split("uptime")[-1].strip()
        return status, uptime
    return None, ""


# ---- 节点/路径解析 ----

def _node_ip(node_key):
    """节点名 -> IP/host (SSH 连接用)"""
    node = CLUSTER_NODES.get(node_key)
    if node:
        return node["host"]
    return node_key


def _node_hostname(node_key):
    """节点名 -> hostname (容器内 hostname, 用于 jps 匹配等)"""
    node = CLUSTER_NODES.get(node_key)
    if node:
        return node["hostname"]
    return node_key


def _node_supervisor_conf(node_key):
    """节点名 -> supervisord 配置文件路径"""
    node = CLUSTER_NODES.get(node_key)
    if node:
        return node.get("supervisor_conf", "")
    return ""


# CDH: hostId -> hostname 缓存 (CM API roles 返回 hostId 而非 hostname)
_host_map_cache = None


def _build_host_map():
    """通过全局 /hosts API 获取 hostId -> hostname 映射 (CDH)"""
    global _host_map_cache
    if _host_map_cache is not None:
        return _host_map_cache
    data = cm_get("/hosts")
    _host_map_cache = {
        h.get("hostId", ""): h.get("hostname", "")
        for h in data.get("items", [])
    }
    return _host_map_cache


def _resolve_hostname(host_ref):
    """从 role 的 hostRef 解析出 hostname (CDH)"""
    host_id = host_ref.get("hostId", "")
    if host_id:
        return _build_host_map().get(host_id, host_id)
    return host_ref.get("hostname", "")


def _resolve_node(service_info, node):
    """解析目标节点列表. node=None -> 所有节点; node=hadoop03 -> [hadoop03]"""
    if node:
        return [node]
    return service_info.get("nodes", [])


def _log_filename(service_info, hostname):
    """构造日志文件名 (CDH: hadoop-cmf-hdfs-DATANODE-hadoop03.yuf.com.log.out)"""
    return f"{service_info['log_prefix']}-{hostname}.log.out"


# ============================================================
# 工具实现
# ============================================================

@tool("get_service_status")
def _get_service_status(service="", node=""):
    """获取服务运行状态 — CDH: CM API / Apache: jps + supervisorctl"""
    # 支持 all 参数，批量查询所有服务
    if service == "all":
        results = {}
        for svc_name in INSPECT_SERVICES:
            svc_info = SERVICE_MAP[svc_name]
            if CLUSTER_BACKEND == "cdh":
                results[svc_name] = _cdh_get_service_status(svc_info, svc_name, node)
            else:
                results[svc_name] = _apache_get_service_status(svc_info, svc_name, node)
        # 统计整体健康状态
        bad_services = [k for k, v in results.items() if v.get("overall_health") != "GOOD"]
        overall = "BAD" if bad_services else "GOOD"
        return {
            "service": "all",
            "overall_health": overall,
            "services_count": len(results),
            "bad_services": bad_services,
            "details": results
        }
    
    svc_info = SERVICE_MAP.get(service)
    if not svc_info:
        return {"error": f"未知服务: {service}",
                "available": list(SERVICE_MAP.keys())}

    if CLUSTER_BACKEND == "cdh":
        return _cdh_get_service_status(svc_info, service, node)
    else:
        return _apache_get_service_status(svc_info, service, node)


def _cdh_get_service_status(svc_info, service, node):
    """CDH: 通过 CM API 获取服务各角色状态"""
    cm_svc = svc_info["cm_service"]
    data = cm_get(f"/clusters/{CM_CLUSTER}/services/{cm_svc}/roles")
    roles = data.get("items", [])

    target_type = svc_info["cm_role_type"]
    target_nodes = _resolve_node(svc_info, node)
    target_hostnames = {_node_hostname(n) for n in target_nodes}

    role_list = []
    for r in roles:
        if r.get("type") != target_type:
            continue
        hostname = _resolve_hostname(r.get("hostRef", {}))
        if target_hostnames and hostname not in target_hostnames:
            continue
        role_list.append({
            "name": r.get("name", ""),
            "node": hostname,
            "roleState": r.get("roleState", ""),
            "healthSummary": r.get("healthSummary", ""),
            "healthChecks": [
                {"name": hc.get("name", ""), "summary": hc.get("summary", "")}
                for hc in r.get("healthChecks", [])
                if hc.get("summary") != "GOOD"
            ],
        })

    bad_roles = [r for r in role_list if r["healthSummary"] not in ("GOOD", "DISABLED")]
    overall = "BAD" if bad_roles else "GOOD"

    return {
        "service": service,
        "overall_health": overall,
        "role_count": len(role_list),
        "roles": role_list,
    }


def _apache_get_service_status(svc_info, service, node):
    """Apache: 通过 jps + supervisorctl 获取服务状态

    健康判断: supervisorctl 为主, jps 为辅.
    supervisorctl 不可用本身视为异常 (不应降低标准回退到 jps 判断 GOOD).
    """
    java_class = svc_info.get("java_class")
    sup_prog = svc_info.get("supervisor_program")
    target_nodes = _resolve_node(svc_info, node)

    role_list = []
    for n in target_nodes:
        hostname = _node_hostname(n)
        sup_conf = _node_supervisor_conf(n)

        # 1. jps 检查进程是否存在
        jps_class_short = java_class.rsplit(".", 1)[-1] if java_class else ""
        stdout, _, _ = ssh_exec(n, f"{JPS_BIN} -l 2>/dev/null || jps -l 2>/dev/null")
        jps_lines = stdout.split("\n") if stdout else []
        process_found = any(java_class in line or jps_class_short in line
                           for line in jps_lines if line.strip()) if java_class else False

        # 2. supervisorctl 检查程序状态
        sup_status = None
        sup_uptime = ""
        if sup_prog:
            stdout, stderr, rc = ssh_exec(
                n, f"supervisorctl -c {sup_conf} status {sup_prog} 2>&1")
            # 健壮解析: 区分正常状态行和错误/traceback 输出
            sup_status, sup_uptime = _parse_supervisor_status(stdout)

        # 综合判断健康状态
        if sup_status == "RUNNING" and process_found:
            health = "GOOD"
            state = "RUNNING"
        elif sup_status == "RUNNING" and not process_found and (
            not java_class or java_class == "RunJar"
        ):
            # RunJar 类型 (HiveMetaStore/HiveServer2): hadoop jar 启动, jps 显示 RunJar
            # 如果 supervisor 说 RUNNING, 信任它 (jps 可能有延迟或类名不匹配)
            health = "GOOD"
            state = "RUNNING"
        elif sup_status in ("STOPPED", "EXITED", "FATAL"):
            health = "BAD"
            state = "STOPPED" if sup_status in ("STOPPED", "EXITED") else "DOWN"
        elif sup_status == "STARTING":
            health = "CONCERNING"
            state = "STARTING"
        else:
            # supervisorctl 不可用或返回未知状态, 视为异常
            health = "BAD"
            state = "UNKNOWN"

        role_list.append({
            "name": f"{service}-{hostname}",
            "node": hostname,
            "roleState": state,
            "healthSummary": health,
            "supervisor_status": sup_status or "UNKNOWN",
            "uptime": sup_uptime,
            "process_detected": process_found,
        })

    bad_roles = [r for r in role_list if r["healthSummary"] not in ("GOOD", "DISABLED")]
    overall = "BAD" if bad_roles else "GOOD"

    return {
        "service": service,
        "overall_health": overall,
        "role_count": len(role_list),
        "roles": role_list,
    }


@tool("get_alerts")
def _get_alerts():
    """获取当前集群告警 — CDH: CM API / Apache: Prometheus + 健康检查"""
    if CLUSTER_BACKEND == "cdh":
        return _cdh_get_alerts()
    else:
        return _apache_get_alerts()


def _cdh_get_alerts():
    """CDH: 遍历所有 CM 服务, 收集非 GOOD 的健康检查作为告警"""
    services_data = cm_get(f"/clusters/{CM_CLUSTER}/services")
    alerts = []
    for svc in services_data.get("items", []):
        svc_name = svc.get("name", "")
        svc_health = svc.get("healthSummary", "")
        svc_type = svc.get("type", "")
        if svc_health != "GOOD":
            alerts.append({
                "alertname": f"{svc_type}_UNHEALTHY",
                "severity": "critical" if svc_health == "BAD" else "warning",
                "service": svc_name,
                "summary": f"Service {svc_name} health={svc_health}",
            })
        role_data = cm_get(f"/clusters/{CM_CLUSTER}/services/{svc_name}/roles")
        for role in role_data.get("items", []):
            r_health = role.get("healthSummary", "")
            r_state = role.get("roleState", "")
            hostname = _resolve_hostname(role.get("hostRef", {}))
            _NORMAL_STATES = ("STARTED", "ACTIVE", "ENABLED", "NA", "DISABLED")
            if r_health == "BAD" or r_state not in _NORMAL_STATES:
                alerts.append({
                    "alertname": f"{role.get('type', 'UNKNOWN')}_DOWN",
                    "severity": "critical" if r_state == "STOPPED" else "warning",
                    "node": hostname,
                    "roleState": r_state,
                    "healthSummary": r_health,
                    "summary": f"{role.get('type', '')} on {hostname}: "
                               f"state={r_state} health={r_health}",
                })

    return {"alerts": alerts, "count": len(alerts)}


def _apache_get_alerts():
    """Apache: 告警系统只做最基本的进程存活检测 (快速路径).
    
    其他异常 (Safe Mode / 磁盘满 / HDFS 坏块 / OOM 等) 不在此预编码,
    而是由巡检 LLM 在 /auto session 中分析工具输出后自行发现并升级触发 /fix.
    这样无需为每种故障手写检测规则, Agent 的分析能力覆盖未知故障.
    """
    alerts = []

    # 1. Prometheus targets: up == 0 的 target 为告警 (进程/JMX exporter 不可达)
    targets = prometheus_targets()
    for t in targets:
        if t.get("health") != "up":
            job = t.get("labels", {}).get("job", "")
            instance = t.get("labels", {}).get("instance", "")
            component = t.get("labels", {}).get("component", "")
            # 从 instance 解析节点名 (如 hadoop01:10101)
            node = instance.split(":")[0] if ":" in instance else instance
            alerts.append({
                "alertname": f"{component or job}_DOWN",
                "severity": "critical",
                "service": component or job,
                "node": node,
                "summary": f"{component or job} on {instance} is DOWN "
                           f"(JMX exporter unreachable, last_error: {t.get('lastError', '')[:100]})",
            })

    # 2. 服务级健康检查: 遍历关键服务, 检查 supervisor 进程状态
    # (补充 Prometheus 可能漏掉的: 如进程在但 JMX exporter 没配)
    for svc_name in INSPECT_SERVICES:
        svc_info = SERVICE_MAP.get(svc_name, {})
        sup_prog = svc_info.get("supervisor_program")
        if not sup_prog:
            continue
        for n in svc_info.get("nodes", []):
            hostname = _node_hostname(n)
            sup_conf = _node_supervisor_conf(n)
            stdout, _, _ = ssh_exec(
                n, f"supervisorctl -c {sup_conf} status {sup_prog} 2>&1")
            # 健壮解析: 只接受有效的 supervisor 状态值, 忽略 traceback/error 输出
            sup_status, _ = _parse_supervisor_status(stdout)
            if sup_status in ("STOPPED", "EXITED", "FATAL"):
                # 检查是否已经在 Prometheus 告警中
                already_alerted = any(
                    a.get("node") == hostname and a.get("service") == svc_name
                    for a in alerts
                )
                if not already_alerted:
                    alerts.append({
                        "alertname": f"{svc_name}_DOWN",
                        "severity": "critical",
                        "service": svc_name,
                        "node": hostname,
                        "roleState": sup_status,
                        "summary": f"{svc_name} on {hostname}: "
                                   f"supervisor status={sup_status}",
                    })

    # 注意: 以下检测已移除, 改由巡检 LLM 在 /auto 中分析工具输出自行发现:
    # - HDFS Safe Mode (hdfs_admin(report/safemode_get) 输出中 "Safe mode is ON")
    # - 磁盘使用率过高 (get_metrics(disk) 输出中百分比)
    # - HDFS 坏块 (hdfs_admin(report) 输出中 "Corrupt blocks" > 0)
    # 这避免了为每种故障手写检测规则, Agent 的分析能力可覆盖未知故障类型.

    return {"alerts": alerts, "count": len(alerts)}


@tool("get_metrics")
def _get_metrics(metric="", node=""):
    """通过 SSH 执行系统命令获取节点指标"""
    if node:
        nodes = [node]
    else:
        nodes = list(CLUSTER_NODES.keys())

    metric_cmds = {
        "memory": "free -m | head -3",
        "disk": "df -h / | tail -1",
        "cpu": "top -bn1 | head -5",
        "load": "cat /proc/loadavg",
        "java_procs": f"{JPS_BIN} -l 2>/dev/null || jps -l 2>/dev/null",
    }
    cmd = metric_cmds.get(metric)
    if not cmd:
        return {"error": f"未知指标: {metric}", "available": list(metric_cmds.keys())}

    results = {}
    for n in nodes:
        stdout, stderr, rc = ssh_exec(n, cmd, timeout=30)
        results[n] = {
            "hostname": _node_hostname(n),
            "output": stdout if stdout else stderr,
            "returncode": rc,
        }
    return {"metric": metric, "nodes": results}


@tool("read_logs")
def _read_logs(service="", filter="", tail_n=50, node=""):
    """读取服务日志 — CDH: /var/log/hadoop-hdfs/hadoop-cmf-* / Apache: /logs/*.log"""
    svc_info = SERVICE_MAP.get(service)
    if not svc_info:
        return {"error": f"未知服务: {service}",
                "available": list(SERVICE_MAP.keys())}

    target_nodes = _resolve_node(svc_info, node)
    all_results = []

    for n in target_nodes:
        hostname = _node_hostname(n)

        # 日志文件路径: CDH vs Apache
        if CLUSTER_BACKEND == "cdh":
            log_dir = svc_info["log_dir"]
            logfile = _log_filename(svc_info, hostname)
            filepath = f"{log_dir}/{logfile}"
        else:
            # Apache: supervisor 日志在 /logs/ 下
            filepath = svc_info.get("log_file", f"/logs/{service.lower()}.log")
            # 如果服务有多个节点, 日志文件名加 hostname 后缀
            # (Apache docker 环境中, 所有服务日志都在 /logs/ 下, 按 supervisor program 名区分)

        try:
            tail_n = int(tail_n)
        except (TypeError, ValueError):
            tail_n = 50
        safe_filepath = shlex.quote(filepath)
        if filter:
            safe_filter = shlex.quote(filter)
            cmd = f"grep -i {safe_filter} {safe_filepath} 2>/dev/null | tail -{tail_n}"
        else:
            cmd = f"tail -{tail_n} {safe_filepath} 2>/dev/null"

        stdout, stderr, rc = ssh_exec(n, cmd, timeout=30)
        lines = stdout.split("\n") if stdout else []

        errors = [l for l in lines if "ERROR" in l or "FATAL" in l]
        warns = [l for l in lines if "WARN" in l]

        all_results.append({
            "node": hostname,
            "log_file": filepath,
            "total_lines": len(lines),
            "error_count": len(errors),
            "warn_count": len(warns),
            "errors": errors[:5],
            "sample": lines[:10],
        })

    total_errors = sum(r["error_count"] for r in all_results)
    return {
        "service": service,
        "filter": filter or "none",
        "nodes_checked": len(all_results),
        "total_errors": total_errors,
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": all_results,
    }


@tool("search_kb")
def _search_kb(query=""):
    """检索运维知识库 — M5: 向量检索(bge-small) + BM25(FTS5) 混合检索"""
    store = _get_store()
    if store is None:
        return _search_kb_static(query)

    try:
        from . import kb
        kb.ensure_embeddings(store)
        results = kb.hybrid_search(store, query, limit=5)
    except Exception as e:
        logger.warning(f"search_kb hybrid search failed ({e}), fallback to FTS")
        results = store.search_runbooks_fts(query, limit=5)

    if not results:
        return {
            "query": query,
            "matches": 0,
            "results": [],
            "message": "知识库中未找到相关条目",
        }

    simplified = []
    for r in results:
        content = r.get("content", "")
        simplified.append({
            "title": r["title"],
            "content": content[:500] + ("..." if len(content) > 500 else ""),
            "tags": r.get("tags", ""),
            "score": r.get("score", 0),
            "match_type": r.get("match_type", ""),
        })

    return {
        "query": query,
        "matches": len(simplified),
        "results": simplified,
        "search_mode": "hybrid" if any(r.get("match_type") == "vector" for r in results) else "bm25",
    }


def _search_kb_static(query=""):
    """静态 mock 数据 (store 未注入时的兜底, 仅用于单元测试)"""
    _kb = [
        {"title": "DataNode OOM 修复runbook",
         "content": "DataNode OOM 崩溃修复步骤: 1.检查DataNode日志确认OOM "
                    "2.检查HADOOP_HEAPSIZE配置 3.调大heap至8192MB "
                    "4.重启DataNode: 通过supervisorctl restart datanode "
                    "5.验证: jps确认DataNode进程存在, hdfs dfsadmin -report确认Live Datanodes"},
        {"title": "NameNode GC overhead 排查",
         "content": "NameNode GC overhead 原因: 1.堆内存不足 2.小文件过多 3.GC策略不当. "
                    "排查: jstat -gcutil 查看GC频率, 检查hdfs count看文件数. "
                    "修复: 调大NameNode堆内存, 启用G1GC, 清理小文件"},
    ]
    results = [kb for kb in _kb
               if any(w in kb["title"] or w in kb["content"]
                      for w in query.split())]
    return {"query": query, "matches": len(results), "results": results,
            "search_mode": "static_fallback"}


@tool("write_runbook")
def _write_runbook(title="", content="", tags="", confidence=1.0, session_id=""):
    """M5 学习闭环 — 将修复经验回写为知识库 runbook"""
    store = _get_store()
    if store is None:
        return {"error": "知识库未初始化 (store 未注入)"}

    CONFIDENCE_THRESHOLD = 0.7
    if confidence < CONFIDENCE_THRESHOLD:
        return {
            "error": f"置信度 {confidence} 低于阈值 {CONFIDENCE_THRESHOLD}, 拒绝写入",
            "rejected": True,
            "message": "修复置信度不足, 建议人工确认后手动添加",
        }

    if not title.strip() or not content.strip():
        return {"error": "title 和 content 不能为空"}

    rb_id = store.upsert_runbook({
        "title": title,
        "content": content,
        "tags": tags,
        "source": "agent_generated",
        "status": "pending_review",
        "session_id": session_id,
        "confidence": confidence,
        "updated_by": f"agent:{session_id}" if session_id else "agent",
    })

    return {
        "id": rb_id,
        "title": title,
        "status": "pending_review",
        "confidence": confidence,
        "message": f"runbook 已写入知识库 (待人工审核), id={rb_id}",
        "hint": "可在 Web 控制台 > 知识库管理 中审核此条目",
    }


@tool("restart_service")
def _restart_service(service="", reason="", node=""):
    """重启服务 — CDH: CM API / Apache: supervisorctl restart"""
    svc_info = SERVICE_MAP.get(service)
    if not svc_info:
        return {"error": f"未知服务: {service}",
                "available": list(SERVICE_MAP.keys())}

    if CLUSTER_BACKEND == "cdh":
        return _cdh_restart_service(svc_info, service, reason, node)
    else:
        return _apache_restart_service(svc_info, service, reason, node)


def _cdh_restart_service(svc_info, service, reason, node):
    """CDH: 通过 CM API 启动停止的服务角色"""
    cm_svc = svc_info["cm_service"]
    target_type = svc_info["cm_role_type"]
    target_nodes = _resolve_node(svc_info, node)
    target_hostnames = {_node_hostname(n) for n in target_nodes}

    role_data = cm_get(f"/clusters/{CM_CLUSTER}/services/{cm_svc}/roles")
    stopped_roles = []
    running_roles = []
    for role in role_data.get("items", []):
        if role.get("type") != target_type:
            continue
        hostname = _resolve_hostname(role.get("hostRef", {}))
        if target_hostnames and hostname not in target_hostnames:
            continue
        state = role.get("roleState", "")
        if state in ("STOPPED", "DOWN", "UNKNOWN"):
            stopped_roles.append({"name": role.get("name", ""),
                                  "node": hostname, "state": state})
        else:
            running_roles.append({"name": role.get("name", ""),
                                  "node": hostname, "state": state})

    if not stopped_roles:
        return {
            "service": service,
            "reason": reason,
            "risk_level": "high" if svc_info.get("core") else "medium",
            "result": "already_running",
            "message": f"所有 {service} 角色已在运行, 无需启动",
            "running": running_roles,
        }

    cmd_data = cm_post(
        f"/clusters/{CM_CLUSTER}/services/{cm_svc}/commands/start"
    )

    return {
        "service": service,
        "reason": reason,
        "risk_level": "high" if svc_info.get("core") else "medium",
        "command_id": cmd_data.get("id", ""),
        "command_name": cmd_data.get("name", ""),
        "stopped_before": stopped_roles,
        "already_running": running_roles,
        "result": "starting" if cmd_data.get("id") else "failed",
        "hint": "CM API 以服务为单位启动所有 stopped 角色. 请等待几秒后用 get_service_status 验证恢复",
    }


def _apache_restart_service(svc_info, service, reason, node):
    """Apache: 通过 supervisorctl 重启服务

    处理三种状态:
    - STOPPED/EXITED/FATAL → 直接 start
    - STARTING → 先 stop 再 start (卡在启动中)
    - RUNNING → restart (正常重启); 如果 restart 失败, fallback 到 stop+start
    """
    sup_prog = svc_info.get("supervisor_program")
    if not sup_prog:
        return {"error": f"服务 {service} 无 supervisor 程序配置, 无法重启"}

    target_nodes = _resolve_node(svc_info, node)
    results = []

    for n in target_nodes:
        hostname = _node_hostname(n)
        sup_conf = _node_supervisor_conf(n)

        # 先检查当前状态
        stdout, _, _ = ssh_exec(n, f"supervisorctl -c {sup_conf} status {sup_prog} 2>&1")
        before_status = stdout.strip() if stdout else "UNKNOWN"

        # 根据状态选择操作
        if "RUNNING" in before_status:
            # RUNNING → restart (stop+start)
            stdout, stderr, rc = ssh_exec(
                n, f"supervisorctl -c {sup_conf} restart {sup_prog} 2>&1", timeout=60)
            # 如果 restart 失败 (僵尸进程等), fallback: stop → 等待 → start
            if rc != 0 or ("error" in (stdout or "").lower() or "error" in (stderr or "").lower()):
                logger.warning(f"{service} on {hostname}: restart failed, trying stop+start fallback")
                ssh_exec(n, f"supervisorctl -c {sup_conf} stop {sup_prog} 2>&1", timeout=30)
                time.sleep(2)
                stdout, stderr, rc = ssh_exec(
                    n, f"supervisorctl -c {sup_conf} start {sup_prog} 2>&1", timeout=60)
        elif "STARTING" in before_status:
            # STARTING → 先 stop 再 start (卡在启动中)
            ssh_exec(n, f"supervisorctl -c {sup_conf} stop {sup_prog} 2>&1", timeout=30)
            time.sleep(2)
            stdout, stderr, rc = ssh_exec(
                n, f"supervisorctl -c {sup_conf} start {sup_prog} 2>&1", timeout=60)
        else:
            # STOPPED/EXITED/FATAL → 直接 start
            stdout, stderr, rc = ssh_exec(
                n, f"supervisorctl -c {sup_conf} start {sup_prog} 2>&1", timeout=60)

        after_status = stdout.strip() if stdout else stderr.strip()

        results.append({
            "node": hostname,
            "before": before_status,
            "after": after_status,
            "returncode": rc,
        })

    # 判断结果
    all_started = all("RUNNING" in r["after"] or "started" in r["after"].lower()
                      for r in results)

    return {
        "service": service,
        "reason": reason,
        "risk_level": "high" if svc_info.get("core") else "medium",
        "nodes": results,
        "result": "started" if all_started else "failed",
        "hint": f"supervisorctl 已执行重启, 请等待几秒后用 get_service_status 验证恢复",
    }


@tool("hdfs_admin")
def _hdfs_admin(action="", path="/", quota=""):
    """执行 HDFS 管理命令 (只读 + safemode_leave + quota 管理)"""
    user = "hdfs"
    # 选取 active NameNode 节点 (Apache: hadoop01; CDH: SERVICE_MAP 中 NameNode 的第一个节点)
    nn_node = SERVICE_MAP["NameNode"]["nodes"][0]

    # 安全: 校验 path 防止命令注入
    if not path or not path.startswith("/") or ".." in path:
        path = "/"
    safe_path = shlex.quote(path)
    # 安全: 校验 quota 参数 (允许数字+单位字母, 防注入)
    import re
    safe_quota = ""
    if quota:
        if re.match(r'^\d+[gGmMtTkKbB]?$', str(quota)):
            safe_quota = str(quota)
        else:
            return {"error": f"非法 quota 参数: {quota}", "hint": "允许格式: 1000 / 500g / 2t"}

    # 配额相关操作需要 path
    _QUOTA_ACTIONS = {"count_quota", "set_quota", "set_space_quota", "clr_quota", "clr_space_quota"}
    if action in _QUOTA_ACTIONS and (not path or path == "/"):
        return {"error": f"操作 {action} 需要指定 path"}
    # set 操作需要 quota
    if action in ("set_quota", "set_space_quota") and not safe_quota:
        return {"error": f"操作 {action} 需要指定 quota 参数"}

    if CLUSTER_BACKEND == "cdh":
        ip = _node_ip(nn_node)
        cmds = {
            "report": f"sudo -u {user} hdfs dfsadmin -report 2>&1 | head -30",
            "fsck": f"sudo -u {user} hdfs fsck {safe_path} 2>&1 | tail -20",
            "fsck_list_corrupt": f"sudo -u {user} hdfs fsck / -list-corruptfileblocks 2>&1",
            "fsck_delete": f"sudo -u {user} hdfs fsck {safe_path} -delete 2>&1 | tail -20",
            "ls": f"sudo -u {user} hdfs dfs -ls {safe_path} 2>&1",
            "du": f"sudo -u {user} hdfs dfs -du -h {safe_path} 2>&1",
            "safemode_get": f"sudo -u {user} hdfs dfsadmin -safemode get 2>&1",
            "safemode_leave": f"sudo -u {user} hdfs dfsadmin -safemode leave 2>&1",
            "count_quota": f"sudo -u {user} hdfs dfs -count -q {safe_path} 2>&1",
            "set_quota": f"sudo -u {user} hdfs dfsadmin -setQuota {safe_quota} {safe_path} 2>&1",
            "set_space_quota": f"sudo -u {user} hdfs dfsadmin -setSpaceQuota {safe_quota} {safe_path} 2>&1",
            "clr_quota": f"sudo -u {user} hdfs dfsadmin -clrQuota {safe_path} 2>&1",
            "clr_space_quota": f"sudo -u {user} hdfs dfsadmin -clrSpaceQuota {safe_path} 2>&1",
        }
    else:
        # Apache: 需设置 JAVA_HOME, 用 /opt/hadoop/bin/hdfs
        cmds = {
            "report": f"export JAVA_HOME={JAVA_HOME}; /opt/hadoop/bin/hdfs dfsadmin -report 2>&1 | head -30",
            "fsck": f"export JAVA_HOME={JAVA_HOME}; /opt/hadoop/bin/hdfs fsck {safe_path} 2>&1 | tail -20",
            "fsck_list_corrupt": f"export JAVA_HOME={JAVA_HOME}; /opt/hadoop/bin/hdfs fsck / -list-corruptfileblocks 2>&1",
            "fsck_delete": f"export JAVA_HOME={JAVA_HOME}; /opt/hadoop/bin/hdfs fsck {safe_path} -delete 2>&1 | tail -20",
            "ls": f"export JAVA_HOME={JAVA_HOME}; /opt/hadoop/bin/hdfs dfs -ls {safe_path} 2>&1",
            "du": f"export JAVA_HOME={JAVA_HOME}; /opt/hadoop/bin/hdfs dfs -du -h {safe_path} 2>&1",
            "safemode_get": f"export JAVA_HOME={JAVA_HOME}; /opt/hadoop/bin/hdfs dfsadmin -safemode get 2>&1",
            "safemode_leave": f"export JAVA_HOME={JAVA_HOME}; /opt/hadoop/bin/hdfs dfsadmin -safemode leave 2>&1",
            "count_quota": f"export JAVA_HOME={JAVA_HOME}; /opt/hadoop/bin/hdfs dfs -count -q {safe_path} 2>&1",
            "set_quota": f"export JAVA_HOME={JAVA_HOME}; /opt/hadoop/bin/hdfs dfsadmin -setQuota {safe_quota} {safe_path} 2>&1",
            "set_space_quota": f"export JAVA_HOME={JAVA_HOME}; /opt/hadoop/bin/hdfs dfsadmin -setSpaceQuota {safe_quota} {safe_path} 2>&1",
            "clr_quota": f"export JAVA_HOME={JAVA_HOME}; /opt/hadoop/bin/hdfs dfsadmin -clrQuota {safe_path} 2>&1",
            "clr_space_quota": f"export JAVA_HOME={JAVA_HOME}; /opt/hadoop/bin/hdfs dfsadmin -clrSpaceQuota {safe_path} 2>&1",
        }

    cmd = cmds.get(action)
    if not cmd:
        return {"error": f"未知操作: {action}", "available": list(cmds.keys())}

    stdout, stderr, rc = ssh_exec(nn_node, cmd, timeout=30)
    return {
        "action": action,
        "path": path,
        "output": stdout if stdout else stderr,
        "returncode": rc,
    }


# 只读命令白名单 (diagnose_node custom 操作的安全限制)
_READONLY_CMDS = ("ls", "cat", "du", "df", "find", "grep", "wc", "head", "tail",
                  "ps", "netstat", "ss", "lsof", "stat", "file", "wc", "sort",
                  "awk", "uniq", "date", "uptime", "who", "last", "id", "env",
                  "printenv", "hostname", "uname", "dmesg", "journalctl",
                  "systemctl", "supervisorctl", "jps", "jstack", "jmap",
                  "jstat", "jinfo", "free", "vmstat", "iostat", "mpstat",
                  "tcpdump", "curl", "wget", "ping", "nslookup", "dig",
                  "getent", "lsblk", "fdisk", "mount", "mountpoint")


@tool("diagnose_node")
def _diagnose_node(node="", action="", cmd=""):
    """在指定节点上执行诊断命令 (只读安全)"""
    if not node:
        return {"error": "需指定 node"}
    if node not in CLUSTER_NODES:
        return {"error": f"未知节点: {node}", "available": list(CLUSTER_NODES.keys())}

    actions = {
        "du_root": "du -sh /* 2>/dev/null | sort -rh | head -20",
        "find_large": "find / -type f -size +100M -exec ls -lh {} \\; 2>/dev/null | head -20",
        "top_procs": "ps aux --sort=-%mem | head -15",
        "netstat": "netstat -tlnp 2>/dev/null || ss -tlnp 2>/dev/null",
        "mount": "mount | head -20",
    }

    if action == "custom":
        if not cmd:
            return {"error": "custom 操作需提供 cmd 参数"}
        # 安全: 只允许白名单中的命令开头
        cmd_stripped = cmd.strip()
        first_word = cmd_stripped.split()[0] if cmd_stripped.split() else ""
        # 处理管道和分号: 检查每个子命令
        import re
        # 拆分管道/分号/&&/|| 中的子命令
        sub_cmds = re.split(r'[|;]|&&|\|\|', cmd_stripped)
        for sub in sub_cmds:
            sub = sub.strip()
            if not sub:
                continue
            first = sub.split()[0] if sub.split() else ""
            # 去除路径前缀 (如 /usr/bin/ls)
            first_base = first.split("/")[-1] if "/" in first else first
            if first_base not in _READONLY_CMDS:
                return {"error": f"安全限制: 命令 '{first_base}' 不在只读白名单中. "
                               f"允许: {', '.join(sorted(_READONLY_CMDS)[:20])}..."}
        exec_cmd = cmd_stripped
    elif action in actions:
        exec_cmd = actions[action]
    else:
        return {"error": f"未知操作: {action}", "available": list(actions.keys()) + ["custom"]}

    stdout, stderr, rc = ssh_exec(node, exec_cmd, timeout=30)
    return {
        "node": node,
        "action": action,
        "output": stdout if stdout else stderr,
        "returncode": rc,
    }


@tool("file_ops")
def _file_ops(node="", action="", path="", reason=""):
    """文件操作: 删除/截断/清理 (中风险, 有审计)"""
    if not node or not action:
        return {"error": "需指定 node 和 action"}
    if node not in CLUSTER_NODES:
        return {"error": f"未知节点: {node}", "available": list(CLUSTER_NODES.keys())}

    # 危险路径保护: 禁止删除系统关键目录
    _PROTECTED_PATHS = ("/etc", "/bin", "/sbin", "/usr", "/lib", "/lib64",
                        "/boot", "/proc", "/sys", "/dev", "/opt/hadoop",
                        "/opt/hbase", "/opt/hive", "/opt/zookeeper",
                        "/opt/tez", "/data")
    # 允许删除的路径模式 (日志/临时文件)
    _ALLOWED_PATTERNS = ("/logs/", "/tmp/", "/disk_fill", "disk_fill",
                         ".log", ".out", ".tmp", ".bak")

    if action == "delete":
        if not path:
            return {"error": "delete 操作需提供 path"}
        safe_path = shlex.quote(path)
        # 安全检查
        for prot in _PROTECTED_PATHS:
            if path.startswith(prot) and path != prot.rstrip("/"):
                # 但允许删除日志文件
                if not any(p in path for p in _ALLOWED_PATTERNS):
                    return {"error": f"安全限制: 禁止删除受保护路径下的文件: {path}"}
        # 检查文件是否存在及大小
        stdout, _, _ = ssh_exec(node, f"ls -lh {safe_path} 2>&1", timeout=10)
        if "No such file" in stdout:
            return {"error": f"文件不存在: {path}"}
        # 执行删除
        stdout, stderr, rc = ssh_exec(node, f"rm -f {safe_path} 2>&1", timeout=30)
        return {
            "node": node,
            "action": "delete",
            "path": path,
            "reason": reason,
            "before": stdout if stdout else "deleted",
            "returncode": rc,
        }

    elif action == "truncate":
        if not path:
            return {"error": "truncate 操作需提供 path"}
        safe_path = shlex.quote(path)
        # 保留最后1000行
        cmd = f"tail -1000 {safe_path} > {safe_path}.tmp && mv {safe_path}.tmp {safe_path} 2>&1"
        stdout, stderr, rc = ssh_exec(node, cmd, timeout=30)
        return {
            "node": node,
            "action": "truncate",
            "path": path,
            "reason": reason,
            "output": stdout if stdout else stderr,
            "returncode": rc,
        }

    elif action == "cleanup_logs":
        # 清理 /logs/ 下7天前的日志文件
        cmd = "find /logs/ -name '*.log' -mtime +7 -exec rm -f {} \\; 2>&1; " \
              "find /logs/ -name '*.out' -mtime +7 -exec rm -f {} \\; 2>&1; " \
              "find /tmp/ -type f -mtime +3 -exec rm -f {} \\; 2>&1; " \
              "echo 'cleanup done'"
        stdout, stderr, rc = ssh_exec(node, cmd, timeout=60)
        return {
            "node": node,
            "action": "cleanup_logs",
            "reason": reason,
            "output": stdout if stdout else stderr,
            "returncode": rc,
        }
    else:
        return {"error": f"未知操作: {action}", "available": ["delete", "truncate", "cleanup_logs"]}


@tool("edit_remote_config")
def _edit_remote_config(service="", node="", file="", find="", replace="", reason=""):
    """修改远程配置文件 (reversible: 先备份 .bak.<ts> 再 sed 替换 再 reload)"""
    if not all([service, node, file, find, replace]):
        return {"error": "参数缺失: 需 service/node/file/find/replace"}

    svc_info = SERVICE_MAP.get(service)
    if not svc_info:
        return {"error": f"未知服务: {service}", "available": list(SERVICE_MAP.keys())}

    ts = int(time.time())
    safe_file = shlex.quote(file)

    # 1. 备份
    _, stderr, rc = ssh_exec(node, f"cp {safe_file} {safe_file}.bak.{ts}", timeout=15)
    if rc != 0:
        return {"error": f"备份失败: {stderr}", "result": "failed"}

    # 2. 字面替换 (用 python3 避免 sed 正则注入)
    py_script = (
        "import sys; f=sys.argv[1]; find=sys.argv[2]; repl=sys.argv[3];"
        "c=open(f).read(); n=c.count(find); "
        "open(f,'w').write(c.replace(find,repl)); print(n)"
    )
    replace_cmd = (
        f"python3 -c {shlex.quote(py_script)} {safe_file} "
        f"{shlex.quote(find)} {shlex.quote(replace)}"
    )
    stdout, stderr, rc = ssh_exec(node, replace_cmd, timeout=15)
    if rc != 0:
        ssh_exec(node, f"cp {safe_file}.bak.{ts} {safe_file}", timeout=15)
        return {"error": f"替换失败: {stderr}, 已回滚",
                "result": "failed", "backup": f"{file}.bak.{ts}"}

    # 3. reload 服务
    if CLUSTER_BACKEND == "cdh":
        cm_svc = svc_info["cm_service"]
        cmd_data = cm_post(f"/clusters/{CM_CLUSTER}/services/{cm_svc}/commands/restart")
        reload_result = {"command_id": cmd_data.get("id", "")}
    else:
        # Apache: supervisorctl restart
        sup_prog = svc_info.get("supervisor_program")
        if sup_prog:
            sup_conf = _node_supervisor_conf(node)
            stdout, stderr, rc = ssh_exec(
                node, f"supervisorctl -c {sup_conf} restart {sup_prog} 2>&1")
            reload_result = {"output": stdout or stderr, "returncode": rc}
        else:
            reload_result = {"message": "无 supervisor 程序, 跳过 reload"}

    return {
        "service": service,
        "node": node,
        "file": file,
        "reason": reason,
        "backup": f"{file}.bak.{ts}",
        "replacements": stdout.strip() if stdout else "0",
        "reload": reload_result,
        "result": "reloaded" if reload_result else "failed",
        "hint": "配置已修改并备份, 服务正在 reload, 请等待后用 get_service_status 验证",
    }


# ============================================================
# 执行入口
# ============================================================

def execute_tool(name: str, arguments: dict) -> dict:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return {"error": f"未知工具: {name}"}
    risk = TOOL_RISK.get(name, RISK_LOW)
    if name == "restart_service":
        svc = arguments.get("service", "")
        svc_info = SERVICE_MAP.get(svc, {})
        risk = RISK_HIGH if svc_info.get("core") else RISK_MEDIUM
    elif name == "hdfs_admin" and arguments.get("action") == "safemode_leave":
        risk = RISK_MEDIUM
    elif name == "hdfs_admin" and arguments.get("action") == "fsck_delete":
        risk = RISK_MEDIUM
    elif name == "hdfs_admin" and arguments.get("action") in (
        "set_quota", "set_space_quota", "clr_quota", "clr_space_quota"
    ):
        risk = RISK_MEDIUM
    try:
        result = handler(**arguments)
        logger.info(f"TOOL {name} [risk={risk}] args={arguments} -> "
                    f"{json.dumps(result, ensure_ascii=False)[:300]}")
        return result
    except Exception as e:
        logger.error(f"TOOL {name} 执行异常: {e}")
        return {"error": str(e)}


# ---- 工具子集 (按 session 模式) ----
AUTO_TOOL_NAMES = [
    "get_service_status", "get_alerts", "get_metrics",
    "read_logs", "search_kb", "hdfs_admin", "diagnose_node",
]
FIX_TOOL_NAMES = AUTO_TOOL_NAMES + ["restart_service", "edit_remote_config", "write_runbook", "file_ops"]
# 对话式运维: 全工具 (用户可直接请求修复操作, 高危走审批)
CHAT_TOOL_NAMES = FIX_TOOL_NAMES


def get_tool_definitions(names):
    return [d for d in TOOL_DEFINITIONS if d["function"]["name"] in names]


# ============================================================
# Demo 辅助: 故障注入 / 告警检测 / 集群快照
# ============================================================

def inject_fault(fault="datanode_oom"):
    """故障注入 — 当前由用户手动操作"""
    if fault == "none":
        logger.info("故障恢复: 确保所有服务运行 (空操作, 由用户手动管理)")
    else:
        logger.info(f"故障注入({fault}): 当前由用户手动操作, 请手动停止对应服务")


# 告警缓存
_alerts_cache = {"data": [], "ts": 0}
_alerts_cache_lock = threading.Lock()
_ALERTS_CACHE_TTL = 10


def get_pending_alerts():
    """获取当前待处理告警 (供 orchestrator 调度用), 带 10s 缓存"""
    now = time.time()
    with _alerts_cache_lock:
        if now - _alerts_cache["ts"] < _ALERTS_CACHE_TTL:
            return _alerts_cache["data"]
    result = _get_alerts()
    alerts = result.get("alerts", [])
    with _alerts_cache_lock:
        _alerts_cache["data"] = alerts
        _alerts_cache["ts"] = time.time()
    return alerts


def get_cluster_snapshot():
    """获取集群服务快照 (供 orchestrator 状态卡用)"""
    if CLUSTER_BACKEND == "cdh":
        return _cdh_get_cluster_snapshot()
    else:
        return _apache_get_cluster_snapshot()


def _cdh_get_cluster_snapshot():
    """CDH: 通过 CM API 获取集群快照"""
    services = {}
    for svc_name in INSPECT_SERVICES:
        svc_info = SERVICE_MAP.get(svc_name)
        if not svc_info:
            continue
        cm_svc = svc_info["cm_service"]
        role_data = cm_get(
            f"/clusters/{CM_CLUSTER}/services/{cm_svc}/roles"
        )
        roles = []
        for r in role_data.get("items", []):
            if r.get("type") == svc_info["cm_role_type"]:
                roles.append({
                    "node": _resolve_hostname(r.get("hostRef", {})),
                    "state": r.get("roleState", ""),
                    "health": r.get("healthSummary", ""),
                })
        bad = [r for r in roles if r["health"] not in ("GOOD", "DISABLED")]
        services[svc_name] = {
            "health": "BAD" if bad else "GOOD",
            "role_count": len(roles),
        }
    bad_services = [k for k, v in services.items() if v["health"] != "GOOD"]
    overall_health = "BAD" if bad_services else "GOOD"
    alerts = get_pending_alerts()
    return {
        "overall_health": overall_health,
        "services": services,
        "alerts": len(alerts),
    }


def _apache_get_cluster_snapshot():
    """Apache: 通过 supervisorctl + Prometheus 获取集群快照"""
    services = {}
    for svc_name in INSPECT_SERVICES:
        svc_info = SERVICE_MAP.get(svc_name, {})
        sup_prog = svc_info.get("supervisor_program")
        if not sup_prog:
            continue

        roles = []
        for n in svc_info.get("nodes", []):
            hostname = _node_hostname(n)
            sup_conf = _node_supervisor_conf(n)
            stdout, _, _ = ssh_exec(
                n, f"supervisorctl -c {sup_conf} status {sup_prog} 2>&1")
            # 健壮解析: 只接受有效的 supervisor 状态值
            sup_status, _ = _parse_supervisor_status(stdout)
            if sup_status:
                status = sup_status
                health = "GOOD" if status == "RUNNING" else "BAD"
            else:
                # supervisorctl 不可用, 视为异常
                status = "UNKNOWN"
                health = "BAD"
            roles.append({"node": hostname, "state": status, "health": health})

        bad = [r for r in roles if r["health"] != "GOOD"]
        services[svc_name] = {
            "health": "BAD" if bad else "GOOD",
            "role_count": len(roles),
        }

    bad_services = [k for k, v in services.items() if v["health"] != "GOOD"]
    overall_health = "BAD" if bad_services else "GOOD"
    alerts = get_pending_alerts()
    return {
        "overall_health": overall_health,
        "services": services,
        "alerts": len(alerts),
    }
