from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlparse

from .v10_contracts import V10ContractError


_SHA256 = re.compile(r"[0-9a-f]{64}")
_SHELL_CONTROL = re.compile(r"(?:&&|\|\||[;|<>`\n\r])")


class ClaimKind(str, Enum):
    EXPRESS = "express"
    IMPLIED = "implied"
    COMPARATIVE = "comparative"
    TESTIMONIAL = "testimonial"
    MADE_IN_USA = "made_in_usa"
    MEDICAL = "medical"
    FINANCIAL = "financial"


@dataclass(frozen=True)
class ClaimCandidate:
    claim_id: str
    kind: ClaimKind
    text: str
    evidence_locator: str | None
    evidence_precedes_claim: bool
    net_impression_supported: bool
    disclosure: str | None = None
    disclosure_prominent: bool = False
    comparison_basis: str | None = None
    testimonial_experience_verified: bool = False
    made_in_usa_qualified: bool = False
    specialist_human_approval: str | None = None


@dataclass(frozen=True)
class SafetyDecision:
    passed: bool
    blockers: tuple[str, ...]
    human_required: bool


def evaluate_claim(candidate: ClaimCandidate) -> SafetyDecision:
    blockers: list[str] = []
    if not candidate.claim_id.strip() or not candidate.text.strip():
        raise V10ContractError("claim identity and text are required")
    if not candidate.evidence_locator:
        blockers.append("missing prior substantiation")
    if not candidate.evidence_precedes_claim:
        blockers.append("substantiation does not predate publication")
    if not candidate.net_impression_supported:
        blockers.append("net impression is unsupported")
    if candidate.kind == ClaimKind.COMPARATIVE and not candidate.comparison_basis:
        blockers.append("comparative basis is absent")
    if candidate.kind == ClaimKind.TESTIMONIAL:
        if not candidate.testimonial_experience_verified:
            blockers.append("testimonial experience is unverified")
        if not candidate.disclosure:
            blockers.append("material connection disclosure is absent")
    if candidate.disclosure and not candidate.disclosure_prominent:
        blockers.append("disclosure is not clear and prominent")
    if candidate.kind == ClaimKind.MADE_IN_USA and not candidate.made_in_usa_qualified:
        blockers.append("Made-in-USA qualification is absent")
    high_risk = candidate.kind in {ClaimKind.MEDICAL, ClaimKind.FINANCIAL}
    if high_risk and not candidate.specialist_human_approval:
        blockers.append("specialist human approval is absent")
    return SafetyDecision(not blockers, tuple(blockers), high_risk)


@dataclass(frozen=True)
class PrivacyAndAiLabelInput:
    personal_data_present: bool
    consent_locator: str | None
    ai_generated_or_materially_edited: bool
    ai_label_present: bool


def evaluate_privacy_and_ai_label(value: PrivacyAndAiLabelInput) -> SafetyDecision:
    blockers = []
    if value.personal_data_present and not value.consent_locator:
        blockers.append("personal data lacks consent locator")
    if value.ai_generated_or_materially_edited and not value.ai_label_present:
        blockers.append("required AI provenance label is absent")
    return SafetyDecision(not blockers, tuple(blockers), bool(value.personal_data_present))


class Channel(str, Enum):
    GOOGLE = "google"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    META = "meta"
    AMAZON = "amazon"


@dataclass(frozen=True)
class ChannelPolicySnapshot:
    channel: Channel
    revision: str
    sha256: str
    source_url: str
    allowed_formats: tuple[str, ...]

    def __post_init__(self) -> None:
        parsed = urlparse(self.source_url)
        if (
            not self.revision.strip()
            or not _SHA256.fullmatch(self.sha256)
            or parsed.scheme != "https"
            or not parsed.hostname
            or not self.allowed_formats
            or any(not value.strip() for value in self.allowed_formats)
        ):
            raise V10ContractError("channel policy must be revisioned, hashed and source-located")

    def evaluate(self, output_format: str, observed_revision: str, observed_sha256: str) -> SafetyDecision:
        blockers = []
        if observed_revision != self.revision or observed_sha256 != self.sha256:
            blockers.append("channel policy drift")
        if output_format not in self.allowed_formats:
            blockers.append("format is not admitted by frozen channel policy")
        return SafetyDecision(not blockers, tuple(blockers), False)


