#!/usr/bin/env bash
# One-shot remote kickoff: clean slate then detached overnight pipeline.
# Designed to be triggered by a fire-and-forget SSH call over a flaky link.
pkill -f 'overnight_pipelin[e]' 2>/dev/null
pkill -f 'vllm serv[e]' 2>/dev/null
sleep 4
cd /root/rocm-autopilot || exit 1
rm -f /workspace/pipeline.log /workspace/vllm_state.json
setsid nohup bash scripts/overnight_pipeline.sh > /workspace/pipeline.log 2>&1 < /dev/null &
echo "kickoff done, pipeline pid: $!" > /workspace/kickoff.log
