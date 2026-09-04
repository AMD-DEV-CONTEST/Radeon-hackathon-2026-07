"""Deterministic extraction of delivery dates from confirmed case facts."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.schemas.rights import (
    DeliveryDateCandidate,
    DeliveryDateResult,
    DeliveryDateStatus,
)

DATE_PATTERN = re.compile(r"(?P<year>\d{4})[-年/](?P<month>\d{1,2})[-月/](?P<day>\d{1,2})日?")
TRUSTED_FACT_STATUSES = {"confirmed", "verified"}


class DeliveryDateExtractor:
    """Never infers a legal trigger from a document issue/signature date."""

    def extract(
        self,
        *,
        facts: list[dict[str, Any]],
        evidence_nodes: list[dict[str, Any]] | None = None,
        sources: list[dict[str, Any]] | None = None,
        manual_date: date | str | None = None,
        manual_source_id: str = "USER-INPUT",
        timezone: str = "Asia/Shanghai",
    ) -> DeliveryDateResult:
        node_map = {
            str(item.get("node_id")): item for item in (evidence_nodes or [])
        }
        source_map = {
            str(item.get("source_id")): item for item in (sources or [])
        }
        candidates: list[DeliveryDateCandidate] = []
        if manual_date is not None:
            parsed = (
                manual_date if isinstance(manual_date, date) else date.fromisoformat(manual_date)
            )
            candidates.append(
                DeliveryDateCandidate(
                    date_type="manual_confirmed_delivery_date",
                    extracted_date=parsed,
                    raw_text=parsed.isoformat(),
                    source_type="human_explicit_input",
                    source_id=manual_source_id,
                    extraction_method="deterministic_iso_date_parser",
                    confidence=1.0,
                    priority=100,
                    is_delivery_evidence=True,
                )
            )

        for fact in facts:
            text = " ".join(
                str(fact.get(key, ""))
                for key in ("statement", "subject", "predicate", "value")
            )
            matches = list(DATE_PATTERN.finditer(text))
            if not matches:
                continue
            classification = self._classify(text, str(fact.get("predicate", "")))
            if classification is None:
                continue
            date_type, priority, base_confidence, is_delivery = classification
            status = str(fact.get("status", "")).lower()
            if status not in TRUSTED_FACT_STATUSES:
                base_confidence = min(base_confidence, 0.55)
            node_ids = [
                str(value)
                for value in fact.get("source_node_ids", [])
                if value
            ]
            evidence_id = node_ids[0] if node_ids else None
            node = node_map.get(evidence_id or "", {})
            source_id = str(node.get("source_id") or "") or None
            source = source_map.get(source_id or "", {})
            source_type = str(
                source.get("role")
                or source.get("kind")
                or node.get("node_type")
                or "case_fact"
            )
            for match in matches:
                try:
                    parsed = date(
                        int(match.group("year")),
                        int(match.group("month")),
                        int(match.group("day")),
                    )
                except ValueError:
                    continue
                candidates.append(
                    DeliveryDateCandidate(
                        date_type=date_type,
                        extracted_date=parsed,
                        raw_text=match.group(0),
                        source_type=source_type,
                        source_id=source_id,
                        evidence_id=evidence_id,
                        extraction_method="deterministic_fact_date_parser",
                        confidence=base_confidence,
                        priority=priority,
                        is_delivery_evidence=is_delivery,
                    )
                )

        candidates = self._deduplicate(candidates)
        trusted_delivery = [
            item
            for item in candidates
            if item.is_delivery_evidence and item.confidence >= 0.7
        ]
        distinct = {item.extracted_date for item in trusted_delivery}
        if len(distinct) > 1:
            return DeliveryDateResult(
                status=DeliveryDateStatus.DISPUTED,
                date_type="disputed_delivery_date",
                source_type="multiple_conflicting_sources",
                extraction_method="deterministic_conflict_detection",
                confidence=0.0,
                timezone=timezone,
                ambiguity=[
                    "多个可信送达日期相互冲突，系统未自动选择。",
                    *[
                        f"{item.extracted_date.isoformat()} from "
                        f"{item.source_type}/{item.evidence_id or item.source_id}"
                        for item in trusted_delivery
                    ],
                ],
                alternatives=candidates,
                requires_human_confirmation=True,
            )
        if trusted_delivery:
            selected = sorted(
                trusted_delivery,
                key=lambda item: (item.priority, item.confidence),
                reverse=True,
            )[0]
            untrusted_conflicts = {
                item.extracted_date
                for item in candidates
                if item.is_delivery_evidence and item.extracted_date != selected.extracted_date
            }
            return DeliveryDateResult(
                status=DeliveryDateStatus.CONFIRMED,
                date_type=selected.date_type,
                extracted_date=selected.extracted_date,
                original_date_text=selected.raw_text,
                source_type=selected.source_type,
                source_id=selected.source_id,
                evidence_id=selected.evidence_id,
                extraction_method=selected.extraction_method,
                confidence=selected.confidence,
                timezone=timezone,
                ambiguity=(
                    ["存在低置信度不同日期，已要求人工复核。"]
                    if untrusted_conflicts
                    else []
                ),
                alternatives=candidates,
                requires_human_confirmation=bool(untrusted_conflicts),
            )

        weak = [item for item in candidates if not item.is_delivery_evidence]
        if weak:
            return DeliveryDateResult(
                status=DeliveryDateStatus.WEAK_EVIDENCE,
                date_type="document_date_only",
                source_type=weak[0].source_type,
                source_id=weak[0].source_id,
                evidence_id=weak[0].evidence_id,
                extraction_method="deterministic_weak_evidence_guard",
                confidence=max(item.confidence for item in weak),
                timezone=timezone,
                ambiguity=["文书落款/作出日期不是送达日期，不得自动起算。"],
                alternatives=candidates,
                requires_human_confirmation=True,
            )
        return DeliveryDateResult(
            status=DeliveryDateStatus.MISSING,
            date_type="missing_delivery_date",
            source_type="none",
            extraction_method="deterministic_absence_check",
            confidence=0.0,
            timezone=timezone,
            ambiguity=["未找到可确认的送达日期。"],
            alternatives=[],
            requires_human_confirmation=True,
        )

    @staticmethod
    def _classify(
        text: str, predicate: str
    ) -> tuple[str, int, float, bool] | None:
        if any(value in text for value in ("送达回执", "回执送达")):
            return ("delivery_receipt_date", 95, 0.97, True)
        if any(value in text for value in ("签收记录", "签收日期", "签收时间")):
            return ("signed_receipt_date", 90, 0.94, True)
        if any(value in text for value in ("短信送达", "电子送达", "平台送达")):
            return ("electronic_delivery_date", 85, 0.90, True)
        if "送达" in text or "送达" in predicate:
            return ("document_delivery_date", 80, 0.88, True)
        if any(value in text for value in ("落款日期", "文书日期", "作出日期", "签发日期")):
            return ("document_issue_date", 10, 0.35, False)
        return None

    @staticmethod
    def _deduplicate(
        candidates: list[DeliveryDateCandidate],
    ) -> list[DeliveryDateCandidate]:
        unique: dict[tuple[date, str, str | None, str | None], DeliveryDateCandidate] = {}
        for item in candidates:
            key = (
                item.extracted_date,
                item.date_type,
                item.source_id,
                item.evidence_id,
            )
            existing = unique.get(key)
            if existing is None or item.confidence > existing.confidence:
                unique[key] = item
        return sorted(
            unique.values(),
            key=lambda item: (item.priority, item.confidence, item.extracted_date),
            reverse=True,
        )
