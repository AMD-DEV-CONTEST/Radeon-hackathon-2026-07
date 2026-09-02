# Deployment Guide

> Scope: the single-GPU instance this project actually runs on. Paths below are
> real, verified values, not placeholders.

## 1. Current Deployment

| Item | Value |
|---|---|
| OS | Ubuntu 24.04 |
| GPU | AMD Radeon PRO W7900 48 GB, `gfx1100` |
| GPU stack | ROCm 7.2.1 + HIP |
| Database | SQLite (`modernc.org/sqlite`, no CGO) |
| Storage | Local filesystem under `/workspace/persistence` |
| Public ingress | Cloudflare Quick Tunnel |

### Process layout

| Service | Port | PID file | Log |
|---|---|---|---|
| vLLM (Qwen3.5-9B) | `8001` | `backend/run/vllm.pid` | `backend/logs/vllm.log` |
| ComfyUI (Z-Image Turbo) | `8188` | `backend/run/comfyui.pid` | `backend/logs/comfyui.log` |
| Go backend | `8080` | `backend/run/backend.pid` | `backend/logs/backend.log` |
| cloudflared | — | `backend/run/cloudflared.pid` | `backend/logs/cloudflared.log` |

Only the Go backend is reachable from the browser. ComfyUI and vLLM are
internal. **Never expose 8001 or 8188 publicly** — vLLM runs with
`VLLM_SERVER_DEV_MODE=1`, which exposes unauthenticated admin endpoints.

## 2. Environment File

The live config is at the **project root**, not under `backend/`:

```
/workspace/poster-engine/.env
```

`scripts/start-all.sh` resolves it as: `backend/.env` if present, otherwise
`.env` at the project root. On this machine `backend/.env` does not exist, so
the project-root file is authoritative.

> **Do not create `backend/.env`.** It takes precedence in the resolution order,
> so an accidental copy there silently shadows the real config. The recovery
> script used to do exactly this; see §6.

Key paths it defines — all four point into the persistence directory:

```bash
DB_PATH            = /workspace/persistence/stageposter/data/poster.db
STORAGE_ROOT       = /workspace/persistence/stageposter/storage/jobs
ASSET_STORAGE_ROOT = /workspace/persistence/stageposter/storage/assets
POSTER_OUTPUT_ROOT = /workspace/persistence/stageposter/storage/posters

COMFY_VENV = /workspace/venv                             # note: outside the project
VLLM_VENV  = /workspace/poster-engine/.venv-vllm
```

> `backend/data/poster.db` is a **stale leftover**, not the live database. It is
> still on disk and it is still what the documented `DB_PATH` *default* resolves
> to. Reading it yields data that looks plausible but is days old. The only
> source of truth is `DB_PATH` in `.env`.

> **`COMFY_VENV` is `/workspace/venv`** — outside the project tree. Scripts that
> assume `$PROJECT_ROOT/venv` are wrong. This bit both instance-kill scripts.

### The backend binary does not read `.env`

`start-all.sh` does `set -a; source "$ENV_FILE"; set +a` before exec'ing the
binary. Running `./poster-backend` by hand silently starts with **all defaults**
— wrong database, wrong storage roots. Always start through the script, or
source the env file yourself first.

## 3. Build

```bash
cd /workspace/poster-engine/backend
go mod download
go test ./...
go build -o poster-backend ./cmd/server
```

## 4. Start and Verify

```bash
cd /workspace/poster-engine
./scripts/start-all.sh      # vLLM → ComfyUI → backend → health checks
./scripts/status.sh
./scripts/smoke-test.sh
./scripts/start-dev-tunnel.sh
```

Full route regression (30 routes, 127 assertions):

```bash
.venv-vllm/bin/python scripts/e2e-test.py all
```

> Use **that interpreter**, not bare `python3`. The script needs Pillow to
> synthesize test images and only `.venv-vllm` has it. System `python3` fails
> with `ModuleNotFoundError: No module named 'PIL'` before running a single
> assertion.

### vLLM is started resident, NOT sleeping

Earlier revisions of this guide said "put vLLM into sleep mode" as step 2 of
startup. **That is wrong and will break the instance.** On ROCm 7.2 + vLLM
0.20.0, `--enable-sleep-mode` makes every subsequent generation fail with
`CUDA Error: invalid argument`. `start-all.sh:141` deliberately no longer
requests sleep, and logs `VLM resident (sleep mode disabled on ROCm)`.

GPU pressure is instead managed by the Go runtime coordinator, which calls
`ReleaseComfyMemory` to unload ComfyUI models before a VLM call.

### `--mm-processor-cache-gb 0` is required

vLLM's multimodal processor cache (default 4 GB) self-corrupts after uptime:
every image-bearing request starts returning 500 with
`AssertionError: Expected a cached item for mm_hash=...` while text-only
requests keep working. It reads like a backend bug and is not. `start-all.sh`
passes `0`.

## 5. Stop and Restart

```bash
./scripts/stop-all.sh
```

Restart one service — remove its PID file, then re-run `start-all.sh`, which
starts only what is missing:

```bash
kill "$(cat backend/run/backend.pid)"
rm -f backend/run/backend.pid
./scripts/start-all.sh
```

Check for duplicates before restarting; only one backend process may write the
SQLite database:

```bash
pgrep -af 'vllm serve'
pgrep -af 'main.py.*8188'
pgrep -af poster-backend
```

## 6. Persistence and Instance Recovery

