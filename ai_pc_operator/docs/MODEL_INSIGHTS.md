# Screen-AI Model Insights

Updated: 2026-07-25 17:55:31 +05:30

This file summarizes how the inspected local models are used by the runtime.
The backend source of truth is `app/runtime/model_insights.py`.

## Runtime Policy

- Rules, native ranking, UIA scanning, and simple tools stay resident.
- OCR detection and recognition are the fast perception lane.
- Qwen2.5 Coder 1.5B Q4 stays SSD-backed through mmap and loads only when the budget allows.
- OmniParser v2 icon detection is a teacher/high-confidence fallback, not a default 4GB resident model.
- Phone-side JavaScript memory gives instant route hints while the backend builds the safe executable plan.

## Models

| Model | Role | Format | Low-resource use |
|---|---|---|---|
| Qwen2.5 Coder 1.5B Instruct Q4_0 | planner/reasoner | GGUF | SSD mmap, 512-768 ctx, 2 threads, no prefetch |
| OCR det v3 | text box detector | ONNX opset 14 | warm/resident when OCR budget exists |
| OCR rec English | text recognizer | ONNX opset 14 | warm with detector, input height 48 |
| OmniParser v2 icon detect | teacher icon detector | Ultralytics YOLO | cloud teacher or explicit fallback only |

## Inspection Facts Wired Into Code

- Qwen context length: 32768
- Qwen layers: 28
- Qwen embedding length: 1536
- Qwen heads/KV heads: 12/2
- OCR detector input/output: `N x 3 x H x W` -> `N x 1 x H x W`
- OCR recognizer input/output: `N x 3 x 48 x W` -> `N x T x 438`
- OmniParser report: YOLO scale `m`, `nc=1`, file size about 38.74 MB

## Parallel Lanes

- `fast-perception`: OCR detector + OCR recognizer + UI detector fallback.
- `browser-tools`: Playwright/browser warmup for search, browse, research, download.
- `secure-vault`: crypto warmup for password/passkey flows.
- `reasoning`: Qwen mmap load for complex or unknown commands.
- `teacher`: OmniParser teacher for cloud distillation or explicit fallback.
