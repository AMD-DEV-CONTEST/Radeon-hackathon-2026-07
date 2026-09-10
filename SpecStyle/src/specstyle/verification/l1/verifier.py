"""L1 hard-rule Verifier: looks up artifact bytes and evaluates decode/dim/pixels."""

from __future__ import annotations

from collections.abc import Mapping

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import RuleLevel, RuleScope, RuleStatus, StaticApplicability
from specstyle.domain.identifiers import ArtifactId
from specstyle.errors import DomainError
from specstyle.verification.l1.decode import RULE_DECODE, decode_png_bytes, rule_decode
from specstyle.verification.l1.dimensions import (
    RULE_DIMENSIONS,
    check_dimensions_decoded,
)
from specstyle.verification.l1.pixels import RULE_PIXELS, check_pixels_decoded
from specstyle.verification.rule_models import GatePolicy, RuleDefinition, RuleResult


def l1_hard_rule_definitions() -> tuple[RuleDefinition, ...]:
    policy = GatePolicy("reject", "reject", "reject")
    return (
        RuleDefinition(
            RULE_DECODE,
            RuleLevel.L1,
            RuleScope.ITEM,
            True,
            StaticApplicability.APPLICABLE,
            policy,
        ),
        RuleDefinition(
            RULE_DIMENSIONS,
            RuleLevel.L1,
            RuleScope.ITEM,
            True,
            StaticApplicability.APPLICABLE,
            policy,
        ),
        RuleDefinition(
            RULE_PIXELS,
            RuleLevel.L1,
            RuleScope.ITEM,
            True,
            StaticApplicability.APPLICABLE,
            policy,
        ),
    )


class L1HardVerifier:
    """Maps ArtifactId → PNG bytes; evaluates only known L1 hard rule IDs."""

    def __init__(
        self,
        contents: Mapping[ArtifactId, bytes],
        expected_resolution: tuple[int, int],
        /,
    ) -> None:
        if not isinstance(contents, Mapping):
            raise DomainError("invalid L1 content map")
        if (
            type(expected_resolution) is not tuple
            or len(expected_resolution) != 2
            or type(expected_resolution[0]) is not int
            or type(expected_resolution[1]) is not int
            or isinstance(expected_resolution[0], bool)
            or isinstance(expected_resolution[1], bool)
        ):
            raise DomainError("invalid expected resolution")
        self._contents = {k: v for k, v in contents.items()}
        self._expected = expected_resolution

    def verify(
        self,
        artifacts: tuple[ArtifactRef, ...],
        rules: tuple[RuleDefinition, ...],
        /,
    ) -> tuple[RuleResult, ...]:
        if type(artifacts) is not tuple or type(rules) is not tuple:
            raise DomainError("invalid verifier inputs")
        results: list[RuleResult] = []
        for rule in rules:
            rid = rule.rule_id
            for artifact in artifacts:
                aid = artifact.artifact_id
                data = self._contents.get(aid)
                if data is None:
                    results.append(
                        RuleResult(rid, RuleStatus.UNVERIFIABLE, (aid,), None)
                    )
                    continue
                if rid == RULE_DECODE:
                    results.append(rule_decode(aid, data))
                elif rid == RULE_DIMENSIONS:
                    try:
                        decoded = decode_png_bytes(data)
                    except DomainError:
                        results.append(
                            RuleResult(rid, RuleStatus.UNVERIFIABLE, (aid,), None)
                        )
                        continue
                    results.append(
                        check_dimensions_decoded(aid, decoded, self._expected)
                    )
                elif rid == RULE_PIXELS:
                    try:
                        decoded = decode_png_bytes(data)
                    except DomainError:
                        results.append(
                            RuleResult(rid, RuleStatus.UNVERIFIABLE, (aid,), None)
                        )
                        continue
                    results.append(check_pixels_decoded(aid, decoded))
                else:
                    raise DomainError("unknown L1 rule")
        return tuple(results)
