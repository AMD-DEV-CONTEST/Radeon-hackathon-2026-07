from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Teacher labeling wrapper for OmniParser V2 icon detector."
    )
    parser.add_argument("--screens", default="../data/raw_screenshots", help="Folder with screenshots.")
    parser.add_argument("--out", default="../data/labels_teacher", help="Teacher label output folder.")
    parser.add_argument(
        "--weights",
        default="../../ai_pc_operator/data/models/teachers/omniparser_v2_icon_detect.pt",
        help="Path to OmniParser V2 icon detector weights.",
    )
    parser.add_argument("--conf", type=float, default=0.25, help="Detector confidence threshold.")
    parser.add_argument(
        "--mode",
        choices=["omniparser", "placeholder"],
        default="omniparser",
        help="Use real OmniParser detector labels or explicit placeholders.",
    )
    args = parser.parse_args()

    screens = Path(args.screens).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    images = sorted([*screens.glob("*.png"), *screens.glob("*.jpg"), *screens.glob("*.jpeg")])
    if not images:
        raise SystemExit(f"No screenshots found in {screens}")

    if args.mode == "omniparser":
        weights = Path(args.weights).resolve()
        if not weights.exists():
            raise SystemExit(f"Missing OmniParser detector weights: {weights}")
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise SystemExit("Install ultralytics first: pip install ultralytics") from exc

        model = YOLO(str(weights))
        for image in images:
            result = model.predict(str(image), conf=args.conf, verbose=False)[0]
            elements = []
            names = getattr(result, "names", {}) or {}
            for box in result.boxes:
                x1, y1, x2, y2 = [float(value) for value in box.xyxy[0].tolist()]
                cls_id = int(box.cls[0].item()) if box.cls is not None else 0
                elements.append(
                    {
                        "class": names.get(cls_id, "icon"),
                        "text": "",
                        "box": [x1, y1, x2, y2],
                        "confidence": float(box.conf[0].item()) if box.conf is not None else 0.0,
                        "teacher": "omniparser-v2-icon-detect",
                    }
                )

            label_path = out / f"{image.stem}.json"
            payload = {
                "image": str(image),
                "elements": elements,
                "teacher": {
                    "name": "microsoft/OmniParser-v2.0 icon_detect",
                    "weights": str(weights),
                    "confidence_threshold": args.conf,
                },
            }
            label_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            print(f"wrote {label_path} ({len(elements)} elements)")
        return

    for image in images:
        label_path = out / f"{image.stem}.json"
        payload = {
            "image": str(image),
            "elements": [],
            "note": "Placeholder. Replace with OmniParser v2 output normalized to this schema.",
        }
        label_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {label_path}")


if __name__ == "__main__":
    main()
