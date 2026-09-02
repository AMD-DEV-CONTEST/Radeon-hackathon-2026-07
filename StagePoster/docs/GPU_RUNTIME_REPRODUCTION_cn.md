---

# StagePoster 单 GPU 推理服务启动与复现指南

## 1. 文档目标

本文档用于在单张 AMD GPU 服务器上复现 StagePoster 的核心链路：

```text
创建 AI Session
→ Qwen 理解用户 Brief
→ 生成三套 Design Plan
→ 确认 Plan
→ Z-Image Turbo 生成三张 Candidate
→ 返回候选图 URL
```

当前验证环境采用一张约 48GB 显存的 AMD GPU，同时运行：

- StagePoster Go Backend
- vLLM + Qwen3.5-9B
- ComfyUI + Z-Image Turbo

由于 Qwen 和 Z-Image 无法稳定同时常驻显存，系统采用 GPU 显存接力机制：

```text
Qwen 阶段
→ Backend 调用 vLLM /wake_up
→ Brief / Plan / Review
→ Backend 调用 vLLM /sleep?level=1
→ Qwen 显存释放

ComfyUI 阶段
→ 加载 Z-Image
→ 生成 Candidates
→ POST /free
→ 卸载模型并释放显存
```

---

# 2. 已验证环境

本次测试成功环境：

```text
OS: Ubuntu Linux
GPU: AMD Radeon GPU，约 48GB VRAM
ROCm: 7.2 系列
Python for ComfyUI: 3.10.20
Python for vLLM: 3.12 virtual environment
vLLM: 0.25.1
ComfyUI: 0.28.0
Go: 1.25.0
Backend port: 8080
ComfyUI port: 8188
vLLM port: 8001
```

模型：

```text
Qwen:
  /workspace/poster-engine/models/Qwen3.5-9B

Z-Image Turbo:
  z_image_turbo_bf16.safetensors
  qwen_3_4b.safetensors
  ae.safetensors
```

项目根目录：

```text
/workspace/poster-engine
```

建议所有需要持久化的内容全部放在 `/workspace`，不要放在实例重启后可能清空的 `/models`、`/root` 或其他临时挂载目录。

---

# 3. 推荐目录结构

```text
/workspace/poster-engine/
├── backend/
│   ├── poster-backend
│   ├── data/
│   ├── storage/
│   └── logs/
│
├── ComfyUI/
│   ├── main.py
│   └── models/
│       ├── diffusion_models/
│       ├── text_encoders/
│       ├── vae/
│       └── loras/
│
├── models/
│   ├── Qwen3.5-9B/
│   └── poster/
│       ├── diffusion_models/
│       ├── text_encoders/
│       ├── vae/
│       └── loras/
│
├── workflows/
│   └── z_image_poster_v1.json
│
├── logs/
│   ├── backend.log
│   ├── comfyui/
│   │   └── server.log
│   └── vllm/
│       └── server.log
│
├── venv/
├── .venv-vllm/
├── backend.pid
├── comfyui.pid
└── vllm.pid
```

---

# 4. 核心端口

| 服务 | 地址 | 用途 |
|---|---|---|
| Backend | `127.0.0.1:8080` | StagePoster API |
| ComfyUI | `127.0.0.1:8188` | Z-Image 推理 |
| vLLM | `127.0.0.1:8001` | Qwen 推理 |

检查监听：

```bash
lsof -iTCP:8080 -sTCP:LISTEN
lsof -iTCP:8188 -sTCP:LISTEN
lsof -iTCP:8001 -sTCP:LISTEN
```

服务器安装了 `iproute2` 后也可以：

```bash
ss -ltnp | grep -E ':8080|:8188|:8001'
```

---

# 5. 启动 vLLM

## 5.1 稳定参数

本次验证中，以下参数可以稳定完成：

```text
sleep
→ wake_up
→ 推理
→ sleep
```

