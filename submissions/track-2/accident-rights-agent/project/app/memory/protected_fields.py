"""Deterministic protected-field extraction and loss detection."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.schemas.memory import ProtectedField, ProtectedFieldKind


class ProtectedFieldLoss(RuntimeError):
    pass


KEY_RULES: tuple[tuple[re.Pattern[str], ProtectedFieldKind], ...] = (
    (re.compile(r"(date|日期|时间)$", re.I), ProtectedFieldKind.DATE),
    (re.compile(r"(deadline|due_at|截止|期限)", re.I), ProtectedFieldKind.DEADLINE),
    (re.compile(r"(amount|金额|损失|费用)$", re.I), ProtectedFieldKind.AMOUNT),
    (re.compile(r"(ratio|比例|责任比例)", re.I), ProtectedFieldKind.LIABILITY_RATIO),
    (re.compile(r"(plate|车牌|vehicle_id|车辆标识)", re.I), ProtectedFieldKind.VEHICLE_ID),
    (re.compile(r"(party_role|当事人角色|角色)$", re.I), ProtectedFieldKind.PARTY_ROLE),
    (re.compile(r"(evidence_id|node_id)", re.I), ProtectedFieldKind.EVIDENCE_ID),
    (re.compile(r"fact_id", re.I), ProtectedFieldKind.FACT_ID),
    (re.compile(r"law_id$", re.I), ProtectedFieldKind.LAW_ID),
    (re.compile(r"(document_version|法律版本|version)$", re.I), ProtectedFieldKind.DOCUMENT_VERSION),
    (re.compile(r"(approval_status|审批状态)", re.I), ProtectedFieldKind.APPROVAL_STATUS),
)

VALUE_RULES: tuple[tuple[re.Pattern[str], ProtectedFieldKind], ...] = (
    (re.compile(r"\b(?:SRC|NODE|EVID)-[A-Z0-9_-]+\b"), ProtectedFieldKind.EVIDENCE_ID),
    (re.compile(r"\bFACT-[A-Z0-9_-]+\b"), ProtectedFieldKind.FACT_ID),
    (re.compile(r"\bLAW-[A-Z0-9_-]+\b"), ProtectedFieldKind.LAW_ID),
    (
        re.compile(r"(?:[\u4e00-\u9fff][A-Z][A-Z0-9]{5,6}|\b[A-HJ-NPR-Z0-9]{17}\b)"),
        ProtectedFieldKind.VEHICLE_ID,
    ),
    (
        re.compile(
            r"(?:机动车驾驶人|非机动车驾驶人|两轮车辆驾驶人|"
            r"被保险人|受害人|侵权人|投保人)"
        ),
        ProtectedFieldKind.PARTY_ROLE,
    ),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[0-9:+.-]+Z?)?\b"), ProtectedFieldKind.DATE),
    (re.compile(r"(?:¥|￥)\s?\d+(?:\.\d+)?|\b\d+(?:\.\d+)?元\b"), ProtectedFieldKind.AMOUNT),
    (re.compile(r"\b\d+(?:\.\d+)?%\b"), ProtectedFieldKind.LIABILITY_RATIO),
)


def collect_protected_fields(value: Any) -> list[ProtectedField]:
    found: dict[tuple[str, str], ProtectedField] = {}

    def visit(item: Any, path: str, key_name: str = "") -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                child_path = f"{path}.{key}" if path else str(key)
                visit(child, child_path, str(key))
            return
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]", key_name)
            return
        if item is None:
            return
        text = (
            json.dumps(item, ensure_ascii=False, sort_keys=True)
            if not isinstance(item, str)
            else item
        )
        for pattern, kind in KEY_RULES:
            if pattern.search(key_name):
                entry = ProtectedField(kind=kind, value=text, source_path=path or "$")
                found[(kind.value, text)] = entry
        for pattern, kind in VALUE_RULES:
            for match in pattern.finditer(text):
                matched = match.group(0)
                entry = ProtectedField(
                    kind=kind, value=matched, source_path=path or "$"
                )
                found[(kind.value, matched)] = entry

    visit(value, "$")
    return sorted(found.values(), key=lambda item: (item.kind.value, item.value))


def protected_set(value: Any) -> set[tuple[str, str]]:
    return {
        (item.kind.value, item.value) for item in collect_protected_fields(value)
    }


def assert_protected_fields_preserved(before: Any, after: Any) -> None:
    before_set = protected_set(before)
    after_set = protected_set(after)
    missing = sorted(before_set - after_set)
    if missing:
        raise ProtectedFieldLoss(
            "Protected fields were lost: "
            + ", ".join(f"{kind}={value}" for kind, value in missing)
        )
