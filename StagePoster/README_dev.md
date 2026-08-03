# Poster Engine

AI Multimodal Poster Generation System.

## define
用户提交活动信息和 Logo，系统自动规划三种设计方向，生成、检查、失败重试。用户只挑方案，不写提示词。挑中后不再重新抽图，直接排版生成最终海报。

## Architecture

User
 |
Poster API
 |
LLM Planner
 |
ComfyUI Runtime
 |
Z-Image Turbo
 |
Generated Poster


## Components

- LLM planning
- Image generation
- Workflow orchestration
- Review loop
- Asset management

## Current Status

- AMD W7900 ROCm inference ready
- Z-Image Turbo deployed
- ComfyUI workflow ready


## MVP-0: Poster Generation Pipeline

Goal:
输入:
- artist
- event info
- logo
- style

输出:
- generated poster

Pipeline:
API
 ↓
Prompt Builder
 ↓
ComfyUI
 ↓
Image Generation
 ↓
Result Storage


# backend run command (dev)
```bash
export VLM_URL=http://127.0.0.1:8001
export VLM_API_KEY=stageposter-vlm-local
export VLM_MODEL=stageposter-vlm
export VLM_REQUEST_TIMEOUT=5m
export VLM_AUTO_SLEEP=true

export COMFY_URL=http://127.0.0.1:8188

mkdir -p logs

pkill -f '/workspace/poster-engine/backend/poster-backend' \
  2>/dev/null || true

nohup ./poster-backend \
  > logs/backend.log 2>&1 &

echo $! > backend.pid

sleep 2

tail -80 logs/backend.log

```

```bash
if [ -f /workspace/poster-engine/backend.pid ]; then
  kill "$(cat /workspace/poster-engine/backend.pid)" 2>/dev/null || true
fi

pkill -f '/workspace/poster-engine/backend/poster-backend' 2>/dev/null || true

cd /workspace/poster-engine/backend

nohup env \
  LISTEN_ADDR=:8080 \
  COMFY_URL=http://127.0.0.1:8188 \
  WORKFLOW_PATH=/workspace/poster-engine/workflows/z_image_poster_v1.json \
  PROMPT_NODE_ID='57:27' \
  SEED_NODE_ID='57:3' \
  DB_PATH=/workspace/poster-engine/backend/data/poster.db \
  STORAGE_ROOT=/workspace/poster-engine/backend/storage/jobs \
  WORKFLOW_KEY=poster-text \
  WORKFLOW_VERSION=1.0.0 \
  RECONCILE_INTERVAL=2s \
  POSTER_API_TOKEN='poster-dev-2026' \
  CORS_ORIGIN='*' \
  ./poster-backend \
  > /workspace/poster-engine/logs/backend.log 2>&1 &

echo $! > /workspace/poster-engine/backend.pid

sleep 2
cat /workspace/poster-engine/logs/backend.log

```

```bash
用户原始需求
       ↓
Poster Goal Spec
       ↓
Creative Brief Agent
       ↓
Prompt Planner
       ↓
生成多组 Key Visual
       ↓
多模板 Composer 合成
       ↓
程序化质量检查
       ↓
AI Vision Critic 视觉评审
       ↓
Decision Router
   ┌──────┼──────────┐
   ↓      ↓          ↓
通过   重新排版    重新生成主视觉
   │      │          │
   └──────┴──── Loop ┘
       ↓
保留最佳结果
       ↓
用户最终选择
```

## llm model qwen/qwen-9b

## install vllm rocm

```
uv pip install \
  --upgrade \
  vllm \
  --extra-index-url https://wheels.vllm.ai/rocm/
```


```bash
cd /workspace/poster-engine

source .venv-vlm/bin/activate

python -m pip install -U uv

PYTHON_BIN="$(
  command -v python3.12 ||
  command -v python3
)"

uv venv .venv-vllm \
  --python "$PYTHON_BIN"

deactivate

source .venv-vllm/bin/activate

```

## 启动告诉多模态服务
```bash
cd /workspace/poster-engine

mkdir -p logs/vllm

pkill -f 'vllm serve.*Qwen3.5-9B' 2>/dev/null || true

nohup env \
  VLLM_SERVER_DEV_MODE=1 \
  VLLM_ROCM_SLEEP_MEM_CHUNK_SIZE=128 \
  /workspace/poster-engine/.venv-vllm/bin/vllm serve \
  /workspace/poster-engine/models/Qwen3.5-9B \
  --host 127.0.0.1 \
  --port 8001 \
  --served-model-name stageposter-vlm \
  --api-key stageposter-vlm-local \
  --dtype float16 \
  --max-model-len 4096 \
  --max-num-seqs 1 \
  --max-num-batched-tokens 4096 \
  --gpu-memory-utilization 0.90 \
  --limit-mm-per-prompt '{"image":{"count":1,"width":768,"height":1152},"video":0}' \
  --enforce-eager \
  --enable-sleep-mode \
  --default-chat-template-kwargs '{"enable_thinking":false}' \
  --generation-config vllm \
  > logs/vllm/server.log 2>&1 &

echo $! > vlm.pid

echo "vLLM PID: $(cat vlm.pid)"
```

check run log 
```
tail -f /workspace/poster-engine/logs/vllm/server.log
```

moiot oom
```bash
watch -n 1 \
  rocm-smi \
  --showmeminfo vram \
  --showuse
```
## setup scripts
重新安装 apt 系统工具
重新创建 /usr/local/bin/go 等链接
重新写入 shell 环境
检查 Python runtime
检查 venv
检查模型 SHA256
复用全部 /workspace 内容
跳过已完成的大文件下载
```bash
chmod +x /workspace/poster-engine/scripts/bootstrap-server.sh

本次只想恢复系统，不下载模型

DOWNLOAD_MODELS=0 \
/workspace/poster-engine/scripts/bootstrap-server.sh
不想下载 LoRA：
DOWNLOAD_LORA=0 \
/workspace/poster-engine/scripts/bootstrap-server.sh
跳过 apt：
SKIP_APT=1 \
/workspace/poster-engine/scripts/bootstrap-server.sh
```


## dev public url

```bash
cd /workspace/poster-engine

mkdir -p logs run

nohup cloudflared tunnel \
  --no-autoupdate \
  --url http://127.0.0.1:8080 \
  > logs/cloudflared.log 2>&1 &

echo $! > run/cloudflared.pid

```
