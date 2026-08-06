from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from shared_contracts import CloudDataType, stable_json_sha256
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import ProjectCloudPolicyRecord


class ProjectCloudPolicyError(RuntimeError):
    pass


class ProjectCloudPolicyConflict(ProjectCloudPolicyError):
    pass


def _public_payload(record: ProjectCloudPolicyRecord | None, project_id: UUID) -> dict:
    if record is None:
        identity = {
            "project_id": str(project_id),
            "policy_version": 0,
            "provider_allowlist": [],
            "allowed_data_types": [],
            "provider_retention_notice": None,
            "consented_at": None,
            "created_by_actor": None,
            "created_at": None,
        }
        return {
            **identity,
            "snapshot_sha256": stable_json_sha256(identity),
            "default_block": True,
        }
    return {**record.payload, "default_block": True}


class ProjectCloudPolicyRepository:
    """Append-only project authorization; no request may broaden it inline."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def latest_record(self, project_id: UUID) -> ProjectCloudPolicyRecord | None:
        return self.session.scalar(
            select(ProjectCloudPolicyRecord)
            .where(ProjectCloudPolicyRecord.project_id == project_id)
            .order_by(ProjectCloudPolicyRecord.policy_version.desc())
            .limit(1)
        )

    def latest(self, project_id: UUID) -> dict:
        return _public_payload(self.latest_record(project_id), project_id)

    def append(
        self,
        *,
        project_id: UUID,
        provider_allowlist: tuple[str, ...],
        allowed_data_types: tuple[CloudDataType, ...],
        provider_retention_notice: str | None,
        consent: bool,
        actor_id: str,
        idempotency_key: str,
        created_at: datetime | None = None,
    ) -> tuple[dict, bool]:
        if not idempotency_key or len(idempotency_key) > 255:
            raise ProjectCloudPolicyError("cloud policy idempotency key is invalid")
        if len(provider_allowlist) != len(set(provider_allowlist)):
            raise ProjectCloudPolicyError("cloud providers must be unique")
        if len(allowed_data_types) != len(set(allowed_data_types)):
            raise ProjectCloudPolicyError("cloud data types must be unique")
        if allowed_data_types and (
            not provider_allowlist
            or not provider_retention_notice
            or not consent
        ):
            raise ProjectCloudPolicyError(
                "cloud data authorization requires provider, notice, and consent"
            )
        if not allowed_data_types and (
            provider_allowlist or provider_retention_notice or consent
        ):
            raise ProjectCloudPolicyError(
                "blocked cloud policy cannot retain authorization fields"
            )
        existing = self.session.scalar(
            select(ProjectCloudPolicyRecord).where(
                ProjectCloudPolicyRecord.idempotency_key == idempotency_key
            )
        )
        requested = {
            "provider_allowlist": list(provider_allowlist),
            "allowed_data_types": [
                value.value for value in allowed_data_types
            ],
            "provider_retention_notice": provider_retention_notice,
        }
        if existing is not None:
            comparable = {
                key: existing.payload[key]
                for key in requested
            }
            if existing.project_id != project_id or comparable != requested:
                raise ProjectCloudPolicyConflict(
                    "cloud policy idempotency key conflicts with stored revision"
                )
            return _public_payload(existing, project_id), False

        latest = self.latest_record(project_id)
        now = created_at or datetime.now(timezone.utc)
        identity = {
            "project_id": str(project_id),
            "policy_version": (
                1 if latest is None else latest.policy_version + 1
            ),
            **requested,
            "consented_at": now.isoformat() if consent else None,
            "created_by_actor": actor_id,
            "created_at": now.isoformat(),
        }
        payload = {
            **identity,
            "snapshot_sha256": stable_json_sha256(identity),
        }
        record = ProjectCloudPolicyRecord(
            id=uuid4(),
            project_id=project_id,
            policy_version=identity["policy_version"],
            idempotency_key=idempotency_key,
            provider_allowlist=list(provider_allowlist),
            allowed_data_types=[
                value.value for value in allowed_data_types
            ],
            provider_retention_notice=provider_retention_notice,
            consented_at=now if consent else None,
            created_by_actor=actor_id,
            snapshot_sha256=payload["snapshot_sha256"],
            payload=payload,
            created_at=now,
        )
        self.session.add(record)
        try:
            self.session.flush()
        except IntegrityError:
            raise ProjectCloudPolicyConflict(
                "cloud policy version changed concurrently"
            ) from None
        return _public_payload(record, project_id), True
