@echo off
chcp 65001 >nul
title OPC工业AI能力中台 - CNC AI Brain v11.1.0
cd /d %~dp0

:: 使用项目独立虚拟环境（避免污染系统Python，解决OCP/cadquery依赖冲突）
set "VENV=%~dp0.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "PIP=%VENV%\Scripts\pip.exe"

echo =======================================================
echo   OPC工业AI能力中台 - CNC AI Brain v11.1.0
echo   启动完整版（支持云端AI + 本地模型）
echo =======================================================
echo.

:: ── 检测/创建虚拟环境 ──
echo [1/4] 检测 Python 虚拟环境...
if not exist "%VENV%\Scripts\python.exe" (
    echo   [WARN] 虚拟环境不存在，正在创建...
    python -m venv "%VENV%"
    if %errorlevel% neq 0 (
        echo   [ERROR] 创建虚拟环境失败！请先安装 Python 3.10+（勾选 Add to PATH）
        pause
        exit /b 1
    )
)
for /f "tokens=2" %%i in ('"%PYTHON%" --version 2^>^&1') do set PYVER=%%i
echo   [OK] Python %PYVER% (venv)

:: ── 检查依赖 ──
echo.
echo [2/4] 检查依赖...
"%PIP%" show fastapi >nul 2>&1
if %errorlevel% neq 0 (
    echo   [WARN] 依赖未安装，正在安装...
    "%PIP%" install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
)
echo   [OK] 核心依赖就绪

:: ── 检查OCC/OCP ──
echo.
echo [3/4] 检查 OCC/OCP 精确几何引擎...
"%PYTHON%" -c "import OCP; print('OCP', OCP.__version__)" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [WARN] OCC/OCP 未安装，正在安装 cadquery-ocp...
    "%PIP%" install cadquery-ocp -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
    if %errorlevel% neq 0 (
        echo   [WARN] OCC安装失败，将降级使用trimesh网格引擎
    ) else (
        echo   [OK] OCC/OCP 安装成功
    )
) else (
    echo   [OK] OCC/OCP 已就绪
)

:: ── 启动 MTClaw Function Router (上游LLM Provider, :7863) ──
echo.
echo [4/5] 启动 MTClaw Function Router (CNC垂类加速路由)...
set "FR_DIR=%~dp0..\MTClaw-main"
set "FR_CONFIG=%USERPROFILE%\.function-router\config.json"
if not exist "%FR_CONFIG%" (
    echo   [WARN] FR 配置不存在: %FR_CONFIG%
    echo   [WARN] 跳过FR, cnc-ai-brain 将直连上游模型
) else (
    start "MTClaw FR :7863" /min cmd /c "pushd ""%FR_DIR%"" && ""%PYTHON%"" -m function_router.server --config ""%FR_CONFIG%"" && popd"
    echo   [OK] MTClaw Function Router 启动中... http://127.0.0.1:7863/v1/models
    echo   [OK] CNC 工具: cnc_conflict_check + cnc_quote_calc
)

:: ── 启动服务 ──
echo.
echo [5/5] 启动 cnc-ai-brain 主服务...
echo.
echo =======================================================
echo   [OK] 服务启动中...
echo   浏览器将自动打开: http://localhost:7862
echo   仪表盘:              http://localhost:7862/api/dashboard
echo   状态检查:            http://localhost:7862/api/health
echo   MTClaw FR:           http://127.0.0.1:7863/v1/models (加速路由)
echo =======================================================
echo.
echo   按 Ctrl+C 停止服务
echo.

start http://localhost:7862
"%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 7862 --reload

pause
