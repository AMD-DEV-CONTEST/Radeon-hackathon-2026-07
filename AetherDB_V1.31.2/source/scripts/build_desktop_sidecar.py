"""Build and validate the host-native Python sidecar staged for Tauri."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_VERSION = json.loads(
    (ROOT / "frontend" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
)["version"]
STAGE_ROOT = ROOT / "frontend" / "src-tauri" / "backend" / "generated"
ASSET_PATHS = (
    Path("static"),
    Path("templates"),
    Path("prompts"),
    Path("resources") / "model_manifests",
    Path("resources") / "model_packages",
    Path("resources") / "ollama_install_manifests",
    Path("config.example.yaml"),
)
SENSITIVE_NAMES = {
    ".api_keys.json",
    ".env",
    "api_keys.json",
    "config.local.yaml",
    "config.yaml",
}
MODEL_EXTENSIONS = {".onnx", ".bin", ".safetensors", ".gguf", ".pt", ".pth"}
SECRET_PATTERNS = tuple(
    re.compile(value, re.IGNORECASE)
    for value in (
        r"sk-[A-Za-z0-9_-]{20,}",
        r"nvk_(?:admin_)?[a-f0-9]{32}",
        r"ghp_[A-Za-z0-9]{30,}",
        r"AIza[0-9A-Za-z_-]{30,}",
        r"xox[baprs]-[A-Za-z0-9-]{20,}",
        r"Bearer\s+[A-Za-z0-9._-]{24,}",
    )
)
TEXT_EXTENSIONS = {".json", ".yaml", ".yml", ".txt", ".html", ".css", ".js"}
BUILD_ID = os.environ.get("AETHERDB_BUILD_ID", f"dev-{APP_VERSION}").strip()


def _validate_build_id() -> None:
    if (
        not 3 <= len(BUILD_ID) <= 128
        or any(not (value.isalnum() or value in "._-") for value in BUILD_ID)
    ):
        raise RuntimeError("AETHERDB_BUILD_ID is malformed")


def _write_build_manifest() -> None:
    _validate_build_id()
    payload = {
        "schema_version": 1,
        "product": "AetherDB",
        "version": APP_VERSION,
        "build_id": BUILD_ID,
        "protocol_version": "1.0",
        "component": "backend-sidecar",
    }
    (STAGE_ROOT / "build-manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def executable_name() -> str:
    return "aetherdb-backend.exe" if os.name == "nt" else "aetherdb-backend"


def _pyinstaller_launcher() -> tuple[dict[str, str], str]:
    env = os.environ.copy()
    build_tools = env.get("AETHERDB_BUILD_TOOLS_PATH")
    if build_tools:
        path = str(Path(build_tools).expanduser().resolve())
        launcher = (
            f"import sys; sys.path.append({path!r}); "
            "from PyInstaller.__main__ import run; run()"
        )
        return env, launcher
    if importlib.util.find_spec("PyInstaller") is None:
        raise RuntimeError(
            "PyInstaller is unavailable. Install requirements-desktop-build.txt into the build environment "
            "or set AETHERDB_BUILD_TOOLS_PATH."
        )
    return env, "from PyInstaller.__main__ import run; run()"


def _safe_clear_stage() -> None:
    expected = (ROOT / "frontend" / "src-tauri" / "backend" / "generated").resolve()
    if STAGE_ROOT.resolve() != expected or ROOT.resolve() not in expected.parents:
        raise RuntimeError("Refusing to clear an unexpected sidecar stage path")
    if STAGE_ROOT.exists():
        shutil.rmtree(STAGE_ROOT)
    STAGE_ROOT.mkdir(parents=True)
    (STAGE_ROOT / ".gitkeep").touch()


def _copy_assets() -> None:
    for relative in ASSET_PATHS:
        source = ROOT / relative
        if not source.exists():
            raise FileNotFoundError(f"Required packaged asset is missing: {relative.as_posix()}")
        destination = STAGE_ROOT / relative
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def validate_stage() -> list[str]:
    issues: list[str] = []
    binary = STAGE_ROOT / executable_name()
    if not binary.is_file():
        issues.append(f"missing executable: {binary.name}")
    elif os.name != "nt" and not os.access(binary, os.X_OK):
        issues.append(f"sidecar is not executable on this Unix host: {binary.name}")
    for relative in ASSET_PATHS:
        if not (STAGE_ROOT / relative).exists():
            issues.append(f"missing asset: {relative.as_posix()}")
    manifest_path = STAGE_ROOT / "build-manifest.json"
    if not manifest_path.is_file():
        issues.append("missing asset: build-manifest.json")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("build_id") != BUILD_ID:
                issues.append("build manifest identity does not match the active build")
            if manifest.get("version") != APP_VERSION:
                issues.append("build manifest version does not match the backend")
        except (OSError, json.JSONDecodeError):
            issues.append("invalid asset: build-manifest.json")
    for path in STAGE_ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(STAGE_ROOT).as_posix()
        if path.name.lower() in SENSITIVE_NAMES:
            issues.append(f"sensitive runtime file: {relative}")
        if path.suffix.lower() in MODEL_EXTENSIONS:
            issues.append(f"model binary must not be bundled: {relative}")
        if path.suffix.lower() in TEXT_EXTENSIONS and path.stat().st_size <= 5 * 1024 * 1024:
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(pattern.search(text) for pattern in SECRET_PATTERNS):
                issues.append(f"real-looking secret: {relative}")
    return issues


def build(work_root: Path) -> None:
    env, launcher = _pyinstaller_launcher()
    work_root = work_root.expanduser().resolve()
    dist_root = work_root / "dist"
    pyinstaller_work = work_root / "work"
    spec_root = work_root / "spec"
    for path in (dist_root, pyinstaller_work, spec_root):
        path.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-c",
        launcher,
        str(ROOT / "main.py"),
        "--name",
        "aetherdb-backend",
        "--onedir",
        "--contents-directory",
        ".",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_root),
        "--workpath",
        str(pyinstaller_work),
        "--specpath",
        str(spec_root),
        "--paths",
        str(ROOT),
        "--collect-all",
        "sqlite_vec",
        "--hidden-import",
        "onnxruntime",
        "--hidden-import",
        "tokenizers",
    ]
    print(f"[INFO] Building AetherDB sidecar for {platform.system()} {platform.machine()}")
    subprocess.run(command, cwd=ROOT, env=env, check=True)

    source = dist_root / "aetherdb-backend"
    if not source.is_dir():
        raise RuntimeError(f"PyInstaller output is missing: {source}")
    _safe_clear_stage()
    shutil.copytree(source, STAGE_ROOT, dirs_exist_ok=True)
    _copy_assets()
    _write_build_manifest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--work-root",
        type=Path,
        default=Path(os.environ.get("AETHERDB_BUILD_CACHE_ROOT", ROOT / "build" / "desktop-sidecar")),
    )
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    if not args.validate_only:
        build(args.work_root)
    issues = validate_stage()
    if issues:
        for issue in issues:
            print(f"[BLOCKED] {issue}")
        return 1
    files = sum(1 for path in STAGE_ROOT.rglob("*") if path.is_file())
    print(f"[OK] packaged sidecar stage validated: {files} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
