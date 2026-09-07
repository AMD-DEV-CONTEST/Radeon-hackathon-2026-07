"""Populate and verify simulation assets for reproducible evaluation.

Priority order for each required asset:

1. Already present under ``assets/`` (the submitted tree ships meshes so clones work offline);
2. Copy from well-known local development mirrors (optional);
3. Copy the Franka model from the installed ``genesis`` package;
4. Optional network download of YCB google_16k packs when ``--download`` is set and a
   reachable URL is configured (see ``ASSETS.md`` / README).

Run ``python -m radeonvla.setup_assets --verify`` to check SHA256 against
``assets/SHA256SUMS`` when that file is present.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from radeonvla.paths import ASSETS_DIR, PROJECT_ROOT, ROBOT_DIR, YCB_DIR
from radeonvla.protocol import BOWL_YCB, FRUIT_YCB

REQUIRED_YCB = tuple(sorted({*FRUIT_YCB.values(), BOWL_YCB}))
REQUIRED_OBJECT_FILES = ("textured.obj", "collision.ply")
ROBOT_REQUIRED = "panda.xml"
SHA256SUMS = ASSETS_DIR / "SHA256SUMS"

# Official-style YCB google_16k archives used by many robotics stacks.
# Host: caltech-hosted mirror used by the YCB Object and Model Set project pages.
# If a host becomes unavailable, the project tree still contains the extracted files.
YCB_TARBALL_URLS: dict[str, tuple[str, ...]] = {
    "011_banana": (
        "https://huggingface.co/datasets/lerobot/ycb_assets/resolve/main/011_banana.tar.gz",
        "http://ycb-benchmarks.s3-website-us-east-1.amazonaws.com/data/berkeley_processed/011_banana/google_16k.tgz",
    ),
    "013_apple": (
        "https://huggingface.co/datasets/lerobot/ycb_assets/resolve/main/013_apple.tar.gz",
    ),
    "014_lemon": (
        "https://huggingface.co/datasets/lerobot/ycb_assets/resolve/main/014_lemon.tar.gz",
    ),
    "017_orange": (
        "https://huggingface.co/datasets/lerobot/ycb_assets/resolve/main/017_orange.tar.gz",
    ),
    "018_plum": (
        "https://huggingface.co/datasets/lerobot/ycb_assets/resolve/main/018_plum.tar.gz",
    ),
    "024_bowl": (
        "https://huggingface.co/datasets/lerobot/ycb_assets/resolve/main/024_bowl.tar.gz",
    ),
}


def _have_object(directory: Path) -> bool:
    return directory.is_dir() and all((directory / name).is_file() for name in REQUIRED_OBJECT_FILES)


def _copy_tree(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _candidate_ycb_roots() -> list[Path]:
    roots: list[Path] = []
    for relative in (
        Path("../../references/franka_fruit_pick_demo/assets/ycb"),
        Path("../../../references/franka_fruit_pick_demo/assets/ycb"),
        Path("../../RadeonVLA-Reflex/assets/ycb"),
    ):
        roots.append((PROJECT_ROOT / relative).resolve())
    roots.append(Path.home() / ".cache" / "radeonvla" / "ycb")
    return roots


def _candidate_franka_roots() -> list[Path]:
    roots: list[Path] = []
    for relative in (
        Path("../../references/franka_fruit_pick_demo/assets/robots/franka"),
        Path("../../../references/franka_fruit_pick_demo/assets/robots/franka"),
        Path("../../references/genesis-world/genesis/assets/xml/franka_emika_panda"),
    ):
        roots.append((PROJECT_ROOT / relative).resolve())
    try:
        genesis = importlib.import_module("genesis")
        genesis_root = Path(genesis.__file__).resolve().parent
        roots.append(genesis_root / "assets" / "xml" / "franka_emika_panda")
    except Exception:
        pass
    return roots


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_checksums(*, strict: bool = True) -> None:
    """Verify assets against assets/SHA256SUMS when the manifest exists."""
    if not SHA256SUMS.is_file():
        if strict:
            raise FileNotFoundError(f"Missing checksum manifest: {SHA256SUMS}")
        print("[assets] no SHA256SUMS present; skip verify")
        return

    errors: list[str] = []
    checked = 0
    for line in SHA256SUMS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, rel = line.split(None, 1)
        rel = rel.lstrip("*").strip()
        # Manifest paths are relative to assets/ (e.g. ycb/011_banana/textured.obj).
        if rel.startswith("assets/"):
            path = PROJECT_ROOT / rel
        else:
            path = ASSETS_DIR / rel
        if not path.is_file():
            errors.append(f"missing {rel}")
            continue
        actual = _sha256_file(path)
        checked += 1
        if actual != digest:
            errors.append(f"mismatch {rel}: expected {digest[:12]}… got {actual[:12]}…")
    if errors:
        raise RuntimeError("Asset verification failed:\n  " + "\n  ".join(errors))
    print(f"[assets] verified {checked} files against {SHA256SUMS.name}")


def _download(url: str, dest: Path, timeout: float = 120.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "radeonvla-setup-assets/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out)


def _try_download_ycb(name: str, dst: Path) -> bool:
    """Attempt an optional download and return whether the asset became available."""
    urls = YCB_TARBALL_URLS.get(name, ())
    cache = Path.home() / ".cache" / "radeonvla" / "downloads"
    cache.mkdir(parents=True, exist_ok=True)
    for url in urls:
        archive = cache / f"{name}.download"
        try:
            print(f"[assets] downloading {name} <- {url}")
            _download(url, archive)
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                if tarfile.is_tarfile(archive):
                    with tarfile.open(archive, "r:*") as tar:
                        tar.extractall(tmp_path)
                else:
                    continue
                # Find a directory that already has required files, or the extracted root.
                candidates = [p for p in tmp_path.rglob("textured.obj")]
                if not candidates:
                    continue
                src_dir = candidates[0].parent
                # Ensure collision.ply exists; if only mesh, skip (need both).
                if not (src_dir / "collision.ply").is_file():
                    # Some packs use textured.obj only; collision may be named differently.
                    colliders = list(src_dir.glob("*.ply"))
                    if colliders and not (src_dir / "collision.ply").is_file():
                        shutil.copy2(colliders[0], src_dir / "collision.ply")
                if not _have_object(src_dir):
                    continue
                _copy_tree(src_dir, dst)
                print(f"[assets] downloaded ycb/{name} -> {dst}")
                return True
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, tarfile.TarError) as exc:
            print(f"[assets] download failed for {name} ({url}): {exc}")
            continue
    return False


def setup_assets(*, force: bool = False, download: bool = False) -> Path:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []

    ycb_roots = [root for root in _candidate_ycb_roots() if root.is_dir()]
    for name in REQUIRED_YCB:
        dst = YCB_DIR / name
        if _have_object(dst) and not force:
            continue
        src = next((root / name for root in ycb_roots if _have_object(root / name)), None)
        if src is not None:
            _copy_tree(src, dst)
            print(f"[assets] copied ycb/{name} <- {src}")
            continue
        if download and _try_download_ycb(name, dst):
            continue
        if not _have_object(dst):
            missing.append(f"ycb/{name}")

    robot_ready = (ROBOT_DIR / ROBOT_REQUIRED).is_file() and not force
    if not robot_ready:
        src = next((root for root in _candidate_franka_roots() if (root / ROBOT_REQUIRED).is_file()), None)
        if src is None:
            missing.append("robots/franka")
        else:
            _copy_tree(src, ROBOT_DIR)
            print(f"[assets] copied robots/franka <- {src}")

    if missing:
        hint = (
            "Missing assets:\n  "
            + "\n  ".join(missing)
            + "\n\nThe project repository ships extracted meshes under assets/.\n"
            "If this is a sparse checkout, re-clone the full branch or run:\n"
            "  python -m radeonvla.setup_assets --download\n"
            "Franka can also be recovered from a genesis-world install.\n"
            "See assets/README.md and the Assets section of README.md."
        )
        raise FileNotFoundError(hint)

    print(f"[assets] ready at {ASSETS_DIR}")
    return ASSETS_DIR


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-copy assets even if present.")
    parser.add_argument(
        "--download",
        action="store_true",
        help="Allow network download of missing YCB packs (optional fallback).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify SHA256 of tracked asset files against assets/SHA256SUMS.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_assets(force=args.force, download=args.download)
    if args.verify:
        verify_checksums(strict=True)
    elif SHA256SUMS.is_file():
        try:
            verify_checksums(strict=False)
        except RuntimeError as exc:
            print(f"[assets] WARNING: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
