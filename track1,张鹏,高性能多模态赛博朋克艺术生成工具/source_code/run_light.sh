#!/usr/bin/env bash
# =============================================================================
# Aether Style — 启动脚本（原则：在配置允许的前提下，用最好的模型）
#
# 引擎会自动在配置（磁盘配额 / 模型授权）允许的范围内，为每个任务选最优模型：
#   · 文生图 / 图生图 : Stable Diffusion 3.5-Medium（Community License，~10GB，画质最佳）
#                        → 否则 SDXL（~7GB，非 gated，明显好于 v1.5）
#                        → 再否则 SD v1.5（~4GB 兜底）
#   · 文生视频        : Wan2.2-TI2V-5B（Wan-AI，5B DiT+umt5-xxl 原生中文，~34GB，720P@24fps）
#                        → 否则 LTX-Video（Lightricks，2B，兜底回退）
#                        → 再否则 Legacy SD T2V（damo-vilab 1.7b，最终兜底）
#
# 因此"最好"取决于你的机器配置：引擎不会去下载装不下的模型（磁盘不足时自动跳过/降级），
# 也不会因 gated / 配额满而崩溃——始终回退到可跑的模型。
#
# ⚠ 首次运行前请先清出足够磁盘空间（删除半成品权重 / HF 缓存 / 旧产物），否则所有模型都装不下。
#    示例：rm -rf models/* ~/.cache/huggingface/hub outputs/*
# =============================================================================
set -e
cd "$(dirname "$0")"

# 文生图默认 SDXL（非 gated、画质优于 v1.5；如需强制某档可用 AETHER_SD_MODEL=v1.5 覆盖）
export AETHER_SD_MODEL=sdxl
# SD3 默认启用（Stable Diffusion 3.5-Medium，Community License，画质最佳）。
# 显式 export AETHER_ENABLE_SD3=0 后再跑本脚本可关闭 SD3（例如极端小盘）。
export AETHER_ENABLE_SD3=1
# SD3 默认使用 Stable Diffusion 3.5-Medium（Community License，~10GB）。
# 可选覆盖：export AETHER_SD3_MODEL=large（SD3.5-Large，~16GB）
#           export AETHER_SD3_MODEL=turbo（SD3.5-Large-Turbo，~16GB，4步出图）
export AETHER_SD3_MODEL=medium
# 文生视频默认主模型 Wan2.2-TI2V-5B，引擎自动回退 LTX-Video → Legacy SD T2V。
# 可选覆盖：AETHER_T2V_MODEL=Lightricks/LTX-Video（强制走 LTX 回退）
#           AETHER_T2V_MODEL=Wan-AI/Wan2.2-TI2V-5B（默认，显式指定）
# 国内镜像，首次下载更快；若机器能直连 HF 可去掉下一行
export HF_ENDPOINT=https://hf-mirror.com

echo ">>> 启动 Aether Style（自动在配置允许范围内选择最优模型）"

# 清理上次残留进程，避免端口 7860 被占用
if [ -f /tmp/aether_app.pid ]; then
    OLD_PID=$(cat /tmp/aether_app.pid 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo ">>> 检测到上次残留进程 (PID=$OLD_PID)，正在清理..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f /tmp/aether_app.pid
fi

# 后台启动，记录 PID 以便下次清理
exec python3 app.py "$@" &
APP_PID=$!
echo $APP_PID > /tmp/aether_app.pid
wait $APP_PID
