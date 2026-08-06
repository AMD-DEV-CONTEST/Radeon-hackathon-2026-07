from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from ..security import sensitive_material_kind
from .models import (
    AvailabilityInput,
    AvailabilityItem,
    AvailabilityResult,
    BookingListResult,
    BookingResult,
    BookingView,
    BuildStayBriefInput,
    ConflictError,
    ConsentRequired,
    CreateServiceTicketInput,
    DeletePreferenceInput,
    DeletePreferenceResult,
    GetPreferencesInput,
    HoldBookingInput,
    ListServiceTicketsInput,
    MemoryConsentResult,
    ModifyBookingInput,
    MyBookingsInput,
    NotFoundError,
    OwnerScopeAttestation,
    PermissionDenied,
    PreferenceResult,
    PreferencesResult,
    QuoteInput,
    QuoteResult,
    RememberPreferenceInput,
    ServiceTicketListResult,
    ServiceTicketResult,
    ServiceTicketView,
    SetMemoryConsentInput,
    StayBriefResult,
    StayBriefServiceTicket,
    ToolEffect,
    UpdateServiceTicketInput,
    UpdateServiceTicketResult,
    UserContext,
    ValidationError,
)
from .storage import HotelStore, iso_utc, stable_hash, utc_now

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
ALLOWED_TICKET_STATUSES = {"open", "in_progress", "resolved", "cancelled"}
ALLOWED_ROOM_TYPES = {"standard", "deluxe", "suite"}
def _service_ticket_state_sha256(row) -> str:
    """Hash authoritative ticket state without exposing free-text descriptions."""

    return stable_hash(
        {
            "ticket_id": str(row["ticket_id"]),
            "booking_id": str(row["booking_id"]),
            "category": str(row["category"]),
            "description": str(row["description"]),
            "status": str(row["status"]),
            "updated_at": str(row["updated_at"]),
        }
    )


