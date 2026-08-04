from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


class Role(str, Enum):
    GUEST = "guest"
    STAFF = "staff"
    ADMIN = "admin"


class ToolEffect(str, Enum):
    READ = "read"
    WRITE = "write"


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
    def from_dict(cls, data: Mapping[str, Any]) -> "AvailabilityResult":
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

    def to_dict(self) -> dict[str, Any]:
        return {"bookings": [asdict(item) for item in self.bookings]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BookingListResult":
        return cls(tuple(BookingView(**item) for item in data["bookings"]))


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
    def from_dict(cls, data: Mapping[str, Any]) -> "BookingResult":
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

    def to_dict(self) -> dict[str, Any]:
        return {"preferences": [list(item) for item in self.preferences]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PreferencesResult":
        return cls(tuple((str(key), str(value)) for key, value in data["preferences"]))


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
