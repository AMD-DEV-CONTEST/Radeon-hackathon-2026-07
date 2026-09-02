#!/bin/bash
cd "$(dirname "$0")"
export XAI_PORT=8000 XAI_HOST=localhost
echo "▶ 启动 XAI 后端 (:8000) ..."
( /Users/Admin/.workbuddy/binaries/python/versions/3.13.12/bin/python3 server_xai.py > server.log 2>&1 ) &
echo "▶ 启动 XAI 前端 (:5180) ..."
( cd xai-frontend && /Users/Admin/.workbuddy/binaries/node/versions/22.22.2/bin/npm run dev -- --port 5180 --host ) &
sleep 4
open http://localhost:5180/ 2>/dev/null || echo "请浏览器打开 http://localhost:5180/"
wait
