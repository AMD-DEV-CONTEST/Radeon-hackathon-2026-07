# JAX Training / Inference for openpi on AMD ROCm (gfx1100 · RDNA3)

This document is the **only officially recommended path** for openpi on AMD ROCm (gfx1100 / RDNA3): .venv + apt installation, training / inference usage, and VRAM and GPU compute utilization performance metrics during training and inference. We primarily recommend `.venv + apt` (no conda required); the repo also provides `install_rocm.sh` as an alternative conda route.

> Test host: AMD gfx1100 (RX 7900 series / RDNA3), ROCm 7.2.1 installed in `/opt/rocm`, single-GPU reports VRAM 51.5 GiB.
> Test model: pi05 LoRA fine-tuning (`gemma_2b_lora` + `gemma_300m_lora`, base frozen), 3 cameras (cam_high 480×848 + left/right wrist 480×640), action-dim 16, action-horizon 10.
>
> 📗 **Companion evaluation article**: BiGym **closed-loop evaluation** with a 3DGS room shell (two-process architecture) + **gsplat-on-AMD compile fixes** + **full-chain training/inference/evaluation/rendering performance benchmarks** + key pitfalls such as autotune-segfault/h10-vs-h20, see [`amd_rocm_bigym_eval.md`](amd_rocm_bigym_eval.md).

---

## 0. Overview

| Dimension | AMD / ROCm route (the only officially recommended path in this repo) |
| --- | --- |
| Installation | **System python3.12 + apt ffmpeg + `.venv`** (Ubuntu 24.04; see §1.1) |
| Dependency list | `requirements_rocm.txt` |
| JAX | **AMD ROCm JAX 0.6.0** (rocm7.0.2, `repo.radeon.com` proprietary wheel) |
| jaxlib | PyPI `jaxlib==0.6.0` + AMD `jax_rocm7_pjrt`/`jax_rocm7_plugin` |
| torch | `torch==2.7.1` **CPU** (training GPU compute handled by JAX; CPU torch avoids dual ROCm runtime conflicts) |
| ml-dtypes | **0.5.4** (jaxlib 0.6.0 requires `float4_e2m1fn` at runtime) |
| ffmpeg | **apt 6.1.1** (Ubuntu 24.04 default; torchcodec 0.5 is compatible with 4–7, no pin needed) |
| GPU visibility | `ROCR_VISIBLE_DEVICES` |
| venv activation | `source .venv/bin/activate` (activation hook automatically sets `LD_LIBRARY_PATH=/opt/rocm/lib`) |

Key points: openpi uses `pip install -e . --no-deps` to bypass the upstream legacy cuda pin in pyproject (`jax[cuda12]==0.5.3`), keeping AMD jax 0.6.0. pyproject's `[tool.uv] override-dependencies` sets `ml-dtypes==0.5.4` — jaxlib 0.6.0 has no upper bound on ml-dtypes (`>=0.2.0`), so 0.5.4 is safe for both pip and uv.

JAX **does work** on this machine: AMD's official ROCm 7.x JAX backend explicitly compiled `gfx1100` kernels (after unpacking the `.so` files of `jax_rocm7_plugin`/`jax_rocm7_pjrt`, grep found `gfx1100`, `gfx1101`, `gfx1150`, `gfx1200`, etc.).

---

## 1. Environment Configuration

### 1.1 Installation (.venv + apt, no conda required)

Ubuntu 24.04 ships with **python3.12** (AMD jax 0.6.0 only publishes cp312 wheels, which matches perfectly), and apt's **ffmpeg 6.1.1** falls within torchcodec 0.5's compatibility range (4–7), so system python + apt + one `.venv` is enough to install the entire ROCm stack. Fully reproducible commands are in the [Installation section of the README](../README.md); key points:

```bash
sudo apt-get install -y ffmpeg python3.12-venv          # Ubuntu 24.04: ffmpeg 6.1.1
python3.12 -m venv .venv && source .venv/bin/activate
# Stepwise pip: AMD ROCm JAX → ml-dtypes → CPU torch → requirements → lerobot deps → openpi(-e --no-deps)
# Write the ROCm library path into the .venv activation hook once (equivalent to conda's activate.d):
echo 'export LD_LIBRARY_PATH="/opt/rocm/lib:${LD_LIBRARY_PATH:-}"' >> .venv/bin/activate
```

