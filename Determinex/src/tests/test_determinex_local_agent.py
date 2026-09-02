"""The local-model agent's edit loop.

WHY THESE EXIST
---------------
`determinex_local_agent.py` shipped as a single-shot generator: prompt the model
once, apply whatever SEARCH/REPLACE blocks matched, return. Two consequences went
unnoticed because nothing had ever run it against a workspace an oracle could
judge:

1. The prompt listed workspace file *paths* but never file *contents*, while
   demanding a byte-exact SEARCH block. Asked to fix `add.py` having never seen
   `add.py`, a 1.5B model emitted `def subtract(a, b):` as its SEARCH text --
   absent from the file, so it failed all six of the applicator's fuzzy passes.
   The task was impossible, not merely hard.
2. There was no retry. `run_agent()` judged the result with the oracle afterwards
   but never told the agent what failed -- an open loop wearing a closed loop's
   clothes.

And the first version of the fix introduced a third: a response that named a file
but emitted a malformed block parsed to zero blocks, which the loop reported as
success having changed nothing.

Every test below pins one of those three. The model is stubbed, so they run in
milliseconds and need neither Ollama nor a GPU.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
for p in (str(REPO_ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import determinex_local_agent as L  # noqa: E402

GOOD_BLOCK = """### FILE: add.py
<<<SEARCH
    return a - b
===
    return a + b
>>>REPLACE
"""

# What a 1.5B model actually emitted, verbatim: `<<<` not `<<<SEARCH`, no
# `>>>REPLACE` terminator, and the corrected code in the SEARCH half.
MALFORMED_BLOCK = """### FILE: add.py
<<<
def add(a, b):
    return a + b

===
<no change>
"""

NONMATCHING_BLOCK = """### FILE: add.py
<<<SEARCH
def subtract(a, b):
    return a - b
===
def add(a, b):
    return a + b
>>>REPLACE
"""

TASK = "add() subtracts instead of adding. Fix add.py so add(2, 3) returns 5."


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "add.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def spy(monkeypatch):
    """Stub the model. Returns the recorder; set .replies to a list of responses."""

    class Spy:
        replies: list[str] = []
        prompts: list[str] = []

        def __call__(self, model, prompt, system=None, timeout=None):
            self.prompts.append(prompt)
            i = min(len(self.prompts) - 1, len(self.replies) - 1)
            return self.replies[i]

    s = Spy()
    monkeypatch.setattr(L, "_ollama", s)
    monkeypatch.setattr(L._bench, "estimate_timeout_seconds", lambda m: 5)
    return s


# ── defect 1: the model was never shown the bytes it had to match ────────────


def test_the_prompt_contains_the_files_verbatim_contents(ws, spy):
    spy.replies = [GOOD_BLOCK]
    L.run(TASK, ws, "m")
    assert "return a - b" in spy.prompts[0], (
        "the prompt does not contain the file's actual text, so an exact SEARCH "
        "block is impossible to produce"
    )


def test_a_truncated_file_is_labelled_as_truncated(ws, spy):
    (ws / "big.py").write_text("# pad\n" * 5000, encoding="utf-8")
    spy.replies = [GOOD_BLOCK]
    L.run(TASK, ws, "m")
    rendered, _shown = L._render_file_contents(ws, ["big.py"], per_file_chars=100)
    assert "TRUNCATED" in rendered, (
        "a partially-shown file must say so; a SEARCH in the elided region can never match"
    )


# ── defect 2: no retry, so a weak model got exactly one guess ────────────────


def test_a_nonmatching_search_is_retried_with_the_failure_injected(ws, spy):
    spy.replies = [NONMATCHING_BLOCK, GOOD_BLOCK]
    out, rc = L.run(TASK, ws, "m", max_attempts=3)

    assert len(spy.prompts) == 2, "a failed apply was not retried"
    assert "def subtract(a, b):" in spy.prompts[1], (
        "the retry prompt does not contain the SEARCH text that failed, so the "
        "model has no way to know what went wrong"
    )
    assert rc == 0
    assert (ws / "add.py").read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"


def test_exhausting_the_attempts_reports_failure_not_success(ws, spy):
    spy.replies = [NONMATCHING_BLOCK]
    out, rc = L.run(TASK, ws, "m", max_attempts=2)
    assert len(spy.prompts) == 2
    assert rc == 1, "gave up but reported success"
    assert "exhausted" in out
    # The file must be untouched -- a failed edit that half-applies is worse
    # than one that doesn't apply.
    assert (ws / "add.py").read_text(encoding="utf-8") == "def add(a, b):\n    return a - b\n"


# ── defect 3: a malformed block reported success having changed nothing ──────


def test_a_malformed_block_is_a_failure_not_a_silent_success(ws, spy):
    """The regression. `<<<` instead of `<<<SEARCH` parses to zero blocks; the
    first version of the retry loop saw "no failures" and returned 0."""
    spy.replies = [MALFORMED_BLOCK]
    out, rc = L.run(TASK, ws, "m", max_attempts=2)
    assert rc == 1, "a malformed block that changed nothing was reported as success"
    assert (ws / "add.py").read_text(encoding="utf-8") == "def add(a, b):\n    return a - b\n"


def test_a_malformed_block_is_retried_with_format_correction(ws, spy):
    spy.replies = [MALFORMED_BLOCK, GOOD_BLOCK]
    out, rc = L.run(TASK, ws, "m", max_attempts=3)
    assert len(spy.prompts) == 2, "a malformed block was not retried"
    assert "<<<SEARCH" in spy.prompts[1], "the correction does not show the right markers"
    assert rc == 0
    assert (ws / "add.py").read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"


# ── the paths that must NOT be treated as failures ──────────────────────────


def test_a_reply_with_no_file_marker_is_a_discussion_turn_not_a_failure(ws, spy):
    """A chat participant is allowed to just talk. Only a response that names a
    file is claiming to have made an edit."""
    spy.replies = ["I looked at add.py and the operator is wrong, but you asked me not to edit."]
    out, rc = L.run(TASK, ws, "m", max_attempts=3)
    assert len(spy.prompts) == 1, "a discussion turn was retried as though it failed"
    assert rc == 0


def test_a_clean_first_attempt_does_not_retry(ws, spy):
    spy.replies = [GOOD_BLOCK]
    out, rc = L.run(TASK, ws, "m", max_attempts=3)
    assert len(spy.prompts) == 1, "a successful edit was retried anyway"
    assert rc == 0


def test_no_response_from_ollama_is_reported_not_swallowed(ws, spy):
    spy.replies = [""]
    out, rc = L.run(TASK, ws, "m")
    assert rc == 1
    assert "ollama" in out.lower()


# ── the ranker ──────────────────────────────────────────────────────────────


def test_ranking_reuses_the_context_provisioner_and_still_lists_everything(ws, spy):
    """The provisioner only scores code files with a keyword hit, so anything it
    skips still has to be reachable -- otherwise a task mentioning no filename
    would show the model nothing."""
    (ws / "notes.txt").write_text("unrelated\n", encoding="utf-8")
    ranked = L._rank_paths(ws, TASK)
    assert "add.py" in ranked
    assert "notes.txt" in ranked
    assert ranked.index("add.py") < ranked.index("notes.txt"), (
        "the file the task names should be ranked above an unrelated one"
    )
