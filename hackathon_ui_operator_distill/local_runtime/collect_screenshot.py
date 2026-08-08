from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pyautogui


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect screenshots for cloud teacher labeling.")
    parser.add_argument("--out", default="../data/raw_screenshots")
    parser.add_argument("--name", default="")
    args = parser.parse_args()

    out = Path(__file__).resolve().parent.joinpath(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    name = args.name or datetime.now().strftime("screen_%Y%m%d_%H%M%S")
    path = out / f"{name}.png"
    pyautogui.screenshot().save(path)
    print(path)


if __name__ == "__main__":
    main()

