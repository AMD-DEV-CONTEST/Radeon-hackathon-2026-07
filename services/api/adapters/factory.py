import os
from pathlib import Path

from adapters.base import ThreeDProvider, ImageProvider, DepthProvider
from adapters.threed_stub import StubThreeDProvider
from adapters.image_stub import StubImageProvider
from adapters.tripo import TripoProvider
from config import settings

# ROCm / Hunyuan3D-2 providers are imported lazily so the app still starts when heavy deps are missing.
try:
    from adapters.rocm import (
        ROCmStyleProvider,
        ROCmDepthProvider,
        ROCmReliefProvider,
        rocm_available,
    )
    from adapters.hunyuan3d import Hunyuan3D2Provider

    _HAS_ROCM = True
except ImportError:  # pragma: no cover
    _HAS_ROCM = False

    def rocm_available() -> bool:  # type: ignore
        return False

    class ROCmStyleProvider:  # type: ignore
        pass

    class ROCmDepthProvider:  # type: ignore
        pass

    class ROCmReliefProvider:  # type: ignore
        pass

    class Hunyuan3D2Provider:  # type: ignore
        pass


USE_ROCM = os.environ.get("USE_ROCM", "false").lower() in ("1", "true", "yes")
USE_HUNYUAN3D = os.environ.get("USE_HUNYUAN3D", "true").lower() in ("1", "true", "yes")


USE_HUNYUAN3D_MV = os.environ.get("USE_HUNYUAN3D_MV", "true").lower() in ("1", "true", "yes")


def _prefer_rocm() -> bool:
    return USE_ROCM or (_HAS_ROCM and rocm_available())


def get_3d_provider(output_mode: str = "fullcolor_3d") -> ThreeDProvider:
    """Return the appropriate 3D provider based on output mode and environment.

    Args:
        output_mode: "fullcolor_3d" selects a mesh generator (Hunyuan3D-2 / Tripo / stub),
            "relief_2d5" selects a 2.5D relief generator.
    """
    priority = [p.strip().lower() for p in settings.threed_provider_priority.split(",")]

    if _prefer_rocm():
        if output_mode == "relief_2d5":
            return ROCmReliefProvider()
        if USE_HUNYUAN3D:
            try:
                if USE_HUNYUAN3D_MV:
                    return Hunyuan3D2Provider(
                        shape_model_path="tencent/Hunyuan3D-2mv",
                        subfolder="hunyuan3d-dit-v2-mv",
                    )
                return Hunyuan3D2Provider()
            except Exception as exc:  # pragma: no cover
                import warnings

                warnings.warn(
                    f"Hunyuan3D-2 provider could not be initialized ({exc}); "
                    "falling back to configured 3D providers or stub."
                )
        # If Hunyuan3D-2 is disabled or failed, fall through to the priority list.

    for name in priority:
        if name == "tripo" and settings.tripo_api_key:
            return TripoProvider(api_key=settings.tripo_api_key)
        if name == "meshy" and settings.meshy_api_key:
            # TODO: implement MeshyProvider
            continue
        if name == "rodin" and settings.rodin_api_key:
            # TODO: implement RodinProvider
            continue

    return StubThreeDProvider()


def get_image_provider() -> ImageProvider:
    """Return the image/multi-view provider."""
    if _prefer_rocm():
        return ROCmStyleProvider()
    return StubImageProvider()


def get_depth_provider() -> DepthProvider:
    """Return the depth-estimation provider."""
    if _prefer_rocm():
        return ROCmDepthProvider()
    # Fallback: treat the image stub as a pass-through depth provider for dev tests.
    class _StubDepth(StubImageProvider, DepthProvider):  # type: ignore
        name = "stub_depth"

        def generate_depth_map(self, image: Path, invert: bool = False) -> Path:  # type: ignore
            return image

    return _StubDepth()
