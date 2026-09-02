#!/usr/bin/env python3
"""Download all model weights required by PolicyCut.

Hugging Face models are fetched with ``huggingface_hub.snapshot_download``,
which is resumable: re-running this script continues interrupted downloads.

Mirror support
--------------
``snapshot_download`` honors the ``HF_ENDPOINT`` environment variable.
Users behind restricted networks (e.g. mainland China) can use a mirror:

    export HF_ENDPOINT=https://hf-mirror.com
    python scripts/download_models.py

The YuNet face detector ONNX file is downloaded from the OpenCV Zoo GitHub
repository via plain ``urllib`` into ``models/face_detection_yunet_2023mar.onnx``
(relative to the project root). OpenCV Zoo stores the file in Git LFS, so we
try the LFS media endpoint first and fall back to the raw endpoint, detecting
and rejecting LFS pointer stubs.

Usage
-----
    python scripts/download_models.py                 # everything
    python scripts/download_models.py --only dino,yunet
    python scripts/download_models.py --only whisper --only sam2
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

HF_MODELS: dict[str, str] = {
    "dino": "IDEA-Research/grounding-dino-tiny",
    "qwen": "Qwen/Qwen3-4B-Instruct-2507",
    "whisper": "openai/whisper-large-v3-turbo",
    "sam2": "facebook/sam2.1-hiera-small",
}

YUNET_KEY = "yunet"
YUNET_FILENAME = "face_detection_yunet_2023mar.onnx"
YUNET_DEST = PROJECT_ROOT / "models" / YUNET_FILENAME
# OpenCV Zoo keeps model weights in Git LFS. media.githubusercontent.com serves
# the resolved LFS binary; raw.githubusercontent.com may return a tiny pointer.
YUNET_URLS = [
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
    "models/face_detection_yunet/" + YUNET_FILENAME,
    "https://raw.githubusercontent.com/opencv/opencv_zoo/main/"
    "models/face_detection_yunet/" + YUNET_FILENAME,
]

ALL_KEYS = list(HF_MODELS.keys()) + [YUNET_KEY]


def human_size(num_bytes: float) -> str:
    """Format a byte count for humans."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:,.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:,.1f} PB"


def dir_size(path: Path) -> int:
    """Total size in bytes of all regular files under path."""
    total = 0
    if path.is_file():
        return path.stat().st_size
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def download_hf_model(repo_id: str) -> tuple[bool, str, str]:
    """Snapshot-download one Hugging Face repo.

    Returns (ok, local_path, detail).
    """
    try:
        from huggingface_hub import snapshot_download  # lazy heavy import
    except Exception as exc:  # pragma: no cover - env dependent
        return False, "", f"huggingface_hub not installed ({exc}); pip install huggingface_hub"

    endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co")
    print(f"[hf] downloading {repo_id} (endpoint: {endpoint}) ...", flush=True)
    try:
        local_path = snapshot_download(repo_id=repo_id)
    except Exception as exc:
        return False, "", f"download failed: {exc}"
    size = dir_size(Path(local_path))
    return True, local_path, f"{human_size(size)}"


def _is_lfs_pointer(head: bytes) -> bool:
    return head.startswith(b"version https://git-lfs")


def download_yunet(dest: Path, force: bool = False) -> tuple[bool, str, str]:
    """Download the YuNet ONNX file from OpenCV Zoo via urllib.

    Returns (ok, local_path, detail).
    """
    if dest.exists() and dest.stat().st_size > 200_000 and not force:
        return True, str(dest), f"already present ({human_size(dest.stat().st_size)})"

    dest.parent.mkdir(parents=True, exist_ok=True)
    last_err = "no url attempted"
    for url in YUNET_URLS:
        print(f"[yunet] trying {url} ...", flush=True)
        tmp = dest.with_suffix(".onnx.part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "policycut-downloader"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as fh:
                first = resp.read(4096)
                if _is_lfs_pointer(first):
                    last_err = "got a Git LFS pointer stub, not the binary"
                    tmp.unlink(missing_ok=True)
                    continue
                fh.write(first)
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
            size = tmp.stat().st_size
            if size < 100_000:
                last_err = f"file suspiciously small ({size} bytes)"
                tmp.unlink(missing_ok=True)
                continue
            os.replace(tmp, dest)
            return True, str(dest), f"{human_size(size)}"
        except (urllib.error.URLError, OSError) as exc:
            last_err = str(exc)
            tmp.unlink(missing_ok=True)
    return False, "", f"all mirrors failed: {last_err}"


def parse_only(values: list[str] | None) -> list[str]:
    """Parse --only values (repeatable and/or comma-separated) into keys."""
    if not values:
        return ALL_KEYS
    keys: list[str] = []
    for value in values:
        for part in value.split(","):
            part = part.strip().lower()
            if not part:
                continue
            if part not in ALL_KEYS:
                sys.exit(f"error: unknown model key '{part}'. Choose from: {', '.join(ALL_KEYS)}")
            if part not in keys:
                keys.append(part)
    return keys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--only",
        action="append",
        metavar="KEYS",
        help=f"subset to download, comma separated or repeated. Keys: {', '.join(ALL_KEYS)}",
    )
    parser.add_argument("--force", action="store_true", help="re-download YuNet even if present")
    args = parser.parse_args(argv)

    keys = parse_only(args.only)
    print(f"PolicyCut model downloader — targets: {', '.join(keys)}")
    if os.environ.get("HF_ENDPOINT"):
        print(f"Using HF_ENDPOINT={os.environ['HF_ENDPOINT']}")
    else:
        print("Tip: export HF_ENDPOINT=https://hf-mirror.com to use a mirror.")

    results: list[tuple[str, str, bool, str, str]] = []  # key, id, ok, path, detail
    for key in keys:
        if key == YUNET_KEY:
            ok, path, detail = download_yunet(YUNET_DEST, force=args.force)
            results.append((key, "opencv_zoo/" + YUNET_FILENAME, ok, path, detail))
        else:
            repo_id = HF_MODELS[key]
            ok, path, detail = download_hf_model(repo_id)
            results.append((key, repo_id, ok, path, detail))

    print("\n=== Download summary ===")
    failed = 0
    for key, model_id, ok, path, detail in results:
        status = "OK  " if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{status}] {key:8s} {model_id}")
        print(f"       size: {detail}")
        if path:
            print(f"       path: {path}")
    if failed:
        print(f"\n{failed} download(s) failed. Re-run to resume (downloads are resumable).")
        return 1
    print("\nAll requested models are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
