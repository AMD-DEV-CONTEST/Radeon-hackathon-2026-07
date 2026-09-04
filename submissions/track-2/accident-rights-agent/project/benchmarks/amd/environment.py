#!/usr/bin/env python3
"""Capture the immutable environment fingerprint for AMD-05."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def command(*parts: str) -> dict[str, Any]:
    completed = subprocess.run(
        list(parts), check=False, capture_output=True, text=True, timeout=60
    )
    return {
        "command": list(parts),
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def model_fingerprint(model: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    files: list[dict[str, Any]] = []
    for path in sorted(model.glob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        files.append({"name": path.name, "size": stat.st_size})
        digest.update(path.name.encode())
        digest.update(str(stat.st_size).encode())
        if path.suffix == ".json":
            digest.update(path.read_bytes())
    return {
        "path": str(model),
        "metadata_and_size_sha256": digest.hexdigest(),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--model", type=Path, default=Path("/persistent/models/Qwen3-VL-8B-Instruct")
    )
    args = parser.parse_args()
    runtime = command(
        "/opt/venv/bin/python",
        "-c",
        "import json,platform,torch,vllm; print(json.dumps({'python':platform.python_version(),'torch':torch.__version__,'torch_hip':torch.version.hip,'vllm':vllm.__version__}))",
    )
    fingerprint = {
        "schema_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "platform": platform.platform(),
        "source_commit": args.source_commit,
        "gpu_static": command("amd-smi", "static", "--gpu", "0"),
        "amd_smi_version": command("amd-smi", "version"),
        "rocm_info": command("rocminfo"),
        "runtime": runtime,
        "vllm_process": command("pgrep", "-af", "vllm serve"),
        "model": model_fingerprint(args.model),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(fingerprint, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(fingerprint, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