Prerequisite: the host already has ROCm installed (`/opt/rocm`), and `rocminfo` can recognize gfx1100.

What the flow does (10 steps, see README for details):

1. `apt install ffmpeg python3.12-venv` (Ubuntu 24.04's ffmpeg is 6.1.1, compatible with torchcodec 0.5; only the conda route needs pin=7 to avoid conda-forge's 8).
2. `python3.12 -m venv .venv` (system python3.12; AMD jax 0.6.0 only publishes cp312 wheels, 3.12 is mandatory).
3. **AMD ROCm JAX**: install two AMD wheels (`jax_rocm7_pjrt` + `jax_rocm7_plugin`, 0.6.0/cp312) + `jax==0.6.0 jaxlib==0.6.0 scipy numpy`.
4. **`ml-dtypes==0.5.4`** (`--no-deps` to prevent being pulled back). ★ jaxlib 0.6.0 requires `float4_e2m1fn` at runtime; ml-dtypes 0.4.1 lacks it and will crash `import jax` — **this is the most hidden pitfall of the AMD route**.
5. **CPU torch / torchvision** (`--index-url .../whl/cpu`): training GPU compute is JAX, torch only handles the data pipeline; the CPU route avoids the dual ROCm runtime symbol conflict between jax-rocm7 and torch-rocm6.4.
6. openpi ecosystem dependencies: strip the AMD jax/torch/ml-dtypes/lerobot lines from `requirements_rocm.txt` and then `pip install -r` (flax/orbax/chex/transformers, etc.; optax is pulled in transitively by flax).
7. lerobot runtime dependencies (av/datasets/pyarrow/pandas/draccus/jsonlines/opencv, CPU) + `torchcodec==0.5` CPU build.
8. `lerobot==0.6.0 --no-deps` (to bypass hub>=1.0 metadata conflict) + `pip install -e . --no-deps` (★ `--no-deps`: bypasses pyproject's `jax[cuda12]==0.5.3`, keeping AMD jax 0.6.0).
9. Patch transformers.
10. Write `export LD_LIBRARY_PATH=/opt/rocm/lib:...` into `.venv/bin/activate` (takes effect automatically on every subsequent `source .venv/bin/activate`).

### 1.2 Why JAX 0.6.0 (rocm7.0.2)

AMD does not publish ROCm JAX on PyPI; it only releases a few versions at `https://repo.radeon.com/rocm/manylinux/rocm-rel-X/`:

| ROCm rel | jax version | Python available | gfx1100 kernel | Applicability to openpi |
| --- | --- | --- | --- | --- |
| rocm-rel-6.4.x | 0.4.35 | cp310, cp312 | — | ❌ orbax 0.11.13 requires `jax>=0.5.0` |
| **rocm-rel-7.0.2** | **0.6.0** | cp310, **cp312** | ✅ | ⚠️ Only cp312 (openpi requires py≥3.11) |
| rocm-rel-7.2.1 / 7.2.4 | 0.8.2 | cp311, cp312 | ✅ | Too far from the fork's pinned 0.5.3 (3 minors), flax/orbax/chex require cascading upgrades, high risk |

`0.6.0` is the only choice that simultaneously satisfies "orbax ≥0.5.0 lower bound" and "closest to the fork ecosystem". Cost: gives up the optional RLDS dataset group (`tensorflow-cpu==2.15.0` in the `rlds` group is only published for cp311, cannot be installed on py3.12 — **does not affect pi05 core training/inference**).

### 1.3 Post-installation verification

```bash
source .venv/bin/activate        # activation hook automatically sets LD_LIBRARY_PATH=/opt/rocm/lib
python -c "import jax; print(jax.__version__); print(jax.devices())"
#   Expected: 0.6.0  /  [RocmDevice(id=0)]
python -c "import jax.numpy as jnp; x=jnp.ones((1024,1024)); print((x@x).sum())"   # small compute smoke test
python train_jax.py --help     # Expected EXIT=0 (full model/import chain loaded)
```

If JAX reports "unsupported gfx / no GPU device" as a fallback (usually not needed when `rocminfo` on this machine already recognizes gfx1100):
```bash
export HSA_OVERRIDE_GFX_VERSION=11.0.0
```

### 1.4 torch: CPU or GPU?

- **CPU route (default, used by the `.venv` flow)**: avoids dual ROCm runtime conflicts; the data pipeline bottleneck is JAX on the GPU, CPU is sufficient.
- **GPU route (optional)**: the host's bigym environment has verified that `torch 2.9.1+rocm6.4` works on gfx1100 (`torch.cuda.is_available()==True`). If you want torch to also use the GPU, install it separately and run `import torch; torch.cuda.is_available()` once; if MIOpen/rocBLAS symbol errors occur in the same process as JAX, fall back to CPU.
- **GPU coexistence**: JAX pre-allocates about 75% of VRAM by default. If another GPU load in the same process requires moving JAX to CPU, set `JAX_PLATFORMS=cpu`.

---

## 2. Usage Details

### 2.1 Obtaining the base checkpoint (pi05_base) — GCS anonymous cache pitfall

**Recommended: the repo's built-in `prefetch_base.py` can complete the anonymous prefetch below in one step** (cache path is already handled). Manual steps and root cause are provided below for offline use / troubleshooting.

`train_jax.py --base-checkpoint gs://openpi-assets/checkpoints/pi05_base/params` triggers `download.maybe_download(path)`. This function **prefers `gsutil`** for the `openpi-assets` bucket (most AMD hosts don't have it installed) → falls back to `gcsfs`, but `CheckpointWeightLoader` **does not pass `token="anon"`** when called → fails on hosts without GCP credentials.

The bucket itself is **public** (an approximately 12.4 GB orbax ocdbt checkpoint). Solution: use anonymous fsspec to pre-download `params/` to openpi's local cache path; afterwards `maybe_download` hits the local cache and returns directly, zero network during training:

```python
# Run once inside the venv (after source .venv/bin/activate)
import fsspec, pathlib, os
src = "openpi-assets/checkpoints/pi05_base/params"
dst = pathlib.Path(os.path.expanduser("~/.cache/openpi/openpi-assets/checkpoints/pi05_base/params")).resolve()
dst.parent.mkdir(parents=True, exist_ok=True)
if (dst/"_METADATA").exists() or (dst/"manifest.ocdbt").exists():
    print("cache already present:", dst); raise SystemExit
fs = fsspec.filesystem("gs", token="anon")          # ★ key: anonymous token
print("du bytes:", fs.du(src))
partial = dst.parent / "pi05_base_params.partial"
fs.get(src, str(partial), recursive=True)             # ~12GB
partial.rename(dst)
print("DONE ->", dst)
```

The cache path comes from `maybe_download`'s `cache_dir/<netloc>/<path>` rule: `gs://openpi-assets/checkpoints/pi05_base/params` → `~/.cache/openpi/openpi-assets/checkpoints/pi05_base/params`. Verification: this directory must contain `_METADATA`, `manifest.ocdbt`, `_sharding`, `d/`.

### 2.2 Computing normalization statistics (one-time)

```bash
python compute_norm_stats.py \
    --data-dir /path/to/lerobot_dataset \
    --output-dir ./assets/<dataset_name>
# Output: ./assets/<dataset_name>/norm_stats.json, keys state / actions
# Reads parquet offline, does not decode video; only needs the dataset directory + state/action column names
```

### 2.3 Training (`train_jax.py`)

Running pi05 on a single gfx1100 (~48 GiB VRAM) **must use LoRA** (freeze base, only train adapters); full-parameter fine-tuning won't fit on a single card. The training command itself is vendor-agnostic and consistent with the README's training example; only environment variables and single-card configuration are tuned for AMD:

```bash
XLA_PYTHON_CLIENT_MEM_FRACTION=0.9 python train_jax.py \
    --action-dim 16 --action-horizon 10 --model-action-dim 32 \
    --camera-names high l_wrist r_wrist \
    --camera-sources observation.images.cam_high \
                    observation.images.cam_left_wrist \
                    observation.images.cam_right_wrist \
    --wrist-names l_wrist r_wrist \
    --data-dir /path/to/lerobot_dataset \
    --exp-name run1_lora \
    --norm-stats ./assets/<dataset_name> \
    --base-checkpoint gs://openpi-assets/checkpoints/pi05_base/params \
    --lora \
    --num-train-steps 4000 --batch-size 4 --save-interval 500 \
    --log-interval 50 --num-workers 0 --overwrite
```

Key points:
- `--model-action-dim 32` must equal pi05_base's action_dim (32), do not change it; dataset actions are zero-padded to 32, and sliced back to `--action-dim` during inference.
- `--lora`: mandatory for single-card; also freezes base and disables EMA.
- The `Pi0Config` (camera order / action_dim / action_horizon / lora variant) for training and inference **must be consistent**, otherwise inputs won't align.
- Stable single-card configuration: `--batch-size 4 --num-workers 0 XLA_PYTHON_CLIENT_MEM_FRACTION=0.9` (see §3.3 OOM troubleshooting for details).
- wandb is off by default; to enable it, first `wandb login` then add `--wandb`.
- Checkpoints are saved at `./checkpoints/<config_name>/<exp_name>/<step>/` (`config_name` defaults to the basename of `--data-dir`), containing `params/` (orbax) and `assets/<asset_id>/norm_stats.json`.

### 2.4 Inference service (`inference_server.py`)

openpi's built-in service uses the **msgpack** protocol (not JSON):

```bash
python inference_server.py \
    --action-dim 16 --action-horizon 10 --model-action-dim 32 \
    --camera-names high l_wrist r_wrist \
    --camera-sources observation.images.cam_high observation.images.cam_left_wrist observation.images.cam_right_wrist \
    --wrist-names l_wrist r_wrist \
    --data-dir /path/to/lerobot_dataset \
    --checkpoint-dir ./checkpoints/<config_name>/<exp_name>/<final_step> \
    --lora --default-prompt "<prompt used during training>" \
    --host 0.0.0.0 --port 8000
```

- `--checkpoint-dir` points to the **step directory** (containing `params/` and `assets/`); JAX / PyTorch backend auto-detected.
- norm_stats is loaded from `checkpoint_dir/assets/<asset_id>/norm_stats.json` (asset_id = dataset basename).
- Endpoints: `POST /infer` (msgpack obs → msgpack action), `GET /healthz`, `GET /metadata`.
- The client encodes images using `openpi_client.msgpack_numpy` (not JSON; uint8 image arrays cannot be carried by JSON):

```python
import requests, openpi_client.msgpack_numpy as mn
obs = {
    "state": state16,                          # np.float32, 16-dim
    "images": {"high": rgb_high, "l_wrist": rgb_l, "r_wrist": rgb_r},  # HxWx3 uint8 RGB
    "prompt": "your prompt",
}
r = requests.post("http://host:8000/infer", data=mn.packb(obs),
                  headers={"Content-Type": "application/msgpack"})
action = mn.unpackb(r.content)                # {"state":..., "actions": (action_horizon,16), ...}
```

Image conventions: `data["images"][name]` is **H×W×3 uint8 RGB** (`MultiCameraInputs` also accepts CHW and auto-converts to HWC, floating-point auto ×255); `ResizeImages(224,224)` scales internally on the server side, the client can send original resolution.

### 2.5 Multi-GPU

This machine is a single gfx1100; JAX occupies that card by default (GPU visibility is determined by `ROCR_VISIBLE_DEVICES` and the driver). Multi-GPU hosts can:

- Limit visible cards: `export ROCR_VISIBLE_DEVICES=0,1`.
- Data/model parallelism: `train_jax.py --fsdp-devices <N>` (number of JAX FSDP shards, default 1).
- JAX pre-allocation: `XLA_PYTHON_CLIENT_MEM_FRACTION=<0..1>` controls the single-card pre-allocation cap; `XLA_PYTHON_CLIENT_PREALLOCATE=false` switches to on-demand allocation (sacrificing a bit of throughput for VRAM headroom).

---

## 3. Performance Metrics (Measured)

### 3.1 Training (pi05 LoRA, single gfx1100, 48 GiB VRAM)

| Metric | Measured value | Notes |
| --- | --- | --- |
| Model configuration | pi05 LoRA (base frozen) | `gemma_2b_lora` + `gemma_300m_lora` |
| Cameras | 3 routes (cam_high 480×848 + left/right wrist 480×640) | resized to 224 for model input |
| batch-size | 4 | Stable upper bound for single-card LoRA, see 3.3 |
| VRAM cap | `XLA_PYTHON_CLIENT_MEM_FRACTION=0.9` (≈46.4 GiB) | Default 0.75 (≈38.6 GiB) hits OOM ceiling at batch≥8 |
| **Peak VRAM** | **45.29 GiB / 51.5 GiB (≈88%)** | Maximum of 1457 rocm-smi samples |
| **Steady-state GPU utilization** | **≈100%** | 100% in 1093/1093 samples, only 0% during startup/shutdown phases |
| Throughput | **≈1.2 s/it** | 4000 steps ≈ 81 minutes |
| loss | Monotonically decreasing, grad_norm converges to ~0.2 | Prints `Step N: loss=.. grad_norm=.. param_norm=..` every `--log-interval` |
| Non-fatal warning | XLA `gemm_fusion_autotuner` reports "Results do not match the reference" | Numerical precision warning, training proceeds normally, does not affect convergence |

### 3.2 Inference (pi05 LoRA, single card, batch 1)

| Metric | Measured value | Notes |
| --- | --- | --- |
| Resident service VRAM | **≈40 GiB** (default pre-allocation 75% ≈38.6 GiB + model weights) | Occupied on process startup, regardless of whether inference is running |
| Per-inference incremental VRAM | Negligible (batch 1) | Peak ≈ resident |
| **End-to-end latency** | **≈208 ms per `/infer`** | Includes PNG decoding + HTTP + pi05 LoRA forward; returns 10-step action chunk |
| Model forward (excluding HTTP/decoding) | About 150–180 ms | `policy_timing.infer_ms` returned by `policy.infer` |
| Non-fatal warning | Same as training: gemm autotuner numerical precision warning | Does not affect output |

> Training uses `MEM_FRACTION=0.9`; inference does not need to be set (default 0.75 is enough for batch-1). If inference co-resides with other GPU processes, reduce `XLA_PYTHON_CLIENT_MEM_FRACTION` to leave headroom. Monitor VRAM and utilization with `rocm-smi --showmeminfo vram --showuse` (corresponds to NVIDIA's `nvidia-smi`).

### 3.3 OOM / stability troubleshooting log (important experience)

Running pi05 LoRA on a single 48 GiB card, **not just any batch can start**. Measured (3 routes of 480×848/640 cameras):

| Configuration | Result | Cause |
| --- | --- | --- |
| `--batch-size 16`, default pre-allocation | SIGKILL around step8 (no Python stack) | Peak ~40 GiB exceeds default 75% pre-allocation cap (~38.6 GiB) → XLA kills process directly |
| `--batch-size 8` + `PREALLOCATE=false` | Crashes during step0 autotuning/compile | On-demand allocation is unstable on ROCm/XLA |
| `--batch-size 8`, default pre-allocation | Crashes around step3 | VRAM margin tight |
| **`--batch-size 4` + `--num-workers 0` + `MEM_FRACTION=0.9`** | ✅ Stable run to 4000 steps | See below |

**Stable configuration**: `--batch-size 4`, `--num-workers 0`, `XLA_PYTHON_CLIENT_MEM_FRACTION=0.9`.

Experience-based judgment:
1. Most of these crashes are **ROCm/XLA hard kills (SIGKILL, no Python OOM exception)** and will not throw `RESOURCE_EXHAUSTED` — when troubleshooting, don't only watch the Python stack, check `dmesg`/whether the process was killed by the OOM killer or XLA.
2. The main trigger is the **data loading worker subprocess** (`--num-workers>0`) compounded with tight VRAM; `--num-workers 0` + enlarging the managed pool (`MEM_FRACTION=0.9`) resolves it. When the dataset is small, `num-workers 0` barely costs throughput.
3. Priority for tight VRAM: first reduce `--batch-size` → then set `XLA_PYTHON_CLIENT_MEM_FRACTION` close to the cap → only disable `PREALLOCATE` as a last resort (unstable on ROCm).
4. Multi-camera high resolution (e.g., 3×480×848) significantly raises per-sample activation VRAM; if necessary, downscale images in the data pipeline before feeding the model (keep training/inference consistent).

---

## Appendix: Version list (verified working)

```
jax            0.6.0          (AMD ROCm, rocm7.0.2)
jaxlib         0.6.0
ml-dtypes      0.5.4          (★ required by jaxlib 0.6.0, do not use 0.4.1)
flax           0.10.2         (transitively pulls in optax 0.2.8)
orbax-checkpoint 0.11.13
chex           0.1.90
torch          2.7.1+cpu
torchvision    0.22.1+cpu
torchcodec     0.5            (CPU build)
lerobot        0.6.0          (--no-deps to bypass hf-hub conflict)
transformers   4.53.2
huggingface-hub 0.36.2
numpy          2.2.6
ffmpeg         6.1.1          (apt, Ubuntu 24.04)
openpi         0.1.0          (editable, --no-deps)
```
