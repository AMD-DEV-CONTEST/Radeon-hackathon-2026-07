"""Does the Proof Center show the scores the models actually earned?

WHY THIS EXISTS
---------------
Found 2026-07-29. `frontend/src/app/proof-center/page.tsx` hardcoded a model benchmark
table that credited the SHIPPED models with their PREDECESSORS' scores:

    displayed                        artifact on disk
    C1 Engineer v11-dsl  89% 40/45   57/70 = 81%   (40/45 belongs to v10-dsl)
    C3 Observer  v6-dsl  82% 37/45   53/70 = 76%   (37/45 belongs to v5-dsl)
    C7 Sentinel  v5-dsl  87% 39/45   NO ARTIFACT   (39/45 belongs to v3)
    System Combined      86% 116/135 a sum of the three above

CLAUDE.md carries exactly this correction, dated 2026-07-28: "README, WHITE_PAPER and
ARCHITECTURE had been crediting the shipped v11/v6 models with v10/v5's scores...
Sentinel v5-dsl genuinely has no eval artifact." Three prose documents were corrected.
The product page -- the one surface whose entire purpose is showing verified proof -- was
not, and nothing existed to notice.

So this test does not compare the page against CLAUDE.md. Prose is what drifted. It
compares the page against `logs/eval_results/*.json`, the artifacts the eval harness
wrote, because those are the only thing that cannot be edited into agreement.

The 45-probe and 70-probe sets are NOT interchangeable -- different denominators,
different probe content -- so a score from one may not be shown against, or summed with,
the other. That conflation is what produced the original row.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PAGE = REPO_ROOT / "frontend" / "src" / "app" / "proof-center" / "page.tsx"
EVAL_DIR = REPO_ROOT / "logs" / "eval_results"

# The models the product actually ships, per CLAUDE.md's model table.
SHIPPED = {
    "C1 Engineer v11-dsl": "engineer-v11-dsl",
    "C3 Observer v6-dsl": "observer-v6-dsl",
    "C7 Sentinel v5-dsl": "sentinel-v5",
}


def _newest_artifact(slug: str) -> dict | None:
    """The latest eval artifact for a model slug, or None when none was ever produced."""
    if not EVAL_DIR.is_dir():
        return None
    # Artifacts predate the Citadel->Determinex rename and keep their original filenames;
    # they are historical evidence and are deliberately not renamed.
    hits = sorted(EVAL_DIR.glob(f"eval_*{slug}*.json"))
    if not hits:
        return None
    try:
        return json.loads(hits[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _page_rows() -> list[dict[str, str]]:
    """Parse the MODEL_ROWS literal out of the page.

    Deliberately textual: the point is to check what SHIPS in the file, so importing or
    transpiling it would only move the question. Each row is captured as a field->value
    map of raw source text.
    """
    src = PAGE.read_text(encoding="utf-8")
    start = src.index("const MODEL_ROWS")
    end = src.index("\n];", start)
    body = src[start:end]
    rows = []
    for chunk in re.findall(r"\{(.*?)\}", body, re.S):
        fields = dict(re.findall(r'(\w+)\s*:\s*("(?:[^"\\]|\\.)*"|null|[-\d.]+)', chunk))
        if "model" in fields:
            rows.append({k: v.strip('"') for k, v in fields.items()})
    return rows


@pytest.mark.skipif(not PAGE.is_file(), reason="proof-center page not present")
def test_every_shipped_model_row_matches_its_own_eval_artifact():
    """THE regression. Each shipped model's displayed score must come from that model's
    artifact -- not from the predecessor whose numbers used to sit in this row."""
    rows = {r["model"]: r for r in _page_rows()}
    assert rows, "could not parse MODEL_ROWS out of the page"

    checked = 0
    for label, slug in SHIPPED.items():
        row = rows.get(label)
        assert row is not None, f"{label} row missing from the Proof Center table"
        artifact = _newest_artifact(slug)

        if artifact is None:
            # No artifact: the row must say so, not borrow a number.
            assert row.get("score") == "null", (
                f"{label} has NO eval artifact on disk but the page shows "
                f"score={row.get('score')} ({row.get('raw')}). An unmeasured model with a "
                f"score is the overclaim this page exists to refute."
            )
            checked += 1
            continue

        passed = artifact["total_passed"]
        total = artifact["total_probes"]
        expected_pct = round(passed / total * 100)
        assert row["score"] != "null", (
            f"{label} has an artifact ({passed}/{total}) but the page shows no score"
        )
        assert int(float(row["score"])) == expected_pct, (
            f"{label}: page shows {row['score']}%, artifact says {expected_pct}% ({passed}/{total})"
        )
        assert row["raw"] == f"{passed}/{total}", (
            f"{label}: page shows raw={row['raw']!r}, artifact says {passed}/{total}"
        )
        checked += 1

    assert checked == len(SHIPPED), "not every shipped model was checked"


@pytest.mark.skipif(not PAGE.is_file(), reason="proof-center page not present")
def test_no_row_shows_a_45_probe_score_for_a_shipped_model():
    """The specific conflation that caused this. The shipped models were evaluated on the
    70-probe set; the 45-probe figures belong to v10/v5/v3. A shipped row displaying /45
    means a predecessor's number has crept back in."""
    for row in _page_rows():
        if row["model"] in SHIPPED:
            assert not row.get("raw", "").endswith("/45"), (
                f"{row['model']} shows {row['raw']} -- a 45-probe figure, which belongs to "
                f"its predecessor, not to the shipped model"
            )


@pytest.mark.skipif(not PAGE.is_file(), reason="proof-center page not present")
def test_no_aggregate_row_claims_to_cover_the_whole_system():
    """With the Architect unmeasured, no figure can describe the system as a whole. The
    old row was literally labelled 'System Combined' at 86% while one of its three inputs
    had no measurement at all."""
    labels = [r["model"] for r in _page_rows()]
    assert "System Combined" not in labels, (
        "an aggregate labelled 'System Combined' implies every role was measured; "
        "Sentinel v5-dsl has no eval artifact"
    )


@pytest.mark.skipif(not EVAL_DIR.is_dir(), reason="no eval artifacts on this machine")
def test_the_predecessor_scores_really_do_belong_to_the_predecessors():
    """Guards the claim this whole file rests on: that 40/45 and 39/45 are v10's and v3's.
    If that were wrong, the 'correction' would itself be the error."""
    v10 = _newest_artifact("engineer-v10-dsl")
    if v10:
        assert (v10["total_passed"], v10["total_probes"]) == (40, 45), (
            f"expected v10-dsl to be the source of 40/45, got "
            f"{v10['total_passed']}/{v10['total_probes']}"
        )
    v3 = _newest_artifact("sentinel-v3")
    if v3:
        assert (v3["total_passed"], v3["total_probes"]) == (39, 45), (
            f"expected sentinel-v3 to be the source of 39/45, got "
            f"{v3['total_passed']}/{v3['total_probes']}"
        )
