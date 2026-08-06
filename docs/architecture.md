# Architecture

## System overview

The Explainable AI Radiology Assistant is a full-stack application that
combines computer vision, natural language generation, and custom AMD GPU
kernels into an interactive clinical-assistant demo.

## Data flow

```
+-------------+    +---------------------+
|  User uploads| -> |  Chest X-ray image  |
+-------------+    +----------+----------+
                                    |
                                    v
                    +-------------------------------+
                    |  ChestXRayClassifier           |
                    |  - predicts findings           |
                    |  - outputs confidence scores   |
                    +---------------+---------------+
                                    |
                                    v
                    +-------------------------------+
                    |  XRayLocalizer                 |
                    |  - generates masks/heatmaps    |
                    |  - default regions per finding |
                    +---------------+---------------+
                                    |
                                    v
                    +-------------------------------+
                    |  ReportGenerator               |
                    |  - Ternary-Bonsai-27B or       |
                    |    tiny ternary surrogate      |
                    |  - produces structured report  |
                    +---------------+---------------+
                                    |
                                    v
                    +-------------------------------+
                    |  FastAPI backend               |
                    |  - /api/analyze                |
                    |  - /api/chat                   |
                    |  - /api/benchmark              |
                    +---------------+---------------+
                                    |
                                    v
                    +-------------------------------+
                    |  React frontend                |
                    |  - image viewer with overlays  |
                    |  - interactive report          |
                    |  - conversational assistant    |
                    |  - benchmark dashboard         |
                    +-------------------------------+
```

## Explainability

The key UX feature is the link between report text and image regions.

- Each finding carries a default bounding box / mask.
- The combined mask is returned as a base64 PNG overlay.
- Report terms that match finding labels are rendered as hoverable spans.
- On hover, the viewer shows the bounding box and increases overlay opacity.

## ROCm acceleration

- Weights in `TernaryLinear` are quantized to `{-1, 0, +1}`.
- A custom HIP kernel packs four weights into one byte and performs GEMM
  without expanding to full precision.
- `TernaryGemmFunction` integrates the kernel with PyTorch.
- Benchmark endpoint compares baseline dense FP32 vs ternary ROCm.

## Extensibility

- `ChestXRayClassifier` can be swapped for any HuggingFace image model via
  `CLASSIFIER_MODEL`.
- `XRayLocalizer` is a placeholder for a real segmentation model.
- `ReportGenerator` supports loading Ternary-Bonsai-27B when available.
