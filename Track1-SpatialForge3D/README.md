# SpatialForge 3D

**Track 1: Multimodal Content Creation Tools**
**AMD AI DevMaster Hackathon 2026**

A local-first 3D asset creation tool. Give it a photo or a sentence, get back an
interactive 3D mesh and a rendered turntable video. Every inference stage runs on
an AMD Radeon GPU through ROCm. No cloud APIs are used for any core function.

---

## What it does

| Input | Output |
|---|---|
| A single photograph | Textured `.glb` mesh + 640p turntable `.mp4` |
| A text prompt | Same, via an intermediate generated image |

Two generation modes with a deliberate speed/fidelity tradeoff:

- **Fast (TripoSR)** — about 3 seconds end to end, vertex-colored mesh, roughly
  45K vertices. For rapid iteration and previewing.
- **Quality (TripoSG)** — rectified-flow shape synthesis at a 505³ grid,
  substantially higher geometric fidelity, followed by CPU smoothing,
  decimation, and photographic surface projection.

Track 1 creation tasks covered: **text-to-image**, **image-to-video**, and
**text-to-video**.

---

## Hardware and environment

Developed and benchmarked entirely on the AMD Radeon Cloud instance provided for
this hackathon.

| Component | Version |
|---|---|
| GPU | AMD Radeon Graphics, `gfx1100` (Navi 31), 48 GB VRAM |
| ROCm | 7.2.1 |
| PyTorch | 2.9.1 (ROCm build) |
| Python | 3.12 |
| Container image | `amd-oneclick-base:rocm7.2.1-py3.12-v20260416` |

Peak VRAM with all models resident: **12.97 GB of 48 GB (27%)**. The pipeline
fits comfortably on consumer Radeon cards, not only workstation hardware.

---

## Quick start

### 1. Launch the environment

On Radeon Cloud, create a template with:

- Container image: `AMD OneClick Base (amd-oneclick-base:rocm7.2.1-py3.12-v20260416)`
- Deploy type: `Notebook (Jupyter / OpenCode)`
- Storage: **Persistent (PVC)**
- SSH access: enabled

Launch it and open a terminal.

### 2. Clone and set up

```bash
cd /persistent
git clone <this-repo> spatialforge
cd spatialforge
bash setup.sh
```

