#!/bin/bash
# ============================================
# ComfyUI + SDXL 重建恢复脚本（在"新实例"上执行）
# 前提：/persistent 已挂载（PVC 保留），内有:
#   - amd_ai_env  (venv, torch ROCm)
#   - comfyui/    (ComfyUI_src.tar.gz + models/模型)
#   - ssh_keys/   (登录密钥)
# ============================================
set -e
VENV=/persistent/amd_ai_env
COMFY=/workspace/ComfyUI
SRC_TAR=/persistent/comfyui/ComfyUI_src.tar.gz

echo "[1] 注入 ROCm 环境变量到 venv"
grep -qxF "export ROCM_PATH=/opt/rocm" $VENV/bin/activate || echo "export ROCM_PATH=/opt/rocm" >> $VENV/bin/activate
grep -qxF "export HSA_OVERRIDE_GFX_VERSION=11.0.0" $VENV/bin/activate || echo "export HSA_OVERRIDE_GFX_VERSION=11.0.0" >> $VENV/bin/activate

echo "[2] 恢复 ComfyUI 源码（/workspace 被清空后）"
if [ ! -d "$COMFY" ]; then
    mkdir -p "$COMFY"
    tar xzf "$SRC_TAR" -C /workspace
    echo "ComfyUI 已从备份恢复"
else
    echo "ComfyUI 目录已存在，跳过"
fi

echo "[3] 配置额外模型路径（指向 /persistent/comfyui/models）"
cat > $COMFY/extra_model_paths.yaml <<'YAML'
persistent:
    base_path: /persistent/comfyui
    checkpoints: models/
    vae: models/
    loras: models/loras/
    text_encoders: models/text_encoders/
    diffusion_models: models/diffusion_models/
    controlnet: models/controlnet/
    embeddings: models/embeddings/
    upscale_models: models/upscale_models/
YAML

echo "[4] 合并备用 SSH 公钥（不覆盖平台注入的密钥）"
if [ -f <SSH_KEY_DIR>/id_ed25519.pub ]; then
    mkdir -p /root/.ssh && chmod 700 /root/.ssh
    grep -qxF "$(cat <SSH_KEY_DIR>/id_ed25519.pub)" /root/.ssh/authorized_keys 2>/dev/null || \
        cat <SSH_KEY_DIR>/id_ed25519.pub >> /root/.ssh/authorized_keys
    chmod 600 /root/.ssh/authorized_keys
    echo "备用密钥已合并"
fi

echo "[5] 校验 GPU 环境"
source $VENV/bin/activate
python -c "import torch; print('torch', torch.__version__, '| gpu:', torch.cuda.get_device_name(0))"

echo "[6] 安装 openssh-server（如需平台 SSH，仍需在模板开启 SSH Access）"
command -v sshd >/dev/null || apt-get install -y -qq openssh-server >/dev/null
mkdir -p /run/sshd
pgrep -x sshd >/dev/null || /usr/sbin/sshd
echo "sshd 已启动"

echo "[7] 启动 ComfyUI (127.0.0.1:8188)"
setsid bash -c "export ROCM_PATH=/opt/rocm HSA_OVERRIDE_GFX_VERSION=11.0.0; cd $COMFY && exec $VENV/bin/python main.py --listen 127.0.0.1 --port 8188 > /tmp/comfyui_run.log 2>&1" < /dev/null &
sleep 5
curl -s -o /dev/null -w "ComfyUI HTTP %{http_code}\n" http://127.0.0.1:8188/ || echo "ComfyUI 启动中，稍后检查 /tmp/comfyui_run.log"

echo "============================================="
echo "恢复完成！访问方式见 /persistent/访问说明.md"
echo "============================================="
