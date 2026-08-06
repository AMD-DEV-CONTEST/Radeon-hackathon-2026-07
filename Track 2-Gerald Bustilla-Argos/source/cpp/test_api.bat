@echo off
curl -s -X POST https://developer.amd.com.cn/radeon/api/v1/chat/completions -H "Authorization: Bearer rc-c042ad0acc56669f7b46e70f924189b5ac51664ce329f5b2" -H "Content-Type: application/json" -d "{\"model\":\"Qwen3.6-35B-A3B\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello, say hi in one sentence.\"}]}"
echo.
