# StagePoster One-Click Deployment Guide

> Goal: Deploy the full StagePoster stack on Ubuntu 24.04 + AMD Radeon PRO W7900 48 GB with a single command.

---

## 1. Verified Environment

| Component | Version / Config |
|---|---|
| OS | Ubuntu 24.04.4 |
| GPU | AMD Radeon PRO W7900 48 GB |
| GPU Architecture | `gfx1100` |
| ROCm | 7.2.1 (HIP 7.2.53211) |
| ComfyUI Python | 3.10.20 |
| ComfyUI Torch | 2.13.0+rocm7.2 |
| vLLM | 0.20.0 |
| vLLM Torch | 2.10.0+git8514f05 |
| Go | 1.25.0 |

---

## 2. Prerequisites

- **ROCm pre-installed**: Cloud images usually include ROCm drivers. Verify
  with `rocm-smi --showproductname`.
- **sudo access**: Required for system dependencies and Go installation.
- **Stable network**: Model files are ~21 GB total.

---

## 3. One-Click Deployment

```bash
cd /workspace/poster-engine

# One-click deploy (system deps, Python envs, models, backend build, service start)
sudo -E bash scripts/install-all.sh
```

The script automatically:
1. Checks/installs system tools
2. Verifies ROCm environment
3. Installs uv, Go 1.25.0, cloudflared
4. Clones ComfyUI (if not present)
5. Creates ComfyUI Python 3.10.20 env + ROCm Torch
6. Creates vLLM Python 3.12 env + ROCm vLLM wheel
7. Downloads Qwen3.5-9B + Z-Image Turbo models (with SHA256 verification)
8. Compiles Go Backend
9. Generates `.env` configuration
10. Starts ComfyUI, vLLM, Backend services
11. Runs health checks

---

## 4. Environment Variables

| Variable | Default | Description |
|---|---|---|
| `STAGEPOSTER_ROOT` | `/workspace/poster-engine` | Project root |
| `COMFY_VENV` | `/workspace/venv` | ComfyUI Python env |
| `VLLM_VENV` | `/workspace/poster-engine/.venv-vllm` | vLLM Python env |
| `VLLM_MODEL_PATH` | `/workspace/poster-engine/models/Qwen3.5-9B` | Qwen model path |
| `SKIP_APT` | `0` | Set `1` to skip apt install |
| `SKIP_COMFY_TORCH` | `0` | Set `1` to skip ComfyUI Torch install |
| `DOWNLOAD_MODELS` | `1` | Set `0` to skip model download |
| `INSTALL_ROCM` | `0` | Set `1` to install ROCm drivers (usually unnecessary) |

---

## 5. Script Architecture

```
scripts/
├── install-all.sh              # One-click deploy entrypoint
├── install-system-deps.sh      # System dependencies
├── install-uv.sh               # uv package manager
├── install-go.sh               # Go 1.25.0
├── install-cloudflared.sh      # Cloudflare Tunnel
├── install-comfyui.sh          # ComfyUI + ROCm Torch
├── install-vllm.sh             # vLLM ROCm environment
├── download-models.sh          # Qwen + Z-Image models
├── build-backend.sh            # Go backend build
├── generate-env.sh             # Generate .env config
├── start-all.sh                # Start all services
├── stop-all.sh                 # Stop all services
├── status.sh                   # Service status
├── smoke-test.sh               # Smoke test
└── start-dev-tunnel.sh         # Dev tunnel
```

---

## 6. Service Management

```bash
# Start all services
./scripts/start-all.sh

# Check status
./scripts/status.sh

# Stop all services
./scripts/stop-all.sh

# Smoke test
./scripts/smoke-test.sh

# Dev tunnel
./scripts/start-dev-tunnel.sh
```

---

## 7. Verification Checklist

