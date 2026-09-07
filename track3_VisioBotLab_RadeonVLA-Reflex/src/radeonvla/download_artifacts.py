"""Download immutable public RadeonVLA-Reflex datasets, models, and evidence."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from radeonvla.paths import PROJECT_ROOT


@dataclass(frozen=True)
class ArtifactSpec:
    repo_id: str
    repo_type: Literal["dataset", "model"]
    revision: str
    destination: str


ARTIFACTS: dict[str, ArtifactSpec] = {
    "physical-1k": ArtifactSpec(
        repo_id="a3124371940/radeonvla_reflex_physical_1k",
        repo_type="dataset",
        revision="b0f72c60e9100739fd82bd498c8f3d9bed7b75af",
        destination="datasets/radeonvla_reflex_physical_1k",
    ),
    "physical-2k": ArtifactSpec(
        repo_id="a3124371940/radeonvla_reflex_physical_2k",
        repo_type="dataset",
        revision="2779b7c5566df9072bb9a7c43335d6203ea97887",
        destination="datasets/radeonvla_reflex_physical_2k",
    ),
    "model-20k": ArtifactSpec(
        repo_id="a3124371940/radeonvla_reflex_smolvla_1k",
        repo_type="model",
        revision="abcca9f2b313e378b554449016b520b8117016fe",
        destination="checkpoints/radeonvla_reflex_smolvla_1k_20k",
    ),
    "model-50k": ArtifactSpec(
        repo_id="a3124371940/radeonvla_reflex_smolvla_1k_50k",
        repo_type="model",
        revision="59f6f0ad720054505667a652fe07e03d65e82915",
        destination="checkpoints/radeonvla_reflex_smolvla_1k_50k",
    ),
    "model-200k": ArtifactSpec(
        repo_id="a3124371940/radeonvla_reflex_smolvla_2k_200k",
        repo_type="model",
        revision="1ea32da3d59ce0905d0f1331bc3c6643e42beb7e",
        destination="checkpoints/radeonvla_reflex_smolvla_2k_200k",
    ),
    "evaluation-videos": ArtifactSpec(
        repo_id="a3124371940/radeonvla_reflex_evaluation_videos",
        repo_type="dataset",
        revision="6de24191322c76c53405d6686b9ae74989073414",
        destination="downloads/radeonvla_reflex_evaluation_videos",
    ),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--artifact",
        nargs="+",
        choices=sorted(ARTIFACTS),
        help="One or more public artifacts to download.",
    )
    selection.add_argument("--all", action="store_true", help="Download every registered public artifact.")
    parser.add_argument("--list", action="store_true", help="List pinned repositories and destinations.")
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_ROOT,
        help="Project root below which datasets/checkpoints/downloads are created.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the resolved download plan without network I/O.")
    args = parser.parse_args(argv)
    if not args.list and not args.all and not args.artifact:
        parser.error("choose --artifact NAME [...], --all, or --list")
    return args


def _show(keys: list[str], root: Path) -> None:
    for key in keys:
        spec = ARTIFACTS[key]
        print(f"{key:17} {spec.repo_type:7} {spec.repo_id}@{spec.revision} -> {root / spec.destination}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.expanduser().resolve()
    keys = list(ARTIFACTS) if args.all else list(args.artifact or [])

    if args.list:
        _show(list(ARTIFACTS), root)
        if not keys:
            return 0

    _show(keys, root)
    if args.dry_run:
        return 0

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("Install requirements.local.txt or requirements.remote.txt before downloading") from exc

    downloaded: dict[str, dict[str, str]] = {}
    for key in keys:
        spec = ARTIFACTS[key]
        destination = root / spec.destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        resolved = Path(
            snapshot_download(
                repo_id=spec.repo_id,
                repo_type=spec.repo_type,
                revision=spec.revision,
                local_dir=destination,
            )
        ).resolve()
        downloaded[key] = {**asdict(spec), "resolved_path": str(resolved)}
        print(f"[download] verified {key}: {resolved}")

    receipt_path = root / "downloads" / "public_artifacts.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema_version": 1,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": downloaded,
    }
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"[download] receipt: {receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
