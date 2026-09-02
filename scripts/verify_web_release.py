"""Read-only integrity check for an already-built React workbench release."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("web/dist"), help="built frontend directory")
    args = parser.parse_args()
    dist = args.dist.resolve()
    index = dist / "index.html"
    assets = sorted(path for path in dist.rglob("*") if path.is_file() and path != index)
    if not index.is_file():
        raise SystemExit(f"ERROR: missing frontend entry point: {index}")
    if not assets:
        raise SystemExit(f"ERROR: no emitted frontend assets found under: {dist}")

    files = [index, *assets]
    print(f"release directory: {dist}")
    print(f"verified files: {len(files)}")
    for path in files:
        print(f"SHA256  {digest(path)}  {path.relative_to(dist).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
