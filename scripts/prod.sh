#!/usr/bin/env bash
# =============================================================================
# AMD Radeon Studio - 生产环境启动 (AMD Cloud, Linux + ROCm)
# 用法: 在 AMD Cloud JupyterLab 终端里运行
#   chmod +x scripts/prod.sh
#   ./scripts/prod.sh [ui|api]
# =============================================================================
set -euo pipefail

MODE="${1:-ui}"
echo "[*] 启动 AMD Radeon Studio ($MODE 模式 - ROCm) ..."

# 加载 .env
if [ -f .env ]; then
    set -a; source .env; set +a
    echo "    .env loaded"
fi

# 确保 ROCm PyTorch 已装(用户应该提前装好)
python -c "import torch; assert torch.version.hip is not None, '请先装 ROCm 版 PyTorch'" \
    || { echo "[X] ROCm PyTorch 未装,见 README"; exit 1; }

case "$MODE" in
    api)
        echo "    FastAPI -> 0.0.0.0:8000"
        exec uv run uvicorn src.api.app:app --host 0.0.0.0 --port 8000
        ;;
    ui)
        echo "    Gradio -> 0.0.0.0:7860"
        exec uv run python -m src.ui.app --host 0.0.0.0 --port 7860
        ;;
    *)
        echo "[X] 未知模式: $MODE (可选: ui | api)"; exit 1
        ;;
esac