> **⚠️ 已废弃 —— 不要照抄下面的 sleep mode 参数。**
>
> 本节记录的是当初 bring-up 时验证过的配置。后来发现在 **ROCm 7.2 + vLLM
> 0.20.0** 上 `--enable-sleep-mode` 会破坏生成：第一次 sleep→wake 循环之后，
> 后续每个请求都以 `CUDA Error: invalid argument` 失败。
>
> 因此生产启动脚本 `scripts/start-all.sh` **不再开启 sleep mode，也从不请求
> 睡眠**，而是打印 `VLM resident (sleep mode disabled on ROCm)`。显存改由 Go
> 运行时协调器在调用 VLM 前调用 `ReleaseComfyMemory` 卸载 ComfyUI 模型来回收。
>
> 另有两个本节尚未包含、但现在必须加的参数：
> - `--mm-processor-cache-gb 0` —— 默认 4 GB 的多模态预处理缓存运行一段时间后
>   会自我损坏，之后每个带图请求都 500，报
>   `AssertionError: Expected a cached item for mm_hash=...`
> - `VLLM_SERVER_DEV_MODE=1` 必须**保持内网**，它会在 8001 暴露无鉴权的管理端点。
>
> 请使用 `scripts/start-all.sh`，而不是下面的命令。

关键参数（bring-up 当时验证；sleep 那一项见上方警告，现已不用）：

```bash
VLLM_ROCM_SLEEP_MEM_CHUNK_SIZE=64
--gpu-memory-utilization 0.65
--enable-sleep-mode           # ← 已废弃，在 ROCm 7.2 上会破坏生成
```

以下旧配置曾导致 OOM 或 `cumem_allocator.cpp invalid argument`：

```text
--gpu-memory-utilization 0.90
VLLM_ROCM_SLEEP_MEM_CHUNK_SIZE=128
```

## 5.2 启动命令

```bash
cd /workspace/poster-engine

mkdir -p logs/vllm

if [[ -f vllm.pid ]]; then
  kill "$(cat vllm.pid)" 2>/dev/null || true
fi

VLLM_PID="$(
  lsof -tiTCP:8001 -sTCP:LISTEN 2>/dev/null \
  | head -n 1
)"

if [[ -n "$VLLM_PID" ]]; then
  kill "$VLLM_PID"
fi

sleep 5

nohup env \
  VLLM_SERVER_DEV_MODE=1 \
  VLLM_ROCM_SLEEP_MEM_CHUNK_SIZE=64 \
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
  --gpu-memory-utilization 0.65 \
  --limit-mm-per-prompt '{"image":{"count":1,"width":768,"height":1152},"video":0}' \
  --enforce-eager \
  --mm-processor-cache-gb 0 \
  --default-chat-template-kwargs '{"enable_thinking":false}' \
  --generation-config vllm \
  > /workspace/poster-engine/logs/vllm/server.log \
  2>&1 &

echo $! > /workspace/poster-engine/vllm.pid

echo "vLLM PID=$(cat /workspace/poster-engine/vllm.pid)"
```

## 5.3 等待 vLLM 就绪

```bash
for i in $(seq 1 180); do
  CODE="$(
    curl --max-time 5 \
      -sS \
      -o /tmp/vllm-models.json \
      -w '%{http_code}' \
      http://127.0.0.1:8001/v1/models \
      -H "Authorization: Bearer stageposter-vlm-local" \
      2>/dev/null || true
  )"

  if [[ "$CODE" == "200" ]]; then
    echo "vLLM ready"
    break
  fi

  printf '.'
  sleep 2
done

echo
tail -80 /workspace/poster-engine/logs/vllm/server.log
```

---

# 6. 验证 vLLM Sleep/Wake

## 6.1 清醒状态推理

```bash
curl --max-time 180 \
  -sS \
  -X POST \
  http://127.0.0.1:8001/v1/chat/completions \
  -H "Authorization: Bearer stageposter-vlm-local" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "stageposter-vlm",
    "messages": [
      {
        "role": "user",
        "content": "只回复 AWAKE"
      }
    ],
    "temperature": 0,
    "max_tokens": 8
  }' \
  | python3 -m json.tool
```

预期：

```json
{
  "choices": [
    {
      "message": {
        "content": "AWAKE"
      }
    }
  ]
}
```

## 6.2 进入睡眠

