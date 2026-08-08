from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pyautogui
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CACHE = ROOT / ".screen_cache"


def capture_screen() -> Image.Image:
    return pyautogui.screenshot()


def image_hash(image: Image.Image) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()[:24]


def run_uia_scan(max_depth: int, max_elements: int) -> list[dict]:
    script = ROOT / "uia_scan.ps1"
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-MaxDepth",
                str(max_depth),
                "-MaxElements",
                str(max_elements),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        return []
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())

    raw = completed.stdout.strip()
    if not raw:
        return []

    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        return [parsed]
    return parsed


def detect_visual_boxes(image: Image.Image, limit: int = 350) -> list[dict]:
    arr = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)

    # Edges plus light morphology catches many rectangles, fields, and button borders.
    edges = cv2.Canny(gray, 45, 130)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[tuple[int, int, int, int, float]] = []
    screen_area = image.width * image.height

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if w < 24 or h < 14:
            continue
        if area < 300 or area > screen_area * 0.65:
            continue
        aspect = w / max(h, 1)
        if aspect > 30 or aspect < 0.08:
            continue
        boxes.append((x, y, x + w, y + h, float(area)))

    boxes.sort(key=lambda item: item[4], reverse=True)
    return [
        {
            "source": "vision",
            "role": "visual_candidate",
            "localized_role": "visual candidate",
            "label": "",
            "automation_id": "",
            "class_name": "",
            "process_id": None,
            "depth": None,
            "bounds": [x1, y1, x2, y2],
            "center": [(x1 + x2) // 2, (y1 + y2) // 2],
            "confidence": 0.45,
        }
        for x1, y1, x2, y2, _ in boxes[:limit]
    ]


def area(bounds: list[int]) -> int:
    x1, y1, x2, y2 = bounds
    return max(0, x2 - x1) * max(0, y2 - y1)


def valid_bounds(item: dict, width: int, height: int) -> bool:
    x1, y1, x2, y2 = item["bounds"]
    if x2 <= x1 or y2 <= y1:
        return False
    if x2 < 0 or y2 < 0 or x1 > width or y1 > height:
        return False
    if area(item["bounds"]) > width * height * 0.92:
        return item.get("role") in {"window", "pane"}
    return True


def draw_overlay(image: Image.Image, elements: list[dict], path: Path) -> None:
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except OSError:
        font = ImageFont.load_default()

    role_colors = {
        "button": (40, 190, 95),
        "edit": (40, 125, 245),
        "hyperlink": (150, 85, 245),
        "checkbox": (245, 165, 35),
        "radiobutton": (245, 165, 35),
        "menuitem": (245, 90, 80),
        "tabitem": (245, 90, 80),
        "combobox": (20, 185, 210),
        "visual_candidate": (255, 220, 0),
    }

    # Draw larger/background candidates first, then semantic controls on top.
    sorted_elements = sorted(elements, key=lambda item: (item["source"] == "uia", area(item["bounds"])))
    for idx, item in enumerate(sorted_elements, start=1):
        x1, y1, x2, y2 = item["bounds"]
        role = item.get("role", "unknown")
        color = role_colors.get(role, (255, 80, 180))
        width = 3 if item.get("source") == "uia" else 1
        draw.rectangle([x1, y1, x2, y2], outline=color, width=width)

        label = item.get("label") or item.get("automation_id") or role
        if item.get("source") == "uia" and label:
            text = f"{idx}: {role} {label}"[:80]
            text_box = draw.textbbox((x1, max(0, y1 - 18)), text, font=font)
            draw.rectangle(text_box, fill=(0, 0, 0))
            draw.text((x1, max(0, y1 - 18)), text, fill=color, font=font)

    overlay.save(path)


def actionable_elements(elements: list[dict]) -> list[dict]:
    actionable_roles = {
        "button",
        "edit",
        "hyperlink",
        "checkbox",
        "radiobutton",
        "combobox",
        "menuitem",
        "tabitem",
        "splitbutton",
        "spinner",
        "slider",
    }
    return [
        item for item in elements
        if item.get("source") == "uia" and item.get("role") in actionable_roles
    ]


def short_action_report(elements: list[dict], limit: int = 80) -> list[dict]:
    report = []
    for item in actionable_elements(elements)[:limit]:
        x1, y1, x2, y2 = item["bounds"]
        cx, cy = item["center"]
        report.append({
            "role": item.get("role"),
            "label": item.get("label") or item.get("automation_id") or "",
            "endpoints": {
                "top_left": [x1, y1],
                "bottom_right": [x2, y2],
                "center": [cx, cy],
            },
        })
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="No-LLM screen element scanner.")
    parser.add_argument("--max-depth", type=int, default=9)
    parser.add_argument("--max-elements", type=int, default=3000)
    parser.add_argument("--vision-limit", type=int, default=350)
    parser.add_argument("--quiet", action="store_true", help="Write files without printing element reports.")
    parser.add_argument("--cache-ttl", type=int, default=2, help="Reuse identical screen maps within this many seconds.")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    screenshot = capture_screen()
    screen_key = image_hash(screenshot)
    cache_path = CACHE / f"{screen_key}.json"
    screenshot_path = OUT / f"screen_{stamp}.png"
    overlay_path = OUT / f"overlay_{stamp}.png"
    json_path = OUT / f"elements_{stamp}.json"
    latest_json_path = OUT / "latest_elements.json"
    latest_overlay_path = OUT / "latest_overlay.png"
    clean_overlay_path = OUT / f"actionable_overlay_{stamp}.png"
    latest_clean_overlay_path = OUT / "latest_actionable_overlay.png"

    screenshot.save(screenshot_path)

    if args.cache_ttl > 0 and cache_path.exists() and time.time() - cache_path.stat().st_mtime <= args.cache_ttl:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        payload["captured_at"] = stamp
        payload["cache_hit"] = True
        payload["files"] = {
            "screenshot": str(screenshot_path),
            "overlay": str(overlay_path),
            "json": str(json_path),
        }
        all_elements = payload.get("elements", [])
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        latest_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        draw_overlay(screenshot, all_elements, overlay_path)
        draw_overlay(screenshot, all_elements, latest_overlay_path)
        draw_overlay(screenshot, actionable_elements(all_elements), clean_overlay_path)
        draw_overlay(screenshot, actionable_elements(all_elements), latest_clean_overlay_path)
        if not args.quiet:
            print(json.dumps(payload["counts"], indent=2))
            print("Cache: hit")
            print(f"JSON: {json_path}")
            print(f"Overlay: {overlay_path}")
            print(f"Actionable overlay: {clean_overlay_path}")
        return

    uia_elements = run_uia_scan(args.max_depth, args.max_elements)
    visual_elements = detect_visual_boxes(screenshot, args.vision_limit)
    all_elements = [
        item for item in [*uia_elements, *visual_elements]
        if "bounds" in item and valid_bounds(item, screenshot.width, screenshot.height)
    ]

    payload = {
        "captured_at": stamp,
        "screen": {
            "width": screenshot.width,
            "height": screenshot.height,
        },
        "counts": {
            "uia": len(uia_elements),
            "vision": len(visual_elements),
            "total_valid": len(all_elements),
            "buttons": sum(1 for item in all_elements if item.get("role") == "button"),
            "inputs": sum(1 for item in all_elements if item.get("role") == "edit"),
        },
        "screen_hash": screen_key,
        "cache_hit": False,
        "elements": all_elements,
        "files": {
            "screenshot": str(screenshot_path),
            "overlay": str(overlay_path),
            "json": str(json_path),
        },
    }

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    latest_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    draw_overlay(screenshot, all_elements, overlay_path)
    draw_overlay(screenshot, all_elements, latest_overlay_path)
    draw_overlay(screenshot, actionable_elements(all_elements), clean_overlay_path)
    draw_overlay(screenshot, actionable_elements(all_elements), latest_clean_overlay_path)

    if not args.quiet:
        print(json.dumps(payload["counts"], indent=2))
        print(json.dumps({"actionable": short_action_report(all_elements, 30)}, indent=2))
        print(f"JSON: {json_path}")
        print(f"Overlay: {overlay_path}")
        print(f"Actionable overlay: {clean_overlay_path}")


if __name__ == "__main__":
    main()
