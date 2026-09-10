"""Authoritative production L1 rule-to-implementation bindings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from specstyle.domain.identifiers import RuleId
from specstyle.errors import DomainError

__all__ = ("ProductionL1RuleBinding", "production_l1_rule_bindings")


class _ProductionL1Implementation(StrEnum):
    BUNDLE = "technical_rgb_png_bundle_v1"
    DECODE = "decode_png_rgb_no_metadata_v1"
    DIMENSIONS = "dimensions_exact_v1"
    PIXELS = "pixels_nonblank_v1"


_PRODUCTION_L1_RULE_REGISTRY = (
    ("l1_bundle", _ProductionL1Implementation.BUNDLE),
    ("l1_decode", _ProductionL1Implementation.DECODE),
    ("l1_dimensions", _ProductionL1Implementation.DIMENSIONS),
    ("l1_pixels", _ProductionL1Implementation.PIXELS),
)


@dataclass(frozen=True, slots=True)
class ProductionL1RuleBinding:
    rule_id: RuleId
    implementation: str

    def __post_init__(self) -> None:
        implementations = tuple(item[1].value for item in _PRODUCTION_L1_RULE_REGISTRY)
        if (
            type(self.rule_id) is not RuleId
            or type(self.rule_id.value) is not str
            or type(self.implementation) is not str
            or self.implementation not in implementations
        ):
            raise DomainError("invalid production runtime dependency") from None
        object.__setattr__(self, "rule_id", RuleId(str.__str__(self.rule_id.value)))
        object.__setattr__(self, "implementation", str.__str__(self.implementation))


def production_l1_rule_bindings() -> tuple[ProductionL1RuleBinding, ...]:
    return tuple(
        ProductionL1RuleBinding(RuleId(rule_id), implementation.value)
        for rule_id, implementation in _PRODUCTION_L1_RULE_REGISTRY
    )


def _validate_production_l1_rule_registry(value: object, /) -> None:
    if type(value) is not tuple:
        raise DomainError("invalid production runtime dependency") from None
    try:
        actual = tuple(
            (mapping[0].value, mapping[1])
            if (
                type(mapping) is tuple
                and len(mapping) == 2
                and type(mapping[0]) is RuleId
                and type(mapping[0].value) is str
                and type(mapping[1]) is str
            )
            else (_ for _ in ()).throw(ValueError())
            for mapping in value
        )
    except Exception:
        raise DomainError("invalid production runtime dependency") from None
    expected = tuple(
        (rule_id, implementation.value)
        for rule_id, implementation in _PRODUCTION_L1_RULE_REGISTRY
    )
    if actual != expected:
        raise DomainError("invalid production runtime dependency") from None


def _rebuild_production_l1_rule_bindings(
    value: object, /
) -> tuple[ProductionL1RuleBinding, ...]:
    if type(value) is not tuple:
        raise DomainError("invalid production runtime dependency") from None
    try:
        rebuilt = tuple(
            ProductionL1RuleBinding(item.rule_id, item.implementation)
            if type(item) is ProductionL1RuleBinding
            else (_ for _ in ()).throw(ValueError())
            for item in value
        )
        _validate_production_l1_rule_registry(
            tuple((item.rule_id, item.implementation) for item in rebuilt)
        )
    except Exception:
        raise DomainError("invalid production runtime dependency") from None
    return rebuilt
