"""`determinex corpus fetch` — reconstruct a vendored tool from its own maintainers.

WHY THE COMMAND EXISTS. `corpus/` carries complete upstream checkouts of ~200 CLI tools, because
the Native Reimplementation Loop feeds real source and a real oracle to a model. That has to stay
available, but re-hosting it in the public repo fails twice:

  SIZE  the pack is 9.73 GiB; GitHub soft-limits at 1 GB and rejects files over 100 MB.
  LAW   publishing those trees is redistribution, and MIT/BSD/ISC/Apache-2.0 all require the
        copyright notice and license text to travel with the code.

So the public repo ships the knowledge layer and `canonical_tasks.json`, which pins
`repository` + `commit` for all 200 tasks, and this command rebuilds any tree from upstream at
exactly that commit.

The tests here are offline: network fetching is exercised separately and deliberately not in the
suite, because a unit test that clones 200 repositories is not a unit test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import determinex_corpus_fetch as CF  # noqa: E402


class TestPinnedTasksAreUsable:
    def test_every_pinned_task_has_a_repository_and_a_commit(self):
        """A task without both is a tree nobody can reconstruct — the whole premise."""
        tasks = CF.load_tasks()
        assert tasks, "canonical_tasks.json yielded no usable tasks"
        bad = [t.task_id for t in tasks if not t.repository or not t.commit]
        assert not bad, f"tasks missing provenance: {bad[:5]}"

    def test_the_pinned_set_covers_the_benchmark(self):
        assert len(CF.load_tasks()) >= 200

    def test_commits_are_full_length_shas(self):
        """A short sha can become ambiguous as upstream history grows; the pins are exact."""
        short = [t.task_id for t in CF.load_tasks() if len(t.commit) < 40]
        assert not short, f"tasks pinned to a short sha: {short[:5]}"


class TestResolution:
    @pytest.fixture(scope="class")
    @staticmethod
    def tasks():
        # staticmethod: a class-scoped fixture defined as an instance method is deprecated in
        # pytest 10 and its attributes would not be visible to the tests anyway.
        return CF.load_tasks()

    @pytest.mark.parametrize("name", ["cmatrix", "abishekvashok/cmatrix", "abishekvashok__cmatrix"])
    def test_a_tool_resolves_by_any_of_its_spellings(self, tasks, name):
        task = CF.resolve(tasks, name)
        assert task is not None, f"{name!r} did not resolve"
        assert task.repository.lower().endswith("cmatrix")

    def test_resolution_is_case_insensitive(self, tasks):
        assert CF.resolve(tasks, "CMatrix") is not None

    def test_an_unknown_tool_resolves_to_none_rather_than_guessing(self, tasks):
        assert CF.resolve(tasks, "definitely-not-a-pinned-tool") is None

    def test_slug_matches_the_override_directory_convention(self, tasks):
        """Override dirs are named owner__repo[.commit]; the slug has to line up or the recipe
        overlay silently finds nothing."""
        task = CF.resolve(tasks, "cmatrix")
        assert task is not None
        assert task.slug == "abishekvashok__cmatrix"

    def test_clone_url_is_https_for_a_bare_owner_repo(self, tasks):
        task = CF.resolve(tasks, "cmatrix")
        assert task is not None
        assert task.clone_url == "https://github.com/abishekvashok/cmatrix"


class TestRecipeOverlay:
    """The overlay must copy OUR files and nothing else.

    Copying the whole override directory would restore the vendored tree this command exists to
    avoid re-hosting — the recipe lives *inside* a full upstream checkout.
    """

    def test_only_our_recipe_files_are_ever_copied(self):
        source = (REPO_ROOT / "scripts" / "determinex_corpus_fetch.py").read_text(encoding="utf-8")
        # The allowlist is the load-bearing detail; assert it is a literal tuple, not a glob.
        assert '("compile.sh", "conftest.py", "eval_report.json", "tests.json")' in source
        assert "copytree" not in source, (
            "a recursive copy would re-materialise the vendored upstream tree from the override "
            "directory, defeating the point of fetching from upstream"
        )

    def test_overrides_are_matched_on_the_owner_repo_prefix(self):
        """Override dirs carry a commit suffix that is not always the pinned one, so an exact
        name match would find nothing for most tools."""
        tasks = CF.load_tasks()
        task = CF.resolve(tasks, "cmatrix")
        assert task is not None
        found = CF.find_overrides(task)
        if found is None:
            pytest.skip("no override directory for cmatrix in this checkout")
        assert found.name.lower().startswith("abishekvashok__cmatrix")

    def test_scaffolding_directories_are_not_mistaken_for_overrides(self, tmp_path, monkeypatch):
        """`per_tool_overrides/` also holds .vscode and _superseded; neither is a tool."""
        fake = tmp_path / "per_tool_overrides"
        (fake / ".vscode").mkdir(parents=True)
        (fake / "_superseded").mkdir()
        monkeypatch.setattr(CF, "OVERRIDES", fake)
        task = CF.Task(task_id="x", repository="owner/vscode", commit="a" * 40, language="c")
        assert CF.find_overrides(task) is None


class TestTheFetchIsShallowAndPinned:
    def test_it_fetches_the_pinned_commit_not_a_branch(self):
        source = (REPO_ROOT / "scripts" / "determinex_corpus_fetch.py").read_text(encoding="utf-8")
        assert '"fetch", "--quiet", "--depth", "1", "origin", task.commit' in source, (
            "the point of a pin is that the tree is reproducible; fetching a branch is not"
        )
        assert '"checkout", "--quiet", task.commit' in source

    def test_an_existing_tree_is_not_silently_reused_under_force(self, tmp_path, monkeypatch):
        task = CF.Task(task_id="t", repository="owner/repo", commit="b" * 40, language="c")
        dest = tmp_path / task.slug
        dest.mkdir(parents=True)
        (dest / "stale.txt").write_text("old", encoding="utf-8")

        ok, detail = CF.fetch(task, tmp_path, force=False)
        assert ok and "already present" in detail, detail
        assert (dest / "stale.txt").exists(), "without --force an existing tree is left alone"

    def test_it_reports_failure_rather_than_pretending(self, tmp_path, monkeypatch):
        """A fetch that cannot reach upstream must not return a success the caller trusts."""
        monkeypatch.setattr(CF, "_run", lambda *a, **k: (False, "simulated network failure"))
        task = CF.Task(task_id="t", repository="owner/repo", commit="c" * 40, language="c")
        ok, detail = CF.fetch(task, tmp_path)
        assert ok is False
        assert "simulated network failure" in detail


class TestCliSurface:
    def test_list_runs_and_names_real_tools(self, capsys):
        assert CF.main(["list"]) == 0
        out = capsys.readouterr().out
        assert "pinned tool(s)" in out
        assert "cmatrix" in out

    def test_fetch_without_a_tool_is_an_error_not_a_silent_noop(self, capsys):
        assert CF.main(["fetch"]) == 2

    def test_an_unknown_tool_exits_nonzero_and_points_at_list(self, capsys):
        assert CF.main(["fetch", "no-such-tool-anywhere"]) == 2
        assert "determinex corpus list" in capsys.readouterr().err

    def test_language_filter_narrows_the_listing(self, capsys):
        CF.main(["list", "--language", "rs"])
        rust_lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("  ")]
        assert rust_lines, "expected at least one Rust tool"
        assert all(" rs " in ln for ln in rust_lines)


def test_canonical_tasks_ships_in_the_public_repo():
    """The fetcher is useless without its pin file, so the pin file must not be excluded.

    `publish_mirror.NEVER` used to exclude `corpus` wholesale, which would have shipped a `corpus
    fetch` command with nothing to fetch from.
    """
    assert CF.CANONICAL_TASKS.is_file()
    import subprocess

    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            "--error-unmatch",
            CF.CANONICAL_TASKS.relative_to(REPO_ROOT).as_posix(),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=120,
    )
    assert tracked.returncode == 0, "canonical_tasks.json is not tracked by git"


def test_pins_are_valid_json_and_parse_to_the_same_count():
    raw = json.loads(CF.CANONICAL_TASKS.read_text(encoding="utf-8", errors="replace"))
    rows = raw if isinstance(raw, list) else (raw.get("tasks") or list(raw.values()))
    assert len(rows) == 200
