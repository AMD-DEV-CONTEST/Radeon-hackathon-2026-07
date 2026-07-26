#!/bin/bash
# ==============================================================================
# G1-D OpenPI Client-only 推理脚本 (连接本地或云端 Policy Server)
#
# 与 run_g1d_pi05.sh 的 Client 段使用相同环境:
#   - PYTHONPATH (pinocchio / cyclonedds)
#   - DDS 网卡绑定 (ChannelFactoryInitialize)
#   - 在 unitree_lerobot 根目录运行 (URDF 相对路径)
#
# 用法 (云端 AMD GPU):
#   bash self_scripts/infer/run_g1d_client.sh \
#     --server_host wss://rc-xxxx.radeon.firstdg.ai \
#     --image_host 192.168.123.164 \
#     --instruction "Organize and tidy the items on the table."
#
# 可选环境变量:
#   IMAGE_TRANSPORT=jpeg|raw|auto   远程默认 auto→jpeg
#   JPEG_QUALITY=80
#   IMAGE_MAX_SIZE=224              传输前 letterbox 缩放边长
#
# 用法 (本地 Server):
#   bash self_scripts/infer/run_g1d_client.sh \
#     --server_host localhost --server_port 8000
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OPENPI_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SERVER_HOST="${SERVER_HOST:-localhost}"
SERVER_PORT="${SERVER_PORT:-8000}"
IMAGE_HOST="${IMAGE_HOST:-192.168.123.164}"
FREQUENCY="${FREQUENCY:-30}"
INSTRUCTION="${INSTRUCTION:-Organize and tidy the items on the table.}"
DATASET_PATH="${DATASET_PATH:-}"
EPISODE_INDEX="${EPISODE_INDEX:-0}"
DDS_INTERFACE="${DDS_INTERFACE:-${UNITREE_SDK_INTERFACE:-}}"
ROBOT_SUBNET="${ROBOT_SUBNET:-192.168.123.}"
DISPLAY_DATA="${DISPLAY_DATA:-}"
VIEWER_IP="${VIEWER_IP:-}"
VIEWER_PORT="${VIEWER_PORT:-}"
UNITREE_LEROBOT_ROOT="${UNITREE_LEROBOT_ROOT:-}"
G1_URDF_REL="unitree_lerobot/eval_robot/assets/g1/g1_body29_hand14.urdf"
PINOCCHIO_SITE_PACKAGES="${PINOCCHIO_SITE_PACKAGES:-/home/mailonghua/ws/vla/.pinocchio_py311/lib/python3.11/site-packages}"
IMAGE_TRANSPORT="${IMAGE_TRANSPORT:-auto}"
JPEG_QUALITY="${JPEG_QUALITY:-80}"
IMAGE_MAX_SIZE="${IMAGE_MAX_SIZE:-224}"

detect_unitree_lerobot_root() {
    if [ -n "${UNITREE_LEROBOT_ROOT}" ]; then
        echo "${UNITREE_LEROBOT_ROOT}"
        return
    fi
    python - <<PY
import os
urdf_rel = "${G1_URDF_REL}"
candidates = []

try:
    import unitree_lerobot
except ImportError:
    pass
else:
    pkg_file = getattr(unitree_lerobot, "__file__", None)
    if pkg_file:
        candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(pkg_file))))
    elif getattr(unitree_lerobot, "__path__", None):
        candidates.append(os.path.dirname(os.path.abspath(unitree_lerobot.__path__[0])))

for path in (
    "/home/mailonghua/ws/vla/unitree_lerobot",
    os.path.join("${OPENPI_ROOT}", "..", "unitree_lerobot"),
    "/home/mailonghua/ws/unitree_lerobot",
):
    candidates.append(os.path.abspath(path))

seen = set()
for root in candidates:
    if not root or root in seen:
        continue
    seen.add(root)
    if os.path.isfile(os.path.join(root, urdf_rel)):
        print(root)
        break
PY
}

detect_dds_interface() {
    if [ -n "${DDS_INTERFACE}" ]; then
        echo "${DDS_INTERFACE}"
        return
    fi
    python - <<PY
import re, subprocess
subnet = "${ROBOT_SUBNET}"
try:
    out = subprocess.check_output(["ip", "-br", "addr"], text=True, stderr=subprocess.DEVNULL)
except Exception:
    pass
else:
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[0] == "lo":
            continue
        for token in parts[2:]:
            m = re.match(r"(\d+\.\d+\.\d+\.\d+)/", token)
            if m and m.group(1).startswith(subnet):
                print(parts[0])
                break
        else:
            continue
        break
PY
}

launch_client_with_dds() {
    local client_script="$1"
    shift
    export DDS_IFACE="${DDS_IFACE}"
    export UNITREE_SDK_INTERFACE="${DDS_IFACE}"
    export PYTHONPATH="${PINOCCHIO_SITE_PACKAGES}:${PYTHONPATH:-}"
    python -c '
import os
import runpy
import sys

from unitree_sdk2py.core.channel import ChannelFactoryInitialize

iface = os.environ["DDS_IFACE"]
ChannelFactoryInitialize(0, iface)
print(f"  ✅ DDS ChannelFactory 已绑定网卡: {iface}")

client_script = sys.argv[1]
sys.argv = [client_script, *sys.argv[2:]]
runpy.run_path(client_script, run_name="__main__")
' "${client_script}" "$@"
}

