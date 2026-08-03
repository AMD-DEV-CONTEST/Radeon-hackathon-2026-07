# StagePoster Single-GPU Inference — Reproduction Guide

## Goal

Reproduce the core StagePoster pipeline on a single AMD GPU server:

```
Create AI Session
  → Qwen understands user Brief
  → Generate 3 Design Plans
  → Confirm Plan
  → Z-Image Turbo generates 3 Candidates
  → Return candidate image URLs
```

Verified environment: single AMD GPU with ~48 GB VRAM, running:
- StagePoster Go Backend
- vLLM + Qwen3.5-9B
- ComfyUI + Z-Image Turbo

Because Qwen and Z-Image cannot stably coexist in VRAM simultaneously, the
system uses a GPU memory relay mechanism:

```
Qwen phase
  → Backend calls vLLM /wake_up
  → Brief / Plan / Review
  → Backend calls vLLM /sleep?level=1
  → Qwen VRAM released

ComfyUI phase
  → Load Z-Image
  → Generate Candidates
  → POST /free
  → Unload models and release VRAM
```

---

## 1. Verified Environment

```text
OS: Ubuntu Linux
GPU: AMD Radeon GPU, ~48 GB VRAM
ROCm: 7.2 series
Python (ComfyUI): 3.10.20
Python (vLLM): 3.12 virtual environment
vLLM: 0.20.0
ComfyUI: 0.28.0
Go: 1.25.0
Backend port: 8080
ComfyUI port: 8188
vLLM port: 8001
```

Models:

```text
Qwen: /workspace/poster-engine/models/Qwen3.5-9B

Z-Image Turbo:
  z_image_turbo_bf16.safetensors
  qwen_3_4b.safetensors
  ae.safetensors
```

**Important:** All persistent content should be placed under `/workspace`.
Do not use `/models`, `/root`, or other temporary mount directories that may
be cleared on instance restart.

Project root:

```text
/workspace/poster-engine
```

---

## 2. Recommended Directory Structure

```text
/workspace/poster-engine/
├── backend/
│   ├── poster-backend
│   ├── data/
│   ├── storage/
│   └── logs/
├── ComfyUI/
│   ├── main.py
│   └── models/
│       ├── diffusion_models/
│       ├── text_encoders/
│       ├── vae/
│       └── loras/
├── models/
│   ├── Qwen3.5-9B/
│   └── poster/
│       ├── diffusion_models/
│       ├── text_encoders/
│       ├── vae/
│       └── loras/
├── workflows/
│   └── z_image_poster_v1.json
├── logs/
│   ├── backend.log
│   ├── comfyui/server.log
│   └── vllm/server.log
├── venv/
├── .venv-vllm/
├── backend.pid
├── comfyui.pid
└── vllm.pid
```

---

## 3. Core Ports

| Service | Address | Purpose |
|---|---|---|
| Backend | `127.0.0.1:8080` | StagePoster API |
| ComfyUI | `127.0.0.1:8188` | Z-Image inference |
| vLLM | `127.0.0.1:8001` | Qwen inference |

Check listeners:

```bash
lsof -iTCP:8080 -sTCP:LISTEN
lsof -iTCP:8188 -sTCP:LISTEN
lsof -iTCP:8001 -sTCP:LISTEN
```

Or with `iproute2`:

```bash
ss -ltnp | grep -E ':8080|:8188|:8001'
```

---

## 4. Starting vLLM

