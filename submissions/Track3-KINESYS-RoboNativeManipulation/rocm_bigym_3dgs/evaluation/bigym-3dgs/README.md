# Provider-neutral BiGym + 3DGS evaluation on AMD

This directory owns the simulator side of the AMD evaluation pipeline:

- pinned BiGym/MuJoCo source and ROCm PyTorch + gsplat runtime;
- calibrated AMD 3DGS kitchen-shell download and validation;
- closed-loop task execution against any inference HTTP v2 provider;
- synchronized head, left-wrist and right-wrist MP4 recording;
- append-only transitions, atomic manifests, hashes and result validation.

Inference implementations are deliberately outside this branch. This directory
contains only the external-service client, contract probe, BiGym loop, recorder
and validator. See [`INFERENCE_PROTOCOL.md`](INFERENCE_PROTOCOL.md) for the
provider-neutral contract. No model runtime, checkpoint or inference server is
included here.

## Architecture boundary

```text
third-party inference process             BiGym evaluation process
GET /health                               PyTorch ROCm + gsplat 1.4.0
POST /process_frame  <----------------->  MuJoCo + calibrated 3DGS shell
finite 10x16 action chunks                three-camera recorder + validator
```

The processes may share one 48 GB-class AMD GPU after the smoke memory gate, or
use separate GPUs. They must not import their framework stacks into one Python
process.

## Pinned evaluation inputs

| Component | Pinned value |
| --- | --- |
| BiGym client | [`WuChao-2024/bigym_plus`](https://github.com/WuChao-2024/bigym_plus), commit `d12937686833467b5013ac47a834cf4b6f5a9d53` |
| AMD visual shell | [`eustance/amd-bigym-3dgs-kitchen-shell`](https://huggingface.co/datasets/eustance/amd-bigym-3dgs-kitchen-shell/tree/amd-rocm-w7900d-20260804), revision `amd-rocm-w7900d-20260804` |
| Default task | `DishwasherUnloadCutleryLong` |
| Comparable benchmark | 32 episodes, seeds `0..31` |
| Custom evaluation | any positive episode count |

The machine-readable simulator, shell, inference and recording contract is in
[`VERSION_LOCK.json`](VERSION_LOCK.json).

## Prepare the simulator side

Use a persistent AMD workspace; large PLY and run outputs never belong in Git.

```bash
export AMD_PIPELINE_ROOT=/workspace/amd-bigym-3dgs-rocm
export INFERENCE_GPU=0
export SIM_GPU=0
export INFERENCE_PROVIDER=external
export INFERENCE_BASE_URL=http://127.0.0.1:7891

./evaluation/bigym-3dgs/bin/preflight_amd.sh
./evaluation/bigym-3dgs/bin/bootstrap_bigym_source.sh

export VENV=/workspace/amd-bigym-3dgs/.venv
./evaluation/bigym-3dgs/bin/bootstrap_bigym_runtime.sh

hf auth login
./evaluation/bigym-3dgs/bin/download_shell.sh
```

Start a compatible provider outside this branch. Then validate its contract and
run the closed loop:

```bash
./evaluation/bigym-3dgs/bin/probe_inference.sh
./evaluation/bigym-3dgs/bin/run_eval.sh smoke
./evaluation/bigym-3dgs/bin/run_eval.sh formal

N_EPISODES=8 RUN_NAME=custom-8-full-v2 \
  ./evaluation/bigym-3dgs/bin/run_eval.sh custom
```

The versioned HTTP contract is documented in
[`INFERENCE_PROTOCOL.md`](INFERENCE_PROTOCOL.md). A provider must freeze its
provider/model/adapter identity in `/health`, echo each request ID and return
finite `10 x 16` action chunks with timing evidence.

## Full trajectory recording

Every reset and transition is flushed immediately to append-only JSONL. Each
transition links state before action, action, state after action, MuJoCo time,
reward, termination, task success, request ID, HTTP/provider timing and the
observation record indices. Three camera streams are synchronized per episode.

`RESUME=1` skips terminal episodes. `RESTART_INTERRUPTED=1` archives an unsafe
mid-state attempt under `incomplete-attempts/` and replays that seed from reset.
Failed task rollouts remain diagnostic recordings and are never presented as
successful demonstrations.

```text
$AMD_PIPELINE_ROOT/results/<run>/
├── evaluation-summary.json
├── recording-validation.json
└── dishwasher_unload_cutlery_long/
    ├── results.json
    ├── episodes/episode-000000/
    │   ├── steps.jsonl
    │   ├── manifest.json
    │   ├── evidence/*.png
    │   └── videos/{head,left_wrist,right_wrist}.mp4
    └── incomplete-attempts/
```

## Acceptance gates

The evidence gates remain separate:

1. `/health` proves only that a versioned provider is ready.
2. `inference-contract-probe.json` proves one real finite action request.
3. `results.json` proves the provider was closed over BiGym with strict 3DGS.
4. `recording-validation.json` proves transitions, manifests, videos and hashes.
5. `evaluation-summary.json` proves counts, latency and failure categories.
6. `human_visual_review_status=passed` proves explicit three-camera review.

Only an accepted formal evaluation may be committed under [`evidence/`](evidence/).
Smoke runs, interrupted runs and task-failed trajectories stay in the local
results directory for diagnosis and are not published as release evidence. This
revision contains no accepted formal policy-evaluation receipt.

## Verification

```bash
./evaluation/bigym-3dgs/bin/verify.sh
```

These CPU-safe contract tests do not claim a live ROCm run. GPU, visual-shell,
policy-request, recording and task-success evidence remain separate gates.

## Branch boundary

The former bundled model provider and compatibility wrappers were removed from
this branch and preserved without alteration on `interence`. New integrations
should implement the external HTTP contract and select their provider through
`INFERENCE_BASE_URL`.
