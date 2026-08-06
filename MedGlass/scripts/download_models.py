#!/usr/bin/env python3
"""Download MedGlass models into models/.

Supports:
  - whisper.cpp ggml-small.en.bin (Q5_1)
  - YOLOv8n-seg ONNX export (from ultralytics if torch is available)
  - Qwen3.6:27B GGUF Q4_K_M (configurable, very large download)

Usage:
    python scripts/download_models.py            # all
    python scripts/download_models.py whisper    # one component
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
MODELS.mkdir(parents=True, exist_ok=True)

WHISPER_URL = ("https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
               "ggml-small.en.bin")
WHISPER_OUT = MODELS / "ggml-small.en.bin"

# Qwen3.6:27B Q4_K_M (text path, llama.cpp-compatible, needs llama.cpp b9180+).
# The official Qwen GGUF repo is gated; unsloth's conversion of the official
# weights is ungated and matches the `qwen35` arch that b9180+ loads.
QWEN_URL = ("https://huggingface.co/unsloth/Qwen3.6-27B-GGUF/resolve/main/"
            "Qwen3.6-27B-Q4_K_M.gguf")
QWEN_OUT = MODELS / "qwen3.6-27b-q4_k_m.gguf"

YOLO_OUT = MODELS / "yolov8n-seg.onnx"


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[skip] {dest.name} already present")
        return
    print(f"[download] {url}")
    print(f"      -> {dest}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.rename(dest)
    print(f"[done] {dest.name} ({dest.stat().st_size / 1e6:.0f} MB)")


def download_whisper() -> None:
    download(WHISPER_URL, WHISPER_OUT)


def download_yolo() -> None:
    """Export YOLOv8n-seg to ONNX via ultralytics (needs torch)."""
    if YOLO_OUT.exists() and YOLO_OUT.stat().st_size > 0:
        print("[skip] yolov8n-seg.onnx already present")
        return
    try:
        from ultralytics import YOLO
    except ImportError:
        print("[error] install ultralytics: pip install ultralytics")
        sys.exit(1)
    print("[export] YOLOv8n-seg -> ONNX")
    model = YOLO("yolov8n-seg.pt")
    model.export(format="onnx", opset=12, dynamic=False, simplify=True)
    exported = Path("yolov8n-seg.onnx")
    if exported.exists():
        exported.replace(YOLO_OUT)
        print(f"[done] {YOLO_OUT.name}")


def download_llm() -> None:
    download(QWEN_URL, QWEN_OUT)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download MedGlass models")
    parser.add_argument("component", nargs="?", default="all",
                        choices=["all", "whisper", "yolo", "llm"])
    args = parser.parse_args()

    if args.component in ("all", "whisper"):
        download_whisper()
    if args.component in ("all", "yolo"):
        download_yolo()
    if args.component in ("all", "llm"):
        download_llm()


if __name__ == "__main__":
    main()
