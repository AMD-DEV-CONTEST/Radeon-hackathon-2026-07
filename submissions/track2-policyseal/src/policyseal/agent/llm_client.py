from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Protocol
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from policyseal.agent.schemas import (
    ClassificationBatch,
    LocalCompletion,
    SemanticRegionInput,
)
from policyseal.domain.enums import ContentCategory, FileKind


class LocalInferenceError(RuntimeError):
    """A controlled local inference failure with no prompt content."""


class LocalInferenceUnavailable(LocalInferenceError):
    """The configured localhost model endpoint is unavailable."""


class CompletionClient(Protocol):
    def complete(self, regions: tuple[SemanticRegionInput, ...]) -> LocalCompletion: ...


class _Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = 0
    completion_tokens: int = 0


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str


class _Choice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: _Message


class _CompletionEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    choices: tuple[_Choice, ...]
    usage: _Usage = _Usage()


def _validated_local_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("the model endpoint must be an uncredentialed localhost HTTP URL")
    return base_url.rstrip("/")


class LocalVllmClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_seconds: float = 30,
        max_tokens: int = 1_200,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = _validated_local_base_url(base_url)
        self.endpoint = f"{self.base_url}/chat/completions"
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self._http_client = http_client

    def complete(self, regions: tuple[SemanticRegionInput, ...]) -> LocalCompletion:
        if not regions:
            return LocalCompletion('{"classifications":[]}', 0, 0, 0)
        payload = self._payload(regions)
        started = time.perf_counter()
        try:
            if self._http_client is None:
                with httpx.Client(
                    timeout=self.timeout_seconds,
                    follow_redirects=False,
                ) as client:
                    response = client.post(self.endpoint, json=payload)
            else:
                response = self._http_client.post(
                    self.endpoint,
                    json=payload,
                    timeout=self.timeout_seconds,
                    follow_redirects=False,
                )
            response.raise_for_status()
            envelope = _CompletionEnvelope.model_validate(response.json())
            if len(envelope.choices) != 1:
                raise LocalInferenceError("local model returned an invalid choice count")
        except (httpx.HTTPError, ValidationError, ValueError, json.JSONDecodeError) as error:
            raise LocalInferenceUnavailable("local model request failed") from error
        latency_ms = (time.perf_counter() - started) * 1_000
        return LocalCompletion(
            content=envelope.choices[0].message.content,
            latency_ms=latency_ms,
            prompt_tokens=envelope.usage.prompt_tokens,
            completion_tokens=envelope.usage.completion_tokens,
        )

    def _payload(self, regions: Sequence[SemanticRegionInput]) -> dict[str, object]:
        categories = _categories_for_regions(regions)
        category_evidence = {
            category.value: list(_category_evidence_for_regions(category, regions))
            for category in categories
        }
        user_payload = {
            "regions": [region.model_dump(mode="json") for region in regions],
            "allowed_category_evidence": category_evidence,
            "category_guide": {
                category.value: CATEGORY_GUIDANCE[category] for category in categories
            },
        }
        schema = ClassificationBatch.model_json_schema()
        schema["$defs"]["ContentCategory"]["enum"] = [category.value for category in categories]
        classification_schema = schema["properties"]["classifications"]
        classification_schema["minItems"] = len(regions)
        classification_schema["maxItems"] = len(regions)
        schema["$defs"]["ModelClassification"]["properties"]["region_id"]["enum"] = [
            region.region_id for region in regions
        ]
        schema["$defs"]["ModelClassification"]["properties"]["evidence_ids"]["items"]["enum"] = (
            sorted({item for values in category_evidence.values() for item in values})
        )
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Classify each document region into exactly one allowed content category. "
                        "Use the file-specific category guide and choose the dominant meaning, "
                        "not a merely mentioned secondary detail. Return JSON only. Every "
                        "classification object must contain only region_id, category, and "
                        "evidence_ids. Return every region exactly once in input order, preserve "
                        "each region_id exactly, and cite one to three evidence IDs allowed for "
                        "the selected category. Do not provide reasoning."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        user_payload,
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ],
            "temperature": 0,
            "top_p": 1,
            "max_tokens": self.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "policyseal_semantic_classification",
                    "strict": True,
                    "schema": schema,
                },
            },
            "chat_template_kwargs": {"enable_thinking": False},
        }


