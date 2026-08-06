# 项目启动说明（一键启动）

> 本说明适用于 **clone 本项目后独立启动**。所有路径均可通过环境变量覆盖，
> 复制命令即可运行，无需修改源码。

---

## 快速开始（一条命令）

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 准备模型（二选一）
#    a) 放到默认目录 /models：
#       - Qwen3.6-27B-UD-Q8_K_XL.gguf   (~34GB)
#       - mmproj-BF16.gguf              (视觉投影器，多模态必装)
#    b) 或放到任意目录，用环境变量指定：
export MODEL_DIR=/your/model/dir

# 3. 一键启动（llama-server + 理赔后端 + 核保后端 + Gradio）
bash start.sh
```

启动完成后：
- **Gradio 界面**: http://127.0.0.1:7865
- **理赔 API**: http://127.0.0.1:8001/docs
- **核保 API**: http://127.0.0.1:8002/docs
- **停止**: `bash stop.sh`

---

## 分步启动（手动控制）

### 1. 启动大模型（llama-server）

```bash
MODEL_DIR="${MODEL_DIR:-/models}"
/opt/llama.cpp/llama-server \
  -m "$MODEL_DIR/Qwen3.6-27B-UD-Q8_K_XL.gguf" \
  --mmproj "$MODEL_DIR/mmproj-BF16.gguf" \
  -ngl 99 \
  -c 163840 \
  -ctk q4_0 -ctv q4_0 \
  -fa on \
  --spec-type draft-mtp \
  -np 1 \
  --host 0.0.0.0 --port 8080
```

验证：`curl http://127.0.0.1:8080/health` → `{"status":"ok"}`（加载需 15-30 秒，期间 503）

### 2. 启动 Python 后端

```bash
cd claim-agent            # 或仓库根目录
export MODEL_HOST=127.0.0.1 MODEL_PORT=8080

# 理赔后端 :8001
nohup python3 -u -m backend.main > /tmp/backend-claim.log 2>&1 &

# 核保后端 :8002
nohup python3 -u -m underwriting.backend > /tmp/backend-uw.log 2>&1 &

# Gradio :7865
nohup python3 -u -c "
import sys; sys.path.insert(0, '.')
import app as a
import threading
threading.Thread(target=a._warmup, daemon=True).start()
a.demo.queue(default_concurrency_limit=4)
a.demo.launch(server_name='0.0.0.0', server_port=7865, share=False)
" > /tmp/gradio.log 2>&1 &
```

健康检查：
```bash
curl http://127.0.0.1:8001/api/health   # 理赔
curl http://127.0.0.1:8002/api/health   # 核保
curl -s http://127.0.0.1:7865/ | head  # Gradio
```

---

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `MODEL_DIR` | `/models` | 模型目录（自动探测 `/models` → `/workspace/models`）|
| `MODEL_HOST` | `localhost` | 大模型 API 主机（容器内必须 `127.0.0.1`）|
| `MODEL_PORT` | `8000` | 大模型 API 端口（实际 `8080`）|
| `LLAMA_SERVER` | `/opt/llama.cpp/llama-server` | llama-server 可执行路径 |
| `PORT_LLM` | `8080` | 大模型端口 |
| `PORT_CLAIM` | `8001` | 理赔后端 |
| `PORT_UW` | `8002` | 核保后端 |
| `PORT_WEB` | `7865` | Gradio |

---

## 依赖

```bash
pip install -r requirements.txt
# 含: gradio, langchain, chromadb, sentence-transformers, rank-bm25, jieba, pyjwt, PyMuPDF
```

**运行环境**：AMD Radeon GPU + ROCm 7.2+（W7900/gfx1100 实测）；无 AMD GPU 时可退化为 CPU（速度慢）。

---

## 常见问题

| 问题 | 解决 |
|------|------|
| `localhost` 解析失败 | 容器内 DNS 问题，用 `127.0.0.1:8080` |
| 大模型 503 | 加载中（15-30s），或显存不足降 `-c` |
| 图片报错 | 必须配 `--mmproj`（视觉投影器）|
| 256K 上下文 OOM | 改 `-c 131072` 或保持 Q4 KV |

---

## 架构

```
浏览器 ──► :7865 Gradio ──┐
                          ├──► :8080 llama-server (Qwen3.6-27B, AMD ROCm)
浏览器 ──► :8001 理赔后端 ─┘
浏览器 ──► :8002 核保后端 ─┘
```
