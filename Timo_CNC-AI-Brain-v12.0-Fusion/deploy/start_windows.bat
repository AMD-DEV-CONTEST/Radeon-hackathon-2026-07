@echo off
REM 🦞 Union·由你 CNC AI 工艺大脑 — Windows 启动脚本
REM 前置条件: 安装 Ollama (https://ollama.com) 并拉取 qwen2.5:3b
REM 使用: 双击运行此文件 或 命令行: union_cnc_brain.exe

echo.
echo ============================================================
echo  🦞 Union·由你 — CNC AI 工艺大脑 v11.0
echo ============================================================
echo.

REM 检查 Ollama 是否运行
curl -s http://localhost:11434/api/tags >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Ollama 未运行，正在启动...
    start "" "C:\Program Files\Ollama\ollama.exe" serve
    echo 等待 Ollama 启动 (10秒)...
    timeout /t 10 /nobreak >nul
)

REM 检查模型
echo 检查模型...
curl -s http://localhost:11434/api/tags | findstr "qwen2.5:3b" >nul
if %errorlevel% neq 0 (
    echo [INFO] 正在拉取 qwen2.5:3b 模型 (首次约需2分钟)...
    ollama pull qwen2.5:3b
)

echo.
echo 启动 CNC AI 工艺大脑...
echo 浏览器打开: http://localhost:7861
echo 按 Ctrl+C 停止
echo.

union_cnc_brain.exe
