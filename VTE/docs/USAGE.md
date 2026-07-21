[← Back to README](../README.md)

# Getting started: the Python API and desktop UI in detail

Installation and the fastest path to a running desktop app are covered in the [Quick start](../README.md#quick-start) section of the main README. This page covers the plain Python API and desktop-UI specifics that only matter once it's installed.

## Where models go

Drop a `.gguf` file into `Model/` (a subfolder like `Model/Classifier/` works too: the scan is recursive). That's it: no code to edit, no registry to update. `VTEModel.from_pretrained()` resolves a model name two ways:

1. **A curated name** (`"qwen2.5:1.5b-q4_k_m"`, `"granite-4.1:3b-q8_0"`, `"qwen3.5:2b-q6_k"`): the three architectures this project was built and measured against, mapped in `VTEModel.MODEL_REGISTRY`.
2. **The filename itself** (minus `.gguf`): anything else found under `Model/`. `VTEModel.discover_models()` returns the full map if you want to see what's available: `{"Qwen2.5-7B-Instruct.Q4_K_M": Path("Model/Qwen2.5-7B-Instruct.Q4_K_M.gguf"), ...}`.

```python
from vte.core.model import VTEModel

# curated name
model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", context_length=8192)

# or just the filename of whatever you dropped in Model/: no registry entry needed
model = VTEModel.from_pretrained("Qwen2.5-7B-Instruct.Q4_K_M", context_length=8192)
```

Either way, the file is validated before loading: the GGUF's own `general.architecture` metadata has to be one of the supported families (`qwen2`, `granite`, `qwen3.5`: checked in `vte/compiler/sanitizer.py`, an unsupported architecture is rejected with a clear error). A recognized architecture but an unfamiliar size (`block_count`/file size that doesn't match a variant already validated on real hardware) isn't rejected: it loads with a generic size sanity check instead of the tighter one calibrated per known variant, and logs a warning saying so. Worth reading that warning if it shows up: it means this specific model size hasn't been run against real hardware by this project yet.

## Python API

```python
from vte.core.model import VTEModel

model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", context_length=8192)

for token in model.generate("Summarize the tradeoffs of static batching:", max_tokens=300):
    print(token, end="", flush=True)
```

Switching architectures is just a different `model_name`: everything else about the API is identical (see [Multi-architecture support](GRANITE.md) for what actually changes under the hood):
```python
model = VTEModel.from_pretrained("granite-4.1:3b-q8_0", context_length=8192)

for token in model.generate("Summarize the tradeoffs of static batching:", max_tokens=300):
    print(token, end="", flush=True)
```

Batched decode (same-length prompts only, see [Known limitations](LIMITATIONS.md)):
```python
model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", max_batch_size=4)

prompts = ["The capital of France is", "2 + 2 equals", "My favorite color is", "Once upon a time"]
for words in model.generate_batch(prompts, max_tokens=200, temperature=0.7):
    print(words)  # one word per sequence, per generation tick
```

`VTE_TOPK_LOGITS_READBACK=1` (env var, off by default): reduces the logits readback to a small GPU-side candidate set for greedy decode (`temperature=0`) only. Bit-identical to the default path, with a small, model-size-dependent tok/s gain. See [Performance](PERFORMANCE.md#gpu-side-top-k-logits-reduction-2026-07).

## Desktop UI

The UI (chat + live dashboard: tok/s, ms/token, VRAM, model lifecycle, logs; language toggle between Portuguese and English) lives entirely in [vte/ui/app.py](../vte/ui/app.py), a Flet 0.85+ app. Setup and launch are covered in [Quick start](../README.md#quick-start) (`pip install -e .[dev]` then `vte-ui`): the notes below are specifics that only matter once it's running.

It needs `vte` to be an *importable package*, not just a folder of scripts: running the file directly with a system-wide Python (`python vte/ui/app.py`) fails with `ModuleNotFoundError: No module named 'vte'`, because that Python has never heard of this project. `python -m vte.ui.app` is the fallback if the `vte-ui` console script isn't on `PATH` for some reason: the `-m` runs it *as a module* inside the `vte` package, which is what makes the relative imports resolve; running the file by path does not, even with `.venv` activated.

**Windows-only telemetry dependencies** (`WMI`, `pywin32`, both in `pyproject.toml`) are what let the dashboard read real GPU numbers (dedicated VRAM usage, matching what Task Manager's GPU tab shows) instead of placeholders. Without them the dashboard still works, just with less data. Real GPU temperature needs no extra package: it goes through AMD's ADL (`atiadlxx.dll`, ships with every AMD driver) via [vte/bridge/adl_bridge.py](../vte/bridge/adl_bridge.py), but only works on an AMD GPU; on anything else (or if ADL fails for any reason) the dashboard shows "N/A" rather than a fabricated number.

The GGUF itself goes in a `Model/` folder (see [Where models go](#where-models-go) above): `VTEModel.from_pretrained()` checks it both relative to the current working directory and relative to the repo root, so it's found whether you run from the project folder or invoke `vte-ui` from anywhere else (a fresh shell, a shortcut, another terminal tab). If neither location has it, the error message prints both full paths it checked.

**MSVC Build Tools are usually not needed.** HIP kernels are normally compiled at runtime by `hipcc`, which on Windows needs MSVC, but this project ships precompiled kernels (`vte/core/assets/kernels/`) for `gfx1102` (RX 7600, the card this project is built and tested on), `gfx1100` (RX 7900 series), and `gfx1101` (RX 7600 XT/7700/7800 series). On first use, `CodegenEngine` copies the matching precompiled kernel into the local cache instead of invoking `hipcc`: MSVC never gets involved. If a precompiled kernel fails to load (a driver/ROCm version mismatch: code objects aren't guaranteed forward/backward compatible across ROCm releases), it's discarded automatically and recompiled locally, which *does* need `hipcc`+MSVC at that point. Anyone on RDNA2 or an architecture not listed above needs the [HIP SDK](https://www.amd.com/en/developer/resources/rocm-hub/hip-sdk.html) + [MSVC Build Tools](https://visualstudio.microsoft.com/pt-br/downloads/?q=build+tools) from the start, since there's nothing precompiled to fall back on. See [Bugs found during development](BUGS.md) and [Known limitations](LIMITATIONS.md) for the full story, and `scripts/build_kernel_cache.py`/`scripts/cross_compile_kernel_cache.py` if you're extending the precompiled set.
