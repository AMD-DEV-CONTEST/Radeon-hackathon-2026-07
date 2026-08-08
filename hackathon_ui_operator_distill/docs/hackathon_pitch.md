# Hackathon Pitch

## Track

Track 2: Agentic AI

## Project

Local AI PC Operator: a lightweight desktop control agent that scans the screen, identifies UI elements, and clicks or types into the correct target from user text commands.

## Innovation

The project uses a teacher-student design:

- OmniParser v2 runs on cloud GPU to generate high-quality screen element labels.
- A tiny student model runs locally on low-resource laptops.
- Windows UI Automation and OCR are fused with model predictions for accuracy.
- Critical actions can later require phone approval.

## AMD/ROCm Angle

The cloud training and inference experiments can be run on AMD Radeon/ROCm hardware. The demo can compare:

- CPU local screen scan
- ROCm-accelerated teacher labeling/training
- compressed local ONNX inference

## Demo Goal

User says:

```text
click Share
```

System:

```text
takes screenshot -> maps UI -> finds Share -> clicks center -> verifies screen changed
```

