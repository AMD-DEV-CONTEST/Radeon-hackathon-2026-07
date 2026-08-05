"""Addon reachability lock -- ADDON_REACHABILITY_LOCK_001.

Ryan, live, 2026-07-23, after this exact bug pattern surfaced for the
FIFTH time across separate audit rounds: "im tired of issues that keep
surfacing... go through and find all instances of those patterns from
the backend... the corpus should theoretically be able to see all of
this, or it should have if you have built it and wired it right."

The pattern, every time: a real, backend-wired, often lock-verified addon
panel (Idea Lab; FlywheelFeed/PrivacyCockpit/ArtifactBrowser; Learning
Studio/Repo Clinic/Maintenance Bay/Product Surfaces; Mission/Roadmap/
Flywheel/Runtime/Merge) gets registered in `addonItems` and the command
palette, and NOTHING ELSE -- reachable only via Ctrl+K or the addon-dock's
own AddonSwitcher dropdown, which itself only renders once some OTHER
addon is already open. A normal user clicking around the UI has no path
to it at all.

A markdown lesson (however honest) doesn't stop this from recurring --
the corpus has no way to "see" a frontend UI-wiring gap unless something
actually checks for it on every change. This is that something: every
`addonItems` id must appear in `quickAttachIds`, the ONE status-bar
surface page.tsx's own comment already describes as "reachable from
every screen, not just Work/Explorer's inline grids" -- one absolute
rule, no addon-by-addon judgment calls about whether some other screen's
bespoke button counts as "discoverable enough."

Static text-based (matches this repo's existing tests/ide_frontend/*.py
convention, e.g. test_frontend_panel_command_wiring_lock.py) -- no build
step, no runtime, just page.tsx's own source.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE_TSX = _REPO_ROOT / "frontend" / "src" / "app" / "page.tsx"

# The 5 ids found buried live 2026-07-23, on top of the 4 found and fixed
# earlier the same session (learning/repoclinic/maintenancebay/surfaces).
# Pinned here so a regression shows up as "you just re-broke a NAMED past
# incident," not just an anonymous assertion failure.
# "surfaces" was removed from this set on 2026-07-28. It is NOT a regression that
# got waved through: the addon itself was deliberately retired as a duplicate by
# d0d979a280 ("remove the duplicate surfaces, and three drawer entries that opened
# nothing"), so it is absent from addonItems and from the WorkspaceAddon union.
# Pinning it as "must stay reachable" was asserting that a deleted feature still
# had a button.
#
# It did still have one. That commit missed the WORK COCKPIT's "Attach What You
# Need" grid, which kept a "Product Surfaces" button wired to the dead id --
# compiling cleanly because the grid's tuples inferred as plain `string` and the
# launch call cast with `as WorkspaceAddon`. Fixed at the source instead of here:
# that array now carries `satisfies [string, WorkspaceAddon, LucideIcon, string][]`
# and the cast is gone, so a retired id is a COMPILE error rather than something a
# regex test has to notice. Verified by re-adding the id and watching tsc reject it.
_PREVIOUSLY_BURIED_IDS = frozenset(
    {
        "learning",
        "repoclinic",
        "maintenancebay",
        "flywheel",
        "execution",
        "mission",
        "roadmap",
        "merge",
        "review",
    }
)


def _extract_bracketed_ids(src: str, start_marker: str) -> set[str]:
    """Grab every `"id-like-string"` between `start_marker` and the next
    top-level `];` -- good enough for this file's own consistent
    formatting (one array literal, one id per line or per tuple)."""
    start = src.index(start_marker)
    end = src.index("];", start)
    body = src[start + len(start_marker) : end]
    return set(re.findall(r'"([a-z][a-z0-9-]*)"', body))


def _addon_ids() -> set[str]:
    src = PAGE_TSX.read_text(encoding="utf-8")
    start = src.index("const addonItems: AddonItem[] = [")
    end = src.index("const selectedAddon = addonItems.find", start)
    body = src[start:end]
    return set(re.findall(r'id:\s*"([a-z][a-z0-9-]*)"', body))


def _quick_attach_ids() -> set[str]:
    src = PAGE_TSX.read_text(encoding="utf-8")
    return _extract_bracketed_ids(src, "const quickAttachIds: WorkspaceAddon[] = [")


def test_page_tsx_exists():
    assert PAGE_TSX.is_file()


def test_every_addon_is_in_quick_attach():
    """The one absolute rule: no addon may be registered without also
    being in quickAttachIds. A new addon that fails this is the same
    live incident happening a sixth time."""
    addons = _addon_ids()
    reachable = _quick_attach_ids()
    unreachable = addons - reachable
    assert not unreachable, (
        f"{sorted(unreachable)} are registered in addonItems but missing from "
        "quickAttachIds -- reachable only via the command palette (Ctrl+K) or "
        "the addon-dock's AddonSwitcher dropdown (itself gated behind another "
        "addon already being open). Add them to quickAttachIds in page.tsx. "
        "See this file's module docstring for why this keeps happening."
    )


def test_previously_buried_ids_stay_fixed():
    """Named regression guard for the exact 10 ids found buried across the
    two 2026-07-23 audit rounds -- if this ever fails, don't just re-add
    the id and move on; something about how new addons get wired keeps
    reintroducing this, and that process is the real bug."""
    reachable = _quick_attach_ids()
    missing = _PREVIOUSLY_BURIED_IDS - reachable
    assert not missing, f"previously-fixed buried addons regressed: {sorted(missing)}"


def test_quick_attach_ids_reference_real_addons():
    """The inverse check: quickAttachIds should not silently accumulate a
    typo'd or removed id that no longer resolves to a real addonItems
    entry (quickAttachItems' own .filter(Boolean) would hide that from
    ever surfacing at runtime -- a dead entry unnoticed forever)."""
    addons = _addon_ids()
    reachable = _quick_attach_ids()
    dangling = reachable - addons
    assert not dangling, f"quickAttachIds references non-existent addon ids: {sorted(dangling)}"
