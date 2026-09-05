from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _resolve_lupdate(project_root: Path) -> str | None:
    command = shutil.which("pyside6-lupdate")
    if command is not None:
        return command

    candidates = (
        project_root / ".venv" / "Scripts" / "pyside6-lupdate.exe",
        project_root / ".venv" / "Lib" / "site-packages" / "PySide6" / "lupdate.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    source_root = project_root / "src" / "xenix"
    translations_root = source_root / "translations"
    translations_root.mkdir(parents=True, exist_ok=True)
    source_files = [str(path) for path in sorted(source_root.rglob("*.py"))]

    command = _resolve_lupdate(project_root)
    if command is None:
        raise SystemExit("pyside6-lupdate is not available in the active environment.")

    subprocess.run(
        [
            command,
            *source_files,
            "-extensions",
            "py",
            "-ts",
            str(translations_root / "xenix_en_US.ts"),
            str(translations_root / "xenix_zh_CN.ts"),
        ],
        check=True,
        cwd=project_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
