"""Strict parsing and defensive copying for Production output profiles."""

from __future__ import annotations

from typing import Any

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.generation.output_profile_contracts import (
    production_output_profile_capabilities,
)
from specstyle.spec.compiled_models import (
    OutputProfileCapability,
    OutputRenderContract,
    ResourcePin,
)

_PIN_KEYS = {"id", "revision", "sha256"}
_V2_OUTPUT_KEYS = {
    "profile",
    "pin",
    "final_resolution",
    "fit",
    "resampling",
    "background",
    "overlay",
    "sequence_semantics",
}
_V2_NATIVE_OUTPUT_KEYS = _V2_OUTPUT_KEYS | {"native_resolution"}
_PROFILE_ORDER = ("xhs_grid", "talking_head_cover", "background_sequence")


def _exact(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise DomainError(f"invalid production context {label}")
    return value


def _pin(value: object) -> ResourcePin:
    raw = _exact(value, _PIN_KEYS, "pin")
    return ResourcePin(raw["id"], raw["revision"], Sha256(raw["sha256"]))


def parse_legacy_output_profile(value: object) -> OutputProfileCapability:
    raw = _exact(value, {"pin"}, "output")
    return OutputProfileCapability(
        _pin(raw["pin"]),
        "xhs_grid",
        ("product_instance",),
        ("preview", "production"),
    )


def _parse_v2_output_profile(value: object) -> OutputProfileCapability:
    if type(value) is not dict or set(value) not in (
        _V2_OUTPUT_KEYS,
        _V2_NATIVE_OUTPUT_KEYS,
    ):
        raise DomainError("invalid production context output")
    raw = value
    contract = OutputRenderContract(
        tuple(raw["final_resolution"]),
        raw["fit"],
        raw["resampling"],
        tuple(raw["background"]),
        raw["overlay"],
        raw["sequence_semantics"],
        None if "native_resolution" not in raw else tuple(raw["native_resolution"]),
    )
    capability = OutputProfileCapability(
        _pin(raw["pin"]),
        raw["profile"],
        ("product_instance",),
        ("preview", "production"),
        contract,
    )
    implemented = tuple(
        item
        for item in production_output_profile_capabilities()
        if item.profile == capability.profile
    )
    if implemented != (capability,):
        raise DomainError("invalid production output renderer contract")
    return capability


def parse_output_profiles_v2(value: object) -> tuple[OutputProfileCapability, ...]:
    if type(value) is not list or not value:
        raise DomainError("invalid production context output profiles")
    outputs = tuple(_parse_v2_output_profile(item) for item in value)
    profiles = tuple(item.profile for item in outputs)
    if len(set(profiles)) != len(profiles) or profiles != tuple(
        item for item in _PROFILE_ORDER if item in profiles
    ):
        raise DomainError("invalid production context output profiles")
    return outputs


def copy_output_profile(value: OutputProfileCapability) -> OutputProfileCapability:
    pin, contract = value.pin, value.render_contract
    return OutputProfileCapability(
        ResourcePin(str(pin.id), str(pin.revision), Sha256(pin.sha256.value)),
        str(value.profile),
        tuple(str(item) for item in value.supported_domains),
        tuple(str(item) for item in value.supported_generation_profiles),
        None
        if contract is None
        else OutputRenderContract(
            tuple(contract.final_resolution),
            str(contract.fit),
            str(contract.resampling),
            tuple(contract.background),
            str(contract.overlay),
            str(contract.sequence_semantics),
            None
            if contract.native_resolution is None
            else tuple(contract.native_resolution),
        ),
    )
