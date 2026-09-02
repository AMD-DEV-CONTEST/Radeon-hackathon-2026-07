"""tests/test_determinex_ingest.py

Regression coverage for the ingest file-walk bug found live 2026-07-22: the
FIRST time a multi-agent chat-room turn ever reached oracle verification
(after fixing the separate PATHEXT spawn bug that had silently swallowed
every prior codex/gemini-cli turn), repair_workspace() crashed scanning this
very repo with `OSError: [WinError 1920] The file cannot be accessed by the
system` on frontend/node_modules/.bin/.acorn-DALZbuMa -- a broken/
reparse-point npm shim. Root cause: `_census_languages`/`_detect_harness`
called `p.is_file()` on every path BEFORE the node_modules/.git/etc
exclusion check ran, and `_detect_build` didn't exclude those directories at
all. See determinex_ingest.py's `_walk_files` docstring for the full story.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_ingest as ingest_mod  # noqa: E402


def test_walk_files_skips_a_path_that_raises_on_stat(tmp_path, monkeypatch):
    """A broken/reparse-point/permission-denied file must not abort the
    whole scan -- exactly the live WinError 1920 failure mode."""
    (tmp_path / "real.py").write_text("print('hi')\n", encoding="utf-8")
    poisoned = tmp_path / "poisoned.py"
    poisoned.write_text("", encoding="utf-8")

    real_is_file = Path.is_file

    def flaky_is_file(self):
        if self.name == "poisoned.py":
            raise OSError("[WinError 1920] The file cannot be accessed by the system")
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", flaky_is_file)

    files = list(ingest_mod._walk_files(tmp_path))
    names = {p.name for p in files}
    assert "real.py" in names
    assert "poisoned.py" not in names  # skipped, not propagated


def test_walk_files_excludes_node_modules_git_target_vendor(tmp_path):
    (tmp_path / "src.py").write_text("x = 1\n", encoding="utf-8")
    for excluded_dir in ("node_modules", ".git", "target", "vendor"):
        d = tmp_path / excluded_dir
        d.mkdir()
        (d / "should_not_count.py").write_text("y = 2\n", encoding="utf-8")

    names = {p.name for p in ingest_mod._walk_files(tmp_path)}
    assert names == {"src.py"}


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(root), check=True)


def test_walk_files_prefers_git_ls_files_and_respects_gitignore(tmp_path):
    """The real fix for the OTHER half of the live 2026-07-22 incident: even
    with a hand-maintained exclusion list, this project's own gitignored
    scratch/archive/release_build_work/.pytest_tmp_*/etc directories pushed
    a single ingest() call past several minutes and multiple GB of resident
    memory. Every git repo already has the authoritative answer in
    .gitignore -- use it instead of trying to hand-enumerate every
    project's own huge-but-irrelevant directory names."""
    _init_git_repo(tmp_path)
    (tmp_path / "src.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("huge_scratch_dir/\n", encoding="utf-8")
    huge = tmp_path / "huge_scratch_dir"
    huge.mkdir()
    (huge / "irrelevant.py").write_text("y = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "src.py", ".gitignore"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(tmp_path), check=True)

    names = {p.name for p in ingest_mod._walk_files(tmp_path)}
    assert "src.py" in names
    assert ".gitignore" in names
    assert "irrelevant.py" not in names  # gitignored dir never even .rglob()'d


def test_git_tracked_files_returns_none_for_non_git_workspace(tmp_path):
    assert ingest_mod._git_tracked_files(tmp_path) is None


def test_walk_files_applies_exclusions_to_tracked_files_too(tmp_path):
    """Regression: an is_file()-removal optimization to the git branch of
    _walk_files silently dropped the per-path _EXCLUDED_DIR_NAMES check
    entirely on that branch (it had only ever lived in the manual
    fallback's loop). git ls-files only respects .gitignore, which does
    NOT cover intentionally-TRACKED-but-not-real-source directories (this
    project's own corpus/programbench/per_tool_overrides/, 124k+ files of
    vendored reference archives, found live 2026-07-22) -- so every
    _EXCLUDED_DIR_NAMES entry silently stopped applying to any git
    workspace (i.e. every real repo) until this was caught."""
    _init_git_repo(tmp_path)
    (tmp_path / "src.py").write_text("x = 1\n", encoding="utf-8")
    excluded = tmp_path / "per_tool_overrides"
    excluded.mkdir()
    (excluded / "vendored.c").write_text("int x;\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(tmp_path), check=True)

    # Both tracked; only .gitignore-based filtering wouldn't catch this one.
    tracked = ingest_mod._git_tracked_files(tmp_path)
    assert tracked is not None
    assert any(p.name == "vendored.c" for p in tracked)

    names = {p.name for p in ingest_mod._walk_files(tmp_path)}
    assert "src.py" in names
    assert "vendored.c" not in names


def test_walk_files_excludes_caches_and_venvs(tmp_path):
    """Regression: a real-world monorepo's .venv/scratch-style cache dirs
    (this project's own, found live 2026-07-22) pushed a single ingest()
    call past several minutes and multiple GB of resident memory -- a
    general-purpose 'point this at any repo' scanner needs to skip common
    interpreter/tool caches and virtualenvs by default, not just avoid
    crashing on them."""
    (tmp_path / "src.py").write_text("x = 1\n", encoding="utf-8")
    for excluded_dir in (
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".uv-cache",
        ".cache",
        "dist",
        "build",
        ".next",
        ".idea",
        ".vscode",
    ):
        d = tmp_path / excluded_dir
        d.mkdir()
        (d / "should_not_count.py").write_text("y = 2\n", encoding="utf-8")

    names = {p.name for p in ingest_mod._walk_files(tmp_path)}
    assert names == {"src.py"}


def test_census_languages_ignores_node_modules_contents(tmp_path):
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    nm = tmp_path / "frontend" / "node_modules" / ".bin"
    nm.mkdir(parents=True)
    (nm / "shim.js").write_text("// noop\n", encoding="utf-8")

    census = ingest_mod._census_languages(list(ingest_mod._walk_files(tmp_path)))
    assert census == {"python": 1}


def test_detect_build_ignores_nested_node_modules_package_json(tmp_path):
    """Regression: _detect_build previously had NO exclusion filtering at
    all (unlike _census_languages/_detect_harness), so a vendored nested
    node_modules/package.json could misreport the whole repo's build system
    as npm even when the real, top-level build system is something else."""
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n", encoding="utf-8")
    nm = tmp_path / "some_tool" / "node_modules" / "leftpad"
    nm.mkdir(parents=True)
    (nm / "package.json").write_text("{}", encoding="utf-8")

    files = list(ingest_mod._walk_files(tmp_path))
    assert ingest_mod._detect_build(tmp_path, files) == "cargo"


def test_detect_build_still_finds_nested_marker_outside_excluded_dirs(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "go.mod").write_text("module x\n", encoding="utf-8")

    files = list(ingest_mod._walk_files(tmp_path))
    assert ingest_mod._detect_build(tmp_path, files) == "go"


def test_detect_harness_skips_broken_file_and_excluded_dirs(tmp_path):
    (tmp_path / "test_foo.py").write_text(
        "import pytest\ndef test_x():\n    assert True\n", encoding="utf-8"
    )
    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / "test_should_be_ignored.py").write_text("assert False\n", encoding="utf-8")

    files = list(ingest_mod._walk_files(tmp_path))
    name, has_tests, test_files = ingest_mod._detect_harness(files)
    assert has_tests is True
    assert name == "pytest"
    assert all("node_modules" not in p.parts for p in test_files)


# ---------------------------------------------------------------------------
# Tauri composite-subproject merging, 2026-07-22 -- the oracle pool grew a
# "pure tauri" composite oracle (determinex_oracle._verify_tauri) that
# verifies a Rust backend (src-tauri/) and its TS/JS frontend TOGETHER as one
# app, because a passing `cargo check` next to a broken frontend build isn't
# a real pass. discover_subprojects previously reported these as two
# unrelated subprojects (rust at src-tauri/, typescript at the app root) --
# _merge_tauri_pairs collapses a real Tauri pair into one "tauri" subproject
# rooted at the app, and must NOT touch a plain rust-app-next-to-a-js-app
# that merely happens to share the same layout without a tauri.conf.json.
# ---------------------------------------------------------------------------


def _write_cargo_toml(p: Path, name: str = "x") -> None:
    p.write_text(f'[package]\nname = "{name}"\nversion = "0.1.0"\n', encoding="utf-8")


def test_discover_subprojects_merges_real_tauri_pair_into_one(tmp_path):
    app = tmp_path / "frontend"
    src_tauri = app / "src-tauri"
    src_tauri.mkdir(parents=True)
    _write_cargo_toml(src_tauri / "Cargo.toml")
    (src_tauri / "tauri.conf.json").write_text("{}", encoding="utf-8")
    (src_tauri / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    (app / "package.json").write_text("{}", encoding="utf-8")
    (app / "index.ts").write_text("export const x = 1;\n", encoding="utf-8")

    subprojects = ingest_mod.discover_subprojects(tmp_path)

    assert len(subprojects) == 1
    sp = subprojects[0]
    assert sp.language == "tauri"
    assert sp.path == app


def test_discover_subprojects_does_not_merge_a_rust_app_without_tauri_conf(tmp_path):
    """A rust subproject that merely happens to sit in a dir named
    src-tauri, with no tauri.conf.json, is NOT a real Tauri app -- must stay
    two independent subprojects, not be silently collapsed."""
    app = tmp_path / "frontend"
    src_tauri = app / "src-tauri"
    src_tauri.mkdir(parents=True)
    _write_cargo_toml(src_tauri / "Cargo.toml")
    (src_tauri / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    (app / "package.json").write_text("{}", encoding="utf-8")
    (app / "index.ts").write_text("export const x = 1;\n", encoding="utf-8")

    subprojects = ingest_mod.discover_subprojects(tmp_path)

    languages = {sp.language for sp in subprojects}
    assert languages == {"rust", "typescript"}


def test_discover_subprojects_finds_independent_rust_and_c_projects(tmp_path):
    rust_dir = tmp_path / "engine"
    rust_dir.mkdir()
    _write_cargo_toml(rust_dir / "Cargo.toml")
    (rust_dir / "main.rs").write_text("fn main() {}\n", encoding="utf-8")

    c_dir = tmp_path / "native"
    c_dir.mkdir()
    (c_dir / "Makefile").write_text("all:\n\tgcc -o out main.c\n", encoding="utf-8")
    (c_dir / "main.c").write_text("int main() { return 0; }\n", encoding="utf-8")

    subprojects = ingest_mod.discover_subprojects(tmp_path)

    by_lang = {sp.language: sp for sp in subprojects}
    assert by_lang["rust"].path == rust_dir
    assert by_lang["c"].path == c_dir
