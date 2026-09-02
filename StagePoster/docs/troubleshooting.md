# Troubleshooting

Ordered roughly by how often each one actually bites.

## Every image request 500s, text requests are fine

Symptom — the backend logs a VLM error like:

```
AssertionError: Expected a cached item for mm_hash=...
```

Reviews and reference-image understanding fail; plain text planning still works.
This reads like a backend bug and is not one: vLLM's multimodal processor cache
self-corrupts after some uptime.

Fix — ensure vLLM was started with the cache disabled, then restart it:

```bash
grep -n 'mm-processor-cache-gb' scripts/start-all.sh   # expect 0
```

`start-all.sh` passes `--mm-processor-cache-gb "${VLLM_MM_PROCESSOR_CACHE_GB:-0}"`.
The vLLM default is 4, which is the broken configuration.

## `ModuleNotFoundError: No module named 'PIL'`

You ran the E2E script with the wrong interpreter. It needs Pillow to synthesize
test images, and only the vLLM venv has it:

```bash
cd /workspace/poster-engine
.venv-vllm/bin/python scripts/e2e-test.py all     # correct
python3 scripts/e2e-test.py all                   # fails before assertion 1
```

## Sleep endpoints return 404 / sleep calls fail

**Sleep mode is deliberately disabled on this deployment.** On ROCm 7.2 + vLLM
0.20.0, `--enable-sleep-mode` makes every subsequent generation fail with
`CUDA Error: invalid argument`. `start-all.sh:141` no longer requests sleep and
logs `VLM resident (sleep mode disabled on ROCm)`.

So `/sleep`, `/wake_up` and `/is_sleeping` are not part of the working path — do
not "fix" a 404 there by turning sleep mode back on. Earlier revisions of this
document told you to add `--enable-sleep-mode`; that advice was wrong and would
break generation.

VRAM is instead reclaimed by the Go runtime coordinator calling
`ReleaseComfyMemory` to unload ComfyUI models before a VLM call.

## Backend started but is using the wrong database

Symptom — poster/session counts look far too low, or writes seem to vanish.

Cause — the binary was started directly. **`poster-backend` does not read
`.env`.** `start-all.sh` does `set -a; source "$ENV_FILE"; set +a` first; a
manual launch silently uses defaults, including `backend/data/poster.db`, which
is a stale leftover.

```bash
# which database is live
grep -E '^DB_PATH=' /workspace/poster-engine/.env

# what the process actually has open
ls -l /proc/"$(pgrep -f poster-backend | head -1)"/fd | grep -i '\.db'
```

Fix — always start via `./scripts/start-all.sh`.

## Session appears stale — poster `succeeded`, session `generating_candidates`

Cause — a low-level Poster route was used instead of the AI Session route.

```bash
curl http://127.0.0.1:8080/api/ai/sessions/<SESSION_ID>
```

The Session GET reconciles state against the Poster. Frontend prevention — use

```
/api/ai/sessions/{sessionId}/candidates/{candidateId}/select
```

not

```
/api/posters/{posterId}/select
```

## Finalize returns 409 Conflict

Finalize is allowed only after composition has succeeded.

```bash
curl http://127.0.0.1:8080/api/ai/sessions/<SESSION_ID>
```

## Finalize ends in `completed_with_warnings`, not `succeeded`

**This is the normal outcome, not a failure.** The poster, thumbnail and review
evidence are all produced; the session is finished and the result is usable.

It means the review loop hit `maxFinalizeReviewRounds` without the VLM returning
`ACCEPT` (total score ≥ 82). Measured on live data: round 1 averages 81.2 with a
max of 92, so 82 is reachable but not typical.

`RECOMPOSE` rounds in particular often fail to move the score — see
`docs/job-lifecycle.md` §9 for the measured numbers and the known cause. Do not
"fix" this by lowering `domain.ReviewAcceptScore`.

## GPU out of memory

```bash
rocm-smi --showmeminfo vram
```

Mitigations, in order of preference:

- Stop duplicate model processes (see below)
- Reduce `VLLM_GPU_MEMORY_UTILIZATION`
- Reduce `VLLM_MAX_MODEL_LEN`
- Reduce multimodal input resolution

## Duplicate services

```bash
pgrep -af 'vllm serve'
pgrep -af 'main.py.*8188'
pgrep -af poster-backend
```

Stop duplicates before restarting. Only one backend process may write the SQLite
database.

## ComfyUI model not found

