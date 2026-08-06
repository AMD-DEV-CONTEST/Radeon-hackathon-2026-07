# sd_disable_initialization.py Patch — AMD ROCm Compatibility

## 1. What this patch fixes

The A1111 WebUI's `modules/sd_disable_initialization.py` contains a hook that
stops the CLIP text encoder from downloading weights during model loading
(offline mode). The original hook calls:

```python
self.CLIPTextModel_from_pretrained(None, *model_args, config=pretrained_model_name_or_path, state_dict={}, **kwargs)
```

where `pretrained_model_name_or_path` is a **string** (e.g.
`"openai/clip-vit-large-patch14"`). Under `transformers>=4.40`, that string is
passed into `cached_file(None, config.json)`, which triggers a network request
to `https://huggingface.co/None/resolve/main/config.json` → **404**.

The exception is raised inside a background model-loading thread and silently
swallowed, so the WebUI process stays alive but never finishes building the
SDXL model — the classic "hang" / frozen at
`Creating model from config: ...sd_xl_base.yaml`.

## 2. What the patch does

It replaces the string config with an **offline-constructed**
`transformers.CLIPTextConfig` object:

1. First it tries `CLIPConfig.from_pretrained(path, local_files_only=True)`
   so a locally cached real config is used when available.
2. If the model is not cached locally (no network allowed), it falls back to a
   hard-coded CLIP ViT-L/14 text config (vocab 49408, 12 layers, hidden 768).

The `CLIPTextModel_from_pretrained` wrapper then receives a config *object*
instead of a repo id string, so `transformers` never performs a network lookup.

## 3. Why this matters on AMD ROCm

- `open-clip-torch` and `transformers` are pulled from PyPI, whose latest
  versions behave differently from the versions A1111 was built for. On this
  server `transformers==4.40.2` exhibits the `cached_file(None, ...)` bug.
- PyPI/`pytorch.org` are partially unreachable in this deployment, so the
  "download the real config from HF" path is not a reliable fallback — the
  patch must work fully offline.
- The upstream `--disable-clip` flag already forbids weight downloads; this
  patch is the missing piece that also forbids the *config* download.

## 4. Files

| File | Purpose |
| --- | --- |
| `sd_disable_initialization.patch` | `git diff` against the unpatched file |
| `sd_disable_initialization.py` (source copy) | The fully patched file, ready to drop in |

## 5. How to apply

```bash
cd /workspace/stable-diffusion-webui
git apply patches/sd_disable_initialization.patch     # or: cp source file into modules/
```

or manually replace `modules/sd_disable_initialization.py` with the provided
patched copy.

## 6. Environment this was validated on

- OS: Ubuntu/Debian container, Python 3.12.3
- GPU: AMD Radeon Pro W7900D (gfx1100), ROCm 7.2.1
- PyTorch: `torch 2.9.1+rocm7.2.1` (shared env `/persistent/amd_ai_env`)
- transformers: `4.40.2` (in `/persistent/webui_env`)
- A1111 WebUI v1.10.1

Result: SDXL base 1.0 loads and generates images with no network access.
