from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from radeonstay.domain import (
    AvailabilityInput,
    ConfirmationRequired,
    ConflictError,
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
    minimize_audit_details,
)
from radeonstay.domain.models import (
    BuildStayBriefInput,
    ListServiceTicketsInput,
    UpdateServiceTicketInput,
)
from radeonstay.domain.storage import (
    AUDIT_GENESIS_HASH,
    AUDIT_KEY_ID_METADATA_KEY,
    CURRENT_SCHEMA_VERSION,
    actor_reference,
    audit_key_id,
    sign_session_audit_payload,
)

AUDIT_SECRET = "domain-unittest-audit-secret-00000001"


def signed_session_event(
    index: int,
    *,
    actor_ref: str,
    previous_hash: str = AUDIT_GENESIS_HASH,
    action: str = "journey.saved",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "event_id": f"evt_domain_{index:04d}",
        "occurred_at": f"2030-01-01T00:00:{index % 60:02d}+00:00",
        "actor_ref": actor_ref,
        "role": "guest",
        "action": action,
        "effect": "control",
        "outcome": "success",
        "details": {"index": index},
        "previous_hash": previous_hash,
    }
    return {
        **payload,
        "event_hash": sign_session_audit_payload(AUDIT_SECRET, payload),
        "chain_valid": True,
    }


