#!/usr/bin/env python3
"""Pack a ProgramBench per-tool override into an official-eval run directory.

This is intentionally small and boring. External models should use this instead
of ad hoc copy/tar commands so candidate staging is reproducible.

Usage:
    python scripts/pb_pack_candidate.py anordal__shellharden.6a6ffd4
    python scripts/pb_pack_candidate.py anordal__shellharden.6a6ffd4 --run-root .determinex_staging/pb_shellharden
"""

from __future__ import annotations

import argparse
import os
import shutil
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / "corpus" / "programbench" / "per_tool_overrides"
PB_STAGING_ROOT = Path(os.environ.get("DETERMINEX_PB_STAGING_ROOT", "T:/determinex-staging"))
DEFAULT_RUN_ROOT = PB_STAGING_ROOT / "programbench_candidate"


_LF_NORMALIZE_EXTS = (
    ".sh",
    ".py",
    ".bash",
    ".conf",
    ".cfg",
    ".ini",
    ".toml",
    ".yaml",
    ".yml",
    ".txt",
    ".json",
)


def _strip_crlf_inplace(path: Path) -> bool:
    """Convert CRLF -> LF in-place for text files staged for pack.

    Windows-on-Linux footgun: scaffolds written via Python on Windows pick up
    `\\r\\n` line endings. When the Linux container runs `./compile.sh`, the
    shebang resolves to `/bin/bash\\r` -> `bad interpreter`. This normalization
    runs at pack time so it's caught regardless of how the file was authored
    (editor, Python script, copy/paste, network share). One central choke point;
    never have to debug this again.
    Returns True if the file was modified.
    """
    if path.suffix.lower() not in _LF_NORMALIZE_EXTS:
        return False
    try:
        b = path.read_bytes()
    except OSError:
        return False
    if b"\r\n" not in b:
        return False
    path.write_bytes(b.replace(b"\r\n", b"\n"))
    return True


def _add_file(tar: tarfile.TarFile, path: Path, arcname: str, mode: int) -> None:
    info = tar.gettarinfo(str(path), arcname=arcname)
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    with path.open("rb") as f:
        tar.addfile(info, f)


def _add_dir(tar: tarfile.TarFile, path: Path, arcname: str, mode: int = 0o755) -> None:
    info = tar.gettarinfo(str(path), arcname=arcname)
    info.type = tarfile.DIRTYPE
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    tar.addfile(info)


_SKIP_NAMES = {
    "__pycache__",
    ".git",
    "target",
    "node_modules",
    ".cargo",
    ".rustup",
    "build",
    "dist",
    "eval",
}
_SKIP_SUFFIXES = (".bak", ".backup", ".regressed_pre_recovery", ".pre_bundle", ".pyc", ".pyo")


def _gather_sources(override_dir: Path) -> list[tuple[Path, str]]:
    """Recursively collect source files for packing.

    Returns a list of (absolute_path, archive_name) tuples. Archive name is
    the path RELATIVE to override_dir (forward slashes). Subdirectories like
    `src/`, `config/`, `cmd/`, etc. are included so native crates with
    multi-file layouts (Rust src/, Go subpackages) pack correctly.
    """
    out: list[tuple[Path, str]] = []
    for path in override_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(override_dir)
        parts = rel.parts
        if any(p in _SKIP_NAMES or p.startswith(".") for p in parts):
            continue
        if path.name == "compile.sh" and len(parts) == 1:
            # compile.sh is added separately at the archive root
            continue
        if any(path.name.endswith(s) for s in _SKIP_SUFFIXES):
            continue
        arcname = "/".join(parts)
        out.append((path, arcname))
    return out


def _gather_dirs(override_dir: Path) -> list[tuple[Path, str]]:
    """Collect source directories, including empty native-resource dirs.

    Some native projects bind directories at compile time. Rust crates using
    include_dir!("aliases") fail if the directory disappears during staging,
    even when the directory intentionally contains no files.
    """
    out: list[tuple[Path, str]] = []
    for path in override_dir.rglob("*"):
        if not path.is_dir():
            continue
        rel = path.relative_to(override_dir)
        parts = rel.parts
        if any(p in _SKIP_NAMES or p.startswith(".") for p in parts):
            continue
        out.append((path, "/".join(parts)))
    return out


def pack_candidate(slug: str, run_root: Path) -> Path:
    override_dir = OVERRIDES / slug
    if not override_dir.is_dir():
        raise SystemExit(f"override not found: {override_dir}")

    compile_sh = override_dir / "compile.sh"
    if not compile_sh.is_file():
        raise SystemExit(f"missing override compile.sh: {compile_sh}")

    dirs = _gather_dirs(override_dir)
    sources = _gather_sources(override_dir)
    if not sources:
        raise SystemExit(f"no source files found in override: {override_dir}")

    inst_dir = run_root / slug
    source_dir = inst_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(compile_sh, source_dir / "compile.sh")
    for _, arcname in dirs:
        (source_dir / arcname).mkdir(parents=True, exist_ok=True)
    for src_path, arcname in sources:
        dest = source_dir / arcname
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_path, dest)

    # CRLF normalization on staged copies only (originals stay editable on
    # Windows). Skip binary files - they must not be mangled.
    crlf_fixed: list[str] = []
    for staged in source_dir.rglob("*"):
        if not staged.is_file():
            continue
        if staged.suffix in (
            ".go",
            ".rs",
            ".c",
            ".cpp",
            ".h",
            ".py",
            ".sh",
            ".toml",
            ".mod",
            ".sum",
            ".lock",
            ".md",
            ".txt",
        ):
            if _strip_crlf_inplace(staged):
                crlf_fixed.append(str(staged.relative_to(source_dir)))
    if crlf_fixed:
        print(f"  CRLF -> LF normalized at pack-time: {', '.join(crlf_fixed)}")

    submission = inst_dir / "submission.tar.gz"
    with tarfile.open(submission, "w:gz") as tar:
        _add_file(tar, source_dir / "compile.sh", "compile.sh", 0o755)
        for _, arcname in sorted(dirs, key=lambda p: p[1]):
            _add_dir(tar, source_dir / arcname, arcname)
        for _, arcname in sorted(sources, key=lambda p: p[1]):
            staged_path = source_dir / arcname
            # Detect executable mode (binaries identified by absence of a
            # text suffix). Use 0o755 for binaries, 0o644 for sources.
            if staged_path.suffix == "" or staged_path.suffix in (".sh",):
                mode = 0o755
            elif _is_native_binary(staged_path):
                mode = 0o755
            else:
                mode = 0o644
            _add_file(tar, staged_path, arcname, mode)

    return submission


def _is_native_binary(path: Path) -> bool:
    """Detect ELF / PE / Mach-O native binaries by magic bytes."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return False
    if head.startswith(b"\x7fELF"):
        return True
    if head[:2] == b"MZ":
        return True
    if head[:4] in (
        b"\xfe\xed\xfa\xce",
        b"\xfe\xed\xfa\xcf",
        b"\xce\xfa\xed\xfe",
        b"\xcf\xfa\xed\xfe",
    ):
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="full ProgramBench instance id, e.g. owner__repo.hash")
    ap.add_argument(
        "--run-root",
        type=Path,
        default=DEFAULT_RUN_ROOT,
        help="parent directory that will contain <slug>/source and <slug>/submission.tar.gz",
    )
    args = ap.parse_args()

    run_root = args.run_root if args.run_root.is_absolute() else ROOT / args.run_root
    submission = pack_candidate(args.slug, run_root)
    print(f"packed {submission}")
    print(f"eval with: python scripts/programbench_eval_runner.py {args.slug} {run_root} --force")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
