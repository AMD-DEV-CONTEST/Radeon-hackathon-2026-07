#!/usr/bin/env bash
# ============================================================
# AMD AI Studio — 双服务启动脚本
#
# 服务：
#   1. AI 创作工作室  (app.py, 端口 7860)
#   2. 测试报告       (静态 HTTP, 端口 8080)
#
# 外网访问：每个服务各开一个 cloudflared trycloudflare 隧道
#
# 进程冲突检测：启动前先杀掉占用目标端口的旧进程
# 启动成功后打印两个服务的外网地址
#
# 用法: bash scripts/start_services.sh
# ============================================================

set -uo pipefail
cd "$(dirname "$0")/.."

# ---------- 颜色 ----------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ---------- 配置 ----------
PROJECT_DIR="$(pwd)"
APP_PY="${PROJECT_DIR}/app.py"
REPORTS_DIR="${PROJECT_DIR}/outputs/benchmarks"

APP_PORT=7860
REPORTS_PORT=8080

LOG_DIR="/tmp"
APP_LOG="${LOG_DIR}/amd_app.log"
REPORTS_LOG="${LOG_DIR}/amd_reports_server.log"
CF_APP_LOG="${LOG_DIR}/amd_cf_app.log"
CF_REPORTS_LOG="${LOG_DIR}/amd_cf_reports.log"

# ---------- venv ----------
if [[ -f /opt/venv/bin/activate ]]; then
    source /opt/venv/bin/activate
    info "已激活 venv: /opt/venv"
elif [[ -f .venv/bin/activate ]]; then
    source .venv/bin/activate
    info "已激活 venv: .venv"
fi
PY_BIN="${PYTHON_BIN:-python3}"

# ---------- 工具函数 ----------

# 杀掉占用指定端口的所有进程
kill_port() {
    local port="$1"
    local pids
    pids=$(ss -tlnp 2>/dev/null | grep ":${port} " | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u)
    if [[ -n "$pids" ]]; then
        warn "端口 ${port} 被占用，杀掉旧进程: $(echo $pids | tr '\n' ' ')"
        for pid in $pids; do
            kill -9 "$pid" 2>/dev/null
        done
        sleep 2
    fi
}

# 杀掉所有匹配命令行的进程（cloudflared 隧道）
kill_pattern() {
    local pattern="$1"
    local pids
    pids=$(pgrep -f "$pattern" 2>/dev/null)
    if [[ -n "$pids" ]]; then
        warn "杀掉匹配 '$pattern' 的旧进程: $(echo $pids | tr '\n' ' ')"
        for pid in $pids; do
            kill -9 "$pid" 2>/dev/null
        done
        sleep 1
    fi
}

# 等待端口就绪，最多 timeout 秒
wait_port() {
    local port="$1"
    local timeout="${2:-30}"
    local elapsed=0
    while ! ss -tlnp 2>/dev/null | grep -q ":${port} "; do
        sleep 1
        elapsed=$((elapsed + 1))
        if [[ $elapsed -ge $timeout ]]; then
            return 1
        fi
    done
    return 0
}

# 从 cloudflared 日志提取 trycloudflare URL
get_cf_url() {
    local log_file="$1"
    local timeout="${2:-30}"
    local elapsed=0
    while [[ $elapsed -lt $timeout ]]; do
        if [[ -f "$log_file" ]]; then
            # 优先匹配 "Your quick Tunnel has been created" 那行的 URL
            url=$(strings "$log_file" 2>/dev/null | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -1)
            if [[ -n "$url" ]]; then
                echo "$url"
                return 0
            fi
            # 如果日志里有明确失败，提前返回
            if strings "$log_file" 2>/dev/null | grep -qiE "failed to request|context deadline exceeded"; then
                return 2
            fi
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    return 1
}

# 获取本机内网 IP
get_lan_ip() {
    local ip
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    [[ -z "$ip" ]] && ip="127.0.0.1"
    echo "$ip"
}

# ---------- 启动前清理 ----------

info "启动前清理旧进程..."
kill_port "$APP_PORT"
kill_port "$REPORTS_PORT"
# 杀掉旧的 cloudflared 隧道（排除 defunct 僵尸）
kill_pattern "cloudflared tunnel --url http://localhost:${APP_PORT}"
kill_pattern "cloudflared tunnel --url http://localhost:${REPORTS_PORT}"

# ---------- 1. 启动 AI 创作工作室 ----------

echo ""
info "${BOLD}启动服务 1/2: AI 创作工作室${NC}"
info "脚本: $APP_PY"
info "端口: $APP_PORT"

if [[ ! -f "$APP_PY" ]]; then
    err "app.py 不存在: $APP_PY"
    exit 1
fi

