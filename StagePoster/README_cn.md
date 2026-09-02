# StagePoster

> AI 原生音乐活动海报引擎，已在 AMD Radeon PRO W7900 48 GB + ROCm 环境完成部署与端到端验证。

StagePoster 的目标不是返回一张“裸生成图”，而是把结构化活动需求转化为可选择、可审查、可下载的完整活动海报。

```text
结构化活动 Brief
        ↓
Qwen3.5-9B 艺术指导 Agent
        ↓
3 个结构化设计方案
        ↓
ComfyUI + Z-Image 生成 3 张候选图
        ↓
用户选择候选图
        ↓
Go 确定性文字 / Logo / 信息排版
        ↓
Qwen Vision 视觉审查与有限轮自动优化
        ↓
最终海报 + 缩略图 + 审查证据
```

---

## 1. 当前验证状态

| 组件 | 状态 | 本地地址 |
|---|---:|---|
| ComfyUI | Ready | `http://127.0.0.1:8188` |
| Qwen3.5-9B / vLLM | Ready | `http://127.0.0.1:8001` |
| StagePoster Go Backend | Ready | `http://127.0.0.1:8080` |
| SQLite | Ready | `/workspace/poster-engine/backend/data/poster.db` |
| Cloudflare Quick Tunnel | 开发联调 | `https://<random>.trycloudflare.com` |
| 完整海报闭环 | Passed | 3 candidates → select → compose → review → final |
| 冒烟测试 | Passed | scripts/smoke-test.sh 全部通过 |

已验证的一次完整 E2E（2026-07-29 冒烟测试）：

| 字段 | 验证结果 |
|---|---|
| Session | `session_71a2f36d-bd35-4a92-8fe7-92de20aed972` |
| 设计方案 | `abyssal-red-dimension` (深渊红维度的王座) |
| Poster | `poster_5b5c743a-1314-42f9-a186-85053b50d446` |
| 候选图 | 3 / 3 ready |
| 已选 Candidate | `candidate_cb3c5483-cf02-485a-8b62-9f065ea1203b` |
| Poster 状态 | `completed_with_warnings` |
| Finalize 状态 | `completed_with_warnings` |
| 审查轮数 | 2 |
| 最佳评分 | 88 |
| 最终文件 | 约 1.0 MB PNG (1024×1536) |

`completed_with_warnings` 是合法终态，表示自动审查达到最大轮数后，系统保留了评分最高且可用的版本，并不表示海报文件生成失败。

---

## 2. 系统架构

```mermaid
flowchart LR
    FE[Frontend] -->|HTTPS| CF[Cloudflare Quick Tunnel]
    CF --> API[StagePoster Go API :8080]

    API --> DB[(SQLite)]
    API --> FS[Local Asset and Poster Storage]
    API --> VLM[vLLM :8001<br/>Qwen3.5-9B]
    API --> COMFY[ComfyUI :8188<br/>Z-Image Workflow]

    VLM --> GPU[AMD Radeon PRO W7900 48 GB]
    COMFY --> GPU

    API --> LOOP[Deterministic Composition<br/>and Review Loop]
    LOOP --> FS
```

### 公私边界

只向前端公开 Go Backend：

```text
公开：
Cloudflare HTTPS URL
        ↓
StagePoster Go API :8080

私有：
ComfyUI :8188
vLLM :8001
SQLite
模型文件
Workflow JSON
ComfyUI Node IDs
```

浏览器不直接调用 ComfyUI 或 vLLM。这样可以隐藏模型路径、工作流节点、队列协议和 GPU 调度细节。

---

## 3. 一键部署

**新环境首次部署**（从零开始安装所有依赖）：

```bash
cd /workspace/poster-engine
sudo -E bash scripts/install-all.sh
```

脚本会自动完成：
1. ✅ 检查/安装 ROCm 驱动
2. ✅ 安装系统工具（build-essential、git、jq、sqlite3 等）
3. ✅ 安装 uv 包管理器
4. ✅ 安装 Go 1.25.0
5. ✅ 安装 cloudflared
6. ✅ 克隆 ComfyUI（如不存在）
7. ✅ 创建 ComfyUI Python 3.10.20 环境 + ROCm Torch 2.13.0
8. ✅ 创建 vLLM Python 3.12 环境 + ROCm vLLM 0.20.0
9. ✅ 下载 Qwen3.5-9B + Z-Image Turbo 模型（带 SHA256 校验，约 21 GB）
10. ✅ 编译 Go Backend
11. ✅ 生成 `.env` 配置文件
12. ✅ 启动 ComfyUI、vLLM、Backend 三项服务
13. ✅ 执行健康检查

**详细文档**：见 [docs/one-click-deployment.md](docs/one-click-deployment.md)

**环境变量**：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SKIP_APT=1` | `0` | 跳过 apt 安装 |
| `SKIP_COMFY_TORCH=1` | `0` | 跳过 ComfyUI Torch 安装 |
| `DOWNLOAD_MODELS=0` | `1` | 跳过模型下载 |
| `INSTALL_ROCM=1` | `0` | 安装 ROCm 驱动（通常不需要） |

**服务管理**：

```bash
./scripts/start-all.sh      # 启动所有服务
./scripts/stop-all.sh       # 停止所有服务
./scripts/status.sh         # 查看服务状态
./scripts/smoke-test.sh     # 冒烟测试
./scripts/start-dev-tunnel.sh  # 启动开发隧道
```

---

## 3. W7900 已验证运行环境

| 项目 | 配置 |
|---|---|
| OS | Ubuntu 24.04.4 |
| GPU | AMD Radeon PRO W7900 |
| VRAM | 48 GB |
| GPU 架构 | `gfx1100` |
| ROCm Core | `7.2.1.70201-81~24.04` |
| HIP | `7.2.53211` |
| ComfyUI Python | Python 3.10.20 |
| ComfyUI Torch | `2.13.0+rocm7.2` |
| vLLM | `0.20.0` |
| vLLM Torch | `2.10.0+git8514f05` |
| vLLM Platform | ROCm |
| Go | 1.25.0 |
| Backend | `127.0.0.1:8080` |
| vLLM | `127.0.0.1:8001` |
| ComfyUI | `127.0.0.1:8188` |

### 单卡共享策略

Qwen3.5-9B 和 ComfyUI 共享同一张 W7900：

1. Brief 理解、设计方案生成、视觉审查时唤醒 vLLM。
2. 进入候选图生成前，让 vLLM 进入 sleep mode 释放显存。
3. ComfyUI 加载图像生成模型并生成候选图。
4. 需要 Qwen 审查时重新唤醒 vLLM。

这套调度避免两套大模型长期同时占据显存。

---

## 4. 目录结构

```text
/workspace/poster-engine/
├── ComfyUI/
├── models/
│   └── Qwen3.5-9B/
├── workflows/
│   └── z_image_poster_v1.json
├── venv/                         # ComfyUI Python 环境
├── .venv-vllm/                   # vLLM Python 环境
└── backend/
    ├── cmd/server/
    ├── data/
    │   └── poster.db
    ├── logs/
    │   ├── comfyui.log
    │   ├── vllm.log
    │   ├── backend.log
    │   └── cloudflared.log
    ├── run/
    │   ├── comfyui.pid
    │   ├── vllm.pid
    │   ├── backend.pid
    │   ├── cloudflared.pid
    │   └── public-api-url.txt
    ├── storage/
    │   ├── jobs/
    │   ├── assets/
    │   └── posters/
    ├── scripts/
    └── poster-backend