INJECTION_TOKENS = (
    "ignore previous instructions",
    "disable audit",
    "reveal system prompt",
    "exfiltrate secret",
    "override approval",
)


def detect_injection(text: str, *, indirect: bool) -> SafetyDecision:
    lowered = text.casefold()
    findings = tuple(token for token in INJECTION_TOKENS if token in lowered)
    prefix = "indirect" if indirect else "direct"
    return SafetyDecision(not findings, tuple(f"{prefix} injection: {item}" for item in findings), bool(findings))


@dataclass(frozen=True)
class ExecutionAllowlist:
    root: Path
    hosts: tuple[str, ...]
    commands: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.hosts or not self.commands:
            raise V10ContractError("execution allowlists cannot be empty")
        if any(host != host.casefold() or not host.strip() for host in self.hosts):
            raise V10ContractError("network hosts must be non-empty lowercase names")
        if any(
            not command.strip()
            or Path(command).name != command
            or _SHELL_CONTROL.search(command)
            for command in self.commands
        ):
            raise V10ContractError("commands must be bare executable names")

    def admit_path(self, candidate: Path) -> bool:
        try:
            return candidate.resolve().is_relative_to(self.root.resolve())
        except OSError:
            return False

    def admit_url(self, url: str) -> bool:
        parsed = urlparse(url)
        hostname = parsed.hostname.casefold() if parsed.hostname else None
        if parsed.scheme != "https" or hostname not in self.hosts:
            return False
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return True
        return not (address.is_private or address.is_loopback or address.is_link_local)

    def admit_command(self, argv: Sequence[str]) -> bool:
        return (
            bool(argv)
            and argv[0] in self.commands
            and all(
                "\x00" not in item and not _SHELL_CONTROL.search(item)
                for item in argv
            )
        )


@dataclass(frozen=True)
class DriftReceipt:
    kind: str
    expected_revision: str
    observed_revision: str
    expected_sha256: str
    observed_sha256: str

    @property
    def passed(self) -> bool:
        return (
            self.kind in {"model", "data", "adapter"}
            and bool(self.expected_revision.strip())
            and self.expected_revision == self.observed_revision
            and self.expected_sha256 == self.observed_sha256
            and bool(_SHA256.fullmatch(self.expected_sha256))
        )


class RedTeamKind(str, Enum):
    MEMORY_POISONING = "memory_poisoning"
    AGENT_COLLUSION = "agent_collusion"
    REWARD_HACKING = "reward_hacking"
    CROSS_AGENT_PROPAGATION = "cross_agent_propagation"
    HALLUCINATED_SOURCE = "hallucinated_source"
    LOGO_MISUSE = "logo_misuse"
    CULTURAL_HARM = "cultural_harm"
    FALSE_COMPARISON = "false_comparison"


@dataclass(frozen=True)
class RedTeamProbe:
    kind: RedTeamKind
    attempted: bool
    mechanical_detector_passed: bool
    release_blocked: bool
    evidence_locator: str

    @property
    def passed(self) -> bool:
        return self.attempted and self.mechanical_detector_passed and self.release_blocked and bool(self.evidence_locator.strip())


@dataclass(frozen=True)
class RiskAcceptance:
    risk_id: str
    accepter_id: str
    reason: str
    residual_risk: str
    expires_at: str

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.risk_id, self.accepter_id, self.reason, self.residual_risk, self.expires_at)):
            raise V10ContractError("risk acceptance requires accountable person, reason, residual risk and expiry")
        try:
            datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise V10ContractError("risk acceptance expiry must be ISO-8601") from error


def red_team_suite(probes: Sequence[RedTeamProbe]) -> SafetyDecision:
    if len({item.kind for item in probes}) != len(probes):
        raise V10ContractError("red-team probe kinds must be unique")
    by_kind = {item.kind: item for item in probes}
    missing = set(RedTeamKind) - set(by_kind)
    blockers = [f"missing red-team probe: {item.value}" for item in sorted(missing, key=lambda item: item.value)]
    blockers.extend(f"failed red-team probe: {item.kind.value}" for item in probes if not item.passed)
    return SafetyDecision(not blockers, tuple(blockers), bool(blockers))
