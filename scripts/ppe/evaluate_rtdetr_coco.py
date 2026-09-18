import json
import os
import time
from pathlib import Path

import torch
from PIL import Image
from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForObjectDetection, RTDetrImageProcessorPil


def required_env(primary, legacy):
    value = os.environ.get(primary) or os.environ.get(legacy)
    if not value:
        raise RuntimeError(f"Set {primary} (preferred) or legacy {legacy}")
    return value


MODEL_DIR = Path(required_env("VISION_BEST_MODEL", "PPE_BEST_MODEL"))
IMAGE_DIR = Path(required_env("VISION_TEST_IMAGES", "PPE_TEST_IMAGES"))
ANNOTATION_FILE = Path(
    required_env("VISION_TEST_ANNOTATIONS", "PPE_TEST_ANNOTATIONS")
)
PREDICTIONS_FILE = Path(required_env("VISION_PREDICTIONS", "PPE_PREDICTIONS"))
REPORT_FILE = Path(required_env("VISION_EVAL_REPORT", "PPE_EVAL_REPORT"))

BATCH_SIZE = int(
    os.environ.get("VISION_EVAL_BATCH_SIZE", os.environ.get("PPE_EVAL_BATCH_SIZE", "4"))
)
SCORE_THRESHOLD = float(
    os.environ.get(
        "VISION_EVAL_SCORE_THRESHOLD",
        os.environ.get("PPE_EVAL_SCORE_THRESHOLD", "0.001"),
    )
)
NUM_WORKERS = int(
    os.environ.get("VISION_EVAL_WORKERS", os.environ.get("PPE_EVAL_WORKERS", "2"))
)


class CocoImageDataset(Dataset):
    def __init__(self, coco, image_dir):
        self.coco = coco
        self.image_dir = image_dir
        self.image_ids = sorted(coco.getImgIds())

    def __len__(self):
        return len(self.image_ids)

    def __getitem__(self, index):
        image_id = self.image_ids[index]
        info = self.coco.loadImgs([image_id])[0]
        path = self.image_dir / info["file_name"]

        with Image.open(path) as image:
            image = image.convert("RGB")

        return {
            "image_id": image_id,
            "image": image,
            "height": info["height"],
            "width": info["width"],
        }


def collate_fn(items):
    return items


def run_coco_evaluation(coco_gt, predictions, category_ids=None):
    coco_dt = coco_gt.loadRes(predictions)
    evaluator = COCOeval(coco_gt, coco_dt, "bbox")

    if category_ids is not None:
        evaluator.params.catIds = category_ids

    evaluator.evaluate()
    evaluator.accumulate()
    evaluator.summarize()
    return [float(value) for value in evaluator.stats]


def main():
    started = time.time()

    for path, label in (
        (MODEL_DIR, "model"),
        (IMAGE_DIR, "test image directory"),
        (ANNOTATION_FILE, "test annotation file"),
    ):
        if not path.exists():
            raise FileNotFoundError(f"Missing {label}: {path}")

    PREDICTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print("Model:", MODEL_DIR, flush=True)
    print("Images:", IMAGE_DIR, flush=True)
    print("Annotations:", ANNOTATION_FILE, flush=True)
    print("Batch size:", BATCH_SIZE, flush=True)
    print("Score threshold:", SCORE_THRESHOLD, flush=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("Device:", device, flush=True)

    processor = RTDetrImageProcessorPil.from_pretrained(
        MODEL_DIR,
        local_files_only=True,
    )
    model = AutoModelForObjectDetection.from_pretrained(
        MODEL_DIR,
        local_files_only=True,
    )
    model.to(device)
    model.eval()

    coco_gt = COCO(str(ANNOTATION_FILE))
    dataset = CocoImageDataset(coco_gt, IMAGE_DIR)
    loader = DataLoader(
        dataset,
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=NUM_WORKERS,
        collate_fn=collate_fn,
        pin_memory=(device.type == "cuda"),
    )

    predictions = []
    processed = 0

    with torch.inference_mode():
        for batch in loader:
            images = [item["image"] for item in batch]

            inputs = processor(
                images=images,
                return_tensors="pt",
            )
            inputs = {
                key: value.to(device)
                for key, value in inputs.items()
            }

            outputs = model(**inputs)

            target_sizes = torch.tensor(
                [
                    [item["height"], item["width"]]
                    for item in batch
                ],
                device=device,
            )

            results = processor.post_process_object_detection(
                outputs,
                target_sizes=target_sizes,
                threshold=SCORE_THRESHOLD,
            )

            for item, result in zip(batch, results):
                boxes = result["boxes"].detach().cpu()
                scores = result["scores"].detach().cpu()
                labels = result["labels"].detach().cpu()

                for box, score, label in zip(boxes, scores, labels):
                    x1, y1, x2, y2 = [float(value) for value in box]
                    width = max(0.0, x2 - x1)
                    height = max(0.0, y2 - y1)

                    if width <= 0.0 or height <= 0.0:
                        continue

                    predictions.append(
                        {
                            "image_id": int(item["image_id"]),
                            "category_id": int(label),
                            "bbox": [x1, y1, width, height],
                            "score": float(score),
                        }
                    )

            processed += len(batch)
            print(
                f"Processed {processed}/{len(dataset)} images; "
                f"predictions={len(predictions)}",
                flush=True,
            )

    PREDICTIONS_FILE.write_text(
        json.dumps(predictions, ensure_ascii=False),
        encoding="utf-8",
    )

    if not predictions:
        raise RuntimeError("Model produced no predictions")

    print("\nOverall COCO evaluation", flush=True)
    overall = run_coco_evaluation(coco_gt, predictions)

    categories = coco_gt.loadCats(coco_gt.getCatIds())
    per_class = {}

    for category in categories:
        print(f"\nCategory: {category['name']}", flush=True)
        stats = run_coco_evaluation(
            coco_gt,
            predictions,
            category_ids=[category["id"]],
        )
        per_class[category["name"]] = {
            "category_id": int(category["id"]),
            "AP_50_95": stats[0],
            "AP_50": stats[1],
            "AP_75": stats[2],
            "AR_100": stats[8],
        }

    report = {
        "status": "PASS",
        "model": str(MODEL_DIR),
        "annotation_file": str(ANNOTATION_FILE),
        "image_directory": str(IMAGE_DIR),
        "image_count": len(dataset),
        "prediction_count": len(predictions),
        "batch_size": BATCH_SIZE,
        "score_threshold": SCORE_THRESHOLD,
        "device": str(device),
        "duration_seconds": time.time() - started,
        "overall": {
            "AP_50_95": overall[0],
            "AP_50": overall[1],
            "AP_75": overall[2],
            "AP_small": overall[3],
            "AP_medium": overall[4],
            "AP_large": overall[5],
            "AR_1": overall[6],
            "AR_10": overall[7],
            "AR_100": overall[8],
        },
        "per_class": per_class,
        "predictions_file": str(PREDICTIONS_FILE),
    }

    REPORT_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("\nRT-DETR COCO EVALUATION PASS", flush=True)
    print("Report:", REPORT_FILE, flush=True)


if __name__ == "__main__":
    main()
