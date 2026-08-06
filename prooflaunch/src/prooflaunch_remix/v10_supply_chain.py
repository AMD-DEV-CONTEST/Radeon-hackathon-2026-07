from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping

from .v10_contracts import V10ContractError


_HEX = frozenset("0123456789abcdef")
_SPDX_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]*$")


def stable_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=lambda item: item.value if isinstance(item, Enum) else asdict(item),
        ).encode("utf-8")
    ).hexdigest()


def bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise V10ContractError(f"{field_name} must be a lowercase SHA-256")


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise V10ContractError(f"{field_name} is required")


class SourceKind(str, Enum):
    CODE = "code"
    MODEL = "model"
    DATASET = "dataset"
    FONT = "font"
    MUSIC = "music"
    IMAGE = "image"
    VIDEO = "video"
    TEXT = "text"
    ASSET = "asset"


class LicenseDisposition(str, Enum):
    ALLOW = "allow"
    RESEARCH_ISOLATION = "research_isolation"
    DENY = "deny"
    REVIEW = "review"


class UseProfile(str, Enum):
    RESEARCH = "research"
    COMMERCIAL = "commercial"
    COMPETITION = "competition"


class RiskKind(str, Enum):
    PROMPT_INJECTION = "prompt_injection"
    SECRET = "secret"
    PII = "pii"
    LIKENESS = "likeness"
    TRADEMARK = "trademark"
    SENSITIVE_INDUSTRY = "sensitive_industry"
    COPYRIGHT_LONG_TEXT = "copyright_long_text"


class LifecycleEventKind(str, Enum):
    REGISTER = "register"
    QUARANTINE = "quarantine"
    HUMAN_APPROVE = "human_approve"
    HUMAN_REJECT = "human_reject"
    OPT_OUT = "opt_out"
    DELETE = "delete"


@dataclass(frozen=True)
class LicenseEvidence:
    expression: str
    locator: str
    evidence_sha256: str
    authoritative_metadata: bool
    source_field: str
    custom_terms: bool = False

    def __post_init__(self) -> None:
        _require_text(self.expression, "license expression")
        _require_text(self.locator, "license evidence locator")
        _require_sha256(self.evidence_sha256, "license evidence SHA-256")
        _require_text(self.source_field, "license source field")


@dataclass(frozen=True)
class LicensedSource:
    source_id: str
    source_kind: SourceKind
    raw_uri: str
    commit: str
    revision: str
    sha256: str
    author_attribution: str
    license_evidence: LicenseEvidence
    training_use: bool
    distribution_use: bool
    commercial_restriction: str
    geography_restriction: str
    termination_terms: str
    media_type: str
    public_access: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "raw_uri",
            "commit",
            "revision",
            "author_attribution",
            "commercial_restriction",
            "geography_restriction",
            "termination_terms",
            "media_type",
        ):
            _require_text(str(getattr(self, field_name)), field_name)
        _require_sha256(self.sha256, "source SHA-256")
        if self.public_access and not self.license_evidence.authoritative_metadata:
            raise V10ContractError(
                "public access is not a license; authoritative license evidence is required"
            )


@dataclass(frozen=True)
class LicensePolicy:
    allowed: frozenset[str]
    research_isolation: frozenset[str]
    denied: frozenset[str]
    policy_version: str = "ProofLaunchLicensePolicyV3"

    def __post_init__(self) -> None:
        overlap = (
            (self.allowed & self.research_isolation)
            | (self.allowed & self.denied)
            | (self.research_isolation & self.denied)
        )
        if overlap:
            raise V10ContractError(
                f"license policy sets overlap: {', '.join(sorted(overlap))}"
            )

    def classify(self, expression: str) -> LicenseDisposition:
        normalized = expression.strip()
        if normalized in self.denied:
            return LicenseDisposition.DENY
        if normalized in self.research_isolation:
            return LicenseDisposition.RESEARCH_ISOLATION
        if normalized in self.allowed:
            return LicenseDisposition.ALLOW
        return LicenseDisposition.REVIEW


