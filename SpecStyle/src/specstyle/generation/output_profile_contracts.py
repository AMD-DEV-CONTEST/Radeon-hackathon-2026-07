"""Pinned, lightweight contracts for built-in Production output renderers."""

from __future__ import annotations

import hashlib
import json

from specstyle.domain.identifiers import Sha256
from specstyle.spec.compiled_models import (
    OutputProfileCapability,
    OutputRenderContract,
    ResourcePin,
)

_SCHEMA = "specstyle.output-renderer-contract.v1"


def _digest(profile: str, contract: OutputRenderContract) -> Sha256:
    value = {
        "background": list(contract.background),
        "final_resolution": list(contract.final_resolution),
        "fit": contract.fit,
        "overlay": contract.overlay,
        "profile": profile,
        "resampling": contract.resampling,
        "sequence_semantics": contract.sequence_semantics,
    }
    if contract.native_resolution is not None:
        value.update(
            {
                "alignment": "center",
                "native_resolution": list(contract.native_resolution),
                "png_encoder": {
                    "compress_level": 9,
                    "format": "PNG",
                    "frames": 1,
                    "metadata": "none",
                    "mode": "RGB",
                    "optimize": False,
                },
                "rounding": "pillow-imageops-integer-v1",
            }
        )
    payload = {
        "schema": _SCHEMA,
        "value": value,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return Sha256(hashlib.sha256(encoded).hexdigest())


def _xhs_grid() -> OutputProfileCapability:
    contract = OutputRenderContract(
        (1080, 1080),
        "contain_pad",
        "lanczos",
        (255, 255, 255),
        "disabled",
        "single_static",
    )
    return OutputProfileCapability(
        ResourcePin(
            "specstyle-output-renderer-xhs-grid",
            "v1",
            _digest("xhs_grid", contract),
        ),
        "xhs_grid",
        ("product_instance",),
        ("preview", "production"),
        contract,
    )


def _talking_head_cover() -> OutputProfileCapability:
    contract = OutputRenderContract(
        (1080, 1440),
        "contain_pad_center",
        "lanczos",
        (255, 255, 255),
        "disabled",
        "single_static",
        (768, 768),
    )
    return OutputProfileCapability(
        ResourcePin(
            "specstyle-output-renderer-talking-head-cover",
            "v1",
            _digest("talking_head_cover", contract),
        ),
        "talking_head_cover",
        ("product_instance",),
        ("preview", "production"),
        contract,
    )


def _background_sequence() -> OutputProfileCapability:
    contract = OutputRenderContract(
        (1920, 1080),
        "contain_pad_center",
        "lanczos",
        (255, 255, 255),
        "disabled",
        "single_item_sequence_index_zero",
        (768, 768),
    )
    return OutputProfileCapability(
        ResourcePin(
            "specstyle-output-renderer-background-sequence",
            "v1",
            _digest("background_sequence", contract),
        ),
        "background_sequence",
        ("product_instance",),
        ("preview", "production"),
        contract,
    )


def production_output_profile_capabilities() -> tuple[OutputProfileCapability, ...]:
    """Return detached capabilities implemented by this code revision."""
    return (_xhs_grid(), _talking_head_cover(), _background_sequence())
