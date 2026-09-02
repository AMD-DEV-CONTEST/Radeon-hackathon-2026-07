"""Download and verify the pinned BGE-M3 ONNX model outside the Git workspace."""
import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.embedding_runtime import load_bge_m3_manifest


DOWNLOAD_BASE = "https://huggingface.co/BAAI/bge-m3/resolve/{revision}/"
LOCK_NAME = ".aetherdb-model-download.lock"


def default_model_root() -> Path:
    return Path(os.environ.get("AETHERDB_MODEL_ROOT", PROJECT_ROOT / "app_data" / "models" / "bge-m3"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_artifact(session, url: str, destination: Path, size: int, sha256: str) -> None:
    if destination.is_file() and destination.stat().st_size == size and _sha256(destination) == sha256:
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > size:
        partial.unlink()
        offset = 0

    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with session.get(url, headers=headers, stream=True, timeout=(15, 180)) as response:
        response.raise_for_status()
        append = offset > 0 and response.status_code == 206
        mode = "ab" if append else "wb"
        with partial.open(mode) as output:
            for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                if chunk:
                    output.write(chunk)

    if partial.stat().st_size != size:
        raise RuntimeError(f"Downloaded size mismatch: {destination.name}")
    if _sha256(partial) != sha256:
        raise RuntimeError(f"Downloaded checksum mismatch: {destination.name}")
    os.replace(partial, destination)


def _required_download_bytes(manifest, model_root: Path) -> int:
    return sum(
        artifact.size
        for artifact in manifest.artifacts
        if not (model_root / artifact.path).is_file()
        or (model_root / artifact.path).stat().st_size != artifact.size
    )


def download_model(model_root: Path, session=None) -> None:
    manifest = load_bge_m3_manifest()
    model_root.mkdir(parents=True, exist_ok=True)
    required = _required_download_bytes(manifest, model_root)
    free = shutil.disk_usage(model_root).free
    if free < required + 512 * 1024 * 1024:
        raise RuntimeError("Insufficient free space for the pinned BGE-M3 model")

    lock_path = model_root / LOCK_NAME
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(descriptor)
    except FileExistsError as exc:
        raise RuntimeError("Another BGE-M3 model download is already running") from exc

    client = session or requests.Session()
    try:
        base = DOWNLOAD_BASE.format(revision=manifest.revision)
        for artifact in manifest.artifacts:
            _download_artifact(
                client,
                base + artifact.path,
                model_root / artifact.path,
                artifact.size,
                artifact.sha256,
            )
        issues = manifest.verify_artifacts(model_root)
        if issues:
            raise RuntimeError("BGE-M3 verification failed: " + ", ".join(issues))
        manifest.write_verification_record(model_root)
    finally:
        lock_path.unlink(missing_ok=True)
        if session is None:
            client.close()


def status(model_root: Path) -> dict:
    manifest = load_bge_m3_manifest()
    missing = manifest.missing_artifacts(model_root)
    return {
        "model_id": manifest.model_id,
        "revision": manifest.revision,
        "model_root": str(model_root),
        "missing_artifacts": list(missing),
        "verified": not missing and manifest.verification_record_is_current(model_root),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the pinned local BGE-M3 ONNX model")
    parser.add_argument("command", choices=("status", "download", "verify"))
    parser.add_argument("--model-root", type=Path, default=default_model_root())
    args = parser.parse_args()
    model_root = args.model_root.expanduser().resolve()

    if args.command == "download":
        download_model(model_root)
    elif args.command == "verify":
        manifest = load_bge_m3_manifest()
        issues = manifest.verify_artifacts(model_root)
        if issues:
            print(json.dumps({"verified": False, "issues": issues}, indent=2))
            return 1
        manifest.write_verification_record(model_root)
    print(json.dumps(status(model_root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
