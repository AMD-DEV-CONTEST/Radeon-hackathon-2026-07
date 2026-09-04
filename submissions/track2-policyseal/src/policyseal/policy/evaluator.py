from __future__ import annotations

from collections.abc import Iterable

from policyseal.domain.enums import (
    Action,
    ContentCategory,
    DecisionOrigin,
    FileKind,
    OwnerRelation,
)
from policyseal.domain.models import DisclosureContext, DocumentRegion, PolicyDecision
from policyseal.policy.conflicts import resolve_actions
from policyseal.policy.schema import PolicyPack, PolicyRule, RuleConditions

_FAIL_CLOSED_EVIDENCE_ID = "EV-GEN-002"


def _allows[T](allowed: tuple[T, ...], actual: T) -> bool:
    return not allowed or actual in allowed


def _matches(
    conditions: RuleConditions,
    context: DisclosureContext,
    region: DocumentRegion,
    category: ContentCategory,
    owner_relation: OwnerRelation,
) -> bool:
    return all(
        (
            _allows(conditions.file_kinds, region.file_kind),
            _allows(conditions.recipients, context.recipient),
            _allows(conditions.purposes, context.purpose),
            _allows(conditions.channels, context.channel),
            _allows(conditions.classifications, context.classification),
            _allows(conditions.categories, category),
            _allows(conditions.owner_relations, owner_relation),
        )
    )


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _fallback_evidence(pack: PolicyPack) -> tuple[str, ...]:
    evidence_ids = {record.id for record in pack.evidence}
    if _FAIL_CLOSED_EVIDENCE_ID in evidence_ids:
        return (_FAIL_CLOSED_EVIDENCE_ID,)
    if pack.evidence:
        return (pack.evidence[0].id,)
    raise ValueError("a policy pack without evidence cannot produce an auditable decision")


def _fail_closed(
    pack: PolicyPack,
    region: DocumentRegion,
    category: ContentCategory,
    *,
    rule_id: str,
    reason_code: str,
    reason: str,
    action: Action = Action.REQUIRE_APPROVAL,
    evidence_ids: tuple[str, ...] | None = None,
) -> PolicyDecision:
    return PolicyDecision(
        region_id=region.id,
        category=category,
        action=action,
        rule_ids=(rule_id,),
        evidence_ids=evidence_ids or _fallback_evidence(pack),
        reason_code=reason_code,
        reason=reason,
        policy_version=pack.version,
        policy_sha256=pack.sha256,
        origin=DecisionOrigin.FAIL_CLOSED,
    )


def _matching_rules(
    pack: PolicyPack,
    context: DisclosureContext,
    region: DocumentRegion,
    category: ContentCategory,
    owner_relation: OwnerRelation,
) -> tuple[PolicyRule, ...]:
    matches = (
        rule
        for rule in pack.rules
        if rule.enabled and _matches(rule.when, context, region, category, owner_relation)
    )
    return tuple(sorted(matches, key=lambda rule: (-rule.priority, rule.id)))


def evaluate_region(
    pack: PolicyPack,
    context: DisclosureContext,
    region: DocumentRegion,
    *,
    mapped_category: ContentCategory | None = None,
    owner_relation: OwnerRelation = OwnerRelation.NONE,
) -> PolicyDecision:
    category = mapped_category or region.category
    if context.policy_version != pack.version:
        return _fail_closed(
            pack,
            region,
            category,
            rule_id="PS-SYSTEM-POLICY-VERSION-MISMATCH",
            reason_code="policy_version_mismatch",
            reason="The requested policy version does not match the loaded policy pack.",
        )

    if category is ContentCategory.UNCLASSIFIED and region.semantic_reason_code in {
        "local_model_unavailable",
        "controlled_local_model_failure",
    }:
        file_evidence = {
            FileKind.DOCX: "EV-DOCX-004",
            FileKind.PDF: "EV-PDF-004",
            FileKind.XLSX: "EV-XLSX-004",
        }[region.file_kind]
        available_evidence = {record.id for record in pack.evidence}
        evidence_ids = tuple(
            item for item in ("EV-GEN-002", file_evidence) if item in available_evidence
        )
        return _fail_closed(
            pack,
            region,
            category,
            rule_id="PS-MODEL-OFFLINE-APPROVAL",
            reason_code="semantic_model_unavailable",
            reason="Local semantic evidence is unavailable, so disclosure requires review.",
            evidence_ids=evidence_ids,
        )

    if owner_relation is OwnerRelation.UNKNOWN:
        available_evidence = {record.id for record in pack.evidence}
        evidence_ids = tuple(
            item for item in ("EV-GEN-002", "EV-XLSX-004") if item in available_evidence
        )
        return _fail_closed(
            pack,
            region,
            category,
            rule_id="PS-DEFAULT-OWNER-UNKNOWN",
            reason_code="owner_relation_unknown",
            reason="Row ownership is unresolved, so disclosure requires human confirmation.",
            evidence_ids=evidence_ids,
        )

    rules = _matching_rules(pack, context, region, category, owner_relation)
    if not rules:
        available_evidence = {record.id for record in pack.evidence}
        default_evidence = tuple(
            evidence_id
            for evidence_id in ("EV-GEN-002", "EV-GEN-003")
            if evidence_id in available_evidence
        ) or _fallback_evidence(pack)
        return _fail_closed(
            pack,
            region,
            category,
            rule_id="PS-DEFAULT-FAIL-CLOSED",
            reason_code="no_matching_rule",
            reason="No deterministic rule proves this disclosure safe.",
            action=pack.default_action,
            evidence_ids=default_evidence,
        )

    resolution = resolve_actions(rule.action for rule in rules)
    transform: str | None = None
    if resolution.action in {Action.MASK, Action.FILTER, Action.GENERALIZE}:
        transforms = {
            rule.transform.value
            for rule in rules
            if rule.action is resolution.action and rule.transform is not None
        }
        if len(transforms) != 1:
            return PolicyDecision(
                region_id=region.id,
                category=category,
                action=Action.REQUIRE_APPROVAL,
                rule_ids=_unique(rule.id for rule in rules),
                evidence_ids=_unique(
                    evidence_id for rule in rules for evidence_id in rule.evidence_ids
                ),
                reason_code="incompatible_transform_definitions",
                reason="Applicable transforms do not have a provably conservative intersection.",
                policy_version=pack.version,
                policy_sha256=pack.sha256,
                origin=DecisionOrigin.FAIL_CLOSED,
            )
        transform = next(iter(transforms))

    winning_rules = tuple(rule for rule in rules if rule.action is resolution.action)
    if not winning_rules:
        winning_rules = rules
    primary_rule = winning_rules[0]
    origin = (
        DecisionOrigin.FAIL_CLOSED
        if resolution.reason_code in {"incompatible_transforms", "invalid_or_missing_action"}
        else DecisionOrigin.DETERMINISTIC
    )
    return PolicyDecision(
        region_id=region.id,
        category=category,
        action=resolution.action,
        rule_ids=_unique(rule.id for rule in winning_rules),
        evidence_ids=_unique(
            evidence_id for rule in winning_rules for evidence_id in rule.evidence_ids
        ),
        reason_code=primary_rule.reason_code,
        reason=primary_rule.reason,
        policy_version=pack.version,
        policy_sha256=pack.sha256,
        origin=origin,
        transform=transform,
    )
