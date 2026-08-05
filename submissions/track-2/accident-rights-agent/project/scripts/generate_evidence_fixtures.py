#!/usr/bin/env python3
"""Generate synthetic PDF/video fixtures for parser integration tests."""

from __future__ import annotations

import argparse
from pathlib import Path


def generate_video(frame_dir: Path, output: Path) -> None:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required to generate the video fixture.") from exc

    paths = sorted(frame_dir.glob("*.png"))
    if len(paths) != 8:
        raise RuntimeError(f"Expected 8 PNG frames, found {len(paths)}.")
    first = cv2.imread(str(paths[0]))
    if first is None:
        raise RuntimeError(f"Cannot read {paths[0]}.")
    height, width = first.shape[:2]
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output),
        cv2.VideoWriter_fourcc(*"mp4v"),
        4.0,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError("OpenCV MP4 writer is unavailable.")
    try:
        for path in paths:
            frame = cv2.imread(str(path))
            if frame is None or frame.shape[:2] != (height, width):
                raise RuntimeError(f"Invalid or mismatched frame: {path}.")
            for _ in range(4):
                writer.write(frame)
    finally:
        writer.release()


def generate_pdf(output: Path, scanned_output: Path, image_path: Path) -> None:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required to generate the PDF fixture.") from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    try:
        page = document.new_page(width=595, height=842)
        page.insert_text(
            (72, 72),
            "SYNTHETIC TEST DOCUMENT - NOT A REAL CASE",
            fontsize=14,
        )
        lines = [
            "Document type: Traffic accident material (synthetic)",
            "Accident time: 2026-07-28 09:30",
            "Accident place: Test Road and Demo Street",
            "Party A: white passenger car",
            "Party B: two-wheeled electric vehicle",
            "Recorded fact: both vehicles appear in the intersection image.",
            "Delivery date: 2026-07-28",
        ]
        y = 120
        for line in lines:
            page.insert_text((72, y), line, fontsize=12)
            y += 28
        document.save(output)
    finally:
        document.close()

    scanned = fitz.open()
    try:
        page = scanned.new_page(width=595, height=842)
        page.insert_image(
            fitz.Rect(48, 100, 547, 500),
            filename=str(image_path),
            keep_proportion=True,
        )
        scanned.save(scanned_output)
    finally:
        scanned.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--frame-dir", type=Path, default=Path("data/smoke/frames")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/smoke/generated")
    )
    args = parser.parse_args()
    video = args.output_dir / "synthetic_sequence.mp4"
    pdf = args.output_dir / "synthetic_accident_material.pdf"
    scanned_pdf = args.output_dir / "synthetic_scanned_material.pdf"
    generate_video(args.frame_dir, video)
    generate_pdf(pdf, scanned_pdf, args.frame_dir / "frame_04.png")
    print(f"Generated video: {video.resolve()}")
    print(f"Generated PDF: {pdf.resolve()}")
    print(f"Generated scanned PDF: {scanned_pdf.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