```bash
curl --max-time 180 \
  -sS \
  -X POST \
  "http://127.0.0.1:8001/sleep?level=1" \
  -H "Authorization: Bearer stageposter-vlm-local"

sleep 8
```

检查：

```bash
curl -sS \
  http://127.0.0.1:8001/is_sleeping \
  -H "Authorization: Bearer stageposter-vlm-local"

echo
rocm-smi --showmeminfo vram
```

本次实际结果：

```text
is_sleeping: true
VRAM Used: 约 729 MB
```

## 6.3 唤醒

```bash
curl --max-time 300 \
  -sS \
  -D /tmp/vllm-wake.headers \
  -o /tmp/vllm-wake.body \
  -w '\nHTTP_STATUS=%{http_code}\n' \
  -X POST \
  http://127.0.0.1:8001/wake_up \
  -H "Authorization: Bearer stageposter-vlm-local"
```

预期：

```text
HTTP_STATUS=200
```

唤醒后显存约：

```text
33 GB
```

## 6.4 唤醒后再次推理

```bash
curl --max-time 180 \
  -sS \
  -X POST \
  http://127.0.0.1:8001/v1/chat/completions \
  -H "Authorization: Bearer stageposter-vlm-local" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "stageposter-vlm",
    "messages": [
      {
        "role": "user",
        "content": "只回复 WOKE"
      }
    ],
    "temperature": 0,
    "max_tokens": 8
  }' \
  | python3 -m json.tool
```

预期：

```json
{
  "choices": [
    {
      "message": {
        "content": "WOKE"
      }
    }
  ]
}
```

---

# 7. 启动 ComfyUI

启动 ComfyUI 前，建议确认 vLLM 处于 sleeping 状态。

```bash
curl -sS \
  http://127.0.0.1:8001/is_sleeping \
  -H "Authorization: Bearer stageposter-vlm-local"
```

预期：

```json
{"is_sleeping":true}
```

启动 ComfyUI：

```bash
cd /workspace/poster-engine/ComfyUI

mkdir -p /workspace/poster-engine/logs/comfyui

if [[ -f /workspace/poster-engine/comfyui.pid ]]; then
  kill "$(cat /workspace/poster-engine/comfyui.pid)" \
    2>/dev/null || true
fi

COMFY_PID="$(
  lsof -tiTCP:8188 -sTCP:LISTEN 2>/dev/null \
  | head -n 1
)"

if [[ -n "$COMFY_PID" ]]; then
  kill "$COMFY_PID"
fi

sleep 3

nohup /workspace/poster-engine/venv/bin/python \
  main.py \
  --listen 0.0.0.0 \
  --port 8188 \
  > /workspace/poster-engine/logs/comfyui/server.log \
  2>&1 &

echo $! > /workspace/poster-engine/comfyui.pid

echo "ComfyUI PID=$(cat /workspace/poster-engine/comfyui.pid)"
```

等待就绪：

```bash
for i in $(seq 1 120); do
  CODE="$(
    curl --max-time 3 \
      -sS \
      -o /tmp/comfy-system.json \
      -w '%{http_code}' \
      http://127.0.0.1:8188/system_stats \
      2>/dev/null || true
  )"

  if [[ "$CODE" == "200" ]]; then
    echo "ComfyUI ready"
    break
  fi

  printf '.'
  sleep 2
done

echo
tail -80 /workspace/poster-engine/logs/comfyui/server.log
```

---

# 8. 验证 ComfyUI 模型

```bash
curl -sS \
  http://127.0.0.1:8188/object_info \
  > /tmp/comfy-object-info.json
```

解析模型列表：

```bash
python3 - <<'PY'
import json

with open("/tmp/comfy-object-info.json") as f:
    data = json.load(f)

checks = {
    "UNETLoader": "unet_name",
    "CLIPLoader": "clip_name",
    "VAELoader": "vae_name",
}

for node_name, input_name in checks.items():
    values = (
        data.get(node_name, {})
        .get("input", {})
        .get("required", {})
        .get(input_name, [[]])[0]
    )

    print(f"\n{node_name}:")
    for value in values:
        print("  ", value)
PY
```

必须包含：

```text
UNETLoader:
  z_image_turbo_bf16.safetensors

CLIPLoader:
  qwen_3_4b.safetensors

VAELoader:
  ae.safetensors
```

