# =============================================================================
# AMD Radeon Studio - 本地环境初始化 (Windows + NVIDIA CUDA)
# 用法: powershell -ExecutionPolicy Bypass -File scripts/setup_env.ps1
# =============================================================================
$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " AMD Radeon Studio - 环境初始化" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. 检查 uv
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Host "[X] uv 未安装" -ForegroundColor Red
    Write-Host "    安装: irm https://astral.sh/uv/install.ps1 | iex" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] uv 已装: $(uv --version)" -ForegroundColor Green

# 2. 装 Python 3.11
Write-Host ""; Write-Host "[1/4] 装 Python 3.11 ..." -ForegroundColor Yellow
uv python install 3.11

# 3. 同步依赖(锁文件 uv.lock)
Write-Host ""; Write-Host "[2/4] 同步依赖 (uv sync) ..." -ForegroundColor Yellow
uv sync --extra dev

# 4. 装 PyTorch (Windows 默认 CUDA;AMD ROCm 用户请去 AMD Cloud)
Write-Host ""; Write-Host "[3/4] 装 PyTorch (CUDA 12.1) ..." -ForegroundColor Yellow
uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# 5. 跑测试
Write-Host ""; Write-Host "[4/4] 跑单元测试 ..." -ForegroundColor Yellow
uv run pytest

Write-Host ""; Write-Host "========================================" -ForegroundColor Green
Write-Host " [OK] 环境初始化完成" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "下一步:" -ForegroundColor Cyan
Write-Host "  uv run pytest                 # 跑全部测试"
Write-Host "  uv run jupyter lab            # 启动 notebook"
Write-Host "  .\scripts\dev.ps1 ui          # 启动 Gradio UI"
Write-Host "  .\scripts\dev.ps1 api         # 启动 FastAPI"
