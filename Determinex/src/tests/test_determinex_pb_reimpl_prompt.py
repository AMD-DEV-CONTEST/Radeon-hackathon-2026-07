"""Tests for determinex_pb_reimpl.py's prompt builders -- specifically the 2026-07-16 fix for a
real, live bug: build_prompt()'s final "Your task" trailer hardcoded "Write a single
self-contained Python 3 program... invoked as python3 main.py" UNCONDITIONALLY, for every
language -- a direct contradiction with _lang_directive() (called earlier in the SAME prompt),
which correctly said "write Rust"/"write Go"/etc. for native tasks. Every native reimplementation
attempt was getting a self-contradictory prompt. build_incremental_prompt() (the iterative
fix-loop prompt) already handled this correctly via a fname/runcmd lookup -- build_prompt() (the
first-pass generation prompt, the one that actually matters most) never got the same fix.

These tests exist so that regression is structurally impossible: test_your_task_never_mentions_
python_for_native_languages is the direct regression guard, and would have failed against the
pre-fix code.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_pb_reimpl as R  # noqa: E402


def _task_section(prompt: str) -> str:
    return prompt.split("## Your task")[1].split("CRITICAL rules")[0]


def test_your_task_never_mentions_python_for_native_languages():
    """THE regression guard for the bug this session found: for every native (non-python)
    language, the 'Your task' trailer must not say 'Python' or 'python3' anywhere."""
    for lang in ("rust", "go", "c", "cpp", "haskell"):
        R._LANG = lang
        prompt = R.build_prompt("some__tool.abc1234", "docs", "help text", [])
        task = _task_section(prompt)
        assert "Python" not in task, f"{lang}: task trailer still mentions Python"
        assert "python3" not in task, f"{lang}: task trailer still says 'python3 main.py'"


def test_your_task_names_the_correct_language_and_fence():
    cases = {
        "rust": ("Rust", "```rust"),
        "go": ("Go", "```go"),
        "c": ("C", "```c"),
        "cpp": ("C++", "```cpp"),
        "haskell": ("Haskell", "```haskell"),
    }
    for lang, (display_name, fence) in cases.items():
        R._LANG = lang
        prompt = R.build_prompt("some__tool.abc1234", "docs", "help text", [])
        task = _task_section(prompt)
        assert display_name in task
        assert fence in task


def test_your_task_uses_the_correct_native_filename():
    expected = {
        "rust": "main.rs",
        "go": "main.go",
        "c": "main.c",
        "cpp": "main.cpp",
        "haskell": "main.hs",
    }
    for lang, fname in expected.items():
        R._LANG = lang
        prompt = R.build_prompt("some__tool.abc1234", "docs", "help text", [])
        assert fname in _task_section(prompt)


def test_python_task_instruction_is_unchanged_python_specific():
    """Regression guard the other direction: fixing native languages must not break python."""
    R._LANG = "python"
    prompt = R.build_prompt("some__tool.abc1234", "docs", "help text", [])
    task = _task_section(prompt)
    assert "Python 3 program" in task
    assert "python3 main.py" in task
    assert "```python" in task


def test_language_reference_block_present_for_native_languages_with_a_reference_file():
    for lang in ("rust", "go", "c", "cpp"):
        R._LANG = lang
        prompt = R.build_prompt("some__tool.abc1234", "docs", "help text", [])
        assert f"Language reference for `{lang}`" in prompt
        assert "NOT this tool's source" in prompt


def test_language_reference_block_absent_for_python_and_haskell():
    """python needs no native-build grounding; haskell has no reference file yet -- absent,
    not fabricated, matching this session's established pattern (e.g. gemma in the rosetta
    registry: skip gracefully rather than invent content)."""
    for lang in ("python", "haskell"):
        R._LANG = lang
        prompt = R.build_prompt("some__tool.abc1234", "docs", "help text", [])
        assert f"Language reference for `{lang}`" not in prompt


def test_language_reference_block_unknown_language_returns_empty():
    assert R._language_reference_block("cobol") == ""


def test_language_reference_block_content_is_real_not_placeholder():
    """Sanity check the actual reference files carry real technical content, not stubs."""
    rust_block = R._language_reference_block("rust")
    assert "ownership" in rust_block.lower()
    assert "rustc --edition 2021" in rust_block
    go_block = R._language_reference_block("go")
    assert "os.Args" in go_block
    c_block = R._language_reference_block("c")
    assert "malloc" in c_block
    cpp_block = R._language_reference_block("cpp")
    assert "RAII" in cpp_block


def test_systems_reference_block_present_for_every_language():
    """Unlike the per-language block, systems.md applies regardless of language -- python
    included, since it runs in the same container/harness as native builds."""
    for lang in ("python", "rust", "go", "c", "cpp", "haskell"):
        R._LANG = lang
        prompt = R.build_prompt("some__tool.abc1234", "docs", "help text", [])
        assert "Systems/runtime conventions" in prompt


def test_systems_reference_block_content_is_real():
    block = R._systems_reference_block()
    assert "128 + signal_number" in block
    assert "NO_COLOR" in block
    assert "root" in block.lower()


def test_family_conventions_block_matches_a_known_tool_archetype():
    """nomino is a real ProgramBench tool (file renamer) with a hint in
    programbench_classify_family.py's _TOOL_NAME_HINTS."""
    R._LANG = "rust"
    block = R._family_conventions_block("nomino")
    assert block != ""
    assert "rename" in block.lower() or "file_renamers" in block.lower()


