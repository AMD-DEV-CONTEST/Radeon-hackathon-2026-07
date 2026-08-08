from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path

from PIL import Image


CLASSES = {
    "button": 0,
    "input": 1,
    "checkbox": 2,
    "radio": 3,
    "dropdown": 4,
    "tab": 5,
    "menu": 6,
    "link": 7,
    "icon": 8,
}


ALIASES = {
    "edit": "input",
    "textbox": "input",
    "text_field": "input",
    "radio_button": "radio",
    "combobox": "dropdown",
    "menuitem": "menu",
    "tabitem": "tab",
    "hyperlink": "link",
}


def normalize_class(raw: str) -> str | None:
    value = (raw or "").strip().lower().replace(" ", "_")
    value = ALIASES.get(value, value)
    return value if value in CLASSES else None


def yolo_line(class_id: int, box: list[float], width: int, height: int) -> str:
    x1, y1, x2, y2 = box
    x1 = max(0.0, min(float(width), float(x1)))
    x2 = max(0.0, min(float(width), float(x2)))
    y1 = max(0.0, min(float(height), float(y1)))
    y2 = max(0.0, min(float(height), float(y2)))
    bw = max(1.0, x2 - x1)
    bh = max(1.0, y2 - y1)
    cx = x1 + bw / 2.0
    cy = y1 + bh / 2.0
    return f"{class_id} {cx / width:.6f} {cy / height:.6f} {bw / width:.6f} {bh / height:.6f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert normalized teacher labels to YOLO dataset.")
    parser.add_argument("--labels", default="../data/labels_teacher")
    parser.add_argument("--out", default="../data/yolo_dataset")
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    labels_dir = Path(args.labels).resolve()
    out = Path(args.out).resolve()
    random.seed(args.seed)

    label_files = sorted(labels_dir.glob("*.json"))
    if not label_files:
        raise SystemExit(f"No teacher JSON labels found in {labels_dir}")

    for split in ["train", "val"]:
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)

    converted = 0
    for label_file in label_files:
        payload = json.loads(label_file.read_text(encoding="utf-8"))
        image_path = Path(payload["image"])
        if not image_path.exists():
            print(f"skip missing image: {image_path}")
            continue

        split = "val" if random.random() < args.val_ratio else "train"
        with Image.open(image_path) as image:
            width, height = image.size

        lines = []
        for element in payload.get("elements", []):
            class_name = normalize_class(element.get("class") or element.get("role") or element.get("type"))
            box = element.get("box") or element.get("bounds")
            if class_name is None or not box or len(box) != 4:
                continue
            lines.append(yolo_line(CLASSES[class_name], box, width, height))

        dst_image = out / "images" / split / image_path.name
        dst_label = out / "labels" / split / f"{image_path.stem}.txt"
        shutil.copy2(image_path, dst_image)
        dst_label.write_text("\n".join(lines), encoding="utf-8")
        converted += 1

    yaml_path = out / "ui_dataset.yaml"
    names = [name for name, _ in sorted(CLASSES.items(), key=lambda item: item[1])]
    yaml_path.write_text(
        "\n".join(
            [
                f"path: {out.as_posix()}",
                "train: images/train",
                "val: images/val",
                "names:",
                *[f"  {idx}: {name}" for idx, name in enumerate(names)],
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"converted {converted} images into {out}")
    print(f"dataset yaml written to {yaml_path}")


if __name__ == "__main__":
    main()
