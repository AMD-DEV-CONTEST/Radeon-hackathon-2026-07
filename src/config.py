import os

# ============================================================
# 加载本地秘密配置 (不提交到 git, 见 secrets.example.py)
# ============================================================
try:
    from . import secrets_local  # noqa: F401 — 设置环境变量
except ImportError:
    pass

# ============================================================
# LLM 推理配置
# ============================================================
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:18080/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "CHANGE_ME")
LLM_MODEL = os.getenv("LLM_MODEL", "/workspace/Qwopus3.6-27B-v2-MTP-Q4_K_M.gguf")

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "aiops.db"))

# ---- Web 控制台认证 ----
# 设置 CONSOLE_TOKEN 后, 所有 API 请求需携带 Authorization: Bearer <token>
# 留空则不启用认证 (仅限开发环境)
CONSOLE_TOKEN = os.getenv("CONSOLE_TOKEN", "")

# ---- 自治模式 (§21.2 双轴之轴1) ----
# supervised: 高危操作需人工审批 (通过审批中心)
# autonomous: 无人值守, 按安全护栏四档策略自动执行
AUTONOMY = os.getenv("AUTONOMY", "supervised").lower()

# ---- 提示词语言 ----
# en: English (default)
# zh: 中文
PROMPT_LANGUAGE = os.getenv("PROMPT_LANGUAGE", "en").lower()

# 运行时可变语言 (前端切换语言时通过 API 更新, 优先于 PROMPT_LANGUAGE)
_current_lang: str = PROMPT_LANGUAGE

def get_lang() -> str:
    return _current_lang

def set_lang(lang: str) -> None:
    global _current_lang
    _current_lang = lang.lower() if lang else _current_lang

MAX_REACT_ITERATIONS = 15
# 推理模型(reasoning_content)需要更多token: 思考过程+实际回答
# 实测一次工具调用决策约消耗 500-1500 tokens (含reasoning)
MAX_TOKENS = 4096
TEMPERATURE = 0.7

# ============================================================
# 集群配置 (配置驱动, 切换环境只改这里)
#
# CLUSTER_BACKEND:
#   "cdh"    — Cloudera Manager API + SSH (旧 CDH 6.3.2 环境, 保留兼容)
#   "apache" — docker-compose Apache Hadoop + supervisorctl + jps + Prometheus (当前主力)
#
# 切换时: 1) 改 CLUSTER_BACKEND 2) 改 CLUSTER_NODES 3) 改 secrets_local.py
# ============================================================

CLUSTER_BACKEND = os.getenv("CLUSTER_BACKEND", "apache").lower()

# SSH 配置
SSH_USER = os.getenv("SSH_USER", "root")
SSH_PORT = int(os.getenv("SSH_PORT", "22"))
SSH_OPTS = "-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=no"
# Docker 环境需要指定密钥文件; CDH 环境留空则用默认密钥
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH", "")

# ============================================================
# 集群节点 (node_key -> IP + hostname + ssh_port)
#
# 动态构建: 仅包含设置了 NODE0X_HOST 环境变量的节点
#   单节点直装: 只设 NODE01_HOST → 只有 hadoop01 (ssh_port=22)
#   Docker 3节点: 设 NODE01/02/03_HOST → 三个节点 (ssh_port=2222/2223/2224)
#   CDH: 设 NODE01/02/03_HOST 为真实IP → 三个节点 (ssh_port=22)
# ============================================================
CLUSTER_NODES = {}

_NODE_DEFS = [
    ("hadoop01", "NODE01_HOST", "NODE01_NAME", "NODE01_SSH_PORT", "2222"),
    ("hadoop02", "NODE02_HOST", "NODE02_NAME", "NODE02_SSH_PORT", "2223"),
    ("hadoop03", "NODE03_HOST", "NODE03_NAME", "NODE03_SSH_PORT", "2224"),
]

