"""Validate every LegalCitation and Rule ID against local authoritative stores."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.rag.corpus import LegalCorpusStore
from app.rules.repository import RuleRepository
from app.schemas.legal import LegalCitation
from app.schemas.verification import (
    ComponentVerifierResult,
    VerificationIssue,
    VerificationSeverity,
)


class LegalCitationVerifier:
    def __init__(self, corpus: LegalCorpusStore, rules: RuleRepository):
        self.corpus = corpus
        self.rules = rules

    def verify(
        self,
        *,
        state: dict[str, Any],
        as_of_date: date,
        jurisdiction: str = "CN",
    ) -> ComponentVerifierResult:
        issues: list[VerificationIssue] = []
        verified: set[str] = set()
        citation_payloads = _collect_citations(state)
        for payload in citation_payloads:
            source_id = str(payload.get("source_id", "?"))
            try:
                citation = LegalCitation.model_validate(payload)
                chunk = self.corpus.get_chunk(citation.source_id)
                mismatches = []
                for field in (
                    "document_id",
                    "article_no",
                    "paragraph_no",
                    "item_no",
                    "version",
                    "jurisdiction",
                ):
                    if getattr(citation, field) != getattr(chunk, field):
                        mismatches.append(field)
                if mismatches:
                    raise ValueError(
                        "citation differs from indexed official chunk: "
                        + ", ".join(mismatches)
                    )
                if not citation.is_applicable(as_of_date):
                    raise ValueError(
                        f"citation is not effective on {as_of_date.isoformat()}"
                    )
                if citation.jurisdiction not in {
                    "CN",
                    "中华人民共和国",
                    jurisdiction,
                }:
                    raise ValueError(
                        f"wrong jurisdiction: {citation.jurisdiction}/{jurisdiction}"
                    )
                verified.add(citation.source_id)
            except Exception as exc:
                issues.append(
                    VerificationIssue(
                        code="LEGAL-CITATION-INVALID",
                        message=f"{source_id}: {type(exc).__name__}: {exc}",
                        severity=VerificationSeverity.BLOCKING,
                        related_ids=[source_id],
                        required_action=(
                            "Replace with a current, case-applicable citation from "
                            "the local authoritative corpus."
                        ),
                    )
                )

        for rule_id in sorted(_collect_ids(state, "rule_id", "RULE-")):
            try:
                self.rules.get(
                    rule_id,
                    as_of_date=as_of_date,
                    jurisdiction=jurisdiction,
                )
                verified.add(rule_id)
            except Exception as exc:
                issues.append(
                    VerificationIssue(
                        code="LEGAL-RULE-INVALID",
                        message=f"{rule_id}: {type(exc).__name__}: {exc}",
                        severity=VerificationSeverity.BLOCKING,
                        related_ids=[rule_id],
                        required_action=(
                            "Select an effective rule for the case date and jurisdiction."
                        ),
                    )
                )
        referenced_law_ids = _collect_ids(state, "law_id", "")
        available_chunks = self.corpus.list_chunks(status=None)
        available_documents = {item.document_id for item in available_chunks}
        available_sources = {item.source_id for item in available_chunks}
        for law_id in sorted(referenced_law_ids):
            if law_id in verified or law_id in available_documents or law_id in available_sources:
                verified.add(law_id)
                continue
            issues.append(
                VerificationIssue(
                    code="LEGAL-LAW-ID-NOT-FOUND",
                    message=f"Law ID is not resolvable in the local corpus: {law_id}",
                    severity=VerificationSeverity.BLOCKING,
                    related_ids=[law_id],
                    required_action="Use a local corpus document_id/source_id.",
                )
            )
        if not citation_payloads:
            issues.append(
                VerificationIssue(
                    code="LEGAL-NO-CITATIONS",
                    message="No verifier-ready LegalCitation was provided.",
                    severity=VerificationSeverity.BLOCKING,
                    required_action="Attach current official LegalCitation objects.",
                )
            )
        return ComponentVerifierResult(
            verifier="legal",
            passed=not issues,
            issues=issues,
            verified_ids=sorted(verified),
        )


def _collect_citations(value: Any) -> list[dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            if {
                "source_id",
                "document_id",
                "quote",
                "version",
                "effective_date",
                "source_url",
            } <= set(item):
                results[str(item["source_id"])] = item
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return list(results.values())


def _collect_ids(value: Any, key_fragment: str, prefix: str) -> set[str]:
    results: set[str] = set()

    def visit(item: Any, key: str = "") -> None:
        if isinstance(item, dict):
            for child_key, child in item.items():
                visit(child, str(child_key))
        elif isinstance(item, list):
            for child in item:
                visit(child, key)
        elif isinstance(item, str):
            if key_fragment in key.lower() and (not prefix or item.startswith(prefix)):
                results.add(item)

    visit(value)
    return results