FILE_KIND_CATEGORIES: dict[FileKind, tuple[ContentCategory, ...]] = {
    FileKind.XLSX: (
        ContentCategory.GENERAL_BUSINESS,
        ContentCategory.SUPPLIER_IDENTITY,
        ContentCategory.CONTACT_PERSONAL,
        ContentCategory.BANK_PAYMENT,
        ContentCategory.QUOTE_COMMERCIAL_TERMS,
        ContentCategory.INTERNAL_COST_BUDGET,
        ContentCategory.SCORE_RANKING,
        ContentCategory.INTERNAL_OPINION_APPROVAL,
    ),
    FileKind.DOCX: (
        ContentCategory.GENERAL_BUSINESS,
        ContentCategory.INCIDENT_FACT_TIMELINE,
        ContentCategory.EXTERNAL_THREAT_INDICATOR,
        ContentCategory.INTERNAL_INFRASTRUCTURE,
        ContentCategory.NETWORK_LOG,
        ContentCategory.CREDENTIAL_SECRET,
        ContentCategory.VULNERABILITY_FACT,
        ContentCategory.EXPLOIT_PAYLOAD,
        ContentCategory.PERSON_IDENTITY,
        ContentCategory.INTERNAL_ACCOUNT,
        ContentCategory.ORGANIZATIONAL_ROLE,
        ContentCategory.CONTACT_DETAIL,
        ContentCategory.INTERNAL_ATTRIBUTION,
        ContentCategory.REMEDIATION,
        ContentCategory.REMEDIATION_OWNER,
        ContentCategory.REMEDIATION_BUDGET_COMMENT,
    ),
    FileKind.PDF: (
        ContentCategory.GENERAL_BUSINESS,
        ContentCategory.CONTACT_PERSONAL,
        ContentCategory.BANK_PAYMENT,
        ContentCategory.CONTRACT_BUYER,
        ContentCategory.CONTRACT_SUPPLIER,
        ContentCategory.CORPORATE_IDENTIFIER,
        ContentCategory.CONTRACT_DATE_IDENTIFIER,
        ContentCategory.RELATIVE_PERFORMANCE_TERM,
        ContentCategory.HISTORICAL_PRICING,
        ContentCategory.STANDARD_LEGAL_TERM,
        ContentCategory.NONSTANDARD_OBLIGATION,
        ContentCategory.SIGNATURE,
        ContentCategory.SOURCE_METADATA,
    ),
}


