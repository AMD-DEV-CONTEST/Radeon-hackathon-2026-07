"""Vendor the small SmolVLM config/tokenizer files beside a trained checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

from radeonvla.artifact_io import atomic_write_json

SMOLVLM_REPO_ID = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
SMOLVLM_REVISION = "7b375e1b73b11138ff12fe22c8f2822d8fe03467"
VLM_ASSET_FILES = (
    "added_tokens.json",
    "chat_template.json",
    "config.json",
    "generation_config.json",
    "merges.txt",
    "preprocessor_config.json",
    "processor_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
)


def vendor_assets(
    source: Path,
    policy_path: Path,
    *,
    repo_id: str = SMOLVLM_REPO_ID,
    revision: str = SMOLVLM_REVISION,
) -> Path:
    """Copy resolved files (not Hub symlinks) and write an integrity manifest."""
    if not policy_path.is_dir():
        raise FileNotFoundError(f"Policy directory not found: {policy_path}")
    destination = policy_path / "vlm_assets"
    destination.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, object]] = {}
    for name in VLM_ASSET_FILES:
        src = source / name
        if not src.is_file():
            raise FileNotFoundError(f"Required VLM asset not found: {src}")
        dst = destination / name
        shutil.copy2(src.resolve(), dst)
        data = dst.read_bytes()
        files[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    atomic_write_json(
        destination / "radeonvla_vlm_assets.json",
        {"repo_id": repo_id, "revision": revision, "files": files},
    )
    return destination


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-path", type=Path, required=True)
    parser.add_argument("--repo-id", default=SMOLVLM_REPO_ID)
    parser.add_argument("--revision", default=SMOLVLM_REVISION)
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Optional existing snapshot directory; otherwise download only the required small files.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source = args.source
    if source is None:
        from huggingface_hub import snapshot_download

        source = Path(
            snapshot_download(
                repo_id=args.repo_id,
                revision=args.revision,
                allow_patterns=list(VLM_ASSET_FILES),
            )
        )
    destination = vendor_assets(source, args.policy_path, repo_id=args.repo_id, revision=args.revision)
    print(f"[vendor-vlm] wrote {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
