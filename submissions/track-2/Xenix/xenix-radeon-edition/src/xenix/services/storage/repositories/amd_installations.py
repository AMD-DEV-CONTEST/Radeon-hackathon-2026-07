"""SQLite authority for managed installation desired state.

Target processes, endpoint bindings, ports, tokens, health, cache paths, and
runtime incarnations are intentionally absent. This repository remains usable as
inert compatibility history independently of the Radeon runtime composition.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Final

from sqlalchemy import update
from sqlmodel import Session, select

from ....exceptions import ValidationError
from ..models import AmdComponentGenerationRow, AmdInstallationRow, AmdTargetEnrollmentRow

_PLACEMENT_LOCAL_LINUX: Final = "local_linux"
_PLACEMENT_LOCAL_WSL: Final = "local_wsl"
_PLACEMENT_PRIVATE_SSH: Final = "private_ssh"
_WSL_DISTRIBUTION: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()@+-]{0,79}$")
_CAPABILITIES: Final = frozenset({"chat", "embedding", "ocr"})
_GENERATION_TRANSITIONS: Final = {
    "staging": frozenset({"verified", "failed", "blocked", "retiring"}),
    "verified": frozenset({"registered", "failed", "blocked", "retiring"}),
    "registered": frozenset({"failed", "retiring"}),
    "failed": frozenset({"staging", "retiring"}),
    "blocked": frozenset({"staging", "retiring"}),
    "retiring": frozenset({"removal_blocked", "removed"}),
    "removal_blocked": frozenset({"retiring", "removed"}),
    "removed": frozenset(),
}


class AmdInstallationRepository:
    """Narrow, forward-only repository operations for one coordinator."""

    def create_target(
        self,
        session: Session,
        row: AmdTargetEnrollmentRow,
    ) -> AmdTargetEnrollmentRow:
        _require_text(row.host, "Target host")
        _require_text(row.user, "Target user")
        _require_text(row.pinned_host_key, "Pinned host key")
        _require_text(row.identity_file_reference, "Identity-file reference")
        if not isinstance(row.port, int) or isinstance(row.port, bool) or not 1 <= row.port <= 65_535:
            raise ValidationError("Target SSH port is invalid.")
        if session.get(AmdTargetEnrollmentRow, row.id) is not None:
            raise ValidationError("Managed target ID already exists.")
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def get_target(self, session: Session, target_id: str) -> AmdTargetEnrollmentRow | None:
        return session.get(AmdTargetEnrollmentRow, target_id)

    def list_targets(self, session: Session) -> list[AmdTargetEnrollmentRow]:
        """List durable Private SSH target enrollments independently of installs."""

        return list(
            session.exec(
                select(AmdTargetEnrollmentRow).order_by(
                    AmdTargetEnrollmentRow.created_at,
                    AmdTargetEnrollmentRow.id,
                )
            )
        )

    def create_installation(
        self,
        session: Session,
        row: AmdInstallationRow,
    ) -> AmdInstallationRow:
        if session.get(AmdInstallationRow, row.id) is not None:
            raise ValidationError("Managed installation ID already exists.")
        self._validate_installation(row, session)
        row.desired_presence = True
        row.lifecycle_state = "active"
        row.revision = 0
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def get_installation(self, session: Session, installation_id: str) -> AmdInstallationRow | None:
        return session.get(AmdInstallationRow, installation_id)

    def list_installations(self, session: Session) -> list[AmdInstallationRow]:
        return list(
            session.exec(
                select(AmdInstallationRow).order_by(AmdInstallationRow.created_at, AmdInstallationRow.id)
            )
        )

    def request_retirement(
        self,
        session: Session,
        *,
        installation_id: str,
        expected_revision: int,
        now: datetime,
    ) -> AmdInstallationRow:
        row = _require_row(self.get_installation(session, installation_id), "Managed installation was not found.")
        _require_revision(expected_revision, row.revision)
        if row.lifecycle_state == "removed":
            return row
        if row.lifecycle_state not in {"active", "retiring"}:
            raise ValidationError("Managed installation cannot be retired from its current lifecycle state.")
        if row.lifecycle_state == "retiring":
            return row
        updated = session.execute(
            update(AmdInstallationRow)
            .where(
                AmdInstallationRow.id == installation_id,
                AmdInstallationRow.revision == expected_revision,
                AmdInstallationRow.lifecycle_state == "active",
                AmdInstallationRow.desired_presence.is_(True),
            )
            .values(
                desired_presence=False,
                lifecycle_state="retiring",
                revision=expected_revision + 1,
                updated_at=now,
            )
        )
        if int(updated.rowcount or 0) != 1:
            raise ValidationError("Managed installation state changed; refresh and retry.")
        session.flush()
        session.expire_all()
        return _require_row(
            self.get_installation(session, installation_id),
            "Managed installation was not found.",
        )

    def mark_removed(
        self,
        session: Session,
        *,
        installation_id: str,
        expected_revision: int,
        now: datetime,
    ) -> AmdInstallationRow:
        row = _require_row(self.get_installation(session, installation_id), "Managed installation was not found.")
        _require_revision(expected_revision, row.revision)
        if row.lifecycle_state == "removed":
            return row
        if row.lifecycle_state != "retiring" or row.desired_presence:
            raise ValidationError("Managed installation may be removed only after retirement is committed.")
        updated = session.execute(
            update(AmdInstallationRow)
            .where(
                AmdInstallationRow.id == installation_id,
                AmdInstallationRow.revision == expected_revision,
                AmdInstallationRow.lifecycle_state == "retiring",
                AmdInstallationRow.desired_presence.is_(False),
            )
            .values(
                lifecycle_state="removed",
                revision=expected_revision + 1,
                updated_at=now,
            )
        )
        if int(updated.rowcount or 0) != 1:
            raise ValidationError("Managed installation state changed; refresh and retry.")
        session.flush()
        session.expire_all()
        return _require_row(
            self.get_installation(session, installation_id),
            "Managed installation was not found.",
        )

    def create_generation(
        self,
        session: Session,
        row: AmdComponentGenerationRow,
    ) -> AmdComponentGenerationRow:
        installation = _require_row(
            self.get_installation(session, row.installation_id),
            "Managed installation was not found.",
        )
        if installation.lifecycle_state != "active" or not installation.desired_presence:
            raise ValidationError("A retired managed installation cannot receive a new generation.")
        if row.capability not in _CAPABILITIES:
            raise ValidationError("Managed generation capability is unsupported.")
        _require_text(row.manifest_digest, "Manifest digest")
        duplicate = session.exec(
            select(AmdComponentGenerationRow).where(
                AmdComponentGenerationRow.installation_id == row.installation_id,
                AmdComponentGenerationRow.capability == row.capability,
                AmdComponentGenerationRow.manifest_digest == row.manifest_digest,
            )
        ).first()
        if duplicate is not None:
            raise ValidationError("Managed component generation identity already exists.")
        row.lifecycle_state = "staging"
        row.phase = "planned"
        row.error_code = None
        row.attestation_reference = None
        row.revision = 0
        session.add(row)
        session.flush()
        session.refresh(row)
        return row

    def get_generation(
        self,
        session: Session,
        generation_id: str,
    ) -> AmdComponentGenerationRow | None:
        return session.get(AmdComponentGenerationRow, generation_id)

    def list_generations(
        self,
        session: Session,
        *,
        installation_id: str,
    ) -> list[AmdComponentGenerationRow]:
        return list(
            session.exec(
                select(AmdComponentGenerationRow)
                .where(AmdComponentGenerationRow.installation_id == installation_id)
                .order_by(
                    AmdComponentGenerationRow.created_at,
                    AmdComponentGenerationRow.id,
                )
            )
        )

    def transition_generation(
        self,
        session: Session,
        *,
        generation_id: str,
        expected_revision: int,
        next_state: str,
        phase: str,
        now: datetime,
        error_code: str | None = None,
        attestation_reference: str | None = None,
    ) -> AmdComponentGenerationRow:
        row = _require_row(self.get_generation(session, generation_id), "Managed component generation was not found.")
        _require_revision(expected_revision, row.revision)
        allowed = _GENERATION_TRANSITIONS.get(row.lifecycle_state)
        if allowed is None or next_state not in allowed:
            raise ValidationError("Managed component generation lifecycle cannot move backwards.")
        _require_text(phase, "Managed generation phase")
        if error_code is not None:
            _require_bounded_code(error_code, "Managed generation error code")
        if attestation_reference is not None:
            _require_text(attestation_reference, "Generation attestation reference")
        if next_state == "verified" and not attestation_reference:
            raise ValidationError("A verified managed generation requires an attestation reference.")
        if next_state != "verified" and attestation_reference is not None:
            raise ValidationError("Only verification may attach a managed generation attestation.")
        values: dict[str, object] = {
            "lifecycle_state": next_state,
            "phase": phase,
            "error_code": error_code,
            "revision": expected_revision + 1,
            "updated_at": now,
        }
        if attestation_reference is not None:
            values["attestation_reference"] = attestation_reference
        updated = session.execute(
            update(AmdComponentGenerationRow)
            .where(
                AmdComponentGenerationRow.id == generation_id,
                AmdComponentGenerationRow.revision == expected_revision,
                AmdComponentGenerationRow.lifecycle_state == row.lifecycle_state,
            )
            .values(**values)
        )
        if int(updated.rowcount or 0) != 1:
            raise ValidationError("Managed component generation state changed; refresh and retry.")
        session.flush()
        session.expire_all()
        return _require_row(
            self.get_generation(session, generation_id),
            "Managed component generation was not found.",
        )

    def _validate_installation(self, row: AmdInstallationRow, session: Session) -> None:
        if row.placement not in {
            _PLACEMENT_LOCAL_LINUX,
            _PLACEMENT_LOCAL_WSL,
            _PLACEMENT_PRIVATE_SSH,
        }:
            raise ValidationError("Managed installation placement is unsupported.")
        _require_text(row.profile_id, "Managed profile ID")
        _require_text(row.profile_digest, "Managed profile digest")
        if row.placement == _PLACEMENT_LOCAL_LINUX and (
            row.target_id is not None or row.local_wsl_distribution is not None
        ):
            raise ValidationError("Local Linux managed installations cannot reference an SSH target.")
        if row.placement == _PLACEMENT_PRIVATE_SSH:
            if not row.target_id or session.get(AmdTargetEnrollmentRow, row.target_id) is None:
                raise ValidationError("Private SSH managed installations require an enrolled target.")
            if row.local_wsl_distribution is not None:
                raise ValidationError("Private SSH managed installations cannot reference a WSL distribution.")
        if row.placement == _PLACEMENT_LOCAL_WSL:
            if row.target_id is not None:
                raise ValidationError("Local WSL managed installations cannot reference an SSH target.")
            _require_wsl_distribution(row.local_wsl_distribution)


def _require_row[T](row: T | None, message: str) -> T:
    if row is None:
        raise ValidationError(message)
    return row


def _require_revision(expected_revision: int, actual_revision: int) -> None:
    if (
        not isinstance(expected_revision, int)
        or isinstance(expected_revision, bool)
        or expected_revision != actual_revision
    ):
        raise ValidationError("Managed installation state changed; refresh and retry.")


def _require_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValidationError(f"{label} is invalid.")


def _require_bounded_code(value: str, label: str) -> None:
    _require_text(value, label)
    if any(character.isspace() for character in value) or len(value) > 120:
        raise ValidationError(f"{label} is invalid.")


def _require_wsl_distribution(value: str | None) -> None:
    if (
        not isinstance(value, str)
        or not _WSL_DISTRIBUTION.fullmatch(value)
        or value != value.strip()
        or value.startswith("-")
        or "\x00" in value
        or "\r" in value
        or "\n" in value
    ):
        raise ValidationError("Local WSL distribution is invalid.")


__all__ = ["AmdInstallationRepository"]
