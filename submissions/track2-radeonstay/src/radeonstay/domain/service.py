from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta

from .models import (
    AvailabilityInput,
    AvailabilityItem,
    AvailabilityResult,
    BookingListResult,
    BookingResult,
    BookingView,
    ConflictError,
    ConsentRequired,
    CreateServiceTicketInput,
    DeletePreferenceInput,
    DeletePreferenceResult,
    GetPreferencesInput,
    HoldBookingInput,
    MemoryConsentResult,
    ModifyBookingInput,
    MyBookingsInput,
    NotFoundError,
    PermissionDenied,
    PreferenceResult,
    PreferencesResult,
    QuoteInput,
    QuoteResult,
    RememberPreferenceInput,
    ServiceTicketResult,
    SetMemoryConsentInput,
    ToolEffect,
    UserContext,
    ValidationError,
)
from .storage import HotelStore, iso_utc, utc_now

ALLOWED_PREFERENCE_KEYS = {
    "accessibility",
    "bed_type",
    "floor",
    "language",
    "pillow",
    "quiet_room",
}
ALLOWED_TICKET_CATEGORIES = {
    "accessibility",
    "cleaning",
    "maintenance",
    "room_service",
    "transport",
    "other",
}
ALLOWED_ROOM_TYPES = {"standard", "deluxe", "suite"}
_SECRET_MARKERS = (
    "api key",
    "api_key",
    "access token",
    "private key",
    "password",
    "passwd",
    "secret key",
    "cvv",
    "cvc",
    "银行卡密码",
    "支付密码",
    "密码",
    "口令",
)
_TOKEN_PATTERN = re.compile(r"\b(?:sk|ghp|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b")
_CARD_CANDIDATE_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def _passes_luhn(value: str) -> bool:
    digits = [int(character) for character in value if character.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _reject_sensitive_free_text(value: str) -> None:
    normalized = value.casefold()
    if any(marker in normalized for marker in _SECRET_MARKERS):
        raise ValidationError("credentials and payment secrets must not be stored")
    if _TOKEN_PATTERN.search(value):
        raise ValidationError("API or access tokens must not be stored")
    if any(_passes_luhn(match.group(0)) for match in _CARD_CANDIDATE_PATTERN.finditer(value)):
        raise ValidationError("payment-card numbers must not be stored")


def _parse_stay(check_in: str, check_out: str) -> tuple[date, date, int]:
    if not isinstance(check_in, str) or not isinstance(check_out, str):
        raise ValidationError("dates must be strings in ISO format YYYY-MM-DD")
    try:
        start = date.fromisoformat(check_in)
        end = date.fromisoformat(check_out)
    except ValueError as exc:
        raise ValidationError("dates must use ISO format YYYY-MM-DD") from exc
    if end <= start:
        raise ValidationError("check_out must be after check_in")
    return start, end, (end - start).days


def _validate_guests(guests: int) -> int:
    if isinstance(guests, bool) or not isinstance(guests, int) or guests <= 0:
        raise ValidationError("guests must be a positive integer")
    return guests


def _validate_room_type(room_type: str | None, *, optional: bool = False) -> str | None:
    if room_type is None and optional:
        return None
    if not isinstance(room_type, str) or room_type not in ALLOWED_ROOM_TYPES:
        raise ValidationError("room_type must be standard, deluxe, or suite")
    return room_type


class HotelService:
    def __init__(self, store: HotelStore, *, hold_minutes: int = 15) -> None:
        self.store = store
        self.hold_minutes = hold_minutes

    def _availability_rows(
        self,
        check_in: str,
        check_out: str,
        guests: int,
        *,
        room_type: str | None = None,
        exclude_booking_id: str | None = None,
    ):
        _parse_stay(check_in, check_out)
        guests = _validate_guests(guests)
        query = """
            SELECT r.room_type, r.capacity, r.nightly_rate_cents,
                   r.inventory - COUNT(b.booking_id) AS available_rooms
            FROM rooms r
            LEFT JOIN bookings b
              ON b.room_type = r.room_type
             AND b.check_in < ?
             AND b.check_out > ?
             AND (
                 b.status = 'confirmed'
                 OR (b.status = 'held' AND b.hold_expires_at > ?)
             )
             AND (? IS NULL OR b.booking_id != ?)
            WHERE r.capacity >= ? AND (? IS NULL OR r.room_type = ?)
            GROUP BY r.room_type, r.capacity, r.nightly_rate_cents, r.inventory
            ORDER BY r.nightly_rate_cents, r.room_type
        """
        return self.store.connection.execute(
            query,
            (
                check_out,
                check_in,
                iso_utc(),
                exclude_booking_id,
                exclude_booking_id,
                guests,
                room_type,
                room_type,
            ),
        ).fetchall()

    def check_availability(
        self, context: UserContext, request: AvailabilityInput
    ) -> AvailabilityResult:
        _validate_room_type(request.room_type, optional=True)
        with self.store.transaction():
            rows = self._availability_rows(
                request.check_in,
                request.check_out,
                request.guests,
                room_type=request.room_type,
            )
            result = AvailabilityResult(
                request.check_in,
                request.check_out,
                tuple(
                    AvailabilityItem(
                        room_type=row["room_type"],
                        available_rooms=max(0, int(row["available_rooms"])),
                        capacity=int(row["capacity"]),
                        nightly_rate_cents=int(row["nightly_rate_cents"]),
                    )
                    for row in rows
                ),
            )
            self.store.audit(
                context,
                action="check_availability",
                effect=ToolEffect.READ,
                resource_type="room_inventory",
                details={"result_count": len(result.items)},
            )
            return result

    def quote(self, context: UserContext, request: QuoteInput) -> QuoteResult:
        _validate_room_type(request.room_type)
        _, _, nights = _parse_stay(request.check_in, request.check_out)
        with self.store.transaction():
            rows = self._availability_rows(
                request.check_in,
                request.check_out,
                request.guests,
                room_type=request.room_type,
            )
            if not rows:
                raise NotFoundError("room type does not exist or cannot fit guest count")
            row = rows[0]
            rate = int(row["nightly_rate_cents"])
            result = QuoteResult(
                room_type=row["room_type"],
                check_in=request.check_in,
                check_out=request.check_out,
                guests=int(request.guests),
                nights=nights,
                nightly_rate_cents=rate,
                total_cents=rate * nights,
                currency="CNY",
                available=int(row["available_rooms"]) > 0,
            )
            self.store.audit(
                context,
                action="quote_stay",
                effect=ToolEffect.READ,
                resource_type="quote",
                details={
                    "room_type": result.room_type,
                    "nights": nights,
                    "available": result.available,
                },
            )
            return result

    @staticmethod
    def _booking_view(row) -> BookingView:
        status = row["status"]
        if (
            status == "held"
            and row["hold_expires_at"]
            and datetime.fromisoformat(row["hold_expires_at"]) <= utc_now()
        ):
            status = "expired"
        return BookingView(
            booking_id=row["booking_id"],
            room_type=row["room_type"],
            check_in=row["check_in"],
            check_out=row["check_out"],
            guests=int(row["guests"]),
            total_cents=int(row["total_cents"]),
            currency=row["currency"],
            status=status,
            hold_expires_at=row["hold_expires_at"],
        )

    def my_bookings(
        self, context: UserContext, request: MyBookingsInput
    ) -> BookingListResult:
        where_status = "" if request.include_cancelled else "AND status != 'cancelled'"
        with self.store.transaction():
            rows = self.store.connection.execute(
                f"""
                SELECT * FROM bookings
                WHERE user_id = ? {where_status}
                ORDER BY check_in, created_at
                """,
                (context.user_id,),
            ).fetchall()
            result = BookingListResult(tuple(self._booking_view(row) for row in rows))
            self.store.audit(
                context,
                action="my_bookings",
                effect=ToolEffect.READ,
                resource_type="booking",
                details={"result_count": len(result.bookings)},
            )
            return result

    def preview_hold_booking(
        self, context: UserContext, request: HoldBookingInput
    ) -> dict[str, object]:
        """Validate a hold and calculate the authoritative terms before consent."""

        _validate_room_type(request.room_type)
        _, _, nights = _parse_stay(request.check_in, request.check_out)
        _validate_guests(request.guests)
        with self.store.transaction():
            rows = self._availability_rows(
                request.check_in,
                request.check_out,
                request.guests,
                room_type=request.room_type,
            )
            if not rows:
                raise NotFoundError("room type does not exist or cannot fit guest count")
            row = rows[0]
            available_rooms = int(row["available_rooms"])
            if available_rooms <= 0:
                raise ConflictError("no room is available for the requested stay")
            nightly_rate = int(row["nightly_rate_cents"])
            return {
                "room_type": request.room_type,
                "check_in": request.check_in,
                "check_out": request.check_out,
                "guests": request.guests,
                "nights": nights,
                "nightly_rate_cents": nightly_rate,
                "total_cents": nightly_rate * nights,
                "currency": "CNY",
                "available_rooms": available_rooms,
            }

    def hold_booking(
        self, context: UserContext, request: HoldBookingInput
    ) -> BookingResult:
        _validate_room_type(request.room_type)
        _parse_stay(request.check_in, request.check_out)
        _validate_guests(request.guests)
        with self.store.transaction():
            rows = self._availability_rows(
                request.check_in,
                request.check_out,
                request.guests,
                room_type=request.room_type,
            )
            if not rows:
                raise NotFoundError("room type does not exist or cannot fit guest count")
            row = rows[0]
            if int(row["available_rooms"]) <= 0:
                raise ConflictError("no room is available for the requested stay")
            _, _, nights = _parse_stay(request.check_in, request.check_out)
            now = utc_now()
            booking_id = f"RSV-{uuid.uuid4().hex[:12].upper()}"
            hold_expires_at = now + timedelta(minutes=self.hold_minutes)
            self.store.connection.execute(
                """
                INSERT INTO bookings(
                    booking_id, user_id, room_type, check_in, check_out,
                    guests, total_cents, status, hold_expires_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'held', ?, ?, ?)
                """,
                (
                    booking_id,
                    context.user_id,
                    request.room_type,
                    request.check_in,
                    request.check_out,
                    int(request.guests),
                    int(row["nightly_rate_cents"]) * nights,
                    iso_utc(hold_expires_at),
                    iso_utc(now),
                    iso_utc(now),
                ),
            )
            booking = self.store.connection.execute(
                "SELECT * FROM bookings WHERE booking_id = ?", (booking_id,)
            ).fetchone()
            self.store.audit(
                context,
                action="hold_booking",
                effect=ToolEffect.WRITE,
                resource_type="booking",
                resource_id=booking_id,
                details={"room_type": request.room_type, "nights": nights},
            )
            return BookingResult(self._booking_view(booking))

    def _get_authorized_booking(self, context: UserContext, booking_id: str):
        row = self.store.connection.execute(
            "SELECT * FROM bookings WHERE booking_id = ?", (booking_id,)
        ).fetchone()
        if context.is_staff:
            if row is None:
                raise NotFoundError("booking not found")
            return row
        # Guests receive one indistinguishable refusal for missing and foreign
        # identifiers so the API cannot be used as a booking-existence oracle.
        if row is None or row["user_id"] != context.user_id:
            raise PermissionDenied("booking not found or not accessible")
        return row

    def preview_modify_booking(
        self, context: UserContext, request: ModifyBookingInput
    ) -> dict[str, object]:
        """Authorize and price a booking modification without changing state."""

        if not request.booking_id.strip():
            raise ValidationError("booking_id must not be empty")
        if all(
            value is None
            for value in (
                request.room_type,
                request.check_in,
                request.check_out,
                request.guests,
            )
        ):
            raise ValidationError("at least one booking field must be changed")
        _validate_room_type(request.room_type, optional=True)
        with self.store.transaction():
            current = self._get_authorized_booking(context, request.booking_id)
            if current["status"] == "cancelled":
                raise ConflictError("cancelled booking cannot be modified")
            if (
                current["status"] == "held"
                and current["hold_expires_at"]
                and datetime.fromisoformat(current["hold_expires_at"]) <= utc_now()
            ):
                raise ConflictError("expired booking hold cannot be modified")
            room_type = request.room_type or current["room_type"]
            check_in = request.check_in or current["check_in"]
            check_out = request.check_out or current["check_out"]
            guests = request.guests if request.guests is not None else int(current["guests"])
            _, _, nights = _parse_stay(check_in, check_out)
            _validate_guests(guests)
            rows = self._availability_rows(
                check_in,
                check_out,
                guests,
                room_type=room_type,
                exclude_booking_id=request.booking_id,
            )
            if not rows:
                raise NotFoundError("room type does not exist or cannot fit guest count")
            room = rows[0]
            if int(room["available_rooms"]) <= 0:
                raise ConflictError("no room is available for the modified stay")
            current_total = int(current["total_cents"])
            new_total = int(room["nightly_rate_cents"]) * nights
            return {
                "booking_id": request.booking_id,
                "current": {
                    "room_type": current["room_type"],
                    "check_in": current["check_in"],
                    "check_out": current["check_out"],
                    "guests": int(current["guests"]),
                    "total_cents": current_total,
                },
                "proposed": {
                    "room_type": room_type,
                    "check_in": check_in,
                    "check_out": check_out,
                    "guests": guests,
                    "nights": nights,
                    "total_cents": new_total,
                },
                "price_delta_cents": new_total - current_total,
                "currency": current["currency"],
            }

    def modify_booking(
        self, context: UserContext, request: ModifyBookingInput
    ) -> BookingResult:
        if not request.booking_id.strip():
            raise ValidationError("booking_id must not be empty")
        if all(
            value is None
            for value in (
                request.room_type,
                request.check_in,
                request.check_out,
                request.guests,
            )
        ):
            raise ValidationError("at least one booking field must be changed")
        _validate_room_type(request.room_type, optional=True)
        with self.store.transaction():
            current = self._get_authorized_booking(context, request.booking_id)
            if current["status"] == "cancelled":
                raise ConflictError("cancelled booking cannot be modified")
            if (
                current["status"] == "held"
                and current["hold_expires_at"]
                and datetime.fromisoformat(current["hold_expires_at"]) <= utc_now()
            ):
                raise ConflictError("expired booking hold cannot be modified")
            room_type = request.room_type or current["room_type"]
            check_in = request.check_in or current["check_in"]
            check_out = request.check_out or current["check_out"]
            guests = request.guests if request.guests is not None else int(current["guests"])
            _, _, nights = _parse_stay(check_in, check_out)
            _validate_guests(guests)
            rows = self._availability_rows(
                check_in,
                check_out,
                guests,
                room_type=room_type,
                exclude_booking_id=request.booking_id,
            )
            if not rows:
                raise NotFoundError("room type does not exist or cannot fit guest count")
            room = rows[0]
            if int(room["available_rooms"]) <= 0:
                raise ConflictError("no room is available for the modified stay")
            self.store.connection.execute(
                """
                UPDATE bookings SET room_type = ?, check_in = ?, check_out = ?,
                    guests = ?, total_cents = ?, updated_at = ?
                WHERE booking_id = ?
                """,
                (
                    room_type,
                    check_in,
                    check_out,
                    int(guests),
                    int(room["nightly_rate_cents"]) * nights,
                    iso_utc(),
                    request.booking_id,
                ),
            )
            updated = self.store.connection.execute(
                "SELECT * FROM bookings WHERE booking_id = ?", (request.booking_id,)
            ).fetchone()
            self.store.audit(
                context,
                action="modify_booking",
                effect=ToolEffect.WRITE,
                resource_type="booking",
                resource_id=request.booking_id,
                details={"room_type": room_type, "nights": nights},
            )
            return BookingResult(self._booking_view(updated))

    def preview_service_ticket(
        self, context: UserContext, request: CreateServiceTicketInput
    ) -> dict[str, object]:
        category = request.category.strip().lower()
        description = request.description.strip()
        if category not in ALLOWED_TICKET_CATEGORIES:
            raise ValidationError("unsupported service ticket category")
        if not description or len(description) > 1_000:
            raise ValidationError("description must contain 1 to 1000 characters")
        _reject_sensitive_free_text(description)
        with self.store.transaction():
            booking = self._get_authorized_booking(context, request.booking_id)
            if booking["status"] == "cancelled":
                raise ConflictError("service ticket requires an active booking")
            if (
                booking["status"] == "held"
                and booking["hold_expires_at"]
                and datetime.fromisoformat(booking["hold_expires_at"]) <= utc_now()
            ):
                raise ConflictError("service ticket requires an unexpired booking hold")
            return {
                "booking_id": request.booking_id,
                "category": category,
                "description_chars": len(description),
            }

    def create_service_ticket(
        self, context: UserContext, request: CreateServiceTicketInput
    ) -> ServiceTicketResult:
        category = request.category.strip().lower()
        description = request.description.strip()
        if category not in ALLOWED_TICKET_CATEGORIES:
            raise ValidationError("unsupported service ticket category")
        if not description or len(description) > 1_000:
            raise ValidationError("description must contain 1 to 1000 characters")
        _reject_sensitive_free_text(description)
        with self.store.transaction():
            booking = self._get_authorized_booking(context, request.booking_id)
            if booking["status"] == "cancelled":
                raise ConflictError("service ticket requires an active booking")
            if (
                booking["status"] == "held"
                and booking["hold_expires_at"]
                and datetime.fromisoformat(booking["hold_expires_at"]) <= utc_now()
            ):
                raise ConflictError("service ticket requires an unexpired booking hold")
            ticket_id = f"TKT-{uuid.uuid4().hex[:12].upper()}"
            self.store.connection.execute(
                """
                INSERT INTO service_tickets(
                    ticket_id, booking_id, created_by, category,
                    description, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    request.booking_id,
                    context.user_id,
                    category,
                    description,
                    iso_utc(),
                ),
            )
            self.store.audit(
                context,
                action="create_service_ticket",
                effect=ToolEffect.WRITE,
                resource_type="service_ticket",
                resource_id=ticket_id,
                details={"category": category},
            )
            return ServiceTicketResult(ticket_id, request.booking_id, category, "open")

    def set_memory_consent(
        self, context: UserContext, request: SetMemoryConsentInput
    ) -> MemoryConsentResult:
        with self.store.transaction():
            removed = 0
            if not request.enabled:
                cursor = self.store.connection.execute(
                    "DELETE FROM user_preferences WHERE user_id = ?", (context.user_id,)
                )
                removed = max(0, cursor.rowcount)
            self.store.connection.execute(
                """
                INSERT INTO memory_consent(user_id, enabled, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    enabled = excluded.enabled, updated_at = excluded.updated_at
                """,
                (context.user_id, int(request.enabled), iso_utc()),
            )
            self.store.audit(
                context,
                action="set_memory_consent",
                effect=ToolEffect.WRITE,
                resource_type="memory_consent",
                details={"enabled": request.enabled, "removed_preferences": removed},
            )
            return MemoryConsentResult(request.enabled, removed)

    def _has_memory_consent(self, user_id: str) -> bool:
        row = self.store.connection.execute(
            "SELECT enabled FROM memory_consent WHERE user_id = ?", (user_id,)
        ).fetchone()
        return bool(row and row["enabled"])

    def preview_preference_storage(
        self, context: UserContext, request: RememberPreferenceInput
    ) -> dict[str, object]:
        del context
        key = request.key.strip().lower()
        value = request.value.strip()
        if key not in ALLOWED_PREFERENCE_KEYS:
            raise ValidationError("preference key is not allow-listed")
        if not value or len(value) > 200:
            raise ValidationError("preference value must contain 1 to 200 characters")
        _reject_sensitive_free_text(value)
        return {"key": key, "value_chars": len(value)}

    def remember_preference(
        self, context: UserContext, request: RememberPreferenceInput
    ) -> PreferenceResult:
        key = request.key.strip().lower()
        value = request.value.strip()
        if key not in ALLOWED_PREFERENCE_KEYS:
            raise ValidationError("preference key is not allow-listed")
        if not value or len(value) > 200:
            raise ValidationError("preference value must contain 1 to 200 characters")
        _reject_sensitive_free_text(value)
        with self.store.transaction():
            if not self._has_memory_consent(context.user_id):
                raise ConsentRequired("memory is disabled; explicit opt-in is required")
            self.store.connection.execute(
                """
                INSERT INTO user_preferences(
                    user_id, preference_key, preference_value, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, preference_key) DO UPDATE SET
                    preference_value = excluded.preference_value,
                    updated_at = excluded.updated_at
                """,
                (context.user_id, key, value, iso_utc()),
            )
            self.store.audit(
                context,
                action="remember_preference",
                effect=ToolEffect.WRITE,
                resource_type="preference",
                resource_id=key,
                details={"preference_key": key},
            )
            return PreferenceResult(key, True)

    def get_preferences(
        self, context: UserContext, request: GetPreferencesInput
    ) -> PreferencesResult:
        del request
        with self.store.transaction():
            if not self._has_memory_consent(context.user_id):
                return PreferencesResult(())
            rows = self.store.connection.execute(
                """
                SELECT preference_key, preference_value FROM user_preferences
                WHERE user_id = ? ORDER BY preference_key
                """,
                (context.user_id,),
            ).fetchall()
            result = PreferencesResult(
                tuple((row["preference_key"], row["preference_value"]) for row in rows)
            )
            self.store.audit(
                context,
                action="get_preferences",
                effect=ToolEffect.READ,
                resource_type="preference",
                details={"result_count": len(result.preferences)},
            )
            return result

    def delete_preference(
        self, context: UserContext, request: DeletePreferenceInput
    ) -> DeletePreferenceResult:
        key = request.key.strip().lower()
        if key not in ALLOWED_PREFERENCE_KEYS:
            raise ValidationError("preference key is not allow-listed")
        with self.store.transaction():
            cursor = self.store.connection.execute(
                """
                DELETE FROM user_preferences
                WHERE user_id = ? AND preference_key = ?
                """,
                (context.user_id, key),
            )
            deleted = cursor.rowcount > 0
            self.store.audit(
                context,
                action="delete_preference",
                effect=ToolEffect.WRITE,
                resource_type="preference",
                resource_id=key,
                details={"deleted": deleted},
            )
            return DeletePreferenceResult(key, deleted)
