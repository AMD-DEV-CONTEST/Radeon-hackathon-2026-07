"""The shipped VSIX must declare the identity package.json declares.

WHY THIS EXISTS
---------------
Found 2026-07-30. `determinex-0.1.0.vsix` on disk was a stale pre-rename build.

SEVERITY, corrected: that file is **gitignored** (`frontend/vscode-extension/.gitignore: *.vsix`), so
it was a LOCAL build artifact and was never shipped or published. `vsce publish` rebuilds from
package.json, so the wrong identity would not have reached the Marketplace by that route. It was a
local TESTING trap, not a distribution blocker — and it worked exactly as a trap: it cost real time
below. Its
`extension.vsixmanifest` said:

    <Identity Id="citadel" Publisher="lunarian-data-systems" />

while `package.json` said `name: determinex`, `publisher: darthceltic`. The manifest wins, so the
extension installed as **lunarian-data-systems.citadel** — the retired product name, published under
the wrong account. Publishing it would have put "Citadel" and `lunarian-data-systems` into the VS Code
Marketplace and Open VSX, directly contradicting CLAUDE.md's rename-finalized directive.

It was invisible for two reasons worth recording. `code --install-extension` printed *"Extension
'determinex-0.1.0.vsix' was successfully installed."* and exited 0 — the success message names the
FILE, not the identity, so it looks right. And every check anyone would run
(`code --list-extensions | grep determinex`, or looking for `~/.vscode/extensions/darthceltic.determinex`)
finds nothing, because it installed under a name nobody thought to search for.

The stale VSIX also shipped no LICENSE, on an AGPL project.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXT_DIR = ROOT / "frontend" / "vscode-extension"
PACKAGE_JSON = EXT_DIR / "package.json"


def _vsix_files() -> list[Path]:
    return sorted(EXT_DIR.glob("*.vsix"))


def _manifest_identity(vsix: Path) -> tuple[str, str, str]:
    with zipfile.ZipFile(vsix) as archive:
        manifest = archive.read("extension.vsixmanifest").decode("utf-8", "replace")
    ident = re.search(r"<Identity\b[^>]*>", manifest)
    assert ident, f"{vsix.name} has no <Identity> element"
    tag = ident.group(0)

    def attr(name: str) -> str:
        match = re.search(rf'{name}="([^"]*)"', tag)
        return match.group(1) if match else ""

    return attr("Id"), attr("Publisher"), attr("Version")


def test_every_committed_vsix_matches_package_json():
    """THE regression. The manifest is what VS Code installs under, so a mismatch means the extension
    lands under a name nobody is looking for -- and in this case a retired one."""
    vsixes = _vsix_files()
    if not vsixes:
        pytest.skip("no .vsix committed; nothing to check")

    pkg = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    expected_id = pkg["name"]
    expected_publisher = pkg["publisher"]
    expected_version = pkg["version"]

    for vsix in vsixes:
        got_id, got_publisher, got_version = _manifest_identity(vsix)
        assert got_id == expected_id, (
            f"{vsix.name} declares Id={got_id!r} but package.json says {expected_id!r}. It would "
            f"install as {got_publisher}.{got_id}, not {expected_publisher}.{expected_id}."
        )
        assert got_publisher == expected_publisher, (
            f"{vsix.name} declares Publisher={got_publisher!r} but package.json says "
            f"{expected_publisher!r}. Publishing it would attribute the extension to the wrong account."
        )
        assert got_version == expected_version, (
            f"{vsix.name} declares Version={got_version!r}, package.json says {expected_version!r}"
        )


def test_no_committed_vsix_carries_the_retired_product_name():
    """CLAUDE.md: Citadel is retired everywhere outside historical evidence. A shipped artifact is not
    historical evidence."""
    for vsix in _vsix_files():
        got_id, got_publisher, _ = _manifest_identity(vsix)
        combined = f"{got_id} {got_publisher}".lower()
        for retired in ("citadel", "lunarian"):
            assert retired not in combined, (
                f"{vsix.name} identity is {got_publisher}.{got_id}, which still carries {retired!r}. "
                f"Rebuild with: npx @vscode/vsce package"
            )


def test_the_shipped_vsix_includes_the_licence():
    """AGPL-3.0-or-later. The stale build shipped no LICENSE at all, which for a copyleft project is a
    conveyance problem, not a tidiness one."""
    vsixes = _vsix_files()
    if not vsixes:
        pytest.skip("no .vsix committed")
    for vsix in vsixes:
        with zipfile.ZipFile(vsix) as archive:
            names = [n.lower() for n in archive.namelist()]
        assert any("license" in n for n in names), (
            f"{vsix.name} ships no LICENSE, on an AGPL project. Contents: {names}"
        )


def test_the_extension_declares_the_licence_package_json_claims():
    pkg = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    assert pkg.get("license", "").startswith("AGPL-3.0"), (
        f"extension package.json declares license={pkg.get('license')!r}; the project is "
        f"AGPL-3.0-or-later"
    )


def test_package_json_identity_is_rename_clean():
    """Not conditional on a local artifact, and that is the point.

    The `.vsix` is gitignored, so every test above SKIPS on a clean checkout — they guard a developer's
    local build, not CI. `package.json` is the tracked file, and it is what `vsce package` / `vsce
    publish` derive the published identity from, so this is the assertion that actually protects the
    Marketplace listing.
    """
    pkg = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    for field in ("name", "publisher", "displayName", "description"):
        value = str(pkg.get(field, "")).lower()
        for retired in ("citadel", "lunarian"):
            assert retired not in value, (
                f"extension package.json {field}={pkg.get(field)!r} still carries {retired!r}; "
                f"vsce would publish under that identity"
            )
    assert pkg["name"] == "determinex", f"expected name 'determinex', got {pkg['name']!r}"
    assert pkg["publisher"] == "darthceltic", (
        f"expected publisher 'darthceltic' (the OSS account), got {pkg['publisher']!r}"
    )
