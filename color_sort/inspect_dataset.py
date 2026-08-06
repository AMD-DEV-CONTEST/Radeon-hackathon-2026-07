"""Inspect action[7:9] (finger) distribution in a lerobot dataset via pyarrow.

torchcodec is broken in this env; LeRobotDataset video loading is unreliable,
so we read the parquet action column directly.
"""
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

def main(dataset_dir: str) -> None:
    root = Path(dataset_dir)
    parquets = sorted((root / "data").rglob("*.parquet"))
    if not parquets:
        raise SystemExit(f"[inspect] no parquet under {root / 'data'}")
    finger_all: list[float] = []
    for p in parquets:
        t = pq.read_table(p, columns=["action"])
        for row in t["action"].to_pylist():
            finger_all.extend([row[7], row[8]])
    arr = np.asarray(finger_all, dtype=np.float64)
    print(f"[inspect] parquets={len(parquets)} finger samples={len(arr)}")
    print(f"[inspect] mean={arr.mean():.4f} std={arr.std():.4f} min={arr.min():.4f} max={arr.max():.4f}")
    print(f"[inspect] frac<0.01 (closed)={np.mean(arr < 0.01):.3f} "
          f"frac>=0.03 (open)={np.mean(arr >= 0.03):.3f}")

if __name__ == "__main__":
    main(sys.argv[1])
