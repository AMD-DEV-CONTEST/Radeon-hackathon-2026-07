"""What may leave this repo, and what may not.

`corpus/` was on `publish_mirror.NEVER` — never published at all. That was wrong for the product:
the corpus IS Determinex, because the Native Reimplementation Loop feeds real source and a real
oracle to a model, and a public repo without it ships a hollow thing. So the knowledge layer now
publishes. What must never travel with it:

  VENDORED UPSTREAM SOURCE   ~150,000 files of other people's code. Redistribution obliges us to
                             carry each project's copyright notice and license, and 59 of them
                             still have none. `determinex corpus fetch` rebuilds any tree from its
                             own upstream at the pinned commit instead.
  BULK EVIDENCE              519 eval_report files are 554 MB on their own; a git repo keeps every
                             revision forever. `eval_index.json` carries `eval_report_sha256`, so
                             the repo proves integrity and the dataset carries the artifact.

The subtle one is `per_tool_overrides/`. It reads like a directory of our own recipes and it is
142,750 files, of which roughly 420 are ours — our `compile.sh` sits *inside* a complete upstream
checkout. A blocklist would leak every upstream file nobody thought to name, so the filter is an
ALLOWLIST by basename and these tests pin that.

Measured before/after: 158,788 tracked corpus files, 9.73 GiB pack -> 1,709 files, 69.1 MB.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import publish_mirror as PM  # noqa: E402

#: Extensions that indicate compiled-language source. If one of these appears in the published set
#: from a vendored tree, upstream code is leaking.
UPSTREAM_SOURCE_EXTS = (".rs", ".c", ".h", ".cpp", ".hpp", ".cc", ".go", ".java", ".rb", ".php")


@pytest.fixture(scope="module")
def corpus_paths() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "corpus"], cwd=REPO_ROOT, capture_output=True, timeout=900
    )
    paths = [p for p in out.stdout.decode("utf-8", errors="replace").split("\0") if p]
    if not paths:
        pytest.skip("no corpus/ in this checkout")
    return paths


@pytest.fixture(scope="module")
def published(corpus_paths: list[str]) -> list[str]:
    kept, _ = PM.filter_corpus(corpus_paths)
    return kept


class TestVendoredSourceNeverLeaves:
    def test_no_file_under_a_source_tree_is_published(self, published):
        leaked = [p for p in published if "/source/" in p.replace("\\", "/")]
        assert not leaked, f"vendored upstream trees leaked: {leaked[:5]}"

    def test_per_tool_overrides_publishes_only_our_recipe_filenames(self, published):
        """The allowlist is the whole defence: 142,750 files there, ~420 of them ours."""
        offenders = [
            p
            for p in published
            if "/per_tool_overrides/" in p.replace("\\", "/")
            and Path(p).name not in PM.CORPUS_OVERRIDE_KEEP
        ]
        assert not offenders, f"non-recipe files published from an override tree: {offenders[:5]}"

    def test_no_compiled_language_source_is_published_from_a_vendored_tree(self, published):
        """A backstop that does not depend on the path rules being right.

        Our own Python generators (scaffold_generator.py, conftest_template.py) are legitimately
        published, so `.py` is excluded here; the check targets the languages the vendored CLI
        tools are written in.
        """
        leaked = [p for p in published if p.lower().endswith(UPSTREAM_SOURCE_EXTS)]
        assert not leaked, f"upstream-source-shaped files published: {leaked[:8]}"

    def test_the_filter_is_an_allowlist_not_a_blocklist(self):
        source = (REPO_ROOT / "scripts" / "publish_mirror.py").read_text(encoding="utf-8")
        assert "CORPUS_OVERRIDE_KEEP" in source
        assert "not in CORPUS_OVERRIDE_KEEP" in source, (
            "override filtering must allowlist our filenames; a blocklist leaks every upstream "
            "file nobody thought to name"
        )


class TestBulkEvidenceStaysOutOfGit:
    @pytest.mark.parametrize("marker", [".bak", ".tar.gz"])
    def test_archives_and_backups_are_not_published(self, published, marker):
        leaked = [p for p in published if p.endswith(marker)]
        assert not leaked, f"{marker} artifacts published: {leaked[:5]}"

    def test_eval_reports_are_not_published_under_any_of_their_names(self, published):
        """Matching only `eval_report.json` left eval_report_tui_v1.json and friends behind."""
        leaked = [p for p in published if Path(p).name.startswith("eval_report")]
        assert not leaked, f"eval report artifacts published: {leaked[:5]}"

    def test_the_training_corpus_is_not_published(self, published):
        leaked = [p for p in published if "/training_corpus/" in p.replace("\\", "/")]
        assert not leaked, f"training corpus published: {leaked[:5]}"

    def test_integrity_is_still_provable_without_the_artifacts(self):
        """Withholding the reports is only acceptable because their hashes ship."""
        import json

        index = REPO_ROOT / "corpus" / "programbench" / "eval_index.json"
        if not index.is_file():
            pytest.skip("no eval_index.json")
        raw = json.loads(index.read_text(encoding="utf-8", errors="replace"))
        rows = raw if isinstance(raw, list) else (raw.get("rows") or list(raw.values()))
        hashed = [r for r in rows if isinstance(r, dict) and r.get("eval_report_sha256")]
        assert hashed, (
            "no row carries eval_report_sha256, so a withheld report could not be verified "
            "against the dataset copy"
        )


class TestTheKnowledgeLayerActuallyShips:
    """The inverse failure: filtering so hard that the published corpus is useless."""

    @pytest.mark.parametrize(
        "required",
        [
            "corpus/programbench/canonical_tasks.json",  # the pins `corpus fetch` needs
            "corpus/programbench/eval_index.json",  # the board's rows + report hashes
            "corpus/programbench/build_knowledge.json",  # the learned SYMPTOM->FIX knowledge
            "corpus/programbench/README.md",  # the status board
        ],
    )
    def test_load_bearing_knowledge_is_published(self, published, required):
        assert required in published, f"{required} was filtered out of the public corpus"

    def test_the_build_recipes_ship(self, published):
        recipes = [p for p in published if Path(p).name == "compile.sh"]
        assert len(recipes) >= 200, f"only {len(recipes)} compile.sh recipes published"

    def test_the_published_corpus_is_a_sane_size_for_git(self, published):
        import os

        total = sum(os.path.getsize(REPO_ROOT / p) for p in published if (REPO_ROOT / p).exists())
        mb = total / 1e6
        assert mb < 150, (
            f"published corpus is {mb:.0f} MB. GitHub soft-limits a repo at 1 GB and every "
            "revision is kept forever; bulk evidence belongs in the dataset."
        )
        assert mb > 5, f"published corpus is only {mb:.1f} MB — the knowledge layer is missing"

    def test_third_party_notices_accompany_the_corpus(self):
        notices = REPO_ROOT / "corpus" / "THIRD_PARTY_NOTICES.md"
        assert notices.is_file(), (
            "corpus/THIRD_PARTY_NOTICES.md must exist: it is the attribution that makes "
            "redistributing anything under corpus/ legitimate"
        )
        text = notices.read_text(encoding="utf-8", errors="replace")
        assert "AGPL-3.0-or-later" in text, "the notice must state Determinex's own license"
        assert "Withheld from redistribution" in text, (
            "the notice must disclose what was withheld, or it overstates what ships"
        )


def test_corpus_is_no_longer_on_the_never_list():
    """The change that started all this. If someone re-adds it, the product ships hollow."""
    assert "corpus" not in PM.NEVER, (
        "corpus is back on the never-publish list; the Native Reimplementation Loop needs the "
        "knowledge layer to be public"
    )


def test_genuinely_secret_paths_are_still_never_published():
    """Relaxing corpus must not have relaxed anything else."""
    for must_stay in (".env", ".env.local", ".git", "logs", "sessions", ".venv"):
        assert must_stay in PM.NEVER, f"{must_stay} fell off the never-publish list"
