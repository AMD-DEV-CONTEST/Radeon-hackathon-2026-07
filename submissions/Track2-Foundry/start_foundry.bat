@echo off
rem Foundry one-click launcher (dev machine).
cd /d %~dp0
echo Starting Foundry... your browser will open when it's ready.
.venv\Scripts\python.exe serve_ui.py --config configs/pilot_4060.toml --open
pause
