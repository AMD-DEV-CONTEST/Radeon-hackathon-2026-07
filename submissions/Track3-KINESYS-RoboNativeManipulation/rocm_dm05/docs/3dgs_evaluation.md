# AMD 3DGS shell evaluation

## Public shell source

The AMD evaluation shell is published as the Hugging Face dataset
[`eustance/amd-bigym-3dgs-kitchen-shell`](https://huggingface.co/datasets/eustance/amd-bigym-3dgs-kitchen-shell/tree/amd-rocm-w7900d-20260804)
at revision `amd-rocm-w7900d-20260804`. Large PLY assets remain outside this Git
repository.

Download by named revision, resolve it to an immutable commit, discover the
runtime profile and verify every referenced PLY:

```bash
"$PYTHON" scripts/download_3dgs_shell.py \
  --output-dir /data/amd-bigym-3dgs-kitchen-shell
source /data/amd-bigym-3dgs-kitchen-shell/shell.env
```

The downloader writes `download_manifest.json` with repository, requested
revision, resolved commit, profile mode, byte sizes and SHA-256 values. For a
combined shell, it also enforces the byte/hash contract embedded in the profile.
If the dataset contains more than one valid profile, pass its relative path via
`--profile` rather than selecting one implicitly.

## Effective AMD runtime changes

The 3DGS path keeps only integration changes required by the verified W7900
runtime:

1. build `gsplat==1.4.0` for `gfx1100` with the repository-owned ROCm compiler
   wrapper and compatibility headers;
2. keep compiled extensions in a persistent `TORCH_EXTENSIONS_DIR` so rollout
   workers do not rebuild kernels;
3. pin the reconstructed 3DGS source commit and run an actual ROCm rasterizer
   smoke test during setup;
4. use the same 10-step quality protocol as native
   evaluation;
5. run strict visual-shell mode, which aborts on a missing renderer, profile or
   PLY instead of silently reverting to native images.

MuJoCo remains the physics and success engine. The Gaussian shell changes only
the RGB observations; it does not add collision geometry or task state.

## Run

```bash
NUM_EPISODES=1 SEED_START=200009 AMD_GPU_IDS=0 \
  bash scripts/run_amd_eval.sh 3dgs \
  "$MODEL_PATH" "$OFFICIAL_DEMO" "$OUTPUT_ROOT/3dgs-smoke"
```

For multiple AMD GPUs, pass a comma-separated `AMD_GPU_IDS`. The runner assigns
deterministic seed shards, loads one model per process and merges summaries only
after every shard succeeds.

## Verified result

With seeds `200000-200049`, the released checkpoint completed 20/50 episodes
(40%) through the public shell. The AMD port also passed a strict end-to-end
W7900 rollout with the same shell and final 10-step code: seed `200009`
succeeded in 567 control steps and 71 model calls, with 726.580 ms mean model
latency and 91.852 seconds wall time. The gate covered ROCm rasterization,
policy inference, MuJoCo control, success detection and MP4 output; it is not a
second success-rate estimate.

The official lightweight demo supplies environment class, robot and action-mode
metadata only. Its recorded actions are never replayed during policy evaluation.
The actual runtime is pinned to BiGym commit
`14beb30318ad14c5d6723175c2ee2281129792af` and the installed MuJoCo package.
