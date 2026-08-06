@echo off
chcp 65001 >nul
title 停止 Motus Agent

echo 正在停止 Motus Agent 服务...

rem 查找占用8000端口的进程
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do (
    taskkill /PID %%a /F >nul 2>nul
)

echo 服务已停止
timeout /t 2 >nul