---

# 9. 验证 Workflow 尺寸

StagePoster Candidate 合约要求：

```text
width  = 1024
height = 1536
```

检查：

```bash
python3 - <<'PY'
import json

path = "/workspace/poster-engine/workflows/z_image_poster_v1.json"

with open(path) as f:
    data = json.load(f)

def walk(value, path="root"):
    if isinstance(value, dict):
        if "width" in value or "height" in value:
            print(
                path,
                "width=", value.get("width"),
                "height=", value.get("height"),
            )

        for key, child in value.items():
            walk(child, f"{path}.{key}")

    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk(child, f"{path}[{index}]")

walk(data)
PY
```

如果 ComfyUI 输出 `1024×1024`，Candidate 会被后端拒绝：

```text
candidate rejected:
expected 1024x1536,
received 1024x1024
```

---

# 10. 启动 StagePoster Backend

先编译：

```bash
cd /workspace/poster-engine/backend

go build -o poster-backend ./cmd/server
```

启动：

```bash
mkdir -p /workspace/poster-engine/logs

if [[ -f /workspace/poster-engine/backend.pid ]]; then
  kill "$(cat /workspace/poster-engine/backend.pid)" \
    2>/dev/null || true
fi

BACKEND_PID="$(
  lsof -tiTCP:8080 -sTCP:LISTEN 2>/dev/null \
  | head -n 1
)"

if [[ -n "$BACKEND_PID" ]]; then
  kill "$BACKEND_PID"
fi

sleep 3

cd /workspace/poster-engine/backend

nohup env \
  LISTEN_ADDR=:8080 \
  COMFY_URL=http://127.0.0.1:8188 \
  VLM_URL=http://127.0.0.1:8001 \
  VLM_API_KEY=stageposter-vlm-local \
  VLM_MODEL=stageposter-vlm \
  VLM_AUTO_SLEEP=true \
  VLM_REQUEST_TIMEOUT=5m \
  WORKFLOW_PATH=/workspace/poster-engine/workflows/z_image_poster_v1.json \
  PROMPT_NODE_ID='57:27' \
  SEED_NODE_ID='57:3' \
  DB_PATH=/workspace/persistence/stageposter/data/poster.db \
  STORAGE_ROOT=/workspace/persistence/stageposter/storage/jobs \
  ASSET_STORAGE_ROOT=/workspace/persistence/stageposter/storage/assets \
  POSTER_OUTPUT_ROOT=/workspace/persistence/stageposter/storage/posters \
  WORKFLOW_KEY=poster-text \
  WORKFLOW_VERSION=1.0.0 \
  RECONCILE_INTERVAL=2s \
  ./poster-backend \
  > /workspace/poster-engine/logs/backend.log \
  2>&1 &

echo $! > /workspace/poster-engine/backend.pid

echo "Backend PID=$(cat /workspace/poster-engine/backend.pid)"
```

如果需要开启 API Token：

```bash
POSTER_API_TOKEN=poster-dev-2026
```

然后所有 Backend 请求都需要添加：

```bash
-H "X-Poster-Token: poster-dev-2026"
```

本文后续命令默认不开启 Backend Token。

---

# 11. Backend 健康检查

```bash
curl -sS \
  http://127.0.0.1:8080/health \
  | python3 -m json.tool
```

预期：

```json
{
  "status": "ok",
  "comfy": "connected",
  "database": "connected"
}
```

检查依赖：

```bash
curl -sS \
  http://127.0.0.1:8080/api/system/dependencies \
  | python3 -m json.tool
```

预期：

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
      "sleeping": true,
      "status": "ready",
      "url": "http://127.0.0.1:8001"
    }
  },
  "status": "healthy"
}
```

---

# 12. 完整 Candidate 生成复现流程

## 12.1 创建 Session

```bash
curl -sS \
  -X POST \
  http://127.0.0.1:8080/api/ai/sessions \
  -H "Content-Type: application/json" \
  -d '{}' \
  | tee /tmp/stageposter-session-create.json \
  | python3 -m json.tool
