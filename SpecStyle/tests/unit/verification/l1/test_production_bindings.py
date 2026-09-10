"""Production L1 rule-binding authority tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

from specstyle.domain.identifiers import RuleId
from specstyle.errors import DomainError


class _HostileRuleId(RuleId):
    pass


class _HostileStr(str):
    pass


def _module():
    from specstyle.verification.l1 import production_bindings

    return production_bindings


def test_production_bindings_are_ordered_exact_and_fresh() -> None:
    module = _module()

    first = module.production_l1_rule_bindings()
    second = module.production_l1_rule_bindings()

    assert tuple((item.rule_id.value, item.implementation) for item in first) == (
        ("l1_bundle", "technical_rgb_png_bundle_v1"),
        ("l1_decode", "decode_png_rgb_no_metadata_v1"),
        ("l1_dimensions", "dimensions_exact_v1"),
        ("l1_pixels", "pixels_nonblank_v1"),
    )
    assert type(first) is tuple
    assert first is not second
    assert all(type(item) is module.ProductionL1RuleBinding for item in first)
    assert all(left is not right for left, right in zip(first, second, strict=True))


def test_production_binding_is_frozen_slotted_and_exactly_typed() -> None:
    module = _module()
    binding = module.ProductionL1RuleBinding(
        RuleId("l1_bundle"), "technical_rgb_png_bundle_v1"
    )

    assert tuple(field.name for field in fields(binding)) == (
        "rule_id",
        "implementation",
    )
    assert not hasattr(binding, "__dict__")
    with pytest.raises(FrozenInstanceError):
        binding.implementation = "decode_png_rgb_no_metadata_v1"
    for rule_id, implementation in (
        (_HostileRuleId("l1_bundle"), "technical_rgb_png_bundle_v1"),
        (RuleId("l1_bundle"), _HostileStr("technical_rgb_png_bundle_v1")),
        (RuleId("l1_bundle"), "unknown"),
    ):
        with pytest.raises(
            DomainError, match="^invalid production runtime dependency$"
        ):
            module.ProductionL1RuleBinding(rule_id, implementation)


def test_rebuild_returns_fresh_canonical_bindings() -> None:
    module = _module()
    supplied = module.production_l1_rule_bindings()

    rebuilt = module._rebuild_production_l1_rule_bindings(supplied)

    assert rebuilt == supplied
    assert rebuilt is not supplied
    assert all(left is not right for left, right in zip(rebuilt, supplied, strict=True))


def test_rebuild_rejects_invalid_tampered_duplicate_and_missing_bindings() -> None:
    module = _module()
    good = module.production_l1_rule_bindings()
    tampered = module.production_l1_rule_bindings()
    object.__setattr__(tampered[0], "implementation", "tampered")
    swapped = (
        module.ProductionL1RuleBinding(good[0].rule_id, good[1].implementation),
        module.ProductionL1RuleBinding(good[1].rule_id, good[0].implementation),
        *good[2:],
    )
    candidates = (
        list(good),
        (*good, good[-1]),
        good[:-1],
        tuple(reversed(good)),
        swapped,
        tampered,
        (object(),),
    )

    for candidate in candidates:
        with pytest.raises(
            DomainError, match="^invalid production runtime dependency$"
        ):
            module._rebuild_production_l1_rule_bindings(candidate)


def test_registry_validator_rejects_duplicate_missing_and_wrong_pairs() -> None:
    module = _module()
    good = tuple(
        (binding.rule_id, binding.implementation)
        for binding in module.production_l1_rule_bindings()
    )
    invalid = (
        good[:-1],
        (*good, good[-1]),
        (good[1], good[0], *good[2:]),
        ((good[0][0], good[1][1]), (good[1][0], good[0][1]), *good[2:]),
    )

    module._validate_production_l1_rule_registry(good)
    for candidate in invalid:
        with pytest.raises(
            DomainError, match="^invalid production runtime dependency$"
        ):
            module._validate_production_l1_rule_registry(candidate)


def test_workflow_reexports_the_authoritative_class_and_function() -> None:
    module = _module()
    from specstyle.workflow import production_service

    assert production_service.ProductionL1RuleBinding is (
        module.ProductionL1RuleBinding
    )
    assert production_service.production_l1_rule_bindings is (
        module.production_l1_rule_bindings
    )
