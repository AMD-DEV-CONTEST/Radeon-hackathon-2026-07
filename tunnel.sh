#!/bin/bash
set -Eeuo pipefail

# ==========================================
# 精简版 radeon-tunnel 内网穿透脚本
# 暴露本地 7860 端口到公网
# ==========================================

# --- 配置（可按需修改）---
EXPOSE_PORT="${EXPOSE_PORT:-7860}"
TUNNEL_BIN="${TUNNEL_BIN:-/tmp/radeon-tunnel}"
TUNNEL_SERVER="${TUNNEL_SERVER:-http://36.150.116.206:20080}"
TUNNEL_URL_TIMEOUT="${TUNNEL_URL_TIMEOUT:-60}"
RADEON_TUNNEL_AUTH="${RADEON_TUNNEL_AUTH:-4de02807e814ca0f0722f97faef8488d}"

TUNNEL_PID_FILE="/tmp/tunnel.pid"
TUNNEL_LOG="/tmp/tunnel.log"
TUNNEL_PID=""

# --- 清理函数 ---
cleanup() {
    trap - EXIT INT TERM

    if [[ -n "${TUNNEL_PID}" ]] && kill -0 "${TUNNEL_PID}" 2>/dev/null; then
        echo "[cleanup] 停止 tunnel PID ${TUNNEL_PID}"
        kill "${TUNNEL_PID}" >/dev/null 2>&1 || true
    fi
    rm -f "${TUNNEL_PID_FILE}"
}

trap cleanup EXIT INT TERM

# --- 清理旧进程 ---
if [[ -f "${TUNNEL_PID_FILE}" ]]; then
    OLD_PID=$(cat "${TUNNEL_PID_FILE}" 2>/dev/null || true)
    if [[ "${OLD_PID}" =~ ^[0-9]+$ ]] && kill -0 "${OLD_PID}" 2>/dev/null; then
        echo "[cleanup] 停止旧 tunnel PID ${OLD_PID}"
        kill "${OLD_PID}" 2>/dev/null || true
    fi
    rm -f "${TUNNEL_PID_FILE}"
fi

# --- 下载客户端 ---
export RADEON_TUNNEL_AUTH

echo "[tunnel] 下载 radeon-tunnel 客户端..."
curl --noproxy '*' -fsSL "${TUNNEL_SERVER}/client" -o "${TUNNEL_BIN}"
chmod +x "${TUNNEL_BIN}"

# --- 清理旧状态 ---
rm -rf "${HOME:-/root}/.radeon"
rm -f "${TUNNEL_LOG}"

# --- 启动隧道 ---
echo "[tunnel] 启动 radeon-tunnel expose ${EXPOSE_PORT}"
nohup "${TUNNEL_BIN}" expose "${EXPOSE_PORT}" > "${TUNNEL_LOG}" 2>&1 &
TUNNEL_PID=$!
echo "${TUNNEL_PID}" > "${TUNNEL_PID_FILE}"
echo "[tunnel] Tunnel PID: ${TUNNEL_PID}"

# --- 等待公网 URL ---
echo "[tunnel] 等待公网 URL..."
PUBLIC_URL=""

for ((i = 1; i <= TUNNEL_URL_TIMEOUT; i++)); do
    sleep 1

    if ! kill -0 "${TUNNEL_PID}" 2>/dev/null; then
        echo "[error] Tunnel 进程异常退出"
        echo "[error] 日志："
        tail -n 80 "${TUNNEL_LOG}" || true
        exit 1
    fi

    PUBLIC_URL=$(grep -Eo 'https?://[^[:space:]]+' "${TUNNEL_LOG}" 2>/dev/null | head -1 || true)

    if [[ -n "${PUBLIC_URL}" ]]; then
        break
    fi
done

# --- 结果输出 ---
if [[ -n "${PUBLIC_URL}" ]]; then
    echo ""
    echo "========================================"
    echo "✅ 公网 URL: ${PUBLIC_URL}"
    echo "========================================"
else
    echo "[error] ${TUNNEL_URL_TIMEOUT}s 内未获取到公网 URL"
    echo "[error] 日志："
    tail -n 40 "${TUNNEL_LOG}" || true
    exit 2
fi

# --- 保持运行 ---
echo ""
echo "[tunnel] 隧道运行中，按 Ctrl+C 退出..."
wait "${TUNNEL_PID}"