```

提取 Session ID：

```bash
export SESSION_ID="$(
python3 - <<'PY'
import json

with open("/tmp/stageposter-session-create.json") as f:
    print(json.load(f)["sessionId"])
PY
)"

echo "SESSION_ID=$SESSION_ID"
```

## 12.2 发送用户 Brief

```bash
curl --max-time 480 \
  -sS \
  -X POST \
  "http://127.0.0.1:8080/api/ai/sessions/$SESSION_ID/messages" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "我要制作一张音乐节海报。活动名 Abyssal Kingdom Festival，艺人 Maverick，2026-08-21 晚上 20:00，场地 Void Arena。音乐类型是 gothic metal，风格是 dark fantasy editorial，主题是 abyssal gothic kingdom，氛围要 epic、mysterious、ritualistic，颜色以 black、aged ivory、deep red 为主。画面核心是黑色王座和巨大羽翼，要高级、有压迫感，禁止生成文字。"
  }' \
  | tee /tmp/stageposter-session-message.json \
  | python3 -m json.tool
```

这一阶段 Backend 会：

```text
检测 vLLM 正在睡眠
→ POST /wake_up
→ 调用 Qwen
→ 提取结构化 Brief
→ 生成三套 Plan
→ POST /sleep?level=1
```

验证：

```bash
python3 - <<'PY'
import json

with open("/tmp/stageposter-session-message.json") as f:
    data = json.load(f)

session = data["session"]

print("status:", session["status"])
print("missingFields:", session["missingFields"])
print("plans:", len(session.get("plans") or []))

assert session["status"] == "awaiting_plan_selection"
assert not session["missingFields"]
assert len(session["plans"]) == 3

print("BRIEF + PLAN FLOW OK")
PY
```

## 12.3 验证 Qwen 自动睡眠

```bash
curl -sS \
  http://127.0.0.1:8001/is_sleeping \
  -H "Authorization: Bearer stageposter-vlm-local"

echo
rocm-smi --showmeminfo vram
```

预期：

```json
{"is_sleeping":true}
```

## 12.4 提取 Plan ID

```bash
export PLAN_ID="$(
python3 - <<'PY'
import json

with open("/tmp/stageposter-session-message.json") as f:
    data = json.load(f)

print(data["session"]["plans"][0]["planId"])
PY
)"

echo "PLAN_ID=$PLAN_ID"
```

## 12.5 确认 Plan

```bash
curl --max-time 300 \
  -sS \
  -X POST \
  "http://127.0.0.1:8080/api/ai/sessions/$SESSION_ID/plans/$PLAN_ID/confirm" \
  -H "Content-Type: application/json" \
  -d '{}' \
  | tee /tmp/stageposter-plan-confirm.json
```

格式化：

```bash
python3 -m json.tool \
  < /tmp/stageposter-plan-confirm.json
```

预期：

```json
{
  "status": "generating_candidates",
  "posterId": "poster_..."
}
```

提取 Poster ID：

```bash
export POSTER_ID="$(
python3 - <<'PY'
import json

with open("/tmp/stageposter-plan-confirm.json") as f:
    print(json.load(f)["posterId"])
PY
)"

echo "POSTER_ID=$POSTER_ID"
```

## 12.6 轮询 Candidate

```bash
for i in $(seq 1 240); do
  curl -sS \
    "http://127.0.0.1:8080/api/ai/sessions/$SESSION_ID" \
    > /tmp/stageposter-session-status.json

  python3 - <<'PY'
import json

with open("/tmp/stageposter-session-status.json") as f:
    data = json.load(f)

poster = data.get("poster") or {}
candidates = poster.get("candidates") or []

print(
    "session=", data.get("status"),
    "poster=", poster.get("status"),
    "progress=", poster.get("progress"),
    "candidates=",
    [
        (
            candidate.get("status"),
            candidate.get("attempt"),
        )
        for candidate in candidates
    ],
)
PY

  STATUS="$(
    python3 - <<'PY'
import json

with open("/tmp/stageposter-session-status.json") as f:
    print(json.load(f).get("status", ""))
PY
  )"

  case "$STATUS" in
    awaiting_candidate_selection|failed)
      break
      ;;
  esac

  sleep 3
