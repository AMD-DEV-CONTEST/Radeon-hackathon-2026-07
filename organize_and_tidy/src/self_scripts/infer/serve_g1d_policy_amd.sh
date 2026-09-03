#!/bin/bash
# ==============================================================================
# G1-D OpenPI Policy Server（AMD 云 / PyTorch full 模型）
#
# 功能:
#   - 启动前自动清理同端口旧 Server 进程
#   - 使用项目 .venv + 预置 ROCm PyTorch 环境
#   - 可选通过 Radeon Cloud rc-tunnel 暴露到公网（本地 Client 可远程调用）
#   - Ctrl+C / kill 脚本时自动停止 Server 与 Tunnel
#
# 用法:
#   bash self_scripts/infer/serve_g1d_policy_amd.sh
#   RC_TUNNEL=1 bash self_scripts/infer/serve_g1d_policy_amd.sh
#   SERVER_PORT=8001 bash self_scripts/infer/serve_g1d_policy_amd.sh
#
# rc-tunnel 参考:
#   https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/tree/main/Radeon-Cloud-User%20Guide
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OPENPI_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── 可配置参数（AMD 云 full 模型默认值）────────────────────────────
CHECKPOINT_DIR="${CHECKPOINT_DIR:-${OPENPI_ROOT}/checkpoints/pi05_g1d_joint_full_pytorch/Organize_table_normal_start/29999}"
CONFIG_NAME="${CONFIG_NAME:-pi05_g1d_joint_full}"
INSTRUCTION="${INSTRUCTION:-Organize and tidy the items on the table.}"
SERVER_PORT="${SERVER_PORT:-8000}"
SERVER_HOST="${SERVER_HOST:-127.0.0.1}"
GPU="${GPU:-0}"
MAX_WAIT="${MAX_WAIT:-300}"
SERVER_LOG="${SERVER_LOG:-${OPENPI_ROOT}/logs/openpi_server_amd.log}"
TUNNEL_URL_FILE="${TUNNEL_URL_FILE:-${OPENPI_ROOT}/logs/rc_tunnel_url.txt}"

# 设为 1 启用 Radeon Cloud rc-tunnel 公网暴露（仅支持新版 Notebook Pod）
RC_TUNNEL="${RC_TUNNEL:-0}"
# tunnel 不可用时：1=直接退出；0=仅启动 Server 并提示替代方案
RC_TUNNEL_STRICT="${RC_TUNNEL_STRICT:-1}"
RC_TUNNEL_BIN="${RC_TUNNEL_BIN:-${HOME}/.local/bin/rc-tunnel}"
RC_TUNNEL_INSTALL="${RC_TUNNEL_INSTALL:-/var/run/secrets/frp-self-service/install}"
RC_TUNNEL_CA_FILE="${RC_TUNNEL_CA_FILE:-/var/run/secrets/frp-self-service/ca.crt}"

SERVER_PID=""
TUNNEL_ENABLED=0
TUNNEL_PUBLIC_URL=""

stop_existing_server() {
    local pids
    pids="$(pgrep -f "scripts/serve_policy.py.*--port=${SERVER_PORT}" 2>/dev/null || true)"
    if [ -n "${pids}" ]; then
        echo "── 停止占用端口 ${SERVER_PORT} 的旧 Server ──"
        # shellcheck disable=SC2086
        kill ${pids} 2>/dev/null || true
        sleep 1
        pids="$(pgrep -f "scripts/serve_policy.py.*--port=${SERVER_PORT}" 2>/dev/null || true)"
        if [ -n "${pids}" ]; then
            # shellcheck disable=SC2086
            kill -9 ${pids} 2>/dev/null || true
            sleep 1
        fi
    fi
}

