"""tests/test_determinex_stewardship.py

Ryan: "the place you are sending everything to, that's there will be the
overall runtime md, and then the project md, if the project doesnt have an
adequate md (or even if they do) the project automatically converts the
stewardship document from the project or in lieu of it not having one,
creates it on the initial scan run so that EVERYTHING stays synced."
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_stewardship as steward  # noqa: E402


def test_find_runtime_doc_walks_up_and_skips_workspace_own_claude_md(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# root runtime doc\n" * 30, encoding="utf-8")
    workspace = tmp_path / "projects" / "myproj"
    workspace.mkdir(parents=True)
    (workspace / "CLAUDE.md").write_text("# project's own doc\n" * 30, encoding="utf-8")

    runtime_doc = steward.find_runtime_doc(workspace)
    assert runtime_doc is not None
    assert runtime_doc == tmp_path / "CLAUDE.md"
    assert runtime_doc != workspace / "CLAUDE.md"


def test_find_runtime_doc_returns_none_when_no_ancestor_has_one(tmp_path):
    workspace = tmp_path / "isolated"
    workspace.mkdir()
    assert steward.find_runtime_doc(workspace) is None


def test_find_project_docs_finds_both_claude_and_project_md(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("x", encoding="utf-8")
    (tmp_path / "PROJECT.md").write_text("y", encoding="utf-8")
    docs = steward.find_project_docs(tmp_path)
    assert {p.name for p in docs} == {"CLAUDE.md", "PROJECT.md"}


def test_is_adequate_rejects_stub_files(tmp_path):
    stub = tmp_path / "CLAUDE.md"
    stub.write_text("TODO\n", encoding="utf-8")
    assert steward.is_adequate(stub) is False


def test_is_adequate_accepts_real_content(tmp_path):
    real = tmp_path / "CLAUDE.md"
    real.write_text(
        "# Real Project\n\n" + ("This is real documentation content. " * 20), encoding="utf-8"
    )
    assert steward.is_adequate(real) is True


def test_is_adequate_missing_file_returns_false(tmp_path):
    assert steward.is_adequate(tmp_path / "does-not-exist.md") is False


def test_generate_stewardship_doc_detects_python_stack(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    doc = steward.generate_stewardship_doc(tmp_path)
    assert "Python" in doc
    assert "pyproject.toml" in doc
    assert "src/" in doc
    assert "Auto-generated" in doc


def test_generate_stewardship_doc_no_recognized_stack(tmp_path):
    doc = steward.generate_stewardship_doc(tmp_path)
    assert "No recognized manifest file found" in doc


def test_resolve_stewardship_content_uses_adequate_project_doc_verbatim(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    real_content = "# My Project\n\n" + ("Real documented content here. " * 20)
    (workspace / "CLAUDE.md").write_text(real_content, encoding="utf-8")

    content = steward.resolve_stewardship_content(workspace)
    assert "My Project" in content
    assert "project doc:" in content
    # must NOT have auto-generated a PROJECT.md since an adequate doc already existed
    assert not (workspace / "PROJECT.md").exists()


def test_resolve_stewardship_content_generates_and_persists_when_missing(tmp_path):
    workspace = tmp_path / "ws2"
    workspace.mkdir()
    (workspace / "go.mod").write_text("module test\n", encoding="utf-8")

    content = steward.resolve_stewardship_content(workspace)
    assert "Go" in content
    assert "generated stewardship doc:" in content
    generated_path = workspace / "PROJECT.md"
    assert generated_path.exists()
    assert "Go" in generated_path.read_text(encoding="utf-8")


def test_resolve_stewardship_content_includes_runtime_doc_above_project_doc(tmp_path):
    (tmp_path / "CLAUDE.md").write_text(
        "# Runtime Doc\n\n" + ("Runtime content. " * 20), encoding="utf-8"
    )
    workspace = tmp_path / "proj"
    workspace.mkdir()
    (workspace / "PROJECT.md").write_text(
        "# Project Doc\n\n" + ("Project content. " * 20), encoding="utf-8"
    )

    content = steward.resolve_stewardship_content(workspace)
    runtime_idx = content.index("Runtime Doc")
    project_idx = content.index("Project Doc")
    assert runtime_idx < project_idx


def test_resolve_stewardship_content_second_call_does_not_regenerate(tmp_path):
    workspace = tmp_path / "ws3"
    workspace.mkdir()
    steward.resolve_stewardship_content(workspace)  # generates PROJECT.md
    generated_path = workspace / "PROJECT.md"
    first_mtime = generated_path.stat().st_mtime

    # second call: PROJECT.md now exists and is adequate (it's a real generated
    # doc, not a stub) -- must be treated as the project doc, not regenerated
    content2 = steward.resolve_stewardship_content(workspace)
    assert generated_path.stat().st_mtime == first_mtime
    assert "project doc:" in content2