```

---

## 5. 模型与工作流

### Qwen3.5-9B

```text
/workspace/poster-engine/models/Qwen3.5-9B
```

vLLM 对外服务名：

```text
stageposter-vlm
```

### ComfyUI 模型

```text
/workspace/poster-engine/ComfyUI/models/
├── diffusion_models/
│   └── z_image_turbo_bf16.safetensors
├── text_encoders/
│   └── qwen_3_4b.safetensors
├── vae/
│   └── ae.safetensors
└── loras/
    └── z_image_turbo_distill_patch_lora_bf16.safetensors
```

检查：

```bash
find /workspace/poster-engine/ComfyUI/models \
  -type f \
  -name '*.safetensors' \
  -printf '%s\t%p\n' \
  | sort -n
```

### Workflow

```text
/workspace/poster-engine/workflows/z_image_poster_v1.json
```

Runtime identity：

```text
poster-text@1.0.0
```

Node bindings：

| 绑定 | Node ID |
|---|---|
| Positive Prompt | `57:27` |
| Negative Prompt | 未绑定 |
| Seed | `57:3` |

---

## 6. 首次环境检查

```bash
rocm-smi --showproductname
rocminfo | grep -m1 -E 'Name:.*gfx'
hipcc --version

/workspace/venv/bin/python --version
/workspace/poster-engine/.venv-vllm/bin/python --version

go version
```

验证 vLLM ROCm 环境：

```bash
/workspace/poster-engine/.venv-vllm/bin/python - <<'PY'
import torch
import vllm

print("vLLM:", vllm.__version__)
print("Torch:", torch.__version__)
print("HIP:", torch.version.hip)
print("GPU available:", torch.cuda.is_available())

if torch.cuda.is_available():
    print("Device:", torch.cuda.get_device_name(0))
PY
```

期望关键结果：

```text
vLLM: 0.20.0
HIP: 7.2.53211
GPU available: True
Device: AMD Radeon Graphics
```

---

# 7. 日常启动命令

## 7.1 推荐脚本入口

恢复脚本约定的日常入口：

```bash
cd /workspace/poster-engine/backend

./scripts/start-all.sh
./scripts/status.sh
./scripts/smoke-test.sh
./scripts/start-dev-tunnel.sh
```

获取当前前端开发地址：

```bash
cat /workspace/poster-engine/backend/run/public-api-url.txt
```

下面给出每个服务的手动启动方式，便于调试和复现。

---

## 7.2 启动 ComfyUI

```bash
cd /workspace/poster-engine/ComfyUI

mkdir -p \
  /workspace/poster-engine/backend/logs \
  /workspace/poster-engine/backend/run

if [[ -f /workspace/poster-engine/backend/run/comfyui.pid ]]; then
  kill "$(cat /workspace/poster-engine/backend/run/comfyui.pid)" \
    2>/dev/null || true
fi

pkill -f \
  '/workspace/poster-engine/ComfyUI/main.py.*8188' \
  2>/dev/null || true

rm -f /workspace/poster-engine/backend/run/comfyui.pid
: > /workspace/poster-engine/backend/logs/comfyui.log

nohup /workspace/venv/bin/python main.py \
  --listen 127.0.0.1 \
  --port 8188 \
  --disable-auto-launch \
  > /workspace/poster-engine/backend/logs/comfyui.log \
  2>&1 &

echo "$!" \
  > /workspace/poster-engine/backend/run/comfyui.pid

echo "ComfyUI PID: $!"
```

验证：

```bash
curl -fsS \
  http://127.0.0.1:8188/system_stats \
  | python3 -m json.tool
```

---

## 7.3 启动 Qwen3.5-9B / vLLM

```bash
cd /workspace/poster-engine

mkdir -p backend/logs backend/run

if [[ -f backend/run/vllm.pid ]]; then
  kill "$(cat backend/run/vllm.pid)" \
    2>/dev/null || true
fi

pkill -f \
  '/workspace/poster-engine/.venv-vllm/bin/vllm serve' \
  2>/dev/null || true

rm -f backend/run/vllm.pid
: > backend/logs/vllm.log

export VLLM_SERVER_DEV_MODE=1
export VLLM_ROCM_SLEEP_MEM_CHUNK_SIZE=256
export PYTHONUNBUFFERED=1

nohup /workspace/poster-engine/.venv-vllm/bin/vllm serve \
  /workspace/poster-engine/models/Qwen3.5-9B \
  --host 127.0.0.1 \
  --port 8001 \
  --served-model-name stageposter-vlm \
  --api-key stageposter-vlm-local \
  --dtype float16 \
  --max-model-len 4096 \
  --max-num-seqs 1 \
  --max-num-batched-tokens 4096 \
  --gpu-memory-utilization 0.65 \
  --limit-mm-per-prompt \
    '{"image":{"count":1,"width":768,"height":1152},"video":0}' \
  --enforce-eager \
  --enable-sleep-mode \
  --default-chat-template-kwargs \
    '{"enable_thinking":false}' \
  --generation-config vllm \
  > backend/logs/vllm.log \
  2>&1 &

echo "$!" > backend/run/vllm.pid

echo "vLLM PID: $!"
```

核心配置：

| 设置 | 值 | 说明 |
|---|---:|---|
| dtype | FP16 | ROCm 推理 |
| max model length | 4096 | MVP 上下文上限 |
| max sequences | 1 | 单卡稳定并发 |
| max batched tokens | 4096 | 与上下文上限一致 |
| GPU memory utilization | 0.65 | 配置预算约 31.2 GiB |
| eager mode | 开启 | 更稳定的 ROCm 执行路径 |
| sleep mode | 开启 | 为 ComfyUI 释放显存 |
| thinking | 关闭 | 减少结构化 JSON 冗余 |
| image limit | 1 × 768×1152 | 单次视觉审查上限 |

验证：

```bash
curl -fsS \
  http://127.0.0.1:8001/v1/models \
  -H 'Authorization: Bearer stageposter-vlm-local' \
  | python3 -m json.tool
```

检查 sleep state：

```bash
curl -fsS \
  http://127.0.0.1:8001/is_sleeping \
  -H 'Authorization: Bearer stageposter-vlm-local'

echo
```

### 重建 vLLM 环境

已验证的 ROCm wheel 安装方式：

```bash
uv pip install "vllm==0.20.0" \
  --index-url \
    https://pypi.tuna.tsinghua.edu.cn/simple \
  --extra-index-url \
    https://wheels.vllm.ai/rocm/0.20.0/rocm721
