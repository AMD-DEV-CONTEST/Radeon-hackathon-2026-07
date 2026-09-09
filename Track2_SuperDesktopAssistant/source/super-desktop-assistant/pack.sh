#!/bin/bash
# ============================================================
#  打包脚本 - 生成可直接部署的 tar.gz
#  用法: chmod +x pack.sh && ./pack.sh
#  输出: super-assistant-ubuntu24.tar.gz
# ============================================================
set -e

PKG_NAME="super-assistant-ubuntu24"
OUTPUT="${PKG_NAME}.tar.gz"

# 需要打包的文件和目录
INCLUDE=(
    "app.py"
    "requirements.txt"
    "config.json"
    ".env.example"
    "README.md"
    "LICENSE"
    "Dockerfile"
    "docker-compose.yml"
    "deploy-ubuntu24.sh"
    "deploy.sh"
    "src/"
    "data/"
)

# 排除的文件
EXCLUDE=(
    "__pycache__"
    "*.pyc"
    ".env"
    ".venv"
    "outputs/test_chain.png"
    ".git"
    ".gitignore"
    "*.zip"
    "*.tar.gz"
    "*_output.txt"
    "*_trace.txt"
    "_s.txt"
    "_s2.txt"
    "_s3.txt"
    "_summary.txt"
    "_img_trace.txt"
    "_pdf_test.txt"
    "_comfyui_prompts.txt"
    "image_prompts.json"
)

echo "=== 打包 Super Desktop Assistant ==="

# 构建排除参数
EXCL_ARGS=""
for e in "${EXCLUDE[@]}"; do
    EXCL_ARGS="$EXCL_ARGS --exclude=$e"
done

# 打包
tar czf "$OUTPUT" $EXCL_ARGS "${INCLUDE[@]}"

SIZE=$(du -h "$OUTPUT" | cut -f1)
echo "✅ 打包完成: $OUTPUT ($SIZE)"
echo ""
echo "部署方式（在 Ubuntu 24 上）:"
echo "  scp $OUTPUT user@host:~"
echo "  tar xzf $OUTPUT && cd super-desktop-assistant"
echo "  chmod +x deploy-ubuntu24.sh && ./deploy-ubuntu24.sh"
