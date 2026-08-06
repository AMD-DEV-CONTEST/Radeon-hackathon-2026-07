"""Create a deterministic source-only AMD deployment archive."""

from __future__ import annotations

import hashlib
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_TOP_LEVEL = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".venv-dev",
    "artifacts",
    "data",
    "datasets",
    "models",
    "workspace",
}
EXCLUDED_NAMES = {
    'erver progress"q',
    "erver progress_q",
    "Qweasd123",
    "Qweasd123.pub",
    "RR",
}
EXCLUDED_SUFFIXES = {".gguf", ".safetensors", ".bin", ".zip", ".tar", ".gz", ".key", ".pem"}


def included_files() -> list[Path]:
    return sorted(
        (
            path
            for path in ROOT.rglob("*")
            if path.is_file()
            and path.relative_to(ROOT).parts[0] not in EXCLUDED_TOP_LEVEL
            and path.name not in EXCLUDED_NAMES
            and path.suffix.casefold() not in EXCLUDED_SUFFIXES
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        ),
        key=lambda item: item.as_posix(),
    )


def build() -> tuple[Path, Path]:
    output = ROOT / "artifacts" / "delivery"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "BuildGuard-Radeon-amd-deployment.tar.gz"
    with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as tar:
        for path in included_files():
            tar.add(path, arcname=Path("BuildGuard-Radeon-restored") / path.relative_to(ROOT))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = archive.with_suffix(archive.suffix + ".sha256")
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    return archive, checksum


if __name__ == "__main__":
    package, package_checksum = build()
    print(package)
    print(package_checksum)