# 解析 --key value 覆盖环境变量默认值
EXTRA_ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --server_host)
            SERVER_HOST="$2"
            shift 2
            ;;
        --server_port)
            SERVER_PORT="$2"
            shift 2
            ;;
        --image_host)
            IMAGE_HOST="$2"
            shift 2
            ;;
        --instruction)
            INSTRUCTION="$2"
            shift 2
            ;;
        --frequency)
            FREQUENCY="$2"
            shift 2
            ;;
        --dataset_path)
            DATASET_PATH="$2"
            shift 2
            ;;
        --episode_index)
            EPISODE_INDEX="$2"
            shift 2
            ;;
        --image_transport)
            IMAGE_TRANSPORT="$2"
            shift 2
            ;;
        --jpeg_quality)
            JPEG_QUALITY="$2"
            shift 2
            ;;
        --image_max_size)
            IMAGE_MAX_SIZE="$2"
            shift 2
            ;;
        --display_data|--no-display_data)
            EXTRA_ARGS+=("$1")
            shift
            ;;
        --viewer_ip|--viewer_port)
            EXTRA_ARGS+=("$1" "$2")
            shift 2
            ;;
        -h|--help)
            sed -n '1,20p' "$0"
            exit 0
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

DDS_IFACE="$(detect_dds_interface)"
UNITREE_ROOT="$(detect_unitree_lerobot_root)"

echo "============================================================"
echo "  G1-D OpenPI 推理 Client-only"
echo "============================================================"
echo "  Server        : ${SERVER_HOST}"
if [[ "${SERVER_HOST}" != ws://* && "${SERVER_HOST}" != wss://* ]]; then
    echo "  Server Port   : ${SERVER_PORT}"
fi
echo "  Image Host    : ${IMAGE_HOST}"
echo "  Frequency     : ${FREQUENCY} Hz"
echo "  Instruction   : ${INSTRUCTION}"
if [ -n "${DDS_IFACE}" ]; then
    echo "  DDS Interface : ${DDS_IFACE}"
else
    echo "  DDS Interface : (未检测到 ${ROBOT_SUBNET}* 网卡)"
fi
if [ -n "${UNITREE_ROOT}" ]; then
    echo "  Unitree Root  : ${UNITREE_ROOT}"
fi
echo "  Image Transport: ${IMAGE_TRANSPORT} (quality=${JPEG_QUALITY}, max=${IMAGE_MAX_SIZE})"
echo "============================================================"
echo ""

if [ -z "${DDS_IFACE}" ]; then
    echo "❌ 未找到连接机器人的网卡 (${ROBOT_SUBNET}*)"
    echo "   示例: DDS_INTERFACE=enp3s0f1 bash self_scripts/infer/run_g1d_client.sh ..."
    exit 1
fi

if [ -z "${UNITREE_ROOT}" ]; then
    echo "❌ 未找到 unitree_lerobot 根目录"
    echo "   请设置: UNITREE_LEROBOT_ROOT=/path/to/unitree_lerobot"
    exit 1
fi

G1_URDF_PATH="${UNITREE_ROOT}/${G1_URDF_REL}"
if [ ! -f "${G1_URDF_PATH}" ]; then
    echo "❌ URDF 文件不存在: ${G1_URDF_PATH}"
    exit 1
fi

cd "${OPENPI_ROOT}"

DATASET_ARG=""
if [ -n "${DATASET_PATH}" ]; then
    DATASET_ARG="--dataset_path ${DATASET_PATH} --episode_index ${EPISODE_INDEX}"
fi

RERUN_ARG=""
if [ -n "${DISPLAY_DATA}" ]; then
    case "${DISPLAY_DATA}" in
        0|false|False|no|No) RERUN_ARG="--no-display_data" ;;
        1|true|True|yes|Yes) RERUN_ARG="--display_data" ;;
        *) echo "❌ 无效的 DISPLAY_DATA: ${DISPLAY_DATA}"; exit 1 ;;
    esac
fi
if [ -n "${VIEWER_IP}" ]; then
    RERUN_ARG="${RERUN_ARG} --viewer_ip ${VIEWER_IP}"
fi
if [ -n "${VIEWER_PORT}" ]; then
    RERUN_ARG="${RERUN_ARG} --viewer_port ${VIEWER_PORT}"
fi

echo "  工作目录: ${UNITREE_ROOT} (URDF 相对路径依赖)"
echo ""

(
    cd "${UNITREE_ROOT}"
    launch_client_with_dds "${SCRIPT_DIR}/client_g1d_joint.py" \
        --server_host "${SERVER_HOST}" \
        --server_port "${SERVER_PORT}" \
        --image_host "${IMAGE_HOST}" \
        --instruction "${INSTRUCTION}" \
        --frequency "${FREQUENCY}" \
        --image_transport "${IMAGE_TRANSPORT}" \
        --jpeg_quality "${JPEG_QUALITY}" \
        --image_max_size "${IMAGE_MAX_SIZE}" \
        ${DATASET_ARG} \
        ${RERUN_ARG} \
        "${EXTRA_ARGS[@]}"
)
