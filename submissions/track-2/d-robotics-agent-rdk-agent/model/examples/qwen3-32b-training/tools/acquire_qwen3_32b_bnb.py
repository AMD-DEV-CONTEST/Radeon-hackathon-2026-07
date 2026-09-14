#!/usr/bin/env python3
"""Acquire the pinned Qwen3-32B BnB checkpoint into persistent workspace."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ID = "unsloth/Qwen3-32B-bnb-4bit"
REVISION = "7f721e74a6a8cc9ee352f7e49303a2c1705f9083"
ENDPOINT = "https://hf-mirror.com"
EXPECTED_HOSTNAME = "u-7701-ae3eba8a"
EXPECTED_MACHINE_ID_SHA256 = "7c225d1717bb5f671c4bf071b1df172abdc72a50a3ed53e24de9ab724d35ad54"
ROOT = Path("/workspace/qwen36-agentic-sft")
TARGET = ROOT / "models" / "Qwen3-32B-bnb-4bit-7f721e74"
CACHE = ROOT / "artifacts" / "model-acquisition" / ".hf-qwen3-32b-7f721e74-cache"
RUN = ROOT / "runs" / "model-acquisition-qwen3-32b-7f721e74"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def atomic_create(path: Path, value: object) -> None:
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    partial = path.with_name(f".{path.name}.partial")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(partial, path)
        partial.unlink()
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        try:
            partial.unlink()
        except FileNotFoundError:
            pass
        raise


def main() -> None:
    require(socket.gethostname() == EXPECTED_HOSTNAME, "remote hostname mismatch")
    machine_id_hash = hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest()
    require(machine_id_hash == EXPECTED_MACHINE_ID_SHA256, "remote machine-id mismatch")
    require(shutil.disk_usage("/workspace").free >= 40_000_000_000, "insufficient persistent-disk headroom")
    require(not TARGET.exists(), f"target already exists: {TARGET}")
    require(not CACHE.exists(), f"cache already exists: {CACHE}")
    require(not RUN.exists(), f"run already exists: {RUN}")
    RUN.mkdir(parents=True)
    TARGET.mkdir(parents=True)
    CACHE.mkdir(parents=True)
    atomic_create(
        RUN / "launch.json",
        {
            "schema_version": "model_acquisition_launch.v1",
            "status": "RUNNING",
            "started_at_utc": utc_now(),
            "pid": os.getpid(),
            "repo_id": REPO_ID,
            "revision": REVISION,
            "endpoint": ENDPOINT,
            "target": str(TARGET),
            "cache": str(CACHE),
            "hostname": EXPECTED_HOSTNAME,
            "machine_id_sha256": machine_id_hash,
        },
    )
    os.environ["HF_HOME"] = str(CACHE / "home")
    os.environ["HF_HUB_CACHE"] = str(CACHE / "hub")
    os.environ["HF_XET_CACHE"] = str(CACHE / "xet")
    os.environ["HF_ENDPOINT"] = ENDPOINT
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ["HF_HUB_ETAG_TIMEOUT"] = "30"
    os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "300"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        from huggingface_hub import snapshot_download

        resolved = snapshot_download(
            repo_id=REPO_ID,
            repo_type="model",
            revision=REVISION,
            local_dir=TARGET,
            cache_dir=CACHE / "hub",
            max_workers=4,
        )
        files = [path for path in TARGET.rglob("*") if path.is_file()]
        atomic_create(
            RUN / "final_status.json",
            {
                "schema_version": "model_acquisition_status.v1",
                "status": "DOWNLOADED_NOT_YET_VERIFIED",
                "finished_at_utc": utc_now(),
                "pid": os.getpid(),
                "repo_id": REPO_ID,
                "revision": REVISION,
                "endpoint": ENDPOINT,
                "resolved_path": str(resolved),
                "target": str(TARGET),
                "file_count_including_local_cache": len(files),
                "bytes_including_local_cache": sum(path.stat().st_size for path in files),
            },
        )
    except BaseException as error:
        atomic_create(
            RUN / "failure.json",
            {
                "schema_version": "model_acquisition_failure.v1",
                "status": "FAILED",
                "failed_at_utc": utc_now(),
                "pid": os.getpid(),
                "repo_id": REPO_ID,
                "revision": REVISION,
                "endpoint": ENDPOINT,
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )
        raise


if __name__ == "__main__":
    main()
