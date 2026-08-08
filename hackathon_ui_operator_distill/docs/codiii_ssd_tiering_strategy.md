# codiii-Inspired SSD Tiering Strategy

Screen-AI should not think in only two modes:

```text
small model local
large model cloud
```

The `codiii` / Colibri idea is stronger:

```text
fast resident core + SSD-backed cold model parts + cache + prefetch
```

The original `codiii` repo demonstrates running a huge MoE model by keeping dense/shared parts resident and streaming routed experts from SSD on demand. Screen-AI can borrow the same systems idea, but adapted to screen parsing.

## What Transfers From codiii

Useful ideas:

- resident core stays in RAM
- heavy modules live on SSD
- lazy loading only when needed
- LRU cache for recently used modules/results
- hot-store for common modules
- prefetch likely next modules
- quantized weights
- RAM budget enforcement
- read-only SSD streaming
- cold path can be slower, warm path should get faster

## What Does Not Transfer Directly

OmniParser is not a giant MoE model with thousands of routed experts.

So we cannot stream OmniParser experts exactly like Colibri streams GLM experts.

Instead, we tier **pipeline modules**:

```text
resident:
  UI Automation scanner
  OpenCV scanner
  action executor
  last UI map cache

warm-load:
  OCR model
  tiny YOLO/ONNX UI detector

cold-load / SSD:
  Florence/OmniParser-style captioning
  heavy icon captioning
  teacher parser
```

## Screen-AI Runtime Tiers

### Tier 0: Always Resident

Memory target: below 250 MB.

```text
Windows UI Automation
OpenCV candidate detector
rule-based command matcher
click executor
JSON logger
```

### Tier 1: Warm Cache

Loaded only after Tier 0 fails.

```text
PaddleOCR mobile
YOLOv8n INT8 ONNX
```

Unload after idle timeout.

### Tier 2: SSD Cold Modules

Loaded only for difficult screens.

```text
OmniParser/Floorence-style screen captioning
icon captioning
large teacher models
```

For 4 GB laptops this tier is experimental and should be optional.

### Tier 3: Cloud AMD GPU

Used when local cold tier is too slow.

```text
teacher labeling
training
distillation
benchmarking
ROCm demo
```

## Practical Design

The local runtime should choose like this:

```text
click "Share"
↓
Tier 0: UIA exact label
↓ fail
Tier 1: OCR text detection
↓ fail
Tier 1: tiny detector finds possible buttons
↓ fail
Tier 2: heavy parser from SSD
↓ fail/slow
Tier 3: cloud AMD parser
```

## SSD Cache Files

```text
.screen_ai_cache/
  ui_maps/
  screenshots/
  ocr_results/
  detector_results/
  heavy_parser_results/
  models/
```

Cache key:

```text
screen_hash + active_window_title + monitor_resolution
```

If the same screen appears again, Screen-AI can reuse previous element maps.

## Why This Helps 4 GB RAM

We do not need to keep all AI models in memory.

The machine keeps only:

- current screenshot
- UI map
- small resident scanner
- one optional model at a time

Heavy models can stay on SSD or cloud until needed.

## Implemented Runtime Knobs

The backend now exposes a live Screen-AI adaptation of these ideas:

```powershell
$env:SCREEN_AI_RAM_MB="1200"
$env:SCREEN_AI_MMAP="1"
$env:SCREEN_AI_PREFETCH="0"
$env:SCREEN_AI_ALLOW_COLD_LLM="0"
$env:SCREEN_AI_LLM_CTX="512"
$env:SCREEN_AI_LLM_THREADS="2"
```

The runtime maps these to:

- resident: rules, router, UIA/OpenCV scanner
- warm: small OCR/detector artifacts
- SSD-cold: optional mmap-loaded GGUF or model artifacts
- SSD-off: too heavy for current memory budget

`GET /runtime` reports the current placement plan.

## Hackathon Story

Screen-AI is not just a desktop clicker.

It is a tiered AI runtime:

```text
low-resource local control
+ SSD-backed heavy perception
+ AMD ROCm cloud acceleration for training/distillation
```

This directly follows the spirit of `codiii`: use storage intelligently so weaker hardware can still access stronger AI capability.
