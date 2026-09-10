"""Unit tests for strict StyleSpecV1 models.

Cover the frozen Module 2 contract: all 14 top-level fields are required with
extra fields forbidden, strict and frozen types, constrained scalar bounds,
lowercase SHA normalization, exactly three nullable locations, the
``Literal[False]`` validator, duplicate output rejection without deduplication,
non-empty assets, repair-round bounds, strict fidelity booleans, and the
SPEC-003 fail-closed handling of required fidelity with raw null L3.

With ``strict=True``, tuple fields reject lists. The loader explicitly converts
YAML sequences, while direct model validation remains strict, so fixtures here
use tuples.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from specstyle.spec.models import StyleSpecV1

# --- Minimal valid Spec fixture ---


def _valid_spec() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "schema_uri": "schemas/style-spec-1.0.schema.json",
        "metadata": {
            "spec_id": "brand-retro-v1",
            "name": "Retro Editorial",
            "author": "studio-a",
            "created_at": "2026-07-29T10:00:00Z",
            "parent_spec": None,
        },
        "runtime": {
            "backend": "rocm",
            "rocm_version": "6.2",
            "torch_version": "2.4",
            "diffusers_version": "0.30",
            "dtype": "float16",
        },
        "models": {
            "base": {"id": "sdxl-base", "revision": "r1", "sha256": "a" * 64},
            "ip_adapter": {"id": "ip-adapter", "revision": "r1", "sha256": "b" * 64},
            "controlnet": {
                "type": "canny",
                "id": "canny-cn",
                "revision": "r1",
                "sha256": "c" * 64,
            },
        },
        "assets": {
            "style_references": (
                {
                    "asset_sha256": "d" * 64,
                    "source_url": "https://example.com/a.png",
                    "license": "CC0",
                    "attribution": "author",
                    "consent": "not_applicable",
                },
            )
        },
        "profiles": {
            "preview": {
                "pipeline": "sdxl_turbo",
                "resolution": (512, 512),
                "steps": 4,
                "guidance_scale": 0,
            },
            "production": {
                "pipeline": "sdxl_base",
                "resolution": (1024, 1024),
                "steps": 30,
                "guidance_scale": 5,
                "scheduler": "euler",
            },
        },
        "style": {
            "preset_id": "retro-v1",
            "user_strength": 0.7,
            "preview_ip_adapter_scale": 0.55,
            "production_ip_adapter_scale": 0.72,
        },
        "generation": {
            "img2img_strength": 0.45,
            "controlnet_scale": 0.70,
            "seed_policy": "per_asset_deterministic",
            "batch_execution": "sequential",
        },
        "domain": {
            "profile": "product_instance",
            "verifier_version": None,
            "fidelity_required": False,
        },
        "outputs": {"profiles": ("xhs_grid",)},
        "verification": {
            "ruleset_version": "1.0",
            "gate_defaults": {
                "on_unverifiable": "reject",
                "on_warning": "manual_review",
            },
            "l2": {
                "encoder_id": "enc",
                "encoder_revision": "r1",
                "preprocessing_version": "p1",
                "threshold_profile": {
                    "id": "tp1",
                    "revision": "r1",
                    "sha256": "e" * 64,
                },
            },
            "l3": None,
        },
        "repair": {
            "policy_version": "1.0",
            "max_rounds": 3,
            "stop_after_no_improvement": 2,
        },
        "replay_contract": {
            "mode": "semantic",
            "tolerated_metric_delta": {"l2_style_fidelity": 0.02, "l3_fidelity": 0.02},
            "new_batch": {
                "contract": "same_compiled_graph_and_gate_definitions",
                "per_item_metric_equality_required": False,
            },
        },
    }


@pytest.fixture
def valid_spec() -> dict[str, Any]:
    return copy.deepcopy(_valid_spec())


def _with(spec: dict, path: list, value: Any) -> dict:
    s = copy.deepcopy(spec)
    cur = s
    for k in path[:-1]:
        cur = cur[k]
    cur[path[-1]] = value
    return s


# --- Valid construction ---


def test_valid_spec_constructs(valid_spec):
    spec = StyleSpecV1(**valid_spec)
    assert spec.schema_version == "1.0"
    assert spec.metadata.spec_id == "brand-retro-v1"
    assert spec.models.controlnet.type == "canny"
    assert spec.domain.fidelity_required is False
    assert spec.verification.l3 is None
    # Collections are stored as tuples.
    assert spec.profiles.preview.resolution == (512, 512)
    assert spec.outputs.profiles == ("xhs_grid",)


def test_spec_is_frozen(valid_spec):
    spec = StyleSpecV1(**valid_spec)
    with pytest.raises(ValidationError):
        spec.schema_version = "2.0"  # type: ignore[misc]


# --- extra-forbid + required ---


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "schema_uri",
        "metadata",
        "runtime",
        "models",
        "assets",
        "profiles",
        "style",
        "generation",
        "domain",
        "outputs",
        "verification",
        "repair",
        "replay_contract",
    ],
)
def test_top_level_field_required(valid_spec, field):
    with pytest.raises(ValidationError):
        StyleSpecV1(**{k: v for k, v in valid_spec.items() if k != field})


def test_extra_top_level_forbidden(valid_spec):
    valid_spec["bogus"] = 1
    with pytest.raises(ValidationError):
        StyleSpecV1(**valid_spec)


def test_extra_nested_forbidden(valid_spec):
    valid_spec["metadata"]["bogus"] = 1
    with pytest.raises(ValidationError):
        StyleSpecV1(**valid_spec)


def test_no_l1_rules_field(valid_spec):
    valid_spec["verification"]["l1_rules"] = []
    with pytest.raises(ValidationError):
        StyleSpecV1(**valid_spec)


def test_no_repair_rules_field(valid_spec):
    valid_spec["repair"]["rules"] = []
    with pytest.raises(ValidationError):
        StyleSpecV1(**valid_spec)


# --- Literal enums ---


def test_schema_version_literal(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["schema_version"], "2.0"))


def test_runtime_backend_literal(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["runtime", "backend"], "cuda"))


def test_dtype_literal(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["runtime", "dtype"], "fp32"))


def test_controlnet_type_literal(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["models", "controlnet", "type"], "scribble"))


def test_consent_literal(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(
            **_with(valid_spec, ["assets", "style_references", 0, "consent"], "maybe")
        )


def test_domain_profile_literal(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["domain", "profile"], "generic"))


def test_output_profile_literal(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["outputs", "profiles"], ("square",)))


# --- SHA lowercase normalization ---


def test_sha256_uppercase_normalized(valid_spec):
    valid_spec["models"]["base"]["sha256"] = "A" * 64
    spec = StyleSpecV1(**valid_spec)
    assert spec.models.base.sha256 == "a" * 64


def test_sha256_invalid_hex_rejected(valid_spec):
    valid_spec["models"]["base"]["sha256"] = "g" * 64
    with pytest.raises(ValidationError):
        StyleSpecV1(**valid_spec)


def test_sha256_wrong_length_rejected(valid_spec):
    valid_spec["models"]["base"]["sha256"] = "a" * 63
    with pytest.raises(ValidationError):
        StyleSpecV1(**valid_spec)


# --- SafeText boundaries ---


def test_safetext_rejects_control_chars(valid_spec):
    for bad in ("ab\x00c", "ab\x1bc", "ab\x7fc"):
        with pytest.raises(ValidationError):
            StyleSpecV1(**_with(valid_spec, ["runtime", "rocm_version"], bad))


def test_safetext_rejects_leading_trailing_ws(valid_spec):
    for bad in (" 6.2", "6.2 ", "\t6.2"):
        with pytest.raises(ValidationError):
            StyleSpecV1(**_with(valid_spec, ["runtime", "rocm_version"], bad))


def test_safetext_allows_internal_space_unicode_slash_dot(valid_spec):
    spec = StyleSpecV1(**_with(valid_spec, ["runtime", "rocm_version"], "ro cm / v.6"))
    assert spec.runtime.rocm_version == "ro cm / v.6"


def test_name_max_256(valid_spec):
    valid_spec["metadata"]["name"] = "x" * 256
    StyleSpecV1(**valid_spec)  # ok
    valid_spec["metadata"]["name"] = "x" * 257
    with pytest.raises(ValidationError):
        StyleSpecV1(**valid_spec)


# --- ID-like ---


def test_idlike_rejects_non_ascii(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["metadata", "spec_id"], "café"))


def test_idlike_rejects_leading_hyphen_and_too_long(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["metadata", "spec_id"], "-abc"))
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["metadata", "spec_id"], "a" * 129))


# --- created_at RFC3339 tz ---


def test_created_at_requires_timezone(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(
            **_with(valid_spec, ["metadata", "created_at"], "2026-07-29T10:00:00")
        )


def test_created_at_accepts_offset(valid_spec):
    spec = StyleSpecV1(
        **_with(valid_spec, ["metadata", "created_at"], "2026-07-29T10:00:00+08:00")
    )
    assert spec.metadata.created_at == "2026-07-29T10:00:00+08:00"


# --- source_url ---


def test_source_url_http_only(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(
            **_with(
                valid_spec, ["assets", "style_references", 0, "source_url"], "ftp://x"
            )
        )
    with pytest.raises(ValidationError):
        StyleSpecV1(
            **_with(
                valid_spec, ["assets", "style_references", 0, "source_url"], "not-a-url"
            )
        )


# --- Scale [0,1] ---


def test_scale_rejects_out_of_range(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["style", "user_strength"], 1.5))
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["style", "user_strength"], -0.1))


def test_scale_rejects_bool_and_string(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["style", "user_strength"], True))
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["style", "user_strength"], "0.7"))


def test_scale_rejects_inf_nan(valid_spec):
    import math

    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["style", "user_strength"], math.inf))
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["style", "user_strength"], math.nan))


# --- resolution ---


def test_resolution_exactly_two(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["profiles", "preview", "resolution"], (512,)))
    with pytest.raises(ValidationError):
        StyleSpecV1(
            **_with(valid_spec, ["profiles", "preview", "resolution"], (512, 512, 512))
        )


def test_resolution_range_and_multiple_of_8(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(
            **_with(valid_spec, ["profiles", "preview", "resolution"], (63, 512))
        )
    with pytest.raises(ValidationError):
        StyleSpecV1(
            **_with(valid_spec, ["profiles", "preview", "resolution"], (4097, 512))
        )
    with pytest.raises(ValidationError):
        StyleSpecV1(
            **_with(valid_spec, ["profiles", "preview", "resolution"], (513, 512))
        )


# --- steps / guidance ---


def test_steps_range(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["profiles", "preview", "steps"], 0))
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["profiles", "preview", "steps"], 201))


def test_guidance_range(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["profiles", "preview", "guidance_scale"], 51))
    StyleSpecV1(**_with(valid_spec, ["profiles", "preview", "guidance_scale"], 50))


# --- nullable exactly three ---


def test_parent_spec_nullable(valid_spec):
    spec = StyleSpecV1(**_with(valid_spec, ["metadata", "parent_spec"], None))
    assert spec.metadata.parent_spec is None


def test_verifier_version_nullable(valid_spec):
    spec = StyleSpecV1(**_with(valid_spec, ["domain", "verifier_version"], None))
    assert spec.domain.verifier_version is None


def test_l3_nullable(valid_spec):
    spec = StyleSpecV1(**_with(valid_spec, ["verification", "l3"], None))
    assert spec.verification.l3 is None


def test_non_nullable_field_rejects_none(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["verification", "ruleset_version"], None))


# --- fidelity_required strict bool ---


def test_fidelity_required_strict_bool(valid_spec):
    for bad in (0, 1, "true", None, 0.0):
        with pytest.raises(ValidationError):
            StyleSpecV1(**_with(valid_spec, ["domain", "fidelity_required"], bad))


def test_fidelity_required_true_l3_null_passes_raw(valid_spec):
    valid_spec["domain"]["fidelity_required"] = True
    valid_spec["verification"]["l3"] = None
    spec = StyleSpecV1(**valid_spec)
    assert spec.domain.fidelity_required is True
    assert spec.verification.l3 is None


# --- outputs no-dup, no silent dedup ---


def test_outputs_rejects_empty(valid_spec):
    valid_spec["outputs"]["profiles"] = ()
    with pytest.raises(ValidationError):
        StyleSpecV1(**valid_spec)


def test_outputs_rejects_duplicate_no_dedup(valid_spec):
    valid_spec["outputs"]["profiles"] = ("xhs_grid", "xhs_grid")
    with pytest.raises(ValidationError):
        StyleSpecV1(**valid_spec)


def test_outputs_accepts_three_distinct(valid_spec):
    valid_spec["outputs"]["profiles"] = (
        "xhs_grid",
        "talking_head_cover",
        "background_sequence",
    )
    spec = StyleSpecV1(**valid_spec)
    assert len(spec.outputs.profiles) == 3


# --- assets non-empty ---


def test_assets_style_references_non_empty(valid_spec):
    valid_spec["assets"]["style_references"] = ()
    with pytest.raises(ValidationError):
        StyleSpecV1(**valid_spec)


# --- repair stop_after_no_improvement ≤ max_rounds ---


def test_stop_after_no_improvement_le_max_rounds(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["repair", "stop_after_no_improvement"], 4))
    spec = StyleSpecV1(**_with(valid_spec, ["repair", "stop_after_no_improvement"], 3))
    assert spec.repair.stop_after_no_improvement == 3


def test_max_rounds_range(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["repair", "max_rounds"], 0))
    with pytest.raises(ValidationError):
        StyleSpecV1(**_with(valid_spec, ["repair", "max_rounds"], 11))


# --- replay_contract Literal[False] before-validator ---


@pytest.mark.parametrize(
    "bad",
    [0, 0.0, "false", "", None, True],
    ids=["int0", "float0", "str_false", "empty", "none", "true"],
)
def test_per_item_metric_equality_required_only_false(valid_spec, bad):
    with pytest.raises(ValidationError):
        StyleSpecV1(
            **_with(
                valid_spec,
                ["replay_contract", "new_batch", "per_item_metric_equality_required"],
                bad,
            )
        )


def test_per_item_metric_equality_required_false_accepted(valid_spec):
    spec = StyleSpecV1(**valid_spec)
    assert spec.replay_contract.new_batch.per_item_metric_equality_required is False


def test_replay_tolerated_delta_range(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(
            **_with(
                valid_spec,
                ["replay_contract", "tolerated_metric_delta", "l2_style_fidelity"],
                1.5,
            )
        )
    with pytest.raises(ValidationError):
        StyleSpecV1(
            **_with(
                valid_spec,
                ["replay_contract", "tolerated_metric_delta", "l3_fidelity"],
                -0.1,
            )
        )


def test_replay_new_batch_contract_literal(valid_spec):
    with pytest.raises(ValidationError):
        StyleSpecV1(
            **_with(
                valid_spec,
                ["replay_contract", "new_batch", "contract"],
                "something_else",
            )
        )
