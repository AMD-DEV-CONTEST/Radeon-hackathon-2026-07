"""The GNU family: AGPL is not GPL, LGPL is not GPL, and "or later" is a grant.

WHY THIS EXISTS
---------------
Found live 2026-07-28 by running `scripts/security/security_gate.py`: it reported
BLOCKED on license_scan, flagging Determinex's own LICENSE as `GPL-3.0-only`. The
file plainly reads "GNU **Affero** General Public License ... either version 3 of
the License, or (at your option) **any later version**" -- i.e. AGPL-3.0-or-later.

Two independent defects in `spdx_normalizer`:

1. The GPL pattern was `gnu.{0,20}general.{0,20}public...`, and `.{0,20}` spans
   " Affero " (8 characters) perfectly well -- as it does " Lesser ". The GPL rule
   sat AHEAD of the AGPL and LGPL rules in an ordered first-match-wins list, so
   every AGPL and every LGPL text in the corpus normalised to GPL-3.0-only. The
   short alternatives made it worse: `gpl-3` matches inside `lgpl-3`, and `gplv3`
   inside `lgplv3`, so even reordering alone would not have been enough.
2. Nothing detected the FSF's standard "or (at your option) any later version"
   grant, so every GNU license normalised to `-only` -- despite `-or-later` being
   a distinct SPDX identifier, with different obligations, already listed in the
   bucket tables.

These matter beyond the repo's own file: the buckets gate what may be ingested
into the training corpus, and a license read as the wrong identifier is a wrong
answer about someone else's code.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from corpus.code_ingest.spdx_normalizer import (  # noqa: E402
    GREEN_LICENSES,
    RED_LICENSES,
    YELLOW_LICENSES,
    bucket,
    normalize,
)

_GRANT = "either version 3 of the License, or (at your option) any later version"


# ── defect 1: the GPL rule swallowed AGPL and LGPL ───────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "GNU Affero General Public License version 3",
        "Licensed under the GNU Affero General Public License, Version 3",
        "AGPL-3",
        "agplv3",
    ],
)
def test_affero_is_never_read_as_plain_gpl(text):
    got = normalize(text)
    assert got is not None and got.startswith("AGPL-3.0"), (
        f"{text!r} normalised to {got!r}; the GPL rule matched across the word 'Affero' again"
    )


@pytest.mark.parametrize(
    "text",
    [
        "GNU Lesser General Public License version 3",
        "LGPL-3",
        "lgplv3",
        "This library is under the GNU Lesser General Public License, Version 3",
    ],
)
def test_lesser_is_never_read_as_plain_gpl(text):
    got = normalize(text)
    assert got is not None and got.startswith("LGPL-3.0"), (
        f"{text!r} normalised to {got!r}; 'gpl-3'/'gplv3' matched inside the 'lgpl' spelling again"
    )


def test_the_gpl_rule_itself_cannot_span_affero_or_lesser():
    """Pins the MECHANISM, not just the outcome.

    AGPL and LGPL are now also ordered ahead of GPL in the first-match-wins list,
    which would mask a regression in the pattern itself. This asserts the GPL rule
    is independently incapable of matching those texts, so the fix does not rest
    on list order alone. The commented original is what shipped, and it matched all
    three of these.
    """
    from corpus.code_ingest.spdx_normalizer import _NORMALIZATIONS

    gpl_rules = [pat for pat, sid in _NORMALIZATIONS if sid.startswith("GPL-")]
    assert gpl_rules, "no GPL rules found; the table shape changed"

    # original: r"(?:gnu.{0,20}general.{0,20}public..." -- matched every one of these
    for text in (
        "GNU Affero General Public License, version 3",
        "GNU Lesser General Public License version 3",
        "licensed lgpl-3",
        "agplv3",
    ):
        for pat in gpl_rules:
            assert not pat.search(text), (
                f"the GPL rule {pat.pattern[:60]!r} matched {text!r}; it can span "
                f"'affero'/'lesser' or the 'lgpl'/'agpl' spelling again"
            )

    assert any(p.search("GNU General Public License version 3") for p in gpl_rules), (
        "the GPL rules no longer match plain GPL text -- tempered too far"
    )


def test_plain_gpl_still_resolves_to_gpl():
    """The tempering must not break the case it was guarding."""
    assert normalize("GNU General Public License, version 3") == "GPL-3.0-only"
    assert normalize("GNU General Public License version 2") == "GPL-2.0-only"
    assert normalize("GPLv3") == "GPL-3.0-only"


# ── defect 2: the "or later" grant was invisible ─────────────────────────────


def test_the_or_later_grant_is_detected():
    assert normalize(f"GNU Affero General Public License, {_GRANT}") == "AGPL-3.0-or-later"
    assert normalize(f"GNU General Public License, {_GRANT}") == "GPL-3.0-or-later"


def test_absence_of_the_grant_stays_only():
    """`-only` and `-or-later` are different licenses. Inferring the grant from a
    text that does not contain it would be as wrong as missing it."""
    assert normalize("GNU Affero General Public License version 3") == "AGPL-3.0-only"
    assert normalize("GNU General Public License, version 3 only") == "GPL-3.0-only"


def test_the_upgrade_never_emits_an_identifier_no_bucket_knows():
    """LGPL-2.0-or-later appears in no bucket table here, so upgrading to it would
    turn a red-bucket license into bucket 'unknown' -- a weaker signal than the
    correct `-only` answer. The upgrade must decline instead."""
    got = normalize(f"GNU Lesser General Public License, version 2, {_GRANT}")
    assert got in (GREEN_LICENSES | YELLOW_LICENSES | RED_LICENSES), (
        f"{got!r} is in no bucket; bucket() would report 'unknown'"
    )
    assert bucket(got) != "unknown"


# ── the repo's own license, which is what surfaced all of this ───────────────


def test_determinex_own_license_resolves_correctly():
    raw = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8", errors="replace")
    assert normalize(raw) == "AGPL-3.0-or-later"


def test_permissive_licenses_are_unaffected():
    assert normalize("MIT License") == "MIT"
    assert bucket(normalize("MIT License")) == "green"
    assert normalize("Apache License 2.0") == "Apache-2.0"
