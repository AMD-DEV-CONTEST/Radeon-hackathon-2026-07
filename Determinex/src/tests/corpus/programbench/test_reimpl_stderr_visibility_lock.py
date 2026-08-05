"""Lock for the 2026-07-02 stderr-blindness bug.

Found while watching a live cmatrix run: 48/48 VerifiedSearch samples (both
tiers of the escalation ladder, all rounds) scored exactly 0.00. Root cause
was NOT a hard reimplementation problem -- make_verify() requires an EXACT
stderr match whenever the exit is non-zero and stderr is non-empty (e.g.
ncurses' "Error opening terminal: unknown." under a no-TTY capture -- a
common pattern for any TUI tool, and stderr-on-error is a near-universal CLI
pattern generally), but none of the three places that show the model what to
reproduce ever displayed expected stderr:
  1. observations_to_examples() -- the monolithic prompt's example block
  2. build_incremental_prompt() -- the decompose station prompt
  3. make_verify()'s Failure.text -- the retry-round feedback (shared root
     cause: VerifiedSearch._feedback_from reads this verbatim every round)
The model was being scored against content it could never see, in any round,
via any prompt path. Fixed by surfacing expected (and, in failures, actual)
stderr in all three.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import determinex_observe as OBS  # noqa: E402
import determinex_pb_reimpl as reimpl  # noqa: E402


def _err_probe(argv=("-a",)):
    return OBS.Probe("p", list(argv), None, {}, {})


def test_observations_to_examples_shows_expected_stderr_on_error():
    obs = [OBS.Observation(_err_probe(), "", "Error opening terminal: unknown.\n", 1)]
    block = OBS.observations_to_examples(obs)
    assert "Error opening terminal: unknown." in block
    assert "MUST MATCH EXACTLY" in block


def test_observations_to_examples_omits_stderr_note_on_clean_exit():
    obs = [OBS.Observation(_err_probe(), "ok\n", "", 0)]
    block = OBS.observations_to_examples(obs)
    assert "stderr" not in block.lower()


def test_incremental_prompt_shows_expected_stderr_on_error(monkeypatch):
    monkeypatch.setattr(reimpl, "_LANG", "c")
    o = OBS.Observation(_err_probe(), "", "Error opening terminal: unknown.\n", 1)
    prompt = reimpl.build_incremental_prompt("", o, [o], "helptext", "cmatrix")
    assert "Error opening terminal: unknown." in prompt
    assert "MUST MATCH EXACTLY" in prompt
    assert "part of the pass criteria" in prompt.lower() or "MUST MATCH" in prompt


def test_incremental_prompt_passes_observations_to_corpus_recipes(monkeypatch):
    # LOAD-BEARING: without observations=, recipes_for() sees an empty blob and domain
    # recipes (tui/json/table) never auto-fire for decompose stations.
    monkeypatch.setattr(reimpl, "_LANG", "c")
    tui_obs = OBS.Observation(
        OBS.Probe("tui-snapshot", [], None, {}, {}), "\x1b[42m  \x1b[49m", "", 0
    )
    prompt = reimpl.build_incremental_prompt("", tui_obs, [tui_obs], "helptext", "sometool")
    assert "ncurses" in prompt.lower() or "TUI" in prompt


def test_make_verify_failure_text_includes_expected_and_actual_stderr():
    obs = [OBS.Observation(_err_probe(), "", "Error opening terminal: unknown.\n", 1)]
    verify = OBS.make_verify(obs, runner=lambda code, probe: ("", "wrong stderr\n", 1))
    res = verify("int main(){return 1;}")
    assert not res.passed
    text = res.failures[0].text
    assert "Error opening terminal: unknown." in text  # expected
    assert "wrong stderr" in text  # actual
    assert "MISMATCH" in text


def test_make_verify_passes_when_stderr_matches_exactly():
    obs = [OBS.Observation(_err_probe(), "", "Error opening terminal: unknown.\n", 1)]
    verify = OBS.make_verify(
        obs, runner=lambda code, probe: ("", "Error opening terminal: unknown.\n", 1)
    )
    res = verify("int main(){return 1;}")
    assert res.passed


def test_make_verify_ignores_stderr_on_clean_exit():
    # stderr is only load-bearing on the ERROR path (rc != 0); success-path stderr
    # (warnings/progress) is not asserted by default.
    obs = [OBS.Observation(_err_probe(), "ok\n", "some warning\n", 0)]
    verify = OBS.make_verify(obs, runner=lambda code, probe: ("ok\n", "different warning\n", 0))
    res = verify("int main(){return 0;}")
    assert res.passed
