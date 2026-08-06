# Content Studio — Project Description

## 2026 AMD AI DevMaster Hackathon · Track 1: Multimodal Content Creation

---

## 1. Project Background

Content creators on Chinese social media platforms (WeChat Official Accounts, Xiaohongshu) face a repetitive, multi-step workflow: write articles, style photos, place images, format for each platform, and manually publish. Existing tools address fragments of this pipeline but none integrate AI-powered text generation, image styling, intelligent image placement, and direct publishing into a single tool — especially one powered by AMD Radeon GPU + ROCm.

Content Studio fills this gap. Users upload photos, type a theme, and get a complete, ready-to-publish article with AI-styled images logically placed throughout — all on AMD GPU infrastructure.

## 2. Target Users & Use Cases

| User | Scenario |
|---|---|
| **Social media operators** | Daily batch content production for WeChat / Xiaohongshu accounts |
| **Independent creators** | Turn personal photos + ideas into polished articles in minutes |
| **Small business marketing** | Generate promotional content from product photos |
| **Content teams** | Pre-generate drafts for review, then publish via API |

## 3. System Architecture

```
┌─────────────────────────────────────────────┐
│           User Web Interface                │
│    (FastAPI + Jinja2 + PyWebView)           │
├─────────────┬───────────────┬───────────────┤
│  Text Gen   │  Image Gen    │  Publishing   │
│             │               │               │
│ Radeon Cloud│ ComfyUI       │ WeChat API    │
│ API (AMD)   │ (ROCm/AMD)    │               │
│             │               │               │
│ Qwen3.6-35B │ DreamShaper 8 │ /draft/add    │
│ Qwen2.5-VL  │ img2img+txt2img│ uploadimg    │
│             │               │ add_material  │
├─────────────┴───────────────┴───────────────┤
│          Vision Understanding                │
│    Model reads photo content → places        │
│    each image in its most relevant section   │
└─────────────────────────────────────────────┘
```

### Key Design Decisions

1. **Decoupled architecture:** `core/` is completely UI-independent, tested in isolation (92 tests). All external services (LLM, ComfyUI, WeChat) communicate via HTTP — mockable, replaceable.

2. **Provider-agnostic LLM:** Any OpenAI-compatible API works. Switching models = change config, not code. Supports: Radeon Cloud (free/shared + dedicated vLLM), Qwen/DashScope, GLM, DeepSeek, Kimi.

3. **Graceful degradation:** ComfyUI unreachable → falls back to original photos (no crash). Vision model unsupported → falls back to text-only generation. JSON parse fails → extracts from surrounding text.

4. **Per-photo style selection:** Each uploaded photo gets its own style dropdown. "Unify all" option for bulk styling. Style drives ComfyUI workflow + LLM writing tone + t2i prompts.

## 4. Model & Algorithm Description

### 4.1 Text Generation Pipeline

- **LLM:** Qwen3.6-35B-A3B (Radeon Cloud free API) or Qwen2.5-VL-7B-Instruct (dedicated vLLM)
- **Output:** Structured JSON (title, summary, cover_prompt, body_html, image_captions, image_prompts)
- **Robust parsing:** Code-fence stripping, prose extraction, repair re-request, raw fallback
- **Article templates:** Product review, event promo, tutorial, industry analysis — each injects structural guidance

### 4.2 Image Style Transfer (img2img)

- **Engine:** ComfyUI with DreamShaper 8 checkpoint on AMD GPU (ROCm 6.2)
- **Workflow:** LoadImage → VAEEncode → KSampler (denoise 0.55, 20 steps, euler sampler) → VAEDecode → SaveImage
- **8 preset styles:** anime, cyberpunk, watercolor, retro, minimal, oil painting, ink wash, pixel art
- **Per-style visual keywords:** Injected into CLIPTextEncode positive prompt
- **Pre-upload compression:** Images >1MB auto-resized to 1024px JPEG quality 85 (avoids tunnel size limits)

### 4.3 Text-to-Image (txt2img)

- **Engine:** ComfyUI with DreamShaper 8, EmptyLatentImage (512×512), 22 steps, denoise 1.0
- **Prompt source:** LLM-generated `image_prompts` (English descriptions based on article theme)

### 4.4 Vision-Based Image Placement

- **Model:** Qwen2.5-VL-7B-Instruct (vision-language model on AMD GPU)
- **Process:** Photos sent as base64 to the LLM → model reads content (text on screenshots, scenes, objects) → places `[[IMG:k]]` markers at most relevant sections
- **Fallback:** If model doesn't use markers, system converts Chinese "图N" references and distributes images after section headers

### 4.5 Image Weaving Algorithm