def downgrade_audit_schema_to_real_v3(database: Path) -> None:
    """Create an actual five-column v3 audit table for migration coverage."""

    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            DROP TABLE session_audit_heads;
            DROP TABLE security_metadata;
            ALTER TABLE session_audit_events RENAME TO session_audit_events_v6;
            CREATE TABLE session_audit_events (
                session_id TEXT NOT NULL,
                sequence INTEGER NOT NULL CHECK (sequence > 0),
                actor_ref TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                event_json TEXT NOT NULL,
                PRIMARY KEY (session_id, sequence)
            );
            INSERT INTO session_audit_events(
                session_id, sequence, actor_ref, occurred_at, event_json
            )
            SELECT session_id, sequence, actor_ref, occurred_at, event_json
            FROM session_audit_events_v6;
            DROP TABLE session_audit_events_v6;
            CREATE INDEX idx_session_audit_actor
            ON session_audit_events(actor_ref, session_id, sequence);
            PRAGMA user_version = 3;
            """
        )
    finally:
        connection.close()


class HotelDomainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = HotelStore(":memory:", audit_secret=AUDIT_SECRET)
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
        self.assertEqual(self.store.schema_version, CURRENT_SCHEMA_VERSION)

    def test_incremental_schema_migrates_existing_service_tickets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "legacy.sqlite3"
            connection = sqlite3.connect(database)
            connection.executescript(
                """
                CREATE TABLE service_tickets (
                    ticket_id TEXT PRIMARY KEY,
                    booking_id TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL
                );
                INSERT INTO service_tickets(
                    ticket_id, booking_id, created_by, category,
                    description, status, created_at
                ) VALUES (
                    'TKT-LEGACY', 'RSV-LEGACY', 'legacy-owner', 'other',
                    'legacy row', 'open', '2029-01-01T00:00:00+00:00'
                );
                PRAGMA user_version = 1;
                """
            )
            connection.close()

            migrated = HotelStore(database, audit_secret=AUDIT_SECRET)
            try:
                migrated.initialize(seed=False)
                self.assertEqual(migrated.schema_version, CURRENT_SCHEMA_VERSION)
                ticket_columns = {
                    row["name"]
                    for row in migrated.connection.execute(
                        "PRAGMA table_info(service_tickets)"
                    )
                }
                self.assertIn("updated_at", ticket_columns)
                row = migrated.connection.execute(
                    "SELECT created_at, updated_at FROM service_tickets "
                    "WHERE ticket_id = 'TKT-LEGACY'"
                ).fetchone()
                self.assertEqual(row["updated_at"], row["created_at"])
                migrated.initialize(seed=False)
                self.assertEqual(migrated.schema_version, CURRENT_SCHEMA_VERSION)
            finally:
                migrated.close()

    def test_v3_migration_verifies_history_before_storing_hmac_key_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "audit-v3.sqlite3"
            owner_ref = actor_reference(self.alice.user_id)
            legacy = HotelStore(database, audit_secret=AUDIT_SECRET)
            legacy.initialize(seed=False)
            legacy.append_session_audit_event(
                "legacy-audit-session",
                self.alice,
                signed_session_event(1, actor_ref=owner_ref),
            )
            legacy.close()
            downgrade_audit_schema_to_real_v3(database)

            migrated = HotelStore(database, audit_secret=AUDIT_SECRET)
            try:
                migrated.initialize(seed=False)
                metadata = migrated.connection.execute(
                    """
                    SELECT metadata_value FROM security_metadata
                    WHERE metadata_key = ?
                    """,
                    (AUDIT_KEY_ID_METADATA_KEY,),
                ).fetchone()
                self.assertIsNotNone(metadata)
                assert metadata is not None
                self.assertEqual(metadata["metadata_value"], audit_key_id(AUDIT_SECRET))
                self.assertNotIn(AUDIT_SECRET, metadata["metadata_value"])
                self.assertEqual(migrated.schema_version, CURRENT_SCHEMA_VERSION)
                row = migrated.connection.execute(
                    "SELECT row_hmac FROM session_audit_events"
                ).fetchone()
                self.assertIsNotNone(row)
                assert row is not None
                self.assertRegex(row["row_hmac"], r"^[0-9a-f]{64}$")
                head = migrated.connection.execute(
                    "SELECT event_count, last_event_hash, head_hmac "
                    "FROM session_audit_heads"
                ).fetchone()
                self.assertIsNotNone(head)
                assert head is not None
                self.assertEqual(head["event_count"], 1)
                self.assertRegex(head["last_event_hash"], r"^[0-9a-f]{64}$")
                self.assertRegex(head["head_hmac"], r"^[0-9a-f]{64}$")
            finally:
                migrated.close()

    def test_v3_migration_rolls_back_metadata_when_full_chain_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "tampered-v3.sqlite3"
            legacy = HotelStore(database, audit_secret=AUDIT_SECRET)
            legacy.initialize(seed=False)
            legacy.append_session_audit_event(
                "tampered-session",
                self.alice,
                signed_session_event(
                    1,
                    actor_ref=actor_reference(self.alice.user_id),
                ),
            )
            row = legacy.connection.execute(
                "SELECT event_json FROM session_audit_events"
            ).fetchone()
            tampered = json.loads(row["event_json"])
            tampered["details"]["index"] = 999
            legacy.connection.execute(
                "UPDATE session_audit_events SET event_json = ?",
                (json.dumps(tampered, sort_keys=True, separators=(",", ":")),),
            )
            legacy.close()
            downgrade_audit_schema_to_real_v3(database)

            migrating = HotelStore(database, audit_secret=AUDIT_SECRET)
            try:
                with self.assertRaisesRegex(RuntimeError, "signature is invalid"):
                    migrating.initialize(seed=False)
            finally:
                migrating.close()
            inspection = sqlite3.connect(database)
            try:
                self.assertEqual(inspection.execute("PRAGMA user_version").fetchone()[0], 3)
                metadata_table = inspection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name = 'security_metadata'
                    """
                ).fetchone()
                self.assertIsNone(metadata_table)
            finally:
                inspection.close()

    def test_concurrent_initializers_recheck_schema_version_under_write_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "concurrent-v3.sqlite3"
            seed = HotelStore(database, audit_secret=AUDIT_SECRET)
            seed.initialize(seed=False)
            seed.close()
            downgrade_audit_schema_to_real_v3(database)

            first = HotelStore(database, audit_secret=AUDIT_SECRET)
            second = HotelStore(database, audit_secret=AUDIT_SECRET)
            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [
                        executor.submit(store.initialize, seed=False)
                        for store in (first, second)
                    ]
                    for future in futures:
                        future.result()

                self.assertEqual(first.schema_version, CURRENT_SCHEMA_VERSION)
                self.assertEqual(second.schema_version, CURRENT_SCHEMA_VERSION)
                first._verify_all_session_audit_chains()
                second._verify_all_session_audit_chains()
            finally:
                first.close()
                second.close()

    def test_key_bound_database_rejects_a_different_audit_key_at_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "key-bound.sqlite3"
            bound = HotelStore(database, audit_secret=AUDIT_SECRET)
            bound.initialize(seed=False)
            bound.close()

            with self.assertRaisesRegex(RuntimeError, "does not match"):
                HotelStore(
                    database,
                    audit_secret="different-domain-audit-secret-00000002",
                )

    def test_persisted_audit_row_identity_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "row-bound.sqlite3"
            owner_ref = actor_reference(self.alice.user_id)
            store = HotelStore(database, audit_secret=AUDIT_SECRET)
            store.initialize(seed=False)
            store.append_session_audit_event(
                "session-row-bound",
                self.alice,
                signed_session_event(1, actor_ref=owner_ref),
            )
            store.connection.execute(
                """
                UPDATE session_audit_events
                SET session_id = 'session-moved-without-resigning'
                WHERE session_id = 'session-row-bound'
                """
            )
            store.close()

            reopened = HotelStore(database, audit_secret=AUDIT_SECRET)
            try:
                with self.assertRaisesRegex(
                    RuntimeError,
                    "audit head set is invalid",
                ):
                    reopened.initialize(seed=False)
            finally:
                reopened.close()

    def test_direct_row_materialization_rechecks_event_signature(self) -> None:
        owner_ref = actor_reference(self.alice.user_id)
        event = signed_session_event(1, actor_ref=owner_ref)
        self.store.append_session_audit_event(
            "session-direct-load",
            self.alice,
            event,
        )
        tampered = dict(event)
        tampered["details"] = {"index": 999}
        self.store.connection.execute(
            "UPDATE session_audit_events SET event_json = ? WHERE session_id = ?",
            (
                json.dumps(tampered, sort_keys=True, separators=(",", ":")),
                "session-direct-load",
            ),
        )
        rows = self.store.connection.execute(
            "SELECT session_id, sequence, actor_ref, occurred_at, event_json, "
            "row_hmac FROM session_audit_events WHERE session_id = ?",
            ("session-direct-load",),
        ).fetchall()

        with self.assertRaisesRegex(RuntimeError, "signature is invalid"):
            self.store._persisted_audit_events_from_rows(rows)

    def test_append_rejects_runtime_row_authentication_tampering(self) -> None:
        owner_ref = actor_reference(self.alice.user_id)
        first = signed_session_event(1, actor_ref=owner_ref)
        self.store.append_session_audit_event(
            "session-runtime-tamper",
            self.alice,
            first,
        )
        self.store.connection.execute(
            "UPDATE session_audit_events SET row_hmac = ? WHERE session_id = ?",
            ("0" * 64, "session-runtime-tamper"),
        )
        second = signed_session_event(
            2,
            actor_ref=owner_ref,
            previous_hash=str(first["event_hash"]),
        )

        with self.assertRaisesRegex(RuntimeError, "row authentication is invalid"):
            self.store.append_session_audit_event(
                "session-runtime-tamper",
                self.alice,
                second,
            )
        count = self.store.connection.execute(
            "SELECT COUNT(*) FROM session_audit_events WHERE session_id = ?",
            ("session-runtime-tamper",),
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_head_catalog_detects_tail_and_complete_chain_deletion(self) -> None:
        owner_ref = actor_reference(self.alice.user_id)
        for delete_head, expected_error in (
            (False, "audit head set is invalid"),
            (True, "catalog authentication is invalid"),
        ):
            with (
                self.subTest(delete_head=delete_head),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                database = Path(temporary_directory) / "truncated.sqlite3"
                store = HotelStore(database, audit_secret=AUDIT_SECRET)
                store.initialize(seed=False)
                store.append_session_audit_event(
                    "session-truncated",
                    self.alice,
                    signed_session_event(1, actor_ref=owner_ref),
                )
                store.connection.execute(
                    "DELETE FROM session_audit_events WHERE session_id = ?",
                    ("session-truncated",),
                )
                if delete_head:
                    store.connection.execute(
                        "DELETE FROM session_audit_heads WHERE session_id = ?",
                        ("session-truncated",),
                    )
                try:
                    with self.assertRaisesRegex(RuntimeError, expected_error):
                        store.list_session_audit_events(
                            "session-truncated",
                            self.alice,
                        )
                finally:
                    store.close()

    def test_persisted_audit_tail_and_whole_chain_deletion_are_detected(self) -> None:
        for label, delete_sql, expected_error in (
            (
                "tail",
                "DELETE FROM session_audit_events WHERE sequence = 2",
                "head does not match event history",
            ),
            (
                "whole-chain",
                "DELETE FROM session_audit_events",
                "head set is invalid",
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                database = Path(directory) / f"audit-delete-{label}.sqlite3"
                owner_ref = actor_reference(self.alice.user_id)
                store = HotelStore(database, audit_secret=AUDIT_SECRET)
                store.initialize(seed=False)
                first = signed_session_event(1, actor_ref=owner_ref)
                store.append_session_audit_event(
                    "session-delete-proof",
                    self.alice,
                    first,
                )
                store.append_session_audit_event(
                    "session-delete-proof",
                    self.alice,
                    signed_session_event(
                        2,
                        actor_ref=owner_ref,
                        previous_hash=str(first["event_hash"]),
                    ),
                )
                store.connection.execute(delete_sql)
                store.close()

                reopened = HotelStore(database, audit_secret=AUDIT_SECRET)
                try:
                    with self.assertRaisesRegex(RuntimeError, expected_error):
                        reopened.initialize(seed=False)
                finally:
                    reopened.close()

    def test_direct_audit_load_revalidates_event_payload_hmac(self) -> None:
        owner_ref = actor_reference(self.alice.user_id)
        self.store.append_session_audit_event(
            "session-live-payload-tamper",
            self.alice,
            signed_session_event(1, actor_ref=owner_ref),
        )
        row = self.store.connection.execute(
            "SELECT event_json FROM session_audit_events "
            "WHERE session_id = 'session-live-payload-tamper'"
        ).fetchone()
        payload = json.loads(row["event_json"])
        payload["details"]["index"] = 999
        self.store.connection.execute(
            """
            UPDATE session_audit_events SET event_json = ?
            WHERE session_id = 'session-live-payload-tamper'
            """,
            (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
        )

        with self.assertRaisesRegex(RuntimeError, "signature is invalid"):
            self.store.list_session_audit_events(
                "session-live-payload-tamper",
                self.alice,
            )

    def test_runtime_tampering_blocks_a_later_audit_append(self) -> None:
        owner_ref = actor_reference(self.alice.user_id)
        first = signed_session_event(1, actor_ref=owner_ref)
        self.store.append_session_audit_event(
            "session-live-append-tamper",
            self.alice,
            first,
        )
        row = self.store.connection.execute(
            "SELECT event_json FROM session_audit_events "
            "WHERE session_id = 'session-live-append-tamper'"
        ).fetchone()
        payload = json.loads(row["event_json"])
        payload["outcome"] = "tampered"
        self.store.connection.execute(
            """
            UPDATE session_audit_events SET event_json = ?
            WHERE session_id = 'session-live-append-tamper'
            """,
            (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
        )

        with self.assertRaisesRegex(RuntimeError, "signature is invalid"):
            self.store.append_session_audit_event(
                "session-live-append-tamper",
                self.alice,
                signed_session_event(
                    2,
                    actor_ref=owner_ref,
                    previous_hash=str(first["event_hash"]),
                ),
            )
        self.assertEqual(
            self.store.connection.execute(
                "SELECT COUNT(*) FROM session_audit_events "
                "WHERE session_id = 'session-live-append-tamper'"
            ).fetchone()[0],
            1,
        )

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
        self.assertEqual(
            schemas["hotel.list_service_tickets"]["effect"],
            ToolEffect.READ.value,
        )
        self.assertTrue(
            schemas["hotel.update_service_ticket"]["requires_confirmation"]
        )
        self.assertEqual(
            schemas["hotel.update_service_ticket"]["parameters"]["anyOf"],
            [{"required": ["status"]}, {"required": ["description"]}],
        )
        self.assertEqual(
            schemas["journey.build_stay_brief"]["effect"],
            ToolEffect.READ.value,
        )

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

        with self.assertRaisesRegex(
            PermissionDenied,
            "authoritative preview terms changed",
        ):
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

    def test_confirmation_can_be_invalidated_without_token_oracle(self) -> None:
        request = HoldBookingInput("standard", "2030-07-10", "2030-07-12", 1)
        with self.assertRaises(ConfirmationRequired) as challenge:
            self.registry.invoke(
                "hotel.hold_booking",
                self.alice,
                request,
                idempotency_key="invalidate-confirmation",
            )
        token = challenge.exception.token
        self.assertFalse(self.store.invalidate_confirmation(self.bob, token))
        self.assertFalse(
            self.store.invalidate_confirmation(self.alice, "unknown-token")
        )
        self.assertTrue(self.store.invalidate_confirmation(self.alice, token))
        self.assertFalse(self.store.invalidate_confirmation(self.alice, token))
        with self.assertRaises(PermissionDenied):
            self.registry.invoke(
                "hotel.hold_booking",
                self.alice,
                request,
                idempotency_key="invalidate-confirmation",
                confirmation_token=token,
            )

    def test_journey_snapshot_and_session_audit_persist_with_owner_binding(self) -> None:
        owner_ref = actor_reference(self.alice.user_id)
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "journey.sqlite3"
            first_store = HotelStore(database, audit_secret=AUDIT_SECRET)
            first_store.initialize(seed=False)
            snapshot = first_store.save_journey_snapshot(
                "session-persisted",
                owner_ref,
                {"active_booking_id": "RSV-LOCAL", "next_action": "review"},
                expected_version=0,
            )
            self.assertEqual(snapshot.version, 1)
            first_payload = signed_session_event(1, actor_ref=owner_ref)
            event = first_store.append_session_audit_event(
                "session-persisted",
                self.alice,
                first_payload,
            )
            self.assertEqual(event.sequence, 1)
            second_payload = signed_session_event(
                2,
                actor_ref=actor_reference(self.bob.user_id),
                previous_hash=str(first_payload["event_hash"]),
                action="session.access",
            )
            denied = first_store.append_session_audit_event(
                "session-persisted",
                self.bob,
                second_payload,
                session_owner_ref=owner_ref,
            )
            self.assertEqual(denied.sequence, 2)
            with self.assertRaises(PermissionDenied):
                first_store.append_session_audit_event(
                    "unowned-session",
                    self.bob,
                    signed_session_event(
                        3,
                        actor_ref=actor_reference(self.bob.user_id),
                        action="session.access",
                    ),
                    session_owner_ref=owner_ref,
                )
            first_store.close()

            reopened = HotelStore(database, audit_secret=AUDIT_SECRET)
            try:
                reopened.initialize(seed=False)
                loaded = reopened.load_journey_snapshot(
                    "session-persisted",
                    owner_ref,
                )
                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertEqual(loaded.payload["active_booking_id"], "RSV-LOCAL")
                with self.assertRaises(ConflictError):
                    reopened.save_journey_snapshot(
                        "session-persisted",
                        owner_ref,
                        {"active_booking_id": "RSV-OTHER"},
                        expected_version=0,
                    )
                with self.assertRaises(PermissionDenied):
                    reopened.load_journey_snapshot(
                        "session-persisted",
                        actor_reference(self.bob.user_id),
                    )
                self.assertEqual(
                    reopened.list_session_audit_events(
                        "session-persisted",
                        self.alice,
                    )[0].event["action"],
                    "journey.saved",
                )
                with self.assertRaises(PermissionDenied):
                    reopened.list_session_audit_events(
                        "session-persisted",
                        self.bob,
                    )
                self.assertEqual(
                    len(
                        reopened.list_session_audit_events(
                            "session-persisted",
                            self.staff,
                        )
                    ),
                    2,
                )
                state_row = reopened.connection.execute(
                    "SELECT state_hmac FROM journey_state WHERE session_id = ?",
                    ("session-persisted",),
                ).fetchone()
                self.assertRegex(state_row["state_hmac"], r"^[0-9a-f]{64}$")
                reopened.connection.execute(
                    "UPDATE journey_state SET state_json = '{}' WHERE session_id = ?",
                    ("session-persisted",),
                )
                with self.assertRaisesRegex(RuntimeError, "authentication is invalid"):
                    reopened.load_journey_snapshot(
                        "session-persisted",
                        owner_ref,
                    )
            finally:
                reopened.close()

    def test_audit_minimization_recursively_removes_secret_handles(self) -> None:
        secret = "secret-confirmation-capability"
        private_assignment = "private-key-assignment-value"
        ssh_assignment = "ssh-key-assignment-value"
        minimized = minimize_audit_details(
            {
                "safe_count": 2,
                "confirmation_token": secret,
                "private_key": secret,
                "ssh-key": secret,
                "safe_message": (
                    f"private_key={private_assignment} ssh_key={ssh_assignment}"
                ),
                "nested": {
                    "identity-token-hash": secret,
                    "token_status": "expired",
                    "prompt_tokens": 42,
                },
            }
        )
        serialized = json.dumps(minimized, ensure_ascii=False)

        self.assertNotIn(secret, serialized)
        self.assertNotIn(private_assignment, serialized)
        self.assertNotIn(ssh_assignment, serialized)
        self.assertIn("[REDACTED]", minimized["safe_message"])
        self.assertEqual(minimized["safe_count"], 2)
        self.assertEqual(minimized["nested"]["prompt_tokens"], 42)

    def test_owner_isolation_and_staff_override(self) -> None:
        held = self.hold_for_alice()
        booking_id = held.booking.booking_id

        bob_bookings = self.registry.invoke(
            "hotel.my_bookings", self.bob, MyBookingsInput()
        )
        self.assertEqual(bob_bookings.bookings, ())
        self.assertIsNotNone(bob_bookings.scope_attestation)
        self.assertTrue(bob_bookings.scope_attestation.scope_verified)
        self.assertEqual(
            bob_bookings.scope_attestation.owner_scoped_result_count,
            0,
        )
        self.assertEqual(bob_bookings.scope_attestation.cross_user_result_count, 0)

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
        stale_request = CreateServiceTicketInput(
            held.booking.booking_id,
            "accessibility",
            "Please also arrange a separate accessibility check.",
        )
        with self.assertRaises(ConfirmationRequired) as stale_challenge:
            self.registry.invoke(
                "hotel.create_service_ticket",
                self.alice,
                stale_request,
                idempotency_key="ticket-stale-scope",
            )
        ticket = self.invoke_confirmed(
            "hotel.create_service_ticket", self.alice, request, "ticket-1"
        )
        self.assertEqual(ticket.status, "open")
        with self.assertRaisesRegex(
            PermissionDenied,
            "authoritative preview terms changed",
        ):
            self.registry.invoke(
                "hotel.create_service_ticket",
                self.alice,
                stale_request,
                idempotency_key="ticket-stale-scope",
                confirmation_token=stale_challenge.exception.token,
            )

        with self.assertRaises(PermissionDenied):
            self.registry.invoke(
                "hotel.create_service_ticket",
                self.bob,
                request,
                idempotency_key="ticket-bob",
            )

    def test_service_ticket_list_and_confirmed_update_are_owner_scoped(self) -> None:
        held = self.hold_for_alice(key="ticket-list-hold")
        created = self.invoke_confirmed(
            "hotel.create_service_ticket",
            self.alice,
            CreateServiceTicketInput(
                held.booking.booking_id,
                "transport",
                "Airport pickup for two guests.",
            ),
            "ticket-list-create",
        )
        self.assertIsNotNone(created.updated_at)
        self.assertEqual(len(created.state_sha256), 64)

        alice_tickets = self.registry.invoke(
            "hotel.list_service_tickets",
            self.alice,
            ListServiceTicketsInput(booking_id=held.booking.booking_id),
        )
        self.assertEqual(
            [item.ticket_id for item in alice_tickets.tickets],
            [created.ticket_id],
        )
        self.assertIsNotNone(alice_tickets.scope_attestation)
        self.assertEqual(
            alice_tickets.scope_attestation.owner_scoped_result_count,
            1,
        )
        self.assertEqual(alice_tickets.scope_attestation.cross_user_result_count, 0)
        self.assertEqual(
            self.registry.invoke(
                "hotel.list_service_tickets",
                self.bob,
                ListServiceTicketsInput(),
            ).tickets,
            (),
        )
        self.assertEqual(
            self.registry.invoke(
                "hotel.list_service_tickets",
                self.staff,
                ListServiceTicketsInput(),
            ).tickets,
            (),
        )
        with self.assertRaises(PermissionDenied):
            self.registry.invoke(
                "hotel.update_service_ticket",
                self.bob,
                UpdateServiceTicketInput(created.ticket_id, status="resolved"),
                idempotency_key="ticket-update-bob",
            )

        stale_update = UpdateServiceTicketInput(
            created.ticket_id,
            description="Pickup request with a child seat.",
        )
        with self.assertRaises(ConfirmationRequired) as stale_challenge:
            self.registry.invoke(
                "hotel.update_service_ticket",
                self.alice,
                stale_update,
                idempotency_key="ticket-update-stale",
            )
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE service_tickets
                SET description = ?, updated_at = ? WHERE ticket_id = ?
                """,
                (
                    "Another confirmed description.",
                    "2030-07-01T00:00:01+00:00",
                    created.ticket_id,
                ),
            )
        with self.assertRaisesRegex(
            PermissionDenied,
            "authoritative preview terms changed",
        ):
            self.registry.invoke(
                "hotel.update_service_ticket",
                self.alice,
                stale_update,
                idempotency_key="ticket-update-stale",
                confirmation_token=stale_challenge.exception.token,
            )

        update = UpdateServiceTicketInput(created.ticket_id, status="resolved")
        with self.assertRaises(ConfirmationRequired) as challenge:
            self.registry.invoke(
                "hotel.update_service_ticket",
                self.alice,
                update,
                idempotency_key="ticket-update-alice",
            )
        self.assertEqual(challenge.exception.preview["current_status"], "open")
        self.assertEqual(challenge.exception.preview["proposed_status"], "resolved")
        self.assertEqual(challenge.exception.preview["stay_price_delta_cents"], 0)
        self.assertEqual(
            challenge.exception.preview["external_service_price"],
            "not_quoted",
        )
        completed = self.registry.invoke(
            "hotel.update_service_ticket",
            self.alice,
            update,
            idempotency_key="ticket-update-alice",
            confirmation_token=challenge.exception.token,
        )
        self.assertEqual(completed.ticket.status, "resolved")
        self.assertEqual(len(completed.state_sha256), 64)
        self.assertEqual(
            self.registry.invoke(
                "hotel.list_service_tickets",
                self.alice,
                ListServiceTicketsInput(),
            ).tickets,
            (),
        )
        closed = self.registry.invoke(
            "hotel.list_service_tickets",
            self.alice,
            ListServiceTicketsInput(include_closed=True),
        )
        self.assertEqual(closed.tickets[0].status, "resolved")

    def test_stay_brief_is_owner_scoped_and_excludes_internal_fields(self) -> None:
        held = self.hold_for_alice(key="brief-hold")
        self.invoke_confirmed(
            "hotel.create_service_ticket",
            self.alice,
            CreateServiceTicketInput(
                held.booking.booking_id,
                "accessibility",
                "Private arrival detail that must not enter the brief.",
            ),
            "brief-ticket",
        )
        self.invoke_confirmed(
            "memory.set_consent",
            self.alice,
            SetMemoryConsentInput(True),
            "brief-consent",
        )
        self.invoke_confirmed(
            "memory.remember_preference",
            self.alice,
            RememberPreferenceInput("quiet_room", "high_floor"),
            "brief-preference",
        )

        brief = self.registry.invoke(
            "journey.build_stay_brief",
            self.alice,
            BuildStayBriefInput(held.booking.booking_id),
        )
        self.assertEqual(brief.booking.booking_id, held.booking.booking_id)
        self.assertEqual(
            brief.service_tickets[0].booking_id,
            held.booking.booking_id,
        )
        self.assertEqual(brief.service_tickets[0].category, "accessibility")
        self.assertEqual(len(brief.service_tickets[0].state_sha256), 64)
        self.assertTrue(brief.memory_enabled)
        self.assertEqual(brief.preferences, (("quiet_room", "high_floor"),))
        self.assertIsNotNone(brief.scope_attestation)
        self.assertEqual(brief.scope_attestation.owner_scoped_result_count, 3)
        self.assertEqual(brief.scope_attestation.cross_user_result_count, 0)
        serialized = json.dumps(brief.to_dict(), ensure_ascii=False)
        self.assertNotIn("Private arrival detail", serialized)
        for forbidden in (
            "confirmation_token",
            "identity_token",
            "audit_id",
            "source_path",
        ):
            self.assertNotIn(forbidden, serialized)
        with self.assertRaises(PermissionDenied):
            self.registry.invoke(
                "journey.build_stay_brief",
                self.bob,
                BuildStayBriefInput(held.booking.booking_id),
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
        with self.assertRaisesRegex(ValidationError, "must not be stored"):
            self.registry.invoke(
                "memory.remember_preference",
                self.alice,
                RememberPreferenceInput(
                    "language",
                    "Bearer AbCdEfGhIjKlMnOpQrStUvWxYz012345",
                ),
                idempotency_key="sensitive-bearer-memory",
            )
        with self.assertRaisesRegex(ValidationError, "tokens must not be stored"):
            self.registry.invoke(
                "hotel.create_service_ticket",
                self.alice,
                CreateServiceTicketInput(
                    held.booking.booking_id,
                    "other",
                    (
                        "Store eyJzdWIiOiJndWVzdC1hbGljZSJ9."
                        "MDEyMzQ1Njc4OUFCQ0RFRkdISUpLTE1OT1A"
                    ),
                ),
                idempotency_key="sensitive-signed-ticket",
            )
        with self.assertRaisesRegex(ValidationError, "must not be stored"):
            self.registry.invoke(
                "hotel.create_service_ticket",
                self.alice,
                CreateServiceTicketInput(
                    held.booking.booking_id,
                    "other",
                    "请在工单中保存 SSH 私钥凭据 RSTEST-NOT-A-REAL-KEY-002",
                ),
                idempotency_key="sensitive-chinese-private-key-ticket",
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
        self.assertIsNotNone(remembered.scope_attestation)
        self.assertEqual(
            remembered.scope_attestation.owner_scoped_result_count,
            1,
        )

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

    def test_private_state_bindings_are_hidden_and_reject_memory_drift(self) -> None:
        held = self.hold_for_alice(key="private-binding-hold")
        with self.assertRaises(ConfirmationRequired) as modify_challenge:
            self.registry.invoke(
                "hotel.modify_booking",
                self.alice,
                ModifyBookingInput(held.booking.booking_id, guests=1),
                idempotency_key="private-binding-modify",
            )
        self.assertNotIn(
            "_binding_",
            json.dumps(modify_challenge.exception.preview, sort_keys=True),
        )

        consent_request = SetMemoryConsentInput(True)
        with self.assertRaises(ConfirmationRequired) as consent_challenge:
            self.registry.invoke(
                "memory.set_consent",
                self.alice,
                consent_request,
                idempotency_key="stale-consent-preview",
            )
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO memory_consent(user_id, enabled, updated_at)
                VALUES (?, 1, ?)
                """,
                (self.alice.user_id, "2030-07-01T00:00:00+00:00"),
            )
        with self.assertRaisesRegex(
            PermissionDenied,
            "authoritative preview terms changed",
        ):
            self.registry.invoke(
                "memory.set_consent",
                self.alice,
                consent_request,
                idempotency_key="stale-consent-preview",
                confirmation_token=consent_challenge.exception.token,
            )

        preference_request = RememberPreferenceInput("quiet_room", "high_floor")
        with self.assertRaises(ConfirmationRequired) as preference_challenge:
            self.registry.invoke(
                "memory.remember_preference",
                self.alice,
                preference_request,
                idempotency_key="stale-preference-preview",
            )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE memory_consent SET updated_at = ? WHERE user_id = ?",
                ("2030-07-01T00:00:01+00:00", self.alice.user_id),
            )
        with self.assertRaisesRegex(
            PermissionDenied,
            "authoritative preview terms changed",
        ):
            self.registry.invoke(
                "memory.remember_preference",
                self.alice,
                preference_request,
                idempotency_key="stale-preference-preview",
                confirmation_token=preference_challenge.exception.token,
            )

        self.invoke_confirmed(
            "memory.remember_preference",
            self.alice,
            preference_request,
            "fresh-preference-preview",
        )
        delete_request = DeletePreferenceInput("quiet_room")
        with self.assertRaises(ConfirmationRequired) as delete_challenge:
            self.registry.invoke(
                "memory.delete_preference",
                self.alice,
                delete_request,
                idempotency_key="stale-delete-preview",
            )
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE user_preferences
                SET preference_value = ?, updated_at = ?
                WHERE user_id = ? AND preference_key = ?
                """,
                (
                    "courtyard_side",
                    "2030-07-01T00:00:02+00:00",
                    self.alice.user_id,
                    "quiet_room",
                ),
            )
        with self.assertRaisesRegex(
            PermissionDenied,
            "authoritative preview terms changed",
        ):
            self.registry.invoke(
                "memory.delete_preference",
                self.alice,
                delete_request,
                idempotency_key="stale-delete-preview",
                confirmation_token=delete_challenge.exception.token,
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
