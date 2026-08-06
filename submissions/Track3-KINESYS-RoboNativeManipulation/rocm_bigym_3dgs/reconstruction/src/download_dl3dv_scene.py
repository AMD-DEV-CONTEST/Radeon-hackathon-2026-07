#!/usr/bin/env python3
"""Download and validate a pinned gated DL3DV scene.

Authentication is deliberately resolved only from the local Hugging Face
credential store.  The token is never accepted as a command-line argument,
written to a report, or forwarded to Kubernetes.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from PIL import Image, ImageDraw, ImageOps

REPO_ID = "DL3DV/DL3DV-ALL-2K"
REVISION = "e035bc5efd8dc5b2fa1e704cb2b1086fd9ec2c5c"
SOURCE_URL = f"https://huggingface.co/datasets/{REPO_ID}"
LICENSE = "CC BY-NC 4.0 plus DL3DV dataset terms; non-commercial research only"
SCENES = {
    "commercial-kitchen": {
        "scene_hash": "90e70328f9196bc78c7e6c695c1e8cbb55a3c961cccf34c566966a5e2d8d8947",
        "filename": "4K/90e70328f9196bc78c7e6c695c1e8cbb55a3c961cccf34c566966a5e2d8d8947.zip",
        "category": "indoor commercial kitchen with an approximately open central aisle",
        "expected_bytes": 910_995_448,
        "expected_sha256": "9765ce6dd3661ba125b6689c0cc50717645480ec2ce5790a4636129521341adb",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/scene_shells/dl3dv"),
        help="Ignored local data directory.",
    )
    parser.add_argument(
        "--scene",
        default="commercial-kitchen",
        help=(
            "Pinned DL3DV scene profile. Use --scene-hash/--batch for a "
            "screened candidate that is not yet promoted into SCENES."
        ),
    )
    parser.add_argument("--scene-hash")
    parser.add_argument(
        "--batch",
        choices=tuple(f"{index}K" for index in range(1, 11)),
    )
    parser.add_argument("--category", default="screened kitchen candidate")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/download_cache/huggingface"),
    )
    parser.add_argument("--extract-to", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def resolve_scene(
    args: argparse.Namespace,
    api: object,
) -> tuple[str, dict[str, object]]:
    """Resolve a pinned profile or an explicit hash against HF LFS metadata."""

    if args.scene_hash is None:
        if args.scene not in SCENES:
            raise SystemExit(
                f"unknown scene profile {args.scene!r}; provide "
                "--scene-hash and --batch for a screened candidate"
            )
        return args.scene, dict(SCENES[args.scene])

    if args.batch is None:
        raise SystemExit("--batch is required with --scene-hash")
    if not re.fullmatch(r"[0-9a-f]{64}", args.scene_hash):
        raise SystemExit("--scene-hash must be a lowercase 64-character SHA-256")
    filename = f"{args.batch}/{args.scene_hash}.zip"
    paths = None
    last_error: Exception | None = None
    for attempt in range(1, 9):
        try:
            paths = api.get_paths_info(
                REPO_ID,
                [filename],
                repo_type="dataset",
                revision=REVISION,
                expand=True,
            )
            break
        except Exception as exc:
            last_error = exc
            if attempt == 8:
                raise RuntimeError(
                    f"failed to resolve pinned metadata after {attempt} attempts"
                ) from exc
            time.sleep(min(2**attempt, 30))
    if paths is None:
        raise RuntimeError("failed to resolve pinned candidate metadata") from last_error
    if len(paths) != 1:
        raise SystemExit(
            f"candidate {filename!r} is absent at dataset revision {REVISION}"
        )
    metadata = paths[0]
    lfs = getattr(metadata, "lfs", None)
    lfs_sha = getattr(lfs, "sha256", None)
    if not isinstance(metadata.size, int) or not re.fullmatch(
        r"[0-9a-f]{64}", str(lfs_sha or "")
    ):
        raise RuntimeError(f"candidate {filename!r} lacks pinned LFS metadata")
    scene_name = f"candidate-{args.scene_hash[:12]}"
    return scene_name, {
        "scene_hash": args.scene_hash,
        "filename": filename,
        "category": args.category,
        "expected_bytes": metadata.size,
        "expected_sha256": lfs_sha,
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(32 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def classify_members(names: list[str]) -> dict[str, object]:
    lower = [name.lower() for name in names]
    images = [
        name
        for name in names
        if PurePosixPath(name).suffix.lower() in {".jpg", ".jpeg", ".png"}
    ]
    pose_files = [
        name
        for name, normalized in zip(names, lower)
        if any(
            marker in normalized
            for marker in (
                "cameras.bin",
                "cameras.txt",
                "images.bin",
                "images.txt",
                "transforms.json",
                "poses_bounds.npy",
            )
        )
    ]
    point_files = [
        name
        for name, normalized in zip(names, lower)
        if "points3d.bin" in normalized or "points3d.txt" in normalized
    ]
    return {
        "entries": len(names),
        "images": len(images),
        "pose_files": pose_files,
        "point_files": point_files,
        "image_members": images,
    }


def make_contact_sheet(
    archive: zipfile.ZipFile,
    image_members: list[str],
    output: Path,
) -> None:
    if not image_members:
        raise RuntimeError("archive contains no previewable images")
    indices = {
        round(index * (len(image_members) - 1) / 11)
        for index in range(min(12, len(image_members)))
    }
    selected = [image_members[index] for index in sorted(indices)]
    tile_size = (320, 180)
    sheet = Image.new("RGB", (tile_size[0] * 4, tile_size[1] * 3), "#111517")
    draw = ImageDraw.Draw(sheet)
    for tile_index, name in enumerate(selected):
        with archive.open(name) as source:
            image = Image.open(io.BytesIO(source.read())).convert("RGB")
        image = ImageOps.fit(image, tile_size, Image.Resampling.LANCZOS)
        x = (tile_index % 4) * tile_size[0]
        y = (tile_index // 4) * tile_size[1]
        sheet.paste(image, (x, y))
        draw.rectangle((x, y + 154, x + 320, y + 180), fill=(10, 14, 16, 190))
        draw.text((x + 8, y + 160), PurePosixPath(name).name, fill="#e8edef")
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92)


def safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for member in archive.infolist():
        if not is_safe_member(member.filename):
            raise RuntimeError(f"unsafe archive member: {member.filename!r}")
        target = (destination / member.filename).resolve()
        if destination != target and destination not in target.parents:
            raise RuntimeError(f"unsafe archive destination: {member.filename!r}")
        archive.extract(member, destination)


def write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report_path = args.output / "source.json"
    try:
        from huggingface_hub import HfApi, hf_hub_download
        from huggingface_hub.errors import GatedRepoError, HfHubHTTPError
    except ImportError as exc:
        raise SystemExit(
            "huggingface_hub is required: python -m pip install huggingface_hub"
        ) from exc

    api = HfApi()
    scene_name, scene = resolve_scene(args, api)
    scene_hash = str(scene["scene_hash"])
    filename = str(scene["filename"])

    try:
        api.whoami()
    except Exception:
        report = {
            "schema_version": 1,
            "status": "blocked",
            "reason": "huggingface_not_authenticated",
            "source": SOURCE_URL,
            "repo_id": REPO_ID,
            "revision": REVISION,
            "filename": filename,
            "scene": scene_name,
            "scene_hash": scene_hash,
            "license": LICENSE,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "credential_forwarded_to_cluster": False,
        }
        write_report(report_path, report)
        print(
            "BLOCKED: accept the DL3DV terms in the browser, then run "
            "`hf auth login` locally. Do not paste the token into this project.",
            file=sys.stderr,
        )
        raise SystemExit(3)

    try:
        downloaded = Path(
            hf_hub_download(
                repo_id=REPO_ID,
                repo_type="dataset",
                filename=filename,
                revision=REVISION,
                cache_dir=args.cache_dir,
                force_download=args.force,
            )
        )
    except (GatedRepoError, HfHubHTTPError) as exc:
        report = {
            "schema_version": 1,
            "status": "blocked",
            "reason": "dl3dv_terms_not_accepted_or_access_denied",
            "source": SOURCE_URL,
            "repo_id": REPO_ID,
            "revision": REVISION,
            "filename": filename,
            "scene": scene_name,
            "scene_hash": scene_hash,
            "local_authentication_present": True,
            "license": LICENSE,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "credential_forwarded_to_cluster": False,
            "error_type": type(exc).__name__,
        }
        write_report(report_path, report)
        print(
            "BLOCKED: the local account is authenticated but cannot read the "
            "gated DL3DV file. Accept the dataset terms and retry.",
            file=sys.stderr,
        )
        raise SystemExit(4) from exc

    archive_path = args.output / f"{scene_hash}.zip"
    if downloaded.resolve() != archive_path.resolve():
        if archive_path.exists() and not args.force:
            if archive_path.stat().st_size != downloaded.stat().st_size:
                raise RuntimeError("existing local archive size differs from pinned download")
        else:
            archive_path.unlink(missing_ok=True)
            try:
                archive_path.hardlink_to(downloaded)
            except OSError:
                import shutil

                shutil.copyfile(downloaded, archive_path)

    actual_bytes = archive_path.stat().st_size
    actual_sha256 = sha256(archive_path)
    if actual_bytes != int(scene["expected_bytes"]):
        raise RuntimeError(
            f"archive byte count mismatch: {actual_bytes} != "
            f"{scene['expected_bytes']}"
        )
    if actual_sha256 != str(scene["expected_sha256"]):
        raise RuntimeError(
            f"archive SHA-256 mismatch: {actual_sha256} != "
            f"{scene['expected_sha256']}"
        )

    with zipfile.ZipFile(archive_path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP CRC validation failed at {bad!r}")
        names = [member.filename for member in archive.infolist()]
        if not all(is_safe_member(name) for name in names):
            raise RuntimeError("archive contains an unsafe member path")
        inventory = classify_members(names)
        if int(inventory["images"]) < 50:
            raise RuntimeError(f"too few source images: {inventory['images']}")
        if not inventory["pose_files"]:
            raise RuntimeError("archive does not expose camera poses/intrinsics")
        preview_path = args.output / "source-contact-sheet.jpg"
        make_contact_sheet(
            archive,
            list(inventory.pop("image_members")),
            preview_path,
        )
        if args.extract_to is not None:
            safe_extract(archive, args.extract_to)

    report = {
        "schema_version": 1,
        "status": "complete",
        "source": SOURCE_URL,
        "repo_id": REPO_ID,
        "revision": REVISION,
        "filename": filename,
        "scene": scene_name,
        "scene_hash": scene_hash,
        "category": scene["category"],
        "local_authentication_present": True,
        "license": LICENSE,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "archive": {
            "path": str(archive_path),
            "bytes": actual_bytes,
            "sha256": actual_sha256,
            "expected_bytes": scene["expected_bytes"],
            "expected_sha256": scene["expected_sha256"],
            "zip_crc_passed": True,
        },
        "inventory": inventory,
        "preview": str(preview_path),
        "extracted_to": str(args.extract_to) if args.extract_to else None,
        "credential_forwarded_to_cluster": False,
    }
    write_report(report_path, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