DEFAULT_LICENSE_POLICY = LicensePolicy(
    allowed=frozenset(
        {
            "Apache-2.0",
            "MIT",
            "BSD-2-Clause",
            "BSD-3-Clause",
            "CC0-1.0",
            "CC-BY-4.0",
            "OFL-1.1",
            "LicenseRef-ProofLaunch-Owned",
        }
    ),
    research_isolation=frozenset(
        {
            "CC-BY-NC-4.0",
            "CC-BY-NC-SA-4.0",
            "LicenseRef-Research-Only",
        }
    ),
    denied=frozenset(
        {
            "All-Rights-Reserved",
            "LicenseRef-No-AI",
            "LicenseRef-No-Derivatives",
        }
    ),
)


def _license_evidence(
    *,
    expression: object,
    locator: object,
    source_field: str,
    payload: Mapping[str, Any],
    custom_terms: bool = False,
) -> LicenseEvidence:
    license_id = str(expression or "").strip()
    evidence_locator = str(locator or "").strip()
    if not license_id or license_id.lower() in {"unknown", "none", "noassertion"}:
        raise V10ContractError("explicit license metadata is required")
    if not evidence_locator:
        raise V10ContractError("license metadata must include an evidence locator")
    return LicenseEvidence(
        expression=license_id,
        locator=evidence_locator,
        evidence_sha256=stable_sha256(payload),
        authoritative_metadata=True,
        source_field=source_field,
        custom_terms=custom_terms,
    )


def parse_github_spdx(payload: Mapping[str, Any]) -> LicenseEvidence:
    license_block = payload.get("license")
    if not isinstance(license_block, Mapping):
        raise V10ContractError("GitHub response has no license block")
    spdx_id = str(license_block.get("spdx_id") or "").strip()
    if not _SPDX_TOKEN.fullmatch(spdx_id) or spdx_id in {"NOASSERTION", "OTHER"}:
        raise V10ContractError("GitHub SPDX result is unresolved")
    locator = payload.get("html_url") or license_block.get("url")
    return _license_evidence(
        expression=spdx_id,
        locator=locator,
        source_field="license.spdx_id",
        payload=payload,
    )


def _parse_hub_card(
    payload: Mapping[str, Any], *, kind: SourceKind
) -> LicenseEvidence:
    expression = payload.get("license")
    custom = str(expression or "").strip().lower() == "other"
    if custom:
        expression = payload.get("license_name")
    locator = payload.get("license_link") or payload.get("card_url")
    return _license_evidence(
        expression=expression,
        locator=locator,
        source_field=f"{kind.value}_card.license",
        payload=payload,
        custom_terms=custom,
    )


def parse_model_license(payload: Mapping[str, Any]) -> LicenseEvidence:
    return _parse_hub_card(payload, kind=SourceKind.MODEL)


def parse_dataset_license(payload: Mapping[str, Any]) -> LicenseEvidence:
    return _parse_hub_card(payload, kind=SourceKind.DATASET)


def _parse_media_license(
    payload: Mapping[str, Any], *, kind: SourceKind
) -> LicenseEvidence:
    return _license_evidence(
        expression=payload.get("license") or payload.get("license_expression"),
        locator=payload.get("license_url") or payload.get("rights_statement_url"),
        source_field=f"{kind.value}.license",
        payload=payload,
        custom_terms=str(payload.get("license") or "").startswith("LicenseRef-"),
    )


def parse_font_license(payload: Mapping[str, Any]) -> LicenseEvidence:
    return _parse_media_license(payload, kind=SourceKind.FONT)


def parse_music_license(payload: Mapping[str, Any]) -> LicenseEvidence:
    return _parse_media_license(payload, kind=SourceKind.MUSIC)


def parse_image_license(payload: Mapping[str, Any]) -> LicenseEvidence:
    return _parse_media_license(payload, kind=SourceKind.IMAGE)


def parse_video_license(payload: Mapping[str, Any]) -> LicenseEvidence:
    return _parse_media_license(payload, kind=SourceKind.VIDEO)


@dataclass(frozen=True)
class RiskFinding:
    kind: RiskKind
    severity: str
    evidence: str
    requires_human_review: bool


