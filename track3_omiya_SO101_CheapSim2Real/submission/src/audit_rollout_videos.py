"""Audit every real-robot rollout video for wrist-camera staleness, so it is clear
which past evaluations are trustworthy and which were confounded by the frozen
wrist stream. Also reports where the cube ends up (red blob in the upper region)
versus the white sheet located in frame 0."""
import argparse
from pathlib import Path

import cv2
import numpy as np

DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "outputs" / "real_videos"


def biggest_upper(mask, min_area, ymax=300):
    n, _, stats, cent = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    best, ba = None, 0
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a < min_area or cent[i][1] > ymax:
            continue
        if 0.6 < w / max(h, 1) < 1.7 and a > ba:
            best, ba = cent[i], a
    return best, ba


def audit(path: str) -> None:
    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    prev = {"world": None, "wrist": None}
    run = {"world": 0, "wrist": 0}
    worst = {"world": 0, "wrist": 0}
    first = last = None
    i = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if i == 0:
            first = f.copy()
        last = f
        half = f.shape[1] // 2
        for name, img in (("world", f[:, :half]), ("wrist", f[:, half:])):
            s = img[::8, ::8].astype(np.int16)
            if prev[name] is not None:
                d = float(np.abs(s - prev[name]).mean())
                run[name] = run[name] + 1 if d < 0.2 else 0
                worst[name] = max(worst[name], run[name])
            prev[name] = s
        i += 1
    cap.release()

    rel = path.split("real_videos/")[-1]
    verdict = "CLEAN" if worst["wrist"] < 15 else f"CONFOUNDED"
    print(f"{rel:40s} {n:5d}f  wrist_static={worst['wrist']/30:5.1f}s "
          f"world_static={worst['world']/30:4.1f}s  {verdict}")

    if first is None or last is None:
        return
    half = first.shape[1] // 2
    h0 = cv2.cvtColor(first[:, :half], cv2.COLOR_BGR2HSV)
    sc, sa = biggest_upper(cv2.inRange(h0, (0, 0, 180), (180, 50, 255)), 1500)
    h1 = cv2.cvtColor(last[:, :half], cv2.COLOR_BGR2HSV)
    cm = (cv2.inRange(h1, (0, 90, 60), (10, 255, 255))
          | cv2.inRange(h1, (170, 90, 60), (180, 255, 255)))
    cc, ca = biggest_upper(cm, 200)
    if sc is None or cc is None:
        print(f"{'':40s} placement: could not locate sheet/cube in upper region")
        return
    side = sa ** 0.5
    d = float(np.linalg.norm(np.array(cc) - np.array(sc)))
    inside = d < side / 2
    print(f"{'':40s} placement: cube-sheet offset {d:5.1f}px "
          f"({100*d/side:3.0f}% of sheet) -> {'ON SHEET' if inside else 'off sheet'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--video-dir", default=str(DEFAULT_ROOT),
                    help="directory searched recursively for rollout .mp4 files")
    args = ap.parse_args()

    vids = sorted(Path(args.video_dir).glob("**/*.mp4"))
    if not vids:
        print(f"no .mp4 found under {args.video_dir}")
        return
    for v in vids:
        audit(str(v))


if __name__ == "__main__":
    main()
