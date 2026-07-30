#!/bin/bash
set -euo pipefail
# set -e 出错终止；-u 未定义变量报错；pipefail 管道命令失败也退出

# 全局路径常量，统一管理
WORKSPACE="/workspace"
VENV_DIR="${WORKSPACE}/comfyuipy"
COMFY_ROOT="${WORKSPACE}/ComfyUI"
CUSTOM_NODES="${COMFY_ROOT}/custom_nodes"

echo "==================== 1. 创建并激活Python虚拟环境 ===================="
mkdir -p "${VENV_DIR}"
python3 -m venv "${VENV_DIR}"
# 脚本内激活虚拟环境
source "${VENV_DIR}/bin/activate"
echo "✅ 虚拟环境激活完成，当前pip：$(which pip)"

echo -e "\n==================== 2. 拉取/更新ComfyUI主程序 ===================="
if [ ! -d "${COMFY_ROOT}" ]; then
    git clone http://github.com/Comfy-Org/ComfyUI.git "${COMFY_ROOT}"
else
    echo "ComfyUI目录已存在，执行代码更新 git pull"
    cd "${COMFY_ROOT}"
    git pull
fi
cd "${COMFY_ROOT}"

echo -e "\n==================== 3. 安装ROCm7.2配套PyTorch及基础依赖 ===================="
# ROCm7.2专用torch
pip install torch torchvision torchaudio --index-url https://mirrors.nju.edu.cn/pytorch/whl/rocm7.2
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/
pip install gradio==6.20.0 -i https://pypi.tuna.tsinghua.edu.cn/simple/
pip install modelscope

echo -e "\n==================== 4. 下载大模型（断点续传+自动重试） ===================="
modelscope download --model 1038lab/Qwen-Image-Edit-2511-FP8 Qwen-Image-Edit-2511-FP8_e4m3fn.safetensors --local_dir "${WORKSPACE}"

cd "${WORKSPACE}"
# 模型下载地址数组
model_links=(
"https://hf-mirror.com/Comfy-Org/HunyuanVideo_1.5_repackaged/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"
"https://hf-mirror.com/lightx2v/Qwen-Image-Edit-2511-Lightning/resolve/main/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"
"https://hf-mirror.com/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors"
)

# wget参数说明：
# -c 断点续传、--retry-connrefused 连接失败重试、-t 10 最大重试10次
# 移除无效参数 -x 8（wget无多线程分片功能）
echo "开始下载，共 ${#model_links[@]} 个文件"

index=1
for link in "${model_links[@]}"; do
    echo "========================================"
    echo "正在下载第 ${index}/${#model_links[@]} 个文件：${link}"
    echo "========================================"
    # 串行执行，不带&后台符，执行完成才进入下一次循环
    wget -c --retry-connrefused -t 10 --timeout=30 --show-progress "${link}"
    # 判断单个文件下载是否失败
    if [ $? -ne 0 ]; then
        echo "警告：当前文件下载失败，继续下一个文件"
    fi
    index=$((index + 1))
done

echo "✅ 所有模型文件下载完毕"

echo -e "\n==================== 5. 自动分发模型到对应目录 ===================="
# 提前创建所有模型目录，避免mv报错
mkdir -p "${COMFY_ROOT}/models/text_encoders"
mkdir -p "${COMFY_ROOT}/models/loras"
mkdir -p "${COMFY_ROOT}/models/diffusion_models"
mkdir -p "${COMFY_ROOT}/models/vae"

# -f 强制覆盖已有文件，无需交互确认
mv -f "${WORKSPACE}/Qwen-Image-Edit-2511-FP8_e4m3fn.safetensors" "${COMFY_ROOT}/models/diffusion_models/"
mv -f "${WORKSPACE}/qwen_2.5_vl_7b_fp8_scaled.safetensors" "${COMFY_ROOT}/models/text_encoders/"
mv -f "${WORKSPACE}/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors" "${COMFY_ROOT}/models/loras/"
mv -f "${WORKSPACE}/qwen_image_vae.safetensors" "${COMFY_ROOT}/models/vae/"
echo "✅ 模型文件移动完成"

echo -e "\n==================== 6. 批量安装ComfyUI自定义节点插件 ===================="
mkdir -p "${CUSTOM_NODES}"
cd "${CUSTOM_NODES}"
# 插件仓库地址数组
plugins=(
"http://github.com/lrzjason/ComfyUI-EditUtils"
"http://github.com/lrzjason/Comfyui-QwenEditUtils"
"http://github.com/chflame163/ComfyUI_LayerStyle"
"http://github.com/rgthree/rgthree-comfy"
"http://github.com/melMass/comfy_mtb"
"http://github.com/TTPlanetPig/Comfyui_TTP_Toolset"
"http://github.com/kijai/ComfyUI-KJNodes"
"http://github.com/1038lab/ComfyUI-RMBG"
)

# 循环克隆插件，已存在则跳过
for repo in "${plugins[@]}"; do
    repo_name=$(basename "${repo}")
    if [ ! -d "${repo_name}" ]; then
        git clone "${repo}"
        echo "已克隆插件：${repo_name}"
    else
        echo "插件${repo_name}已存在，跳过克隆"
    fi
done

# 批量安装所有插件依赖
find . -name "requirements.txt" -exec python3 -m pip install -r {} \;
echo "✅ 所有插件依赖安装完成"

echo -e "\n==================== 🎉 全部部署流程执行完毕 ===================="