> **⚠️ Superseded — do not copy the sleep-mode flags below.**
>
> This section records what was verified at the time of the original bring-up.
> `--enable-sleep-mode` was later found to break generation on **ROCm 7.2 +
> vLLM 0.20.0**: after the first sleep→wake cycle, every subsequent request
> fails with `CUDA Error: invalid argument`.
>
> The production launcher (`scripts/start-all.sh`) therefore **no longer enables
> sleep mode and never requests sleep** — it logs
> `VLM resident (sleep mode disabled on ROCm)`. VRAM is reclaimed instead by the
> Go runtime coordinator calling `ReleaseComfyMemory` to unload ComfyUI models
> before a VLM call.
>
> Two flags must also be added that this section predates:
> - `--mm-processor-cache-gb 0` — the 4 GB default self-corrupts after uptime,
>   after which every image-bearing request 500s with
>   `AssertionError: Expected a cached item for mm_hash=...`
> - keep `VLLM_SERVER_DEV_MODE=1` **private**; it exposes unauthenticated admin
>   endpoints on 8001.
>
> Use `scripts/start-all.sh` rather than the command below.

### 4.1 Stable Parameters

Verified parameters for a stable sleep → wake → inference cycle *at the time of
bring-up* (see the warning above — the sleep flag is no longer used):

```text
VLLM_ROCM_SLEEP_MEM_CHUNK_SIZE=64
--gpu-memory-utilization 0.65
--enable-sleep-mode           # ← superseded, breaks generation on ROCm 7.2
```

Parameters that previously caused OOM or `cumem_allocator.cpp invalid argument`:

```text
--gpu-memory-utilization 0.90
VLLM_ROCM_SLEEP_MEM_CHUNK_SIZE=128
```

### 4.2 Startup Command

Historical record. The current equivalent is `scripts/start-all.sh`, which drops
`--enable-sleep-mode` and adds `--mm-processor-cache-gb 0`.

```bash
cd /workspace/poster-engine

mkdir -p logs/vllm

if [[ -f vllm.pid ]]; then
  kill "$(cat vllm.pid)" 2>/dev/null || true
fi

VLLM_PID="$(lsof -tiTCP:8001 -sTCP:LISTEN 2>/dev/null | head -n 1)"
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
  > /workspace/poster-engine/logs/vllm/server.log 2>&1 &

echo $! > /workspace/poster-engine/vllm.pid
echo "vLLM PID=$(cat /workspace/poster-engine/vllm.pid)"
```


### 4.3 Wait for vLLM Ready

```bash
for i in $(seq 1 180); do
  CODE="$(
    curl --max-time 5 -sS \
      -o /tmp/vllm-models.json \
      -w '%{http_code}' \
      http://127.0.0.1:8001/v1/models \
      -H "Authorization: Bearer stageposter-vlm-local" \
      2>/dev/null || true
  )"
  [[ "$CODE" == "200" ]] && echo "vLLM ready" && break
  printf '.'
  sleep 2
done
echo
tail -80 /workspace/poster-engine/logs/vllm/server.log
```

---

## 5. Verifying vLLM Sleep/Wake Cycle

### 5.1 Inference While Awake

```bash
curl --max-time 180 -sS -X POST \
  http://127.0.0.1:8001/v1/chat/completions \
  -H "Authorization: Bearer stageposter-vlm-local" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "stageposter-vlm",
    "messages": [{"role": "user", "content": "Reply with AWAKE"}],
    "temperature": 0,
    "max_tokens": 8
  }' | python3 -m json.tool
```

Expected: `"content": "AWAKE"`

### 5.2 Enter Sleep

```bash
curl --max-time 180 -sS -X POST \
  "http://127.0.0.1:8001/sleep?level=1" \
  -H "Authorization: Bearer stageposter-vlm-local"

sleep 8

curl -sS http://127.0.0.1:8001/is_sleeping \
  -H "Authorization: Bearer stageposter-vlm-local"
rocm-smi --showmeminfo vram
```

Expected: `is_sleeping: true`, VRAM ~729 MB

### 5.3 Wake Up

```bash
curl --max-time 300 -sS \
  -D /tmp/vllm-wake.headers \
  -o /tmp/vllm-wake.body \
  -w '\nHTTP_STATUS=%{http_code}\n' \
  -X POST http://127.0.0.1:8001/wake_up \
  -H "Authorization: Bearer stageposter-vlm-local"
```

