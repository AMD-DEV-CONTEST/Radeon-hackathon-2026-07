from io import BytesIO
import warnings

import pytest
from PIL import Image, PngImagePlugin, UnidentifiedImageError

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.identifiers import AssetId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.preprocess import (
    PreparedImage,
    PreprocessPlan,
    preprocess_image,
)
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import ResourcePin


def _encoded(
    mode: str = "RGB", size: tuple[int, int] = (101, 100), **save: object
) -> bytes:
    color: object = (
        (128, 127) if mode == "LA" else (255, 0, 0, 127) if mode == "RGBA" else 128
    )
    image = Image.new(mode, size, color)
    result = BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        image.save(
            result,
            format="JPEG" if mode == "CMYK" else "TIFF" if mode == "F" else "PNG",
            **save,
        )
    return result.getvalue()


def _encoded_as(image: Image.Image, image_format: str, **save: object) -> bytes:
    result = BytesIO()
    image.save(result, image_format, **save)
    return result.getvalue()


def _plan(mode: str = "contain_pad") -> PreprocessPlan:
    return PreprocessPlan(
        (64, 64), mode, (1, 2, 3), ResourcePin("processor", "r1", Sha256("a" * 64))
    )


def _source(content: bytes) -> AssetRef:
    return AssetRef(AssetId("source"), hash_bytes(content))


@pytest.mark.parametrize(
    ("size", "padding_pixel"),
    (((101, 100), (0, 63)), ((100, 101), (63, 0))),
)
def test_preprocess_normalizes_to_rgb_png_and_puts_odd_contain_padding_on_right_or_bottom(
    size: tuple[int, int], padding_pixel: tuple[int, int]
) -> None:
    encoded = _encoded(size=size)
    prepared = preprocess_image(encoded, _source(encoded), _plan())
    assert (prepared.width, prepared.height, prepared.mode, prepared.format) == (
        64,
        64,
        "RGB",
        "PNG",
    )
    with Image.open(BytesIO(prepared.content)) as image:
        assert image.getpixel(padding_pixel) == (1, 2, 3)
        assert image.info == {}


@pytest.mark.parametrize("mode", ("1", "L", "LA", "P", "RGB", "RGBA", "CMYK"))
def test_preprocess_accepts_contract_modes(mode: str) -> None:
    encoded = _encoded(mode)
    assert preprocess_image(encoded, _source(encoded), _plan()).mode == "RGB"


@pytest.mark.parametrize("mode", ("I", "I;16", "F"))
def test_preprocess_rejects_noncontract_modes(mode: str) -> None:
    encoded = _encoded(mode)
    with pytest.raises(DomainError):
        preprocess_image(encoded, _source(encoded), _plan())


@pytest.mark.parametrize("orientation", range(1, 9))
def test_preprocess_records_each_valid_exif_orientation(orientation: int) -> None:
    exif = Image.Exif()
    exif[274] = orientation
    encoded = _encoded(exif=exif.tobytes())
    assert (
        preprocess_image(encoded, _source(encoded), _plan()).snapshot.exif_orientation
        == orientation
    )


@pytest.mark.parametrize(
    ("orientation", "top_left"),
    (
        (1, (255, 0, 0)),
        (2, (0, 0, 255)),
        (3, (255, 255, 0)),
        (4, (0, 255, 0)),
        (5, (255, 0, 0)),
        (6, (0, 255, 0)),
        (7, (255, 255, 0)),
        (8, (0, 0, 255)),
    ),
)
def test_preprocess_applies_each_exif_orientation_to_pixels(
    orientation: int, top_left: tuple[int, int, int]
) -> None:
    image = Image.new("RGB", (64, 64), "black")
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((63, 0), (0, 0, 255))
    image.putpixel((0, 63), (0, 255, 0))
    image.putpixel((63, 63), (255, 255, 0))
    exif = Image.Exif()
    exif[274] = orientation
    encoded = _encoded_as(image, "PNG", exif=exif.tobytes())

    prepared = preprocess_image(encoded, _source(encoded), _plan())
    with Image.open(BytesIO(prepared.content)) as normalized:
        assert normalized.getpixel((0, 0)) == top_left


