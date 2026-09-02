"""tests/test_determinex_agents.py

Covers the additions made to scripts/determinex_agents.py for the multi-agent
chat room feature: resolve_argv() (the pure, no-subprocess argv-resolution
contract the Rust chat backend relies on to spawn+stream a CLI itself) and
the local-ollama registration. Originally rode on aider's --model flag;
aider isn't installed here and this environment blocks pip installs, so
local-ollama now drives determinex_local_agent.py directly (Ollama HTTP +
swe_agent's proven SEARCH/REPLACE primitives) -- needs nothing beyond Python
and a running Ollama, which are both already present.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_agents as agents  # noqa: E402


def test_resolve_argv_local_ollama_substitutes_task_and_model():
    # local-ollama's template uses {task_file}, not {task} -- a chat-room
    # prompt (Mission Plan + transcript window) as a raw positional CLI
    # argument blew through Windows' command-line length limit (os error 206)
    # on every single turn. resolve_argv() writes the task to a temp file and
    # substitutes its path instead, so the task content is verified by
    # reading that file back, not by string-matching argv.
    argv = agents.resolve_argv(
        "local-ollama", "fix the bug", Path("C:/ws"), model="qwen2.5-coder:14b-instruct-q4_K_M"
    )
    # argv[0] is sys.executable -- NOT shutil.which("python"), which this test
    # used to assert. A bare `python` on PATH can be the Windows Store
    # AppExecLink stub (exits without running anything) and need not be the
    # interpreter holding this repo's dependencies; sys.executable is by
    # definition the one already running. Compared case-insensitively because
    # PATH reports `python.EXE` while sys.executable gives `python.exe` -- the
    # same file on a case-insensitive filesystem.
    assert argv[0].lower() == (sys.executable or "python").lower()
    assert argv[1].endswith("determinex_local_agent.py")
    assert argv[2] == "--task-file"
    task_file = Path(argv[3])
    assert task_file.read_text(encoding="utf-8") == "fix the bug"
    assert argv[4:] == [
        "--workspace",
        "C:\\ws" if sys.platform == "win32" else "C:/ws",
        "--model",
        "qwen2.5-coder:14b-instruct-q4_K_M",
    ]
    task_file.unlink()


def test_resolve_argv_local_ollama_aliases_resolve_the_same():
    for alias in ("aider-local", "ollama"):
        argv = agents.resolve_argv(alias, "fix the bug", Path("C:/ws"), model="tag")
        assert argv[1].endswith("determinex_local_agent.py")
        assert "tag" in argv


def test_resolve_argv_no_model_omits_the_flag_entirely():
    """No model selected -> the --model flag must be ABSENT, not present-and-empty.

    This previously asserted `argv[-1] == ""` ("empty, not a crash"), but an
    explicit `--model ""` is NOT harmless: argparse only applies a default when
    the flag is absent, so the empty string won and determinex_local_agent.py
    called Ollama with no model name -- every local-ollama chat turn died with
    `HTTP 404 ... is '' pulled? (ollama pull )` whenever the user hadn't picked
    a model, which is the default state of the UI.
    """
    argv = agents.resolve_argv("local-ollama", "fix the bug", Path("C:/ws"))
    assert "--model" not in argv
    assert "" not in argv


def test_resolve_argv_unknown_agent_raises():
    try:
        agents.resolve_argv("not-a-real-agent", "task", Path("C:/ws"))
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_resolve_argv_existing_agents_unaffected_by_model_substitution():
    """Regression: with no model= passed, aider/cursor-agent/claude-code/
    codex/gemini-cli resolve identically to before {model} substitution and
    model_flag existed (aider/cursor-agent have neither a {model} token nor
    a model_flag; claude-code/codex/gemini-cli's model_flag is a no-op
    unless model= is actually passed -- see the model_flag assertions below
    for the ANY LLM case where it IS passed).

    claude-code/codex deliberately carry NO {task} in their argv template
    (fixed 2026-07-21, see determinex_agents.py's registration comments and
    stdin_prompt flag) -- their whole prompt goes in via stdin instead, so
    it never touches the Windows command line and can't trip os error 206
    (ERROR_FILENAME_EXCED_RANGE) regardless of prompt size."""
    # argv[0] is shutil.which()-resolved (see resolve_argv's PATHEXT note) --
    # falls back to the bare probe name when not installed (cursor-agent).
    claude_exe = shutil.which("claude") or "claude"
    codex_exe = shutil.which("codex") or "codex"
    gemini_exe = shutil.which("gemini") or "gemini"
    # The permission/sandbox flags (added 2026-07-28) are part of the baseline
    # argv now: without them both CLIs reason correctly and then refuse to write
    # -- claude with "the edit is queued but needs your approval", codex with
    # "the workspace is mounted read-only". Both are the BOUNDED setting, not the
    # bypass-everything one; see the registration comments.
    assert agents.resolve_argv("claude-code", "do x", Path("C:/ws")) == [
        claude_exe,
        "-p",
        "--permission-mode",
        "acceptEdits",
    ]
    assert agents._AGENTS["claude-code"].stdin_prompt is True
    assert agents.resolve_argv("codex", "do x", Path("C:/ws")) == [
        codex_exe,
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "workspace-write",
    ]
    assert agents._AGENTS["codex"].stdin_prompt is True
    assert agents.resolve_argv("gemini-cli", "do x", Path("C:/ws")) == [
        gemini_exe,
        "-p",
        "do x",
        "--skip-trust",
    ]
    assert agents.resolve_argv("cursor-agent", "do x", Path("C:/ws")) == ["cursor-agent", "do x"]
    # ANY LLM: claude-code/codex/gemini-cli each have a model_flag="--model"
    # (2026-07-22) -- passing model=... now appends [--model, value] since
    # none of their templates carry a {model} token. cursor-agent has no
    # model_flag at all, so a model there IS still a harmless no-op.
    assert agents.resolve_argv("claude-code", "do x", Path("C:/ws"), model="opus") == [
        claude_exe,
        "-p",
        "--permission-mode",
        "acceptEdits",
        "--model",
        "opus",
    ]
    assert agents.resolve_argv("cursor-agent", "do x", Path("C:/ws"), model="irrelevant") == [
        "cursor-agent",
        "do x",
    ]


def test_resolve_argv_workspace_substitution(monkeypatch):
    template = ["python", "{task}", "--cwd", "{workspace}"]
    fake_agent = agents.Agent(
        name="_test-workspace-agent",
        probe="python",
        install_hint="",
        runner=agents._cli_runner(template),
        argv_template=template,
    )
    monkeypatch.setitem(agents._AGENTS, "_test-workspace-agent", fake_agent)

    argv = agents.resolve_argv("_test-workspace-agent", "task", Path("C:/some/ws"))
    python_exe = shutil.which("python") or "python"
    assert argv == [python_exe, "task", "--cwd", str(Path("C:/some/ws"))]


def test_run_agent_still_works_after_model_param_addition(monkeypatch, tmp_path):
    """Regression: run_agent()'s existing non-chat callers (AgentsPanel.tsx via
    agent_registry.rs) never pass `model` -- confirm the default (None) still
    threads cleanly through to the runner without a TypeError."""
    calls = []

    def fake_runner(task, workspace, timeout, model=None):
        calls.append((task, workspace, timeout, model))
        return "ok", 0

    fake_agent = agents.Agent(
        name="_test-fake-agent", probe="python", install_hint="", runner=fake_runner
    )
    monkeypatch.setitem(agents._AGENTS, "_test-fake-agent", fake_agent)

    # bypass real oracle for this pure plumbing check
    result = agents.run_agent("_test-fake-agent", "task", tmp_path, verify=False)
    assert result.ran is True
    assert calls[0] == ("task", tmp_path, 300, None)


# ── the two argv builders must stay ONE builder ───────────────────────────────
#
# Everything above this line tests resolve_argv(), which was the CORRECT builder.
# The bug was in the other one: _cli_runner substituted only {task}/{model}, so
# run_agent("local-ollama", ...) spawned the literal string "{task_file}" as a
# path. Nine tests passed while that was broken, because the single run_agent
# test monkeypatches the runner away and never builds a real argv. These tests
# exercise the builder that actually spawns.

import re  # noqa: E402

import pytest  # noqa: E402

_TASKFILE_RE = re.compile(r"determinex-agent-task-")


def _normalise(argv):
    """Temp task-file paths are unique per call; compare their ROLE, not the name."""
    return ["<TASKFILE>" if _TASKFILE_RE.search(a) else a for a in argv]


def _argv_from_cli_runner(monkeypatch, name, task, workspace, model=None):
    """The argv that _cli_runner would really hand to subprocess.run."""
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = list(argv)
        seen["task_file_existed"] = [(a, Path(a).is_file()) for a in argv if _TASKFILE_RE.search(a)]
        seen["task_file_text"] = [
            Path(a).read_text(encoding="utf-8") for a in argv if _TASKFILE_RE.search(a)
        ]

        class R:
            stdout, stderr, returncode = "", "", 0

        return R()

    monkeypatch.setattr(agents.subprocess, "run", fake_run)
    agents._AGENTS[name.lower()].runner(task, Path(workspace), 30, model)
    return seen


@pytest.mark.parametrize("name", ["local-ollama", "claude-code", "codex", "gemini-cli", "aider"])
@pytest.mark.parametrize("model", [None, "some-model:tag"])
def test_both_argv_builders_agree_for_every_agent(monkeypatch, name, model):
    """THE regression guard. resolve_argv (the Rust/IDE path) and _cli_runner (the
    Python run_agent path) must build identical argv, because they diverging is
    what made local-ollama work from the IDE and fail from Python."""
    expected = agents.resolve_argv(name, "fix the bug", Path("C:/ws"), model=model)
    seen = _argv_from_cli_runner(monkeypatch, name, "fix the bug", Path("C:/ws"), model)
    assert _normalise(seen["argv"]) == _normalise(expected), (
        f"{name}: the two argv builders disagree -- one of them is missing a "
        f"substitution or a flag rule"
    )


@pytest.mark.parametrize("name", ["local-ollama", "claude-code", "codex", "gemini-cli", "aider"])
def test_no_unsubstituted_placeholder_ever_reaches_a_spawn(monkeypatch, name):
    """Generalises past the {task_file} bug: ANY future template token that the
    builder forgets shows up here as a literal `{...}` in the spawned argv."""
    seen = _argv_from_cli_runner(monkeypatch, name, "fix the bug", Path("C:/ws"), "m:tag")
    leftover = [a for a in seen["argv"] if re.search(r"\{[a-z_]+\}", a)]
    assert not leftover, f"{name} spawned with unsubstituted placeholders: {leftover}"


def test_the_task_file_actually_exists_and_holds_the_task(monkeypatch):
    """The literal failure: FileNotFoundError: '{task_file}'. The path handed to
    the CLI has to be a real file containing the real prompt at spawn time."""
    seen = _argv_from_cli_runner(monkeypatch, "local-ollama", "fix the bug", Path("C:/ws"))
    assert seen["task_file_existed"], "local-ollama spawned with no task file at all"
    for path, existed in seen["task_file_existed"]:
        assert existed, f"task file {path} did not exist when the CLI was spawned"
    assert seen["task_file_text"] == ["fix the bug"]


def test_the_task_file_is_cleaned_up_after_the_run(monkeypatch):
    """_cli_runner ran the CLI itself, so it owns the temp file. (resolve_argv
    must NOT delete -- its consumer spawns later and still has to read it.)"""
    seen = _argv_from_cli_runner(monkeypatch, "local-ollama", "fix the bug", Path("C:/ws"))
    for path, _ in seen["task_file_existed"]:
        assert not Path(path).is_file(), f"{path} leaked after the run"


def test_local_ollama_spawns_a_real_interpreter_not_a_bare_python():
    """A bare `python` resolves through PATH to the Windows Store AppExecLink stub
    on many boxes -- it exits without running anything. sys.executable is by
    definition the interpreter that already has this repo's dependencies."""
    argv = agents.resolve_argv("local-ollama", "t", Path("C:/ws"))
    assert argv[0] != "python", "local-ollama is spawning a bare PATH python"
    assert Path(argv[0]).is_file(), f"argv[0]={argv[0]!r} is not a real executable"
