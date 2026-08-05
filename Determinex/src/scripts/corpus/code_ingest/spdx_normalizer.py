"""
SPDX license identifier normalizer.

Converts raw license strings found in LICENSE files, headers, and package
metadata into canonical SPDX identifiers (e.g. "MIT License" → "MIT").

Reference: https://spdx.org/licenses/
"""

from __future__ import annotations

import re

# Green: ingest allowed without review
GREEN_LICENSES: frozenset[str] = frozenset(
    {
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "Unlicense",
        "CC0-1.0",
        "0BSD",
        "BlueOak-1.0.0",
        "BSD-2-Clause-Patent",
    }
)

# Yellow: ingest allowed but requires metadata review before model training
YELLOW_LICENSES: frozenset[str] = frozenset(
    {
        "MPL-2.0",
        "EPL-2.0",
        "EPL-1.0",
        "CC-BY-4.0",
        "CC-BY-3.0",
        "CC-BY-SA-4.0",
        "EUPL-1.2",
    }
)

# Red: do not ingest into training corpus without explicit legal review
# LGPL is included: even library copyleft creates obligations for training data usage.
RED_LICENSES: frozenset[str] = frozenset(
    {
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "AGPL-3.0-only",
        "AGPL-3.0-or-later",
        "LGPL-2.0-only",
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        "SSPL-1.0",
        "Commons-Clause",
        "BUSL-1.1",
    }
)

# Canonical normalizations: raw text fragment → SPDX identifier
_NORMALIZATIONS: list[tuple[re.Pattern, str]] = [
    # MIT
    (re.compile(r"\bmit\b", re.I), "MIT"),
    # Apache
    (re.compile(r"apache.{0,10}2\.0|apache.{0,10}license.{0,10}2", re.I), "Apache-2.0"),
    (re.compile(r"apache.{0,10}1\.[01]", re.I), "Apache-1.1"),
    # BSD
    (re.compile(r"bsd.{0,5}3.{0,10}clause|new bsd|modified bsd", re.I), "BSD-3-Clause"),
    (re.compile(r"bsd.{0,5}2.{0,10}clause|simplified bsd|freebsd", re.I), "BSD-2-Clause"),
    # ISC
    (re.compile(r"\bisc\b", re.I), "ISC"),
    # Unlicense
    (re.compile(r"\bunlicense\b", re.I), "Unlicense"),
    # CC0
    (re.compile(r"cc0|creative.commons.zero|public.domain", re.I), "CC0-1.0"),
    # AGPL and LGPL are matched BEFORE plain GPL, and the GPL patterns below
    # are tempered so they cannot span the words "affero"/"lesser".
    #
    # Both, deliberately. Ordering alone is one careless reorder away from a
    # silent regression, and the tempered pattern alone would still leave the
    # more-specific rule second. Found live 2026-07-28: `gnu.{0,20}general`
    # happily spans " Affero " (8 chars), so the repo's own AGPL-3.0-or-later
    # LICENSE was classified GPL-3.0-only -- a RED-bucket id -- which blocked
    # security_gate.py on Determinex's own correctly-licensed LICENSE file.
    # " Lesser " is the same length, so every LGPL text was misread too.
    # AGPL
    (re.compile(r"affero.{0,20}general.{0,20}public|agpl.{0,5}v?3", re.I), "AGPL-3.0-only"),
    # LGPL — handle both "v2.1" and "version 2.1" forms; check 2.1 before 2.0
    (
        re.compile(
            r"(?:lesser.{0,20}general.{0,20}public.{0,20}licen[cs]e.{0,15}(?:v(?:ersion)?\.?\s*)?3)|(?:lgpl.{0,5}v?3)|lgplv3|lgpl-3",
            re.I,
        ),
        "LGPL-3.0-only",
    ),
    (
        re.compile(
            r"(?:lesser.{0,20}general.{0,20}public.{0,20}licen[cs]e.{0,15}(?:v(?:ersion)?\.?\s*)?2\.1)|(?:lgpl.{0,5}v?2\.1)|lgpl-2\.1",
            re.I,
        ),
        "LGPL-2.1-only",
    ),
    (
        re.compile(
            r"(?:lesser.{0,20}general.{0,20}public.{0,20}licen[cs]e.{0,15}(?:v(?:ersion)?\.?\s*)?2(?!\.1))|(?:lgpl.{0,5}v?2(?!\.1))|lgplv2(?!\.1)|lgpl-2(?!\.)",
            re.I,
        ),
        "LGPL-2.0-only",
    ),
    # GPL — handle both "v2"/"v3" and "version 2"/"version 3" forms
    (
        re.compile(
            r"(?:gnu(?:(?!affero|lesser).){0,20}general.{0,20}public.{0,20}licen[cs]e.{0,15}(?:v(?:ersion)?\.?\s*)?3)|(?<![a-z])(?:gpl.{0,5}v?3|gplv3|gpl-3)",
            re.I,
        ),
        "GPL-3.0-only",
    ),
    (
        re.compile(
            r"(?:gnu(?:(?!affero|lesser).){0,20}general.{0,20}public.{0,20}licen[cs]e.{0,15}(?:v(?:ersion)?\.?\s*)?2)|(?<![a-z])(?:gpl.{0,5}v?2|gplv2|gpl-2)",
            re.I,
        ),
        "GPL-2.0-only",
    ),
    # MPL
    (re.compile(r"mozilla.{0,20}public.{0,20}license.{0,10}2|mpl.{0,5}2", re.I), "MPL-2.0"),
    # EPL
    (re.compile(r"eclipse.{0,20}public.{0,20}license.{0,10}2|epl.{0,5}2", re.I), "EPL-2.0"),
    (re.compile(r"eclipse.{0,20}public.{0,20}license.{0,10}1|epl.{0,5}1", re.I), "EPL-1.0"),
    # CC-BY
    (re.compile(r"creative.commons.{0,10}attribution.{0,10}4|cc.by.4", re.I), "CC-BY-4.0"),
    (
        re.compile(
            r"creative.commons.{0,10}attribution.{0,30}share.alike.{0,10}4|cc.by.sa.4", re.I
        ),
        "CC-BY-SA-4.0",
    ),
    # BUSL
    (re.compile(r"business.source.license|busl", re.I), "BUSL-1.1"),
    # SSPL
    (re.compile(r"server.side.public.license|sspl", re.I), "SSPL-1.0"),
]

