from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    GUEST = "guest"
    STAFF = "staff"
    ADMIN = "admin"


class ToolEffect(StrEnum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True, slots=True)
class OwnerScopeAttestation:
    """Display-safe proof emitted by the local authorizer for owner-only reads."""

    owner_scoped_result_count: int
    authorization_scope: str = "owner_only"
    scope_verified: bool = True
    cross_user_result_count: int = 0
    authorizer: str = "local-hotel-store"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> OwnerScopeAttestation:
        return cls(
            owner_scoped_result_count=int(data["owner_scoped_result_count"]),
            authorization_scope=str(data.get("authorization_scope", "owner_only")),
            scope_verified=data.get("scope_verified") is True,
            cross_user_result_count=int(data.get("cross_user_result_count", 0)),
            authorizer=str(data.get("authorizer", "local-hotel-store")),
        )


@dataclass(frozen=True, slots=True)
class UserContext:
    user_id: str
    role: Role = Role.GUEST

    def __post_init__(self) -> None:
        if not self.user_id.strip():
            raise ValueError("user_id must not be empty")
        object.__setattr__(self, "role", Role(self.role))

    @property
    def is_staff(self) -> bool:
        return self.role in {Role.STAFF, Role.ADMIN}


class DomainError(Exception):
    """Base class for expected, user-safe domain failures."""


class ValidationError(DomainError):
    pass


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class PermissionDenied(DomainError):
    pass


class ConsentRequired(DomainError):
    pass


class IdempotencyConflict(ConflictError):
    pass


