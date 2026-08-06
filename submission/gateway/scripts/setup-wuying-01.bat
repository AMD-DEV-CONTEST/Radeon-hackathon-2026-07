@echo off
echo === UnionAgents Reasonix Agent Setup for wuying-01 ===

REM 1. Clone repo
if not exist "D:\UnionAgents" (
    git clone https://github.com/Porphyrioon/union_agents.git D:\UnionAgents
) else (
    echo Repo already exists, pulling latest...
    git -C D:\UnionAgents pull origin master
)

REM 2. Install + build agent
cd /d D:\UnionAgents\packages\agent
call npm install
call npm run build

echo.
echo === Build complete ===
echo.
echo To start the agent, run:
echo   set DEEPSEEK_API_KEY=YOUR_KEY
echo   node D:\UnionAgents\packages\agent\dist\cli.js run --orchestrator-url http://111.228.42.18:8000 --agent-name reasonix-wuying-01 --workspace-root D:\ua-workspaces --max-concurrency 3 --model deepseek-v4-pro
echo.
pause