`setup.sh` handles everything below. If you prefer to run the steps manually,
see [Manual setup](#manual-setup).

### 3. Run

```bash
source /persistent/venv_sg/bin/activate
export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME=/persistent/hf_cache
python spatialforge_app.py
```

The web UI starts on `http://127.0.0.1:7860`. To expose it publicly from the
Radeon Cloud instance:

```bash
/var/run/secrets/frp-self-service/install
export PATH="$HOME/.local/bin:$PATH"
rc-tunnel expose --port 7860
```

First launch downloads roughly 3.5 GB of model weights. Subsequent launches load
from the persistent cache in about 22 seconds.

---

## Manual setup

Three environment-specific issues on the Radeon Cloud instance are worth
documenting, since they will affect anyone reproducing this work.

### TLS interception

The instance sits behind a TLS-intercepting proxy that presents a self-signed
certificate, so `git clone` and `pip` fail certificate verification. Trust the
proxy's certificate rather than disabling verification:

```bash
openssl s_client -showcerts -connect github.com:443 </dev/null 2>/dev/null \
  | openssl x509 -outform PEM > /usr/local/share/ca-certificates/proxy.crt
cat /usr/local/share/ca-certificates/proxy.crt >> $(python -c "import certifi; print(certifi.where())")
update-ca-certificates
export SSL_CERT_FILE=$(python -c "import certifi; print(certifi.where())")
export REQUESTS_CA_BUNDLE=$SSL_CERT_FILE
export GIT_SSL_CAINFO=$SSL_CERT_FILE
```

### HuggingFace routing

`huggingface.co` is unreachable from the instance (`Errno 101`). Use the mirror:

```bash
export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME=/persistent/hf_cache   # keep weights on persistent storage
```

`u2net.onnx` for background removal is normally fetched from GitHub release
assets, which are also blocked. Pull it from the mirror instead:

```bash
mkdir -p /root/.u2net
python -c "
from huggingface_hub import hf_hub_download; import shutil
p = hf_hub_download(repo_id='tomjackson2023/rembg', filename='u2net.onnx')
shutil.copy(p, '/root/.u2net/u2net.onnx')"
```

### Python environment

`/opt/venv` ships the ROCm PyTorch build but is **not** on persistent storage, so
packages installed there are lost when the instance is destroyed. Create a
persistent overlay venv that inherits the ROCm torch:

```bash
/opt/venv/bin/python -m venv --system-site-packages /persistent/venv_sg
source /persistent/venv_sg/bin/activate
echo "/opt/venv/lib/python3.12/site-packages" \
  > /persistent/venv_sg/lib/python3.12/site-packages/_base.pth
```

Then install dependencies:

```bash
# TripoSR
cd /persistent && git clone https://github.com/VAST-AI-Research/TripoSR.git
cd TripoSR && pip install -r requirements.txt onnxruntime
pip uninstall -y cupy-cuda12x   # CUDA build, breaks rembg on AMD

# TripoSG (strip the 2022-era numpy pin, which cannot build on Python 3.12)
cd /persistent && git clone https://github.com/VAST-AI-Research/TripoSG.git
cd TripoSG
grep -v -E "numpy==1.22.3|^diso" requirements.txt > /tmp/req_sg.txt
echo "transformers<5" >> /tmp/req_sg.txt
pip install -r /tmp/req_sg.txt
python patch_triposg.py          # see "ROCm portability work" below
pip install -U scikit-image scipy trimesh imageio-ffmpeg
```

---

## Dependencies

Installed into `/persistent/venv_sg`, layered over the ROCm PyTorch base image.

```
torch==2.9.1          (ROCm 7.2.1 build, from the base image)
diffusers
transformers<5
huggingface_hub
trimesh
scikit-image
scipy
pymeshlab
rembg + onnxruntime
gradio
imageio + imageio-ffmpeg
Pillow
omegaconf, einops, jaxtyping, typeguard
torchmcubes           (built from source, CPU fallback on ROCm)
xatlas, moderngl      (TripoSR texture baking)
```

Deliberately **not** installed: `diso` and `cupy-cuda12x`. Both are CUDA-only and
have no HIP path. See below.

---

## ROCm portability work

Two upstream dependencies assume CUDA and fail on ROCm. Both were worked around
without falling back to CPU-only execution for the model itself.

### `diso` (TripoSG)

TripoSG's surface extraction uses `diso.DiffDMC`, a differentiable dual marching
cubes implementation whose sources `#include <cuda_runtime.h>`. It cannot build
against HIP. `patch_triposg.py` replaces the extraction step with
`skimage.measure.marching_cubes` running on CPU, preserving the original
coordinate rescaling so meshes come out identically positioned. The transformer
and VAE — everything that determines output quality — continue to run on the
Radeon GPU.

Measured cost: **~800 ms** for a 505³ grid.

### `torchmcubes` (TripoSR)

Builds successfully against HIP but its CUDA kernels are not compiled, so it
prints `torchmcubes was not compiled with CUDA support, use CPU version instead`
and falls back automatically. Measured cost: **~1.5 s**.

Both are honest optimization targets. Marching cubes is now the single largest
non-GPU stage in the Quality pipeline, and a HIP port of either library would be
a direct contribution back to the AMD ecosystem.

---

## Architecture

```
              ┌──────────────┐
  text ──────►│ SDXL-Turbo   │──── generated image ────┐
              │ (GPU, 4 step)│                         │
              └──────────────┘                         ▼
                                              ┌─────────────────┐
  image ─────────────────────────────────────►│ Background      │
                                              │ removal         │
                                              │ u2net / BriaRMBG│
                                              └────────┬────────┘
                                                       │
                        ┌──────────────────────────────┴───────────┐
                        ▼                                          ▼
              ┌───────────────────┐                    ┌──────────────────────┐
              │ FAST              │                    │ QUALITY              │
              │ TripoSR           │                    │ TripoSG              │
              │ transformer (GPU) │                    │ rectified flow (GPU) │
              │ AOTriton attention│                    │ 50 steps, fp16       │
              └─────────┬─────────┘                    └──────────┬───────────┘
                        │                                         │
                        ▼                                         ▼
              ┌───────────────────┐                    ┌──────────────────────┐
              │ torchmcubes (CPU) │                    │ marching cubes (CPU) │
              │ vertex colors     │                    │ ROCm patch, 505³     │
              └─────────┬─────────┘                    └──────────┬───────────┘
                        │                                         ▼
                        │                              ┌──────────────────────┐
                        │                              │ Taubin smoothing     │
                        │                              │ Quadric decimation   │
                        │                              │ Surface color        │
                        │                              └──────────┬───────────┘
                        └────────────────┬────────────────────────┘
                                         ▼
                        ┌────────────────────────────────┐
                        │ .glb export                    │
                        │ Turntable MP4 (software raster)│
                        │ Live ROCm telemetry            │
                        └────────────────────────────────┘
```

### Surface color

Quality mode offers three approaches, all CPU:

1. **None (clay)** — neutral material, cleanest read of pure geometry.
2. **Photo + model fill** *(default)* — the input photograph is projected onto
   the visible surface, giving genuine texture detail; hidden surfaces fall back
   to TripoSR's predicted colors. The camera orientation is not assumed: the
   system rasterizes the mesh silhouette under all 24 axis-aligned rotations plus
   a fine angular sweep, and selects the orientation with the highest IoU against
   the input image's subject mask. Measured silhouette fit is reported in the
   telemetry panel.
3. **TripoSR colors** — vertex colors transferred from a parallel Fast pass via
   nearest-neighbor lookup after the same rotation search.

---

## Measured performance

All figures measured on `gfx1100` with `torch.cuda.synchronize()` around each
stage and `torch.cuda.max_memory_allocated()` for VRAM. Nothing is estimated.

### Fast mode, 14-asset batch

Mean over all 14 TripoSR example images, warm start, mesh grid 256:

| Stage | Mean |
|---|---|
| Background removal (u2net, CPU) | 8 ms |
| TripoSR inference (GPU, AOTriton attention) | **1051 ms** |
| Marching cubes (CPU fallback) | 1332 ms |
| GLB export | 40 ms |
| **End to end** | **2816 ms** |

- Inference range across 14 assets: 998–1389 ms
- Peak VRAM: **2.39 GB**, identical on every asset
- Failures: **0 of 14**

Reproduce with `python sf_bench.py --warmup`, which writes `BENCHMARK.md` and
`benchmark.csv` alongside the generated gallery.

### Quality mode, single asset

Mesh grid 505³, 50 flow steps, 400K target faces, photo projection, turntable on:

| Stage | Time | Device |
|---|---|---|
| Background removal (BriaRMBG) | 225 ms | GPU |
| TripoSG rectified flow, 50 steps | 42,965 ms | GPU |
| Marching cubes (ROCm CPU patch) | 928 ms | CPU |
| Taubin smoothing, 4 iterations | 699 ms | CPU |
| Quadric decimation, 3.4M → 400K faces | 87,840 ms | CPU |
| Photo projection (silhouette fit 0.62) | 901 ms | CPU |
| GLB export | 40 ms | CPU |
| Turntable render, 90 frames at 640p | 54,307 ms | CPU |
| **End to end** | **191,110 ms** | |

Peak VRAM: **12.97 GB of 48 GB (27%)** with SDXL-Turbo, TripoSR, TripoSG, and
BriaRMBG all resident simultaneously.

Decimation dominates and scales with the target face count. At the default
120K faces it drops to roughly 12 s, bringing end to end to about 90 s.

---

## Models

All open source, all running locally.

| Model | Role | License |
|---|---|---|
| [TripoSR](https://huggingface.co/stabilityai/TripoSR) | Fast image-to-3D | MIT |
| [TripoSG](https://huggingface.co/VAST-AI/TripoSG) | High-fidelity image-to-3D | MIT |
| [SDXL-Turbo](https://huggingface.co/stabilityai/sdxl-turbo) | Text-to-image | Stability Community |
| [u2net](https://github.com/danielgatis/rembg) | Background removal (Fast) | Apache-2.0 |
| [RMBG-1.4](https://huggingface.co/briaai/RMBG-1.4) | Background removal (Quality) | Non-commercial |

**Note:** RMBG-1.4 is licensed for non-commercial use. It ships as TripoSG's
default background remover. For commercial deployment, substitute BiRefNet or
u2net, both of which are already wired into the Fast path.

---

## Repository contents

```
spatialforge_app.py    Gradio web UI, both modes, telemetry
turntable.py           Software turntable renderer (no OpenGL)
projtex.py             Silhouette-matched photo projection
patch_triposg.py       ROCm patch replacing diso with CPU marching cubes
sf_bench.py            Batch benchmark harness
setup.sh               Full environment bootstrap (idempotent)
LICENSE                MIT
docs/                  Project profile PDF and presentation deck
BENCHMARK.md           Measured 14-asset results
gallery/               Generated meshes and turntable videos
```

## Demo video

**https://youtu.be/9RlgODDrjug **— 3 to 5 minutes: live Fast-mode
generation, Quality-mode turntables, text-to-3D, photo projection, and the
ROCm engineering summary.

---

## Known limitations

Stated plainly, since they are inherent rather than incidental.

- **Single-view reconstruction hallucinates unseen surfaces.** Both models infer
  the back of an object from one image. Geometry there is plausible, not
  measured.
- **Photo projection covers only the visible surface**, typically 20–30% of
  vertices. The remainder uses model-predicted color.
- **Vertex colors, not UV textures.** Fine detail such as sesame seeds or fabric
  weave is limited by vertex density. A baked UV texture would be sharper.
- **Marching cubes and decimation run on CPU** and now dominate Quality-mode
  latency. Both are HIP-portable in principle.
- **Layered or thin-edged subjects** (food, foliage) reconstruct less reliably
  than solid objects with clear silhouettes.

---

## License

Source code in this repository is released under the MIT License. Model weights
remain under their respective licenses as listed above.