Expected: `HTTP_STATUS=200`, VRAM ~33 GB after wake

### 5.4 Inference After Wake

```bash
curl --max-time 180 -sS -X POST \
  http://127.0.0.1:8001/v1/chat/completions \
  -H "Authorization: Bearer stageposter-vlm-local" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "stageposter-vlm",
    "messages": [{"role": "user", "content": "Reply with WOKE"}],
    "temperature": 0,
    "max_tokens": 8
  }' | python3 -m json.tool
```

Expected: `"content": "WOKE"`

---

## 6. Starting ComfyUI

Before starting ComfyUI, verify vLLM is sleeping:

```bash
curl -sS http://127.0.0.1:8001/is_sleeping \
  -H "Authorization: Bearer stageposter-vlm-local"
# Expected: {"is_sleeping":true}
```

Start ComfyUI:

```bash
cd /workspace/poster-engine/ComfyUI

mkdir -p /workspace/poster-engine/logs/comfyui

if [[ -f /workspace/poster-engine/comfyui.pid ]]; then
  kill "$(cat /workspace/poster-engine/comfyui.pid)" 2>/dev/null || true
fi

COMFY_PID="$(lsof -tiTCP:8188 -sTCP:LISTEN 2>/dev/null | head -n 1)"
if [[ -n "$COMFY_PID" ]]; then
  kill "$COMFY_PID"
fi

sleep 3

nohup /workspace/poster-engine/venv/bin/python \
  main.py --listen 0.0.0.0 --port 8188 \
  > /workspace/poster-engine/logs/comfyui/server.log 2>&1 &

echo $! > /workspace/poster-engine/comfyui.pid
echo "ComfyUI PID=$(cat /workspace/poster-engine/comfyui.pid)"
```

Wait for ready:

```bash
for i in $(seq 1 120); do
  CODE="$(
    curl --max-time 3 -sS \
      -o /tmp/comfy-system.json \
      -w '%{http_code}' \
      http://127.0.0.1:8188/system_stats \
      2>/dev/null || true
  )"
  [[ "$CODE" == "200" ]] && echo "ComfyUI ready" && break
  printf '.'
  sleep 2
done
echo
tail -80 /workspace/poster-engine/logs/comfyui/server.log
```

---

## 7. Verifying ComfyUI Models

```bash
curl -sS http://127.0.0.1:8188/object_info > /tmp/comfy-object-info.json

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

Required models:

```text
UNETLoader:
  z_image_turbo_bf16.safetensors

CLIPLoader:
  qwen_3_4b.safetensors

VAELoader:
  ae.safetensors
```

---

## 8. Verifying Workflow Dimensions

StagePoster Candidate contract requires:

```text
width  = 1024
height = 1536
```

Check:

```bash
python3 - <<'PY'
import json

path = "/workspace/poster-engine/workflows/z_image_poster_v1.json"

with open(path) as f:
    data = json.load(f)

def walk(value, path="root"):
    if isinstance(value, dict):
        if "width" in value or "height" in value:
            print(path, "width=", value.get("width"), "height=", value.get("height"))
        for key, child in value.items():
            walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk(child, f"{path}[{index}]")

walk(data)
PY
```

If ComfyUI outputs `1024×1024`, the candidate will be rejected by the backend:

```text
candidate rejected: expected 1024x1536, received 1024x1024
```

---

## 9. Starting StagePoster Backend

### 9.1 Build

```bash
cd /workspace/poster-engine/backend

go build -o poster-backend ./cmd/server
```

### 9.2 Start

```bash
mkdir -p /workspace/poster-engine/logs

if [[ -f /workspace/poster-engine/backend.pid ]]; then
  kill "$(cat /workspace/poster-engine/backend.pid)" 2>/dev/null || true
fi

