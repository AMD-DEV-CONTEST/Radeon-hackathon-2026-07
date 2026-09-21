#!/usr/bin/env python3
"""Download the pinned SmolVLA checkpoint and record an exact manifest."""

import argparse
import hashlib
import json
from pathlib import Path

from huggingface_hub import snapshot_download


REPO_ID = "lerobot/smolvla_base"
REVISION = "c83c3163b8ca9b7e67c509fffd9121e66cb96205"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="checkpoints/smolvla_base",
        help="Local checkpoint directory",
    )
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)

    snapshot_download(
        repo_id=REPO_ID,
        revision=REVISION,
        local_dir=output,
        resume_download=True,
        ignore_patterns=["*.ipynb", "*.gif"],
        max_workers=4,
    )

    files = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or ".cache/huggingface" in path.as_posix():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append(
            {
                "path": str(path.relative_to(output)),
                "size": path.stat().st_size,
                "sha256": digest,
            }
        )
    manifest = {"repo_id": REPO_ID, "revision": REVISION, "files": files}
    (output / "REVISION.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
