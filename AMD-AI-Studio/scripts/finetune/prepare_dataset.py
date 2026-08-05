#!/usr/bin/env python3
"""
AMD AI Studio — 微调数据集准备工具
支持从多种源准备训练数据集：本地文件夹、Hugging Face、爬取等
"""

import os
import json
import csv
import argparse
import logging
from pathlib import Path
from typing import Optional, List, Dict

from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("prepare_dataset")


# ============================================================
# 参数解析
# ============================================================
def parse_args():
    parser = argparse.ArgumentParser(description="AMD AI Studio — 微调数据集准备工具")

    parser.add_argument("--source", type=str, required=True,
                        choices=["local", "huggingface", "coco", "custom"],
                        help="数据源类型")
    parser.add_argument("--input_path", type=str, help="输入路径（本地目录或 Hugging Face 数据集 ID）")
    parser.add_argument("--output_dir", type=str, default="outputs/datasets",
                        help="输出目录")
    parser.add_argument("--name", type=str, default="my-dataset",
                        help="数据集名称")
    parser.add_argument("--caption_strategy", type=str, default="filename",
                        choices=["filename", "dirname", "txt_file", "csv", "json", "blip"],
                        help="字幕生成策略")
    parser.add_argument("--caption_file", type=str, help="字幕文件路径（用于 csv/json 策略）")
    parser.add_argument("--max_samples", type=int, default=0, help="最大样本数（0=全部）")
    parser.add_argument("--resolution", type=int, default=1024, help="目标分辨率")
    parser.add_argument("--format", type=str, default="jsonl", choices=["jsonl", "csv"],
                        help="输出格式")
    parser.add_argument("--val_split", type=float, default=0.1, help="验证集比例")

    return parser.parse_args()


