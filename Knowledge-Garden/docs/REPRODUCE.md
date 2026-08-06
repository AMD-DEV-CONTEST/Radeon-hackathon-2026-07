# Reproduction Guide — Knowledge Garden

> Step-by-step instructions to reproduce the project from scratch on an AMD
> Radeon GPU (ROCm). Verified on the submission instance: 1× gfx1100,
> 48 GB VRAM, ROCm 7.2.x, Python 3.12.

## One-command reproduction (recommended)

A single script reproduces the whole stack on a **fresh instance** (GPU check →
clone the submission repo → model download → sequential vLLM startup →
backend + web UI → health check):

```bash
# on a brand-new AMD Radeon instance: download the script from the submission
# fork and run it — it clones the repo, downloads models and starts everything
curl -fsSL -o reproduce.sh \
  https://raw.githubusercontent.com/mosyoyo/Radeon-hackathon-2026-07/feature/knowledge-garden/Knowledge-Garden/scripts/reproduce.sh
bash reproduce.sh

# models already downloaded: skip the download step
bash reproduce.sh --skip-models

# optional: custom repo / model directory
bash reproduce.sh --repo=https://github.com/<your-fork>/Radeon-hackathon-2026-07.git
bash reproduce.sh --skip-models --models-dir=/path/to/models
```

The script is idempotent — re-running it detects already-running services and
skips them. It reads `HF_ENDPOINT` (defaults to `https://hf-mirror.com`) and
waits for each vLLM instance to be ready before starting the next (sequential
startup requirement). After it finishes, open `http://127.0.0.1:8510`.

## Step-by-step reproduction

## 0. Prerequisites

- AMD Radeon GPU (gfx1100 tested; any ROCm-supported card with ≥ 40 GB VRAM)
- ROCm 7.2.x with the `rock` kernel module loaded
- Python 3.12 virtual environment with ROCm PyTorch + vLLM (ROCm build)
- ~35 GB free disk for model weights

```bash
# verify the GPU is visible
rocm-smi --showproductname --showmeminfo vram
# should show one AMD Radeon card with ~48 GB VRAM
```

## 1. Download the models

```bash
# dialogue layer (AWQ 4-bit, ~12 GB weights)
# batch extraction layer (AWQ 4-bit, ~19 GB weights)
# embedding model (small)
# place under /persistent/models/
mkdir -p /persistent/models
```

Model directories (from the submission instance):

| Model | Path | Size |
|---|---|---|
| Qwen2.5-14B-Instruct-AWQ | `/persistent/models/Qwen2.5-14B-Instruct-AWQ` | ~12 GB |
| Qwen2.5-32B-Instruct-AWQ | `/persistent/models/Qwen2.5-32B-Instruct-AWQ` | ~19 GB |
| bge-base-en-v1.5 | `/persistent/models/bge-base-en-v1.5` | ~0.4 GB |

## 2. Start vLLM — sequential, order matters

The two instances MUST start in order (14B first, wait until ready, then
32B). Concurrent startup can rarely mis-load the 14B as fp16 (27.7 GB) and
fail on the shared 48 GB card.

```bash
# 1) dialogue layer — wait until :8000 serves /v1/models
bash scripts/start_vllm.sh /persistent/models/Qwen2.5-14B-Instruct-AWQ \
    Qwen2.5-14B-AWQ 8000 0.3 8192
curl http://127.0.0.1:8000/v1/models   # must return the model

# 2) batch extraction layer — only after :8000 is ready
bash scripts/start_vllm.sh /persistent/models/Qwen2.5-32B-Instruct-AWQ \
    Qwen2.5-32B-AWQ 8001 0.5 4096
curl http://127.0.0.1:8001/v1/models   # must return the model
```

## 3. Start the backend

```bash
cd /persistent/learning-companion
/opt/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8510
# startup log line: STARTUP_RECOVERY_OK: requeued=0 drain=accepting worker=started
```

The FastAPI app serves the built web UI at `http://127.0.0.1:8510/` (SPA
fallback) and the JSON API under `/api`.

## 4. Use the app

1. Open `http://127.0.0.1:8510` in a browser.
2. Go to the **Upload** page — drag a `.md`/`.markdown` file into the
   drop zone (only Markdown accepted).
3. The extraction job appears on the processing page; it reaches `verified`
   automatically (no refresh) in ~20-40 s on the 32B model.
4. Open the skill detail page to see verified knowledge units; click
   **View source** to see the original document rendered as Markdown.
5. Start learning (Feynman recall), take the first assessment, then let the
   SM-2 schedule bring due reviews back.

## 5. Run the tests

```bash
# backend unit tests (85)
/opt/venv/bin/python -m unittest discover -s tests

# frontend build
cd web && npm install && npm run build

# Playwright e2e (75 tests, 3 viewports) — needs a seeded disposable stack
bash scripts/bootstrap_disposable_env.sh /tmp/lc-e2e /tmp/lc-e2e/db.sqlite \
    8002 8512 5174 --canonical-root /persistent/learning-companion -- \
    npx playwright test --config web/playwright.config.ts web/e2e/journeys.spec.ts
```

## 6. Benchmark (optional)

```bash
python scripts/bench.py http://127.0.0.1:8000/v1 Qwen2.5-14B-AWQ
python scripts/bench.py http://127.0.0.1:8001/v1 Qwen2.5-32B-AWQ
# warmup 1 + 3 runs, take the median — see docs/PERFORMANCE.md for expected values
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `FT_DIALOGUE_URL` | `http://127.0.0.1:8000/v1` | dialogue model endpoint |
| `FT_BATCH_URL` | `http://127.0.0.1:8001/v1` | batch model endpoint |
| `LC_DB_PATH` | `data/learning.db` | SQLite path override (tests) |
| `LC_DRAIN_STATE_FILE` | `data/drain.state.json` | drain state file |
| `LC_EXTRACT_STUB` | unset | `verify` enables deterministic stub extraction for tests |

## Troubleshooting

- **14B loaded as fp16 / OOM**: restart both vLLM instances sequentially,
  wait for `:8000` readiness before starting `:8001`.
- **WAL deadlock under load**: this was fixed by setting `PRAGMA
  journal_mode=WAL` once per process (module-level) + `busy_timeout=5000`
  on every connection.
- **NFS stalls**: run the SQLite DB on fast local storage; a periodic
  backup script copies it to persistent storage.
