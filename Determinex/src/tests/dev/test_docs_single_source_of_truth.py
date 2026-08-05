"""One doc, one path.

WHY THIS EXISTS
---------------
The 2026-05-29 docs reorg moved documents into typed folders (`docs/audits/`,
`docs/architecture/`, `docs/proof/`, `docs/programs/…`) but left copies behind at
their old paths. Four basenames ended up existing twice, and every one of them
caused a real problem, because a stale duplicate of a GENERATED document reads as
current while reporting numbers that are not:

* `PARALLEL_EXECUTION_LAYER_AUDIT.md` -- the security lock test pointed at the
  copy nobody regenerated, so it stayed green while the doc humans read drifted.
  Three sources disagreed on the count of unclassified execution sites.
* `PROGRAMBENCH_ARTIFACT_IMPORT_OPERATOR_GUIDE.md` -- the copy the generator
  writes to had BLANK provenance image names where the orphan had real ones.
* `EVIDENCE_INDEX.md` -- 76 KB orphan beside the 1 MB real index.
* `VERIFIER_COVERAGE_MATRIX.md` -- byte-identical, so harmless until the day one
  of them was regenerated.

Which path is canonical is NOT a naming convention -- it is whatever the
generator writes and the tests read, and it differed per document (three of the
four were canonical at `docs/` root, one under `docs/audits/`). So this test does
not enforce a location. It enforces that there is only ONE.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Basenames that are legitimately per-directory rather than duplicated.
# Adding to this list is a deliberate decision: it says "two files with this name
# are two different documents", not "we have not cleaned this up yet".
_ALLOWED_REPEATS = {"README.md"}


def test_no_markdown_basename_exists_at_two_paths():
    by_name: dict[str, list[str]] = defaultdict(list)
    for p in (_REPO_ROOT / "docs").rglob("*.md"):
        if p.name in _ALLOWED_REPEATS:
            continue
        by_name[p.name].append(p.relative_to(_REPO_ROOT).as_posix())

    dupes = {name: sorted(paths) for name, paths in by_name.items() if len(paths) > 1}
    assert not dupes, (
        "these documents exist at more than one path; delete the orphan and point "
        "every reference at the one the generator writes:\n"
        + "\n".join(f"  {n}: {p}" for n, p in sorted(dupes.items()))
    )
