# Scripts

Shared helpers live in `lib.sh` (sourced by the others). Optional project-root `.env`
is loaded automatically when present (see `.env.example`).

| Script | Purpose |
|---|---|
| `run_all_local.sh` | **One-click local**: assets → scene → expert → record → validate |
| `run_record.sh` | **One-click recording** only (local or remote backend) |
| `run_expert_demo.sh` | Scripted demos across basic / hard tasks |
| `run_pipeline_smoke.sh` | Fast 1-episode smoke + train dry-run |
| `run_full_remote.sh` | **Full AMD path**: check → record → train → eval → benchmark |
| `finish_physical_1k.sh` | Wait for six audited shards → merge exact 20×50 → validate → run the full AMD path |
| `run_reflex_demo.sh` | Normal + interrupt + target-shift videos from an existing checkpoint |
| `check_local.sh` | Env + audit + pytest + ruff |
| `check_remote_amd.sh` | Strict ROCm gate + scene/benchmark |

Public inputs are downloaded by the package entry point rather than an unpinned shell URL:

```bash
python -m radeonvla.download_artifacts --list
python -m radeonvla.download_artifacts --artifact physical-1k model-20k evaluation-videos
python -m radeonvla.download_artifacts --all
```

Each registry entry fixes the Hugging Face repository, 40-character revision, and local
destination. Successful downloads write `downloads/public_artifacts.json`.

## Common environment variables

| Variable | Default | Used by |
|---|---|---|
| `BACKEND` | `cpu` (local) / `amdgpu` (remote) | most runners |
| `EPISODES` | `5` local / `200` remote | record scripts |
| `SUITE` | `basic` or `full` | record / remote |
| `TASK` | empty | pin a single task id |
| `REPO_ID` / `DATASET_ROOT` | suite-based | record / train |
| `DR` | `0` local / `1` remote | domain randomization |
| `TRAIN_STEPS` | `10000` | full remote |
| `EVAL_SEED_START` | `50000` | held-out formal evaluation |
| `INTERRUPT_SEED_START` | `60000` | interrupt/reflex comparison |
| `PERTURB_SEED_START` | `60100` | target-shift recovery comparison |
| `CKPT` | auto under `outputs/train/...` | eval when `SKIP_TRAIN=1` |
| `SKIP_RECORD` | `0` | reuse an already validated dataset on remote |
| `SOURCE_COMMIT` | auto from Git | explicit 40-hex source revision for source-only remote copies |
| `OVERWRITE` | `0` | replace a published dataset only after the new staging run validates |
| `DISCARD_INCOMPLETE` | `0` | explicitly remove the target's stale `.inprogress` directory |
| `HIP_VISIBLE_DEVICES` | `0` | remote AMD |
| `PYTHON` | auto (`conda run -n radeonvla-dev` if present) | all |

## Examples

```bash
# Local: collect 10 basic episodes on CPU
EPISODES=10 SUITE=basic bash scripts/run_record.sh

# Local: full one-click (record + validate)
EPISODES=5 bash scripts/run_all_local.sh

# Hard expert demos
MODE=hard bash scripts/run_expert_demo.sh

# Remote AMD full stack
EPISODES=200 SUITE=basic bash scripts/run_full_remote.sh

# Remote: only re-eval an existing checkpoint
SKIP_RECORD=1 SKIP_TRAIN=1 CKPT=outputs/train/.../pretrained_model bash scripts/run_full_remote.sh
```
