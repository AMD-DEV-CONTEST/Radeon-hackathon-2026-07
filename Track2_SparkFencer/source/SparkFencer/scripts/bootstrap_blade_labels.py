"""Bootstrap YOLO-pose training labels for blade-tip detection.

Reuses SparkFencer's existing per-frame output to auto-generate weak labels,
so a human only has to *correct* them (in CVAT / Label Studio) instead of
labelling from scratch.

Each blade is modelled as one object of class `blade` with two keypoints:
  [guard, tip]  (kpt_shape: [2, 3] — x, y, visibility)

For every processed frame the perception pass already stored, per side:
  - fencers.<side>.keypoints  -> the leading wrist gives the *guard* endpoint
  - blade.<side>.tip_image + confidence -> the CV-estimated *tip*

We keep frames whose blade confidence clears a threshold, extract the actual
frame image from the source video, and write a YOLO-pose label file. Import the
resulting dataset into CVAT/Label Studio, fix the points, then train:

  yolo pose train model=yolo11s-pose.pt data=datasets/blade/blade.yaml \\
       imgsz=1280 epochs=120 batch=16

Usage:
  python scripts/bootstrap_blade_labels.py --output-dir outputs/clip_bout
  python scripts/bootstrap_blade_labels.py --output-dir outputs/clip_bout \\
         --min-conf 0.5 --stride 3 --val-ratio 0.15 --dataset-dir datasets/blade
"""

import argparse
import json
import os
import random
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fencing_analysis.detection.pose import (  # noqa: E402
    L_ELBOW, L_WRIST, R_ELBOW, R_WRIST,
)

KP_CONF = 0.3
SIDES = ("left", "right")


def _leading_wrist(keypoints, kp_scores, side):
    """Guard endpoint = leading wrist, chosen exactly as BladeTracker does
    (the wrist more advanced toward the opponent), so labels stay consistent
    with how the tip was generated."""
    kp = np.asarray(keypoints, dtype=float)
    sc = np.asarray(kp_scores, dtype=float) if kp_scores is not None else np.ones(len(kp))
    arms = []
    for w_i, e_i in ((L_WRIST, L_ELBOW), (R_WRIST, R_ELBOW)):
        if sc[w_i] < KP_CONF or sc[e_i] < KP_CONF:
            continue
        if np.allclose(kp[w_i], 0) or np.allclose(kp[e_i], 0):
            continue
        arms.append(kp[w_i])
    if not arms:
        return None
    if len(arms) == 2:
        arms.sort(key=lambda p: p[0], reverse=(side == "left"))
    return arms[0]


def _label_line(guard, tip, w, h, pad_ratio=0.04):
    """One YOLO-pose row: class cx cy bw bh  gx gy gv  tx ty tv (normalized)."""
    xs, ys = [guard[0], tip[0]], [guard[1], tip[1]]
    pad = max(w, h) * pad_ratio
    x1, x2 = max(0, min(xs) - pad), min(w, max(xs) + pad)
    y1, y2 = max(0, min(ys) - pad), min(h, max(ys) + pad)
    cx, cy = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
    bw, bh = (x2 - x1) / w, (y2 - y1) / h
    g = f"{guard[0] / w:.6f} {guard[1] / h:.6f} 2"
    t = f"{tip[0] / w:.6f} {tip[1] / h:.6f} 2"
    return f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f} {g} {t}"


