from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class Stage(str, Enum):
    EVIDENCE = "evidence"
    PLAN = "plan"
    CREATE = "create"
    AUDIT = "audit"
    REPAIR = "repair"
    AWAITING_RELEASE = "awaiting_release"
    DELIVER = "deliver"
    BLOCKED = "blocked"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ReleaseDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class ReleaseApprovalKind(str, Enum):
    HUMAN = "human"
    FIXTURE = "fixture"


@dataclass(frozen=True)
class ReleaseApproval:
    """Immutable, content-bound release decision.

    ``approval_id`` is an integrity checksum, not an identity signature. The
    append-only evidence ledger supplies the second copy used by the workflow
    to detect state-file tampering.
    """

    approval_id: str
    run_id: str
    preview_digest: str
    decision: ReleaseDecision
    approver: str
    reason: str
    issued_at: str
    kind: ReleaseApprovalKind = ReleaseApprovalKind.HUMAN

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        preview_digest: str,
        decision: ReleaseDecision,
        approver: str,
        reason: str,
        kind: ReleaseApprovalKind = ReleaseApprovalKind.HUMAN,
        issued_at: str | None = None,
    ) -> "ReleaseApproval":
        normalized_approver = approver.strip()
        normalized_reason = reason.strip()
        if not normalized_approver:
            raise ValueError("release approver must be named")
        if not normalized_reason:
            raise ValueError("release reason must be explicit")
        if len(preview_digest) != 64 or any(
            character not in "0123456789abcdef" for character in preview_digest
        ):
            raise ValueError("preview digest must be a lowercase SHA-256 digest")
        timestamp = issued_at or datetime.now(timezone.utc).isoformat()
        core = {
            "run_id": run_id,
            "preview_digest": preview_digest,
            "decision": decision.value,
            "approver": normalized_approver,
            "reason": normalized_reason,
            "issued_at": timestamp,
            "kind": kind.value,
        }
        approval_id = hashlib.sha256(
            json.dumps(
                core,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return cls(
            approval_id=approval_id,
            run_id=run_id,
            preview_digest=preview_digest,
            decision=decision,
            approver=normalized_approver,
            reason=normalized_reason,
            issued_at=timestamp,
            kind=kind,
        )

    def serializable(self) -> dict[str, str]:
        return {
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "preview_digest": self.preview_digest,
            "decision": self.decision.value,
            "approver": self.approver,
            "reason": self.reason,
            "issued_at": self.issued_at,
            "kind": self.kind.value,
        }

    @classmethod
    def from_serializable(cls, payload: dict[str, Any]) -> "ReleaseApproval":
        try:
            approval = cls(
                approval_id=str(payload["approval_id"]),
                run_id=str(payload["run_id"]),
                preview_digest=str(payload["preview_digest"]),
                decision=ReleaseDecision(str(payload["decision"])),
                approver=str(payload["approver"]),
                reason=str(payload["reason"]),
                issued_at=str(payload["issued_at"]),
                kind=ReleaseApprovalKind(str(payload.get("kind", "human"))),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("malformed release approval") from exc
        if not approval.integrity_valid:
            raise ValueError("release approval integrity check failed")
        return approval

    @property
    def integrity_valid(self) -> bool:
        try:
            rebuilt = self.create(
                run_id=self.run_id,
                preview_digest=self.preview_digest,
                decision=self.decision,
                approver=self.approver,
                reason=self.reason,
                issued_at=self.issued_at,
                kind=self.kind,
            )
        except ValueError:
            return False
        return rebuilt.approval_id == self.approval_id


@dataclass(frozen=True)
class CampaignRequest:
    product_name: str
    product_image: str
    specification_text: str
    market: str
    platform: str
    goal: str
    target_emotion: str = "joy"


@dataclass(frozen=True)
class Claim:
    id: str
    text: str
    source_ref: str
    source_span: str
    approved: bool
    confidence: float


@dataclass(frozen=True)
class CreativeBrief:
    id: str
    headline: str
    claim_ids: tuple[str, ...]
    visual_direction: str
    target_emotion: str


@dataclass(frozen=True)
class CreativeAsset:
    id: str
    path: str
    aspect_ratio: str
    seed: int
    model_ref: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditFinding:
    id: str
    category: str
    severity: Severity
    message: str
    asset_id: str
    repair_action: str | None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AudiencePulse:
    target_emotion: str
    predicted_emotion: str
    confidence: float
    matched: bool
    model_ref: str
    limitations: tuple[str, ...]


@dataclass
class CampaignState:
    run_id: str
    request: CampaignRequest
    output_dir: str
    stage: Stage = Stage.EVIDENCE
    claims: list[Claim] = field(default_factory=list)
    briefs: list[CreativeBrief] = field(default_factory=list)
    assets: list[CreativeAsset] = field(default_factory=list)
    findings: list[AuditFinding] = field(default_factory=list)
    audience_pulses: list[AudiencePulse] = field(default_factory=list)
    repair_count: int = 0
    max_repairs: int = 2
    approvals: list[dict[str, Any]] = field(default_factory=list)
    prepared_preview_digest: str | None = None
    release_approval: ReleaseApproval | None = None
    exports: list[str] = field(default_factory=list)
    blocked_reason: str | None = None

    def serializable(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["stage"] = self.stage.value
        for finding in payload["findings"]:
            finding["severity"] = finding["severity"].value
        if self.release_approval is not None:
            payload["release_approval"] = self.release_approval.serializable()
        return payload

    @classmethod
    def from_serializable(cls, payload: dict[str, Any]) -> "CampaignState":
        """Rebuild a typed state from an untrusted JSON object.

        Integrity is checked by ``Supervisor.release`` against the ledger and
        preview digest; this method only performs strict structural parsing.
        """

        if not isinstance(payload, dict):
            raise ValueError("campaign state must be a JSON object")
        try:
            request_raw = payload["request"]
            if not isinstance(request_raw, dict):
                raise TypeError("request must be an object")
            request = CampaignRequest(**request_raw)
            claims = [Claim(**item) for item in cls._object_list(payload, "claims")]
            briefs = [
                CreativeBrief(
                    **{
                        **item,
                        "claim_ids": tuple(item.get("claim_ids", ())),
                    }
                )
                for item in cls._object_list(payload, "briefs")
            ]
            assets = [
                CreativeAsset(**item) for item in cls._object_list(payload, "assets")
            ]
            findings = [
                AuditFinding(
                    **{
                        **item,
                        "severity": Severity(str(item["severity"])),
                    }
                )
                for item in cls._object_list(payload, "findings")
            ]
            pulses = [
                AudiencePulse(
                    **{
                        **item,
                        "limitations": tuple(item.get("limitations", ())),
                    }
                )
                for item in cls._object_list(payload, "audience_pulses")
            ]
            approval_raw = payload.get("release_approval")
            if approval_raw is not None and not isinstance(approval_raw, dict):
                raise TypeError("release_approval must be an object or null")
            approvals = payload.get("approvals", [])
            exports = payload.get("exports", [])
            if not isinstance(approvals, list) or not all(
                isinstance(item, dict) for item in approvals
            ):
                raise TypeError("approvals must be a list of objects")
            if not isinstance(exports, list) or not all(
                isinstance(item, str) for item in exports
            ):
                raise TypeError("exports must be a list of strings")
            repair_count = payload.get("repair_count", 0)
            max_repairs = payload.get("max_repairs", 2)
            if type(repair_count) is not int or type(max_repairs) is not int:
                raise TypeError("repair counts must be integers")
            return cls(
                run_id=str(payload["run_id"]),
                request=request,
                output_dir=str(payload["output_dir"]),
                stage=Stage(str(payload["stage"])),
                claims=claims,
                briefs=briefs,
                assets=assets,
                findings=findings,
                audience_pulses=pulses,
                repair_count=repair_count,
                max_repairs=max_repairs,
                approvals=[dict(item) for item in approvals],
                prepared_preview_digest=(
                    str(payload["prepared_preview_digest"])
                    if payload.get("prepared_preview_digest") is not None
                    else None
                ),
                release_approval=(
                    ReleaseApproval.from_serializable(approval_raw)
                    if approval_raw is not None
                    else None
                ),
                exports=list(exports),
                blocked_reason=(
                    str(payload["blocked_reason"])
                    if payload.get("blocked_reason") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("malformed campaign state") from exc

    @staticmethod
    def _object_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
        value = payload.get(key, [])
        if not isinstance(value, list) or not all(
            isinstance(item, dict) for item in value
        ):
            raise TypeError(f"{key} must be a list of objects")
        return value

    def preview_digest(
        self,
        *,
        file_hashes: dict[str, str] | None = None,
    ) -> str:
        payload = {
            "schema": "ProofLaunchReleasePreviewV1",
            "run_id": self.run_id,
            "claims": [asdict(item) for item in self.claims],
            "briefs": [asdict(item) for item in self.briefs],
            "assets": [
                {
                    **asdict(asset),
                    "release_file_hashes": {
                        role: self._preview_file_hash(
                            asset,
                            role,
                            raw_path,
                            file_hashes=file_hashes,
                        )
                        for role, raw_path in self.release_file_paths(asset)
                    },
                }
                for asset in self.assets
            ],
            "findings": [
                {**asdict(item), "severity": item.severity.value}
                for item in self.findings
            ],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def release_file_paths(asset: CreativeAsset) -> tuple[tuple[str, str], ...]:
        return (
            ("creative", asset.path),
            ("product_layer", str(asset.metadata.get("product_layer_path", ""))),
            ("background", str(asset.metadata.get("background_path", ""))),
        )

    @staticmethod
    def release_file_hash_key(asset_id: str, role: str) -> str:
        return f"{asset_id}:{role}"

    def _preview_file_hash(
        self,
        asset: CreativeAsset,
        role: str,
        raw_path: str,
        *,
        file_hashes: dict[str, str] | None,
    ) -> str:
        key = self.release_file_hash_key(asset.id, role)
        if file_hashes is not None:
            return file_hashes.get(key, "MISSING")
        path = Path(raw_path)
        if not path.is_file():
            return "MISSING"
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir)

    @property
    def release_blockers(self) -> list[AuditFinding]:
        return [
            finding
            for finding in self.findings
            if finding.severity in {Severity.ERROR, Severity.CRITICAL}
        ]