done
```

成功状态：

```text
session=awaiting_candidate_selection
poster=awaiting_selection
progress={completed:3,total:3}
candidates=[
  (ready,1),
  (ready,1),
  (ready,1)
]
```

## 12.7 查看最终 Session

```bash
python3 -m json.tool \
  < /tmp/stageposter-session-status.json
```

预期 Candidate：

```json
{
  "candidateId": "candidate_...",
  "status": "ready",
  "imageUrl": "/api/posters/poster_.../candidates/candidate_.../image"
}
```

---

# 13. 下载候选图

列出 Candidate ID：

```bash
python3 - <<'PY'
import json

with open("/tmp/stageposter-session-status.json") as f:
    data = json.load(f)

for index, candidate in enumerate(
    data["poster"]["candidates"],
    start=1,
):
    print(
        index,
        candidate["candidateId"],
        candidate["variantName"],
        candidate["imageUrl"],
    )
PY
```

下载三张候选图：

```bash
mkdir -p /tmp/stageposter-candidates

python3 - <<'PY'
import json
import subprocess

with open("/tmp/stageposter-session-status.json") as f:
    data = json.load(f)

for index, candidate in enumerate(
    data["poster"]["candidates"],
    start=1,
):
    url = "http://127.0.0.1:8080" + candidate["imageUrl"]
    output = f"/tmp/stageposter-candidates/candidate-{index}.png"

    subprocess.run(
        ["curl", "-sS", url, "-o", output],
        check=True,
    )

    print(output)
