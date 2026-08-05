"""秘密配置模板 — 复制为 secrets.local.py 并填入真实值

  cp src/secrets.example.py src/secrets.local.py

secrets.local.py 已被 .gitignore 排除, 不会提交到 git。
config.py 启动时会自动加载 secrets.local.py (通过设置环境变量)。
"""
import os

# ---- LLM 推理 ----
os.environ.setdefault("LLM_API_KEY", "your-api-key-here")

# ---- SSH ----
os.environ.setdefault("SSH_USER", "root")

# ---- 集群节点 IP + hostname ----
os.environ.setdefault("NODE01_HOST", "10.0.0.1")
os.environ.setdefault("NODE02_HOST", "10.0.0.2")
os.environ.setdefault("NODE03_HOST", "10.0.0.3")
os.environ.setdefault("NODE01_NAME", "hadoop01")
os.environ.setdefault("NODE02_NAME", "hadoop02")
os.environ.setdefault("NODE03_NAME", "hadoop03")

# ---- Cloudera Manager ----
os.environ.setdefault("CM_HOST", "10.0.0.3")
os.environ.setdefault("CM_USER", "admin")
os.environ.setdefault("CM_PASS", "your-password-here")
os.environ.setdefault("CM_CLUSTER", "test")

# ---- 监控 ----
os.environ.setdefault("PROMETHEUS_URL", "http://10.0.0.3:9090")
os.environ.setdefault("ALERTMANAGER_URL", "http://10.0.0.3:9093")
os.environ.setdefault("GRAFANA_URL", "http://10.0.0.3:3000")
