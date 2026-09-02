from swe_experiments.context import build_context
from track2_context_extract import issue_mentions, override_expansion


def test_repo_graph_reports_missing_native_command_instead_of_claiming_success():
    context = build_context("C2", lambda command, timeout: {"output": "", "exit_code": 0}, "fix parser")
    assert context.available is False
    assert "TRACK2_REPOGRAPH_COMMAND" in context.text


def test_git_history_provider_uses_runner_output():
    def runner(command, timeout):
        assert command.startswith("git log")
        return {"output": "abc123 fix parser\n", "exit_code": 0}

    context = build_context("C4", runner, "fix parser")
    assert context.available is True
    assert "abc123" in context.text


def test_loop_guard_provider_is_always_available():
    context = build_context("C5", lambda command, timeout: {}, "fix parser")
    assert context.available is True
    assert "repeating" in context.text


def test_aider_repo_map_mentions_are_issue_aware(tmp_path):
    parser = tmp_path / "src" / "special_parser.py"
    parser.parent.mkdir()
    parser.write_text("def parse_widget():\n    pass\n")
    other = tmp_path / "src" / "unrelated.py"
    other.write_text("def helper():\n    pass\n")

    filenames, identifiers = issue_mentions(
        tmp_path,
        [str(parser), str(other)],
        "Fix parse_widget in special_parser.py without changing helper.",
    )

    assert "src/special_parser.py" in filenames
    assert "parse_widget" in identifiers


def test_override_expansion_surfaces_sibling_implementations(tmp_path):
    common = tmp_path / "common.py"
    sparse = tmp_path / "sparse.py"
    common.write_text("class Matrix:\n    def row_join(self, other):\n        pass\n")
    sparse.write_text("class SparseMatrix:\n    def row_join(self, other):\n        pass\n")

    result = override_expansion(
        tmp_path,
        [str(common), str(sparse)],
        "Matrix hstack changed behavior",
    )

    assert "common.py:2" in result
    assert "sparse.py:2" in result
    assert "every override" in result
