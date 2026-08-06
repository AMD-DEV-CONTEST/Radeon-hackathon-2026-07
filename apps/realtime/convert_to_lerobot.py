#!/usr/bin/env python3
"""
将录制 JSON 转换为 LeRobot Dataset 格式

用法:
    python botclaw/convert_to_lerobot.py demos/recording_*.json
"""

import sys
import os
import json
import argparse
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np

# 项目路径 (monorepo 改造后 convert 直接住在 apps/realtime/ 下,
# parquet 输出到 apps/realtime/datasets/, 与录制 JSON 在 demos/ 并排)
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR


def load_recording(json_path: str) -> dict:
    """加载录制 JSON"""
    with open(json_path) as f:
        return json.load(f)


def create_info_json(fps: int, robot_type: str = "so100", has_images: bool = False) -> dict:
    """创建 info.json"""
    features = {
        "episode_index": {"dtype": "int64", "id": None, "_type": "Value"},
        "frame_index": {"dtype": "int64", "id": None, "_type": "Value"},
        "timestamp": {"dtype": "float64", "id": None, "_type": "Value"},
        "action": {
            "dtype": "float32",
            "shape": [6],
            "id": None,
            "_type": "Array",
        },
        "observation.state": {
            "dtype": "float32",
            "shape": [6],
            "id": None,
            "_type": "Array",
        },
    }
    if has_images:
        features["observation.images.cam_main"] = {
            "dtype": "string",
            "id": None,
            "_type": "Value",
        }

    return {
        "codebase_version": "0.3.0",
        "robot_type": robot_type,
        "total_episodes": 1,
        "total_frames": 0,
        "total_tasks": 1,
        "chunks_size": 100,
        "data_files_size_in_mb": 256,
        "video_files_size_in_mb": 512,
        "fps": fps,
        "splits": {"train": 1.0},
        "data_path": "data/{chunkIndex}/{fileIndex}.parquet",
        "video_path": None,
        "features": features,
        "tasks": [{"name": "default"}],
    }


def convert_to_lerobot(
    json_path: str,
    output_dir: str = None,
    fps: int = 64,
    episode_name: str = None
):
    """
    将录制 JSON 转换为 LeRobot Dataset 格式

    Args:
        json_path: 录制 JSON 文件路径
        output_dir: 输出目录，默认在 datasets/ 下创建
        fps: 帧率
        episode_name: episode 名称
    """
    # 加载数据
    recording = load_recording(json_path)
    frames = recording["frames"]
    has_images = recording.get("has_images", False)

    if not frames:
        print("[ERR] No frames in recording")
        return

    # 生成输出目录
    if output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = PROJECT_ROOT / "datasets" / f"recording_{timestamp}"
    else:
        output_dir = Path(output_dir)

    episode_name = episode_name or "episode_0"
    episode_dir = output_dir / episode_name
    episode_dir.mkdir(parents=True, exist_ok=True)

    print(f"Converting {len(frames)} frames to LeRobot format...")
    print(f"Output: {episode_dir}")
    if has_images:
        image_count = sum(1 for f in frames if f.get("image_path"))
        print(f"  Images: {image_count} / {len(frames)} frames")

    # 创建目录结构
    meta_dir = episode_dir / "meta"
    data_dir = episode_dir / "data"
    meta_dir.mkdir(exist_ok=True)
    data_dir.mkdir(exist_ok=True)

    # 准备数据
    records = []
    for i, frame in enumerate(frames):
        record = {
            "episode_index": 0,
            "frame_index": i,
            "timestamp": frame.get("timestamp", i / fps),
            "action": [frame["joints"][k] for k in sorted(frame["joints"].keys())],
            "observation.state": [frame["joints"][k] for k in sorted(frame["joints"].keys())],
        }
        if has_images:
            record["observation.images.cam_main"] = frame.get("image_path", "")
        records.append(record)

    # 创建 DataFrame
    df = pd.DataFrame(records)

    # 保存为 parquet
    parquet_path = data_dir / "chunk-000" / "file-000.parquet"
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(parquet_path, engine="pyarrow", compression="snappy")
    print(f"Saved {len(df)} frames to {parquet_path}")

    # 创建 info.json
    info = create_info_json(fps=fps, has_images=has_images)
    info["total_frames"] = len(frames)
    info_path = meta_dir / "info.json"
    with open(info_path, "w") as f:
        json.dump(info, f, indent=2)
    print(f"Saved info.json")

    # 创建 stats.json
    stats = {
        "action": {
            "mean": df["action"].apply(lambda x: np.mean(x)).mean(),
            "std": df["action"].apply(lambda x: np.std(x)).mean(),
            "min": df["action"].apply(lambda x: np.min(x)).min(),
            "max": df["action"].apply(lambda x: np.max(x)).max(),
        },
        "observation.state": {
            "mean": df["observation.state"].apply(lambda x: np.mean(x)).mean(),
            "std": df["observation.state"].apply(lambda x: np.std(x)).mean(),
            "min": df["observation.state"].apply(lambda x: np.min(x)).min(),
            "max": df["observation.state"].apply(lambda x: np.max(x)).max(),
        }
    }
    stats_path = meta_dir / "stats.json"
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"Saved stats.json")

    print(f"\n✅ Conversion complete!")
    print(f"Dataset location: {output_dir}")
    print(f"\nTo use this dataset:")
    print(f"  from lerobot.datasets import LeRobotDataset")
    print(f"  ds = LeRobotDataset(root='{output_dir}')")

    return output_dir


def main():
    parser = argparse.ArgumentParser(description="Convert recording JSON to LeRobot Dataset")
    parser.add_argument("json_path", help="Path to recording JSON file")
    parser.add_argument("--output", "-o", help="Output directory")
    parser.add_argument("--fps", type=int, default=64, help="Frames per second (default: 64)")
    parser.add_argument("--name", "-n", help="Episode name (default: episode_0)")

    args = parser.parse_args()

    convert_to_lerobot(
        json_path=args.json_path,
        output_dir=args.output,
        fps=args.fps,
        episode_name=args.name
    )


if __name__ == "__main__":
    main()