print_tunnel_unavailable_help() {
    cat <<'EOF'
❌ 当前环境无法使用 rc-tunnel（Radeon Cloud Tunnel）

文档要求（Expose a Notebook service to the internet）:
  1. 必须使用「启用 Tunnel 功能之后创建」的新 Notebook Pod
  2. 在 JupyterLab Terminal 中运行（不是旧 Pod / 非 Notebook 环境）
  3. 平台需注入 FRP_BROKER_URL / FRP_BROKER_TLS_SERVER_NAME
  4. 若 identity 目录或 FRP_BROKER_URL 不存在 → 关闭并重建 Notebook

你当前环境检测结果:
EOF
    echo "  FRP_BROKER_URL              : ${FRP_BROKER_URL:-<未注入>}"
    echo "  FRP_BROKER_TLS_SERVER_NAME  : ${FRP_BROKER_TLS_SERVER_NAME:-<未注入>}"
    echo "  ca.crt                      : ${RC_TUNNEL_CA_FILE} ($([ -s "${RC_TUNNEL_CA_FILE}" ] && echo 存在 || echo 缺失))"
    echo "  rc-tunnel 二进制            : ${RC_TUNNEL_BIN} ($([ -x "${RC_TUNNEL_BIN}" ] && echo 已安装 || echo 未安装))"
    cat <<'EOF'

替代方案（SSH 实例 / Tunnel 不可用时）:
  在本地 PC 做端口转发，无需 rc-tunnel:
    ssh -L 8000:127.0.0.1:8000 <user>@<host> -p <port>
  然后本地 Client 连接:
    --server_host localhost --server_port 8000

参考:
  https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/tree/main/Radeon-Cloud-User%20Guide
EOF
}

check_rc_tunnel_prerequisites() {
    local missing=0
    if [ -z "${FRP_BROKER_URL:-}" ]; then
        missing=1
    fi
    if [ -z "${FRP_BROKER_TLS_SERVER_NAME:-}" ]; then
        missing=1
    fi
    if [ ! -s "${RC_TUNNEL_CA_FILE}" ]; then
        missing=1
    fi
    if [ "${missing}" = "1" ] && [ ! -x "${RC_TUNNEL_BIN}" ]; then
        return 1
    fi
    return 0
}

ensure_rc_tunnel() {
    export PATH="${HOME}/.local/bin:${PATH}"
    if [ -x "${RC_TUNNEL_BIN}" ]; then
        return 0
    fi
    if ! check_rc_tunnel_prerequisites; then
        print_tunnel_unavailable_help
        return 1
    fi
    if [ ! -x "${RC_TUNNEL_INSTALL}" ]; then
        echo "❌ 未找到 rc-tunnel 安装脚本: ${RC_TUNNEL_INSTALL}"
        return 1
    fi
    echo "── 安装 rc-tunnel ──"
    if ! "${RC_TUNNEL_INSTALL}"; then
        echo "❌ rc-tunnel 安装失败"
        return 1
    fi
    if [ ! -x "${RC_TUNNEL_BIN}" ]; then
        echo "❌ rc-tunnel 安装后仍未找到: ${RC_TUNNEL_BIN}"
        return 1
    fi
}

stop_rc_tunnel() {
    if [ "${TUNNEL_ENABLED}" != "1" ]; then
        return 0
    fi
    if [ -x "${RC_TUNNEL_BIN}" ]; then
        echo ""
        echo "── 清理: 停止 rc-tunnel ──"
        "${RC_TUNNEL_BIN}" stop 2>/dev/null || true
    fi
    TUNNEL_ENABLED=0
}

cleanup() {
    local exit_code=$?
    stop_rc_tunnel
    if [ -n "${SERVER_PID}" ] && kill -0 "${SERVER_PID}" 2>/dev/null; then
        echo ""
        echo "── 清理: 停止 Server (PID=${SERVER_PID}) ──"
        kill "${SERVER_PID}" 2>/dev/null || true
        wait "${SERVER_PID}" 2>/dev/null || true
    fi
    exit "${exit_code}"
}