def _reject_sensitive_free_text(value: str) -> None:
    kind = sensitive_material_kind(value)
    if kind == "credential":
        raise ValidationError("credentials and payment secrets must not be stored")
    if kind == "token":
        raise ValidationError("API or access tokens must not be stored")
    if kind == "payment_card":
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

    @staticmethod
    def _owner_scope_attestation(result_count: int) -> OwnerScopeAttestation:
        """Attest the result of an SQL path constrained to the authenticated owner."""

        return OwnerScopeAttestation(owner_scoped_result_count=max(0, result_count))

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
            bookings = tuple(self._booking_view(row) for row in rows)
            result = BookingListResult(
                bookings,
                self._owner_scope_attestation(len(bookings)),
            )
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
                "_binding_booking_state": stable_hash(
                    {
                        "status": current["status"],
                        "hold_expires_at": current["hold_expires_at"],
                        "updated_at": current["updated_at"],
                    }
                ),
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

    @staticmethod
    def _service_ticket_view(row) -> ServiceTicketView:
        return ServiceTicketView(
            ticket_id=str(row["ticket_id"]),
            booking_id=str(row["booking_id"]),
            category=str(row["category"]),
            description=str(row["description"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            state_sha256=_service_ticket_state_sha256(row),
        )

    def _get_authorized_service_ticket(
        self,
        context: UserContext,
        ticket_id: str,
    ):
        row = self.store.connection.execute(
            """
            SELECT t.*, b.user_id AS booking_owner,
                   b.currency AS booking_currency
            FROM service_tickets t
            JOIN bookings b ON b.booking_id = t.booking_id
            WHERE t.ticket_id = ?
            """,
            (ticket_id,),
        ).fetchone()
        if context.is_staff:
            if row is None:
                raise NotFoundError("service ticket not found")
            return row
        if row is None or row["booking_owner"] != context.user_id:
            raise PermissionDenied("service ticket not found or not accessible")
        return row

    @staticmethod
    def _normalized_ticket_update(
        request: UpdateServiceTicketInput,
    ) -> tuple[str, str | None, str | None]:
        ticket_id = request.ticket_id.strip()
        if not ticket_id:
            raise ValidationError("ticket_id must not be empty")
        if request.status is None and request.description is None:
            raise ValidationError("at least one service ticket field must be changed")
        status = request.status.strip().lower() if request.status is not None else None
        if status is not None and status not in ALLOWED_TICKET_STATUSES:
            raise ValidationError("unsupported service ticket status")
        description = (
            request.description.strip() if request.description is not None else None
        )
        if description is not None:
            if not description or len(description) > 1_000:
                raise ValidationError("description must contain 1 to 1000 characters")
            _reject_sensitive_free_text(description)
        return ticket_id, status, description

    def list_service_tickets(
        self,
        context: UserContext,
        request: ListServiceTicketsInput,
    ) -> ServiceTicketListResult:
        booking_id = request.booking_id.strip() if request.booking_id is not None else None
        if request.booking_id is not None and not booking_id:
            raise ValidationError("booking_id must not be empty")
        clauses = ["b.user_id = ?"]
        arguments: list[object] = [context.user_id]
        if booking_id is not None:
            clauses.append("t.booking_id = ?")
            arguments.append(booking_id)
        if not request.include_closed:
            clauses.append("t.status NOT IN ('resolved', 'cancelled')")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.store.transaction():
            rows = self.store.connection.execute(
                f"""
                SELECT t.* FROM service_tickets t
                JOIN bookings b ON b.booking_id = t.booking_id
                {where}
                ORDER BY t.updated_at DESC, t.ticket_id
                """,
                tuple(arguments),
            ).fetchall()
            tickets = tuple(self._service_ticket_view(row) for row in rows)
            result = ServiceTicketListResult(
                tickets,
                self._owner_scope_attestation(len(tickets)),
            )
            self.store.audit(
                context,
                action="list_service_tickets",
                effect=ToolEffect.READ,
                resource_type="service_ticket",
                details={
                    "result_count": len(result.tickets),
                    "booking_filter": booking_id is not None,
                    "include_closed": request.include_closed,
                },
            )
            return result

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
            active_ticket_rows = self.store.connection.execute(
                """
                SELECT ticket_id, status, updated_at
                FROM service_tickets
                WHERE booking_id = ? AND category = ?
                  AND status NOT IN ('resolved', 'cancelled')
                ORDER BY ticket_id
                """,
                (request.booking_id, category),
            ).fetchall()
            return {
                "booking_id": request.booking_id,
                "category": category,
                "description_chars": len(description),
                "stay_price_delta_cents": 0,
                "currency": str(booking["currency"]),
                "external_service_price": "not_quoted",
                "_binding_booking_state": stable_hash(
                    {
                        "status": booking["status"],
                        "hold_expires_at": booking["hold_expires_at"],
                        "updated_at": booking["updated_at"],
                    }
                ),
                # Recomputed atomically at confirmation time. A newly created,
                # resolved, cancelled, or otherwise changed active ticket makes
                # the old capability stale instead of creating a duplicate from
                # a no-longer-authoritative preview.
                "_binding_active_ticket_scope": stable_hash(
                    [
                        {
                            "ticket_id": str(row["ticket_id"]),
                            "status": str(row["status"]),
                            "updated_at": str(row["updated_at"]),
                        }
                        for row in active_ticket_rows
                    ]
                ),
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
            now = iso_utc()
            self.store.connection.execute(
                """
                INSERT INTO service_tickets(
                    ticket_id, booking_id, created_by, category,
                    description, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    request.booking_id,
                    context.user_id,
                    category,
                    description,
                    now,
                    now,
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
            created = self.store.connection.execute(
                "SELECT * FROM service_tickets WHERE ticket_id = ?",
                (ticket_id,),
            ).fetchone()
            return ServiceTicketResult(
                ticket_id,
                request.booking_id,
                category,
                "open",
                now,
                _service_ticket_state_sha256(created),
            )

    def preview_update_service_ticket(
        self,
        context: UserContext,
        request: UpdateServiceTicketInput,
    ) -> dict[str, object]:
        ticket_id, status, description = self._normalized_ticket_update(request)
        with self.store.transaction():
            current = self._get_authorized_service_ticket(context, ticket_id)
            proposed_status = status or str(current["status"])
            proposed_description = (
                description if description is not None else str(current["description"])
            )
            if (
                proposed_status == current["status"]
                and proposed_description == current["description"]
            ):
                raise ConflictError("service ticket update would not change any field")
            return {
                "ticket_id": ticket_id,
                "booking_id": str(current["booking_id"]),
                "category": str(current["category"]),
                "current_status": str(current["status"]),
                "proposed_status": proposed_status,
                "description_changed": proposed_description != current["description"],
                "description_chars": len(proposed_description),
                "current_updated_at": str(current["updated_at"]),
                "stay_price_delta_cents": 0,
                "currency": str(current["booking_currency"]),
                "external_service_price": "not_quoted",
                "_binding_ticket_state": stable_hash(
                    {
                        "status": str(current["status"]),
                        "description": str(current["description"]),
                        "updated_at": str(current["updated_at"]),
                    }
                ),
            }

    def update_service_ticket(
        self,
        context: UserContext,
        request: UpdateServiceTicketInput,
    ) -> UpdateServiceTicketResult:
        ticket_id, status, description = self._normalized_ticket_update(request)
        with self.store.transaction():
            current = self._get_authorized_service_ticket(context, ticket_id)
            proposed_status = status or str(current["status"])
            proposed_description = (
                description if description is not None else str(current["description"])
            )
            if (
                proposed_status == current["status"]
                and proposed_description == current["description"]
            ):
                raise ConflictError("service ticket update would not change any field")
            updated_at = iso_utc()
            self.store.connection.execute(
                """
                UPDATE service_tickets
                SET status = ?, description = ?, updated_at = ?
                WHERE ticket_id = ?
                """,
                (proposed_status, proposed_description, updated_at, ticket_id),
            )
            updated = self.store.connection.execute(
                "SELECT * FROM service_tickets WHERE ticket_id = ?",
                (ticket_id,),
            ).fetchone()
            self.store.audit(
                context,
                action="update_service_ticket",
                effect=ToolEffect.WRITE,
                resource_type="service_ticket",
                resource_id=ticket_id,
                details={
                    "status": proposed_status,
                    "description_changed": proposed_description != current["description"],
                },
            )
            return UpdateServiceTicketResult(
                self._service_ticket_view(updated),
                _service_ticket_state_sha256(updated),
            )

    def build_stay_brief(
        self,
        context: UserContext,
        request: BuildStayBriefInput,
    ) -> StayBriefResult:
        """Build a safe owner-only brief from authoritative local records."""

        booking_id = request.booking_id.strip()
        if not booking_id:
            raise ValidationError("booking_id must not be empty")
        with self.store.transaction():
            booking = self.store.connection.execute(
                "SELECT * FROM bookings WHERE booking_id = ?",
                (booking_id,),
            ).fetchone()
            if booking is None or booking["user_id"] != context.user_id:
                raise PermissionDenied("booking not found or not accessible")
            # Closed rows remain in the owner-scoped authority set so callers can
            # distinguish a cancelled binding from a missing or cross-owner record.
            # Guest-facing renderers decide which historical rows to display.
            ticket_rows = self.store.connection.execute(
                """
                SELECT ticket_id, booking_id, category, description, status, updated_at
                FROM service_tickets
                WHERE booking_id = ?
                ORDER BY updated_at, ticket_id
                """,
                (booking_id,),
            ).fetchall()
            memory_enabled = self._has_memory_consent(context.user_id)
            preference_rows = (
                self.store.connection.execute(
                    """
                    SELECT preference_key, preference_value
                    FROM user_preferences
                    WHERE user_id = ? ORDER BY preference_key
                    """,
                    (context.user_id,),
                ).fetchall()
                if memory_enabled
                else ()
            )
            result = StayBriefResult(
                booking=self._booking_view(booking),
                service_tickets=tuple(
                    StayBriefServiceTicket(
                        ticket_id=str(row["ticket_id"]),
                        booking_id=booking_id,
                        category=str(row["category"]),
                        status=str(row["status"]),
                        updated_at=str(row["updated_at"]),
                        state_sha256=_service_ticket_state_sha256(row),
                    )
                    for row in ticket_rows
                ),
                memory_enabled=memory_enabled,
                preferences=tuple(
                    (str(row["preference_key"]), str(row["preference_value"]))
                    for row in preference_rows
                ),
                scope_attestation=self._owner_scope_attestation(
                    1 + len(ticket_rows) + len(preference_rows)
                ),
            )
            self.store.audit(
                context,
                action="build_stay_brief",
                effect=ToolEffect.READ,
                resource_type="stay_brief",
                resource_id=booking_id,
                details={
                    "ticket_count": len(result.service_tickets),
                    "preference_count": len(result.preferences),
                    "memory_enabled": memory_enabled,
                },
            )
            return result

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

    def preview_memory_consent(
        self,
        context: UserContext,
        request: SetMemoryConsentInput,
    ) -> dict[str, object]:
        """Bind consent to the current private-memory state without exposing values."""

        with self.store.transaction():
            consent = self.store.connection.execute(
                "SELECT enabled, updated_at FROM memory_consent WHERE user_id = ?",
                (context.user_id,),
            ).fetchone()
            preferences = self.store.connection.execute(
                """
                SELECT preference_key, preference_value, updated_at
                FROM user_preferences
                WHERE user_id = ? ORDER BY preference_key
                """,
                (context.user_id,),
            ).fetchall()
            current_enabled = bool(consent and consent["enabled"])
            return {
                "enabled": request.enabled,
                "current_enabled": current_enabled,
                "preference_count": len(preferences),
                "preferences_removed_on_disable": (
                    len(preferences) if not request.enabled else 0
                ),
                "_binding_memory_state": stable_hash(
                    {
                        "consent": dict(consent) if consent is not None else None,
                        "preferences": [dict(row) for row in preferences],
                    }
                ),
            }

    def _has_memory_consent(self, user_id: str) -> bool:
        row = self.store.connection.execute(
            "SELECT enabled FROM memory_consent WHERE user_id = ?", (user_id,)
        ).fetchone()
        return bool(row and row["enabled"])

    def preview_preference_storage(
        self, context: UserContext, request: RememberPreferenceInput
    ) -> dict[str, object]:
        key = request.key.strip().lower()
        value = request.value.strip()
        if key not in ALLOWED_PREFERENCE_KEYS:
            raise ValidationError("preference key is not allow-listed")
        if not value or len(value) > 200:
            raise ValidationError("preference value must contain 1 to 200 characters")
        _reject_sensitive_free_text(value)
        with self.store.transaction():
            consent = self.store.connection.execute(
                "SELECT enabled, updated_at FROM memory_consent WHERE user_id = ?",
                (context.user_id,),
            ).fetchone()
            current = self.store.connection.execute(
                """
                SELECT preference_value, updated_at FROM user_preferences
                WHERE user_id = ? AND preference_key = ?
                """,
                (context.user_id, key),
            ).fetchone()
            return {
                "key": key,
                "value_chars": len(value),
                "memory_enabled": bool(consent and consent["enabled"]),
                "replaces_existing": current is not None,
                "_binding_memory_state": stable_hash(
                    {
                        "consent": dict(consent) if consent is not None else None,
                        "current": dict(current) if current is not None else None,
                    }
                ),
            }

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
            rows = (
                self.store.connection.execute(
                    """
                    SELECT preference_key, preference_value FROM user_preferences
                    WHERE user_id = ? ORDER BY preference_key
                    """,
                    (context.user_id,),
                ).fetchall()
                if self._has_memory_consent(context.user_id)
                else ()
            )
            preferences = tuple(
                (row["preference_key"], row["preference_value"]) for row in rows
            )
            result = PreferencesResult(
                preferences,
                self._owner_scope_attestation(len(preferences)),
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

    def preview_delete_preference(
        self,
        context: UserContext,
        request: DeletePreferenceInput,
    ) -> dict[str, object]:
        key = request.key.strip().lower()
        if key not in ALLOWED_PREFERENCE_KEYS:
            raise ValidationError("preference key is not allow-listed")
        with self.store.transaction():
            current = self.store.connection.execute(
                """
                SELECT preference_value, updated_at FROM user_preferences
                WHERE user_id = ? AND preference_key = ?
                """,
                (context.user_id, key),
            ).fetchone()
            return {
                "key": key,
                "exists": current is not None,
                "_binding_preference_state": stable_hash(
                    dict(current) if current is not None else None
                ),
            }