CATEGORY_GUIDANCE: dict[ContentCategory, str] = {
    ContentCategory.GENERAL_BUSINESS: (
        "Neutral document context or workflow status with no more specific protected meaning."
    ),
    ContentCategory.SUPPLIER_IDENTITY: (
        "A supplier company identity or controlled supplier owner code in a sourcing workbook."
    ),
    ContentCategory.CONTACT_PERSONAL: (
        "A named business contact or their work email, telephone number, or similar contact data."
    ),
    ContentCategory.BANK_PAYMENT: (
        "A bank, beneficiary, routing code, account number, or payment instruction."
    ),
    ContentCategory.QUOTE_COMMERCIAL_TERMS: (
        "Terms offered by a bidder, such as quoted price, payment period, volume price, "
        "or delivery commitment."
    ),
    ContentCategory.INTERNAL_COST_BUDGET: (
        "Buyer-private cost, budget, target or floor price, margin assumption, or "
        "negotiation limit."
    ),
    ContentCategory.SCORE_RANKING: (
        "An evaluation score, rank, placement, shortlist result, or generalized "
        "competitive standing."
    ),
    ContentCategory.INTERNAL_OPINION_APPROVAL: (
        "An internal approval, rejection, review judgment, warning, recommendation, or "
        "its rationale; choose this when a management decision is dominant even if a "
        "price is mentioned."
    ),
    ContentCategory.INCIDENT_FACT_TIMELINE: (
        "A security incident event, detection, containment fact, timestamp, or "
        "chronological response milestone."
    ),
    ContentCategory.EXTERNAL_THREAT_INDICATOR: (
        "An external malicious IP address, domain, file hash, drop site, or comparable "
        "indicator of compromise."
    ),
    ContentCategory.INTERNAL_INFRASTRUCTURE: (
        "An internal host, private address, service topology, application name, or "
        "environment naming convention."
    ),
    ContentCategory.NETWORK_LOG: (
        "Network or application log evidence such as requests, sessions, connection "
        "records, or repeated access events."
    ),
    ContentCategory.CREDENTIAL_SECRET: (
        "A password, token, private key, bearer credential, or other authentication secret."
    ),
    ContentCategory.VULNERABILITY_FACT: (
        "A vulnerable component, CVE, weakness, or observed unauthorized behavior that "
        "describes the flaw rather than an executable attack."
    ),
    ContentCategory.EXPLOIT_PAYLOAD: (
        "A complete executable command, attack script, replay instruction, or ready-to-run payload."
    ),
    ContentCategory.PERSON_IDENTITY: (
        "The identity or name of an employee or investigator, when the person is not "
        "specifically assigned a remediation action."
    ),
    ContentCategory.INTERNAL_ACCOUNT: (
        "An internal username, administrator account, service account identity, or "
        "employee-linked account name."
    ),
    ContentCategory.ORGANIZATIONAL_ROLE: (
        "A department, team, job role, or responsibility label without identifying a "
        "specific person."
    ),
    ContentCategory.CONTACT_DETAIL: (
        "An incident participant's email address, telephone number, or direct contact channel."
    ),
    ContentCategory.INTERNAL_ATTRIBUTION: (
        "Internal blame, fault attribution, personnel criticism, or performance judgment "
        "about a person or team."
    ),
    ContentCategory.REMEDIATION: (
        "A corrective action, patch, credential rotation, containment step, or remediation status."
    ),
    ContentCategory.REMEDIATION_OWNER: (
        "A specific named person or account assigned ownership of a remediation action."
    ),
    ContentCategory.REMEDIATION_BUDGET_COMMENT: (
        "A private remediation budget, board note, management comment, or spending cap."
    ),
    ContentCategory.CONTRACT_BUYER: "The original buyer party named in a contract.",
    ContentCategory.CONTRACT_SUPPLIER: "The original supplier party named in a contract.",
    ContentCategory.CORPORATE_IDENTIFIER: (
        "A contracting company's registered address, tax or registration number, or "
        "legal representative identity."
    ),
    ContentCategory.CONTRACT_DATE_IDENTIFIER: (
        "A contract or agreement number, effective date, expiry date, signature date, or "
        "other absolute deal identifier."
    ),
    ContentCategory.RELATIVE_PERFORMANCE_TERM: (
        "A standard relative deadline measured from an event, such as days after an "
        "accepted order; not a bespoke service-level promise."
    ),
    ContentCategory.HISTORICAL_PRICING: (
        "Commercial values from the old deal, including historic unit price, discount, "
        "custom tax rate, or legacy service credit."
    ),
    ContentCategory.STANDARD_LEGAL_TERM: (
        "Ordinary standard contract language, standard payment periods, or conventional "
        "liability terms."
    ),
    ContentCategory.NONSTANDARD_OBLIGATION: (
        "A bespoke or special obligation such as a custom service level, unusual "
        "indemnity, uncapped liability, or exact exceptional promise."
    ),
    ContentCategory.SIGNATURE: (
        "A signature, signer identity in a signature block, signing mark, company seal, "
        "or handwritten execution content."
    ),
    ContentCategory.SOURCE_METADATA: (
        "Document author metadata, annotation history, original path, producer field, or "
        "source-file provenance."
    ),
}


def _categories_for_regions(
    regions: Sequence[SemanticRegionInput],
) -> tuple[ContentCategory, ...]:
    selected: list[ContentCategory] = []
    for region in regions:
        for category in FILE_KIND_CATEGORIES[region.file_kind]:
            if category not in selected:
                selected.append(category)
    return tuple(selected)


def category_evidence_for_file(
    category: ContentCategory,
    file_kind: FileKind,
) -> tuple[str, ...]:
    prefix = f"EV-{file_kind.value.upper()}-"
    scoped = tuple(
        evidence_id
        for evidence_id in CATEGORY_EVIDENCE[category]
        if evidence_id.startswith(prefix) or evidence_id.startswith("EV-GEN-")
    )
    return scoped or CATEGORY_EVIDENCE[category]