wait_for_healthz() {
    local wait_count=0
    local health_url="http://127.0.0.1:${SERVER_PORT}/healthz"
    local http_code

    echo ""
    echo "── 等待 Server 就绪 (${health_url}) ──"
    while [ "${wait_count}" -lt "${MAX_WAIT}" ]; do
        if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
            echo "❌ Server 进程已退出，查看日志: ${SERVER_LOG}"
            tail -30 "${SERVER_LOG}" 2>/dev/null || true
            exit 1
        fi

        http_code="$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "${health_url}" 2>/dev/null || echo "000")"
        if [ "${http_code}" = "200" ]; then
            echo "  ✅ Server 已就绪 (HTTP ${http_code}, 等待 ${wait_count}s)"
            echo "  本地健康检查: curl ${health_url}"
            return 0
        fi

        wait_count=$((wait_count + 2))
        printf "  等待中... (%ds / %ds)\r" "${wait_count}" "${MAX_WAIT}"
        sleep 2
    done

    echo ""
    echo "❌ Server 启动超时 (${MAX_WAIT}s)，查看日志: ${SERVER_LOG}"
    tail -30 "${SERVER_LOG}" 2>/dev/null || true
    exit 1
}

expose_rc_tunnel() {
    local expose_output
    local public_url
    local health_code

    if ! ensure_rc_tunnel; then
        if [ "${RC_TUNNEL_STRICT}" = "1" ]; then
            return 1
        fi
        echo ""
        echo "⚠️  RC_TUNNEL=1 但 tunnel 不可用，已跳过公网暴露，Server 继续在本地运行"
        echo "   如需强制失败可设 RC_TUNNEL_STRICT=1（默认）"
        return 0
    fi
    export PATH="${HOME}/.local/bin:${PATH}"

    echo ""
    echo "── 暴露 rc-tunnel (本地端口 ${SERVER_PORT}) ──"
    echo "  ⚠️  公网 URL 可被互联网访问，请勿暴露未鉴权的敏感服务"

    "${RC_TUNNEL_BIN}" stop 2>/dev/null || true
    expose_output="$("${RC_TUNNEL_BIN}" expose --port "${SERVER_PORT}" 2>&1)" || {
        echo "${expose_output}"
        echo "❌ rc-tunnel expose 失败"
        if [ "${RC_TUNNEL_STRICT}" = "1" ]; then
            return 1
        fi
        echo "⚠️  已跳过 tunnel，Server 继续在本地运行"
        return 0
    }
    echo "${expose_output}"

    public_url="$(printf '%s\n' "${expose_output}" | grep -Eo 'https://[^[:space:]\"]+' | head -1 || true)"
    if [ -z "${public_url}" ]; then
        echo "❌ 未能从 rc-tunnel 输出中解析公网 URL"
        exit 1
    fi

    TUNNEL_PUBLIC_URL="${public_url}"
    TUNNEL_ENABLED=1
    mkdir -p "$(dirname "${TUNNEL_URL_FILE}")"
    printf '%s\n' "${TUNNEL_PUBLIC_URL}" > "${TUNNEL_URL_FILE}"

    echo ""
    echo "  等待公网 healthz 就绪..."
    local wait_count=0
    while [ "${wait_count}" -lt 60 ]; do
        health_code="$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
            "${TUNNEL_PUBLIC_URL}/healthz" 2>/dev/null || echo "000")"
        if [ "${health_code}" = "200" ]; then
            echo "  ✅ 公网 Tunnel 已就绪"
            break
        fi
        wait_count=$((wait_count + 2))
        sleep 2
    done

    if [ "${health_code}" != "200" ]; then
        echo "  ⚠️  公网 healthz 暂未返回 200，请稍后手动验证:"
        echo "     curl ${TUNNEL_PUBLIC_URL}/healthz"
    fi

    local wss_url="wss://${TUNNEL_PUBLIC_URL#https://}"
    echo ""
    echo "============================================================"
    echo "  公网访问信息 (rc-tunnel)"
    echo "============================================================"
    echo "  HTTPS healthz : ${TUNNEL_PUBLIC_URL}/healthz"
    echo "  WebSocket     : ${wss_url}"
    echo "  URL 已保存    : ${TUNNEL_URL_FILE}"
    echo ""
    echo "  本地虚拟测试 Client:"
    echo "    python self_scripts/infer/test_amd_policy_client.py \\"
    echo "      --wss-url ${wss_url}"
    echo ""
    echo "  本地真机 Client (示例):"
    echo "    python self_scripts/infer/client_g1d_joint.py \\"
    echo "      --server_host ${wss_url} \\"
    echo "      --image_host <JETSON_IP> --instruction \"${INSTRUCTION}\""
    echo "============================================================"
}