nohup "$PY_BIN" "$APP_PY" > "$APP_LOG" 2>&1 &
APP_PID=$!
info "app.py 进程 PID: $APP_PID"

info "等待 app.py 端口 ${APP_PORT} 就绪（最多 60s）..."
if wait_port "$APP_PORT" 60; then
    ok "AI 创作工作室已启动 (端口 ${APP_PORT})"
else
    err "app.py 启动超时，查看日志: $APP_LOG"
    tail -20 "$APP_LOG" 2>/dev/null
    exit 1
fi

# ---------- 2. 启动测试报告静态服务器 ----------

echo ""
info "${BOLD}启动服务 2/2: 测试报告静态服务器${NC}"
info "目录: $REPORTS_DIR"
info "端口: $REPORTS_PORT"

if [[ ! -d "$REPORTS_DIR" ]]; then
    err "测试报告目录不存在: $REPORTS_DIR"
    exit 1
fi

cd "$REPORTS_DIR"
nohup "$PY_BIN" -m http.server "$REPORTS_PORT" --bind 0.0.0.0 > "$REPORTS_LOG" 2>&1 &
REPORTS_PID=$!
cd "$PROJECT_DIR"
info "测试报告服务器 PID: $REPORTS_PID"

info "等待静态服务器端口 ${REPORTS_PORT} 就绪（最多 15s）..."
if wait_port "$REPORTS_PORT" 15; then
    ok "测试报告服务器已启动 (端口 ${REPORTS_PORT})"
else
    err "测试报告服务器启动超时，查看日志: $REPORTS_LOG"
    tail -20 "$REPORTS_LOG" 2>/dev/null
    exit 1
fi

# ---------- 3. 启动 cloudflare 隧道 ----------

echo ""
info "${BOLD}启动 Cloudflare 隧道（外网访问）${NC}"

# 隧道 1: AI 创作工作室
info "启动隧道 1/2: AI 创作工作室..."
nohup cloudflared tunnel --url "http://localhost:${APP_PORT}" > "$CF_APP_LOG" 2>&1 &
CF_APP_PID=$!
info "cloudflared (app) PID: $CF_APP_PID"

# 隧道 2: 测试报告
info "启动隧道 2/2: 测试报告..."
nohup cloudflared tunnel --url "http://localhost:${REPORTS_PORT}" > "$CF_REPORTS_LOG" 2>&1 &
CF_REPORTS_PID=$!
info "cloudflared (reports) PID: $CF_REPORTS_PID"

info "等待隧道 URL（最多 45s）..."
CF_APP_URL=""
CF_REPORTS_URL=""

# 并行等待两个隧道 URL
CF_APP_URL=$(get_cf_url "$CF_APP_LOG" 45)
CF_APP_RC=$?
if [[ $CF_APP_RC -ne 0 ]]; then
    err "AI 创作工作室隧道 URL 获取失败"
    err "查看日志: $CF_APP_LOG"
    CF_APP_URL="(失败)"
fi

CF_REPORTS_URL=$(get_cf_url "$CF_REPORTS_LOG" 45)
CF_REPORTS_RC=$?
if [[ $CF_REPORTS_RC -ne 0 ]]; then
    err "测试报告隧道 URL 获取失败"
    err "查看日志: $CF_REPORTS_LOG"
    CF_REPORTS_URL="(失败)"
fi

# ---------- 4. 打印结果 ----------

LAN_IP=$(get_lan_ip)

echo ""
echo -e "${BOLD}════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  AMD AI Studio — 双服务启动完成${NC}"
echo -e "${BOLD}════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${GREEN}【服务 1】AI 创作工作室${NC}"
echo -e "  内网访问:  http://${LAN_IP}:${APP_PORT}"
echo -e "  外网访问:  ${CF_APP_URL}"
echo -e "  PID:       ${APP_PID} (app) + ${CF_APP_PID} (cloudflared)"
echo -e "  日志:      ${APP_LOG} / ${CF_APP_LOG}"
echo ""
echo -e "${GREEN}【服务 2】测试报告${NC}"
echo -e "  内网访问:  http://${LAN_IP}:${REPORTS_PORT}/index.html"
echo -e "  外网访问:  ${CF_REPORTS_URL}/index.html"
echo -e "  PID:       ${REPORTS_PID} (http.server) + ${CF_REPORTS_PID} (cloudflared)"
echo -e "  日志:      ${REPORTS_LOG} / ${CF_REPORTS_LOG}"
echo ""
echo -e "${BOLD}════════════════════════════════════════════════════════════${NC}"
echo -e "  提示：外网地址为 trycloudflare 临时域名，进程被杀后失效"
echo -e "  停止服务:  bash scripts/stop_services.sh"
echo -e "${BOLD}════════════════════════════════════════════════════════════${NC}"

exit 0
