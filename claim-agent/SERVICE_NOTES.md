# 服务启动与 Cloudflare 反代笔记

## 环境要求

- Python 3.12+ 虚拟环境（以下假设 `/opt/vllm-env`）
- llama-server 运行在 **127.0.0.1:8080**（ROCm + Qwen3.6-27B）
- cloudflared 已安装

## 关键配置

大模型接口地址在 `config.py` 中由环境变量控制：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `MODEL_HOST` | `localhost` | LLM API 主机名（容器环境必须用 `127.0.0.1`） |
| `MODEL_PORT` | `8000` | LLM API 端口（实际是 `8080`） |
| `MODEL_BASE_URL` | `http://{MODEL_HOST}:{MODEL_PORT}/v1` | 完整 API 地址 |

## 启动服务

```bash
cd /workspace/fake_ocr_test
source /opt/vllm-env/bin/activate

# 理赔后端 :8001
nohup env MODEL_HOST=127.0.0.1 MODEL_PORT=8080 \
  python3 -u -m backend.main > /tmp/backend8001.log 2>&1 &

# 核保后端 :8002
nohup env MODEL_HOST=127.0.0.1 MODEL_PORT=8080 \
  python3 -u -m underwriting.backend > /tmp/backend8002.log 2>&1 &

# Gradio 前端 :7865
nohup env MODEL_HOST=127.0.0.1 MODEL_PORT=8080 \
  python3 -u -c "
import sys; sys.path.insert(0, '.')
import app as a
import threading
threading.Thread(target=a._warmup, daemon=True).start()
a.demo.queue(default_concurrency_limit=4)
a.demo.launch(server_name='0.0.0.0', server_port=7865, share=False)
" > /tmp/fake_ocr.log 2>&1 &
```

> **注意**：容器内 DNS 不通，`localhost` 无法解析，必须用 `127.0.0.1`。
> [Gradio 6] 需打 httpx 补丁，否则 `launch()` 自检会因 DNS 挂掉。

## Cloudflare 隧道（免费反代）

为每个端口开独立隧道：

```bash
# 理赔后端 :8001
nohup cloudflared tunnel --url http://127.0.0.1:8001 \
  --metrics 0.0.0.0:0 > /tmp/cloudflared8001.log 2>&1 &

# 核保后端 :8002
nohup cloudflared tunnel --url http://127.0.0.1:8002 \
  --metrics 0.0.0.0:0 > /tmp/cloudflared8002.log 2>&1 &

# llama-server :8080（调试用）
nohup cloudflared tunnel --url http://127.0.0.1:8080 \
  --metrics 0.0.0.0:0 > /tmp/cloudflared8080.log 2>&1 &
```

查看隧道公网地址：

```bash
grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cloudflared8001.log
grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cloudflared8002.log
```

> 免费隧道域名随机生成，重启后变，无 uptime 保障。

## 常用操作

### 健康检查

```bash
curl http://127.0.0.1:8001/api/health
curl http://127.0.0.1:8002/api/health
```

### 重启服务

```bash
# 杀旧进程
kill $(pgrep -f "backend.main\|underwriting.backend\|app.py\|python3 -u -c" 2>/dev/null)
fuser -k 8001/tcp 8002/tcp 7865/tcp 2>/dev/null

# 重新启动（见上方「启动服务」）
```

### 查看日志

```bash
tail -f /tmp/backend8001.log
tail -f /tmp/backend8002.log
```
