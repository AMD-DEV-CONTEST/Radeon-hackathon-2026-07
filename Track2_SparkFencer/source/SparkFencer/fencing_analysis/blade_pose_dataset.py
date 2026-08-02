"""Local dataset, annotation, training and evaluation utilities for blade pose.

The dataset uses one ``blade`` class and two keypoints per instance:
``guard`` and ``blade_tip``.  Keeping these operations here makes the web
annotation studio and command-line tools use exactly the same YOLO-Pose file
format.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import subprocess
import time
from typing import Iterable

import cv2
import numpy as np
import yaml

KPT_NAMES = ("guard", "blade_tip")
SPLITS = ("train", "val", "test")
_SAFE_STEM = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass
class BladeAnnotation:
    """One blade instance in image pixel coordinates."""

    guard: tuple[float, float] | None = None
    tip: tuple[float, float] | None = None
    guard_visible: int = 2
    tip_visible: int = 2

    @property
    def complete(self) -> bool:
        return self.guard is not None and self.tip is not None


def dataset_paths(dataset_dir: str | Path, split: str) -> tuple[Path, Path]:
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, got {split!r}")
    root = Path(dataset_dir).expanduser().resolve()
    return root / "images" / split, root / "labels" / split


def ensure_dataset(dataset_dir: str | Path) -> Path:
    root = Path(dataset_dir).expanduser().resolve()
    for split in SPLITS:
        images, labels = dataset_paths(root, split)
        images.mkdir(parents=True, exist_ok=True)
        labels.mkdir(parents=True, exist_ok=True)
    write_dataset_yaml(root)
    return root


def write_dataset_yaml(dataset_dir: str | Path) -> Path:
    root = Path(dataset_dir).expanduser().resolve()
    payload = {
        "path": str(root),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "kpt_shape": [2, 3],
        # A horizontal flip leaves guard/tip semantics unchanged.
        "flip_idx": [0, 1],
        "names": {0: "blade"},
        "kpt_names": {0: list(KPT_NAMES)},
    }
    path = root / "blade_tip_pose.yaml"
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)
    return path


def _clip_point(point: tuple[float, float], width: int, height: int) -> tuple[float, float]:
    return (float(np.clip(point[0], 0, width - 1)), float(np.clip(point[1], 0, height - 1)))


def _line_for_annotation(annotation: BladeAnnotation, width: int, height: int,
                         pad_ratio: float = 0.015) -> str | None:
    if not annotation.complete:
        return None
    guard = _clip_point(annotation.guard, width, height)
    tip = _clip_point(annotation.tip, width, height)
    pad = max(4.0, max(width, height) * pad_ratio)
    x1, x2 = max(0.0, min(guard[0], tip[0]) - pad), min(float(width), max(guard[0], tip[0]) + pad)
    y1, y2 = max(0.0, min(guard[1], tip[1]) - pad), min(float(height), max(guard[1], tip[1]) + pad)
    cx, cy = (x1 + x2) / (2 * width), (y1 + y2) / (2 * height)
    bw, bh = (x2 - x1) / width, (y2 - y1) / height
    fields = ["0", f"{cx:.6f}", f"{cy:.6f}", f"{bw:.6f}", f"{bh:.6f}"]
    for point, visibility in ((guard, annotation.guard_visible), (tip, annotation.tip_visible)):
        fields.extend([f"{point[0] / width:.6f}", f"{point[1] / height:.6f}", str(int(visibility))])
    return " ".join(fields)


def label_path_for(image_path: str | Path, dataset_dir: str | Path, split: str) -> Path:
    image = Path(image_path).resolve()
    images_dir, labels_dir = dataset_paths(dataset_dir, split)
    try:
        relative = image.relative_to(images_dir)
    except ValueError as exc:
        raise ValueError(f"image is not inside {images_dir}: {image}") from exc
    return labels_dir / relative.with_suffix(".txt")


def load_annotations(label_path: str | Path, width: int, height: int) -> list[BladeAnnotation]:
    path = Path(label_path)
    if not path.exists():
        return []
    annotations = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        values = raw.split()
        if len(values) != 11 or values[0] != "0":
            continue
        try:
            numbers = [float(v) for v in values[1:]]
        except ValueError:
            continue
        guard = (numbers[4] * width, numbers[5] * height)
        tip = (numbers[7] * width, numbers[8] * height)
        annotations.append(BladeAnnotation(
            guard=guard, tip=tip, guard_visible=int(numbers[6]), tip_visible=int(numbers[9]),
        ))
    return annotations


def save_annotations(label_path: str | Path, annotations: Iterable[BladeAnnotation],
                     width: int, height: int) -> int:
    path = Path(label_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [row for a in annotations if (row := _line_for_annotation(a, width, height))]
    path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    return len(rows)


def list_images(dataset_dir: str | Path, split: str) -> list[str]:
    images_dir, _ = dataset_paths(dataset_dir, split)
    allowed = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    return [str(p) for p in sorted(images_dir.rglob("*")) if p.suffix.lower() in allowed]


def dataset_summary(dataset_dir: str | Path) -> dict:
    root = Path(dataset_dir).expanduser().resolve()
    summary = {"root": str(root), "splits": {}, "total_images": 0, "annotated_images": 0, "instances": 0}
    for split in SPLITS:
        images = list_images(root, split)
        _, labels_dir = dataset_paths(root, split)
        instance_count = 0
        annotated = 0
        for image in images:
            label = label_path_for(image, root, split)
            if label.exists() and label.stat().st_size:
                rows = [line for line in label.read_text(encoding="utf-8").splitlines() if line.strip()]
                annotated += 1 if rows else 0
                instance_count += len(rows)
        summary["splits"][split] = {"images": len(images), "annotated": annotated, "instances": instance_count}
        summary["total_images"] += len(images)
        summary["annotated_images"] += annotated
        summary["instances"] += instance_count
    return summary


def validate_dataset(dataset_dir: str | Path, require_labels: bool = False) -> dict:
    """Validate YOLO-Pose rows without importing Ultralytics.

    Empty label files are allowed while a dataset is being annotated unless
    ``require_labels`` is set (use it immediately before a training run).
    """
    root = Path(dataset_dir).expanduser().resolve()
    problems, checked, labelled = [], 0, 0
    for split in SPLITS:
        for image_path in list_images(root, split):
            checked += 1
            label_path = label_path_for(image_path, root, split)
            if not label_path.exists() or not label_path.read_text(encoding="utf-8").strip():
                if require_labels:
                    problems.append(f"{image_path}: missing label")
                continue
            labelled += 1
            for row_num, row in enumerate(label_path.read_text(encoding="utf-8").splitlines(), 1):
                values = row.split()
                if len(values) != 11 or not values or values[0] != "0":
                    problems.append(f"{label_path}:{row_num}: expected 11 fields for class 0")
                    continue
                try:
                    numbers = [float(v) for v in values[1:]]
                except ValueError:
                    problems.append(f"{label_path}:{row_num}: non-numeric coordinates")
                    continue
                coords = (numbers[0], numbers[1], numbers[2], numbers[3], numbers[4], numbers[5], numbers[7], numbers[8])
                if not all(0.0 <= value <= 1.0 for value in coords):
                    problems.append(f"{label_path}:{row_num}: normalized coordinate outside [0, 1]")
                if int(numbers[6]) not in (0, 1, 2) or int(numbers[9]) not in (0, 1, 2):
                    problems.append(f"{label_path}:{row_num}: visibility must be 0, 1 or 2")
    return {"root": str(root), "checked_images": checked, "labelled_images": labelled,
            "problems": problems, "valid": not problems}


def extract_video_frames(video_path: str | Path, dataset_dir: str | Path, split: str = "train",
                         every_n_frames: int = 15, max_frames: int = 0,
                         tag: str | None = None, jpeg_quality: int = 95) -> dict:
    """Extract editable frames. Existing images are never overwritten."""
    if every_n_frames < 1:
        raise ValueError("every_n_frames must be >= 1")
    root = ensure_dataset(dataset_dir)
    video_path = Path(video_path).expanduser().resolve()
    if not video_path.is_file():
        raise FileNotFoundError(video_path)
    image_dir, _ = dataset_paths(root, split)
    stem = _SAFE_STEM.sub("_", tag or video_path.stem).strip("_.") or "video"
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    written, frame_index = 0, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_index % every_n_frames == 0:
            target = image_dir / f"{stem}_{frame_index:07d}.jpg"
            if not target.exists():
                if not cv2.imwrite(str(target), frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]):
                    raise RuntimeError(f"Cannot write {target}")
                written += 1
            if max_frames and written >= max_frames:
                break
        frame_index += 1
    cap.release()
    return {"written": written, "fps": fps, "source": str(video_path), "split": split, "dataset": str(root)}


def render_annotations(image_path: str | Path, annotations: list[BladeAnnotation],
                       selected_index: int | None = None) -> np.ndarray:
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(image_path)
    for idx, ann in enumerate(annotations):
        if not ann.complete:
            continue
        guard = tuple(map(int, ann.guard))
        tip = tuple(map(int, ann.tip))
        active = idx == selected_index
        box_color = (0, 116, 255) if active else (80, 80, 80)
        cv2.line(image, guard, tip, (210, 198, 22), 2, cv2.LINE_AA)
        cv2.circle(image, guard, 7, (23, 116, 255), -1, cv2.LINE_AA)
        cv2.circle(image, tip, 7, (210, 198, 22), -1, cv2.LINE_AA)
        cv2.circle(image, guard, 10, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(image, tip, 10, (255, 255, 255), 2, cv2.LINE_AA)
        x1, y1 = min(guard[0], tip[0]), min(guard[1], tip[1])
        x2, y2 = max(guard[0], tip[0]), max(guard[1], tip[1])
        pad = 8
        cv2.rectangle(image, (x1 - pad, y1 - pad), (x2 + pad, y2 + pad), box_color, 2)
        cv2.putText(image, f"blade {idx + 1}", (x1, max(20, y1 - 13)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, box_color, 2, cv2.LINE_AA)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def start_training(dataset_dir: str | Path, model: str = "yolo11s-pose.pt", epochs: int = 200,
                   imgsz: int = 1280, batch: int = 4, device: str = "0", project: str = "runs/blade_pose",
                   name: str | None = None) -> dict:
    """Start a local Ultralytics pose run and return its PID/log paths."""
    root = ensure_dataset(dataset_dir)
    yaml_path = write_dataset_yaml(root)
    run_name = name or f"blade_tip_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = Path(project).expanduser().resolve() / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "train.log"
    cmd = [
        "yolo", "pose", "train", f"model={model}", f"data={yaml_path}",
        f"epochs={int(epochs)}", f"imgsz={int(imgsz)}", f"batch={int(batch)}", f"device={device}",
        "cache=disk", "patience=40", "close_mosaic=15", f"project={Path(project).expanduser().resolve()}",
        f"name={run_name}", "exist_ok=True",
    ]
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
    (run_dir / "command.json").write_text(json.dumps({"command": cmd, "pid": process.pid}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"pid": process.pid, "run_dir": str(run_dir), "log_path": str(log_path), "command": cmd}


def _iou(box_a, box_b) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1, iy1, ix2, iy2 = max(ax1, bx1), max(ay1, by1), min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    union = max(1e-6, (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - iw * ih)
    return iw * ih / union


def _annotation_box(annotation: BladeAnnotation, padding: float = 8.0) -> tuple[float, float, float, float]:
    assert annotation.guard is not None and annotation.tip is not None
    return (min(annotation.guard[0], annotation.tip[0]) - padding,
            min(annotation.guard[1], annotation.tip[1]) - padding,
            max(annotation.guard[0], annotation.tip[0]) + padding,
            max(annotation.guard[1], annotation.tip[1]) + padding)


def evaluate_pose_model(model_path: str | Path, dataset_dir: str | Path, split: str = "test",
                        conf: float = 0.15, imgsz: int = 1280, device: str = "0",
                        output_dir: str | Path = "runs/blade_pose_eval") -> dict:
    """Evaluate real tip pixel error and PCK against the manually labelled split."""
    from ultralytics import YOLO

    images = list_images(dataset_dir, split)
    if not images:
        raise ValueError(f"No images in {dataset_dir}/images/{split}")
    model = YOLO(str(model_path))
    errors, guard_errors, matched, total = [], [], 0, 0
    visual_dir = Path(output_dir).expanduser().resolve() / "visuals"
    visual_dir.mkdir(parents=True, exist_ok=True)
    for image_path in images:
        image = cv2.imread(image_path)
        if image is None:
            continue
        h, w = image.shape[:2]
        labels = load_annotations(label_path_for(image_path, dataset_dir, split), w, h)
        labels = [a for a in labels if a.complete and a.tip_visible > 0]
        total += len(labels)
        if not labels:
            continue
        result = model(image, conf=conf, imgsz=imgsz, device=device, verbose=False)[0]
        pred_boxes = result.boxes.xyxy.cpu().numpy() if result.boxes is not None else np.empty((0, 4))
        pred_kpts = result.keypoints.xy.cpu().numpy() if result.keypoints is not None else np.empty((0, 2, 2))
        used = set()
        for ann in labels:
            gt_box = _annotation_box(ann)
            candidates = [(i, _iou(gt_box, box)) for i, box in enumerate(pred_boxes) if i not in used]
            if not candidates:
                continue
            index, overlap = max(candidates, key=lambda item: item[1])
            if overlap <= 0.01 or index >= len(pred_kpts):
                continue
            used.add(index)
            guard_pred, tip_pred = pred_kpts[index][0], pred_kpts[index][1]
            errors.append(float(np.linalg.norm(tip_pred - np.asarray(ann.tip))))
            guard_errors.append(float(np.linalg.norm(guard_pred - np.asarray(ann.guard))))
            matched += 1
    result = {
        "model": str(Path(model_path).expanduser().resolve()), "dataset": str(Path(dataset_dir).expanduser().resolve()),
        "split": split, "ground_truth_instances": total, "matched_instances": matched,
        "detection_rate": round(matched / total, 4) if total else 0.0,
        "tip_mean_pixel_error": round(float(np.mean(errors)), 3) if errors else None,
        "tip_median_pixel_error": round(float(np.median(errors)), 3) if errors else None,
        "tip_pck_at_5px": round(float(np.mean(np.asarray(errors) <= 5)), 4) if errors else 0.0,
        "tip_pck_at_10px": round(float(np.mean(np.asarray(errors) <= 10)), 4) if errors else 0.0,
        "guard_mean_pixel_error": round(float(np.mean(guard_errors)), 3) if guard_errors else None,
    }
    report_path = Path(output_dir).expanduser().resolve() / "evaluation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["report_path"] = str(report_path)
    return result