class ConfirmationRequired(DomainError):
    def __init__(
        self,
        token: str,
        expires_at: str,
        preview: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__("write confirmation required")
        self.token = token
        self.expires_at = expires_at
        self.preview = dict(preview or {})


@dataclass(frozen=True, slots=True)
class AvailabilityInput:
    check_in: str
    check_out: str
    guests: int = 1
    room_type: str | None = None


@dataclass(frozen=True, slots=True)
class AvailabilityItem:
    room_type: str
    available_rooms: int
    capacity: int
    nightly_rate_cents: int


@dataclass(frozen=True, slots=True)
class AvailabilityResult:
    check_in: str
    check_out: str
    items: tuple[AvailabilityItem, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_in": self.check_in,
            "check_out": self.check_out,
            "items": [asdict(item) for item in self.items],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AvailabilityResult:
        return cls(
            check_in=str(data["check_in"]),
            check_out=str(data["check_out"]),
            items=tuple(AvailabilityItem(**item) for item in data["items"]),
        )


@dataclass(frozen=True, slots=True)
class QuoteInput:
    room_type: str
    check_in: str
    check_out: str
    guests: int = 1


@dataclass(frozen=True, slots=True)
class QuoteResult:
    room_type: str
    check_in: str
    check_out: str
    guests: int
    nights: int
    nightly_rate_cents: int
    total_cents: int
    currency: str
    available: bool


@dataclass(frozen=True, slots=True)
class MyBookingsInput:
    include_cancelled: bool = False


@dataclass(frozen=True, slots=True)
class BookingView:
    booking_id: str
    room_type: str
    check_in: str
    check_out: str
    guests: int
    total_cents: int
    currency: str
    status: str
    hold_expires_at: str | None


@dataclass(frozen=True, slots=True)
class BookingListResult:
    bookings: tuple[BookingView, ...]
    scope_attestation: OwnerScopeAttestation | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "bookings": [asdict(item) for item in self.bookings]
        }
        if self.scope_attestation is not None:
            result["scope_attestation"] = self.scope_attestation.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BookingListResult:
        attestation = data.get("scope_attestation")
        return cls(
            tuple(BookingView(**item) for item in data["bookings"]),
            (
                OwnerScopeAttestation.from_dict(attestation)
                if isinstance(attestation, Mapping)
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class HoldBookingInput:
    room_type: str
    check_in: str
    check_out: str
    guests: int = 1


@dataclass(frozen=True, slots=True)
class ModifyBookingInput:
    booking_id: str
    room_type: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    guests: int | None = None


@dataclass(frozen=True, slots=True)
class BookingResult:
    booking: BookingView

    def to_dict(self) -> dict[str, Any]:
        return {"booking": asdict(self.booking)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BookingResult:
        return cls(BookingView(**data["booking"]))


@dataclass(frozen=True, slots=True)
class CreateServiceTicketInput:
    booking_id: str
    category: str
    description: str


@dataclass(frozen=True, slots=True)
class ServiceTicketResult:
    ticket_id: str
    booking_id: str
    category: str
    status: str
    updated_at: str | None = None
    state_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ListServiceTicketsInput:
    booking_id: str | None = None
    include_closed: bool = False


@dataclass(frozen=True, slots=True)
class ServiceTicketView:
    ticket_id: str
    booking_id: str
    category: str
    description: str
    status: str
    created_at: str
    updated_at: str
    state_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ServiceTicketListResult:
    tickets: tuple[ServiceTicketView, ...]
    scope_attestation: OwnerScopeAttestation | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "tickets": [asdict(item) for item in self.tickets]
        }
        if self.scope_attestation is not None:
            result["scope_attestation"] = self.scope_attestation.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ServiceTicketListResult:
        attestation = data.get("scope_attestation")
        return cls(
            tuple(ServiceTicketView(**item) for item in data["tickets"]),
            (
                OwnerScopeAttestation.from_dict(attestation)
                if isinstance(attestation, Mapping)
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class UpdateServiceTicketInput:
    ticket_id: str
    status: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateServiceTicketResult:
    ticket: ServiceTicketView
    state_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"ticket": asdict(self.ticket)}
        if self.state_sha256 is not None:
            result["state_sha256"] = self.state_sha256
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> UpdateServiceTicketResult:
        state_sha256 = data.get("state_sha256")
        return cls(
            ServiceTicketView(**data["ticket"]),
            str(state_sha256) if state_sha256 is not None else None,
        )


@dataclass(frozen=True, slots=True)
class BuildStayBriefInput:
    booking_id: str


@dataclass(frozen=True, slots=True)
class StayBriefServiceTicket:
    ticket_id: str
    booking_id: str
    category: str
    status: str
    updated_at: str
    state_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class StayBriefResult:
    booking: BookingView
    service_tickets: tuple[StayBriefServiceTicket, ...]
    memory_enabled: bool
    preferences: tuple[tuple[str, str], ...]
    scope_attestation: OwnerScopeAttestation | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "booking": asdict(self.booking),
            "service_tickets": [asdict(item) for item in self.service_tickets],
            "memory_enabled": self.memory_enabled,
            "preferences": [list(item) for item in self.preferences],
        }
        if self.scope_attestation is not None:
            result["scope_attestation"] = self.scope_attestation.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StayBriefResult:
        attestation = data.get("scope_attestation")
        return cls(
            booking=BookingView(**data["booking"]),
            service_tickets=tuple(
                StayBriefServiceTicket(**item) for item in data["service_tickets"]
            ),
            memory_enabled=bool(data["memory_enabled"]),
            preferences=tuple(
                (str(key), str(value)) for key, value in data["preferences"]
            ),
            scope_attestation=(
                OwnerScopeAttestation.from_dict(attestation)
                if isinstance(attestation, Mapping)
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class JourneyStateSnapshot:
    session_id: str
    actor_ref: str
    version: int
    payload: Mapping[str, Any]
    updated_at: str


@dataclass(frozen=True, slots=True)
class PersistedSessionAuditEvent:
    session_id: str
    sequence: int
    actor_ref: str
    occurred_at: str
    event: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class SetMemoryConsentInput:
    enabled: bool


@dataclass(frozen=True, slots=True)
class MemoryConsentResult:
    enabled: bool
    removed_preferences: int = 0


@dataclass(frozen=True, slots=True)
class RememberPreferenceInput:
    key: str
    value: str


@dataclass(frozen=True, slots=True)
class PreferenceResult:
    key: str
    saved: bool


@dataclass(frozen=True, slots=True)
class GetPreferencesInput:
    pass


@dataclass(frozen=True, slots=True)
class PreferencesResult:
    preferences: tuple[tuple[str, str], ...]
    scope_attestation: OwnerScopeAttestation | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "preferences": [list(item) for item in self.preferences]
        }
        if self.scope_attestation is not None:
            result["scope_attestation"] = self.scope_attestation.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PreferencesResult:
        attestation = data.get("scope_attestation")
        return cls(
            tuple((str(key), str(value)) for key, value in data["preferences"]),
            (
                OwnerScopeAttestation.from_dict(attestation)
                if isinstance(attestation, Mapping)
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class DeletePreferenceInput:
    key: str


@dataclass(frozen=True, slots=True)
class DeletePreferenceResult:
    key: str
    deleted: bool


@dataclass(frozen=True, slots=True)
class AuditEntry:
    occurred_at: str
    actor_ref: str
    role: str
    action: str
    effect: str
    resource_type: str
    resource_id: str | None
    outcome: str
    details: Mapping[str, Any]