```

不要只替换 PyTorch 后就假定 vLLM 环境可用。安装后必须重新验证 vLLM、Torch、HIP 和 GPU availability。

---

## 7.4 编译并启动 Go Backend

编译：

```bash
cd /workspace/poster-engine/backend

mkdir -p \
  logs \
  run \
  data \
  storage/jobs \
  storage/assets \
  storage/posters

export GOPROXY=https://goproxy.cn,direct
export GOSUMDB=sum.golang.google.cn

go mod download
go test ./...
go build -o poster-backend ./cmd/server

ls -lh poster-backend
```

启动：

```bash
cd /workspace/poster-engine/backend

if [[ -f run/backend.pid ]]; then
  kill "$(cat run/backend.pid)" \
    2>/dev/null || true
fi

pkill -f \
  '/workspace/poster-engine/backend/poster-backend' \
  2>/dev/null || true

rm -f run/backend.pid
: > logs/backend.log

nohup env \
  LISTEN_ADDR='127.0.0.1:8080' \
  COMFY_URL='http://127.0.0.1:8188' \
  WORKFLOW_PATH='/workspace/poster-engine/workflows/z_image_poster_v1.json' \
  WORKFLOW_KEY='poster-text' \
  WORKFLOW_VERSION='1.0.0' \
  PROMPT_NODE_ID='57:27' \
  NEGATIVE_PROMPT_NODE_ID='' \
  SEED_NODE_ID='57:3' \
  DB_PATH='/workspace/poster-engine/backend/data/poster.db' \
  STORAGE_ROOT='/workspace/poster-engine/backend/storage/jobs' \
  ASSET_STORAGE_ROOT='/workspace/poster-engine/backend/storage/assets' \
  POSTER_OUTPUT_ROOT='/workspace/poster-engine/backend/storage/posters' \
  VLM_URL='http://127.0.0.1:8001' \
  VLM_API_KEY='stageposter-vlm-local' \
  VLM_MODEL='stageposter-vlm' \
  VLM_REQUEST_TIMEOUT='4m' \
  CORS_ORIGIN='*' \
  POSTER_API_TOKEN='' \
  ./poster-backend \
  > logs/backend.log \
  2>&1 &

echo "$!" > run/backend.pid

echo "Backend PID: $!"
```

验证：

```bash
curl -fsS \
  http://127.0.0.1:8080/health \
  | python3 -m json.tool

curl -fsS \
  http://127.0.0.1:8080/api/system/dependencies \
  | python3 -m json.tool
```

期望：

```json
{
  "dependencies": {
    "comfyui": {
      "status": "ready"
    },
    "database": {
      "status": "ready"
    },
    "vlm": {
      "model": "stageposter-vlm",
      "sleeping": false,
      "status": "ready",
      "url": "http://127.0.0.1:8001"
    }
  },
  "status": "healthy",
  "tokenRequired": false
}
```

---

# 8. Cloudflare Quick Tunnel

Quick Tunnel 仅用于当前前端远程开发：

```text
https://<random>.trycloudflare.com
        ↓
http://127.0.0.1:8080
```

它不会暴露 ComfyUI 和 vLLM。进程重启后 URL 会变化。

## 8.1 安装 cloudflared

```bash
cd /workspace/poster-engine/backend

chmod +x scripts/install-cloudflared.sh
./scripts/install-cloudflared.sh

command -v cloudflared
cloudflared --version
```

若日志出现：

```text
nohup: failed to run command 'cloudflared': No such file or directory
```

说明二进制尚未安装或不在 `PATH`。

## 8.2 启动 Quick Tunnel

```bash
cd /workspace/poster-engine/backend

mkdir -p logs run

if [[ -f run/cloudflared.pid ]]; then
  kill "$(cat run/cloudflared.pid)" \
    2>/dev/null || true
fi

pkill -f \
  'cloudflared tunnel.*127.0.0.1:8080' \
  2>/dev/null || true

rm -f \
  run/cloudflared.pid \
  run/public-api-url.txt

: > logs/cloudflared.log

nohup cloudflared tunnel \
  --url http://127.0.0.1:8080 \
  > logs/cloudflared.log \
  2>&1 &

echo "$!" > run/cloudflared.pid

echo "cloudflared PID: $!"
```

## 8.3 获取开发地址

```bash
cd /workspace/poster-engine/backend

PUBLIC_API_URL=""

for _ in $(seq 1 60); do
  PUBLIC_API_URL="$(
    grep -oE \
      'https://[a-zA-Z0-9-]+\.trycloudflare\.com' \
      logs/cloudflared.log \
      | tail -n 1
  )"

  [[ -n "$PUBLIC_API_URL" ]] && break
  sleep 1
done

if [[ -z "$PUBLIC_API_URL" ]]; then
  echo "Quick Tunnel URL was not found."
  tail -n 100 logs/cloudflared.log
else
  printf '%s\n' "$PUBLIC_API_URL" \
    > run/public-api-url.txt

  echo "PUBLIC_API_URL=$PUBLIC_API_URL"
fi
```

之后读取：

```bash
cat /workspace/poster-engine/backend/run/public-api-url.txt
```

前端配置：

```env
VITE_API_BASE_URL=https://<random>.trycloudflare.com
```

不要在末尾添加 `/`。

## 8.4 测试公网地址

```bash
cd /workspace/poster-engine/backend

PUBLIC_API_URL="$(cat run/public-api-url.txt)"

curl -fsS \
  "$PUBLIC_API_URL/health" \
  | python3 -m json.tool

curl -fsS \
  "$PUBLIC_API_URL/api/system/dependencies" \
  | python3 -m json.tool
```

测试 CORS：

```bash
curl \
  --silent \
  --show-error \
  --request OPTIONS \
  "$PUBLIC_API_URL/api/ai/sessions" \
  -H 'Origin: http://localhost:5173' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type' \
  --dump-header - \
  --output /dev/null
```

预期关键 Header：

```text
HTTP/2 204
access-control-allow-origin: *
access-control-allow-methods: GET, POST, OPTIONS
```

## 8.5 停止 Quick Tunnel

```bash
cd /workspace/poster-engine/backend

if [[ -f run/cloudflared.pid ]]; then
  kill "$(cat run/cloudflared.pid)" \
    2>/dev/null || true
fi

pkill -f \
  'cloudflared tunnel.*127.0.0.1:8080' \
  2>/dev/null || true

rm -f \
  run/cloudflared.pid \
  run/public-api-url.txt

echo "Quick Tunnel stopped."
```

---

# 9. 日志与运行状态

## 9.1 实时查看单个服务

```bash
tail -f /workspace/poster-engine/backend/logs/comfyui.log
```

```bash
tail -f /workspace/poster-engine/backend/logs/vllm.log
```

```bash
tail -f /workspace/poster-engine/backend/logs/backend.log
```

```bash
tail -f /workspace/poster-engine/backend/logs/cloudflared.log
```

## 9.2 查看所有服务最近日志

```bash
cd /workspace/poster-engine/backend

for file in \
  logs/comfyui.log \
  logs/vllm.log \
  logs/backend.log \
  logs/cloudflared.log
