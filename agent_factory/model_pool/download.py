from __future__ import annotations

import argparse
from pathlib import Path

from agent_factory.model_pool.storage import ModelStorage


def download_model(*, model_id: str, revision: str | None = None) -> Path:
    normalized_model_id = str(model_id or "").strip()
    if not normalized_model_id:
        raise ValueError("model_id is required")

    try:
        from modelscope import snapshot_download
    except ImportError as exc:
        raise RuntimeError("modelscope is required to download models") from exc

    storage = ModelStorage()
    storage.ensure_directories()
    arguments: dict[str, str] = {
        "model_id": normalized_model_id,
        "cache_dir": str(storage.modelscope_cache),
    }
    normalized_revision = str(revision or "").strip()
    if normalized_revision:
        arguments["revision"] = normalized_revision
    downloaded_path = snapshot_download(**arguments)
    return storage.require_model_directory(downloaded_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download a ModelScope model into the configured FastAgentFactory model root"
    )
    parser.add_argument("model_id")
    parser.add_argument("--revision")
    arguments = parser.parse_args()
    print(download_model(model_id=arguments.model_id, revision=arguments.revision))


if __name__ == "__main__":
    main()
