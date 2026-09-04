"""Evidence-cited review-application drafts that always remain drafts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.schemas.legal import LegalCitation
from app.schemas.rights import (
    DeliveryDateResult,
    DraftFactSentence,
    ReviewApplicationDraft,
)
from app.verifier.risk_language import RiskLanguagePolicy

USABLE_FACT_STATUSES = {"confirmed", "verified"}
DISPUTED_FACT_STATUSES = {"unverified", "disputed"}


class ReviewApplicationDraftGenerator:
    def __init__(self, risk_policy: RiskLanguagePolicy | None = None):
        self.risk_policy = risk_policy or RiskLanguagePolicy()

    def generate(
        self,
        *,
        case_id: str,
        facts: list[dict[str, Any]],
        legal_citations: list[LegalCitation],
        delivery: DeliveryDateResult,
        applicant: dict[str, str | None] | None = None,
        challenged_document: dict[str, str | None] | None = None,
        missing_evidence: list[dict[str, Any]] | None = None,
        document_version: int = 1,
    ) -> ReviewApplicationDraft:
        applicant_data = {
            "name": None,
            "identity_or_role": None,
            "contact": None,
            **(applicant or {}),
        }
        document_data = {
            "document_number": None,
            "issuing_authority": None,
            "document_date": None,
            "delivery_date": (
                delivery.extracted_date.isoformat()
                if delivery.extracted_date
                else None
            ),
            **(challenged_document or {}),
        }
        fact_sentences: list[DraftFactSentence] = []
        excluded_risk_patterns: list[str] = []
        for fact in facts:
            status = str(fact.get("status", "unverified")).lower()
            if status == "rejected":
                continue
            fact_id = str(fact.get("fact_id", ""))
            evidence_ids = [
                str(value) for value in fact.get("source_node_ids", []) if value
            ]
            if not fact_id.startswith("FACT-") or not evidence_ids:
                continue
            safe_text, findings = self.risk_policy.safe_text(
                str(fact.get("statement", ""))
            )
            excluded_risk_patterns.extend(findings)
            if not safe_text:
                continue
            qualification = None
            if status in DISPUTED_FACT_STATUSES:
                qualification = "待核实/申请调取，不作为既定事实"
                safe_text = f"待核实：{safe_text}"
            fact_sentences.append(
                DraftFactSentence(
                    text=safe_text,
                    fact_ids=[fact_id],
                    evidence_ids=evidence_ids,
                    fact_status=status,
                    qualification=qualification,
                )
            )

        legal_basis = [
            item
            for item in legal_citations
            if item.document_id == "CN-RULE-ACCIDENT-PROCEDURE-2017"
            and item.article_no in {"第七十一条", "第七十四条"}
        ]
        blocking_fields: list[str] = []
        if not applicant_data["name"]:
            blocking_fields.append("applicant.name")
        if not applicant_data["identity_or_role"]:
            blocking_fields.append("applicant.identity_or_role")
        if not document_data["document_number"]:
            blocking_fields.append("challenged_document.document_number")
        if not delivery.extracted_date:
            blocking_fields.append("challenged_document.delivery_date")
        if not fact_sentences:
            blocking_fields.append("facts")
        if not legal_basis:
            blocking_fields.append("legal_basis")

        evidence_catalog = [
            {
                "fact_id": sentence.fact_ids[0],
                "evidence_ids": sentence.evidence_ids,
                "description": sentence.text,
                "status": sentence.fact_status,
            }
            for sentence in fact_sentences
        ]
        gaps = missing_evidence or []
        disputed_issues = [
            sentence.text
            for sentence in fact_sentences
            if sentence.fact_status in DISPUTED_FACT_STATUSES
        ] + [
            f"待补证：{item.get('reason') or item.get('category')}"
            for item in gaps
        ]
        requests = [
            "请求依法对事故认定的事实、证据、法律适用、责任划分及程序进行复核。",
            "请求依法审查本申请所列争议焦点和证据目录。",
        ]
        review_reasons = [
            (
                f"事实与证据需结合证据目录逐项审查；本草稿引用"
                f"{len(fact_sentences)}项案件事实，不对争议事实作确定性陈述。"
            ),
            "车辆技术标准符合性与车辆法律属性应分别核验。",
            "事故责任、民事赔偿责任与保险赔付结果应分别判断。",
        ]
        payload_for_hash = {
            "case_id": case_id,
            "applicant": applicant_data,
            "challenged_document": document_data,
            "facts": [item.model_dump(mode="json") for item in fact_sentences],
            "legal_basis": [item.model_dump(mode="json") for item in legal_basis],
            "document_version": document_version,
        }
        inputs_hash = hashlib.sha256(
            json.dumps(
                payload_for_hash,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        not_submittable = [
            f"缺少或未确认：{field}" for field in blocking_fields
        ]
        if delivery.requires_human_confirmation:
            not_submittable.append("送达日期仍需人工确认。")
        return ReviewApplicationDraft(
            document_id=f"DRAFT-REVIEW-{case_id}",
            document_version=document_version,
            applicant=applicant_data,
            challenged_document=document_data,
            requests=requests,
            facts=fact_sentences,
            disputed_issues=disputed_issues,
            review_reasons=review_reasons,
            evidence_catalog=evidence_catalog,
            legal_basis=legal_basis,
            attachments=sorted(
                {
                    evidence_id
                    for sentence in fact_sentences
                    for evidence_id in sentence.evidence_ids
                }
            ),
            signature_placeholder="申请人签名：____________",
            date_placeholder="日期：____年__月__日",
            blocking_fields=blocking_fields,
            not_submittable_reasons=not_submittable,
            risk_language_findings=sorted(set(excluded_risk_patterns)),
            inputs_hash=inputs_hash,
        )
