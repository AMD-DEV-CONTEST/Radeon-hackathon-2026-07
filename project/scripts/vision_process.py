# project/scripts/vision_process.py
"""
R.A.G.E. Phase 3 - Module 1: Vision Pipeline (YOLOv8 on ROCm)

Purpose
-------
Bridge between Genesis's `cam_top` render output and the downstream
scheduling / insertion logic. Takes an image array (H, W, 3 uint8 - exactly
what `camera.render()` returns from server_assembly.py) and returns a list
of detections: 3 cables (red/blue/yellow) + 3 ports (red square / blue
circle / yellow triangle).

We do not have custom-trained weights yet, so this module:
  1. Loads the stock `yolov8n.pt` checkpoint via ultralytics (so the real
     inference path, device placement, and I/O contract are all exercised
     and ready to swap in trained weights later).
  2. Exposes `mock_detect()`, which fabricates detections that match the
     known Phase-2 scene layout (see server_assembly.py's GPU_BLOCK_POS /
     CABLE_ANCHOR / PORT_ROTATIONS), so Phase 3's scheduler and Phase 4's
     pipeline can be built and tested end-to-end before a fine-tuned model
     exists.
  3. Exposes `detect()`, a single entry point that downstream code should
     call. It calls the real model if `use_mock=False` and weights loaded
     successfully; otherwise it transparently falls back to `mock_detect()`
     so a missing checkpoint/GPU never blocks the rest of the pipeline.

ROCm note
---------
PyTorch's ROCm build exposes AMD GPUs through the *same* `cuda` device
namespace as NVIDIA CUDA (i.e. `torch.device('cuda')`, `model.to('cuda')`).
There is no separate `'rocm'` device string - "device='cuda'" IS the
ROCm-compatible target on a ROCm-built PyTorch. We verify at runtime with
`torch.cuda.is_available()` (which is True under both CUDA and ROCm
builds) rather than trying to sniff HIP vs. CUDA specifically.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

# --------------------------------------------------------------------------- #
# Optional heavy deps: import lazily / defensively so this module can still
# be imported (and mock_detect() can still run) on a machine without
# ultralytics/torch installed yet, e.g. a fresh hackathon runner.
# --------------------------------------------------------------------------- #
try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False

try:
    from ultralytics import YOLO
    _ULTRALYTICS_AVAILABLE = True
except ImportError:
    _ULTRALYTICS_AVAILABLE = False


# --------------------------------------------------------------------------- #
# Detection schema
# --------------------------------------------------------------------------- #

@dataclass
class Detection:
    """One detected object in image space."""
    label: str                     # e.g. "cable_red", "port_blue_circle"
    category: str                  # "cable" | "port"
    color: str                     # "red" | "blue" | "yellow"
    shape: str                     # "square" | "circle" | "triangle" | "rod"
    confidence: float
    bbox_xyxy: List[float] = field(default_factory=list)  # [x1, y1, x2, y2] px
    center_xy: List[float] = field(default_factory=list)  # [cx, cy] px


# The 3 cable/port pairs the whole Phase-2/3 scene is built around. Kept
# here (not imported from server_assembly.py) so this module has zero
# dependency on the Genesis environment and can run on any machine.
SCENE_OBJECTS = [
    {"color": "red", "shape": "square", "port_label": "port_1_red_square", "cable_label": "cable_1_red"},
    {"color": "blue", "shape": "circle", "port_label": "port_2_blue_circle", "cable_label": "cable_2_blue"},
    {"color": "yellow", "shape": "triangle", "port_label": "port_3_yellow_triangle", "cable_label": "cable_3_yellow"},
]


# --------------------------------------------------------------------------- #
# Device resolution
# --------------------------------------------------------------------------- #

def resolve_device(preferred: str = "cuda") -> str:
    """Resolve the best available torch device string.

    On a ROCm-built PyTorch, AMD GPUs enumerate under the `cuda` namespace,
    so `preferred='cuda'` is correct for both NVIDIA and AMD/ROCm hardware.
    Falls back to CPU (with a warning) if no GPU is visible, so a dev
    laptop without a discrete GPU can still run the mock pipeline.
    """
    if not _TORCH_AVAILABLE:
        print("[vision_process] WARNING: torch not installed - device "
              "resolution skipped, mock_detect() will still work.")
        return "cpu"

    if preferred == "cuda" and torch.cuda.is_available():
        device_name = torch.cuda.get_device_name(0)
        print(f"[vision_process] Resolved device 'cuda' -> {device_name} "
              f"(ROCm builds expose AMD GPUs under this same namespace).")
        return "cuda"

    print("[vision_process] WARNING: no CUDA/ROCm GPU visible to torch - "
          "falling back to CPU. Check your ROCm install if this is "
          "unexpected on hackathon hardware.")
    return "cpu"


# --------------------------------------------------------------------------- #
# Real model loading (stock weights for now; swap in fine-tuned .pt later)
# --------------------------------------------------------------------------- #

def load_model(weights_path: str = "yolov8n.pt", device: str = "cuda") -> Optional["YOLO"]:
    """Load a YOLOv8 model onto `device`. Returns None (with a warning,
    not an exception) if ultralytics isn't installed or the weights can't
    be fetched, so callers can gracefully fall back to mock_detect()
    instead of crashing the whole pipeline over a missing checkpoint.

    NOTE: yolov8n.pt is the stock COCO-pretrained nano checkpoint. It has
    NOT been fine-tuned to recognize our red-square / blue-circle /
    yellow-triangle ports or MPM cables - loading it here only proves the
    model-loading + device-placement path works. Real detections on our
    custom objects require fine-tuning on labeled cam_top frames, which is
    a follow-up Phase 3 task once we have recorded data to label.
    """
    if not _ULTRALYTICS_AVAILABLE:
        print("[vision_process] WARNING: ultralytics not installed. "
              "Install with `pip install ultralytics --break-system-packages` "
              "to use the real model path. Falling back to mock_detect().")
        return None

    resolved_device = resolve_device(device)
    try:
        model = YOLO(weights_path)
        model.to(resolved_device)
        print(f"[vision_process] Loaded '{weights_path}' onto device "
              f"'{resolved_device}'.")
        return model
    except Exception as exc:  # noqa: BLE001 - want to degrade gracefully on ANY load failure
        print(f"[vision_process] WARNING: failed to load '{weights_path}' "
              f"({exc!r}). Falling back to mock_detect().")
        return None


def run_real_inference(model: "YOLO", image: np.ndarray, conf: float = 0.25) -> List[Detection]:
    """Run actual YOLOv8 inference on `image` and translate ultralytics'
    Results object into our simple Detection dataclass.

    Since yolov8n.pt is COCO-pretrained (80 generic classes, none of which
    are "red square port" or "cable"), this will not produce meaningful
    labels for our scene today - it exists so the plumbing (call model(),
    walk .boxes, extract xyxy/conf/cls) is proven out and ready for the
    moment fine-tuned weights exist. Downstream code should prefer
    mock_detect()/detect(use_mock=True) until then.
    """
    results = model.predict(source=image, conf=conf, device=model.device, verbose=False)
    detections: List[Detection] = []
    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue
        for box in boxes:
            xyxy = box.xyxy[0].tolist()
            cls_id = int(box.cls[0].item())
            conf_score = float(box.conf[0].item())
            class_name = model.names.get(cls_id, f"class_{cls_id}")
            cx = (xyxy[0] + xyxy[2]) / 2.0
            cy = (xyxy[1] + xyxy[3]) / 2.0
            detections.append(Detection(
                label=class_name,
                category="unknown",  # stock weights don't know cable/port
                color="unknown",
                shape="unknown",
                confidence=conf_score,
                bbox_xyxy=xyxy,
                center_xy=[cx, cy],
            ))
    return detections


# --------------------------------------------------------------------------- #
# Mock inference (the path Phase 3 actually runs on today)
# --------------------------------------------------------------------------- #

def mock_detect(image: np.ndarray, seed: Optional[int] = None, jitter_px: float = 4.0) -> List[Detection]:
    """Fabricate plausible detections for the 3 cables + 3 ports, laid out
    to roughly match server_assembly.py's top-down camera view:

      - Ports sit in a row in the upper half of the frame (Robot A's side).
      - Cables sit in a row in the lower half of the frame (Robot B's side).

    `image` is only used for its shape (so bboxes stay in-frame); its
    pixel content is ignored. `seed` makes output reproducible for tests.
    A small random `jitter_px` is added to bbox centers so repeated calls
    don't return bit-identical boxes (closer to what a real detector's
    frame-to-frame noise looks like), which is useful for exercising
    downstream code that needs to be robust to small position deltas.
    """
    rng = random.Random(seed)
    h, w = image.shape[0], image.shape[1]

    detections: List[Detection] = []

    # Ports: evenly spaced across the upper third of the frame.
    port_y = h * 0.30
    port_xs = [w * 0.30, w * 0.50, w * 0.70]
    box_half = min(w, h) * 0.035

    for obj, cx_base in zip(SCENE_OBJECTS, port_xs):
        cx = cx_base + rng.uniform(-jitter_px, jitter_px)
        cy = port_y + rng.uniform(-jitter_px, jitter_px)
        detections.append(Detection(
            label=obj["port_label"],
            category="port",
            color=obj["color"],
            shape=obj["shape"],
            confidence=round(rng.uniform(0.88, 0.99), 3),
            bbox_xyxy=[cx - box_half, cy - box_half, cx + box_half, cy + box_half],
            center_xy=[cx, cy],
        ))

    # Cables: evenly spaced across the lower third of the frame, wider
    # boxes since a laid-out cable reads as an elongated blob, not a
    # square.
    cable_y = h * 0.70
    cable_xs = [w * 0.30, w * 0.50, w * 0.70]
    cable_half_w = min(w, h) * 0.10
    cable_half_h = min(w, h) * 0.02

    for obj, cx_base in zip(SCENE_OBJECTS, cable_xs):
        cx = cx_base + rng.uniform(-jitter_px, jitter_px)
        cy = cable_y + rng.uniform(-jitter_px, jitter_px)
        detections.append(Detection(
            label=obj["cable_label"],
            category="cable",
            color=obj["color"],
            shape="rod",
            confidence=round(rng.uniform(0.85, 0.97), 3),
            bbox_xyxy=[cx - cable_half_w, cy - cable_half_h, cx + cable_half_w, cy + cable_half_h],
            center_xy=[cx, cy],
        ))

    return detections


# --------------------------------------------------------------------------- #
# Unified entry point for downstream code (Phase 4's run_pipeline.py)
# --------------------------------------------------------------------------- #

def detect(image: np.ndarray, model: Optional["YOLO"] = None,
           use_mock: bool = True, seed: Optional[int] = None) -> List[Detection]:
    """Single call site downstream code should use.

    use_mock=True  (default, today's reality): always return mock_detect()
                    output, regardless of whether a real model was loaded.
    use_mock=False: try run_real_inference(); if no model was supplied/
                    loaded, transparently fall back to mock_detect() rather
                    than raising, so a missing checkpoint never blocks
                    Robot B's scheduling logic downstream.
    """
    if not use_mock and model is not None:
        return run_real_inference(model, image)
    return mock_detect(image, seed=seed)


# --------------------------------------------------------------------------- #
# Standalone test block
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    print("=" * 70)
    print("[vision_process] Standalone test")
    print("=" * 70)

    # Fake a cam_top-shaped frame (960x960x3, matching server_assembly.py's
    # cam_top resolution) without needing Genesis installed.
    fake_frame = np.zeros((960, 960, 3), dtype=np.uint8)

    print("\n--- 1. Device resolution ---")
    resolve_device("cuda")

    print("\n--- 2. Attempting real model load (stock yolov8n.pt) ---")
    yolo_model = load_model("yolov8n.pt", device="cuda")
    if yolo_model is None:
        print("    -> No real model available in this environment; "
              "that's expected pre-fine-tuning. Continuing with mock path.")

    print("\n--- 3. Mock detection (the path Phase 3 runs on today) ---")
    detections = detect(fake_frame, model=yolo_model, use_mock=True, seed=42)
    for det in detections:
        print(f"    {det.category:5s} | {det.color:6s} | {det.shape:8s} | "
              f"conf={det.confidence:.3f} | center={det.center_xy}")

    n_cables = sum(1 for d in detections if d.category == "cable")
    n_ports = sum(1 for d in detections if d.category == "port")
    assert n_cables == 3, f"Expected 3 cables, got {n_cables}"
    assert n_ports == 3, f"Expected 3 ports, got {n_ports}"
    print(f"\n[vision_process] OK: detected {n_cables} cables + {n_ports} "
          f"ports as expected.")