"""Command-line companion to the Blade Pose Studio.

Examples:
  python scripts/blade_pose_dataset.py extract --video videos/bout.mp4
  python scripts/blade_pose_dataset.py validate --require-labels
  python scripts/blade_pose_dataset.py train --epochs 200 --device 0
  python scripts/blade_pose_dataset.py evaluate --model runs/blade_pose/.../best.pt
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fencing_analysis.blade_pose_dataset import (
    evaluate_pose_model, extract_video_frames, start_training, validate_dataset,
)


def main():
    parser = argparse.ArgumentParser(description="SparkFencer blade-tip pose dataset tools")
    parser.add_argument("--dataset", default="datasets/blade_tip_pose", help="本地 YOLO-Pose 数据集目录")
    commands = parser.add_subparsers(dest="command", required=True)

    extract = commands.add_parser("extract", help="从视频抽取待标注帧")
    extract.add_argument("--video", required=True)
    extract.add_argument("--split", choices=("train", "val", "test"), default="train")
    extract.add_argument("--every-n-frames", type=int, default=15)
    extract.add_argument("--max-frames", type=int, default=0)
    extract.add_argument("--tag")

    validate = commands.add_parser("validate", help="检查 YOLO-Pose 标签")
    validate.add_argument("--require-labels", action="store_true")

    train = commands.add_parser("train", help="启动本地 YOLO Pose 训练")
    train.add_argument("--model", default="yolo11s-pose.pt")
    train.add_argument("--epochs", type=int, default=200)
    train.add_argument("--imgsz", type=int, default=1280)
    train.add_argument("--batch", type=int, default=4)
    train.add_argument("--device", default="0")
    train.add_argument("--project", default="runs/blade_pose")
    train.add_argument("--name")

    evaluate = commands.add_parser("evaluate", help="评测训练模型的真实剑尖误差")
    evaluate.add_argument("--model", required=True)
    evaluate.add_argument("--split", choices=("val", "test"), default="test")
    evaluate.add_argument("--conf", type=float, default=0.15)
    evaluate.add_argument("--imgsz", type=int, default=1280)
    evaluate.add_argument("--device", default="0")
    evaluate.add_argument("--output-dir", default="runs/blade_pose_eval")

    args = parser.parse_args()
    if args.command == "extract":
        result = extract_video_frames(args.video, args.dataset, args.split, args.every_n_frames,
                                      args.max_frames, args.tag)
    elif args.command == "validate":
        result = validate_dataset(args.dataset, args.require_labels)
    elif args.command == "train":
        validation = validate_dataset(args.dataset, require_labels=True)
        if not validation["valid"]:
            print(json.dumps(validation, ensure_ascii=False, indent=2))
            raise SystemExit("数据集校验失败；修复上述标签问题后再训练。")
        result = start_training(args.dataset, args.model, args.epochs, args.imgsz, args.batch,
                                args.device, args.project, args.name)
    else:
        result = evaluate_pose_model(args.model, args.dataset, args.split, args.conf,
                                     args.imgsz, args.device, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "validate" and not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
