#!/usr/bin/env bash
# =============================================================================
# stop.sh — 停止所有 Intelligent Claim Agent 服务
# =============================================================================
echo "停止服务..."

# 停止 Gradio / 后端 / 大模型
pkill -f "backend.main" 2>/dev/null
pkill -f "underwriting.backend" 2>/dev/null
pkill -f "gradio" 2>/dev/null
pkill -f "llama-server" 2>/dev/null
pkill -f "vllm serve" 2>/dev/null

sleep 2
echo "✅ 已停止。剩余相关进程:"
ps aux | grep -E "llama-server|backend.main|underwriting.backend|vllm serve" | grep -v grep | wc -l
