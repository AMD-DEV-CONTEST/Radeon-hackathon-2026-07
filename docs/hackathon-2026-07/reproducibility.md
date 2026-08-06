# BotverseX — Reproducibility Instructions

How to run BotverseX (web + api + realtime) from source, step by step.

## Prerequisites

| Component | Requirement |
|---|---|
| Node.js | ≥ 20 (web frontend) |
| Python | 3.11+ (api / realtime, separate venvs) |
| Linux serial | user in `dialout` group for serial robots (`sudo usermod -aG dialout $USER`) |
| Optional (AMD GPU) | ROCm-compatible AMD Radeon GPU; `torch 2.10.0+rocm7.0` (see §4) |

## Option A — Docker (recommended, fastest)

```bash
# from repository root
docker compose -f infra/docker/docker-compose.prod.yml up -d --build
# web:  http://localhost     (nginx on :80)
# api:  http://localhost:8000/docs
# realtime: http://localhost:8002/api/setup/health
```

Containers built: `web` (Node 22 → vite build → nginx), `api` (FastAPI),
`realtime` (FastAPI + WebSocket + PyTorch CPU runtime; swap to ROCm wheels on AMD hosts).

## Option B — Local dev (three terminals)

First-time dependency install:

```bash
cd apps/api && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cd ../realtime && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cd ../web && npm install
```

Run:

```bash
# terminal 1 — API
cd apps/api && source .venv/bin/activate && uvicorn app.main:app --port 8000 --app-dir .

# terminal 2 — Realtime
cd apps/realtime && source .venv/bin/activate && python run_api.py

# terminal 3 — Web
cd apps/web && npm run dev -- --host 0.0.0.0
```

Or one-shot: `bash scripts/dev-all.sh up` (frontend at http://127.0.0.1:5173).

## Registering an account & first steps

1. Open the web UI → `/register` → create an account (JWT auth, localStorage token).
2. Open the Dashboard: dataset stats, training tasks, models come from `/api/v1/*`.
3. Robots page: pick a runtime. For **SO-101** with a USB-serial adapter, open the
   browser-direct panel → `navigator.serial` → select the port (Feetech STS3215,
   1,000,000 baud) → servos are scanned → wave button → the 3D twin follows → Record
   → parquet dataset saved (see `apps/realtime/datasets/recording_<id>/`).
4. Training page: `Probe local device` calls `/api/remote_compute/device` (isolated
   subprocess torch probe → reports ROCm/CUDA/CPU truthfully).

## AMD Radeon / ROCm setup (local training)

```bash
source apps/realtime/rocm_env.sh        # ROCm env vars + venv activation
# verified stack: torch 2.10.0+rocm7.0 · torchvision 0.25.0+rocm7.0 ·
#                 pytorch-triton-rocm 3.5.1 (Strix Halo gfx1151, 64 GB unified memory)
```

Training scripts (MLP / Vision-MLP / SmolVLA) use standard `torch.cuda` paths,
which ROCm maps to the Radeon GPU.

## Smoke checks

```bash
curl -s http://localhost:8002/api/setup/health                    # realtime alive
curl -s -X POST http://localhost:8002/api/datasets/record \
  -H 'Content-Type: application/json' -d '{"frames":[]}'          # → 400, empty frames
curl -s http://localhost:8002/api/remote_compute/device           # GPU probe JSON
node scripts/webserial-protocol-smoke.mjs                         # 34/34 protocol assertions
```

## Dependency specification

- `apps/api/requirements.txt`, `apps/realtime/requirements.txt` (Python)
- `apps/web/package.json` + `package-lock.json` (npm, registry mirror configurable)
- `packages/botclaw-spec/` — contract schemas (JSON Schema ↔ TS ↔ Python)

## Live deployment

The production stack runs at https://botversex.feispace.me (web nginx → api :8000 /
realtime :8002), deployed from this same repository via `docker compose ... up -d --build
web realtime` (tar-pipe sync; see `docs/deploy-readiness.md`).