def test_family_conventions_block_excludes_language_families():
    """rust_cli/go_cli conventions are already absorbed into language_reference/{rust,go}.md --
    _family_conventions_block must never surface them a second time, even for a tool that
    would otherwise classify as rust_cli via the language-hint fallback."""
    block = R._family_conventions_block("some_purely_rust_named_rs_tool")
    # even if classify_family's language-hint fallback matches rust_cli, the exclusion set
    # must filter it out -- this should return "" (no OTHER family also matches this name)
    assert "clap" not in block.lower() or block == ""


def test_family_conventions_block_empty_for_unknown_tool():
    assert R._family_conventions_block("totally_unclassifiable_xyz_tool") == ""


def test_family_conventions_block_appears_in_build_prompt_when_matched():
    R._LANG = "rust"
    prompt = R.build_prompt("yaa110__nomino.f892499", "docs", "help text", [])
    assert "Tool-category conventions" in prompt


def test_family_conventions_block_absent_in_build_prompt_when_unmatched():
    R._LANG = "rust"
    prompt = R.build_prompt("someauthor__totallyunknowntool.abc1234", "docs", "help text", [])
    assert "Tool-category conventions" not in prompt


def test_fname_by_lang_is_the_single_shared_source_for_both_prompt_builders():
    """build_prompt() and build_incremental_prompt() must derive the output filename from the
    SAME dict -- two independently-maintained copies is exactly the drift mechanism that let
    the Python-hardcoding bug survive undetected."""
    assert R._FNAME_BY_LANG == {
        "python": "main.py",
        "rust": "main.rs",
        "go": "main.go",
        "c": "main.c",
        "cpp": "main.cpp",
        "haskell": "main.hs",
    }


def test_build_incremental_prompt_still_correct_after_fname_dedup():
    R._LANG = "rust"
    prompt = R.build_incremental_prompt(
        current="fn main() {}",
        new_obs=_fake_observation(),
        accepted=[],
        helptext="help",
        short="dirble",
    )
    assert "main.rs" in prompt
    assert "the COMPILED binary" in prompt
    assert "python3" not in prompt


class _FakeProbe:
    argv = ["--help"]
    files: dict = {}
    stdin = None


class _FakeObs:
    probe = _FakeProbe()
    returncode = 0
    stdout = "usage: dirble\n"
    stderr = ""


def _fake_observation():
    return _FakeObs()


# ---------------------------------------------------------------------------
# Sibling error-example surfacing (found live 2026-07-19 driving gron)
# ---------------------------------------------------------------------------
class _Probe:
    def __init__(self, argv, files=None):
        self.argv = argv
        self.files = files or {}
        self.stdin = None


class _Obs:
    def __init__(self, argv, files, returncode, stderr, stdout=""):
        self.probe = _Probe(argv, files)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_sibling_same_flag_error_examples_are_surfaced_in_full():
    """THE regression guard for the bug this session found live: three --ungron stations
    (gron given non-gron JSON input) each show a DIFFERENT exact truncated-token error --
    'ungron failed for ``: invalid statement' / '...for `[1`: ...' / '...for `[`: ...' -- and
    the model was only ever shown ONE of these per station, with sibling cases reduced to a
    one-line '[+exact stderr]' flag that hides the actual text. Three isolated single-shot
    guesses at an unexplained exact-format rule is not the same signal as three examples seen
    together, which is what a model needs to infer the shared rule. build_incremental_prompt
    must now surface full stderr for prior observations sharing the current one's first argv
    token (same flag)."""
    R._LANG = "go"
    prior = _Obs(
        ["--ungron", "-m", "obj_arr.json"],
        {"obj_arr.json": '{"a":1}'},
        5,
        "ungron failed for ``: invalid statement\n",
    )
    target = _Obs(
        ["--ungron", "-m", "top_array.json"],
        {"top_array.json": "[1,2,3]"},
        5,
        "ungron failed for `[1`: invalid statement\n",
    )
    prompt = R.build_incremental_prompt(
        current="package main",
        new_obs=target,
        accepted=[prior, target],
        helptext="help",
        short="gron",
    )
    assert "RELATED --ungron EXAMPLES" in prompt
    # the sibling's FULL stderr text must appear verbatim, not just a "+exact stderr" flag
    assert "ungron failed for ``: invalid statement" in prompt


def test_sibling_examples_omitted_for_different_flags():
    R._LANG = "go"
    prior = _Obs(["--values"], {}, 0, "")  # different flag, not an error case either
    target = _Obs(
        ["--ungron", "-m", "x.json"],
        {"x.json": "[1]"},
        5,
        "ungron failed for `[1`: invalid statement\n",
    )
    prompt = R.build_incremental_prompt(
        current="package main",
        new_obs=target,
        accepted=[prior, target],
        helptext="help",
        short="gron",
    )
    assert "RELATED --ungron EXAMPLES" not in prompt


def test_sibling_examples_capped_at_three():
    R._LANG = "go"
    siblings = [
        _Obs(
            ["--ungron", "-m", f"f{i}.json"],
            {f"f{i}.json": "[1]"},
            5,
            f"ungron failed for `sib{i}`: invalid statement\n",
        )
        for i in range(5)
    ]
    target = _Obs(
        ["--ungron", "-m", "last.json"],
        {"last.json": "[1]"},
        5,
        "ungron failed for `last`: invalid statement\n",
    )
    prompt = R.build_incremental_prompt(
        current="package main",
        new_obs=target,
        accepted=siblings + [target],
        helptext="help",
        short="gron",
    )
    # only the most recent 3 siblings are shown, not all 5
    assert "sib0" not in prompt and "sib1" not in prompt
    assert "sib2" in prompt and "sib3" in prompt and "sib4" in prompt