- [ ] `rocm-smi --showproductname` shows W7900
- [ ] `rocminfo | grep gfx` shows `gfx1100`
- [ ] ComfyUI: `curl http://127.0.0.1:8188/system_stats` returns 200
- [ ] vLLM: `curl http://127.0.0.1:8001/v1/models` returns 200
- [ ] Backend: `curl http://127.0.0.1:8080/health` returns `{"status":"ok"}`
- [ ] Model files SHA256 checksums verified
- [ ] `./scripts/smoke-test.sh` all pass
- [ ] Full E2E: 3 candidates → select → compose → review → final passes

### E2E Smoke Test

```bash
cd /workspace/poster-engine/backend

# 1. Start all services
./scripts/start-all.sh

# 2. Check status
./scripts/status.sh

# 3. Run smoke test (check HTTP reachability)
./scripts/smoke-test.sh

# 4. Full E2E poster pipeline test
set -Eeuo pipefail
BASE_URL="http://127.0.0.1:8080"
SMOKE_DIR=$(mktemp -d /tmp/stageposter-e2e-XXXXXXXX)

# Create Session
SESSION_ID=$(curl -fsS -X POST "$BASE_URL/api/ai/sessions" \
  -H 'Content-Type: application/json' \
  -d '{"brief":{"event":{"title":"Test Event","artist":"Test","date":"2026-08-21","time":"20:00","venue":"Venue","presalePrice":"$45","doorPrice":"$60"},"branding":{},"visual":{"style":"dark fantasy editorial","theme":"test","musicGenre":"metal","mood":["epic"],"preferredColors":["black","red"]}}}' \
  | jq -r '.sessionId')

# Generate design plans
PLAN_ID=$(curl -fsS -X POST "$BASE_URL/api/ai/sessions/$SESSION_ID/messages" \
  -H 'Content-Type: application/json' \
  -d '{"content":"confirm start design"}' \
  | jq -r '.session.plans[0].planId')

# Confirm plan
POSTER_ID=$(curl -fsS -X POST "$BASE_URL/api/ai/sessions/$SESSION_ID/plans/$PLAN_ID/confirm" \
  -H 'Content-Type: application/json' -d '{}' \
  | jq -r '.posterId')

# Wait for candidates (polling)
while true; do
  STATUS=$(curl -fsS "$BASE_URL/api/ai/sessions/$SESSION_ID" | jq -r '.status')
  [[ "$STATUS" == "awaiting_candidate_selection" ]] && break
  [[ "$STATUS" =~ ^(failed|canceled)$ ]] && { echo "FAILED: $STATUS"; exit 1; }
  sleep 10
done

# Select candidate
CANDIDATE_ID=$(curl -fsS "$BASE_URL/api/ai/sessions/$SESSION_ID" \
  | jq -r '.poster.candidates[] | select(.status=="ready") | .candidateId' | head -1)

curl -fsS -X POST "$BASE_URL/api/ai/sessions/$SESSION_ID/candidates/$CANDIDATE_ID/select" \
  -H 'Content-Type: application/json' -d '{}'

# Finalize
FINAL_STATUS=$(curl -fsS -X POST "$BASE_URL/api/ai/sessions/$SESSION_ID/finalize" \
  -H 'Content-Type: application/json' -d '{}' \
  | jq -r '.status')

[[ "$FINAL_STATUS" =~ ^(succeeded|completed_with_warnings)$ ]] || { echo "FAILED: $FINAL_STATUS"; exit 1; }

# Download final poster
RESULT_URL=$(curl -fsS "$BASE_URL/api/ai/sessions/$SESSION_ID" | jq -r '.poster.resultUrl')
curl -fsSL "$BASE_URL$RESULT_URL" -o "$SMOKE_DIR/final-poster.png"

echo "E2E PASSED: $SMOKE_DIR"
```

---

## 8. Troubleshooting

| Problem | Solution |
|---|---|
| ROCm not installed | Use AMD ROCm image, or `INSTALL_ROCM=1` |
| vLLM import fails | Remove `.venv-vllm`, re-run scripts |
| Model download fails | Check network, or manually place models |
| Go version mismatch | Script auto-installs Go 1.25.0 |
| Port occupied | `./scripts/stop-all.sh` then retry |