# SPDX-License-Identifier header pattern
_SPDX_HEADER = re.compile(r"SPDX-License-Identifier:\s*([^\n\r*]+)", re.I)


def normalize(raw: str) -> str | None:
    """
    Convert a raw license string to its canonical SPDX identifier.
    Returns None if no match found.
    """
    raw = raw.strip()
    if not raw:
        return None

    # Check SPDX identifier header first (most reliable) — on original raw
    m = _SPDX_HEADER.search(raw)
    if m:
        candidate = m.group(1).strip().rstrip("*/")
        # validate it looks like an SPDX id (letters, digits, hyphens, dots)
        if re.match(r"^[\w.\-\+]+$", candidate):
            return candidate

    # Normalize whitespace so patterns work across multi-line license texts
    # (e.g. "GNU GPL\nVersion 2" becomes "GNU GPL Version 2")
    normalized = re.sub(r"[\r\n\t]+", " ", raw)
    normalized = re.sub(r" {2,}", " ", normalized)

    # Try normalizations
    for pattern, spdx_id in _NORMALIZATIONS:
        if pattern.search(normalized):
            return _apply_or_later(spdx_id, normalized)

    return None


# "either version N of the License, or (at your option) any later version" is the
# FSF's standard grant, and it is the difference between `-only` and `-or-later`
# -- two distinct SPDX identifiers with different obligations. Nothing detected it,
# so every GNU-family license normalised to `-only` even though the `-or-later`
# ids are in the allowed set above. Determinex's own LICENSE carries this grant.
_OR_LATER = re.compile(
    r"(?:any\s+later\s+version)|(?:or\s+\(?at\s+your\s+option\)?\s+any\s+later)"
    r"|(?:either\s+version\s+[\d.]+\s+of\s+the\s+licen[cs]e,?\s+or)",
    re.I,
)

# Only the GNU family expresses the "or later" choice this way.
_OR_LATER_ELIGIBLE = frozenset(
    {
        "GPL-2.0-only",
        "GPL-3.0-only",
        "AGPL-3.0-only",
        "LGPL-2.0-only",
        "LGPL-2.1-only",
        "LGPL-3.0-only",
    }
)


def _apply_or_later(spdx_id: str, normalized: str) -> str:
    """Upgrade a `-only` GNU identifier to `-or-later` when the text grants it."""
    if spdx_id in _OR_LATER_ELIGIBLE and _OR_LATER.search(normalized):
        candidate = spdx_id.replace("-only", "-or-later")
        # Never emit an identifier no bucket knows: bucket() would return
        # "unknown", which is a WEAKER signal than the correct `-only` answer.
        # LGPL-2.0-or-later is exactly such a case here -- it appears in no
        # bucket, so that upgrade is declined rather than silently downgrading
        # a red-bucket license to unknown.
        if candidate in (GREEN_LICENSES | YELLOW_LICENSES | RED_LICENSES):
            return candidate
    return spdx_id


def bucket(spdx_id: str | None) -> str:
    """
    Return "green", "yellow", "red", or "unknown" for a given SPDX identifier.
    """
    if spdx_id is None:
        return "unknown"
    if spdx_id in GREEN_LICENSES:
        return "green"
    if spdx_id in YELLOW_LICENSES:
        return "yellow"
    if spdx_id in RED_LICENSES:
        return "red"
    return "unknown"


def ingest_allowed(spdx_id: str | None) -> bool:
    """True only for green-bucket licenses."""
    return bucket(spdx_id) == "green"