The `weave_images()` function handles three placement patterns:
1. Explicit markers: `[[IMG:k]]` → photo k at that position
2. Model-wrapped: `<img src="[[IMG:k]]">` → entire tag replaced with styled img
3. Fallback: Unused images distributed after `<h2>/<h3>` headers (reverse insertion to avoid position shift)

### 4.6 WeChat Draft Publishing

- **Token management:** access_token cached, auto-refreshed 5 min before expiry, 40001 retry
- **Body images:** `/media/uploadimg` → content-embedded URLs
- **Cover:** `/material/add_material?type=image` → thumb_media_id
- **Draft:** `/draft/add` with full article structure

## 5. AMD Radeon GPU / ROCm Adaptation

### 5.1 Compute Paths

| Component | AMD GPU Usage | ROCm Stack |
|---|---|---|
| Text generation | Qwen3.6-35B on Radeon Cloud free API | Radeon Cloud managed |
| Text generation (dedicated) | Qwen2.5-VL-7B via vLLM on dedicated instance | ROCm 6.2, PyTorch 2.5.1+rocm6.2 |
| Image style transfer | DreamShaper 8 via ComfyUI img2img | ROCm 6.2, gfx1100 arch |
| Text-to-image | DreamShaper 8 via ComfyUI txt2img | Same |
| Vision understanding | Qwen2.5-VL reads photos for placement | Same as text generation |

### 5.2 Hardware Verified

- **GPU:** AMD Radeon Graphics, gfx1100 (RDNA3)
- **VRAM:** 49,136 MB (48 GB)
- **ROCm:** 6.2
- **PyTorch:** 2.5.1+rocm6.2
- **Performance flags:** `torch.backends.cudnn.enabled = False` (better AMD performance), `--use-split-cross-attention`

### 5.3 Performance Data

| Operation | Time |
|---|---|
| Text generation (free API, Qwen3.6-35B) | 8–300s (shared, variable) |
| Text generation (dedicated vLLM, Qwen2.5-VL-7B) | 2–30s (exclusive GPU) |
| Image style transfer (img2img, 1024px, 20 steps) | 5–15s/image |
| Text-to-image (512px, 22 steps) | 5–10s/image |
| App startup (deferred openai import) | ~1.4s |
| Cover generation (txt2img + crop) | 8–15s |

### 5.4 Deployment Guide

**Option A: Free Shared API (fastest start)**
1. Register at [Token Factory](https://developer.amd.com.cn/radeon/modelapis)
2. Copy API Key for Qwen3.6-35B-A3B
3. Paste into Content Studio Settings → `radeon` provider

**Option B: Dedicated vLLM Instance (best performance)**
1. Radeon Cloud → Add Template → Deploy Type: vLLM Model API
2. Serve: `vllm serve Qwen/Qwen2.5-VL-7B-Instruct --host 0.0.0.0 --port 8000 --max-model-len 8192`
3. Copy Base URL + API Key from instance details

**Option C: ComfyUI on ROCm (image styling)**
1. Radeon Cloud → JupyterLab instance
2. Run: `bash scripts/setup_comfyui_rocm.sh` (installs ROCm PyTorch + ComfyUI + DreamShaper 8)
3. Expose port 8188 via SSH tunnel or tunnel service
4. Set ComfyUI Base URL in Content Studio Settings

## 6. Innovation Highlights

1. **Vision-driven image placement:** Unlike tools that dump images at the end, Content Studio's vision model reads each photo's content and places it beside the most relevant paragraph — screenshot of "3DMark" goes to the 3DMark section, "BurnIn" goes to the BurnIn section.

2. **Style-unified pipeline:** One style preset simultaneously drives image styling (ComfyUI keywords), writing tone (LLM prompt), and t2i generation prompts.

3. **Auto-detect vision capability:** System automatically detects whether the LLM supports vision. If not, falls back to text-only generation without user intervention.

4. **Direct API publishing:** One click sends the complete article (with uploaded images) to WeChat's draft box — no manual copy-paste.

5. **Dual-platform output:** Simultaneously generates WeChat articles (2.35:1 covers, ≤900px body) and Xiaohongshu posts (3:4 portraits, cover text overlay, hashtags) from the same input.

## 7. What's Included

- **92 automated tests** (pytest, covering all core modules)
- **Complete source code** (FastAPI + Jinja2 + ComfyUI integration + WeChat API)
- **Desktop application** (PyWebView, packaged as .exe via PyInstaller)
- **ROCm migration guide** (step-by-step AMD GPU deployment)
- **Demo script** (5-minute judge walkthrough)
- **Product showcase page** (auto GPU detection)
- **Self-diagnostic page** (LLM/ComfyUI/WeChat health check)