PY
```

检查尺寸：

```bash
file /tmp/stageposter-candidates/*.png
```

使用 ImageMagick 时：

```bash
identify /tmp/stageposter-candidates/*.png
```

预期：

```text
1024x1536
```

---

# 14. Candidate 生成后释放 ComfyUI 显存

```bash
curl -sS \
  -X POST \
  http://127.0.0.1:8188/free \
  -H "Content-Type: application/json" \
  -d '{
    "unload_models": true,
    "free_memory": true
  }'

sleep 8

rocm-smi --showmeminfo vram
```

本次实际测试：

```text
ComfyUI /free 后 VRAM Used:
约 1.33 GB
```

这样后续 Qwen Review 可以安全调用：

```text
/wake_up
→ Review
→ /sleep?level=1
```

---

# 15. 显存状态机

## 15.1 Qwen 阶段

```text
初始：
vLLM sleeping
ComfyUI 空闲或已 free
VRAM ≈ 0.7GB 到 1.3GB

Backend 接收用户消息
→ POST vLLM /wake_up
→ Qwen 生成 Brief / Plan
→ POST vLLM /sleep?level=1

结束：
vLLM sleeping=true
VRAM 再次下降
```

## 15.2 ComfyUI 阶段

```text
用户确认 Plan
→ Backend 创建 Poster
→ Worker 提交三次 ComfyUI Workflow
→ Z-Image 依次生成三张 Candidate
→ Session 进入 awaiting_candidate_selection
→ POST ComfyUI /free

结束：
三张 Candidate ready
ComfyUI 权重卸载
VRAM ≈ 1GB
```

## 15.3 Review 阶段

下一阶段预期：

```text
用户选择 Candidate
→ Composer 叠加活动文字与 Logo
→ Backend 调用 vLLM /wake_up
→ Qwen Review 最终海报
→ ACCEPT / RECOMPOSE / REGENERATE
→ Backend 调用 vLLM /sleep?level=1
```

---

# 16. 常见错误

## 16.1 `AI session service is not configured`

原因：

```text
Server 中只注入了部分 AI 依赖
aiClient / aiService / aiRuntime / aiSessionService 不完整
```

推荐使用：

```go
aiConfig := api.NewAIConfigFromEnv()

api.NewServer(...).
    WithAI(aiConfig).
    WithAISessions(aiSessionService)
```

## 16.2 `unauthorized`

Backend 启动时设置了：

```bash
POSTER_API_TOKEN=poster-dev-2026
```

请求需要：

```bash
-H "X-Poster-Token: poster-dev-2026"
```

## 16.3 `POST /api/ai/sessions//plans/...`

原因：

```text
SESSION_ID 为空
```

检查：

```bash
echo "SESSION_ID=$SESSION_ID"
echo "PLAN_ID=$PLAN_ID"
```

## 16.4 `AI session is terminal`

原因：

Session 已经进入：

```text
failed
completed
terminal
```

必须创建新 Session，不能重复 Confirm。

## 16.5 模型 `not in []`

例如：

```text
z_image_turbo_bf16.safetensors not in []
qwen_3_4b.safetensors not in []
```

原因：

ComfyUI 没发现模型。

检查：

```bash
curl -sS http://127.0.0.1:8188/object_info \
  > /tmp/comfy-object-info.json
```

以及模型软链接。

## 16.6 `expected 1024x1536, received 1024x1024`

原因：

Workflow 输出尺寸和 Backend Candidate 合约不一致。

必须设置：

```text
width=1024
height=1536
```

## 16.7 `wake VLM runtime: CUDA Error: out of memory`

检查：

```bash
rocm-smi --showmeminfo vram
rocm-smi --showpids
```

先释放 ComfyUI：

```bash
curl -sS \
  -X POST \
  http://127.0.0.1:8188/free \
  -H "Content-Type: application/json" \
  -d '{
    "unload_models": true,
    "free_memory": true
  }'
```

使用已验证参数：

```text
VLLM_ROCM_SLEEP_MEM_CHUNK_SIZE=64
gpu-memory-utilization=0.65
```

## 16.8 `cumem_allocator.cpp invalid argument`

当前 vLLM Sleep Allocator 已进入异常状态。

停止 vLLM：

```bash
VLLM_PID="$(
  lsof -tiTCP:8001 -sTCP:LISTEN \
  | head -n 1
)"

kill "$VLLM_PID"
```

确认显存释放后，使用稳定参数重新启动。

---

# 17. 官方复现检查表

复现者需要依次确认：

```text
[ ] /workspace 中包含所有持久化模型
[ ] Go Backend 编译成功
[ ] vLLM /v1/models 返回 200
[ ] vLLM 清醒推理成功
[ ] vLLM sleep 后 VRAM 明显下降
[ ] vLLM wake_up 返回 200
[ ] wake 后推理成功
[ ] ComfyUI /system_stats 返回 200
[ ] ComfyUI object_info 能发现三个 Z-Image 模型
[ ] Workflow 输出尺寸为 1024×1536
[ ] Backend /health 返回 ok
[ ] Backend dependencies 返回 healthy
[ ] 创建 Session 成功
[ ] Brief 生成成功
[ ] 三套 Plan 生成成功
[ ] Qwen 自动进入 sleep
[ ] Confirm Plan 成功
[ ] 三张 Candidate 全部 ready
[ ] Candidate 图片尺寸为 1024×1536
[ ] ComfyUI /free 后显存下降
```

---

# 18. 当前已验证结果

本次实际成功结果：

```text
Session:
session_377a7046-5d12-42e2-aad1-0d4d5faa3edd

Poster:
poster_ee608a7a-3ffb-4ee0-b5fd-28ed8e9d8825

Plan:
abyssal-crown-silhouette

Candidate:
3 / 3 ready

Session status:
awaiting_candidate_selection

Poster status:
awaiting_selection

Candidate attempts:
全部为 1

vLLM Sleep:
约 33GB → 729MB

ComfyUI /free:
显存下降至约 1.33GB
```

---

# 19. 当前架构边界

当前流程已经验证：

```text
用户输入
→ Qwen Brief
→ Qwen Plans
→ Plan Confirm
→ Z-Image Candidates
→ Candidate Selection Ready
```

尚待继续验证：

```text
用户选择 Candidate
→ Composer
→ Logo / 文本排版
→ Qwen Visual Review
→ ACCEPT / RECOMPOSE / REGENERATE
→ 最终 Poster
```

另外，当前 Workflow 接收的是：

```text
prompt
negative prompt
seed
```

上传的 `performer` 或 `reference` Asset 可以被 Qwen 看见并影响方案，但尚未作为图像条件直接送入扩散模型。后续需要在 ComfyUI Workflow 中增加 image conditioning 节点。
