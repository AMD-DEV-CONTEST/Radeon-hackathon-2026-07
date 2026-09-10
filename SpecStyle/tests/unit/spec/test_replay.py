"""SPEC-005 replay assessment tests for contracts section 14.5."""

from __future__ import annotations

import pytest

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.spec.migrations import migrate_style_spec
from specstyle.spec.models import StyleSpecV1, StyleSpecV11
from specstyle.spec.replay import (
    NewBatchReplayRequest,
    SameInputReplayRequest,
    assess_new_batch_replay,
    assess_same_input_replay,
)
from tests.unit.spec.test_models import _valid_spec


def _sha(ch: str = "a") -> Sha256:
    # Sha256 accepts only hexadecimal; fill tests with one character from 0-9a-f.
    if ch not in "0123456789abcdef":
        ch = "a"
    return Sha256(ch * 64)


def _same(
    spec: StyleSpecV1 | StyleSpecV11,
    *,
    env_candidate: Sha256 | None = None,
    seed_candidate: int | None = None,
    compiled_candidate: Sha256 | None = None,
) -> SameInputReplayRequest:
    env = _sha("e")
    return SameInputReplayRequest(
        spec,
        _sha("c"),
        _sha("1"),
        (_sha("2"),),
        _sha("3"),
        7,
        _sha("4"),
        env,
        compiled_candidate or _sha("c"),
        _sha("1"),
        (_sha("2"),),
        _sha("3"),
        7 if seed_candidate is None else seed_candidate,
        _sha("4"),
        env if env_candidate is None else env_candidate,
    )


def test_same_input_exact() -> None:
    spec = StyleSpecV1(**_valid_spec())
    result = assess_same_input_replay(_same(spec))
    assert result.status == "EXACT"
    assert result.mode == "same_input"
    assert result.reasons == ()


def test_same_input_advisory_env_diff_is_compatible() -> None:
    v1 = StyleSpecV1(**_valid_spec())
    v11 = migrate_style_spec(v1, "1.1").target_spec
    result = assess_same_input_replay(_same(v11, env_candidate=_sha("z")))
    assert result.status == "COMPATIBLE"
    assert "environment_fingerprint_differs" in result.reasons


def test_same_input_strict_env_diff_rejected() -> None:
    from specstyle.spec.migrations import _list_to_tuple

    v1 = StyleSpecV1(**_valid_spec())
    base = migrate_style_spec(v1, "1.1").target_spec.model_dump(mode="json")
    base["replay_contract"]["environment_policy"] = "strict"
    strict = StyleSpecV11(**_list_to_tuple(base))
    result = assess_same_input_replay(_same(strict, env_candidate=_sha("f")))
    assert result.status == "REJECTED"
    assert "environment_fingerprint_mismatch" in result.reasons


def test_same_input_content_mismatch_rejected() -> None:
    spec = StyleSpecV1(**_valid_spec())
    result = assess_same_input_replay(_same(spec, seed_candidate=9))
    assert result.status == "REJECTED"
    assert "seed_mismatch" in result.reasons
    result2 = assess_same_input_replay(_same(spec, compiled_candidate=_sha("x")))
    assert result2.status == "REJECTED"
    assert "compiled_spec_hash_mismatch" in result2.reasons


def test_new_batch_compatible() -> None:
    spec = StyleSpecV1(**_valid_spec())
    req = NewBatchReplayRequest(
        spec,
        _sha("1"),
        _sha("2"),
        "per_asset_deterministic",
        _sha("1"),
        _sha("2"),
        "per_asset_deterministic",
        (_sha("3"), _sha("4")),
    )
    result = assess_new_batch_replay(req)
    assert result.status == "COMPATIBLE"
    assert result.mode == "new_batch"


def test_new_batch_rejects_empty_or_pin_mismatch() -> None:
    spec = StyleSpecV1(**_valid_spec())
    empty = NewBatchReplayRequest(
        spec,
        _sha("1"),
        _sha("2"),
        "per_asset_deterministic",
        _sha("1"),
        _sha("2"),
        "per_asset_deterministic",
        (),
    )
    assert assess_new_batch_replay(empty).status == "REJECTED"
    mismatch = NewBatchReplayRequest(
        spec,
        _sha("1"),
        _sha("2"),
        "per_asset_deterministic",
        _sha("9"),
        _sha("2"),
        "per_asset_deterministic",
        (_sha("3"),),
    )
    assert assess_new_batch_replay(mismatch).status == "REJECTED"


def test_replay_does_not_mutate_request_objects() -> None:
    spec = StyleSpecV1(**_valid_spec())
    req = _same(spec)
    before = (
        req.compiled_spec_hash,
        req.seed,
        req.style_reference_hashes,
    )
    assess_same_input_replay(req)
    assert (
        req.compiled_spec_hash,
        req.seed,
        req.style_reference_hashes,
    ) == before


def test_invalid_request_types_rejected() -> None:
    with pytest.raises(DomainError, match="invalid replay request"):
        assess_same_input_replay(object())  # type: ignore[arg-type]