class SourceRiskScanner:
    """Conservative risk signals; findings are not legal determinations."""

    _patterns = {
        RiskKind.PROMPT_INJECTION: re.compile(
            r"(?:ignore|disregard)\s+(?:all\s+)?(?:previous|prior)\s+instructions|"
            r"system\s+prompt|developer\s+message",
            re.IGNORECASE,
        ),
        RiskKind.SECRET: re.compile(
            r"(?:AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
            r"(?:api[_ -]?key|secret|token)\s*[:=]\s*[A-Za-z0-9_-]{16,})",
            re.IGNORECASE,
        ),
        RiskKind.PII: re.compile(
            r"(?:\b\d{3}-\d{2}-\d{4}\b|\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|"
            r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b)",
            re.IGNORECASE,
        ),
        RiskKind.LIKENESS: re.compile(
            r"\b(?:celebrity|public figure|face clone|voice clone|digital replica|likeness)\b",
            re.IGNORECASE,
        ),
        RiskKind.TRADEMARK: re.compile(
            r"(?:[®™]|\b(?:trademark|brand logo|passing off)\b)", re.IGNORECASE
        ),
        RiskKind.SENSITIVE_INDUSTRY: re.compile(
            r"\b(?:healthcare|medical diagnosis|pharmaceutical|financial advice|"
            r"credit decision|legal advice|political persuasion|weapons|gambling)\b",
            re.IGNORECASE,
        ),
    }

    def scan(self, text: str, *, has_explicit_text_rights: bool) -> tuple[RiskFinding, ...]:
        findings: list[RiskFinding] = []
        for kind, pattern in self._patterns.items():
            match = pattern.search(text)
            if match:
                findings.append(
                    RiskFinding(
                        kind=kind,
                        severity="critical" if kind == RiskKind.SECRET else "high",
                        evidence=bytes_sha256(match.group(0).encode("utf-8"))[:16],
                        requires_human_review=True,
                    )
                )
        if len(text.split()) >= 800 and not has_explicit_text_rights:
            findings.append(
                RiskFinding(
                    kind=RiskKind.COPYRIGHT_LONG_TEXT,
                    severity="high",
                    evidence=bytes_sha256(text.encode("utf-8"))[:16],
                    requires_human_review=True,
                )
            )
        return tuple(findings)


@dataclass(frozen=True)
class SupplyChainEvent:
    sequence: int
    kind: LifecycleEventKind
    source_id: str
    reason: str
    actor: str
    timestamp: str
    previous_hash: str
    event_hash: str


class SupplyChainLedger:
    def __init__(self) -> None:
        self._events: list[SupplyChainEvent] = []

    @property
    def events(self) -> tuple[SupplyChainEvent, ...]:
        return tuple(self._events)

    def append(
        self,
        kind: LifecycleEventKind,
        source_id: str,
        *,
        reason: str,
        actor: str,
        timestamp: str,
    ) -> SupplyChainEvent:
        for value, field_name in (
            (source_id, "source_id"),
            (reason, "reason"),
            (actor, "actor"),
            (timestamp, "timestamp"),
        ):
            _require_text(value, field_name)
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as error:
            raise V10ContractError("event timestamp must be ISO-8601") from error
        previous_hash = self._events[-1].event_hash if self._events else "0" * 64
        material = {
            "sequence": len(self._events) + 1,
            "kind": kind.value,
            "source_id": source_id,
            "reason": reason,
            "actor": actor,
            "timestamp": timestamp,
            "previous_hash": previous_hash,
        }
        event = SupplyChainEvent(
            sequence=material["sequence"],
            kind=kind,
            source_id=source_id,
            reason=reason,
            actor=actor,
            timestamp=timestamp,
            previous_hash=previous_hash,
            event_hash=stable_sha256(material),
        )
        self._events.append(event)
        return event

    def validate(self) -> bool:
        previous = "0" * 64
        for expected, event in enumerate(self._events, start=1):
            material = {
                "sequence": event.sequence,
                "kind": event.kind.value,
                "source_id": event.source_id,
                "reason": event.reason,
                "actor": event.actor,
                "timestamp": event.timestamp,
                "previous_hash": event.previous_hash,
            }
            if (
                event.sequence != expected
                or event.previous_hash != previous
                or event.event_hash != stable_sha256(material)
            ):
                return False
            previous = event.event_hash
        return True

    def source_state(self, source_id: str) -> str:
        state = "unregistered"
        for event in self._events:
            if event.source_id != source_id:
                continue
            state = {
                LifecycleEventKind.REGISTER: "registered",
                LifecycleEventKind.QUARANTINE: "quarantined",
                LifecycleEventKind.HUMAN_APPROVE: "approved",
                LifecycleEventKind.HUMAN_REJECT: "rejected",
                LifecycleEventKind.OPT_OUT: "opted_out",
                LifecycleEventKind.DELETE: "deleted",
            }[event.kind]
        return state


