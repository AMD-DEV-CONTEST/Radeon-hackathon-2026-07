from __future__ import annotations

import json
import unittest
from dataclasses import asdict

from radeonstay.domain import (
    AvailabilityInput,
    ConfirmationRequired,
    ConsentRequired,
    CreateServiceTicketInput,
    DeletePreferenceInput,
    GetPreferencesInput,
    HoldBookingInput,
    HotelService,
    HotelStore,
    IdempotencyConflict,
    ModifyBookingInput,
    MyBookingsInput,
    PermissionDenied,
    QuoteInput,
    RememberPreferenceInput,
    Role,
    SetMemoryConsentInput,
    ToolEffect,
    UserContext,
    ValidationError,
    build_tool_registry,
)


class HotelDomainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = HotelStore(":memory:")
        self.store.initialize(seed=True)
        self.service = HotelService(self.store)
        self.registry = build_tool_registry(self.service)
        self.alice = UserContext("alice-local-id")
        self.bob = UserContext("bob-local-id")
        self.staff = UserContext("front-desk-7", Role.STAFF)

    def tearDown(self) -> None:
        self.store.close()

    def invoke_confirmed(self, name, context, request, key):
        with self.assertRaises(ConfirmationRequired) as challenge:
            self.registry.invoke(name, context, request, idempotency_key=key)
        return self.registry.invoke(
            name,
            context,
            request,
            idempotency_key=key,
            confirmation_token=challenge.exception.token,
        )

    def hold_for_alice(self, *, key="hold-alice"):
        return self.invoke_confirmed(
            "hotel.hold_booking",
            self.alice,
            HoldBookingInput("standard", "2030-06-01", "2030-06-03", 2),
            key,
        )

    def test_initialize_and_seed_are_idempotent(self) -> None:
        self.store.initialize(seed=True)
        count = self.store.connection.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
        self.assertEqual(count, 3)

    def test_registry_exposes_typed_read_and_write_effects(self) -> None:
        schemas = {item["name"]: item for item in self.registry.schemas()}
        self.assertEqual(schemas["hotel.quote_stay"]["effect"], ToolEffect.READ.value)
        self.assertFalse(schemas["hotel.quote_stay"]["requires_confirmation"])
        self.assertEqual(schemas["hotel.hold_booking"]["effect"], ToolEffect.WRITE.value)
        self.assertTrue(schemas["hotel.hold_booking"]["requires_idempotency_key"])
        self.assertEqual(
            schemas["hotel.hold_booking"]["parameters"]["properties"]["room_type"][
                "enum"
            ],
            ["standard", "deluxe", "suite"],
        )
        self.assertIn(
            "check_in",
            schemas["hotel.hold_booking"]["parameters"]["required"],
        )
        self.assertEqual(
            schemas["hotel.modify_booking"]["parameters"]["anyOf"],
            [
                {"required": ["room_type"]},
                {"required": ["check_in"]},
                {"required": ["check_out"]},
                {"required": ["guests"]},
            ],
        )
        availability_items = schemas["hotel.check_availability"]["returns"][
            "properties"
        ]["items"]
        self.assertEqual(availability_items["type"], "array")
        self.assertIn("room_type", availability_items["items"]["properties"])
        booking_output = schemas["hotel.hold_booking"]["returns"]["properties"]
        self.assertIn("booking_id", booking_output["booking"]["properties"])
        self.assertIn("memory.delete_preference", schemas)

    def test_availability_and_quote_are_local_deterministic_reads(self) -> None:
        availability = self.registry.invoke(
            "hotel.check_availability",
            self.alice,
            AvailabilityInput("2030-05-01", "2030-05-04", 2, "standard"),
        )
        self.assertEqual(availability.items[0].available_rooms, 8)

        quote = self.registry.invoke(
            "hotel.quote_stay",
            self.alice,
            QuoteInput("standard", "2030-05-01", "2030-05-04", 2),
        )
        self.assertEqual(quote.nights, 3)
        self.assertEqual(quote.total_cents, 3 * 12_900)
        self.assertTrue(quote.available)

    def test_registry_rejects_wrong_json_types_before_any_write_challenge(self) -> None:
        with self.assertRaises(ValidationError):
            self.registry.invoke(
                "hotel.check_availability",
                self.alice,
                {
                    "check_in": "2030-05-01",
                    "check_out": "2030-05-04",
                    "guests": 1.5,
                },
            )
        with self.assertRaises(ValidationError):
            self.registry.invoke(
                "memory.set_consent",
                self.alice,
                {"enabled": "false"},
                idempotency_key="bad-bool",
            )
        with self.assertRaises(ValidationError):
            self.registry.invoke(
                "hotel.hold_booking",
                self.alice,
                {
                    "room_type": "penthouse",
                    "check_in": "2030-05-01",
                    "check_out": "2030-05-04",
                    "guests": 1,
                },
                idempotency_key="bad-room-type",
            )
        with self.assertRaises(ValidationError):
            self.registry.invoke(
                "hotel.modify_booking",
                self.alice,
                {"booking_id": "RSV-NOOP"},
                idempotency_key="bad-noop-modify",
            )
        count = self.store.connection.execute(
            "SELECT COUNT(*) FROM confirmation_tokens"
        ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_write_requires_confirmation_and_is_idempotent(self) -> None:
        request = HoldBookingInput("standard", "2030-06-01", "2030-06-03", 2)
        with self.assertRaises(ConfirmationRequired) as preview_challenge:
            self.registry.invoke(
                "hotel.hold_booking",
                self.alice,
                request,
                idempotency_key="preview-terms",
            )
        self.assertEqual(preview_challenge.exception.preview["total_cents"], 25_800)
        self.assertEqual(preview_challenge.exception.preview["available_rooms"], 8)
        first = self.invoke_confirmed(
            "hotel.hold_booking", self.alice, request, "client-operation-1"
        )
        replay = self.registry.invoke(
            "hotel.hold_booking",
            self.alice,
            request,
            idempotency_key="client-operation-1",
        )
        self.assertEqual(first, replay)
        count = self.store.connection.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
        self.assertEqual(count, 1)

        with self.assertRaises(IdempotencyConflict):
            self.registry.invoke(
                "hotel.hold_booking",
                self.alice,
                HoldBookingInput("deluxe", "2030-06-01", "2030-06-03", 2),
                idempotency_key="client-operation-1",
            )

    def test_confirmation_rejects_changed_authoritative_preview(self) -> None:
        request = HoldBookingInput("standard", "2030-06-10", "2030-06-12", 2)
        with self.assertRaises(ConfirmationRequired) as challenge:
            self.registry.invoke(
                "hotel.hold_booking",
                self.alice,
                request,
                idempotency_key="stale-preview",
            )
        self.assertEqual(challenge.exception.preview["total_cents"], 25_800)

        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE rooms SET nightly_rate_cents = 13900 WHERE room_type = 'standard'"
            )

        with self.assertRaisesRegex(PermissionDenied, "authoritative preview terms changed"):
            self.registry.invoke(
                "hotel.hold_booking",
                self.alice,
                request,
                idempotency_key="stale-preview",
                confirmation_token=challenge.exception.token,
            )
        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM bookings").fetchone()[0],
            0,
        )
        token_row = self.store.connection.execute(
            "SELECT used_at FROM confirmation_tokens"
        ).fetchone()
        self.assertIsNotNone(token_row)
        self.assertIsNone(token_row["used_at"])
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM idempotency_records"
            ).fetchone()[0],
            0,
        )

        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE rooms SET nightly_rate_cents = 12900 WHERE room_type = 'standard'"
            )
        completed = self.registry.invoke(
            "hotel.hold_booking",
            self.alice,
            request,
            idempotency_key="stale-preview",
            confirmation_token=challenge.exception.token,
        )
        self.assertEqual(completed.booking.total_cents, 25_800)
        replayed = self.registry.invoke(
            "hotel.hold_booking",
            self.alice,
            request,
            idempotency_key="stale-preview",
        )
        self.assertEqual(replayed, completed)
        self.assertEqual(
            self.store.connection.execute("SELECT COUNT(*) FROM bookings").fetchone()[0],
            1,
        )

    def test_confirmation_token_is_bound_to_actor_tool_and_payload(self) -> None:
        request = HoldBookingInput("standard", "2030-07-01", "2030-07-02", 1)
        with self.assertRaises(ConfirmationRequired) as challenge:
            self.registry.invoke(
                "hotel.hold_booking", self.alice, request, idempotency_key="bound-1"
            )
        with self.assertRaises(PermissionDenied):
            self.registry.invoke(
                "memory.set_consent",
                self.alice,
                SetMemoryConsentInput(True),
                idempotency_key="bound-wrong-tool",
                confirmation_token=challenge.exception.token,
            )
        with self.assertRaises(PermissionDenied):
            self.registry.invoke(
                "hotel.hold_booking",
                self.alice,
                HoldBookingInput("standard", "2030-07-01", "2030-07-03", 1),
                idempotency_key="bound-wrong-payload",
                confirmation_token=challenge.exception.token,
            )
        with self.assertRaises(PermissionDenied):
            self.registry.invoke(
                "hotel.hold_booking",
                self.bob,
                request,
                idempotency_key="bound-2",
                confirmation_token=challenge.exception.token,
            )

    def test_owner_isolation_and_staff_override(self) -> None:
        held = self.hold_for_alice()
        booking_id = held.booking.booking_id

        bob_bookings = self.registry.invoke(
            "hotel.my_bookings", self.bob, MyBookingsInput()
        )
        self.assertEqual(bob_bookings.bookings, ())

        unauthorized = ModifyBookingInput(booking_id, guests=1)
        with self.assertRaises(PermissionDenied):
            self.registry.invoke(
                "hotel.modify_booking",
                self.bob,
                unauthorized,
                idempotency_key="bob-modify",
            )

        missing = ModifyBookingInput("RSV-DOES-NOT-EXIST", guests=1)
        with self.assertRaisesRegex(
            PermissionDenied,
            "booking not found or not accessible",
        ):
            self.registry.invoke(
                "hotel.modify_booking",
                self.bob,
                missing,
                idempotency_key="bob-missing-modify",
            )

        changed = self.invoke_confirmed(
            "hotel.modify_booking",
            self.staff,
            ModifyBookingInput(booking_id, room_type="deluxe", guests=3),
            "staff-modify",
        )
        self.assertEqual(changed.booking.room_type, "deluxe")
        self.assertEqual(changed.booking.guests, 3)

    def test_service_ticket_honors_booking_ownership(self) -> None:
        held = self.hold_for_alice()
        request = CreateServiceTicketInput(
            held.booking.booking_id,
            "accessibility",
            "Please provide step-free access; call alice@example.test.",
        )
        ticket = self.invoke_confirmed(
            "hotel.create_service_ticket", self.alice, request, "ticket-1"
        )
        self.assertEqual(ticket.status, "open")

        with self.assertRaises(PermissionDenied):
            self.registry.invoke(
                "hotel.create_service_ticket",
                self.bob,
                request,
                idempotency_key="ticket-bob",
            )

    def test_sensitive_credentials_are_rejected_before_confirmation(self) -> None:
        held = self.hold_for_alice()
        with self.assertRaisesRegex(ValidationError, "must not be stored"):
            self.registry.invoke(
                "hotel.create_service_ticket",
                self.alice,
                CreateServiceTicketInput(
                    held.booking.booking_id,
                    "other",
                    "My password is correct-horse-battery-staple",
                ),
                idempotency_key="sensitive-ticket",
            )
        with self.assertRaisesRegex(ValidationError, "payment-card"):
            self.registry.invoke(
                "memory.remember_preference",
                self.alice,
                RememberPreferenceInput("quiet_room", "4111 1111 1111 1111"),
                idempotency_key="sensitive-memory",
            )

    def test_memory_requires_opt_in_and_disabling_erases_values(self) -> None:
        preference = RememberPreferenceInput("bed_type", "king")
        with self.assertRaises(ConfirmationRequired) as challenge:
            self.registry.invoke(
                "memory.remember_preference",
                self.alice,
                preference,
                idempotency_key="memory-before-optin",
            )
        with self.assertRaises(ConsentRequired):
            self.registry.invoke(
                "memory.remember_preference",
                self.alice,
                preference,
                idempotency_key="memory-before-optin",
                confirmation_token=challenge.exception.token,
            )

        self.invoke_confirmed(
            "memory.set_consent",
            self.alice,
            SetMemoryConsentInput(True),
            "consent-on",
        )
        self.invoke_confirmed(
            "memory.remember_preference",
            self.alice,
            preference,
            "memory-save",
        )
        remembered = self.registry.invoke(
            "memory.get_preferences", self.alice, GetPreferencesInput()
        )
        self.assertEqual(remembered.preferences, (("bed_type", "king"),))

        deleted = self.invoke_confirmed(
            "memory.delete_preference",
            self.alice,
            DeletePreferenceInput("bed_type"),
            "memory-delete",
        )
        self.assertTrue(deleted.deleted)

        self.invoke_confirmed(
            "memory.remember_preference",
            self.alice,
            RememberPreferenceInput("pillow", "firm"),
            "memory-save-2",
        )
        disabled = self.invoke_confirmed(
            "memory.set_consent",
            self.alice,
            SetMemoryConsentInput(False),
            "consent-off",
        )
        self.assertEqual(disabled.removed_preferences, 1)
        self.assertEqual(
            self.registry.invoke(
                "memory.get_preferences", self.alice, GetPreferencesInput()
            ).preferences,
            (),
        )

    def test_audit_uses_actor_hash_and_omits_pii_and_free_text(self) -> None:
        held = self.hold_for_alice()
        self.invoke_confirmed(
            "hotel.create_service_ticket",
            self.alice,
            CreateServiceTicketInput(
                held.booking.booking_id,
                "other",
                "Alice Smith, +86 13800000000, alice@example.test",
            ),
            "pii-ticket",
        )
        audit = self.store.list_audit(self.staff)
        serialized = json.dumps([asdict(item) for item in audit], ensure_ascii=False)
        self.assertNotIn(self.alice.user_id, serialized)
        self.assertNotIn("Alice Smith", serialized)
        self.assertNotIn("13800000000", serialized)
        self.assertNotIn("alice@example.test", serialized)
        self.assertTrue(all(item.actor_ref.startswith("usr_") for item in audit))


if __name__ == "__main__":
    unittest.main()
