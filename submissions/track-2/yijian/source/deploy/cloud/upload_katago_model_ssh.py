#!/usr/bin/env python3
"""Resume the pinned KataGo model upload over parallel encrypted SSH streams."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from pathlib import Path
import shlex
import subprocess


MODEL_SIZE = 863_210_287
MODEL_SHA256 = "15fb3baf85cdb6578e6c19b65e6201ca906cec3ba5fee19039d05221d57eb0e8"


def remote_size(host: str, path: str) -> int:
    command = f"stat -c %s {shlex.quote(path)} 2>/dev/null || printf 0"
    output = subprocess.run(
        ["ssh", host, command], check=True, capture_output=True, text=True
    ).stdout.strip()
    return int(output or 0)


def upload_span(source: Path, host: str, remote_part: str, start: int, end: int) -> int:
    expected = end - start
    existing = remote_size(host, remote_part)
    if existing > expected:
        raise RuntimeError(f"remote part is too large: {remote_part}")
    if existing == expected:
        return expected
    process = subprocess.Popen(
        ["ssh", host, f"cat >> {shlex.quote(remote_part)}"],
        stdin=subprocess.PIPE,
    )
    assert process.stdin is not None
    remaining = expected - existing
    with source.open("rb") as stream:
        stream.seek(start + existing)
        while remaining:
            block = stream.read(min(8 * 1024 * 1024, remaining))
            if not block:
                process.kill()
                raise EOFError("local model ended before the requested span")
            process.stdin.write(block)
            remaining -= len(block)
    process.stdin.close()
    code = process.wait()
    if code != 0:
        raise RuntimeError(f"SSH upload failed for {remote_part}: exit {code}")
    size = remote_size(host, remote_part)
    if size != expected:
        raise RuntimeError(f"remote part has {size} bytes; expected {expected}")
    return size


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--host", default="radeon-yijian")
    parser.add_argument(
        "--output",
        default=(
            "/persistent/yijian/katago-models/"
            "kata1-zhizi-b40c768nbt-s11272M-d5935M.bin.gz"
        ),
    )
    parser.add_argument("--prefix", help="existing remote prefix file")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    source = args.source.resolve()
    if source.stat().st_size != MODEL_SIZE:
        parser.error(f"local model has {source.stat().st_size} bytes; expected {MODEL_SIZE}")
    digest = sha256(source)
    if digest != MODEL_SHA256:
        parser.error(f"local SHA-256 mismatch: {digest}")

    prefix = args.prefix or args.output + ".uploading"
    prefix_size = remote_size(args.host, prefix)
    if not 0 <= prefix_size <= MODEL_SIZE:
        parser.error(f"invalid remote prefix size: {prefix_size}")
    workers = max(1, min(8, args.workers))
    remaining = MODEL_SIZE - prefix_size
    chunk = (remaining + workers - 1) // workers if remaining else 0
    spans = []
    for index in range(workers):
        start = prefix_size + index * chunk
        end = min(MODEL_SIZE, start + chunk)
        if start < end:
            spans.append((index, start, end, f"{args.output}.part-{index:02d}"))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(upload_span, source, args.host, path, start, end): (index, path)
            for index, start, end, path in spans
        }
        for future in as_completed(futures):
            index, _ = futures[future]
            print(f"part {index + 1}/{len(spans)} complete: {future.result()} bytes", flush=True)

    merged = args.output + ".verified.tmp"
    parts = " ".join(shlex.quote(path) for _, _, _, path in spans)
    merge_command = (
        f"set -eu; cat {shlex.quote(prefix)} {parts} > {shlex.quote(merged)}; "
        f"test $(stat -c %s {shlex.quote(merged)}) -eq {MODEL_SIZE}; "
        f"test $(sha256sum {shlex.quote(merged)} | cut -d' ' -f1) = {MODEL_SHA256}; "
        f"mv {shlex.quote(merged)} {shlex.quote(args.output)}"
    )
    subprocess.run(["ssh", args.host, merge_command], check=True)
    print(f"verified remote model: {args.host}:{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

