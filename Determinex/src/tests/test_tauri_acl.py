"""Is the Tauri app-level ACL on, and does it cover every command?

WHY THIS EXISTS
---------------
Until 2026-07-30 there was no `src-tauri/permissions/` directory and no `__app-acl__` key in
`gen/schemas/acl-manifests.json`. Tauri 2.10 only ACL-checks a command when
`plugin_command.is_some() || has_app_acl_manifest` (webview/mod.rs), so with no app ACL manifest
**every one of the 173 registered commands was invokable from any webview with no permission and no
window restriction** -- including `run_terminal_command`, which shells to
`powershell -ExecutionPolicy Bypass` with CREATE_NO_WINDOW.

The `windows: [...]` list in capabilities/default.json did not help: it governs only `core:*` and
plugin commands. Turning the app ACL on is what makes it apply to app commands too, and what makes a
command added later denied by default instead of silently exposed.

TWO FAILURE DIRECTIONS, BOTH GUARDED
------------------------------------
Turning an ACL on is not free: if the generated manifest omits a command, that command is DENIED at
runtime and the feature silently stops working -- invisible without launching the GUI. So these
tests assert both that the ACL is present AND that it covers the registered set exactly. That pair
is what makes it safe to enable without a GUI run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TAURI = ROOT / "frontend" / "src-tauri"
MANIFEST = TAURI / "gen" / "schemas" / "acl-manifests.json"


def registered_commands() -> set[str]:
    src = (TAURI / "src" / "lib.rs").read_text(encoding="utf-8")
    match = re.search(r"generate_handler!\s*\[(.*?)\]", src, re.DOTALL)
    assert match, "could not find generate_handler! in lib.rs"
    body = re.sub(r"//.*?$", "", match.group(1), flags=re.MULTILINE)
    return {c.strip().split("::")[-1] for c in body.split(",") if c.strip()}


def acl_allowed_commands() -> set[str]:
    if not MANIFEST.is_file():
        return set()
    app = json.loads(MANIFEST.read_text(encoding="utf-8")).get("__app-acl__")
    if not app:
        return set()
    allowed: set[str] = set()
    for permission in (app.get("permissions") or {}).values():
        allowed |= set(((permission.get("commands") or {}).get("allow")) or [])
    return allowed


def test_a_permissions_directory_exists():
    """Its mere existence is what flips has_app_acl_manifest to true."""
    perms = TAURI / "permissions"
    assert perms.is_dir(), (
        f"{perms} is missing, so Tauri sets has_app_acl_manifest=false and skips the ACL check for "
        f"every app command"
    )
    assert list(perms.glob("*.toml")), f"no permission files in {perms}"


def test_the_default_capability_references_the_app_command_set():
    cap = json.loads((TAURI / "capabilities" / "default.json").read_text(encoding="utf-8"))
    assert "allow-app-commands" in cap.get("permissions", []), (
        "capabilities/default.json does not reference allow-app-commands, so the generated app ACL "
        "is not attached to any window and the commands are unreachable"
    )
    # Window scoping only becomes meaningful once the app ACL is on; assert it is still declared.
    assert cap.get("windows"), "the capability declares no windows"


def test_the_generated_acl_is_present_and_covers_every_registered_command():
    """THE regression, in both directions.

    Missing entries mean silent runtime denial; the ACL being absent entirely means no checking at
    all. Skips only when the schema has not been generated yet (a clean checkout before any build).
    """
    if not MANIFEST.is_file():
        pytest.skip("gen/schemas/acl-manifests.json not generated yet; run a cargo build")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert "__app-acl__" in manifest, (
        "the generated manifest has no __app-acl__ key, so has_app_acl_manifest is false and Tauri "
        "performs no ACL check on app commands"
    )

    registered = registered_commands()
    allowed = acl_allowed_commands()
    missing = sorted(registered - allowed)
    assert not missing, (
        f"{len(missing)} registered command(s) are absent from the generated ACL and would be "
        f"DENIED at runtime, breaking the feature silently: {missing[:12]}"
    )


def test_the_permission_file_has_not_drifted_from_the_registered_set():
    """Source-level counterpart, so this fails on a clean checkout too rather than skipping.

    The generated schema is a build artifact; the .toml is the input. If someone adds a command to
    generate_handler! and forgets the permission, this catches it without needing a build.
    """
    toml = (TAURI / "permissions" / "app-commands.toml").read_text(encoding="utf-8")
    declared = set(re.findall(r'^allow\s*=\s*\["([^"]+)"\]', toml, re.MULTILINE))
    registered = registered_commands()

    missing = sorted(registered - declared)
    assert not missing, (
        f"permissions/app-commands.toml does not declare {len(missing)} registered command(s), so "
        f"they will be denied once the ACL is generated: {missing[:12]}. Regenerate it."
    )
    stale = sorted(declared - registered)
    assert not stale, (
        f"permissions/app-commands.toml declares {len(stale)} command(s) that are no longer "
        f"registered: {stale[:12]}. Regenerate it."
    )


def test_no_dead_shell_grants_remain_in_the_capability():
    """`shell:allow-execute` / `shell:allow-spawn` were unscoped, and unscoped shell in Tauri v2
    FAILS CLOSED (tauri-plugin-shell scope.rs returns Error::NotFound on a scope miss).
    `@tauri-apps/plugin-shell` is not even a frontend dependency. So they granted nothing and only
    made the capability read as though arbitrary shell execution were permitted -- the kind of
    thing an enterprise security reviewer will find first."""
    cap = json.loads((TAURI / "capabilities" / "default.json").read_text(encoding="utf-8"))
    permissions = cap.get("permissions", [])
    for dead in ("shell:allow-execute", "shell:allow-spawn"):
        assert dead not in permissions, (
            f"{dead} is unscoped and therefore inert, but it advertises arbitrary shell execution. "
            f"Remove it, or scope it to the specific commands actually needed."
        )
