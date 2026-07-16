# =============================================================================
# AMD Radeon Studio - 本地开发启动 (Windows)
# 用法: powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 [ui|api]
# =============================================================================
param(
    [ValidateSet("ui", "api")]
    [string]$Mode = "ui"
)

$ErrorActionPreference = "Stop"
Write-Host "[*] 启动 AMD Radeon Studio ($Mode 模式) ..." -ForegroundColor Cyan

# 加载 .env (如果存在)
if (Test-Path ".env") {
    Write-Host "    加载 .env ..." -ForegroundColor Gray
    Get-Content ".env" | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
            [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
}

switch ($Mode) {
    "api" {
        Write-Host "    FastAPI -> http://localhost:8000" -ForegroundColor Yellow
        uv run uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000
    }
    "ui" {
        Write-Host "    Gradio -> http://localhost:7860" -ForegroundColor Yellow
        uv run python -m src.ui.app
    }
}
