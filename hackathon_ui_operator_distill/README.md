# Hackathon UI Operator Distillation

Lightweight screen scanning and clicking agent strategy for low-resource laptops.

The idea:

```text
Cloud GPU teacher:
  OmniParser v2 labels screenshots into UI elements.

Local laptop student:
  Windows UI Automation + OpenCV + tiny YOLO/ONNX + OCR finds click targets.
```

This is built for a hackathon demo where the project must show practical Agentic AI and AMD GPU/ROCm acceleration, while still having a low-resource mode for 4 GB RAM laptops.

## Folder Map

```text
hackathon_ui_operator_distill/
  cloud/
    setup_cloud_gpu.sh
    download_omniparser_v2.sh
    run_teacher_labeling.py
    convert_teacher_to_yolo.py
    train_student_yolo.py
    export_int8_onnx.py
  data/
    raw_screenshots/
    labels_teacher/
    yolo_dataset/
  docs/
    cloud_gpu_connection.md
    compression_strategy.md
    hackathon_pitch.md
  local_runtime/
    collect_screenshot.py
    click_by_text.py
    local_ui_runtime.py
    requirements.txt
```

## First Workflow

1. Collect screenshots from your Windows laptop.
2. Upload screenshots to cloud GPU.
3. Run OmniParser v2 as the teacher to create labels.
4. Convert labels to YOLO format.
5. Train YOLOv8n/YOLO11n student model.
6. Export INT8 ONNX.
7. Run the tiny model locally with UI Automation and OCR fallback.

## Commands

Collect a screenshot:

```powershell
python .\hackathon_ui_operator_distill\local_runtime\collect_screenshot.py
```

Test click target selection without clicking:

```powershell
python .\hackathon_ui_operator_distill\local_runtime\click_by_text.py "Share" --dry-run
```

Cloud training path:

```bash
cd hackathon_ui_operator_distill
bash cloud/setup_cloud_gpu.sh
bash cloud/download_omniparser_v2.sh
python cloud/run_teacher_labeling.py --screens data/raw_screenshots --out data/labels_teacher --mode omniparser
python cloud/convert_teacher_to_yolo.py --labels data/labels_teacher --out data/yolo_dataset
python cloud/train_student_yolo.py --data data/yolo_dataset/ui_dataset.yaml --model yolov8n.pt --epochs 80 --device 0
python cloud/export_int8_onnx.py --weights runs/ui_student/weights/best.pt --out ui_detector_int8.onnx
```

## Why This Is Light

The laptop does not run full OmniParser.

It runs:

- Windows UI Automation for real controls
- OpenCV for visual candidates
- optional INT8 ONNX tiny UI detector
- OCR only when text matching is needed

It also includes a `codiii`-inspired SSD tiering strategy:

```text
resident scanner -> warm OCR/detector -> SSD cold parser -> AMD cloud teacher
```

See `docs/codiii_ssd_tiering_strategy.md`.

And a Colibri-style GPU backend methodology:

```text
CPU default + optional CUDA/HIP acceleration through one compatibility shim
```

See `docs/gpu_backend_methodology.md` and `native/gpu_compat.h`.

## Main Local Goal

```powershell
python .\local_runtime\click_by_text.py "Login"
```

Expected behavior:

```text
scan screen -> find matching UI element -> click center -> rescan -> verify
```