do
  echo
  echo "===== $file ====="
  tail -n 80 "$file" 2>/dev/null || true
done
```

## 9.3 查看进程与端口

```bash
pgrep -af \
  'main.py.*8188|vllm serve|poster-backend|cloudflared'
```

```bash
ss -lntp \
  | grep -E ':8001|:8080|:8188'
```

```bash
cd /workspace/poster-engine/backend

for file in run/*.pid; do
  [[ -f "$file" ]] || continue

  echo "$file: $(cat "$file")"
  ps -fp "$(cat "$file")" || true
done
```

## 9.4 监控 W7900

```bash
watch -n 1 \
  rocm-smi \
    --showuse \
    --showmemuse \
    --showtemp \
    --showpower
```

---

# 10. 停止全部服务

按依赖反向停止：

```bash
cd /workspace/poster-engine/backend

for name in cloudflared backend vllm comfyui; do
  pid_file="run/${name}.pid"

  if [[ -f "$pid_file" ]]; then
    kill "$(cat "$pid_file")" \
      2>/dev/null || true
  fi
done

pkill -f \
  'cloudflared tunnel.*127.0.0.1:8080' \
  2>/dev/null || true

pkill -f \
  '/workspace/poster-engine/backend/poster-backend' \
  2>/dev/null || true

pkill -f \
  '/workspace/poster-engine/.venv-vllm/bin/vllm serve' \
  2>/dev/null || true

pkill -f \
  '/workspace/poster-engine/ComfyUI/main.py.*8188' \
  2>/dev/null || true

rm -f \
  run/*.pid \
  run/public-api-url.txt

echo "StagePoster services stopped."
```

确认：

```bash
pgrep -af \
  'main.py.*8188|vllm serve|poster-backend|cloudflared' \
  || echo "No StagePoster service processes remain."
```

---

# 11. 健康检查

## 11.1 本地完整检查

```bash
set -Eeuo pipefail

echo "===== COMFYUI ====="
curl -fsS \
  http://127.0.0.1:8188/system_stats \
  >/tmp/stageposter-comfy-health.json

python3 -m json.tool \
  </tmp/stageposter-comfy-health.json \
  >/dev/null

echo "PASS"

echo
echo "===== VLLM ====="
curl -fsS \
  http://127.0.0.1:8001/v1/models \
  -H 'Authorization: Bearer stageposter-vlm-local' \
  | python3 -m json.tool

echo
echo "===== VLLM SLEEP STATE ====="
curl -fsS \
  http://127.0.0.1:8001/is_sleeping \
  -H 'Authorization: Bearer stageposter-vlm-local'

echo

echo
echo "===== BACKEND ====="
curl -fsS \
  http://127.0.0.1:8080/health \
  | python3 -m json.tool

echo
echo "===== DEPENDENCIES ====="
curl -fsS \
  http://127.0.0.1:8080/api/system/dependencies \
  | python3 -m json.tool

echo
echo "LOCAL HEALTH CHECK PASSED"
```

## 11.2 公网完整检查

```bash
cd /workspace/poster-engine/backend

PUBLIC_API_URL="$(cat run/public-api-url.txt)"

curl -fsS \
  "$PUBLIC_API_URL/health" \
  | python3 -m json.tool

curl -fsS \
  "$PUBLIC_API_URL/api/system/dependencies" \
  | python3 -m json.tool

echo "PUBLIC HEALTH CHECK PASSED"
```

---

# 12. Smoke Test

## 12.1 仓库脚本

```bash
cd /workspace/poster-engine/backend

./scripts/status.sh
./scripts/smoke-test.sh
```

## 12.2 编译测试

```bash
cd /workspace/poster-engine/backend

go test ./...
go build -o poster-backend ./cmd/server
```

## 12.3 完整 API 海报闭环测试

依赖：

```bash
command -v curl
command -v jq
```

执行：

```bash
set -Eeuo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8080}"
SMOKE_DIR="$(mktemp -d /tmp/stageposter-e2e-XXXXXXXX)"

echo "Artifacts: $SMOKE_DIR"

echo
echo "===== 1. DEPENDENCIES ====="

curl -fsS \
  "$BASE_URL/api/system/dependencies" \
  > "$SMOKE_DIR/dependencies.json"

jq . "$SMOKE_DIR/dependencies.json"

test "$(jq -r '.status' "$SMOKE_DIR/dependencies.json")" = "healthy"

echo
echo "===== 2. CREATE SESSION ====="

curl -fsS \
  --request POST \
  "$BASE_URL/api/ai/sessions" \
  -H 'Content-Type: application/json' \
  -d '{
    "brief": {
      "event": {
        "title": "Abyssal Kingdom Festival",
        "artist": "Maverick",
        "date": "2026-08-21",
        "time": "20:00",
        "venue": "Void Arena",
        "presalePrice": "$45",
        "doorPrice": "$60"
      },
      "branding": {},
      "visual": {
        "style": "dark fantasy editorial",
        "theme": "abyssal gothic kingdom",
        "musicGenre": "gothic metal",
        "mood": [
          "epic",
          "mysterious",
          "ritualistic"
        ],
        "preferredColors": [
          "black",
          "aged ivory",
          "deep red"
        ]
      }
    }
  }' \
  > "$SMOKE_DIR/create-session.json"

jq . "$SMOKE_DIR/create-session.json"

SESSION_ID="$(jq -r '.sessionId' "$SMOKE_DIR/create-session.json")"

test -n "$SESSION_ID"
test "$SESSION_ID" != "null"

echo "SESSION_ID=$SESSION_ID"

echo
echo "===== 3. GENERATE DESIGN PLANS ====="

curl -fsS \
  --max-time 480 \
  --request POST \
  "$BASE_URL/api/ai/sessions/$SESSION_ID/messages" \
  -H 'Content-Type: application/json' \
  -d '{
    "content": "确认开始设计。请生成三个海报设计方向，保持 dark fantasy editorial 风格，核心元素是黑色王座和巨大羽翼。"
  }' \
  > "$SMOKE_DIR/design-plans.json"

jq . "$SMOKE_DIR/design-plans.json"

PLAN_ID="$(
  jq -r \
    '.session.plans[0].planId // empty' \
    "$SMOKE_DIR/design-plans.json"
)"

test -n "$PLAN_ID"

echo "PLAN_ID=$PLAN_ID"

echo
echo "===== 4. CONFIRM PLAN ====="

curl -fsS \
  --max-time 240 \
  --request POST \
  "$BASE_URL/api/ai/sessions/$SESSION_ID/plans/$PLAN_ID/confirm" \
  -H 'Content-Type: application/json' \
  -d '{}' \
  > "$SMOKE_DIR/confirm-plan.json"

jq . "$SMOKE_DIR/confirm-plan.json"

POSTER_ID="$(jq -r '.posterId // empty' "$SMOKE_DIR/confirm-plan.json")"

test -n "$POSTER_ID"

echo "POSTER_ID=$POSTER_ID"

echo
echo "===== 5. WAIT FOR CANDIDATES ====="

while true; do
  curl -fsS \
    "$BASE_URL/api/ai/sessions/$SESSION_ID" \
    > "$SMOKE_DIR/session.json"

  STATUS="$(jq -r '.status' "$SMOKE_DIR/session.json")"
  COMPLETED="$(jq -r '.poster.progress.completed // 0' "$SMOKE_DIR/session.json")"
  TOTAL="$(jq -r '.poster.progress.total // 0' "$SMOKE_DIR/session.json")"

  echo "status=$STATUS progress=$COMPLETED/$TOTAL"

  case "$STATUS" in
    awaiting_candidate_selection)
      break
      ;;
    failed|cancelled)
      jq . "$SMOKE_DIR/session.json"
      exit 1
      ;;
  esac

  sleep 10
done

CANDIDATE_ID="$(
  jq -r \
    '.poster.candidates[]
     | select(.status == "ready")
     | .candidateId' \
    "$SMOKE_DIR/session.json" \
    | head -n 1
)"

test -n "$CANDIDATE_ID"
echo "CANDIDATE_ID=$CANDIDATE_ID"

echo
echo "===== 6. SELECT CANDIDATE ====="

curl -fsS \
  --max-time 180 \
  --request POST \
  "$BASE_URL/api/ai/sessions/$SESSION_ID/candidates/$CANDIDATE_ID/select" \
  -H 'Content-Type: application/json' \
  -d '{}' \
  > "$SMOKE_DIR/select-candidate.json"

jq . "$SMOKE_DIR/select-candidate.json"

echo
echo "===== 7. FINALIZE ====="

curl -fsS \
  --max-time 720 \
  --request POST \
  "$BASE_URL/api/ai/sessions/$SESSION_ID/finalize" \
  -H 'Content-Type: application/json' \
  -d '{}' \
  > "$SMOKE_DIR/finalize.json"

jq . "$SMOKE_DIR/finalize.json"

FINAL_STATUS="$(jq -r '.status' "$SMOKE_DIR/finalize.json")"

case "$FINAL_STATUS" in
  succeeded|completed_with_warnings)
    ;;
  *)
    echo "Unexpected final status: $FINAL_STATUS"
    exit 1
    ;;
esac

RESULT_URL="$(jq -r '.poster.resultUrl // empty' "$SMOKE_DIR/finalize.json")"

test -n "$RESULT_URL"

echo
echo "===== 8. DOWNLOAD FINAL POSTER ====="

curl -fsSL \
  "$BASE_URL$RESULT_URL" \
  -o "$SMOKE_DIR/final-poster.png"

file "$SMOKE_DIR/final-poster.png"
ls -lh "$SMOKE_DIR/final-poster.png"

echo
echo "E2E PASSED"
echo "SESSION_ID=$SESSION_ID"
echo "POSTER_ID=$POSTER_ID"
echo "FINAL_STATUS=$FINAL_STATUS"
echo "ARTIFACTS=$SMOKE_DIR"
```

---

# 13. Backend API

## 13.1 Base URL

本地：

```text
http://127.0.0.1:8080
```

临时远程开发：

```text
https://<random>.trycloudflare.com
```

前端只切换一个变量：

```env
VITE_API_BASE_URL=https://<random>.trycloudflare.com
```

## 13.2 接口总览

### 健康与依赖

| Method | Path | 用途 |
|---|---|---|
| `GET` | `/health` | Backend、ComfyUI、数据库健康状态 |
| `GET` | `/api/system/dependencies` | SQLite、ComfyUI、vLLM、sleep state、token 状态 |

### AI 设计与 Session

| Method | Path | 用途 |
|---|---|---|
| `POST` | `/api/ai/design` | 一次性生成 3 个结构化设计方向 |
| `POST` | `/api/ai/sessions` | 创建交互式 AI 海报 Session |
| `GET` | `/api/ai/sessions/{sessionId}` | 获取 Session、Plans、Candidates、进度和结果 |
| `POST` | `/api/ai/sessions/{sessionId}/messages` | 发送消息并推进 Brief 或方案生成 |
| `POST` | `/api/ai/sessions/{sessionId}/assets` | 绑定已上传素材 |
| `POST` | `/api/ai/sessions/{sessionId}/plans/{planId}/confirm` | 确认方案并生成 3 张候选图 |
| `POST` | `/api/ai/sessions/{sessionId}/candidates/{candidateId}/select` | 选择候选图并进行确定性合成 |
| `POST` | `/api/ai/sessions/{sessionId}/finalize` | 执行有限轮视觉审查和自动优化 |
| `POST` | `/api/ai/sessions/{sessionId}/cancel` | 取消 Session |

### Poster

| Method | Path | 用途 |
|---|---|---|
| `POST` | `/api/posters` | 不经过交互 Session 创建 Poster |
| `GET` | `/api/posters/{posterId}` | 获取 Poster、候选图和进度 |
| `POST` | `/api/posters/{posterId}/select` | 通过 body 中的 `candidateId` 选择候选图 |
| `GET` | `/api/posters/{posterId}/candidates/{candidateId}/image` | 下载候选图 |
| `GET` | `/api/posters/{posterId}/result` | 下载最终完整海报 |
| `GET` | `/api/posters/{posterId}/thumbnail` | 下载缩略图 |
| `POST` | `/api/posters/{posterId}/review` | 执行一次 Qwen 视觉审查 |
| `GET` | `/api/posters/{posterId}/reviews` | 获取已持久化审查证据 |
| `GET` | `/api/posters/{posterId}/timeline` | 获取生命周期与审查时间线 |

### 低层 Generation 与 Jobs

| Method | Path | 用途 |
|---|---|---|
| `POST` | `/api/generate` | 提交低层生成任务 |
| `GET` | `/api/jobs?limit=20` | 列出任务 |
| `GET` | `/api/jobs/{jobId}` | 查询任务状态 |
| `GET` | `/api/jobs/{jobId}/result` | 下载任务结果 |

### Assets

| Method | Path | 用途 |
|---|---|---|
| `POST` | `/api/assets` | 上传素材 |
| `GET` | `/api/assets/{assetId}` | 通过 Backend 获取素材 |

## 13.3 创建 Session

顶层必须使用 `brief`，不能把 `event` 直接放在顶层：

```bash
curl -fsS \
  --request POST \
  "$API_BASE_URL/api/ai/sessions" \
  -H 'Content-Type: application/json' \
  -d '{
    "brief": {
      "event": {
        "title": "Abyssal Kingdom Festival",
        "artist": "Maverick",
        "date": "2026-08-21",
        "time": "20:00",
        "venue": "Void Arena",
        "presalePrice": "$45",
        "doorPrice": "$60"
      },
      "branding": {},
      "visual": {
        "style": "dark fantasy editorial",
        "theme": "abyssal gothic kingdom",
        "musicGenre": "gothic metal",
        "mood": ["epic", "mysterious", "ritualistic"],
        "preferredColors": ["black", "aged ivory", "deep red"]
      }
    },
    "assets": []
  }'
```

必填字段：

```text
event.title
event.artist
event.date
event.time
event.venue
visual.style
visual.theme
visual.musicGenre
visual.mood
```

Backend 使用严格 JSON 解码，未知字段会被拒绝。

## 13.4 发送消息

```bash
curl -fsS \
  --request POST \
  "$API_BASE_URL/api/ai/sessions/$SESSION_ID/messages" \
  -H 'Content-Type: application/json' \
  -d '{
    "content": "确认开始设计，请生成三个不同方向的海报设计方案。"
  }'
```

响应包含：

```text
session
metrics.promptTokens
metrics.completionTokens
metrics.latencyMs
```

## 13.5 确认方案

必须使用当前 Session 返回的 `planId`：

```bash
curl -fsS \
  --request POST \
  "$API_BASE_URL/api/ai/sessions/$SESSION_ID/plans/$PLAN_ID/confirm" \
  -H 'Content-Type: application/json' \
  -d '{}'
```

不要复用另一个 Session 的 plan ID。

## 13.6 轮询候选图

```bash
curl -fsS \
  "$API_BASE_URL/api/ai/sessions/$SESSION_ID" \
  | jq '{
      status,
      posterId,
      progress: .poster.progress,
      candidates: [
        .poster.candidates[]? |
        {
          candidateId,
          variantName,
          status,
          imageUrl
        }
      ]
    }'
```

推荐前端策略：

```text
前 10 秒：每 1 秒轮询
之后：每 2 秒轮询
进入终态或等待用户操作的状态后停止
```

## 13.7 选择候选图

```bash
curl -fsS \
  --request POST \
  "$API_BASE_URL/api/ai/sessions/$SESSION_ID/candidates/$CANDIDATE_ID/select" \
  -H 'Content-Type: application/json' \
  -d '{}'
```

## 13.8 Finalize

```bash
curl -fsS \
  --max-time 720 \
  --request POST \
  "$API_BASE_URL/api/ai/sessions/$SESSION_ID/finalize" \
  -H 'Content-Type: application/json' \
  -d '{}'
```

终态：

| Status | 含义 |
|---|---|
| `succeeded` | 最终海报完成且审查接受 |
| `completed_with_warnings` | 审查轮数结束，保留最佳可用版本 |
| `needs_user_input` | 需要修改创意方向 |
| `failed` | 生成或合成失败 |
| `cancelled` | Session 被取消 |

审查摘要示例：

```json
{
  "finalized": true,
  "accepted": false,
  "rounds": 2,
  "bestRound": 2,
  "bestScore": 88,
  "latestDecision": "RECOMPOSE",
  "warning": "Maximum review rounds reached or automatic optimization stopped; the best available version was retained."
}
```

## 13.9 下载结果

```bash
curl -fsSL \
  "$API_BASE_URL/api/posters/$POSTER_ID/result" \
  -o final-poster.png
```

```bash
curl -fsSL \
  "$API_BASE_URL/api/posters/$POSTER_ID/thumbnail" \
  -o thumbnail.png
```

## 13.10 鉴权与 CORS

当前开发模式：

```text
POSTER_API_TOKEN=
CORS_ORIGIN=*
tokenRequired=false
```

启用 Token 后，Backend 支持：

```text
X-Poster-Token: <token>
```

或：

```text
Authorization: Bearer <token>
```

开发 CORS：

```text
GET, POST, OPTIONS
Content-Type, Authorization, X-Poster-Token
```

---

# 14. Session 状态机

```text
collecting_brief
    ↓
awaiting_plan_selection
    ↓
generating_candidates
    ↓
awaiting_candidate_selection
    ↓
looping
    ↓
succeeded
    ↓
completed_with_warnings
```

其他状态：

```text
needs_user_input
failed
cancelled
```

前端应遵循 Backend 返回的 `availableActions`，不要自行猜测当前允许执行的动作。

| State | 常见 availableActions |
|---|---|
| `collecting_brief` | `send_message`, `attach_asset`, `cancel` |
| `awaiting_plan_selection` | `send_message`, `confirm_plan`, `cancel` |
| `generating_candidates` | `refresh`, `cancel` |
| `awaiting_candidate_selection` | `select_candidate`, `cancel` |
| `succeeded` | `finalize`, `download_final` |
| `completed_with_warnings` | `download_final` |

---

# 15. Qwen3.5-9B 在 W7900 上的性能

## 15.1 已验证能力

当前部署已验证：

- Qwen3.5-9B 可以通过 vLLM 在 ROCm 环境正常加载。
- 提供 OpenAI-compatible Chat Completions API。
- 支持中英文结构化 Creative Brief。
- 可以稳定生成 3 个严格结构化设计方案。
- 可以读取最终海报进行多模态视觉审查。
- 每次 AI 调用记录 `promptTokens`、`completionTokens` 和 `latencyMs`。
- 支持 sleep mode，为 ComfyUI 释放显存。

参考 Session 中，从用户提交设计消息到 Backend 持久化三个设计方案的端到端时间约为 41 秒。该时间包含 Backend 编排、模型推理、JSON 生成、解析、校验和数据库写入，不等于纯 Decoder Token Throughput。

## 15.2 历史 Token 速度说明

用于编写本文档的源码快照和运行记录中，没有保留一组可核验的历史 `tokens/s` 和峰值吞吐数字。

因此本文档不写入猜测值。正式提交前应在最终 W7900 节点运行下面的可复现实验，并把输出回填到结果表。

## 15.3 可复现 vLLM 吞吐测试

该测试会：

- 先执行 1 次 warm-up；
- 再执行 5 次正式测量；
- 输出 Prompt Tokens；
- 输出 Completion Tokens；
- 输出完整请求耗时；
- 计算 Output Tokens/s；
- 汇总中位数和峰值。

```bash
/workspace/poster-engine/.venv-vllm/bin/python - <<'PY'
import json
import statistics
import time
import urllib.request

URL = "http://127.0.0.1:8001/v1/chat/completions"
API_KEY = "stageposter-vlm-local"
MODEL = "stageposter-vlm"

payload = {
    "model": MODEL,
    "messages": [
        {
            "role": "user",
            "content": (
                "Return a compact JSON object describing three distinct "
                "dark-fantasy music poster directions. "
                "Do not use Markdown."
            ),
        }
    ],
    "temperature": 0,
    "max_tokens": 512,
    "stream": False,
    "chat_template_kwargs": {
        "enable_thinking": False
    },
}


def run_once(index: int) -> dict:
    request = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        method="POST",
    )

    started = time.perf_counter()

    with urllib.request.urlopen(
        request,
        timeout=600,
    ) as response:
        body = json.load(response)

    elapsed = time.perf_counter() - started
    usage = body.get("usage") or {}

    prompt_tokens = int(
        usage.get("prompt_tokens") or 0
    )
    completion_tokens = int(
        usage.get("completion_tokens") or 0
    )
    total_tokens = int(
        usage.get("total_tokens") or 0
    )

    output_tps = (
        completion_tokens / elapsed
        if elapsed > 0
        else 0.0
    )

    result = {
        "run": index,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "latency_seconds": round(elapsed, 3),
        "output_tokens_per_second": round(
            output_tps,
            3,
        ),
    }

    print(json.dumps(result, ensure_ascii=False))
    return result


print("Warm-up")
run_once(0)

print("Measured runs")
results = [
    run_once(index)
    for index in range(1, 6)
]

throughputs = [
    result["output_tokens_per_second"]
    for result in results
]

latencies = [
    result["latency_seconds"]
    for result in results
]

summary = {
    "measured_runs": len(results),
    "median_output_tokens_per_second": round(
        statistics.median(throughputs),
        3,
    ),
    "peak_output_tokens_per_second": round(
        max(throughputs),
        3,
    ),
    "median_latency_seconds": round(
        statistics.median(latencies),
        3,
    ),
}

print("Summary")
print(json.dumps(summary, ensure_ascii=False, indent=2))
PY
```

回填表：

| Metric | W7900 Result |
|---|---:|
| Warm-up | 执行 Benchmark 后填写 |
| Median Output Tokens/s | 执行 Benchmark 后填写 |
| Peak Output Tokens/s | 执行 Benchmark 后填写 |
| Median Request Latency | 执行 Benchmark 后填写 |
| Context Length | 4096 |
| Max Concurrent Sequences | 1 |
| Configured vLLM VRAM Budget | 65%，约 31.2 GiB |
| Precision | FP16 |

### 指标边界

上面的脚本测量完整的非流式请求吞吐，不测量：

- Time To First Token；
- 流式 Inter-token Latency；
- 多用户并发吞吐；
- ComfyUI 出图速度；
- 整个 StagePoster E2E 时间。

正式报告性能时，应同时记录：

1. Git Commit；
2. ROCm / HIP 版本；
3. vLLM / Torch 版本；
4. 测试 Prompt；
5. `max_tokens`；
6. Warm-up 策略；
7. 测试次数；
8. Median 和 Peak；
9. GPU 温度、功耗和显存状态。

---

# 16. 复现与实例恢复

## 16.1 实例重置后恢复

```bash
cd /workspace/poster-engine/backend

sudo ./scripts/recover-after-instance-kill.sh
```

恢复完成后：

```bash
./scripts/start-all.sh
./scripts/status.sh
./scripts/smoke-test.sh
./scripts/start-dev-tunnel.sh
```

## 16.2 销毁实例前持久化

平台维护窗口前的**轻量**备份（推荐日常用这个）：

```bash
cd /workspace/poster-engine

bash scripts/backup-persistence.sh          # 快速
bash scripts/backup-persistence.sh --hash   # 附带权重 sha256，慢
```

产物在 `/workspace/persistence/stageposter/backups/<时间戳>/`，
`backups/latest` 指向最新一份，内含 `RESTORE.md` 逐步恢复说明。

实例即将被销毁时的**完整**持久化（还会记录工具链、Python runtime、运行命令等）：

```bash
cd /workspace/poster-engine/backend

sudo -E bash scripts/prepare-before-instance-kill.sh
```

> **注意用 `sudo -E`**，不要用 `sudo`。脚本要读项目根目录的 `.env` 拿 `DB_PATH`，
> 丢掉环境会退回到默认值。

持久化流程记录：

- SQLite WAL checkpoint 与数据库备份；
- Backend 环境变量；
- Workflow；
- 模型文件清单和 Checksum；
- ComfyUI 模型；
- Qwen 模型清单；
- Python Runtime 位置；
- Go Toolchain；
- cloudflared Binary；
- 当前运行命令；
- 系统版本；

### 这两个脚本此前的两个 bug（已修，2026-07-31）

写在这里是因为**修复前跑完会打印 `PERSISTENCE PREPARATION COMPLETE`**，
看起来完全成功：

1. **备份目录落在 `/workspace/poster-engine/persist`** —— 即项目目录内部，
   恰好是实例重置时会被清掉的地方。现在落在
   `/workspace/persistence/stageposter/prekill`（可用 `PERSIST_ROOT` 覆盖）。
   `recover-after-instance-kill.sh` 里的同一处路径也一起改了，否则恢复会去错的
   地方找。
2. **数据库路径写死成 `backend/data/poster.db`** —— 那是早期遗留文件，不是线上库。
   线上库由 `.env` 的 `DB_PATH` 指向持久化目录。实测写死会备份到 13 行，
   而线上是 56 行。现在从 `.env` 读。

另外加了一道预检：当权重源和备份目标在**同一个文件系统**上时，跳过那 20G 的
`rsync` —— 同卷复制不构成任何保护（卷没了两份一起没），却会把剩余空间从 26G
压到 6G，中途失败还会留下截断的权重文件，比没有权重更难排查。
跳过时仍然记录 `model-sizes.txt` 供恢复时核对。需要强制复制：`FORCE_MODEL_COPY=1`。
- Git State；
- Symlink 审计；
- E2E Artifacts。

## 16.3 源码和模型检查

```bash
cd /workspace/poster-engine/backend

go test ./...
go build ./...

find /workspace/poster-engine/models/Qwen3.5-9B \
  -maxdepth 1 \
  -type f \
  -printf '%s\t%f\n' \
  | sort -n

find /workspace/poster-engine/ComfyUI/models \
  -type f \
  -name '*.safetensors' \
  -printf '%s\t%p\n' \
  | sort -n
```

---

# 17. Troubleshooting

## `cloudflared: No such file or directory`

原因：cloudflared 未安装或不在 `PATH`。

```bash
cd /workspace/poster-engine/backend
./scripts/install-cloudflared.sh

command -v cloudflared
cloudflared --version
```

## 无法获取 Quick Tunnel URL

```bash
tail -n 200 \
  /workspace/poster-engine/backend/logs/cloudflared.log
```

```bash
ps -fp "$(
  cat /workspace/poster-engine/backend/run/cloudflared.pid
)"
```

先确认本地 Origin：

```bash
curl -fsS \
  http://127.0.0.1:8080/health \
  | python3 -m json.tool
```

排错时不要在 SSH Shell 中直接执行无保护的 `exit 1`，否则会关闭当前连接。

## 公网 URL 返回 502

```bash
curl -fsS http://127.0.0.1:8080/health
ss -lntp | grep ':8080'

tail -n 100 \
  /workspace/poster-engine/backend/logs/backend.log

tail -n 100 \
  /workspace/poster-engine/backend/logs/cloudflared.log
```

## vLLM unavailable

```bash
tail -n 200 \
  /workspace/poster-engine/backend/logs/vllm.log
```

```bash
curl -v \
  http://127.0.0.1:8001/v1/models \
  -H 'Authorization: Bearer stageposter-vlm-local'
```

```bash
/workspace/poster-engine/.venv-vllm/bin/python - <<'PY'
import torch
import vllm

print(vllm.__version__)
print(torch.__version__)
print(torch.version.hip)
print(torch.cuda.is_available())

if torch.cuda.is_available():
    print(torch.cuda.get_device_name(0))
PY
```

## ComfyUI unavailable

```bash
tail -n 200 \
  /workspace/poster-engine/backend/logs/comfyui.log
```

```bash
curl -v http://127.0.0.1:8188/system_stats
```

```bash
find /workspace/poster-engine/ComfyUI/models \
  -type f \
  -name '*.safetensors'
```

## Backend dependency degraded

```bash
curl -s \
  http://127.0.0.1:8080/api/system/dependencies \
  | python3 -m json.tool
```

响应会明确指出：

```text
database
comfyui
vlm
```

哪一个依赖不可用。

## `session or plan not found`

使用同一 Session 实际返回的 Plan ID：

```bash
curl -fsS \
  "$BASE_URL/api/ai/sessions/$SESSION_ID" \
  | jq -r '.plans[].planId'
```

不要使用另一次运行中的旧 Plan ID。

## Candidate 长时间停在 0 / 3

```bash
tail -f \
  /workspace/poster-engine/backend/logs/backend.log
```

```bash
tail -f \
  /workspace/poster-engine/backend/logs/comfyui.log
```

```bash
rocm-smi \
  --showuse \
  --showmemuse \
  --showtemp \
  --showpower
```

## `completed_with_warnings`

这不是网络错误。它表示：

- 最终图片存在；
- 确定性合成成功；
- 审查证据已存储；
- 审查达到最大轮数；
- 系统保留评分最高版本。

```bash
curl -fsS \
  "$BASE_URL/api/ai/sessions/$SESSION_ID" \
  | jq '.reviewSummary'
```

## `nohup: ignoring input`

这是 `nohup` 启动后台进程时的正常提示，不是服务启动失败。

## vLLM sleep mode 在 ROCm 上的已知问题

在当前 ROCm 7.2 + vLLM 0.20.0 环境下，`--enable-sleep-mode` 的 `wake_up` 调用可能失败：

```text
Exception: Call to wake_up method failed: CUDA Error: invalid argument
    at /app/vllm/csrc/cumem_allocator.cpp:187
```

临时解决方案：去掉 `--enable-sleep-mode` 参数启动 vLLM。W7900 48GB 显存足够同时容纳 Qwen3.5-9B (FP16, ~18GB) 和 ComfyUI Z-Image Turbo (~6GB)。

已修复：`start-all.sh` 和 `scripts/smoke-test.sh` 不再依赖 `--enable-sleep-mode`。

## 候选图卡在 generating_candidates

原因：`PosterStatusPartialReady` 曾被错误地放入 `ReconcilePoster` 的终态跳过列表，导致 1 张候选图就绪后，剩余候选图的 reconciliation 停止。

修复：将 `PartialReady` 从跳过列表移除，使其回退到继续 reconciliation 剩余候选图。

```text
// 修复前：PartialReady 在跳过列表中 → reconciler 停止
case PosterStatusPartialReady:  // ← 被跳过！

// 修复后：PartialReady 继续 reconciliation
case PosterStatusPartialReady:
    // 继续 reconciliation 剩余候选图
```

---

# 18. 安全说明

当前开发设置：

```text
CORS_ORIGIN=*
POSTER_API_TOKEN=
```

它适合短期黑客松开发，但不适合无限制长期公开服务。

正式演示或部署前：

- 设置非空 `POSTER_API_TOKEN`；
- 将 `CORS_ORIGIN` 限定为真实前端域名；
- 对生成请求进行限流；
- 保持单卡 GPU 并发有界；
- 保持 8001 和 8188 只监听 Loopback；
- 只暴露 Go API；
- 不提交数据库、模型、日志、Tunnel URL 和 Secret；
- 不让浏览器访问原始 ComfyUI Workflow API。

---

# 19. 前端联调清单

```text
[ ] 从 VITE_API_BASE_URL 读取 Backend 地址
[ ] 不把 Quick Tunnel URL 写死进源码
[ ] 只调用 StagePoster Go API
[ ] 创建 Session 时使用顶层 brief
[ ] 渲染 Backend 返回的 Plans 和 Plan IDs
[ ] 通过 Session GET 轮询状态
[ ] 遵循 availableActions
[ ] 展示三张 Candidate Image URL
[ ] 使用 Candidate ID 提交选择
[ ] succeeded 和 completed_with_warnings 都允许下载结果
[ ] failed 或 cancelled 后停止轮询
[ ] Tunnel 重启后允许替换 Base URL
```

前端环境：

```env
VITE_API_BASE_URL=https://<random>.trycloudflare.com
```

示例：

```ts
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL;

const response = await fetch(
  `${apiBaseUrl}/api/system/dependencies`,
);

if (!response.ok) {
  throw new Error(
    `StagePoster API returned ${response.status}`,
  );
}

const dependencies = await response.json();
```

---

# 20. Daily Operator Card

## 启动

```bash
cd /workspace/poster-engine/backend

./scripts/start-all.sh
./scripts/status.sh
./scripts/smoke-test.sh
./scripts/start-dev-tunnel.sh

cat run/public-api-url.txt
```

## 检查

```bash
curl -fsS \
  http://127.0.0.1:8080/api/system/dependencies \
  | python3 -m json.tool

PUBLIC_API_URL="$(cat run/public-api-url.txt)"

curl -fsS \
  "$PUBLIC_API_URL/api/system/dependencies" \
  | python3 -m json.tool
```

## 日志

```bash
tail -f logs/backend.log
tail -f logs/comfyui.log
tail -f logs/vllm.log
tail -f logs/cloudflared.log
```

## 只停止 Tunnel

```bash
kill "$(cat run/cloudflared.pid)" \
  2>/dev/null || true

rm -f \
  run/cloudflared.pid \
  run/public-api-url.txt
```

## 停止全部

```bash
cd /workspace/poster-engine/backend

for name in cloudflared backend vllm comfyui; do
  [[ -f "run/${name}.pid" ]] &&
    kill "$(cat "run/${name}.pid")" \
      2>/dev/null || true
done

pkill -f \
  'cloudflared tunnel.*127.0.0.1:8080|poster-backend|vllm serve|main.py.*8188' \
  2>/dev/null || true

rm -f \
  run/*.pid \
  run/public-api-url.txt
```

---

## 最终复现判定

只有以下条件全部通过，才视为完成复现：

```text
[✓] ROCm 识别 gfx1100
[✓] ComfyUI 在 127.0.0.1:8188 可访问
[✓] vLLM 在 127.0.0.1:8001 返回 stageposter-vlm
[✓] Backend /health 返回 HTTP 200
[✓] /api/system/dependencies 返回 healthy
[✓] AI Session 返回 3 个设计方案
[✓] 确认方案后生成 3 张候选图
[✓] 候选图可以被选择
[✓] Go 确定性最终海报合成成功
[✓] Finalize 返回 succeeded 或 completed_with_warnings
[✓] 最终海报和 Thumbnail 可下载
[✓] Quick Tunnel 公网健康检查通过
[✓] 冒烟测试 (scripts/smoke-test.sh) 全部通过
```

StagePoster 只有在用户能够下载一张可用的最终海报时，才算在产品边界上完成。单次模型调用成功不等于产品完成。
