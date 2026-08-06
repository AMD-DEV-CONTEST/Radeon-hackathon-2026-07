from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def _resolve_lrelease(project_root: Path) -> str | None:
    command = shutil.which("pyside6-lrelease")
    if command is not None:
        return command

    candidates = (
        project_root / ".venv" / "Scripts" / "pyside6-lrelease.exe",
        project_root / ".venv" / "Lib" / "site-packages" / "PySide6" / "lrelease.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _supported_translation_names(project_root: Path) -> frozenset[str]:
    source_root = project_root / "src"
    sys.path.insert(0, str(source_root))
    try:
        from xenix.i18n import SUPPORTED_LOCALES, TRANSLATION_BASENAME
    finally:
        sys.path.remove(str(source_root))
    return frozenset(
        f"{TRANSLATION_BASENAME}_{locale_code}.ts"
        for locale_code in SUPPORTED_LOCALES
    )


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    translations_root = project_root / "src" / "xenix" / "translations"
    ts_paths = sorted(translations_root.glob("*.ts"))
    if not ts_paths:
        raise SystemExit("No translation source files were found.")
    found_names = {path.name for path in ts_paths}
    missing_names = sorted(_supported_translation_names(project_root) - found_names)
    if missing_names:
        raise SystemExit(
            "Translation sources are missing for supported locales: "
            + ", ".join(missing_names)
        )

    command = _resolve_lrelease(project_root)
    if command is None:
        raise SystemExit("pyside6-lrelease is not available in the active environment.")

    for ts_path in ts_paths:
        qm_path = ts_path.with_suffix(".qm")
        subprocess.run(
            [
                command,
                str(ts_path),
                "-qm",
                str(qm_path),
            ],
            check=True,
            cwd=project_root,
        )
        if not qm_path.is_file() or qm_path.stat().st_size == 0:
            raise SystemExit(
                f"Translation compiler did not produce a non-empty output: {qm_path}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
