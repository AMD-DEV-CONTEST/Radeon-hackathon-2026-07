"""Render exact GPU capability digests for the AMD Shidu video worker."""

from __future__ import annotations

import os

from drama.atomic_plugin import (
    factory_implementation_manifests,
    factory_operation_specs,
)


def capability_environment() -> dict[str, str]:
    if os.getenv("FACTORY_KEYFRAME_PROFILE") != "sdxl-core":
        raise RuntimeError("FACTORY_KEYFRAME_PROFILE must be sdxl-core")

    specs = {item.op_type: item for item in factory_operation_specs()}
    manifests = {
        spec.op_type: manifest
        for spec, manifest in zip(
            factory_operation_specs(),
            factory_implementation_manifests(),
            strict=True,
        )
    }
    keyframe = specs["keyframe.generate"].resource_requirement
    video = specs["video.generate"].resource_requirement
    if keyframe is None or video is None:
        raise RuntimeError("GPU requirements are unavailable")
    if manifests["keyframe.generate"].provider_identity != "local-sdxl-comfy":
        raise RuntimeError("SDXL provider identity is not pinned")
    if manifests["video.generate"].provider_identity != "local-wan-comfy":
        raise RuntimeError("Wan provider identity is not pinned")

    return {
        "AMD_KEYFRAME_MODEL_DIGEST": keyframe.model_digest,
        "AMD_VIDEO_MODEL_DIGEST": video.model_digest,
        "AMD_KEYFRAME_WORKFLOW_DIGEST": keyframe.workflow_digest,
        "AMD_VIDEO_WORKFLOW_DIGEST": video.workflow_digest,
        "AMD_KEYFRAME_NODE_ENV_DIGEST": (
            keyframe.custom_node_environment_digest
        ),
        "AMD_VIDEO_NODE_ENV_DIGEST": video.custom_node_environment_digest,
        "AMD_KEYFRAME_IMPLEMENTATION_DIGEST": manifests[
            "keyframe.generate"
        ].implementation_digest,
        "AMD_VIDEO_IMPLEMENTATION_DIGEST": manifests[
            "video.generate"
        ].implementation_digest,
    }


def main() -> None:
    for name, value in capability_environment().items():
        print(f"{name}={value}")


if __name__ == "__main__":
    main()