The cloud host gets reset, so "which directory does this live in" is a
correctness question. The NFS persistence root is `/workspace/persistence`; this
project uses `/workspace/persistence/stageposter/`.

> **Caveat, measured:** on this instance `/workspace/persistence` is *not* a
> separate mount. `findmnt -T` resolves it to `/workspace` on `/dev/loop0`
> (ext4), and `stat -c%d` returns the same device (1792) for `/workspace`,
> `/workspace/persistence`, and the project directory. `mount | grep -i nfs`
> returns nothing. Placing files there confers no verifiable extra protection
> from inside the container. **Pull backups off-box for anything you cannot
> regenerate.**

### Routine backup

```bash
bash scripts/backup-persistence.sh          # fast, ~2.3 MB
bash scripts/backup-persistence.sh --hash   # adds weight sha256, slow
```

Output lands in `/workspace/persistence/stageposter/backups/<timestamp>/`, with
`backups/latest` symlinked to the newest. Each holds `RESTORE.md`, a consistent
DB snapshot, `env.backup`, a weight manifest, and git state.

The DB snapshot uses `VACUUM INTO`, not `cp`: with the backend live the WAL can
hold megabytes not yet checkpointed, so a plain copy is either stale or torn.
`integrity_check` then runs on **the snapshot**, because the claim worth
asserting is "this backup is usable", not "the source isn't corrupt".

### Before a planned instance kill

```bash
cd /workspace/poster-engine/backend
sudo -E bash scripts/prepare-before-instance-kill.sh
```

Use `sudo -E`, not bare `sudo` — the script reads `.env` for `DB_PATH` and the
venv paths, and a scrubbed environment loses them.

### Rehearsing recovery (do this while things still work)

```bash
sudo bash scripts/recover-after-instance-kill.sh --check
```

`--check` runs every assertion the real recovery depends on and **mutates
nothing**. It verifies: snapshot present and `integrity_check` clean, `.env`
archived, both venv package lists archived, weight byte sizes matching the
manifest, toolchains staged, ROCm reachable, and no unpushed commits. Exit 0
means recovery has what it needs.

Run this after every `prepare`. An unrehearsed restore path is the most common
reason backups turn out to be useless, and it only reveals itself when you
need it most.

### What is NOT backed up

- **~43 GB of model weights** are inventoried, not copied — there isn't the free
  space, and duplicating them onto the same filesystem protects against nothing.
  `model-sizes.txt` exists to verify a re-download.
- **~24 GB of `site-packages`** (ComfyUI 16 GB + vLLM 8.3 GB) are not copied
  either. Instead `pip freeze` for both venvs is archived to
  `prekill/private/{comfyui,vllm}-requirements.txt`. A few KB is the only
  practical rebuild instruction for 24 GB.
- **`storage/`** (candidates, final posters, uploaded assets, ~410 MB) exists
  only in the persistence directory. Losing it loses poster history and leaves
  DB rows pointing at missing files. Accepted tradeoff: outputs are
  regenerable and the briefs are in the database.

### Two traps when restoring

- **Re-downloading weights needs `HF_HUB_DISABLE_XET=1`.** huggingface.co is
  unreachable so downloads go via hf-mirror, but `HF_ENDPOINT` alone is not
  enough: Xet-backed large files bypass the mirror straight to
  `cas-server.xethub.hf.co` and 401. Small files land, the directory looks
  populated, and the exit code can still be 0. Verify byte sizes against
  `model-sizes.txt` — nothing else is reliable.
- **Delete the stale `-wal` / `-shm`** when restoring a database, or SQLite
  replays an old WAL over the fresh file.

## 7. Deploying the Frontend on This Machine

The frontend is a static SPA; the backend already serves CORS for it.

```bash
cd /workspace/poster-engine/frontend
npm ci
npm run build          # emits dist/
```

Point it at the backend through an env var — **never hardcode the tunnel URL**,
whose subdomain changes on every restart:

```bash
# frontend/.env.local
VITE_API_BASE_URL=https://<current>.trycloudflare.com
```

Read the current value from the gitignored file, or `./scripts/status.sh`:

```bash
cat backend/run/public-api-url.txt
```

Serve `dist/` however is convenient (`npx serve dist`, nginx, or a second
tunnel). The only hard rules: talk to the Go API only — never ComfyUI or vLLM
directly — and keep the tunnel URL out of version control.

> `POSTER_API_TOKEN` is currently **empty**, so the backend is unauthenticated.
> Anyone with the tunnel URL can drive it. Set a real token before sharing the
> address beyond the team, and pass it as `Authorization: Bearer <token>`.

## 8. Bind Addresses

```
vLLM:    127.0.0.1
ComfyUI: 127.0.0.1
Backend: 127.0.0.1  (cloudflared connects locally)
```

## 9. Production Hardening

The current architecture suits one backend process, one GPU worker, and
demo/small-team use. For real production:

- Replace SQLite with PostgreSQL; local storage with object storage
- Add distributed job locks and a shared queue
- Cloudflare **Named** Tunnel on a fixed domain, `cloudflared` as a systemd unit
- Set a real `POSTER_API_TOKEN` and restrict `CORS_ORIGIN`
- Move secrets into a secret manager
- Structured logs with request IDs

## 10. Log Inspection

```bash
cd /workspace/poster-engine/backend
tail -f logs/backend.log
tail -f logs/comfyui.log
tail -f logs/vllm.log
tail -f logs/cloudflared.log
```
