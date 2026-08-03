#!/usr/bin/env python3
"""Download the pinned KataGo network with resumable HTTP ranges.

The final file is installed only after both the official byte size and the
locally cross-checked SHA-256 match.  Part files remain resumable after an
interrupted cloud session.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import Request, urlopen


MODEL_NAME = "kata1-zhizi-b40c768nbt-s11272M-d5935M.bin.gz"
MODEL_URL = (
    "https://media.katagotraining.org/uploaded/networks/models/kata1/"
    + MODEL_NAME
)
MODEL_SIZE = 863_210_287
MODEL_SHA256 = "15fb3baf85cdb6578e6c19b65e6201ca906cec3ba5fee19039d05221d57eb0e8"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ranges(size: int, workers: int) -> list[tuple[int, int]]:
    chunk = (size + workers - 1) // workers
    return [
        (start, min(size - 1, start + chunk - 1))
        for start in range(0, size, chunk)
    ]


def download_part(
    index: int,
    start: int,
    end: int,
    part: Path,
    retries: int,
) -> tuple[int, int]:
    expected = end - start + 1
    existing = part.stat().st_size if part.exists() else 0
    if existing > expected:
        raise RuntimeError(f"part {index} is larger than expected")
    if existing == expected:
        return index, expected

    for attempt in range(1, retries + 1):
        offset = start + existing
        request = Request(
            MODEL_URL,
            headers={
                "Range": f"bytes={offset}-{end}",
                "User-Agent": "Yijian-KataGo-verified-downloader/1",
            },
        )
        try:
            with urlopen(request, timeout=90) as response:
                if response.status != 206:
                    raise RuntimeError(
                        f"server ignored range for part {index}: {response.status}"
                    )
                with part.open("ab") as handle:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        handle.write(block)
            existing = part.stat().st_size
            if existing == expected:
                return index, expected
            if existing > expected:
                raise RuntimeError(f"part {index} exceeded expected size")
        except Exception:
            if attempt == retries:
                raise
            time.sleep(min(15, attempt * 2))
            existing = part.stat().st_size if part.exists() else 0
    raise RuntimeError(f"part {index} did not complete")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/persistent/yijian/katago-models") / MODEL_NAME,
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--retries", type=int, default=8)
    args = parser.parse_args()
    workers = max(1, min(16, args.workers))
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    if output.exists() and output.stat().st_size == MODEL_SIZE:
        if sha256(output) == MODEL_SHA256:
            print(f"verified existing model: {output}")
            return 0

    part_dir = output.parent / f".{output.name}.parts-{workers}"
    part_dir.mkdir(parents=True, exist_ok=True)
    spans = ranges(MODEL_SIZE, workers)
    futures = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, (start, end) in enumerate(spans):
            part = part_dir / f"part-{index:03d}"
            futures[
                pool.submit(
                    download_part,
                    index,
                    start,
                    end,
                    part,
                    args.retries,
                )
            ] = index
        for future in as_completed(futures):
            index, size = future.result()
            print(f"part {index + 1}/{len(spans)} complete: {size} bytes", flush=True)

    temporary = output.with_suffix(output.suffix + ".verified.tmp")
    with temporary.open("wb") as target:
        for index in range(len(spans)):
            part = part_dir / f"part-{index:03d}"
            with part.open("rb") as source:
                while True:
                    block = source.read(8 * 1024 * 1024)
                    if not block:
                        break
                    target.write(block)
    if temporary.stat().st_size != MODEL_SIZE:
        raise RuntimeError("merged model has the wrong byte size")
    digest = sha256(temporary)
    if digest != MODEL_SHA256:
        raise RuntimeError(f"SHA-256 mismatch: {digest}")
    os.replace(temporary, output)
    print(f"verified model: {output}")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
