import json
import re
from pathlib import Path

from app.version import APP_VERSION, APP_VERSION_TAG
from main import app


ROOT = Path(__file__).resolve().parents[1]


def _cargo_package_version(path: Path) -> str:
    match = re.search(
        r'(?ms)^\[package\]\s+.*?^version\s*=\s*"([^"]+)"',
        path.read_text(encoding="utf-8"),
    )
    assert match is not None
    return match.group(1)


def _cargo_lock_worldview_version(path: Path) -> str:
    match = re.search(
        r'(?ms)^\[\[package\]\]\s+name\s*=\s*"worldview"\s+version\s*=\s*"([^"]+)"',
        path.read_text(encoding="utf-8"),
    )
    assert match is not None
    return match.group(1)


def test_runtime_and_desktop_versions_are_consistent():
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    tauri = json.loads(
        (ROOT / "frontend" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )

    assert APP_VERSION == "1.31.2"
    assert app.version == APP_VERSION
    assert app.title.endswith(APP_VERSION_TAG)
    assert package["version"] == APP_VERSION
    assert tauri["version"] == APP_VERSION
    assert _cargo_package_version(ROOT / "frontend" / "src-tauri" / "Cargo.toml") == APP_VERSION
    assert (
        _cargo_lock_worldview_version(ROOT / "frontend" / "src-tauri" / "Cargo.lock")
        == APP_VERSION
    )
