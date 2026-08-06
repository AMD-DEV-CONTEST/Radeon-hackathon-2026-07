@echo off
title BotverseX Restart
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart-botversex.ps1"
