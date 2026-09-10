"""L2-001..004 shipped path tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from specstyle.domain.enums import RuleStatus
from specstyle.domain.identifiers import ArtifactId, Sha256
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes
from specstyle.verification.l2.batch_consistency import evaluate_batch_consistency
from specstyle.verification.l2.encoder import (
    EncoderPin,
    FakeStyleEncoder,
    FeatureCache,
    encode_with_cache,
)
from specstyle.verification.l2.fidelity import evaluate_style_fidelity
from specstyle.verification.l2.metrics import cosine_similarity
from specstyle.verification.l2.threshold_profile import (
    MetricThreshold,
    ThresholdProfile,
    dump_threshold_profile,
    load_threshold_profile,
)


def _pin() -> EncoderPin:
    return EncoderPin("style-enc", "r1", "layer0", "prep1")


def _sha(ch: str = "a") -> Sha256:
    return Sha256((ch if ch in "0123456789abcdef" else "a") * 64)


class _HostileString(str):
    def __eq__(self, _other: object) -> bool:
        return True

    __hash__ = str.__hash__


def _profile(**kwargs) -> ThresholdProfile:
    base = dict(
        profile_id="p1",
        revision="r1",
        status="VALIDATED",
        style_pack_id="s1",
        domain_profile="product_instance",
        encoder_id="style-enc",
        encoder_revision="r1",
        preprocessing_version="prep1",
        calibration_dataset_sha256=_sha("c"),
        validation_dataset_sha256=_sha("d"),
        thresholds=(
            MetricThreshold("reference_style_fidelity_min", "gte", 0.0),
            MetricThreshold("batch_style_dispersion_max", "lte", 2.0),
        ),
    )
    base.update(kwargs)
    return ThresholdProfile(**base)


def test_encoder_cache_hit_and_miss_on_pin_change(tmp_path: Path) -> None:
    enc = FakeStyleEncoder(_pin())
    cache = FeatureCache(tmp_path)
    data = b"\x89PNG-fake"
    h = hash_bytes(data)
    f1 = encode_with_cache(enc, cache, data, h)
    f2 = encode_with_cache(enc, cache, data, h)
    assert f1.vector == f2.vector
    other = FakeStyleEncoder(EncoderPin("style-enc", "r2", "layer0", "prep1"))
    f3 = encode_with_cache(other, cache, data, h)
    assert f3.vector != f1.vector or f3.pin.revision == "r2"


def test_threshold_profile_roundtrip_and_required() -> None:
    profile = _profile()
    raw = dump_threshold_profile(profile)
    loaded = load_threshold_profile(raw)
    assert loaded.status == "VALIDATED"
    loaded.require_for_gate()
    draft = _profile(status="DRAFT")
    try:
        draft.require_for_gate()
        raise AssertionError("expected DomainError")
    except Exception as exc:
        assert "VALIDATED" in str(exc)


@pytest.mark.parametrize(
    "status",
    [
        pytest.param("UNKNOWN", id="unknown"),
        pytest.param("CALIBRATED", id="calibrated"),
        pytest.param(_HostileString("UNKNOWN"), id="hostile-subclass"),
    ],
)
def test_threshold_profile_rejects_noncanonical_status(status: object) -> None:
    with pytest.raises(DomainError, match="invalid threshold status"):
        _profile(status=status)


@pytest.mark.parametrize(
    "operator",
    [
        pytest.param("unknown", id="unknown"),
        pytest.param(_HostileString("unknown"), id="hostile-subclass"),
    ],
)
def test_metric_threshold_rejects_noncanonical_operator(operator: object) -> None:
    with pytest.raises(DomainError, match="invalid metric operator"):
        MetricThreshold("reference_style_fidelity_min", operator, 0.0)


def test_fidelity_empty_refs_unverifiable() -> None:
    enc = FakeStyleEncoder(_pin())
    out = enc.encode(b"img", _sha("1"))
    result = evaluate_style_fidelity(ArtifactId("a1"), out, (), _profile())
    assert result.status is RuleStatus.UNVERIFIABLE


@pytest.mark.parametrize(
    ("threshold_value", "expected_status"),
    [(0.0, RuleStatus.PASS), (2.0, RuleStatus.FAIL)],
)
def test_validated_profile_applies_fidelity_threshold(
    threshold_value: float, expected_status: RuleStatus
) -> None:
    enc = FakeStyleEncoder(_pin())
    feat = enc.encode(b"same", _sha("2"))
    profile = _profile(
        thresholds=(
            MetricThreshold("reference_style_fidelity_min", "gte", threshold_value),
        )
    )

    result = evaluate_style_fidelity(ArtifactId("a1"), feat, (feat,), profile)

    assert result.status is expected_status
    assert result.score is not None
    assert cosine_similarity(feat, feat) > 0.99


@pytest.mark.parametrize("threshold_value", [0.0, 2.0])
def test_draft_profile_cannot_gate_reliable_fidelity_score(
    threshold_value: float,
) -> None:
    enc = FakeStyleEncoder(_pin())
    feat = enc.encode(b"same", _sha("2"))
    profile = _profile(
        status="DRAFT",
        thresholds=(
            MetricThreshold("reference_style_fidelity_min", "gte", threshold_value),
        ),
    )

    result = evaluate_style_fidelity(ArtifactId("a1"), feat, (feat,), profile)

    assert result.status is RuleStatus.UNVERIFIABLE
    assert result.score is not None


def test_batch_consistency_outlier_affected_ids() -> None:
    enc = FakeStyleEncoder(_pin())
    a = enc.encode(b"aaa", _sha("1"))
    b = enc.encode(b"aaa", _sha("1"))  # same bytes → same vector
    # force far vector
    from specstyle.verification.l2.encoder import StyleFeature

    far = StyleFeature(tuple(1.0 for _ in a.vector), a.pin, _sha("9"))
    items = (
        (ArtifactId("i1"), a),
        (ArtifactId("i2"), b),
        (ArtifactId("i3"), far),
    )
    result = evaluate_batch_consistency(
        items,
        _profile(
            thresholds=(MetricThreshold("batch_style_dispersion_max", "lte", 0.01),)
        ),
    )
    assert result.status is RuleStatus.FAIL
    # Gate affected = full ordered cohort (report/routing invariant)
    assert result.affected_artifact_ids == (
        ArtifactId("i1"),
        ArtifactId("i2"),
        ArtifactId("i3"),
    )
    from specstyle.verification.l2.batch_consistency import batch_outlier_ids

    outliers = batch_outlier_ids(
        items,
        _profile(
            thresholds=(MetricThreshold("batch_style_dispersion_max", "lte", 0.01),)
        ),
    )
    assert ArtifactId("i3") in outliers


def test_nan_feature_rejected_by_style_feature() -> None:
    from specstyle.verification.l2.encoder import StyleFeature

    with pytest.raises(DomainError):
        StyleFeature((1.0, float("nan")), _pin(), _sha("1"))


def test_revoked_profile_fails_fidelity() -> None:
    enc = FakeStyleEncoder(_pin())
    feat = enc.encode(b"x", _sha("2"))
    result = evaluate_style_fidelity(
        ArtifactId("a1"),
        feat,
        (feat,),
        _profile(
            status="REVOKED",
            thresholds=(MetricThreshold("batch_style_dispersion_max", "lte", 2.0),),
        ),
    )
    assert result.status is RuleStatus.FAIL
    assert result.score is not None


def test_batch_permutation_stable_outliers() -> None:
    from specstyle.verification.l2.encoder import StyleFeature

    enc = FakeStyleEncoder(_pin())
    a = enc.encode(b"aaa", _sha("1"))
    far = StyleFeature(tuple(1.0 for _ in a.vector), a.pin, _sha("9"))
    order1 = (
        (ArtifactId("i1"), a),
        (ArtifactId("i3"), far),
        (ArtifactId("i2"), a),
    )
    order2 = (
        (ArtifactId("i3"), far),
        (ArtifactId("i2"), a),
        (ArtifactId("i1"), a),
    )
    thr = _profile(
        thresholds=(MetricThreshold("batch_style_dispersion_max", "lte", 0.01),)
    )
    r1 = evaluate_batch_consistency(order1, thr)
    r2 = evaluate_batch_consistency(order2, thr)
    assert r1.status is RuleStatus.FAIL and r2.status is RuleStatus.FAIL
    # Full cohort in input order for each call
    assert r1.affected_artifact_ids == tuple(a for a, _ in order1)
    assert r2.affected_artifact_ids == tuple(a for a, _ in order2)
    from specstyle.verification.l2.batch_consistency import batch_outlier_ids

    assert set(batch_outlier_ids(order1, thr)) == set(batch_outlier_ids(order2, thr))


def test_batch_revoked_and_draft_not_pass() -> None:
    enc = FakeStyleEncoder(_pin())
    a = enc.encode(b"a", _sha("1"))
    items = ((ArtifactId("i1"), a),)
    revoked = evaluate_batch_consistency(items, _profile(status="REVOKED"))
    assert revoked.status is RuleStatus.FAIL
    draft = evaluate_batch_consistency(items, _profile(status="DRAFT"))
    assert draft.status is RuleStatus.UNVERIFIABLE


def test_concurrent_cache_puts_no_corrupt(tmp_path: Path) -> None:
    import concurrent.futures

    enc = FakeStyleEncoder(_pin())
    cache = FeatureCache(tmp_path)
    data = b"concurrent-img"
    h = hash_bytes(data)

    def worker(_: int):
        return encode_with_cache(enc, cache, data, h).vector

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        vectors = list(pool.map(worker, range(16)))
    assert all(v == vectors[0] for v in vectors)
    # readable after concurrent writes
    hit = cache.get(_pin(), h)
    assert hit is not None
    assert hit.vector == vectors[0]
