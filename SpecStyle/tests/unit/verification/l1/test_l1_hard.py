"""L1-001 hard rules: decode, dimensions, pixels — drive shipped entry points."""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image, PngImagePlugin

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import RuleStatus
from specstyle.domain.identifiers import ArtifactId
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes
from specstyle.verification.l1.decode import decode_png_bytes, rule_decode
from specstyle.verification.l1.dimensions import check_dimensions
from specstyle.verification.l1.pixels import check_pixels
from specstyle.verification.l1.verifier import L1HardVerifier, l1_hard_rule_definitions
from specstyle.verification.protocols import run_verifier


def _png(color: tuple[int, int, int], size: tuple[int, int] = (32, 32)) -> bytes:
    image = Image.new("RGB", size, color)
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _aid(name: str = "art1") -> ArtifactId:
    return ArtifactId(name)


def test_decode_rejects_empty_and_corrupt() -> None:
    aid = _aid()
    assert rule_decode(aid, b"").status is RuleStatus.FAIL
    assert rule_decode(aid, b"not-a-png").status is RuleStatus.FAIL
    with pytest.raises(DomainError):
        decode_png_bytes(b"")


def test_decode_rejects_rgba_transparency() -> None:
    image = Image.new("RGBA", (16, 16), (10, 20, 30, 128))
    buf = BytesIO()
    image.save(buf, format="PNG")
    result = rule_decode(_aid(), buf.getvalue())
    assert result.status is RuleStatus.FAIL


def test_decode_accepts_rgb() -> None:
    data = _png((10, 20, 30))
    result = rule_decode(_aid(), data)
    assert result.status is RuleStatus.PASS
    decoded = decode_png_bytes(data)
    assert decoded.size == (32, 32)
    assert decoded.n_frames == 1


@pytest.mark.parametrize("image_format", ("JPEG", "WEBP"))
def test_decode_rejects_real_non_png_images(image_format: str) -> None:
    image = Image.new("RGB", (16, 16), (10, 20, 30))
    encoded = BytesIO()
    image.save(encoded, format=image_format)

    with pytest.raises(DomainError):
        decode_png_bytes(encoded.getvalue())
    assert rule_decode(_aid(), encoded.getvalue()).status is RuleStatus.FAIL


def test_decode_rejects_non_rgb_png() -> None:
    encoded = BytesIO()
    Image.new("L", (16, 16), 128).save(encoded, format="PNG")

    with pytest.raises(DomainError):
        decode_png_bytes(encoded.getvalue())
    assert rule_decode(_aid(), encoded.getvalue()).status is RuleStatus.FAIL


@pytest.mark.parametrize("metadata_kind", ("text", "icc"))
def test_decode_rejects_png_with_metadata(metadata_kind: str) -> None:
    encoded = BytesIO()
    image = Image.new("RGB", (16, 16), (10, 20, 30))
    if metadata_kind == "text":
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("comment", "metadata must be rejected")
        image.save(encoded, format="PNG", pnginfo=metadata)
    else:
        image.save(encoded, format="PNG", icc_profile=b"test-icc-profile")

    with Image.open(BytesIO(encoded.getvalue())) as decoded:
        assert decoded.info
    with pytest.raises(DomainError):
        decode_png_bytes(encoded.getvalue())
    assert rule_decode(_aid(), encoded.getvalue()).status is RuleStatus.FAIL


def test_dimensions_exact_match_and_fail() -> None:
    data = _png((1, 2, 3), (64, 48))
    aid = _aid()
    assert check_dimensions(aid, data, (64, 48)).status is RuleStatus.PASS
    assert check_dimensions(aid, data, (64, 64)).status is RuleStatus.FAIL


def test_pixels_reject_all_black_white_and_tiny() -> None:
    aid = _aid()
    assert check_pixels(aid, _png((0, 0, 0))).status is RuleStatus.FAIL
    assert check_pixels(aid, _png((255, 255, 255))).status is RuleStatus.FAIL
    assert check_pixels(aid, _png((5, 5, 5), (4, 4))).status is RuleStatus.FAIL
    assert check_pixels(aid, _png((10, 20, 30))).status is RuleStatus.PASS


def test_l1_verifier_via_run_verifier_entry() -> None:
    data = _png((40, 50, 60), (32, 32))
    aid = _aid("ok")
    ref = ArtifactRef(aid, hash_bytes(data))
    verifier = L1HardVerifier({aid: data}, (32, 32))
    rules = l1_hard_rule_definitions()
    results = run_verifier(verifier, (ref,), rules)
    assert len(results) == 3
    assert all(r.status is RuleStatus.PASS for r in results)
    assert all(r.affected_artifact_ids == (aid,) for r in results)


def test_l1_verifier_missing_content_unverifiable() -> None:
    aid = _aid("missing")
    ref = ArtifactRef(aid, hash_bytes(b"abc"))
    verifier = L1HardVerifier({}, (32, 32))
    results = run_verifier(verifier, (ref,), l1_hard_rule_definitions())
    assert all(r.status is RuleStatus.UNVERIFIABLE for r in results)


def test_results_deterministic() -> None:
    data = _png((7, 8, 9), (16, 16))
    aid = _aid()
    a = check_pixels(aid, data)
    b = check_pixels(aid, data)
    assert a == b


def test_decode_rejects_multi_frame_gif() -> None:
    """Multi-frame must hard-fail via shipped rule_decode (not aesthetic)."""
    frames = [Image.new("RGB", (16, 16), c) for c in ((10, 0, 0), (0, 10, 0))]
    buf = BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )
    data = buf.getvalue()
    with pytest.raises(DomainError, match="MULTI_FRAME"):
        decode_png_bytes(data)
    assert rule_decode(_aid(), data).status is RuleStatus.FAIL


def test_low_contrast_not_hard_fail_on_pixels() -> None:
    """Style-like low contrast must not be an L1 hard fail, per the handoff."""
    # near-uniform gray but not pure black/white
    data = _png((40, 41, 42), (32, 32))
    assert check_pixels(_aid(), data).status is RuleStatus.PASS


def test_l1_verifier_wrong_dimensions_fail_not_pass() -> None:
    data = _png((1, 2, 3), (32, 32))
    aid = _aid("dim")
    ref = ArtifactRef(aid, hash_bytes(data))
    verifier = L1HardVerifier({aid: data}, (64, 64))
    results = run_verifier(verifier, (ref,), l1_hard_rule_definitions())
    by_rule = {r.rule_id.value: r for r in results}
    assert by_rule["L1_DIMENSIONS"].status is RuleStatus.FAIL
    assert by_rule["L1_DIMENSIONS"].affected_artifact_ids == (aid,)