@dataclass(frozen=True)
class BomEntry:
    source_id: str
    source_kind: SourceKind
    revision: str
    sha256: str
    license_expression: str
    attribution: str


@dataclass(frozen=True)
class SupplyChainBoms:
    data: tuple[BomEntry, ...]
    models: tuple[BomEntry, ...]
    assets: tuple[BomEntry, ...]
    fonts: tuple[BomEntry, ...]
    audio: tuple[BomEntry, ...]

    @classmethod
    def from_sources(cls, sources: Iterable[LicensedSource]) -> "SupplyChainBoms":
        buckets: dict[str, list[BomEntry]] = {
            "data": [], "models": [], "assets": [], "fonts": [], "audio": []
        }
        for source in sources:
            entry = BomEntry(
                source_id=source.source_id,
                source_kind=source.source_kind,
                revision=source.revision,
                sha256=source.sha256,
                license_expression=source.license_evidence.expression,
                attribution=source.author_attribution,
            )
            if source.source_kind == SourceKind.DATASET:
                buckets["data"].append(entry)
            elif source.source_kind == SourceKind.MODEL:
                buckets["models"].append(entry)
            elif source.source_kind == SourceKind.FONT:
                buckets["fonts"].append(entry)
            elif source.source_kind == SourceKind.MUSIC:
                buckets["audio"].append(entry)
            else:
                buckets["assets"].append(entry)
        return cls(**{key: tuple(value) for key, value in buckets.items()})


@dataclass(frozen=True)
class OfflineSnapshot:
    source_id: str
    revision: str
    sha256: str
    snapshot_uri: str
    bytes_embedded: bool
    redistribution_permitted: bool

    def __post_init__(self) -> None:
        _require_sha256(self.sha256, "snapshot SHA-256")
        if self.bytes_embedded and not self.redistribution_permitted:
            raise V10ContractError(
                "offline snapshot cannot embed bytes without redistribution permission"
            )


@dataclass(frozen=True)
class SourceObservation:
    source_id: str
    observed_revision: str
    observed_sha256: str
    findings: tuple[RiskFinding, ...] = ()


@dataclass(frozen=True)
class SourceGateDecision:
    source_id: str
    admitted: bool
    disposition: LicenseDisposition
    failures: tuple[str, ...]


@dataclass(frozen=True)
class FullLicenseGateReport:
    profile: UseProfile
    decisions: tuple[SourceGateDecision, ...]
    frozen_digest: str
    all_admitted: bool
    schema: str = "ProofLaunchSupplyChainFullLicenseGateV3"