@pytest.mark.parametrize("value", (0, 9))
def test_preprocess_rejects_invalid_exif_orientation(value: object) -> None:
    exif = Image.Exif()
    exif[274] = value
    encoded = _encoded(exif=exif.tobytes())
    with pytest.raises(DomainError):
        preprocess_image(encoded, _source(encoded), _plan())


def test_preprocess_rejects_hash_mismatch_and_non_bytes() -> None:
    encoded = _encoded()
    with pytest.raises(DomainError):
        preprocess_image(
            encoded, AssetRef(AssetId("source"), Sha256("b" * 64)), _plan()
        )
    with pytest.raises(DomainError):
        preprocess_image(bytearray(encoded), _source(encoded), _plan())  # type: ignore[arg-type]


@pytest.mark.parametrize("chunk", ("tEXt", "zTXt", "iTXt"))
def test_prepared_image_rejects_any_png_text_metadata(chunk: str) -> None:
    clean = _encoded(size=(64, 64))
    prepared = preprocess_image(clean, _source(clean), _plan())
    info = PngImagePlugin.PngInfo()
    if chunk == "iTXt":
        info.add_itxt("credential", "secret")
    elif chunk == "zTXt":
        info.add_text("credential", "secret", zip=True)
    else:
        info.add_text("credential", "secret")
    altered = BytesIO()
    Image.open(BytesIO(prepared.content)).save(altered, "PNG", pnginfo=info)
    with pytest.raises(DomainError):
        type(prepared)(prepared.source, altered.getvalue(), prepared.snapshot)


def test_preprocess_rejects_forged_nested_source_and_nonexact_literals() -> None:
    encoded = _encoded(size=(64, 64))
    prepared = preprocess_image(encoded, _source(encoded), _plan())
    object.__setattr__(prepared.source, "sha256", "forged")
    with pytest.raises(DomainError):
        type(prepared)(prepared.source, prepared.content, prepared.snapshot)

    class Text(str):
        pass

    with pytest.raises(DomainError):
        PreprocessPlan((64, 64), Text("contain_pad"), (0, 0, 0), _plan().processor_pin)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("failure", "error_type"),
    (
        (
            MemoryError("secret"),
            __import__(
                "specstyle.errors", fromlist=["InfrastructureError"]
            ).InfrastructureError,
        ),
        (
            RuntimeError("secret"),
            __import__(
                "specstyle.errors", fromlist=["InfrastructureError"]
            ).InfrastructureError,
        ),
    ),
)
def test_preprocess_wraps_transform_failures_without_leaking_input(
    monkeypatch: pytest.MonkeyPatch, failure: Exception, error_type: type[Exception]
) -> None:
    encoded = _encoded(size=(64, 64))

    def fail(
        image: Image.Image, orientation: int, images: list[Image.Image]
    ) -> Image.Image:
        raise failure

    monkeypatch.setattr("specstyle.generation.preprocess._apply_orientation", fail)
    with pytest.raises(error_type) as raised:
        preprocess_image(encoded, _source(encoded), _plan())
    assert "secret" not in str(raised.value)


@pytest.mark.parametrize(
    ("failure", "error_type"),
    (
        (DomainError("primary failure"), DomainError),
        (InfrastructureError("primary failure"), InfrastructureError),
        (MemoryError("primary failure"), InfrastructureError),
        (RuntimeError("primary failure"), InfrastructureError),
    ),
)
def test_preprocess_does_not_allow_close_failure_to_mask_primary_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    error_type: type[Exception],
) -> None:
    encoded = _encoded(size=(64, 64))

    def fail_transform(
        image: Image.Image, orientation: int, images: list[Image.Image]
    ) -> Image.Image:
        raise failure

    original_close = Image.Image.close
    calls = 0

    def fail_close(image: Image.Image) -> None:
        nonlocal calls
        calls += 1
        if calls > 2:
            raise RuntimeError("close sentinel")
        original_close(image)

    monkeypatch.setattr(
        "specstyle.generation.preprocess._apply_orientation", fail_transform
    )
    monkeypatch.setattr(Image.Image, "close", fail_close)
    with pytest.raises(error_type) as raised:
        preprocess_image(encoded, _source(encoded), _plan())
    assert "close sentinel" not in str(raised.value)


