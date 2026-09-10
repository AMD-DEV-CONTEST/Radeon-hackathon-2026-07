"""Asset provenance audit — incomplete packages marked complete=false."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError

CreditRole = Literal["input", "style_reference", "font", "music", "portrait"]


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    asset_id: str
    sha256: Sha256
    role: CreditRole
    source_url: str | None
    license: str | None
    attribution: str | None
    consent: Literal["not_applicable", "obtained", "missing"] | None

    def __post_init__(self) -> None:
        if type(self.asset_id) is not str or not self.asset_id:
            raise DomainError("invalid provenance")
        if type(self.sha256) is not Sha256:
            raise DomainError("invalid provenance")
        if self.role not in ("input", "style_reference", "font", "music", "portrait"):
            raise DomainError("invalid provenance role")


@dataclass(frozen=True, slots=True)
class ProvenanceAudit:
    complete: bool
    records: tuple[ProvenanceRecord, ...]
    issues: tuple[str, ...]


def audit_provenance(records: tuple[ProvenanceRecord, ...]) -> ProvenanceAudit:
    if type(records) is not tuple:
        raise DomainError("invalid provenance records")
    issues: list[str] = []
    seen: dict[str, Sha256] = {}
    for rec in records:
        if type(rec) is not ProvenanceRecord:
            raise DomainError("invalid provenance record")
        if rec.asset_id in seen and seen[rec.asset_id] != rec.sha256:
            issues.append(f"hash_conflict:{rec.asset_id}")
        seen[rec.asset_id] = rec.sha256
        if rec.license is None or rec.license == "":
            issues.append(f"missing_license:{rec.asset_id}")
        if rec.role == "portrait" and rec.consent != "obtained":
            issues.append(f"portrait_consent:{rec.asset_id}")
        if rec.consent == "missing":
            issues.append(f"consent_missing:{rec.asset_id}")
    complete = len(issues) == 0 and len(records) > 0
    return ProvenanceAudit(complete, records, tuple(issues))