class FullLicenseGate:
    def __init__(self, policy: LicensePolicy = DEFAULT_LICENSE_POLICY) -> None:
        self.policy = policy

    def evaluate_source(
        self,
        source: LicensedSource,
        observation: SourceObservation,
        *,
        profile: UseProfile,
        ledger: SupplyChainLedger,
    ) -> SourceGateDecision:
        failures: list[str] = []
        disposition = self.policy.classify(source.license_evidence.expression)
        if observation.source_id != source.source_id:
            failures.append("observation source mismatch")
        if observation.observed_revision != source.revision:
            failures.append("revision drift")
        if observation.observed_sha256 != source.sha256:
            failures.append("hash drift")
        if not source.license_evidence.authoritative_metadata:
            failures.append("license evidence is not authoritative")
        if disposition in {LicenseDisposition.DENY, LicenseDisposition.REVIEW}:
            failures.append(f"license disposition is {disposition.value}")
        if disposition == LicenseDisposition.RESEARCH_ISOLATION and profile != UseProfile.RESEARCH:
            failures.append("research-isolation source cannot enter this profile")
        if not source.training_use:
            failures.append("training use is not authorized")
        if profile in {UseProfile.COMMERCIAL, UseProfile.COMPETITION}:
            if not source.distribution_use:
                failures.append("distribution use is not authorized")
            if source.commercial_restriction.lower() not in {"none", "not applicable"}:
                failures.append("commercial restriction conflicts with profile")
        if source.geography_restriction.lower() not in {"none", "not applicable"}:
            failures.append("geography restriction requires counsel review")
        if source.termination_terms.lower() in {"unknown", "unreviewed"}:
            failures.append("termination terms are unresolved")
        state = ledger.source_state(source.source_id)
        if state not in {"registered", "approved"}:
            failures.append(f"lifecycle state is {state}")
        if any(finding.requires_human_review for finding in observation.findings) and state != "approved":
            failures.append("high-risk finding lacks human approval")
        return SourceGateDecision(
            source_id=source.source_id,
            admitted=not failures,
            disposition=disposition,
            failures=tuple(failures),
        )

    def evaluate(
        self,
        sources: Iterable[LicensedSource],
        observations: Iterable[SourceObservation],
        *,
        profile: UseProfile,
        ledger: SupplyChainLedger,
    ) -> FullLicenseGateReport:
        source_items = tuple(sources)
        observation_items = tuple(observations)
        observation_map = {item.source_id: item for item in observation_items}
        if len(observation_map) != len(observation_items):
            raise V10ContractError("duplicate source observations")
        decisions: list[SourceGateDecision] = []
        for source in source_items:
            observation = observation_map.get(source.source_id)
            if observation is None:
                decisions.append(
                    SourceGateDecision(
                        source_id=source.source_id,
                        admitted=False,
                        disposition=self.policy.classify(
                            source.license_evidence.expression
                        ),
                        failures=("missing source observation",),
                    )
                )
                continue
            decisions.append(
                self.evaluate_source(
                    source,
                    observation,
                    profile=profile,
                    ledger=ledger,
                )
            )
        material = {
            "profile": profile.value,
            "policy_version": self.policy.policy_version,
            "sources": [asdict(item) for item in source_items],
            "decisions": [asdict(item) for item in decisions],
            "ledger_head": ledger.events[-1].event_hash if ledger.events else "0" * 64,
        }
        return FullLicenseGateReport(
            profile=profile,
            decisions=tuple(decisions),
            frozen_digest=stable_sha256(material),
            all_admitted=bool(decisions) and all(item.admitted for item in decisions),
        )


def verify_snapshot_fallback(
    source: LicensedSource,
    snapshot: OfflineSnapshot,
    *,
    source_deleted: bool,
) -> bool:
    if snapshot.source_id != source.source_id:
        return False
    if snapshot.revision != source.revision or snapshot.sha256 != source.sha256:
        return False
    if source_deleted:
        return False
    return True


def build_dataset_card(
    sources: Iterable[LicensedSource],
    report: FullLicenseGateReport,
) -> dict[str, Any]:
    items = tuple(sources)
    payload: dict[str, Any] = {
        "schema": "ProofLaunchDatasetCardV3",
        "source_count": len(items),
        "source_ids": [item.source_id for item in items],
        "licenses": sorted(
            {item.license_evidence.expression for item in items}
        ),
        "profile": report.profile.value,
        "full_license_gate_digest": report.frozen_digest,
        "all_sources_admitted": report.all_admitted,
        "intended_use": "bounded GTM agent training and evaluation",
        "limitations": [
            "metadata extraction is not legal advice",
            "public availability is not evidence of permission",
            "personality, privacy, trademark and publicity rights require separate review",
        ],
    }
    payload["content_sha256"] = stable_sha256(payload)
    return payload


def build_supply_chain_report(
    sources: Iterable[LicensedSource],
    boms: SupplyChainBoms,
    report: FullLicenseGateReport,
    ledger: SupplyChainLedger,
) -> dict[str, Any]:
    items = tuple(sources)
    payload: dict[str, Any] = {
        "schema": "ProofLaunchSupplyChainReportV3",
        "policy_version": DEFAULT_LICENSE_POLICY.policy_version,
        "source_count": len(items),
        "sources": [asdict(item) for item in items],
        "boms": asdict(boms),
        "license_gate": asdict(report),
        "lifecycle_events": [asdict(item) for item in ledger.events],
        "ledger_valid": ledger.validate(),
        "frozen": True,
        "legal_advice": False,
    }
    payload["content_sha256"] = stable_sha256(payload)
    return payload