def test_preprocess_maps_decompression_bomb_warning_to_domain_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = _encoded(size=(64, 64))

    def warn_bomb(value: object) -> Image.Image:
        warnings.warn("bomb sentinel", Image.DecompressionBombWarning)
        raise AssertionError("warning must be raised as an error")

    monkeypatch.setattr("specstyle.generation.preprocess.Image.open", warn_bomb)
    with pytest.raises(DomainError, match="invalid input image"):
        preprocess_image(encoded, _source(encoded), _plan())


def test_prepared_image_maps_output_close_failure_without_leaking_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = _encoded(size=(64, 64))
    prepared = preprocess_image(encoded, _source(encoded), _plan())

    def fail_close(image: Image.Image) -> None:
        raise RuntimeError("close sentinel")

    monkeypatch.setattr(Image.Image, "close", fail_close)
    with pytest.raises(InfrastructureError) as raised:
        PreparedImage(prepared.source, prepared.content, prepared.snapshot)
    assert "close sentinel" not in str(raised.value)


@pytest.mark.parametrize("image_format", ("JPEG", "WEBP"))
def test_preprocess_accepts_real_jpeg_and_webp(image_format: str) -> None:
    encoded = _encoded_as(Image.new("RGB", (64, 64), "red"), image_format)

    prepared = preprocess_image(encoded, _source(encoded), _plan())

    assert prepared.snapshot.input_format == image_format
    assert prepared.format == "PNG"


def test_preprocess_rejects_animated_input() -> None:
    output = BytesIO()
    first = Image.new("RGB", (64, 64), "red")
    first.save(
        output,
        "WEBP",
        save_all=True,
        append_images=[Image.new("RGB", (64, 64), "blue")],
        duration=100,
    )
    encoded = output.getvalue()
    with Image.open(BytesIO(encoded)) as animated:
        assert (animated.format, animated.n_frames) == ("WEBP", 2)

    with pytest.raises(DomainError, match="single-frame"):
        preprocess_image(encoded, _source(encoded), _plan())


@pytest.mark.parametrize(
    "invalid_output",
    (
        b"not a PNG",
        _encoded(size=(65, 64)),
        _encoded_as(
            Image.new("RGB", (64, 64), "red"),
            "PNG",
            pnginfo=(lambda info: (info.add_text("secret", "metadata"), info)[1])(
                PngImagePlugin.PngInfo()
            ),
        ),
    ),
)
def test_preprocess_revalidates_encoded_output(
    monkeypatch: pytest.MonkeyPatch, invalid_output: bytes
) -> None:
    encoded = _encoded(size=(64, 64))
    monkeypatch.setattr(
        "specstyle.generation.preprocess._encode_png", lambda image: invalid_output
    )

    with pytest.raises(DomainError):
        preprocess_image(encoded, _source(encoded), _plan())


def test_preprocess_checks_exif_before_verify_and_load_on_each_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class OrderedImage:
        format = "PNG"
        mode = "RGB"
        n_frames = 1
        size = (64, 64)
        info: dict[str, object] = {}

        def __init__(self, name: str) -> None:
            self.name = name

        def verify(self) -> None:
            events.append(f"{self.name}.verify")

        def load(self) -> None:
            events.append(f"{self.name}.load")
            raise OSError("controlled stop")

        def close(self) -> None:
            return None

    opened = 0

    def open_image(value: object) -> OrderedImage:
        nonlocal opened
        opened += 1
        return OrderedImage(str(opened))

    monkeypatch.setattr("specstyle.generation.preprocess.Image.open", open_image)
    encoded = _encoded(size=(64, 64))
    with pytest.raises(DomainError, match="invalid input image"):
        preprocess_image(encoded, _source(encoded), _plan())

    assert events == ["1.verify", "2.load"]