echo "============================================================"
echo "  G1-D OpenPI Policy Server (AMD / PyTorch full)"
echo "============================================================"
echo "  Config         : ${CONFIG_NAME}"
echo "  Checkpoint     : ${CHECKPOINT_DIR}"
echo "  Listen         : ${SERVER_HOST}:${SERVER_PORT}"
echo "  GPU            : ${GPU}"
echo "  Instruction    : ${INSTRUCTION}"
echo "  RC_TUNNEL      : ${RC_TUNNEL}"
echo "  OpenPI Root    : ${OPENPI_ROOT}"
echo "  Server Log     : ${SERVER_LOG}"
echo "============================================================"

if [ ! -d "${CHECKPOINT_DIR}" ]; then
    echo "❌ Checkpoint 目录不存在: ${CHECKPOINT_DIR}"
    exit 1
fi

if [ ! -f "${OPENPI_ROOT}/.venv/bin/activate" ]; then
    echo "❌ 未找到虚拟环境: ${OPENPI_ROOT}/.venv"
    echo "   请先按 AMD 部署文档创建 .venv 并安装依赖"
    exit 1
fi

if [ "${RC_TUNNEL}" = "1" ] && [ "${RC_TUNNEL_STRICT}" = "1" ]; then
    if ! check_rc_tunnel_prerequisites && [ ! -x "${RC_TUNNEL_BIN}" ]; then
        print_tunnel_unavailable_help
        echo ""
        echo "若仅需本地/SSH 端口转发启动 Server，请改用:"
        echo "  bash self_scripts/infer/serve_g1d_policy_amd.sh"
        echo "或允许 tunnel 失败时继续:"
        echo "  RC_TUNNEL=1 RC_TUNNEL_STRICT=0 bash self_scripts/infer/serve_g1d_policy_amd.sh"
        exit 1
    fi
fi

mkdir -p "${OPENPI_ROOT}/logs"
stop_existing_server

# shellcheck disable=SC1091
source "${OPENPI_ROOT}/.venv/bin/activate"
cd "${OPENPI_ROOT}"

export CUDA_VISIBLE_DEVICES="${GPU}"
export PATH="${OPENPI_ROOT}/.venv/bin:${PATH}"

trap cleanup EXIT INT TERM

echo ""
echo "── 启动 Policy Server ──"
# rc-tunnel 要求服务监听 127.0.0.1；绑定 0.0.0.0 时改为 SERVER_HOST=127.0.0.1
# serve_policy.py 当前固定 host=0.0.0.0，127.0.0.1 访问仍可用
CUDA_VISIBLE_DEVICES="${GPU}" python scripts/serve_policy.py \
    --port="${SERVER_PORT}" \
    --default_prompt="${INSTRUCTION}" \
    policy:checkpoint \
    --policy.config="${CONFIG_NAME}" \
    --policy.dir="${CHECKPOINT_DIR}" \
    >> "${SERVER_LOG}" 2>&1 &
SERVER_PID=$!
echo "  Server PID: ${SERVER_PID}"
echo "  Server log: ${SERVER_LOG}"

wait_for_healthz

if [ "${RC_TUNNEL}" = "1" ]; then
    if ! expose_rc_tunnel; then
        if [ "${RC_TUNNEL_STRICT}" = "1" ]; then
            exit 1
        fi
    fi
fi

echo ""
echo "── Server 运行中，按 Ctrl+C 或 kill 本脚本即可停止 ──"
wait "${SERVER_PID}"