```bash
find /workspace/poster-engine/ComfyUI/models -type f -name '*.safetensors' \
  -printf '%s\t%p\n' | sort -n
```

Required subdirectories: `diffusion_models/`, `text_encoders/`, `vae/`,
`loras/`. Restart ComfyUI after adding files.

If a file is present but **smaller than expected**, suspect a truncated
download — see the next entry.

## Model download looked fine but the weight is truncated

huggingface.co is unreachable here, so downloads go through hf-mirror. Setting
`HF_ENDPOINT` alone is not enough: Xet-backed large files bypass the mirror
straight to `cas-server.xethub.hf.co` and 401. **Small files land, the directory
looks populated, and the exit code can still be 0.**

```bash
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_DISABLE_XET=1
```

Verify by byte size against the manifest — nothing else is reliable:

```bash
cat /workspace/persistence/stageposter/prekill/snapshots/*/model-sizes.txt
```

## Workflow node not found

Re-exported workflows change node IDs. Check these against the JSON:

```bash
grep -E '^(PROMPT|NEGATIVE_PROMPT|SEED)_NODE_ID=' /workspace/poster-engine/.env

python3 -m json.tool \
  /workspace/poster-engine/workflows/z_image_poster_v1.json | less
```

Note the reference-image nodes (`LoadImage` → `Canny` → `ModelPatchLoader` →
`ZImageFunControlnet`) are **not** in the template. They are injected into a
clone of the graph at build time, so do not go looking for them in the file.

## Negative prompt seems to have no effect

Negative prompts only apply when sampler `cfg > 1`. The workflow ships `cfg = 2`.
If `COMFY_CFG` is set to `1`, the negative prompt is silently ignored.

```bash
grep -E '^COMFY_CFG=' /workspace/poster-engine/.env    # empty keeps the workflow value
```

## Poster candidate file missing

```bash
DB=$(grep -E '^DB_PATH=' /workspace/poster-engine/.env | cut -d= -f2-)

sqlite3 "$DB" "
SELECT id, job_id, status FROM poster_candidates
ORDER BY created_at DESC LIMIT 10;"

find "$(grep -E '^STORAGE_ROOT=' /workspace/poster-engine/.env | cut -d= -f2-)" \
  -type f | tail
```

Use `$DB_PATH` from `.env`. Querying `backend/data/poster.db` returns stale rows
that look plausible.

## Review snapshot missing

Expected per round:

```
review-round-1-final_poster.png
review-round-1-thumbnail.png
```

```bash
find "$(grep -E '^POSTER_OUTPUT_ROOT=' /workspace/poster-engine/.env | cut -d= -f2-)" \
  -name 'review-round-*' -printf '%s\t%p\n'
```

## Cloudflare tunnel has no URL

```bash
grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' \
  /workspace/poster-engine/backend/logs/cloudflared.log | tail -1

cat /workspace/poster-engine/backend/run/public-api-url.txt
```

The subdomain changes on every restart. Warnings about ICMP proxy permissions do
not block HTTP proxying — confirm `Registered tunnel connection` appears, then
test the URL with curl.

## Cloudflare 502

Check the backend locally first — if this works, the tunnel is the problem:

```bash
curl -i http://127.0.0.1:8080/api/ai/sessions/not-found   # expect 404
pgrep -af cloudflared
tail -100 /workspace/poster-engine/backend/logs/cloudflared.log
```

## `ss: command not found`

```bash
apt-get update && apt-get install -y iproute2
```

Alternatives:

```bash
lsof -iTCP -sTCP:LISTEN -P -n
ps aux | grep -E 'vllm|main.py|poster-backend' | grep -v grep
```

## SQLite locked

```bash
pgrep -af poster-backend
```

Only one backend process should write the database.

## Go module download timeout

```bash
export GOPROXY=https://proxy.golang.org,direct
go mod download
```

In restricted regions configure an accessible proxy explicitly.

## Recovery scripts fail on a healthy machine

If `recover-after-instance-kill.sh` exits at the venv verification, check that
it is reading the venv paths from `.env` rather than assuming
`$PROJECT_ROOT/venv`. `COMFY_VENV` is `/workspace/venv` — **outside** the
project tree.

Rehearse the restore path without mutating anything:

```bash
cd /workspace/poster-engine/backend
sudo bash scripts/recover-after-instance-kill.sh --check
```

## Logs

```bash
cd /workspace/poster-engine/backend
tail -f logs/backend.log
tail -f logs/comfyui.log
tail -f logs/vllm.log
tail -f logs/cloudflared.log
```