def collect_labels(output_dir, min_conf, stride):
    """Return {frame_index: [label_line, ...]} for frames worth keeping."""
    with open(os.path.join(output_dir, "metadata.json"), encoding="utf-8") as f:
        meta = json.load(f)
    w, h = meta["video"]["width"], meta["video"]["height"]
    video_path = meta["video"]["path"]

    labels = {}
    with open(os.path.join(output_dir, "detections.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            frame = rec["frame"]
            if frame % stride != 0:
                continue
            rows = []
            for side in SIDES:
                blade = (rec.get("blade") or {}).get(side)
                fencer = (rec.get("fencers") or {}).get(side)
                if not blade or not fencer:
                    continue
                if blade.get("tip_image") is None or blade.get("confidence", 0) < min_conf:
                    continue
                guard = _leading_wrist(fencer["keypoints"], fencer.get("kp_scores"), side)
                if guard is None:
                    continue
                rows.append(_label_line(guard, blade["tip_image"], w, h))
            if rows:
                labels[frame] = rows
    return labels, video_path, (w, h)


def extract_and_write(video_path, labels, dataset_dir, val_ratio, tag, max_frames):
    frames = sorted(labels)
    random.Random(42).shuffle(frames)
    if max_frames and len(frames) > max_frames:
        frames = frames[:max_frames]
    val_set = set(frames[: int(len(frames) * val_ratio)])

    for split in ("train", "val"):
        os.makedirs(os.path.join(dataset_dir, "images", split), exist_ok=True)
        os.makedirs(os.path.join(dataset_dir, "labels", split), exist_ok=True)

    wanted = set(frames)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    written = 0
    idx = 0
    while wanted:
        ret, image = cap.read()
        if not ret:
            break
        idx += 1
        if idx not in wanted:
            continue
        wanted.discard(idx)
        split = "val" if idx in val_set else "train"
        stem = f"{tag}_{idx:06d}"
        cv2.imwrite(os.path.join(dataset_dir, "images", split, stem + ".jpg"),
                    image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        with open(os.path.join(dataset_dir, "labels", split, stem + ".txt"), "w") as f:
            f.write("\n".join(labels[idx]) + "\n")
        written += 1
    cap.release()
    return written, len(val_set)


def write_dataset_yaml(dataset_dir):
    yaml_path = os.path.join(dataset_dir, "blade.yaml")
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(
            f"path: {os.path.abspath(dataset_dir)}\n"
            "train: images/train\n"
            "val: images/val\n"
            "kpt_shape: [2, 3]\n"
            "flip_idx: [0, 1]   # guard/tip not left-right symmetric\n"
            "names:\n  0: blade\n"
        )
    return yaml_path


def main():
    ap = argparse.ArgumentParser(description="Bootstrap weak blade-tip labels from a SparkFencer output dir")
    ap.add_argument("--output-dir", required=True, help="一个已跑过感知遍的 outputs/<视频名> 目录")
    ap.add_argument("--dataset-dir", default="datasets/blade", help="YOLO-pose 数据集输出目录")
    ap.add_argument("--min-conf", type=float, default=0.5, help="剑尖置信度阈值（低于此不导出）")
    ap.add_argument("--stride", type=int, default=3, help="每隔 N 帧取一帧，避免相邻帧近乎重复")
    ap.add_argument("--val-ratio", type=float, default=0.15, help="验证集比例")
    ap.add_argument("--max-frames", type=int, default=0, help="上限帧数（0=不限）")
    ap.add_argument("--tag", default=None, help="文件名前缀，默认取输出目录名")
    args = ap.parse_args()

    tag = args.tag or os.path.basename(os.path.normpath(args.output_dir))
    labels, video_path, (w, h) = collect_labels(args.output_dir, args.min_conf, args.stride)
    if not labels:
        print("没有满足条件的帧。降低 --min-conf 或确认该目录已跑过感知遍且启用了剑尖检测。")
        return

    written, n_val = extract_and_write(video_path, labels, args.dataset_dir,
                                       args.val_ratio, tag, args.max_frames)
    yaml_path = write_dataset_yaml(args.dataset_dir)

    print(f"候选帧: {len(labels)}  写入: {written}（train {written - n_val} / val {n_val}）")
    print(f"分辨率: {w}x{h}  数据集: {os.path.abspath(args.dataset_dir)}")
    print(f"data.yaml: {yaml_path}")
    print("\n下一步：")
    print("  1) 把 images/ + labels/ 导入 CVAT 或 Label Studio，人工修正剑尖/护手点（删假、拖点、补漏）")
    print("     可多次对不同视频运行本脚本累积数据（--tag 区分来源）")
    print("  2) 训练： yolo pose train model=yolo11s-pose.pt "
          f"data={yaml_path} imgsz=1280 epochs=120 batch=16")
    print("  3) 训练完在 config.yaml 设 blade.model_path 指向 best.pt 即可无缝切换")


if __name__ == "__main__":
    main()
