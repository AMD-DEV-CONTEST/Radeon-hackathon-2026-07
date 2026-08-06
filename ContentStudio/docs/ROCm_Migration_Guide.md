# ROCm Migration Guide (AMD Radeon GPU)

> A hands-on guide for migrating Content Studio · Web from "cloud LLM + DirectML placeholder" to "truly running on AMD Radeon GPU + ROCm".
> Prerequisite: a **Linux + AMD GPU** machine (ROCm is Linux-first; native Windows only offers DirectML, which is not ROCm).

## ⭐ Official Organizer Path: AMD Radeon Cloud (easiest, recommended starting point)

The organizer provides **Radeon Cloud** (cloud-hosted AMD Radeon GPUs) with two options — neither requires a local AMD card:

### Option 1 · Free Model APIs (text runs on AMD GPU, no instance, no quota cost)

A ready-to-use OpenAI-compatible endpoint serving Qwen/DeepSeek on AMD Radeon GPUs.

1. Go to https://developer.amd.com.cn/radeon/modelapis (Token Factory), log in → pick a model under Public Free Model APIs (e.g. `Qwen3.6-35B-A3B`) → copy your **API Key**.
2. In the app's Settings, select provider = **radeon**; the Base URL is pre-filled as `https://developer.amd.com.cn/radeon/api/v1`; set the model to `Qwen3.6-35B-A3B` (or `DeepSeek-V4-Flash`) and paste the API Key → Save.

**That's it: your text generation now runs on an AMD Radeon GPU, satisfying the track's "based on AMD GPU" requirement.** (`radeon` is a text-only model; do not enable "vision" — place images manually on the preview page.)

### Option 2 · Your Own Instance (run ComfyUI for images / dedicated models)

1. https://radeon-global.anruicloud.com/ → log in → Profile → Add Template (choose a container image; for SSH, add your public key in Profile first and enable SSH Access in the template) → Launch to start the instance.
2. Enter the instance (Open Notebook → JupyterLab terminal, or SSH). This is a **Linux + ROCm** environment.
3. **Image generation (ComfyUI)**: install ROCm PyTorch + ComfyUI on the instance (see §3 below), then point the app's ComfyUI Base URL in Settings to the instance address.
4. **Dedicated model API**: in the template, set Deploy Type = vLLM Model API with a serve command such as `vllm serve <model> --host 0.0.0.0 --port 8000`; after launch, use the instance's Base URL/Key as a provider.
5. **When finished, always go to Profile → Active Instance → Destroy Instance** (otherwise it keeps consuming quota).

> Option 1 is the fastest way to earn the "AMD GPU text" credit; Option 2 moves ComfyUI/dedicated models onto AMD GPUs too, completing the strongest "text + images both on AMD GPU" story.

---

## 0. Why No Code Changes Are Needed

The architecture is already decoupled:
- **Text**: `LLMClient` (`core/models.py`) is an **OpenAI-compatible client**. vLLM / Ollama / TGI all expose OpenAI-compatible APIs — just change `base_url` in the config from the cloud endpoint to `http://localhost:<port>/v1`; `generator.py`/`pipeline.py` stay untouched.
- **Images**: `comfy.py` talks to ComfyUI over HTTP (default `http://127.0.0.1:8188`). Once ComfyUI runs on Linux+ROCm it automatically uses ROCm/HIP — transparent to the client.

So migration = **install the ROCm stack + start local inference services + change 3 config items + swap 4 workflow JSONs**. No business-logic rewrite.

## 1. Prerequisite: Install ROCm

Install ROCm for your distribution per AMD's official docs (ROCm 6.1+ recommended). Verify:

```bash
rocm-smi                 # should show GPU and VRAM
/opt/rocm/bin/rocminfo   # should list agents
```

> Note: ROCm works best on RDNA3 (RX 7000 series); RDNA2 (6000 series) mostly works but needs `HSA_OVERRIDE_GFX_VERSION` (commonly `export HSA_OVERRIDE_GFX_VERSION=10.3.5` for the 6000 series). Older cards (Polaris/Vega) have limited support.

## 2. Text Inference: Run a Local ROCm Service

### Plan A (recommended): Ollama — simplest, uses ROCm automatically

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve                       # default :11434, OpenAI-compatible at /v1
ollama pull qwen2.5:7b-instruct    # or gemma2:2b / qwen2.5:14b (pick per VRAM, see §5)
```

### Plan B: vLLM — higher throughput (an inference-acceleration scoring point)

The official ROCm image is the easiest route:
```bash
docker run --network host --device /dev/kfd --device /dev/dri \
  -v ollama:/root/.ollama rocm/vllm:latest \
  --model Qwen/Qwen2.5-7B-Instruct --port 8000