def test_preprocess_parses_real_png_exif_without_getexif_and_opens_exactly_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exif = Image.Exif()
    exif[274] = 6
    encoded = _encoded(exif=exif.tobytes())
    with Image.open(BytesIO(encoded)) as original:
        assert (original.format, original.info.get("exif")) == ("PNG", exif.tobytes())

    events: list[str] = []
    input_opens = 0
    output_opens = 0
    original_open = Image.open
    original_verify = PngImagePlugin.PngImageFile.verify
    original_load = PngImagePlugin.PngImageFile.load

    def counted_open(*args: object, **kwargs: object) -> Image.Image:
        nonlocal input_opens, output_opens
        payload = args[0].getvalue() if type(args[0]) is BytesIO else None
        if payload == encoded:
            input_opens += 1
            events.append("input.open")
        else:
            output_opens += 1
            events.append("output.open")
        return original_open(*args, **kwargs)

    def tracked_verify(image: Image.Image) -> None:
        events.append("verify")
        original_verify(image)

    def tracked_load(image: Image.Image) -> object:
        events.append("load")
        return original_load(image)

    def forbidden_getexif(image: Image.Image) -> object:
        raise AssertionError("getexif must not be called")

    monkeypatch.setattr("specstyle.generation.preprocess.Image.open", counted_open)
    monkeypatch.setattr(PngImagePlugin.PngImageFile, "verify", tracked_verify)
    monkeypatch.setattr(PngImagePlugin.PngImageFile, "load", tracked_load)
    monkeypatch.setattr(Image.Image, "getexif", forbidden_getexif)

    prepared = preprocess_image(encoded, _source(encoded), _plan())

    assert prepared.snapshot.exif_orientation == 6
    assert events[:4] == ["input.open", "verify", "input.open", "load"]
    assert (input_opens, output_opens) == (2, 1)


def test_preprocess_rejects_verify_runtime_error_without_png_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = _encoded(size=(64, 64))
    opens = 0
    original_open = Image.open
    original_verify = PngImagePlugin.PngImageFile.verify

    def counted_open(*args: object, **kwargs: object) -> Image.Image:
        nonlocal opens
        opens += 1
        return original_open(*args, **kwargs)

    def fail_first_verify(image: Image.Image) -> None:
        if opens == 1:
            raise RuntimeError("verify sentinel")
        original_verify(image)

    monkeypatch.setattr("specstyle.generation.preprocess.Image.open", counted_open)
    monkeypatch.setattr(PngImagePlugin.PngImageFile, "verify", fail_first_verify)

    with pytest.raises(InfrastructureError, match="image processing failed") as raised:
        preprocess_image(encoded, _source(encoded), _plan())
    assert "verify sentinel" not in str(raised.value)
    assert opens == 1


def test_preprocess_rejects_nonempty_icc_profile() -> None:
    encoded = _encoded_as(
        Image.new("RGB", (64, 64), "red"), "PNG", icc_profile=b"not-a-profile"
    )

    with pytest.raises(DomainError, match="ICC"):
        preprocess_image(encoded, _source(encoded), _plan())


@pytest.mark.parametrize("orientation", (True, "1"))
def test_preprocess_rejects_nonexact_or_out_of_range_exif_orientation(
    monkeypatch: pytest.MonkeyPatch, orientation: object
) -> None:
    exif = Image.Exif()
    exif[274] = 1
    encoded = _encoded(exif=exif.tobytes())

    class InvalidOrientationExif:
        def load(self, value: bytes) -> None:
            return None

        def get(self, key: int, default: object) -> object:
            return orientation

    monkeypatch.setattr(Image, "Exif", InvalidOrientationExif)

    with pytest.raises(DomainError, match="orientation"):
        preprocess_image(encoded, _source(encoded), _plan())


def test_preprocess_composites_transparent_palette_pixel_on_background() -> None:
    image = Image.new("P", (64, 64), 0)
    image.putpalette([255, 0, 0] + [0, 0, 0] * 255)
    image.info["transparency"] = 0
    encoded = _encoded_as(image, "PNG")

    prepared = preprocess_image(encoded, _source(encoded), _plan())
    with Image.open(BytesIO(prepared.content)) as normalized:
        assert normalized.getpixel((0, 0)) == (1, 2, 3)


