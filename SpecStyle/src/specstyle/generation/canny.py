"""Deterministic OpenCV Canny builder for production ControlNet input."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from io import BytesIO
import json
import sys
import zlib

import cv2
import numpy as np
from PIL import Image, features

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.canny_contracts import (
    CannyProcessorConfig,
    _rebuild_canny_processor_config,
)
from specstyle.generation.preprocess import (
    PreparedImage,
    PreprocessPlan,
    PreprocessSnapshot,
)
from specstyle.generation.requests import PreparedControlInput
from specstyle.observability.hashing import hash_bytes
from specstyle.spec.compiled_models import CompiledExecutionGraph, ResourcePin

_SCHEMA = "specstyle.canny_processor.v1"
_ALGORITHM_VERSION = "1"
_OPENCV_DISTRIBUTION = "opencv-python-headless"
_PNG_COMPRESS_TYPE = 0


def _version_value(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or any(ord(character) <= 31 or ord(character) == 127 for character in value)
    ):
        raise InfrastructureError(f"{name} version unavailable")
    return value


def _dependency_version(module: object, name: str) -> str:
    return _version_value(getattr(module, "__version__", None), name)


def _opencv_distribution_version() -> str:
    try:
        value = metadata.version(_OPENCV_DISTRIBUTION)
    except MemoryError:
        raise
    except Exception as error:
        raise InfrastructureError("OpenCV distribution version unavailable") from error
    return _version_value(value, "OpenCV distribution")


def _pillow_linked_zlib_version() -> str:
    try:
        value = features.version_codec("zlib")
    except MemoryError:
        raise
    except Exception as error:
        raise InfrastructureError("Pillow linked zlib version unavailable") from error
    return _version_value(value, "Pillow linked zlib")


def _opencv_build_information_sha256() -> str:
    try:
        build_information = cv2.getBuildInformation()
        if type(build_information) is not str or not build_information.strip():
            raise InfrastructureError("OpenCV build information unavailable")
        return hash_bytes(build_information.encode("utf-8")).value
    except MemoryError:
        raise
    except InfrastructureError:
        raise
    except Exception as error:
        raise InfrastructureError("OpenCV build information unavailable") from error


def _processor_material(config: CannyProcessorConfig, /) -> str:
    """Return the canonical material whose digest identifies this processor."""
    config = _rebuild_canny_processor_config(config)
    material = {
        "algorithm": "opencv.Canny",
        "algorithm_version": _ALGORITHM_VERSION,
        "aperture_size": config.aperture_size,
        "color_conversions": [
            "cv2.imdecode:IMREAD_COLOR",
            "cv2.cvtColor:COLOR_BGR2GRAY",
            "numpy.repeat:GRAY_TO_RGB",
        ],
        "dependencies": {
            "numpy": _dependency_version(np, "numpy"),
            "opencv": _dependency_version(cv2, "opencv"),
            "opencv_build_information_sha256": _opencv_build_information_sha256(),
            "opencv_distribution": _OPENCV_DISTRIBUTION,
            "opencv_distribution_version": _opencv_distribution_version(),
            "pillow": _dependency_version(Image, "Pillow"),
            "pillow_linked_zlib": _pillow_linked_zlib_version(),
            "python_zlib_runtime": _version_value(
                getattr(zlib, "ZLIB_RUNTIME_VERSION", None), "Python zlib runtime"
            ),
        },
        "high_threshold": config.high_threshold,
        "l2_gradient": config.l2_gradient,
        "low_threshold": config.low_threshold,
        "png": {
            "compress_level": 9,
            "compress_type": _PNG_COMPRESS_TYPE,
            "format": "PNG",
            "metadata": "none",
            "optimize": False,
        },
        "schema": _SCHEMA,
    }
    return json.dumps(material, sort_keys=True, separators=(",", ":"))


def _processor_pin(config: CannyProcessorConfig) -> ResourcePin:
    material = _processor_material(config).encode("utf-8")
    return ResourcePin(
        "specstyle-canny-processor",
        _ALGORITHM_VERSION,
        Sha256(hash_bytes(material).value),
    )


def _validate_binding(
    source: object, graph: object
) -> tuple[PreparedImage, CompiledExecutionGraph]:
    if type(source) is not PreparedImage or type(graph) is not CompiledExecutionGraph:
        raise DomainError("invalid Canny builder input")
    rebuilt = PreparedImage(source.source, source.content, source.snapshot)
    if rebuilt != source:
        raise DomainError("invalid Canny builder input")
    if (
        graph.controlnet.role != "controlnet"
        or graph.controlnet.controlnet_type != "canny"
        or graph.resolution != (rebuilt.width, rebuilt.height)
    ):
        raise DomainError("Canny builder graph binding mismatch")
    return rebuilt, graph


def _require_array(
    value: object,
    *,
    shape: tuple[int, ...],
    message: str,
) -> np.ndarray:
    if type(value) is not np.ndarray or value.dtype != np.uint8 or value.shape != shape:
        raise InfrastructureError(message)
    return value


def _edge_rgb(content: bytes, size: tuple[int, int], config: CannyProcessorConfig):
    width, height = size
    encoded = np.frombuffer(content, dtype=np.uint8)
    bgr = _require_array(
        cv2.imdecode(encoded, cv2.IMREAD_COLOR),
        shape=(height, width, 3),
        message="Canny source decode failed",
    )
    gray = _require_array(
        cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY),
        shape=(height, width),
        message="Canny grayscale conversion failed",
    )
    edges = _require_array(
        cv2.Canny(
            gray,
            config.low_threshold,
            config.high_threshold,
            apertureSize=config.aperture_size,
            L2gradient=config.l2_gradient,
        ),
        shape=(height, width),
        message="Canny edge detection failed",
    )
    return np.repeat(edges[:, :, np.newaxis], 3, axis=2)


def _encode_clean_png(pixels: np.ndarray) -> bytes:
    image: Image.Image | None = None
    try:
        image = Image.fromarray(pixels)
        if image.mode != "RGB":
            raise InfrastructureError("Canny RGB conversion failed")
        with BytesIO() as output:
            image.save(
                output,
                format="PNG",
                optimize=False,
                compress_level=9,
                compress_type=_PNG_COMPRESS_TYPE,
            )
            return output.getvalue()
    finally:
        if image is not None:
            try:
                image.close()
            except Exception as error:
                if sys.exc_info()[0] is None:
                    raise InfrastructureError("Canny image close failed") from error


def _output_snapshot(
    source: PreparedImage, processor_pin: ResourcePin
) -> PreprocessSnapshot:
    original = source.snapshot
    plan = PreprocessPlan(
        original.plan.target_size,
        original.plan.resize_mode,
        original.plan.background,
        processor_pin,
    )
    return PreprocessSnapshot(
        plan,
        original.input_format,
        original.input_mode,
        original.input_size,
        original.exif_orientation,
        original.pillow_version,
    )


@dataclass(frozen=True, slots=True, init=False)
class CannyControlInputBuilder:
    config: CannyProcessorConfig

    def __init__(self, config: CannyProcessorConfig, /) -> None:
        object.__setattr__(self, "config", _rebuild_canny_processor_config(config))

    def build(
        self, source: PreparedImage, graph: CompiledExecutionGraph, /
    ) -> PreparedControlInput:
        source, graph = _validate_binding(source, graph)
        try:
            processor_pin = _processor_pin(self.config)
            pixels = _edge_rgb(source.content, graph.resolution, self.config)
            content = _encode_clean_png(pixels)
            image = PreparedImage(
                source.source,
                content,
                _output_snapshot(source, processor_pin),
            )
            return PreparedControlInput("canny", image)
        except MemoryError:
            raise
        except InfrastructureError:
            raise
        except DomainError as error:
            raise InfrastructureError(
                "Canny control input processing failed"
            ) from error
        except Exception as error:
            raise InfrastructureError(
                "Canny control input processing failed"
            ) from error