```
Or install locally: install ROCm PyTorch per vLLM's ROCm documentation, then `pip install vllm`.

### Update the Config (same for both plans)

Fill in the web `/settings` page, or edit `~/.content_studio/config.json` directly:

```json
"providers": [
  {
    "name": "local-rocm",
    "base_url": "http://localhost:11434/v1",   // Ollama
    // "base_url": "http://localhost:8000/v1", // vLLM
    "api_key": "not-needed",                    // any value for local services
    "model": "qwen2.5:7b-instruct"              // must match the pulled model
  }
],
"active_provider": "local-rocm"
```

## 3. Image Inference: ComfyUI on ROCm (fastest: one-shot script)

Copy `scripts/setup_comfyui_rocm.sh` from this repo to the Radeon Cloud instance (or `git clone` this repo inside the instance), then run in the instance terminal:

```bash
bash setup_comfyui_rocm.sh
```

The script automatically: installs ROCm PyTorch → clones and installs ComfyUI → downloads a starter model (DreamShaper 8) → launches ComfyUI (`0.0.0.0:8188`).

**Connect the local app to the instance's ComfyUI (SSH tunnel, most reliable)** — open a terminal on your **local Windows** machine and forward the instance's port 8188:
```
ssh -L 8188:localhost:8188 <user>@<host> -p <port>
```
Find `<user>/<host>/<port>` under SSH access in the instance details. Once the tunnel is up, keep the app's "Settings → ComfyUI Base URL" at **`http://127.0.0.1:8188`** — traffic flows through the tunnel straight to the instance's ComfyUI (AMD GPU). Confirm ComfyUI is enabled in Settings.

Verify the GPU is working: open another terminal on the instance and run `rocm-smi` — `GPU-UTIL` should be non-zero.

## 4. Workflow JSONs (pre-configured and usable; usually no changes needed)

`content_studio/styles/workflows/*.json` are already **working img2img workflows** (LoadImage→VAEEncode→KSampler→VAEDecode→SaveImage, model `dreamshaper8.safetensors` — the same one downloaded by the §3 script; they keep the `{positive}`/`{input_image}`/`{seed}` placeholders for code injection). **Once the §3 script has run, picking a style generates images directly — no manual export needed.**

To swap models / add LoRA / tune style strength: build the workflow in the ComfyUI web UI (`http://127.0.0.1:8188`) → export via "Settings → Save (API format)" → overwrite the corresponding `*.json`, and **be sure to keep** the three placeholder strings `{positive}`, `{input_image}` (LoadImage), and `{seed}` (KSampler).

## 5. VRAM / Model Selection

| Your GPU | VRAM | Recommended text model | SDXL images |
|---|---|---|---|
| RX 7600 / 7600 XT | 8–16GB | Gemma-2-2B or Qwen2.5-1.5B (INT4) | needs `--lowvram` |
| RX 7700 XT / 7800 XT / 7900 GRE | 12–16GB | Qwen2.5-7B (AWQ INT4 ≈5GB) | OK |
| RX 7900 XT / XTX | 20–24GB | Qwen2.5-14B (AWQ INT4 ≈9GB) | comfortable |

Quantization = the lightweight-deployment scoring point: prefer AWQ/GPTQ INT4 builds (e.g. `Qwen2.5-7B-Instruct-AWQ`) — half the VRAM, faster inference.

## 6. Track Scoring Rubric Mapping (after migration)

| Criterion | How it is demonstrated |
|---|---|
| **Inference acceleration** | Show GPU utilization with `rocm-smi` during the demo; vLLM continuous-batching tokens/s; compare "cloud API round-trip" vs "local ROCm inference" latency. |
| **Lightweight deployment** | Single-machine all-in-one (FastAPI + local inference + ComfyUI on one GPU box); INT4 quantization fits large models into consumer VRAM. |
| **Style customization** | Already built in: three-in-one style presets (ComfyUI image styling + LLM writing style + text-to-image prompts). |
| **Image quality optimization** | Already built in: `image_pipeline` (2.35:1 covers, 900px width cap, watermark, JPEG compression) + ComfyUI style transfer. |

## 7. Acceptance Checklist (go through item by item when migration is done)

- [ ] `rocm-smi` shows the GPU.
- [ ] The active provider in `/settings` is `local-rocm`, with base_url pointing at localhost.
- [ ] Generate an article: text comes from the local GPU (verify by disconnecting from the internet — if generation still works, nothing goes through the cloud).
- [ ] `rocm-smi` shows GPU usage while ComfyUI jobs run.
- [ ] The 4 workflow JSONs have been replaced with real exports, keeping the `{positive}`/`{input_image}`/`{seed}` placeholders.
- [ ] Both style transfer and text-to-image produce images.
- [ ] "Send to draft box" still delivers the finished article to the WeChat Official Account draft box.

## 8. Rollback

If migration hits problems, switch `active_provider` back to a cloud provider (e.g. `deepseek`) to instantly fall back to cloud text; if ComfyUI is unreachable, the pipeline automatically degrades to original images (see the ComfyError branch in `pipeline.py`) without blocking article generation.