@pytest.mark.parametrize("mode", ("LA", "RGBA"))
def test_preprocess_composites_alpha_pixel_on_background(mode: str) -> None:
    color: tuple[int, ...] = (255, 0) if mode == "LA" else (255, 0, 0, 0)
    image = Image.new(mode, (64, 64), color)
    encoded = _encoded_as(image, "PNG")

    prepared = preprocess_image(encoded, _source(encoded), _plan())
    with Image.open(BytesIO(prepared.content)) as normalized:
        assert normalized.getpixel((0, 0)) == (1, 2, 3)


@pytest.mark.parametrize("size", ((101, 100), (100, 101)))
def test_preprocess_cover_crops_odd_excess_from_right_and_bottom(
    size: tuple[int, int],
) -> None:
    image = Image.new("RGB", size, "black")
    for x in range(size[0]):
        for y in range(size[1]):
            image.putpixel((x, y), (x, y, 0))
    encoded = _encoded_as(image, "PNG")

    prepared = preprocess_image(encoded, _source(encoded), _plan("cover_center"))
    with Image.open(BytesIO(prepared.content)) as normalized:
        assert normalized.getpixel((0, 0)) == (0, 0, 0)
        assert normalized.getpixel((0, 0)) != normalized.getpixel((63, 63))


def test_preprocess_rejects_real_pillow_decompression_bomb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = _encoded(size=(64, 64))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    with pytest.raises(DomainError, match="invalid input image"):
        preprocess_image(encoded, _source(encoded), _plan())


def test_preprocess_accepts_exact_32_mib_encoded_input() -> None:
    encoded = _encoded(size=(64, 64))
    padded = encoded + b"\0" * (32 * 1024 * 1024 - len(encoded))

    prepared = preprocess_image(padded, _source(padded), _plan())

    assert prepared.width == prepared.height == 64


def test_preprocess_rejects_32_mib_plus_one_encoded_input() -> None:
    encoded = _encoded(size=(64, 64))
    oversized = encoded + b"\0" * (32 * 1024 * 1024 + 1 - len(encoded))

    with pytest.raises(DomainError, match="invalid preprocess input"):
        preprocess_image(oversized, _source(oversized), _plan())


def test_preprocess_rejects_empty_encoded_input() -> None:
    with pytest.raises(DomainError, match="invalid preprocess input"):
        preprocess_image(b"", _source(b""), _plan())


@pytest.mark.parametrize("size", ((16385, 1), (5001, 5000)))
def test_preprocess_rejects_header_limits_before_decode(
    monkeypatch: pytest.MonkeyPatch, size: tuple[int, int]
) -> None:
    class HeaderOnlyImage:
        format = "PNG"
        mode = "RGB"
        n_frames = 1
        info: dict[str, object] = {}

        def __init__(self, dimensions: tuple[int, int]) -> None:
            self.size = dimensions

        def getexif(self) -> dict[int, int]:
            return {}

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "specstyle.generation.preprocess.Image.open",
        lambda value: HeaderOnlyImage(size),
    )
    encoded = _encoded(size=(64, 64))

    with pytest.raises(DomainError, match="exceeds limits"):
        preprocess_image(encoded, _source(encoded), _plan())


@pytest.mark.parametrize("size", ((16384, 1), (5000, 5000)))
def test_preprocess_allows_exact_header_limits_before_later_decode_failure(
    monkeypatch: pytest.MonkeyPatch, size: tuple[int, int]
) -> None:
    class HeaderOnlyImage:
        format = "PNG"
        mode = "RGB"
        n_frames = 1
        info: dict[str, object] = {}
        verified = False

        def __init__(self, dimensions: tuple[int, int]) -> None:
            self.size = dimensions

        def getexif(self) -> dict[int, int]:
            return {}

        def verify(self) -> None:
            type(self).verified = True

        def close(self) -> None:
            return None

    calls = 0

    def open_image(value: object) -> HeaderOnlyImage:
        nonlocal calls
        calls += 1
        if calls == 1:
            return HeaderOnlyImage(size)
        raise UnidentifiedImageError("controlled decode failure")

    monkeypatch.setattr("specstyle.generation.preprocess.Image.open", open_image)
    encoded = _encoded(size=(64, 64))

    with pytest.raises(DomainError, match="invalid input image"):
        preprocess_image(encoded, _source(encoded), _plan())
    assert HeaderOnlyImage.verified is True
