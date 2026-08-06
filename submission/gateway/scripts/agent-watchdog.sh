#!/bin/bash
# UnionAgents Agent Watchdog v1.0
# 部署在 Worker 机器上，cron 每分钟执行一次
# 
# 功能：
# 1. 检测 agent 进程是否存活
# 2. 检测 agent 心跳是否正常（心跳超过 5 分钟未更新 → 进程可能卡死）
# 3. 发现问题 → 自动重启
# 4. 连续重启 3 次失败 → 退出（避免无限重启循环）
#
# 部署方式：
#   chmod +x agent-watchdog.sh
#   crontab -e → * * * * * /path/to/agent-watchdog.sh >> /var/log/agent-watchdog.log 2>&1
#
# 或 systemd timer（推荐）：
#   cp agent-watchdog.service agent-watchdog.timer /etc/systemd/system/
#   systemctl enable --now agent-watchdog.timer

set -euo pipefail

###########################
# 配置区 — 按 agent 类型修改
###########################

AGENT_NAME="${AGENT_NAME:-He}"
ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-http://111.228.42.18:8000}"
AGENT_PID_FILE="${AGENT_PID_FILE:-/var/run/unionagents-agent.pid}"
AGENT_START_CMD="${AGENT_START_CMD:-}"
MAX_RESTART_COUNT=3
RESTART_COUNT_FILE="/tmp/agent-watchdog-restart-count"
HEARTBEAT_MAX_AGE_SECONDS=300  # 5 分钟

###########################
# 函数
###########################

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$AGENT_NAME] $*"
}

get_restart_count() {
    if [ -f "$RESTART_COUNT_FILE" ]; then
        # 如果计数文件超过 30 分钟，重置
        local age=$(( $(date +%s) - $(stat -c %Y "$RESTART_COUNT_FILE" 2>/dev/null || echo 0) ))
        if [ "$age" -gt 1800 ]; then
            echo 0
        else
            cat "$RESTART_COUNT_FILE"
        fi
    else
        echo 0
    fi
}

incr_restart_count() {
    local count
    count=$(get_restart_count)
    count=$((count + 1))
    echo "$count" > "$RESTART_COUNT_FILE"
    echo "$count"
}

check_process_alive() {
    if [ -f "$AGENT_PID_FILE" ]; then
        local pid
        pid=$(cat "$AGENT_PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            return 0  # 存活
        fi
    fi
    # 无 pid 文件或进程已死 → 尝试 ps 查找
    if pgrep -f "agent.*$AGENT_NAME" > /dev/null 2>&1; then
        return 0
    fi
    return 1  # 进程不存在
}

check_heartbeat_fresh() {
    # 检查 orchestrator 上 agent 心跳是否新鲜
    local resp
    resp=$(curl -s --connect-timeout 5 "$ORCHESTRATOR_URL/agents" 2>/dev/null || echo "{}")
    local hb_ago
    hb_ago=$(echo "$resp" | python3 -c "
import json,sys
data = json.load(sys.stdin)
for a in data.get('agents', []):
    if a['name'] == '$AGENT_NAME':
        ago = a.get('heartbeat_ago', '999h')
        # 解析 '1h30m5s' 格式
        import re
        m = re.match(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', ago)
        h = int(m.group(1) or 0)
        mi = int(m.group(2) or 0)
        s = int(m.group(3) or 0)
        print(h*3600 + mi*60 + s)
        break
" 2>/dev/null || echo "99999")
    
    if [ "$hb_ago" -lt "$HEARTBEAT_MAX_AGE_SECONDS" ] 2>/dev/null; then
        return 0  # 心跳新鲜
    fi
    return 1  # 心跳过期
}

restart_agent() {
    local count
    count=$(incr_restart_count)
    
    if [ "$count" -gt "$MAX_RESTART_COUNT" ]; then
        log "FATAL: restarted $MAX_RESTART_COUNT times in 30min, giving up. MANUAL INTERVENTION REQUIRED."
        return 1
    fi
    
    log "restarting agent (attempt $count/$MAX_RESTART_COUNT)..."
    
    # 杀掉旧进程
    if [ -f "$AGENT_PID_FILE" ]; then
        kill "$(cat "$AGENT_PID_FILE")" 2>/dev/null || true
        sleep 2
    fi
    pkill -f "agent.*$AGENT_NAME" 2>/dev/null || true
    sleep 1
    
    # 启动新进程
    if [ -n "$AGENT_START_CMD" ]; then
        eval "$AGENT_START_CMD" &
        echo $! > "$AGENT_PID_FILE"
        log "agent restarted with PID $(cat "$AGENT_PID_FILE")"
    else
        log "WARNING: AGENT_START_CMD not set, cannot restart. Set it in config or env."
        return 1
    fi
    
    return 0
}

###########################
# 主逻辑
###########################

log "watchdog check start"

# 1. 进程存活检查
if ! check_process_alive; then
    log "agent process NOT FOUND → restarting"
    restart_agent
    exit $?
fi
log "process check: OK"

# 2. 心跳新鲜度检查（进程在但可能卡死）
if ! check_heartbeat_fresh; then
    log "heartbeat STALE (>${HEARTBEAT_MAX_AGE_SECONDS}s) → agent may be stuck → restarting"
    restart_agent
    exit $?
fi
log "heartbeat check: OK"

log "watchdog check complete — agent healthy"
