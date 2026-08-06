#!/bin/bash
set -e

# ====================== 配置区 ======================
VENV_PATH="/persistent/amd_ai_env"
WORK_DIR="/workspace"
WEBUI_DIR="${WORK_DIR}/stable-diffusion-webui"
COMFY_DIR="${WORK_DIR}/ComfyUI"
ROCM_VAR1="export ROCM_PATH=/opt/rocm"
ROCM_VAR2="export HSA_OVERRIDE_GFX_VERSION=11.0.0"
# ===============================================================

echo "============================================="
echo "        AMD ROCm AI绘图一键部署脚本（适配ROCm7.7 PyTorch）"
echo " 虚拟环境存放路径：${VENV_PATH}"
echo "============================================="

# 1. 创建虚拟环境（不存在才新建）
if [ ! -d "${VENV_PATH}" ];then
    echo "[1] 创建Python虚拟环境"
    python3 -m venv ${VENV_PATH}
else
    echo "[1] 虚拟环境已存在，跳过创建"
fi

# 2. 虚拟环境激活脚本内置ROCm环境变量
echo "[2] 注入ROCm环境变量至虚拟环境"
grep -qxF "${ROCM_VAR1}" ${VENV_PATH}/bin/activate || echo "${ROCM_VAR1}" >> ${VENV_PATH}/bin/activate
grep -qxF "${ROCM_VAR2}" ${VENV_PATH}/bin/activate || echo "${ROCM_VAR2}" >> ${VENV_PATH}/bin/activate

# 3. 激活虚拟环境
source ${VENV_PATH}/bin/activate
echo "✅ 当前虚拟环境：$VIRTUAL_ENV"

# 4. 安装ROCm7.7版本Pytorch（修复7.8无安装包问题）
echo "[3] 安装ROCm7.7 PyTorch套件"
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm7.7

# 5. GPU识别自检
echo "[4] 执行GPU可用性检测"
python3 -c "
import torch
print('PyTorch版本:',torch.__version__)
print('HIP版本:',torch.version.hip)
print('GPU可用状态:',torch.cuda.is_available())
print('识别显卡数量:',torch.cuda.device_count())
if torch.cuda.is_available():
    for i in range(torch.cuda.device_count()):
        print(f'GPU{i}: {torch.cuda.get_device_name(i)}')
"

# 6. 拉取A1111 WebUI
echo "[5] 准备 Stable Diffusion WebUI"
if [ ! -d "${WEBUI_DIR}" ];then
    cd ${WORK_DIR}
    git clone https://github.com/AUTOMATIC1111/stable-diffusion-webui.git
fi
cd ${WEBUI_DIR}
# 生成启动脚本
cat > run_webui.sh <<'EOF'
#!/bin/bash
source /persistent/amd_ai_env/bin/activate
cd /workspace/stable-diffusion-webui
python3 webui.py --rocm --skip-torch-cuda-test --listen --port 7860 --xformers
EOF
chmod +x run_webui.sh

# 7. 拉取ComfyUI
echo "[6] 准备 ComfyUI"
if [ ! -d "${COMFY_DIR}" ];then
    cd ${WORK_DIR}
    git clone https://github.com/comfyanonymous/ComfyUI.git
fi
cd ${COMFY_DIR}
pip install -r requirements.txt
# 生成启动脚本
cat > run_comfy.sh <<'EOF'
#!/bin/bash
source /persistent/amd_ai_env/bin/activate
cd /workspace/ComfyUI
python3 main.py --listen --port 8188
EOF
chmod +x run_comfy.sh

echo ""
echo "============================================="
echo "🎉 全部部署完成！"
echo "---------------------------------------------"
echo "启动 WebUI 命令：cd ${WEBUI_DIR} && ./run_webui.sh"
echo "访问地址：http://服务器IP:7860"
echo "---------------------------------------------"
echo "启动 ComfyUI 命令：cd ${COMFY_DIR} && ./run_comfy.sh"
echo "访问地址：http://服务器IP:8188"
echo "============================================="