# ============================================================
#  从本地目录组织数据集
# ============================================================
def from_local_directory(args):
    """从本地目录准备数据集"""
    input_path = Path(args.input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"目录不存在: {input_path}")

    samples = []

    # 策略 1: 目录包含图片文件，字幕来自文件名
    if args.caption_strategy == "filename":
        image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        for img_path in input_path.iterdir():
            if img_path.suffix.lower() in image_extensions:
                caption = img_path.stem.replace("_", " ").replace("-", " ")
                samples.append({
                    "image": str(img_path.resolve()),
                    "text": caption,
                })

    # 策略 2: 子目录分类，子目录名作为字幕
    elif args.caption_strategy == "dirname":
        for class_dir in input_path.iterdir():
            if class_dir.is_dir():
                caption = class_dir.name.replace("_", " ").replace("-", " ")
                image_extensions = {".jpg", ".jpeg", ".png", ".webp"}
                for img_path in class_dir.iterdir():
                    if img_path.suffix.lower() in image_extensions:
                        samples.append({
                            "image": str(img_path.resolve()),
                            "text": caption,
                        })

    # 策略 3: 图片 + 同名 txt 文件
    elif args.caption_strategy == "txt_file":
        for img_path in input_path.iterdir():
            if img_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                txt_path = img_path.with_suffix(".txt")
                if txt_path.exists():
                    caption = txt_path.read_text().strip()
                    samples.append({
                        "image": str(img_path.resolve()),
                        "text": caption,
                    })

    # 策略 4: csv 字幕文件
    elif args.caption_strategy == "csv":
        if not args.caption_file:
            raise ValueError("csv 策略需要 --caption_file 参数")
        with open(args.caption_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                img_path = input_path / row.get("image", row.get("file_name", ""))
                if img_path.exists():
                    samples.append({
                        "image": str(img_path.resolve()),
                        "text": row.get("text", row.get("caption", row.get("prompt", ""))),
                    })

    # 策略 5: JSON 字幕文件
    elif args.caption_strategy == "json":
        if not args.caption_file:
            raise ValueError("json 策略需要 --caption_file 参数")
        with open(args.caption_file, "r") as f:
            data = json.load(f)
            for item in data if isinstance(data, list) else data.get("annotations", []):
                img_path = input_path / item.get("image", item.get("file_name", ""))
                if img_path.exists():
                    samples.append({
                        "image": str(img_path.resolve()),
                        "text": item.get("text", item.get("caption", item.get("prompt", ""))),
                    })

    logger.info(f"从本地目录找到 {len(samples)} 个样本")
    return samples


# ============================================================
#  从 Hugging Face 加载数据集
# ============================================================
def from_huggingface(args):
    """从 Hugging Face Hub 加载数据集"""
    from datasets import load_dataset

    logger.info(f"加载 Hugging Face 数据集: {args.input_path}")
    dataset = load_dataset(args.input_path, split="train")

    samples = []
    for i, example in enumerate(dataset):
        if args.max_samples > 0 and i >= args.max_samples:
            break

        # 处理图像
        image = example.get("image")
        if image is None:
            continue

        # 保存到本地
        img_output_dir = Path(args.output_dir) / args.name / "images"
        img_output_dir.mkdir(parents=True, exist_ok=True)
        img_path = img_output_dir / f"{i:06d}.png"

        if isinstance(image, str):
            from PIL import Image as PILImage
            image = PILImage.open(image).convert("RGB")

        image.save(img_path)

        # 获取字幕
        caption = (
            example.get("text") or example.get("caption") or
            example.get("prompt") or f"image_{i:06d}"
        )

        samples.append({
            "image": str(img_path),
            "text": str(caption),
        })

    logger.info(f"从 Hugging Face 加载 {len(samples)} 个样本")
    return samples


# ============================================================
#  COCO 数据集格式
# ============================================================
def from_coco(args):
    """从 COCO 格式数据集准备"""
    input_path = Path(args.input_path)
    annotation_file = input_path / "annotations" / "captions_train2017.json"
    image_dir = input_path / "train2017"

    if not annotation_file.exists():
        # 尝试查找其他配置
        json_files = list((input_path / "annotations").glob("*.json"))
        if json_files:
            annotation_file = json_files[0]
            image_dir = input_path / "images"
            if not image_dir.exists():
                image_dir = input_path

    if not annotation_file.exists():
        raise FileNotFoundError(f"未找到 COCO 标注文件: {annotation_file}")

    with open(annotation_file, "r") as f:
        data = json.load(f)

    # 建立图像 ID → 文件名的映射
    img_id_to_file = {img["id"]: img["file_name"] for img in data.get("images", [])}

    samples = []
    for ann in data.get("annotations", []):
        img_id = ann["image_id"]
        file_name = img_id_to_file.get(img_id)
        if not file_name:
            continue

        img_path = image_dir / file_name
        if not img_path.exists():
            continue

        samples.append({
            "image": str(img_path.resolve()),
            "text": ann["caption"],
        })

        if args.max_samples > 0 and len(samples) >= args.max_samples:
            break

    logger.info(f"从 COCO 格式加载 {len(samples)} 个样本")
    return samples


# ============================================================
#  数据集划分与输出
# ============================================================
def split_and_save(samples: List[Dict], args):
    """划分训练/验证集并保存"""
    import random
    random.seed(42)
    random.shuffle(samples)

    # 划分
    val_count = int(len(samples) * args.val_split)
    val_samples = samples[:val_count]
    train_samples = samples[val_count:]

    output_dir = Path(args.output_dir) / args.name
    output_dir.mkdir(parents=True, exist_ok=True)

    # 复制图片到统一目录
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    for split_name, split_samples in [("train", train_samples), ("val", val_samples)]:
        records = []
        for i, sample in enumerate(split_samples):
            # 复制或链接图片
            src_path = Path(sample["image"])
            if not src_path.exists():
                continue
            dst_name = f"{split_name}_{i:06d}{src_path.suffix}"
            dst_path = images_dir / dst_name

            if not dst_path.exists():
                try:
                    dst_path.symlink_to(src_path.resolve())
                except (OSError, NotImplementedError):
                    from shutil import copy2
                    copy2(src_path, dst_path)

            record = {
                "image": f"images/{dst_name}",
                "text": sample["text"],
            }
            records.append(record)

        # 保存元数据
        if args.format == "jsonl":
            output_file = output_dir / f"{split_name}.jsonl"
            with open(output_file, "w") as f:
                for record in records:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        else:
            output_file = output_dir / f"{split_name}.csv"
            with open(output_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["image", "text"])
                writer.writeheader()
                writer.writerows(records)

        logger.info(f"{split_name}: {len(records)} 条 → {output_file}")

    # 写入配置信息
    config = {
        "name": args.name,
        "source": args.source,
        "total_samples": len(samples),
        "train_samples": len(train_samples),
        "val_samples": len(val_samples),
        "resolution": args.resolution,
        "format": args.format,
    }
    with open(output_dir / "dataset_config.json", "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    logger.info(f"数据集已保存: {output_dir}")
    logger.info(f"  训练集: {len(train_samples)} 条")
    logger.info(f"  验证集: {len(val_samples)} 条")
    logger.info("=" * 50)

    return str(output_dir)


# ============================================================
#  使用 BLIP 生成字幕（CPU 可运行）
# ============================================================
def generate_captions_with_blip(samples: List[Dict]) -> List[Dict]:
    """使用 BLIP 模型为无字幕图片生成描述"""
    logger.info("使用 BLIP 生成字幕（可能需要 5-10 分钟）...")
    try:
        from transformers import BlipProcessor, BlipForConditionalGeneration
        processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
        model = BlipForConditionalGeneration.from_pretrained(
            "Salesforce/blip-image-captioning-base"
        )

        for i, sample in enumerate(samples):
            if sample.get("text"):
                continue
            try:
                image = Image.open(sample["image"]).convert("RGB")
                inputs = processor(image, return_tensors="pt")
                out = model.generate(**inputs)
                caption = processor.decode(out[0], skip_special_tokens=True)
                sample["text"] = caption
            except Exception as e:
                sample["text"] = "a photo"
                logger.warning(f"  [{i}] 生成失败: {e}")

            if (i + 1) % 50 == 0:
                logger.info(f"  已处理 {i + 1}/{len(samples)}...")

        logger.info("BLIP 字幕生成完成")
    except ImportError:
        logger.warning("transformers 未安装，无法使用 BLIP")
        for sample in samples:
            if not sample.get("text"):
                sample["text"] = "a photo"
    return samples


# ============================================================
#  Main
# ============================================================
def main():
    args = parse_args()

    logger.info("=" * 50)
    logger.info("AMD AI Studio — 数据集准备工具")
    logger.info("=" * 50)
    logger.info(f"数据源: {args.source}")
    logger.info(f"输入: {args.input_path or 'N/A'}")

    # 根据源加载数据
    if args.source == "local":
        samples = from_local_directory(args)
    elif args.source == "huggingface":
        samples = from_huggingface(args)
    elif args.source == "coco":
        samples = from_coco(args)
    else:
        raise ValueError(f"不支持的数据源: {args.source}")

    if len(samples) == 0:
        logger.error("未找到任何样本！")
        sys.exit(1)

    # 限制样本数
    if args.max_samples > 0:
        samples = samples[:args.max_samples]

    # 生成缺失的字幕
    need_caption = [s for s in samples if not s.get("text")]
    if need_caption:
        logger.info(f"有 {len(need_caption)} 个样本缺少字幕")
        if args.caption_strategy == "blip":
            samples = generate_captions_with_blip(samples)
        else:
            logger.warning("缺少字幕的样本将使用默认描述")
            for s in need_caption:
                s["text"] = "a photo"

    # 输出
    output = split_and_save(samples, args)
    print(f"\n✅ 数据集已就绪: {output}")


if __name__ == "__main__":
    main()
