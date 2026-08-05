"""
Enforcement test: only the designated controller modules may call Playwright,
pyautogui, adb, or VM action APIs directly.

This prevents action safety governor bypass by ensuring no other module
can execute actions on a real environment without going through the controller.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_SCRIPTS = _ROOT / "scripts"

# Modules that ARE allowed to call these APIs
_ALLOWED_MODULES: frozenset[str] = frozenset(
    {
        # Browser
        "scripts/browser/browser_controller.py",
        "scripts/ide/browser_agent.py",
        # Desktop
        "scripts/desktop/screen_controller.py",
        "scripts/desktop/vm_manager.py",
        "scripts/desktop/clipboard_guard.py",
        "scripts/desktop/window_manager.py",
        # Mobile
        "scripts/mobile/adb_controller.py",
        "scripts/mobile/emulator_manager.py",
        "scripts/mobile/uiautomator_reader.py",
        "scripts/mobile/permission_guard.py",
        "scripts/mobile/mobile_verifier.py",
        # Tests (allowed to import/test controllers)
        "tests/",
    }
)

# Patterns for restricted APIs
_RESTRICTED_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "playwright",
        re.compile(r"\bsync_playwright\b|\basync_playwright\b|\bfrom playwright\b", re.I),
    ),
    (
        "pyautogui",
        re.compile(
            r"\bimport pyautogui\b|\bpyautogui\.(click|type|press|scroll|moveTo|drag)\b", re.I
        ),
    ),
    ("adb_direct", re.compile(r"\bsubprocess\.(run|Popen|call)\s*\(\s*\[.*\badb\b", re.I)),
    ("vboxmanage", re.compile(r"\bsubprocess\.(run|Popen)\s*\(\s*\[.*\bVBoxManage\b", re.I)),
    ("qemu", re.compile(r"\bsubprocess\.(run|Popen)\s*\(\s*\[.*\bqemu-\w+", re.I)),
    ("avdmanager", re.compile(r"\bsubprocess\.(run|Popen)\s*\(\s*\[.*\bavdmanager\b", re.I)),
    ("vncdotool", re.compile(r"\bimport vncdotool\b|\bvncdotool\.api\b")),
]


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _is_allowed(rel: str) -> bool:
    for allowed in _ALLOWED_MODULES:
        if rel.startswith(allowed) or rel == allowed:
            return True
    return False


def _scan_file(path: Path) -> list[str]:
    rel = _relative(path)
    if _is_allowed(rel):
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    violations = []
    for i, line in enumerate(text.splitlines(), 1):
        for api_name, pattern in _RESTRICTED_PATTERNS:
            if pattern.search(line):
                violations.append(f"{rel}:{i} [{api_name}]: {line.strip()}")
    return violations


def test_no_unsafe_controller_bypass():
    """
    Only browser_controller, screen_controller, vm_manager, and adb_controller
    may call Playwright, pyautogui, adb, VBoxManage, or vncdotool APIs directly.
    """
    violations = []
    for py_file in _SCRIPTS.rglob("*.py"):
        violations.extend(_scan_file(py_file))

    assert not violations, (
        f"Found {len(violations)} unsafe controller bypass(es) — "
        "action APIs must only be called from their designated controller modules:\n"
        + "\n".join(violations)
    )
