"""The context budget, and the distinction it exists to keep visible.

PR #44 item 1 raised the serving window from 8192 to 20480. The risk in that
change is not arithmetic: it is that an approved target and a measured
capability become the same number in the code, after which no reader can tell
which one they are looking at. These tests pin the separation, the refusal to
widen, and the provenance carried on every recorded bound.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.experience_asset.inference import budget


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("E5_CONTEXT_BUDGET_TOKENS", raising=False)
    monkeypatch.delenv(budget.TOKENIZER_SNAPSHOT_ENV, raising=False)


def test_the_approved_budget_and_the_verified_window_are_different_numbers():
    """The whole point of the module: 20480 is approved, 8192 is proven."""
    assert budget.APPROVED_CONTEXT_BUDGET_TOKENS == 20480
    assert budget.VERIFIED_CONTEXT_TOKENS == 8192
    assert budget.APPROVED_CONTEXT_BUDGET_TOKENS != budget.VERIFIED_CONTEXT_TOKENS
    assert budget.context_budget_tokens() == budget.APPROVED_CONTEXT_BUDGET_TOKENS


def test_a_run_may_be_held_stricter_than_the_approved_budget(monkeypatch):
    """Narrowing to the verified window must be possible without a code change.

    Until 20K is qualified on the W7900, a deployment may want to run at the
    only window anyone has measured.
    """
    monkeypatch.setenv("E5_CONTEXT_BUDGET_TOKENS", str(budget.VERIFIED_CONTEXT_TOKENS))

    assert budget.context_budget_tokens() == 8192


@pytest.mark.parametrize("value", ["20481", "32768", "0", "-1"])
def test_the_budget_cannot_be_widened_past_what_was_approved(monkeypatch, value):
    """A budget a caller can raise is not a budget.

    The paired negative to the test above: the same environment variable that
    permits a stricter run must refuse a looser one, or the approval means
    nothing and the larger number is the unverified one.
    """
    monkeypatch.setenv("E5_CONTEXT_BUDGET_TOKENS", value)

    with pytest.raises(ValueError, match="approved budget|must be in"):
        budget.context_budget_tokens()


def test_reserved_output_is_taken_out_of_the_same_window():
    """Input and output share one window; a stage may not spend it twice."""
    assert budget.prompt_budget_tokens(2048) == 20480 - 2048

    with pytest.raises(ValueError, match="leaves no room"):
        budget.prompt_budget_tokens(budget.APPROVED_CONTEXT_BUDGET_TOKENS)


def test_a_recorded_bound_says_how_it_was_counted():
    """An estimate later read as a measurement is how a budget stops meaning anything."""
    described = budget.describe_budget(budget.CharacterRatioEstimator(), 1024)

    assert described["counting_method"] == "character-ratio-estimate"
    assert described["prompt_budget_tokens"] == 20480 - 1024
    # Provenance travels with the number, so a reader of a stored run record does
    # not have to know which environment produced it.
    assert described["verified_context_tokens"] == 8192
    assert described["tokenizer_revision"] == budget.TOKENIZER_REVISION
    assert "PR #39" in described["budget_authority"]
    assert json.loads(json.dumps(described)) == described


def _snapshot(directory: Path, tokenizer_json: bytes, config_json: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "tokenizer.json").write_bytes(tokenizer_json)
    (directory / "tokenizer_config.json").write_bytes(config_json)
    return directory


def test_a_snapshot_whose_hash_does_not_match_is_refused(tmp_path):
    """A near-miss tokenizer is the dangerous case, not a missing one.

    A tokenizer that differs slightly from the one the benchmark measured
    produces counts that disagree with the server exactly at the boundary the
    budget defends, and nothing reports it — the numbers are simply wrong by a
    little.
    """
    snapshot = _snapshot(tmp_path / "wrong", b'{"not": "the pinned tokenizer"}', b"{}")

    with pytest.raises(ValueError, match="not the tokenizer the serving benchmark measured"):
        budget.verify_tokenizer_snapshot(snapshot)


def test_a_snapshot_missing_a_file_is_named_rather_than_guessed(tmp_path):
    snapshot = tmp_path / "partial"
    snapshot.mkdir()
    (snapshot / "tokenizer_config.json").write_bytes(b"{}")

    # Named with its path: a snapshot directory that exists but is incomplete
    # otherwise fails as an opaque hash mismatch on whichever file is checked
    # first, which points at the wrong problem.
    with pytest.raises(FileNotFoundError, match="tokenizer.json"):
        budget.verify_tokenizer_snapshot(snapshot)


def test_verification_accepts_the_pinned_hashes(tmp_path, monkeypatch):
    """The paired positive: the check must pass on matching content.

    Content matching the real snapshot is not in the repository, so the pins are
    redirected at the two bytes this test writes. That keeps the comparison
    itself under test — a checker that rejected everything would pass the
    negative cases above and still be broken.
    """
    tokenizer_json, config_json = b'{"pinned": true}', b'{"pinned": "config"}'
    monkeypatch.setattr(
        budget, "TOKENIZER_JSON_SHA256", hashlib.sha256(tokenizer_json).hexdigest()
    )
    monkeypatch.setattr(
        budget, "TOKENIZER_CONFIG_SHA256", hashlib.sha256(config_json).hexdigest()
    )
    snapshot = _snapshot(tmp_path / "right", tokenizer_json, config_json)

    budget.verify_tokenizer_snapshot(snapshot)


def test_a_machine_without_the_snapshot_still_bounds_payloads(monkeypatch, tmp_path):
    """Fallback bounds the payload; it never claims to have measured it."""
    monkeypatch.setenv(budget.TOKENIZER_SNAPSHOT_ENV, str(tmp_path / "absent"))

    counter = budget.resolve_counter()

    assert counter.method == "character-ratio-estimate"
    assert counter.count("hello world") > 0
    # Monotonic in length, which is all the fill loops require of it.
    assert counter.count("x" * 400) > counter.count("x" * 40)


def test_the_fallback_is_never_silent_about_being_a_fallback(monkeypatch, tmp_path):
    """The failure to avoid is an estimate that reaches a run record unlabelled."""
    monkeypatch.setenv(budget.TOKENIZER_SNAPSHOT_ENV, str(tmp_path / "absent"))

    described = budget.describe_budget(budget.resolve_counter(), 2048)

    assert described["counting_method"] != "tokenizer"