for _node_key, _host_env, _name_env, _port_env, _default_port in _NODE_DEFS:
    _host = os.getenv(_host_env)
    if _host:
        CLUSTER_NODES[_node_key] = {
            "host": _host,
            "hostname": os.getenv(_name_env, _node_key),
            "ssh_port": int(os.getenv(_port_env, _default_port)),
            "supervisor_conf": f"/etc/supervisor/conf.d/supervisord-{_node_key}.conf",
        }

# Fallback: if no NODE env vars set, default to single-node localhost:22
if not CLUSTER_NODES:
    CLUSTER_NODES["hadoop01"] = {
        "host": "localhost",
        "hostname": "hadoop01",
        "ssh_port": 22,
        "supervisor_conf": "/etc/supervisor/conf.d/supervisord-hadoop01.conf",
    }

# ---- Cloudera Manager API (CDH 后端用, apache 后端可忽略) ----
CM_HOST = os.getenv("CM_HOST", "10.0.0.3")
CM_PORT = int(os.getenv("CM_PORT", "7180"))
CM_USER = os.getenv("CM_USER", "admin")
CM_PASS = os.getenv("CM_PASS", "CHANGE_ME")
CM_CLUSTER = os.getenv("CM_CLUSTER", "test")
CM_API_VERSION = os.getenv("CM_API_VERSION", "v30")

# ---- 监控配置 ----
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
ALERTMANAGER_URL = os.getenv("ALERTMANAGER_URL", "http://localhost:9093")
GRAFANA_URL = os.getenv("GRAFANA_URL", "http://localhost:3000")

# ============================================================
# Java / Hadoop 路径
#
# CDH:  /usr/java/jdk1.8u372-b07-cloudera/bin/java, /opt/cloudera/parcels/CDH-xxx
# Docker(Apache): JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64, /opt/hadoop/bin
# ============================================================
if CLUSTER_BACKEND == "cdh":
    JAVA_HOME = "/usr/java/jdk1.8u372-b07-cloudera"
    JPS_BIN = f"{JAVA_HOME}/bin/jps"
    HADOOP_BIN = "/opt/cloudera/parcels/CDH-6.3.2-1.cdh6.3.2.p0.1605554/lib/hadoop/bin/hdfs"
    CDH_PARCEL = "/opt/cloudera/parcels/CDH-6.3.2-1.cdh6.3.2.p0.1605554"
    HADOOP_SBIN = f"{CDH_PARCEL}/lib/hadoop/sbin"
    YARN_SBIN = f"{CDH_PARCEL}/lib/hadoop-yarn/sbin"
else:
    # Apache (docker-compose) — 不读宿主机 JAVA_HOME, 用容器内路径
    JAVA_HOME = "/usr/lib/jvm/java-8-openjdk-amd64"
    JPS_BIN = "/usr/bin/jps"  # 容器内 jps 在 /usr/bin/
    HADOOP_BIN = "/opt/hadoop/bin/hdfs"
    HADOOP_SBIN = "/opt/hadoop/sbin"
    YARN_SBIN = "/opt/hadoop/bin"

# ============================================================
# 服务映射表 (核心: 服务名 -> 节点/角色/日志路径/运行用户)
#
# 通用字段 (CDH + Apache 都用):
#   nodes         — 部署节点列表
#   core          — 是否核心服务 (影响风险分级)
#
# CDH 专用字段:
#   cm_service    — Cloudera Manager 服务名
#   cm_role_type  — CM 角色类型
#   log_dir       — CDH 日志目录
#   log_prefix    — CDH 日志前缀
#   run_user      — 运行用户
#
# Apache 专用字段 (docker-compose):
#   supervisor_program — supervisord 程序名
#   java_class         — jps 输出的 Java 类名 (用于进程检测)
#   log_file           — supervisor 日志文件路径 (/logs/xxx.log)
#   jmx_port           — JMX Exporter 端口 (Prometheus 采集)
# ============================================================

# ---- CDH 专用字段 ----
_CDH_FIELDS = {
    "log_dir": "/var/log/hadoop-hdfs",
    "log_prefix": "hadoop-cmf-hdfs-NAMENODE",
    "run_user": "hdfs",
}

