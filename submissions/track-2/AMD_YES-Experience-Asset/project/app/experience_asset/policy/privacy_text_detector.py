"""Small general deterministic privacy detector over canonical statement text.

E1-E5 never populate `Statement.sensitivity_tags`, so the tag-driven detector in
`policy.m5` finds nothing on a real asset. Without a second producer an empty
proposal list would reach the review unchanged and read as "no privacy risk",
which is the one meaning it must never carry. This module supplies that missing
producer: a bounded, deterministic, offline text scan whose output is still an
untrusted *proposal* that Runtime validates like any other.

The rules are intentionally conservative and explainable. Each match names the
rule that fired rather than echoing the matched text, so a finding never copies
private content into a second record the user did not ask to create.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from app.experience_asset.application.m5.contracts import (
    PrivacyCategoryV1,
    PrivacyFindingProposalV1,
)
from app.experience_asset.domain.enums import ConfirmationState, FindingSeverity, StatementStatus
from app.experience_asset.domain.models import Statement

PRIVACY_TEXT_DETECTOR_VERSION = "m5-privacy-text-detector-v1"


class _Rule:
    __slots__ = ("category", "description", "pattern", "rule_id", "severity")

    def __init__(
        self,
        rule_id: str,
        category: PrivacyCategoryV1,
        severity: FindingSeverity,
        pattern: str,
        description: str,
    ) -> None:
        self.rule_id = rule_id
        self.category = category
        self.severity = severity
        self.pattern = re.compile(pattern, re.IGNORECASE | re.UNICODE)
        self.description = description


# Ordered for reproducible output; the scan result is sorted again before use.
_RULES: tuple[_Rule, ...] = (
    _Rule(
        "IDENTITY_SELF_NAME",
        PrivacyCategoryV1.IDENTITY,
        FindingSeverity.HIGH,
        r"(?:\bmy name is\b|\bi am called\b|我叫|我的名字是)",
        "states a personal name",
    ),
    _Rule(
        "IDENTITY_EMPLOYER",
        PrivacyCategoryV1.IDENTITY,
        FindingSeverity.HIGH,
        r"(?:\bi work (?:at|for)\b|\bmy employer\b|\bmy company is\b"
        r"|我在.{1,20}(?:工作|上班)|我的公司)",
        "names an employer alongside the author",
    ),
    _Rule(
        "IDENTITY_EMAIL",
        PrivacyCategoryV1.IDENTITY,
        FindingSeverity.HIGH,
        r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
        "contains an email address",
    ),
    _Rule(
        "IDENTITY_PHONE",
        PrivacyCategoryV1.IDENTITY,
        FindingSeverity.HIGH,
        r"(?:\+\d{1,3}[\s-]?)?(?:\(\d{3}\)|\b\d{3})[\s.-]\d{3,4}[\s.-]\d{4}\b|\b1[3-9]\d{9}\b",
        "contains a phone number",
    ),
    _Rule(
        "IDENTITY_HANDLE",
        PrivacyCategoryV1.IDENTITY,
        FindingSeverity.MEDIUM,
        r"(?<![A-Z0-9._%+-])@[A-Z][A-Z0-9_]{2,}\b",
        "contains a social handle",
    ),
    _Rule(
        "LOCATION_STREET_ADDRESS",
        PrivacyCategoryV1.LOCATION,
        FindingSeverity.HIGH,
        r"\b\d{1,6}\s+[A-Z][A-Za-z]*\s*"
        r"(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Boulevard|Blvd|Drive|Dr|Way|Court|Ct)\b",
        "contains a street address",
    ),
    _Rule(
        "LOCATION_UNIT",
        PrivacyCategoryV1.LOCATION,
        FindingSeverity.HIGH,
        r"\b(?:Apt|Apartment|Suite|Ste|Unit|Floor)\.?\s*#?\s*\d+\b|\d+\s*(?:室|号楼|单元)",
        "contains a unit or apartment number",
    ),
    _Rule(
        "LOCATION_CN_ADDRESS",
        PrivacyCategoryV1.LOCATION,
        FindingSeverity.HIGH,
        r".{1,10}(?:省|市|区|县).{0,20}(?:路|街|道|巷).{0,10}\d+\s*号",
        "contains a Chinese street address",
    ),
    _Rule(
        "LOCATION_POSTAL_CODE",
        PrivacyCategoryV1.LOCATION,
        FindingSeverity.MEDIUM,
        # Both colon forms are intentional: user text arrives in either script.
        r"\b\d{5}(?:-\d{4})?\b(?=[^\d]*(?:USA|United States))|\b邮编\s*[:：]?\s*\d{6}\b",  # noqa: RUF001
        "contains a postal code",
    ),
    _Rule(
        "PURCHASE_ORDER_ID",
        PrivacyCategoryV1.PURCHASE_PAYMENT,
        FindingSeverity.HIGH,
        r"\border\s*(?:#|no\.?|number)\s*[A-Z0-9][A-Z0-9-]{3,}"
        r"|订单\s*(?:号|编号)\s*[:：]?\s*[A-Z0-9-]{4,}",  # noqa: RUF001
        "contains an order identifier",
    ),
    _Rule(
        "PURCHASE_CARD",
        PrivacyCategoryV1.PURCHASE_PAYMENT,
        FindingSeverity.CRITICAL,
        r"\b(?:\d{4}[\s-]){3}\d{4}\b|\b(?:credit card|debit card|信用卡|银行卡)\b",
        "references a payment card",
    ),
    _Rule(
        "PURCHASE_AMOUNT",
        PrivacyCategoryV1.PURCHASE_PAYMENT,
        FindingSeverity.MEDIUM,
        r"[$¥€£]\s?\d[\d,]*(?:\.\d{2})?\b|\b\d[\d,]*\s*(?:元|块钱)\b",
        "states a purchase amount",
    ),
    _Rule(
        "THIRD_PARTY_RELATION",
        PrivacyCategoryV1.THIRD_PARTY,
        FindingSeverity.MEDIUM,
        r"\bmy\s+(?:colleague|coworker|co-worker|boss|manager|client|friend|wife|husband|"
        r"partner|neighbou?r|landlord|doctor|therapist|child|son|daughter)\b"
        r"|我(?:的)?(?:同事|老板|上司|客户|朋友|邻居|房东|医生|爱人|妻子|丈夫|孩子|儿子|女儿)",
        "describes an identifiable third party",
    ),
    _Rule(
        "HEALTH_CONDITION",
        PrivacyCategoryV1.HEALTH_BODY,
        FindingSeverity.MEDIUM,
        r"\b(?:back pain|neck pain|chronic pain|herniat\w+|sciatica|injury|injured|"
        r"diagnos\w+|prescription|surgery|physiotherapy|physical therapy)\b"
        r"|(?:腰痛|颈椎|腰椎|受伤|确诊|诊断|处方|手术|理疗)",
        "describes a health condition or treatment",
    ),
    _Rule(
        "HEALTH_BODY_METRIC",
        PrivacyCategoryV1.HEALTH_BODY,
        FindingSeverity.MEDIUM,
        r"\b(?:my (?:weight|height|bmi)|i weigh)\b|(?:我的?体重|我的?身高)",
        "states a personal body metric",
    ),
    _Rule(
        "SCREENSHOT_ARTIFACT",
        PrivacyCategoryV1.SCREENSHOT_METADATA,
        FindingSeverity.HIGH,
        r"\bscreen ?shot\b|\bIMG_\d+\b|\bEXIF\b|\b[\w-]+\.(?:png|jpe?g|heic)\b|截图|屏幕截图",
        "references a screenshot or image file that may carry metadata",
    ),
    _Rule(
        "COPYRIGHT_NOTICE",
        PrivacyCategoryV1.COPYRIGHT,
        FindingSeverity.MEDIUM,
        r"©|\(c\)\s*\d{4}|\ball rights reserved\b|\breprinted from\b|转载|版权所有",
        "reproduces third-party copyrighted material",
    ),
    _Rule(
        "BRAND_SUPERLATIVE",
        PrivacyCategoryV1.UNVERIFIED_BRAND_CLAIM,
        FindingSeverity.MEDIUM,
        r"\b(?:the best .{0,30}(?:on the market|available)|#1\b|number one\b|"
        r"officially (?:certified|endorsed|approved)|guaranteed to)\b"
        r"|(?:全网最|第一品牌|官方认证|保证有效)",
        "makes an unverified superlative or endorsement claim",
    ),
    _Rule(
        "PROFESSIONAL_ADVICE",
        PrivacyCategoryV1.PROFESSIONAL_ADVICE,
        FindingSeverity.HIGH,
        r"\byou should (?:take|use|stop taking|see a (?:doctor|lawyer))\b"
        r"|\b(?:medical|legal|financial) advice\b"
        r"|(?:建议你(?:服用|停药|就医)|医疗建议|法律建议|投资建议)",
        "gives advice that reads as professional guidance",
    ),
)


def _scan_text(text: str) -> list[_Rule]:
    return [rule for rule in _RULES if rule.pattern.search(text)]


def detect_text_privacy_proposals(
    statements: Iterable[Statement],
) -> list[PrivacyFindingProposalV1]:
    """Scan canonical statement text and return untrusted bounded proposals.

    One proposal per (statement, category) pair. Grouping by category rather than
    by rule keeps the user's decision list short: three rules firing for the same
    address are one location risk to resolve, not three.
    """

    proposals: list[PrivacyFindingProposalV1] = []
    for statement in sorted(statements, key=lambda item: str(item.statement_id)):
        if statement.status is StatementStatus.UNRESOLVED or statement.confirmation in {
            ConfirmationState.CORRECTED,
            ConfirmationState.REJECTED,
        }:
            continue
        by_category: dict[PrivacyCategoryV1, list[_Rule]] = {}
        for rule in _scan_text(statement.text):
            by_category.setdefault(rule.category, []).append(rule)
        for category in sorted(by_category, key=lambda item: item.value):
            matched = by_category[category]
            severity = max((rule.severity for rule in matched), key=_severity_rank)
            reasons = ", ".join(sorted(rule.description for rule in matched))
            proposals.append(
                PrivacyFindingProposalV1(
                    category=category,
                    affected_statement_ids=[statement.statement_id],
                    severity=severity,
                    explanation=(
                        f"Deterministic text detector {PRIVACY_TEXT_DETECTOR_VERSION} "
                        f"found content that {reasons}; confirm before external sharing."
                    ),
                )
            )
    return proposals


_SEVERITY_ORDER: dict[FindingSeverity, int] = {
    FindingSeverity.LOW: 0,
    FindingSeverity.MEDIUM: 1,
    FindingSeverity.HIGH: 2,
    FindingSeverity.CRITICAL: 3,
}


def _severity_rank(severity: FindingSeverity) -> int:
    return _SEVERITY_ORDER[severity]


def detector_rule_ids() -> Sequence[str]:
    """Expose the rule set so evidence can record exactly what was scanned."""

    return tuple(rule.rule_id for rule in _RULES)