def _category_evidence_for_regions(
    category: ContentCategory,
    regions: Sequence[SemanticRegionInput],
) -> tuple[str, ...]:
    selected: list[str] = []
    for region in regions:
        for evidence_id in category_evidence_for_file(category, region.file_kind):
            if evidence_id not in selected:
                selected.append(evidence_id)
    return tuple(selected)


CATEGORY_EVIDENCE: dict[ContentCategory, tuple[str, ...]] = {
    ContentCategory.UNCLASSIFIED: ("EV-GEN-002",),
    ContentCategory.GENERAL_BUSINESS: ("EV-GEN-003",),
    ContentCategory.SUPPLIER_IDENTITY: ("EV-XLSX-003", "EV-XLSX-004"),
    ContentCategory.CONTACT_PERSONAL: (
        "EV-XLSX-001",
        "EV-XLSX-002",
        "EV-PDF-001",
    ),
    ContentCategory.BANK_PAYMENT: ("EV-XLSX-001", "EV-XLSX-002", "EV-PDF-001"),
    ContentCategory.QUOTE_COMMERCIAL_TERMS: ("EV-XLSX-002", "EV-XLSX-003"),
    ContentCategory.INTERNAL_COST_BUDGET: ("EV-XLSX-001", "EV-XLSX-003"),
    ContentCategory.SCORE_RANKING: ("EV-XLSX-002", "EV-XLSX-003"),
    ContentCategory.INTERNAL_OPINION_APPROVAL: ("EV-XLSX-001", "EV-XLSX-003"),
    ContentCategory.INCIDENT_FACT_TIMELINE: ("EV-DOCX-001",),
    ContentCategory.EXTERNAL_THREAT_INDICATOR: ("EV-DOCX-001",),
    ContentCategory.INTERNAL_INFRASTRUCTURE: ("EV-DOCX-002",),
    ContentCategory.NETWORK_LOG: ("EV-DOCX-001",),
    ContentCategory.CREDENTIAL_SECRET: ("EV-DOCX-003",),
    ContentCategory.VULNERABILITY_FACT: ("EV-DOCX-001",),
    ContentCategory.EXPLOIT_PAYLOAD: ("EV-DOCX-003",),
    ContentCategory.PERSON_IDENTITY: ("EV-DOCX-002",),
    ContentCategory.INTERNAL_ACCOUNT: ("EV-DOCX-002",),
    ContentCategory.ORGANIZATIONAL_ROLE: ("EV-DOCX-004",),
    ContentCategory.CONTACT_DETAIL: ("EV-DOCX-004",),
    ContentCategory.INTERNAL_ATTRIBUTION: ("EV-DOCX-004",),
    ContentCategory.REMEDIATION: ("EV-DOCX-001",),
    ContentCategory.REMEDIATION_OWNER: ("EV-DOCX-004",),
    ContentCategory.REMEDIATION_BUDGET_COMMENT: ("EV-DOCX-004",),
    ContentCategory.CONTRACT_BUYER: ("EV-PDF-001",),
    ContentCategory.CONTRACT_SUPPLIER: ("EV-PDF-001",),
    ContentCategory.CORPORATE_IDENTIFIER: ("EV-PDF-001",),
    ContentCategory.CONTRACT_DATE_IDENTIFIER: ("EV-PDF-001",),
    ContentCategory.RELATIVE_PERFORMANCE_TERM: ("EV-PDF-002",),
    ContentCategory.HISTORICAL_PRICING: ("EV-PDF-001",),
    ContentCategory.STANDARD_LEGAL_TERM: ("EV-PDF-002",),
    ContentCategory.NONSTANDARD_OBLIGATION: ("EV-PDF-003",),
    ContentCategory.SIGNATURE: ("EV-PDF-004",),
    ContentCategory.SOURCE_METADATA: ("EV-PDF-004",),
}


__all__ = [
    "CATEGORY_GUIDANCE",
    "CATEGORY_EVIDENCE",
    "CompletionClient",
    "FILE_KIND_CATEGORIES",
    "LocalInferenceError",
    "LocalInferenceUnavailable",
    "LocalVllmClient",
    "category_evidence_for_file",
]