BACKEND_PID="$(lsof -tiTCP:8080 -sTCP:LISTEN 2>/dev/null | head -n 1)"
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
  > /workspace/poster-engine/logs/backend.log 2>&1 &

echo $! > /workspace/poster-engine/backend.pid
echo "Backend PID=$(cat /workspace/poster-engine/backend.pid)"
```

To enable API token:

```bash
POSTER_API_TOKEN=poster-dev-2026
```

Then all requests need:

```bash
-H "X-Poster-Token: poster-dev-2026"
```

Subsequent commands in this guide assume token auth is disabled.

### 9.3 Health Check

```bash
curl -sS http://127.0.0.1:8080/health | python3 -m json.tool
```

Expected:

```json
{
  "status": "ok",
  "comfy": "connected",
  "database": "connected"
}
```

Check dependencies:

```bash
curl -sS http://127.0.0.1:8080/api/system/dependencies | python3 -m json.tool
```

Expected:

```json
{
  "dependencies": {
    "comfyui": { "status": "ready" },
    "database": { "status": "ready" },
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

## 10. Full Candidate Generation Reproduction

### 10.1 Create Session

```bash
curl -sS -X POST http://127.0.0.1:8080/api/ai/sessions \
  -H "Content-Type: application/json" \
  -d '{}' | tee /tmp/stageposter-session-create.json | python3 -m json.tool

export SESSION_ID="$(
  python3 -c "import json; print(json.load(open('/tmp/stageposter-session-create.json'))['sessionId'])"
)"
echo "SESSION_ID=$SESSION_ID"
```

### 10.2 Send User Brief

```bash
curl --max-time 480 -sS -X POST \
  "http://127.0.0.1:8080/api/ai/sessions/$SESSION_ID/messages" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "I want to create a music festival poster. Event: Abyssal Kingdom Festival, artist: Maverick, date: 2026-08-21 at 20:00, venue: Void Arena. Genre: gothic metal. Style: dark fantasy editorial. Theme: abyssal gothic kingdom. Mood: epic, mysterious, ritualistic. Colors: black, aged ivory, deep red. Core imagery: black throne with massive wings. Premium, oppressive feel. NO TEXT in the image."
  }' | tee /tmp/stageposter-session-message.json | python3 -m json.tool
```

During this phase, the backend:

```text
Detects vLLM is sleeping
  → POST /wake_up
  → Call Qwen
  → Extract structured Brief
  → Generate 3 Plans
  → POST /sleep?level=1
```

Verify:

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

### 10.3 Verify Qwen Auto-Sleep

```bash
curl -sS http://127.0.0.1:8001/is_sleeping \
  -H "Authorization: Bearer stageposter-vlm-local"
echo
rocm-smi --showmeminfo vram
```

Expected: `is_sleeping: true`

### 10.4 Extract Plan ID

```bash
export PLAN_ID="$(
  python3 -c "import json; print(json.load(open('/tmp/stageposter-session-message.json'))['session']['plans'][0]['planId'])"
)"
echo "PLAN_ID=$PLAN_ID"
```

### 10.5 Confirm Plan

```bash
curl --max-time 300 -sS -X POST \
  "http://127.0.0.1:8080/api/ai/sessions/$SESSION_ID/plans/$PLAN_ID/confirm" \
  -H "Content-Type: application/json" \
  -d '{}' | tee /tmp/stageposter-plan-confirm.json

python3 -m json.tool < /tmp/stageposter-plan-confirm.json
```

Expected:

```json
{
  "status": "generating_candidates",
  "posterId": "poster_..."
}
```

Extract Poster ID:

```bash
export POSTER_ID="$(
  python3 -c "import json; print(json.load(open('/tmp/stageposter-plan-confirm.json'))['posterId'])"
)"
echo "POSTER_ID=$POSTER_ID"
```

### 10.6 Poll for Candidates

```bash
for i in $(seq 1 240); do
  curl -sS "http://127.0.0.1:8080/api/ai/sessions/$SESSION_ID" \
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
        (c.get("status"), c.get("attempt"))
        for c in candidates
    ],
)
PY

  STATUS="$(python3 -c "import json; print(json.load(open('/tmp/stageposter-session-status.json')).get('status',''))")"

  case "$STATUS" in
    awaiting_candidate_selection|failed) break ;;
  esac

  sleep 3
done
```

Expected result:

```text
session=awaiting_candidate_selection
poster=awaiting_selection
progress={completed:3,total:3}
candidates=[(ready,1), (ready,1), (ready,1)]
```

### 10.7 View Final Session

```bash
python3 -m json.tool < /tmp/stageposter-session-status.json
```

Expected candidate:

```json
{
  "candidateId": "candidate_...",
  "status": "ready",
  "imageUrl": "/api/posters/poster_.../candidates/candidate_.../image"
}
```

### 10.8 Download Candidates

```bash
mkdir -p /tmp/stageposter-candidates

python3 - <<'PY'
import json
import subprocess

with open("/tmp/stageposter-session-status.json") as f:
    data = json.load(f)

for index, candidate in enumerate(
    data["poster"]["candidates"], start=1
):
    url = "http://127.0.0.1:8080" + candidate["imageUrl"]
    output = f"/tmp/stageposter-candidates/candidate-{index}.png"
    subprocess.run(["curl", "-sS", url, "-o", output], check=True)
    print(output)
PY
```

Check dimensions:

```bash
file /tmp/stageposter-candidates/*.png
# Expected: 1024x1536
```

---

## 11. Releasing ComfyUI VRAM After Candidates

```bash
curl -sS -X POST http://127.0.0.1:8188/free \
  -H "Content-Type: application/json" \
  -d '{"unload_models": true, "free_memory": true}'

sleep 8
rocm-smi --showmeminfo vram
```

After `/free`, VRAM drops to ~1.33 GB. This frees memory for the Qwen Review
phase:

```text
/wake_up
  → Review
  → /sleep?level=1
```

---

## 12. VRAM State Machine

### 12.1 Qwen Phase

```text
Initial:
  vLLM sleeping
  ComfyUI idle or freed
  VRAM ≈ 0.7–1.3 GB

Backend receives user message
  → POST vLLM /wake_up
  → Qwen generates Brief / Plan
  → POST vLLM /sleep?level=1

End state:
  vLLM sleeping=true
  VRAM drops again
```

### 12.2 ComfyUI Phase

```text
User confirms Plan
  → Backend creates Poster
  → Worker submits 3 ComfyUI Workflows
  → Z-Image generates 3 Candidates sequentially
  → Session enters awaiting_candidate_selection
  → POST ComfyUI /free

End state:
  3 Candidates ready
  ComfyUI weights unloaded
  VRAM ≈ 1 GB
```

### 12.3 Review Phase

```text
User selects Candidate
  → Composer overlays event text and Logo
  → Backend calls vLLM /wake_up
  → Qwen reviews final poster
  → ACCEPT / RECOMPOSE / REGENERATE
  → Backend calls vLLM /sleep?level=1
```

---

## 13. Common Errors

### 13.1 `AI session service is not configured`

Cause: Server only injected partial AI dependencies. `aiClient`, `aiService`,
`aiRuntime`, `aiSessionService` are incomplete.

Fix:

```go
aiConfig := api.NewAIConfigFromEnv()

api.NewServer(...).
    WithAI(aiConfig).
    WithAISessions(aiSessionService)
```

### 13.2 `unauthorized`

Backend was started with `POSTER_API_TOKEN=poster-dev-2026`. Add the header:

```bash
-H "X-Poster-Token: poster-dev-2026"
```

### 13.3 `POST /api/ai/sessions//plans/...`

Cause: `SESSION_ID` is empty.

Check:

```bash
echo "SESSION_ID=$SESSION_ID"
echo "PLAN_ID=$PLAN_ID"
```

### 13.4 `AI session is terminal`

The session is already in `failed`, `completed`, or `terminal` state. Create a
new session. Do not re-confirm an old plan.

### 13.5 Model `not in []`

Example:

```text
z_image_turbo_bf16.safetensors not in []
qwen_3_4b.safetensors not in []
```

Cause: ComfyUI cannot find the models.

Check:

```bash
curl -sS http://127.0.0.1:8188/object_info > /tmp/comfy-object-info.json
```

Also verify model symlinks.

### 13.6 `expected 1024x1536, received 1024x1024`

Cause: Workflow output dimensions don't match the backend Candidate contract.

Must set:

```text
width=1024
height=1536
```

### 13.7 `wake VLM runtime: CUDA Error: out of memory`

Check:

```bash
rocm-smi --showmeminfo vram
rocm-smi --showpids
```

Free ComfyUI first:

```bash
curl -sS -X POST http://127.0.0.1:8188/free \
  -H "Content-Type: application/json" \
  -d '{"unload_models": true, "free_memory": true}'
```

Use verified parameters:

```text
VLLM_ROCM_SLEEP_MEM_CHUNK_SIZE=64
gpu-memory-utilization=0.65
```

### 13.8 `cumem_allocator.cpp invalid argument`

The vLLM Sleep Allocator is in an abnormal state. Stop vLLM, confirm VRAM is
released, and restart with stable parameters:

```bash
VLLM_PID="$(lsof -tiTCP:8001 -sTCP:LISTEN | head -n 1)"
kill "$VLLM_PID"
```

---

## 14. Reproduction Checklist

Reproducers must confirm each step in order:

```text
[ ] /workspace contains all persistent models
[ ] Go Backend compiles successfully
[ ] vLLM /v1/models returns 200
[ ] vLLM awake inference succeeds
[ ] vLLM VRAM drops after sleep
[ ] vLLM /wake_up returns 200
[ ] Inference succeeds after wake
[ ] ComfyUI /system_stats returns 200
[ ] ComfyUI object_info shows all 3 Z-Image models
[ ] Workflow output dimensions are 1024×1536
[ ] Backend /health returns ok
[ ] Backend /api/system/dependencies returns healthy
[ ] Create Session succeeds
[ ] Brief generation succeeds
[ ] 3 Design Plans generated
[ ] Qwen auto-enters sleep
[ ] Confirm Plan succeeds
[ ] All 3 Candidates ready
[ ] Candidate images are 1024×1536
[ ] ComfyUI /free reduces VRAM
```

---

## 15. Verified Results

Successful reproduction:

```text
Session:  session_377a7046-5d12-42e2-aad1-0d4d5faa3edd
Poster:   poster_ee608a7a-3ffb-4ee0-b5fd-28ed8e9d8825
Plan:     abyssal-crown-silhouette
Candidates: 3 / 3 ready
Session status: awaiting_candidate_selection
Poster status: awaiting_selection
Candidate attempts: all 1
vLLM Sleep: ~33 GB → 729 MB
ComfyUI /free: VRAM drops to ~1.33 GB
```

---

## 16. Current Architecture Boundaries

**Verified:**

```text
User input
  → Qwen Brief
  → Qwen Plans
  → Plan Confirm
  → Z-Image Candidates
  → Candidate Selection Ready
```

**Pending verification:**

```text
User selects Candidate
  → Composer
  → Logo / Text composition
  → Qwen Visual Review
  → ACCEPT / RECOMPOSE / REGENERATE
  → Final Poster
```

The current Workflow receives:

```text
prompt
negative prompt
seed
```

Uploaded `performer` or `reference` Assets can be seen by Qwen and influence
plans, but are not yet passed as image conditioning to the diffusion model.
Future work: add image conditioning nodes to the ComfyUI Workflow.
