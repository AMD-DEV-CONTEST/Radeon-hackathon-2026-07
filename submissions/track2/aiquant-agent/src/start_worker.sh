#!/bin/bash
# ============================================
# Celery Worker 独立启动脚本 + 自动重启
# 使用 python -m celery（二进制路径不受conda影响）
# ============================================
set -e
PROJECT_ROOT="/Users/gaochangcheng/Desktop/AIquant"
cd "$PROJECT_ROOT"

# 加载 .env（避免从 start.sh 调用时环境变量丢失）
if [ -f ".env" ]; then
    set -a
    while IFS= read -r _line; do
        case "$_line" in ""|\#*) continue ;; *=*) eval "export $_line" ;; esac
    done < .env
    set +a
fi

# 运行时必需变量（优先用 .env 值）
export RUN_MODE="${RUN_MODE:-local}"
export AIQUANT_LOG_LEVEL="${AIQUANT_LOG_LEVEL:-INFO}"
export LITELLM_LOCAL_MODEL_COST_MAP="${LITELLM_LOCAL_MODEL_COST_MAP:-True}"
export LITELLM_DROP_PARAMS="${LITELLM_DROP_PARAMS:-n}"
export NO_PROXY="127.0.0.1,localhost"
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

PYTHON_BIN="/opt/anaconda3/envs/aiquant/bin/python"

# 启动前自检：python -m celery 是否可用
if ! "$PYTHON_BIN" -m celery --version > /dev/null 2>&1; then
    echo "[Worker] FATAL: celery 不可用，请运行: pip install celery[redis]"
    exit 1
fi

echo "[Worker] 环境就绪 — RUN_MODE=${RUN_MODE} — celery $("$PYTHON_BIN" -m celery --version 2>&1)"

while true; do
    echo "[$(date)] [Worker] 启动中..."
    "$PYTHON_BIN" -m celery \
        -A backend.worker.celery_app worker \
        --loglevel=info \
        --concurrency=1 \
        --pool=solo \
        -Q factor_evolution \
        -n factor_worker@%h
    echo "[$(date)] [Worker] 退出（返回码 $?），5 秒后自动重启..."
    sleep 5
done
