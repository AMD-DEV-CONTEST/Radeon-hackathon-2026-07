@echo off
chcp 65001 >nul
title 🦞 Union·由你 — CNC AI 工艺大脑 v11.1.0 Lite
cd /d %~dp0

echo ═══════════════════════════════════════════════════════
echo   🦞 Union·由你 CNC AI 工艺大脑 v11.1.0
echo   一键启动（Lite 离线版）
echo   无需 Ollama · 无需 AI 模型 · 解压即用
echo ═══════════════════════════════════════════════════════
echo.

:: ── 检测 Python ──
echo [1/4] 检测 Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ❌ 未安装 Python！
    echo   请先安装 Python 3.10+（勾选 Add to PATH）
    echo   下载: https://www.python.org/downloads/
    echo.
    echo   安装后重新双击本文件即可。
    pause
    start https://www.python.org/downloads/
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo   ✅ Python %PYVER%

:: ── 安装依赖 ──
echo.
echo [2/4] 安装依赖（首次约 1-2 分钟）...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
if %errorlevel% neq 0 (
    echo   ⚠️ 清华源失败，使用默认源...
    pip install -r requirements.txt --quiet
)
echo   ✅ 依赖就绪

:: ── 探测 Ollama ──
echo.
echo [3/4] 检测 Ollama（增强模式可选）...
ollama --version >nul 2>&1
if %errorlevel% equ 0 (
    echo   ✅ Ollama 已安装
    echo   ℹ️ 如需 AI 专家会议功能，运行: ollama pull qwen2.5:3b
) else (
    echo   ℹ️ 未检测到 Ollama（Lite 模式完全够用）
    echo     画图 + 报价 + 3D 预览 + 打包均无需 Ollama
)

:: ── 启动服务 ──
echo.
echo [4/4] 启动服务...
echo.
echo ═══════════════════════════════════════════════════════
echo   ✅ 服务就绪！
echo   浏览器已自动打开: http://localhost:7862
echo   仪表盘:              http://localhost:7862/api/dashboard
echo   状态检查:            http://localhost:7862/api/health
echo ═══════════════════════════════════════════════════════
echo.
echo   快速上手：
echo   1. 左侧输入: 画一个法兰 外径100内径50厚20
echo   2. 右侧自动显示 3D 模型
echo   3. 输入: 6061法兰 50件 阳极氧化 报价
echo   4. 拖拽 STEP 文件到上传区自动报价
echo.
echo   按 Ctrl+C 停止服务
echo.

start http://localhost:7862
python app/main_lite.py

pause