SERVICE_MAP = {
    # ---- HDFS ----
    "NameNode": {
        "cm_service": "hdfs",
        "cm_role_type": "NAMENODE",
        "log_dir": "/var/log/hadoop-hdfs",
        "log_prefix": "hadoop-cmf-hdfs-NAMENODE",
        "nodes": ["hadoop01", "hadoop02"],   # Apache: HA 双 NN
        "run_user": "hdfs",
        "core": True,
        # Apache
        "supervisor_program": "namenode",
        "java_class": "org.apache.hadoop.hdfs.server.namenode.NameNode",
        "log_file": "/logs/nn.log",
        "jmx_port": 10101,
    },
    "DataNode": {
        "cm_service": "hdfs",
        "cm_role_type": "DATANODE",
        "log_dir": "/var/log/hadoop-hdfs",
        "log_prefix": "hadoop-cmf-hdfs-DATANODE",
        "nodes": ["hadoop01", "hadoop02", "hadoop03"],
        "run_user": "hdfs",
        "core": False,
        # Apache
        "supervisor_program": "datanode",
        "java_class": "org.apache.hadoop.hdfs.server.datanode.DataNode",
        "log_file": "/logs/dn.log",
        "jmx_port": 10102,
    },
    # ---- YARN ----
    "ResourceManager": {
        "cm_service": "yarn",
        "cm_role_type": "RESOURCEMANAGER",
        "log_dir": "/var/log/hadoop-yarn",
        "log_prefix": "hadoop-cmf-yarn-RESOURCEMANAGER",
        "nodes": ["hadoop01", "hadoop02"],   # Apache: HA 双 RM
        "run_user": "yarn",
        "core": True,
        # Apache
        "supervisor_program": "resourcemanager",
        "java_class": "org.apache.hadoop.yarn.server.resourcemanager.ResourceManager",
        "log_file": "/logs/rm.log",
        "jmx_port": 10104,
    },
    "NodeManager": {
        "cm_service": "yarn",
        "cm_role_type": "NODEMANAGER",
        "log_dir": "/var/log/hadoop-yarn",
        "log_prefix": "hadoop-cmf-yarn-NODEMANAGER",
        "nodes": ["hadoop01", "hadoop02", "hadoop03"],
        "run_user": "yarn",
        "core": False,
        # Apache
        "supervisor_program": "nodemanager",
        "java_class": "org.apache.hadoop.yarn.server.nodemanager.NodeManager",
        "log_file": "/logs/nm.log",
        "jmx_port": 10105,
    },
    "JobHistoryServer": {
        "cm_service": "yarn",
        "cm_role_type": "JOBHISTORY",
        "log_dir": "/var/log/hadoop-yarn",
        "log_prefix": "hadoop-cmf-yarn-JOBHISTORY",
        "nodes": ["hadoop01"],
        "run_user": "yarn",
        "core": False,
        # Apache
        "supervisor_program": "historyserver",
        "java_class": "org.apache.hadoop.mapreduce.v2.hs.JobHistoryServer",
        "log_file": "/logs/jhs.log",
        "jmx_port": 10106,
    },
    # ---- Hive ----
    "HiveMetaStore": {
        "cm_service": "hive",
        "cm_role_type": "HIVEMETASTORE",
        "log_dir": "/var/log/hive",
        "log_prefix": "hadoop-cmf-hive-HIVEMETASTORE",
        "nodes": ["hadoop01", "hadoop02"],   # Apache: 双 HMS
        "run_user": "hive",
        "core": False,
        # Apache
        "supervisor_program": "hivemetastore",
        "java_class": "RunJar",
        "log_file": "/logs/hms.log",
        "jmx_port": 10110,
    },
    "HiveServer2": {
        "cm_service": "hive",
        "cm_role_type": "HIVESERVER2",
        "log_dir": "/var/log/hive",
        "log_prefix": "hadoop-cmf-hive-HIVESERVER2",
        "nodes": ["hadoop01", "hadoop02"],
        "run_user": "hive",
        "core": False,
        # Apache
        "supervisor_program": "hiveserver2",
        "java_class": "RunJar",
        "log_file": "/logs/hs2.log",
        "jmx_port": 10111,
    },
    # ---- HBase ----
    "HBaseMaster": {
        "cm_service": "hbase",
        "cm_role_type": "HMASTER",
        "log_dir": "/var/log/hbase",
        "log_prefix": "hadoop-cmf-hbase-HMASTER",
        "nodes": ["hadoop01", "hadoop02"],   # Apache: 双 HM
        "run_user": "hbase",
        "core": False,
        # Apache
        "supervisor_program": "hmaster",
        "java_class": "org.apache.hadoop.hbase.master.HMaster",
        "log_file": "/logs/hm.log",
        "jmx_port": 10107,
    },
    "RegionServer": {
        "cm_service": "hbase",
        "cm_role_type": "REGIONSERVER",
        "log_dir": "/var/log/hbase",
        "log_prefix": "hadoop-cmf-hbase-REGIONSERVER",
        "nodes": ["hadoop01", "hadoop02", "hadoop03"],
        "run_user": "hbase",
        "core": False,
        # Apache
        "supervisor_program": "regionserver",
        "java_class": "org.apache.hadoop.hbase.regionserver.HRegionServer",
        "log_file": "/logs/rs.log",
        "jmx_port": 10108,
    },
    # ---- ZooKeeper ----
    "ZooKeeper": {
        "cm_service": "zookeeper",
        "cm_role_type": "SERVER",
        "log_dir": "/var/log/zookeeper",
        "log_prefix": "hadoop-cmf-zookeeper-SERVER",
        "nodes": ["hadoop01", "hadoop02", "hadoop03"],
        "run_user": "zookeeper",
        "core": False,
        # Apache
        "supervisor_program": "zookeeper",
        "java_class": "org.apache.zookeeper.server.quorum.QuorumPeerMain",
        "log_file": "/logs/zk.log",
        "jmx_port": 10109,
    },
    # ---- JournalNode (HDFS HA) ----
    "JournalNode": {
        "cm_service": "hdfs",
        "cm_role_type": "JOURNALNODE",
        "log_dir": "/var/log/hadoop-hdfs",
        "log_prefix": "hadoop-cmf-hdfs-JOURNALNODE",
        "nodes": ["hadoop01", "hadoop02", "hadoop03"],
        "run_user": "hdfs",
        "core": False,
        # Apache
        "supervisor_program": "journalnode",
        "java_class": "org.apache.hadoop.hdfs.qjournal.server.JournalNode",
        "log_file": "/logs/jn.log",
        "jmx_port": 10103,
    },
}

# ---- 运行时过滤: SERVICE_MAP nodes 仅保留实际存在的节点 ----
# 单节点模式下 hadoop02/hadoop03 不存在, 相关服务自动缩减为单实例
_active_nodes = set(CLUSTER_NODES.keys())
for _svc in SERVICE_MAP.values():
    _svc["nodes"] = [n for n in _svc["nodes"] if n in _active_nodes]

# 默认巡检服务列表 (agent /auto 模式 + get_service_status(all) 都用这个)
# 单节点模式无 JournalNode (非 HA), 自动跳过
if CLUSTER_BACKEND == "cdh":
    INSPECT_SERVICES = [
        "NameNode", "DataNode", "ResourceManager", "NodeManager",
        "HiveMetaStore", "ZooKeeper",
    ]
else:
    # Apache: 检查全部组件
    INSPECT_SERVICES = [
        "NameNode", "DataNode", "ResourceManager", "NodeManager",
        "JobHistoryServer", "HiveMetaStore", "HiveServer2",
        "HBaseMaster", "RegionServer", "ZooKeeper",
    ]
    # JournalNode 仅在 HA 多节点模式下巡检 (单节点直装无 JN)
    if len(_active_nodes) >= 3:
        INSPECT_SERVICES.append("JournalNode")
