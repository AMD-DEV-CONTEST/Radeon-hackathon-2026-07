from __future__ import annotations

import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from alphanoah_a1.exceptions import ProviderTransportError  # noqa: E402
from alphanoah_a1.golden_path import (  # noqa: E402
    RestaurantAirconFakeAnalysisProvider,
    RestaurantAirconGoldenPath,
    build_restaurant_aircon_golden_path,
)
from alphanoah_a1.models import (  # noqa: E402
    AuditRecord,
    Event,
    EventStatus,
    HumanReviewOutcome,
    PostReviewResult,
    utc_now,
)
from alphanoah_a1.responsibility import (  # noqa: E402
    ResponsibilityDirectory,
)
from alphanoah_a1.runtime_projection import (  # noqa: E402
    RuntimeProjectionWebAdapter,
)
from alphanoah_a1.web_adapter import RestaurantAirconWebAdapter  # noqa: E402
from alphanoah_a1.web_api import (  # noqa: E402
    LOCAL_HOST,
    WebAdapterHTTPServer,
    create_server,
)

SCHEMA_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "frontend"
    / "RUNTIME_PROJECTION_WORKSPACE_V1.schema.json"
)
RESPONSIBILITY_FILE = (
    REPOSITORY_ROOT
    / "examples"
    / "demo_activation_responsibility.json"
)

WORKSPACE_KEYS = {
    "version",
    "events",
    "active_event",
    "pulse",
    "employees",
}
EVENT_KEYS = {
    "id",
    "type",
    "status",
    "timestamp",
    "severity",
    "location",
    "asset_id",
    "description",
    "responsibility",
}
RESPONSIBILITY_KEYS = {"id", "name"}
EMPLOYEE_KEYS = {
    "id",
    "name",
    "status",
    "current_event_id",
    "responsibility",
    "skills",
}
SKILL_KEYS = {"name"}
PULSE_KEYS = {"level", "title", "event_id"}
TERMINAL_EVENT_STATUSES = {
    EventStatus.CLOSED.value,
    EventStatus.REJECTED.value,
    EventStatus.FAILED.value,
    EventStatus.CANCELLED.value,
}
FORBIDDEN_PROJECTION_KEYS = {
    "prompt",
    "system instruction",
    "system_instruction",
    "system_instructions",
    "analysis_instructions",
    "trace_id",
    "request_id",
    "actor",
    "local file path",
    "local_file_path",
    "database path",
    "database_path",
    "raw audit details",
    "raw_audit_details",
    "model internal response",
    "model_internal_response",
}


class FailingProjectionProvider(RestaurantAirconFakeAnalysisProvider):
    provider_id = "fake:runtime-projection-unavailable"

    def analyze_with_contexts(self, event, skill_context, knowledge_context):
        self.calls += 1
        raise ProviderTransportError(
            "Synthetic projection-test transport failure.",
            code="connection_error",
        )


@contextmanager
def serving(
    server: WebAdapterHTTPServer,
) -> Iterator[int]:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def projection_server(
    application: RestaurantAirconGoldenPath,
    directory: ResponsibilityDirectory,
) -> WebAdapterHTTPServer:
    return WebAdapterHTTPServer(
        (LOCAL_HOST, 0),
        RestaurantAirconWebAdapter(application),
        projection_adapter=RuntimeProjectionWebAdapter(
            application,
            responsibility_directory=directory,
        ),
    )


def request(
    port: int,
    path: str,
) -> tuple[int, dict[str, str], object]:
    connection = http.client.HTTPConnection(
        LOCAL_HOST,
        port,
        timeout=3,
    )
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        encoded = response.read()
        headers = {
            key.lower(): value for key, value in response.getheaders()
        }
        return response.status, headers, json.loads(encoded)
    finally:
        connection.close()


def overwrite_notification_title(
    database: Path,
    notification_id: str,
    title: str,
) -> None:
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            row = connection.execute(
                """
                SELECT payload FROM notifications
                WHERE notification_id = ?
                """,
                (notification_id,),
            ).fetchone()
            if row is None:
                raise AssertionError(
                    "notification fixture was not persisted"
                )
            payload = json.loads(row[0])
            payload["title"] = title
            connection.execute(
                """
                UPDATE notifications
                SET payload = ?
                WHERE notification_id = ?
                """,
                (
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    notification_id,
                ),
            )


class RuntimeProjectionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = (
            Path(self.temporary_directory.name) / "projection.sqlite3"
        )
        self.application = build_restaurant_aircon_golden_path(
            self.database
        )
        self.directory = ResponsibilityDirectory.from_file(
            RESPONSIBILITY_FILE
        )
        self.projection = RuntimeProjectionWebAdapter(
            self.application,
            responsibility_directory=self.directory,
        )

    def create_event(self):
        return self.application.submit_incident()

    def analyze_and_notify(self):
        event = self.create_event()
        analysis = self.application.analyze(event.event_id)
        self.application.runtime.create_notification_for_decision(
            analysis.decision_id,
            directory=self.directory,
            actor="agent:runtime-projection-test",
        )
        return event, analysis

    def close_event(
        self,
        *,
        create_notification: bool = False,
    ):
        event = self.create_event()
        analysis = self.application.analyze(event.event_id)
        if create_notification:
            self.application.runtime.create_notification_for_decision(
                analysis.decision_id,
                directory=self.directory,
                actor="agent:runtime-projection-test",
            )
        self.application.submit_human_review(
            analysis.decision_id,
            outcome=HumanReviewOutcome.APPROVED,
            comment="Explicit synthetic projection-test approval.",
        )
        task = self.application.create_approved_task(
            analysis.decision_id
        )
        self.application.start_task(task.task_id)
        self.application.submit_synthetic_evidence(task.task_id)
        self.application.begin_evidence_review(task.task_id)
        self.application.review_evidence(
            task.task_id,
            result=PostReviewResult.PASSED,
            comment="Explicit synthetic projection-test acceptance.",
        )
        return event

    def assert_event_contract(self, value: object) -> None:
        self.assertIsInstance(value, dict)
        event = value
        assert isinstance(event, dict)
        self.assertEqual(set(event), EVENT_KEYS)
        self.assertRegex(event["id"], r"^event_[a-f0-9]{32}$")
        for key in ("type", "status", "timestamp", "severity"):
            self.assertIsInstance(event[key], str)
            self.assertTrue(event[key])
        responsibility = event["responsibility"]
        if responsibility is not None:
            self.assertIsInstance(responsibility, dict)
            self.assertEqual(set(responsibility), RESPONSIBILITY_KEYS)
            self.assertTrue(responsibility["id"])
            self.assertTrue(responsibility["name"])

    def assert_employee_contract(self, value: object) -> None:
        self.assertIsInstance(value, dict)
        employee = value
        assert isinstance(employee, dict)
        self.assertEqual(set(employee), EMPLOYEE_KEYS)
        self.assertTrue(employee["id"])
        self.assertTrue(employee["name"])
        self.assertIn(employee["status"], {"working", "unknown"})
        if employee["current_event_id"] is not None:
            self.assertRegex(
                employee["current_event_id"],
                r"^event_[a-f0-9]{32}$",
            )
        self.assertIsInstance(employee["responsibility"], str)
        self.assertTrue(employee["responsibility"])
        self.assertIsInstance(employee["skills"], list)
        for skill in employee["skills"]:
            self.assertIsInstance(skill, dict)
            self.assertEqual(set(skill), SKILL_KEYS)
            self.assertTrue(skill["name"])

    def assert_pulse_contract(self, value: object) -> None:
        self.assertIsInstance(value, dict)
        pulse = value
        assert isinstance(pulse, dict)
        self.assertEqual(set(pulse), PULSE_KEYS)
        self.assertIn(pulse["level"], {"attention", "critical"})
        self.assertTrue(pulse["title"])
        self.assertRegex(pulse["event_id"], r"^event_[a-f0-9]{32}$")

    def assert_workspace_contract(self, value: object) -> None:
        self.assertIsInstance(value, dict)
        workspace = value
        assert isinstance(workspace, dict)
        self.assertEqual(set(workspace), WORKSPACE_KEYS)
        self.assertEqual(workspace["version"], "workspace-v1")
        self.assertIsInstance(workspace["events"], list)
        for event in workspace["events"]:
            self.assert_event_contract(event)
        active_event = workspace["active_event"]
        if active_event is not None:
            self.assert_event_contract(active_event)
            self.assertNotIn(
                active_event["status"],
                TERMINAL_EVENT_STATUSES,
            )
        pulse = workspace["pulse"]
        if pulse is not None:
            self.assert_pulse_contract(pulse)
        self.assertIsInstance(workspace["employees"], list)
        for employee in workspace["employees"]:
            self.assert_employee_contract(employee)

    def test_00_schema_is_draft_2020_12_and_exact(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        self.assertEqual(
            schema["$schema"],
            "https://json-schema.org/draft/2020-12/schema",
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            set(schema["required"]),
            WORKSPACE_KEYS,
        )
        self.assertEqual(
            schema["properties"]["version"]["const"],
            "workspace-v1",
        )
        self.assertEqual(
            schema["properties"]["events"]["maxItems"],
            100,
        )
        for definition in (
            "responsibility",
            "event",
            "skill",
            "employee",
            "pulse",
        ):
            self.assertFalse(
                schema["$defs"][definition]["additionalProperties"]
            )
        self.assertEqual(
            set(schema["$defs"]["event"]["required"]),
            EVENT_KEYS,
        )
        self.assertEqual(
            set(
                schema["$defs"]["event"]["properties"]["severity"][
                    "enum"
                ]
            ),
            {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"},
        )
        self.assertEqual(
            set(schema["$defs"]["employee"]["required"]),
            EMPLOYEE_KEYS,
        )
        self.assertEqual(
            set(schema["$defs"]["pulse"]["required"]),
            PULSE_KEYS,
        )

    def test_01_empty_projection_has_no_synthetic_state(self) -> None:
        workspace = self.projection.get_workspace()

        self.assert_workspace_contract(workspace)
        self.assertEqual(
            workspace,
            {
                "version": "workspace-v1",
                "events": [],
                "active_event": None,
                "pulse": None,
                "employees": [],
            },
        )
        self.assertEqual(self.projection.get_events(), [])
        self.assertEqual(self.projection.get_digital_employees(), [])
        self.assertIsNone(self.projection.get_pulse())

    def test_02_workspace_projects_a_real_event(self) -> None:
        created = self.create_event()

        workspace = self.projection.get_workspace()

        self.assert_workspace_contract(workspace)
        self.assertEqual(len(workspace["events"]), 1)
        projected = workspace["events"][0]
        self.assertEqual(projected["id"], created.event_id)
        self.assertEqual(projected["type"], created.event_type)
        self.assertEqual(projected["status"], EventStatus.NEW.value)
        self.assertEqual(projected["timestamp"], created.timestamp)
        self.assertEqual(projected["severity"], created.severity)
        self.assertEqual(projected["location"], created.location)
        self.assertEqual(projected["asset_id"], created.asset_id)
        self.assertEqual(projected["description"], created.description)
        self.assertEqual(
            projected["responsibility"],
            {
                "id": "maintenance_001",
                "name": "Equipment Maintenance",
            },
        )
        self.assertEqual(workspace["active_event"], projected)
        self.assertIsNone(workspace["pulse"])
        self.assertEqual(len(workspace["employees"]), 1)
        employee = workspace["employees"][0]
        self.assertEqual(employee["id"], "maintenance_001")
        self.assertEqual(employee["status"], "working")
        self.assertEqual(employee["current_event_id"], created.event_id)
        self.assertEqual(employee["skills"], [])

    def test_03_failed_event_remains_readable_and_is_not_active(self) -> None:
        application = build_restaurant_aircon_golden_path(
            Path(self.temporary_directory.name) / "failed.sqlite3",
            raw_provider=FailingProjectionProvider(),
        )
        projection = RuntimeProjectionWebAdapter(
            application,
            responsibility_directory=self.directory,
        )
        event = application.submit_incident()
        with self.assertRaises(ProviderTransportError):
            application.analyze(event.event_id)

        workspace = projection.get_workspace()

        self.assert_workspace_contract(workspace)
        self.assertEqual(workspace["events"][0]["id"], event.event_id)
        self.assertEqual(
            workspace["events"][0]["status"],
            EventStatus.FAILED.value,
        )
        self.assertIsNone(workspace["active_event"])
        self.assertIsNone(workspace["pulse"])
        self.assertEqual(
            workspace["employees"][0]["status"],
            "unknown",
        )
        self.assertIsNone(
            workspace["employees"][0]["current_event_id"]
        )

    def test_04_closed_event_remains_readable_and_is_not_active(self) -> None:
        event = self.close_event()

        workspace = self.projection.get_workspace()

        self.assert_workspace_contract(workspace)
        self.assertEqual(workspace["events"][0]["id"], event.event_id)
        self.assertEqual(
            workspace["events"][0]["status"],
            EventStatus.CLOSED.value,
        )
        self.assertIsNone(workspace["active_event"])
        employee = workspace["employees"][0]
        self.assertEqual(employee["status"], "unknown")
        self.assertIsNone(employee["current_event_id"])
        self.assertEqual(
            employee["skills"],
            [{"name": "restaurant-aircon-troubleshooting"}],
        )

    def test_05_active_event_skips_a_newer_terminal_event(self) -> None:
        active = self.create_event()
        closed = self.close_event()

        workspace = self.projection.get_workspace()

        self.assertEqual(workspace["events"][0]["id"], closed.event_id)
        self.assertEqual(
            workspace["events"][0]["status"],
            EventStatus.CLOSED.value,
        )
        self.assertEqual(
            workspace["active_event"]["id"],
            active.event_id,
        )
        self.assertEqual(
            workspace["active_event"]["status"],
            EventStatus.NEW.value,
        )

    def test_06_event_feed_refreshes_after_runtime_status_change(
        self,
    ) -> None:
        event = self.create_event()
        server = projection_server(self.application, self.directory)

        with serving(server) as port:
            first_status, first_headers, first = request(
                port,
                "/api/events",
            )
            self.application.analyze(event.event_id)
            second_status, second_headers, second = request(
                port,
                "/api/events",
            )

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertEqual(first[0]["id"], event.event_id)
        self.assertEqual(first[0]["status"], EventStatus.NEW.value)
        self.assertEqual(
            second[0]["status"],
            EventStatus.PENDING_HUMAN_REVIEW.value,
        )
        self.assertEqual(first_headers["cache-control"], "no-store")
        self.assertEqual(second_headers["cache-control"], "no-store")

    def test_07_event_feed_is_newest_updated_first(self) -> None:
        older_but_updated = self.create_event()
        newer = self.create_event()
        self.application.analyze(older_but_updated.event_id)

        events = self.projection.get_events()

        self.assertEqual(
            [event["id"] for event in events],
            [older_but_updated.event_id, newer.event_id],
        )

    def test_08_employee_projection_matches_responsibility_and_skill(
        self,
    ) -> None:
        event, _ = self.analyze_and_notify()

        employees = self.projection.get_digital_employees()

        self.assertEqual(len(employees), 1)
        self.assert_employee_contract(employees[0])
        self.assertEqual(
            employees[0],
            {
                "id": "maintenance_001",
                "name": "Equipment Maintenance",
                "status": "working",
                "current_event_id": event.event_id,
                "responsibility": "Equipment Maintenance",
                "skills": [
                    {"name": "restaurant-aircon-troubleshooting"},
                ],
            },
        )

    def test_09_unmatched_responsibility_does_not_create_employee(
        self,
    ) -> None:
        event = self.create_event()
        unmatched = RuntimeProjectionWebAdapter(
            self.application,
            responsibility_directory=ResponsibilityDirectory(),
        )

        events = unmatched.get_events()
        employees = unmatched.get_digital_employees()

        self.assertEqual(events[0]["id"], event.event_id)
        self.assertIsNone(events[0]["responsibility"])
        self.assertEqual(employees, [])

    def test_09a_event_feed_is_bounded_to_100_recent_events(
        self,
    ) -> None:
        created = [self.create_event() for _ in range(101)]

        events = self.projection.get_events()
        workspace = self.projection.get_workspace()

        projected_ids = {event["id"] for event in events}
        self.assertEqual(len(events), 100)
        self.assertEqual(len(workspace["events"]), 100)
        self.assertNotIn(created[0].event_id, projected_ids)
        self.assertIn(created[-1].event_id, projected_ids)

    def test_09b_unsupported_severity_fails_safe_to_unknown(
        self,
    ) -> None:
        event = self.create_event()
        persisted = self.application.runtime.store.get_event(
            event.event_id
        )
        persisted.severity = "URGENT"
        self.application.runtime.store.update_event(persisted)

        projected = self.projection.get_events()[0]

        self.assertEqual(projected["severity"], "UNKNOWN")

    def test_10_employee_with_only_terminal_work_is_unknown(
        self,
    ) -> None:
        event = self.close_event()

        employee = self.projection.get_digital_employees()[0]

        self.assertEqual(employee["status"], "unknown")
        self.assertIsNone(employee["current_event_id"])
        self.assertEqual(
            employee["skills"],
            [{"name": "restaurant-aircon-troubleshooting"}],
        )
        self.assertNotEqual(employee["current_event_id"], event.event_id)

    def test_11_pulse_is_null_without_notification(self) -> None:
        self.create_event()

        self.assertIsNone(self.projection.get_pulse())
        self.assertIsNone(self.projection.get_workspace()["pulse"])

    def test_12_pulse_projects_a_real_notification(self) -> None:
        event, _ = self.analyze_and_notify()

        pulse = self.projection.get_pulse()

        self.assert_pulse_contract(pulse)
        self.assertEqual(
            pulse,
            {
                "level": "attention",
                "title": (
                    "Industrial incident requires human review"
                ),
                "event_id": event.event_id,
            },
        )

    def test_13_critical_event_projects_critical_pulse(self) -> None:
        event, _ = self.analyze_and_notify()
        persisted = self.application.runtime.store.get_event(
            event.event_id
        )
        persisted.severity = "CRITICAL"
        self.application.runtime.store.update_event(persisted)

        pulse = self.projection.get_pulse()

        self.assertEqual(pulse["level"], "critical")
        self.assertEqual(pulse["event_id"], event.event_id)

    def test_14_terminal_event_suppresses_stale_notification(
        self,
    ) -> None:
        event = self.close_event(create_notification=True)
        notifications = (
            self.application.runtime.store.list_notifications(
                event.event_id
            )
        )

        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].status.value, "CREATED")
        self.assertIsNone(self.projection.get_pulse())
        self.assertIsNone(self.projection.get_workspace()["pulse"])

    def test_14a_pulse_prioritizes_critical_over_newer_attention(
        self,
    ) -> None:
        critical_event, _ = self.analyze_and_notify()
        persisted = self.application.runtime.store.get_event(
            critical_event.event_id
        )
        persisted.severity = "CRITICAL"
        self.application.runtime.store.update_event(persisted)
        attention_event, _ = self.analyze_and_notify()

        pulse = self.projection.get_pulse()

        self.assertEqual(pulse["level"], "critical")
        self.assertEqual(pulse["event_id"], critical_event.event_id)
        self.assertNotEqual(pulse["event_id"], attention_event.event_id)

    def test_15_workspace_reuses_each_standalone_subprojection(
        self,
    ) -> None:
        self.analyze_and_notify()

        workspace = self.projection.get_workspace()

        self.assertEqual(
            workspace["events"],
            self.projection.get_events(),
        )
        self.assertEqual(
            workspace["employees"],
            self.projection.get_digital_employees(),
        )
        self.assertEqual(
            workspace["pulse"],
            self.projection.get_pulse(),
        )

    def test_16_all_projection_gets_are_read_only(self) -> None:
        event, _ = self.analyze_and_notify()
        before = self.application.runtime.snapshot(event.event_id)
        server = projection_server(self.application, self.directory)

        with serving(server) as port:
            for path in (
                "/api/workspace",
                "/api/events",
                "/api/digital-employees",
                "/api/pulse",
            ):
                status, _, _ = request(port, path)
                self.assertEqual(status, 200)

        after = self.application.runtime.snapshot(event.event_id)
        self.assertEqual(after, before)

    def test_17_create_server_exposes_all_projection_gets_with_safe_headers(
        self,
    ) -> None:
        server = create_server(
            Path(self.temporary_directory.name) / "unused.sqlite3",
            port=0,
            application=self.application,
        )

        with serving(server) as port:
            responses = {
                path: request(port, path)
                for path in (
                    "/api/workspace",
                    "/api/events",
                    "/api/digital-employees",
                    "/api/pulse",
                )
            }

        for path, (status, headers, payload) in responses.items():
            with self.subTest(path=path):
                self.assertEqual(status, 200)
                self.assertEqual(
                    headers["content-type"],
                    "application/json; charset=utf-8",
                )
                self.assertEqual(headers["cache-control"], "no-store")
                self.assertEqual(
                    headers["x-content-type-options"],
                    "nosniff",
                )
                if path == "/api/workspace":
                    self.assert_workspace_contract(payload)
                elif path == "/api/events":
                    self.assertIsInstance(payload, list)
                elif path == "/api/digital-employees":
                    self.assertIsInstance(payload, list)
                else:
                    self.assertIsNone(payload)

    def test_18_forbidden_fields_and_malicious_values_do_not_leak(
        self,
    ) -> None:
        windows_path = "C:" + "\\Users\\private\\runtime.sqlite3"
        unix_path = "/redacted/runtime.sqlite3"
        prompt_canary = "synthetic-private-prompt-canary"
        actor_canary = "actor:synthetic-private-canary"
        trace_canary = "trace_synthetic_private_canary"
        request_canary = "request_synthetic_private_canary"
        model_canary = "synthetic-model-internal-response-canary"
        event = self.application.runtime.create_event(
            source="security_projection_probe",
            actor=actor_canary,
            raw_input_ref=windows_path,
            normalized_input={
                "prompt": prompt_canary,
                "local_file_path": unix_path,
            },
            trace_id=trace_canary,
            event_type="security_projection_probe",
            location="Synthetic-Security-Lab",
            asset_id="SECURITY-PROBE",
            reporter="synthetic:security-probe",
            description=prompt_canary,
            metadata={
                "request_id": request_canary,
                "database_path": str(self.database),
                "system_instruction": prompt_canary,
            },
        )
        self.application.runtime.store.record_audit(
            AuditRecord(
                audit_id=f"audit_{uuid4().hex}",
                actor=actor_canary,
                action="decision_created",
                object_type="Decision",
                object_id=f"decision_{uuid4().hex}",
                previous_state=None,
                new_state="PROPOSED",
                timestamp=utc_now(),
                trace_id=event.trace_id,
                details={
                    "prompt": prompt_canary,
                    "analysis_instructions": prompt_canary,
                    "raw_audit_details": windows_path,
                    "model_internal_response": model_canary,
                    "model_metadata": {
                        "skill_id": windows_path,
                        "skill_version": unix_path,
                    },
                },
            )
        )
        malicious_directory = ResponsibilityDirectory(
            event_type={
                "security_projection_probe": {
                    "owner_id": "security-probe-owner",
                    "owner_name": windows_path,
                }
            }
        )
        server = projection_server(
            self.application,
            malicious_directory,
        )

        with serving(server) as port:
            payloads = [
                request(port, path)[2]
                for path in (
                    "/api/workspace",
                    "/api/events",
                    "/api/digital-employees",
                    "/api/pulse",
                )
            ]

        public_strings = [
            value
            for payload in payloads
            for value in recursive_strings(payload)
        ]
        for forbidden_value in (
            windows_path,
            unix_path,
            prompt_canary,
            actor_canary,
            trace_canary,
            request_canary,
            model_canary,
            str(self.database),
            str(REPOSITORY_ROOT),
        ):
            with self.subTest(forbidden_value=forbidden_value):
                self.assertFalse(
                    any(
                        forbidden_value in public_value
                        for public_value in public_strings
                    )
                )
        keys = {
            key.casefold()
            for payload in payloads
            for key in recursive_keys(payload)
        }
        self.assertTrue(FORBIDDEN_PROJECTION_KEYS.isdisjoint(keys))
        projected_security_event = next(
            item
            for item in payloads[1]
            if item["id"] == event.event_id
        )
        self.assertIsNone(projected_security_event["responsibility"])
        self.assertEqual(payloads[2], [])

    def test_19_pulse_considers_notifications_older_than_feed_window(
        self,
    ) -> None:
        attention_event, _ = self.analyze_and_notify()
        persisted = self.application.runtime.store.get_event(
            attention_event.event_id
        )
        persisted.severity = "CRITICAL"
        self.application.runtime.store.update_event(persisted)
        newer_events = [self.create_event() for _ in range(100)]

        events = self.projection.get_events()
        pulse = self.projection.get_pulse()
        workspace = self.projection.get_workspace()

        self.assertEqual(len(events), 100)
        self.assertNotIn(
            attention_event.event_id,
            {event["id"] for event in events},
        )
        self.assertIn(
            newer_events[-1].event_id,
            {event["id"] for event in events},
        )
        self.assertEqual(
            pulse,
            {
                "level": "critical",
                "title": (
                    "Industrial incident requires human review"
                ),
                "event_id": attention_event.event_id,
            },
        )
        self.assertEqual(workspace["pulse"], pulse)

    def test_20_full_derivation_preserves_old_active_event_and_employee(
        self,
    ) -> None:
        active = self.create_event()
        for index in range(100):
            terminal = self.application.runtime.create_event(
                source="projection_window_probe",
                actor="agent:runtime-projection-test",
                event_type="projection_window_probe",
                location=f"Unmatched-Location-{index}",
                asset_id=f"UNMATCHED-ASSET-{index}",
                reporter="synthetic:runtime-projection-test",
                description="Synthetic terminal projection window probe.",
            )
            terminal.status = EventStatus.CLOSED
            self.application.runtime.store.update_event(terminal)

        workspace = self.projection.get_workspace()
        employees = self.projection.get_digital_employees()

        self.assert_workspace_contract(workspace)
        self.assertEqual(len(workspace["events"]), 100)
        self.assertNotIn(
            active.event_id,
            {event["id"] for event in workspace["events"]},
        )
        self.assertEqual(workspace["active_event"]["id"], active.event_id)
        self.assertEqual(
            workspace["active_event"]["status"],
            EventStatus.NEW.value,
        )
        self.assertEqual(
            employees,
            [
                {
                    "id": "maintenance_001",
                    "name": "Equipment Maintenance",
                    "status": "working",
                    "current_event_id": active.event_id,
                    "responsibility": "Equipment Maintenance",
                    "skills": [],
                }
            ],
        )
        self.assertEqual(workspace["employees"], employees)

    def test_21_invalid_persisted_event_ids_are_omitted_from_all_apis(
        self,
    ) -> None:
        invalid_ids = (
            "/root/private/event",
            "\\\\server\\private\\event",
        )
        for event_id in invalid_ids:
            self.application.runtime.store.save_event(
                Event(
                    event_id=event_id,
                    source="corrupt_projection_fixture",
                    timestamp=utc_now(),
                    raw_input_ref="",
                    normalized_input={},
                    detected_issue="",
                    confidence=0.0,
                    severity="UNKNOWN",
                    status=EventStatus.NEW,
                    trace_id=f"trace_{uuid4().hex}",
                    event_type="corrupt_projection_fixture",
                    location="Synthetic-Security-Lab",
                    asset_id="CORRUPT-ID-PROBE",
                    reporter="synthetic:security-probe",
                    description="Synthetic corrupt Event ID fixture.",
                )
            )
        server = projection_server(self.application, self.directory)

        with serving(server) as port:
            payloads = {
                path: request(port, path)[2]
                for path in (
                    "/api/workspace",
                    "/api/events",
                    "/api/digital-employees",
                    "/api/pulse",
                )
            }

        self.assert_workspace_contract(payloads["/api/workspace"])
        self.assertEqual(
            payloads["/api/workspace"],
            {
                "version": "workspace-v1",
                "events": [],
                "active_event": None,
                "pulse": None,
                "employees": [],
            },
        )
        self.assertEqual(payloads["/api/events"], [])
        self.assertEqual(payloads["/api/digital-employees"], [])
        self.assertIsNone(payloads["/api/pulse"])
        public_strings = [
            item
            for payload in payloads.values()
            for item in recursive_strings(payload)
        ]
        for invalid_id in invalid_ids:
            self.assertFalse(
                any(
                    invalid_id in public_value
                    for public_value in public_strings
                )
            )

    def test_22_path_and_secret_sanitizer_covers_public_text_edges(
        self,
    ) -> None:
        probe = self.application.runtime.create_event(
            source="security_projection_probe",
            actor="agent:runtime-projection-test",
            event_type="security_projection_probe",
            location="Synthetic-Security-Lab",
            asset_id="SECURITY-PROBE",
            reporter="synthetic:security-probe",
            description="Synthetic public-text sanitizer probe.",
        )
        notification_event, analysis = self.analyze_and_notify()
        notification = (
            self.application.runtime.store.list_notifications(
                notification_event.event_id
            )[0]
        )
        canaries = (
            "/root/private/runtime.sqlite3",
            "(/redacted/runtime.sqlite3)",
            "\\\\server\\share\\runtime.sqlite3",
            "../private/runtime.sqlite3",
            "Authorization: Bearer synthetic-private-credential",
            "OPENAI_API_KEY=synthetic-private-key",
            (
                "Bearer eyJhbGciOiJIUzI1NiJ9."
                "eyJzdWIiOiJzeW50aGV0aWMtdXNlciJ9."
                "synthetic-private-signature"
            ),
            (
                "xoxb-111111111111-222222222222-"
                "syntheticprivatecredential"
            ),
            "AKIA1111111111111111",
            "ASIA2222222222222222",
        )

        for index, canary in enumerate(canaries):
            with self.subTest(field="responsibility.owner_id", value=canary):
                directory = ResponsibilityDirectory(
                    event_type={
                        "security_projection_probe": {
                            "owner_id": canary,
                            "owner_name": "Safe Projection Owner",
                        }
                    }
                )
                projection = RuntimeProjectionWebAdapter(
                    self.application,
                    responsibility_directory=directory,
                )
                projected_event = next(
                    event
                    for event in projection.get_events()
                    if event["id"] == probe.event_id
                )
                self.assertIsNone(projected_event["responsibility"])
                self.assertEqual(
                    projection.get_digital_employees(),
                    [],
                )

            with self.subTest(
                field="responsibility.owner_name",
                value=canary,
            ):
                directory = ResponsibilityDirectory(
                    event_type={
                        "security_projection_probe": {
                            "owner_id": f"safe-projection-owner-{index}",
                            "owner_name": canary,
                        }
                    }
                )
                projection = RuntimeProjectionWebAdapter(
                    self.application,
                    responsibility_directory=directory,
                )
                projected_event = next(
                    event
                    for event in projection.get_events()
                    if event["id"] == probe.event_id
                )
                self.assertIsNone(projected_event["responsibility"])
                self.assertEqual(
                    projection.get_digital_employees(),
                    [],
                )

            with self.subTest(field="notification.title", value=canary):
                overwrite_notification_title(
                    self.database,
                    notification.notification_id,
                    canary,
                )
                pulse = self.projection.get_pulse()
                self.assert_pulse_contract(pulse)
                self.assertEqual(pulse["title"], "[REDACTED]")
                self.assertNotIn(
                    canary,
                    list(recursive_strings(pulse)),
                )

        self.assertEqual(
            self.application.runtime.store.get_decision(
                analysis.decision_id
            ).event_id,
            notification_event.event_id,
        )

    def test_23_non_decision_audit_cannot_create_employee_skill(
        self,
    ) -> None:
        event = self.create_event()
        self.application.runtime.store.record_audit(
            AuditRecord(
                audit_id=f"audit_{uuid4().hex}",
                actor="agent:runtime-projection-test",
                action="provider_analysis_failed",
                object_type="Event",
                object_id=event.event_id,
                previous_state=EventStatus.NEW.value,
                new_state=EventStatus.FAILED.value,
                timestamp=utc_now(),
                trace_id=event.trace_id,
                details={
                    "model_metadata": {
                        "skill_id": "restaurant-aircon-troubleshooting",
                        "skill_version": "1.0-demo",
                    }
                },
            )
        )

        employees = self.projection.get_digital_employees()

        self.assertEqual(len(employees), 1)
        self.assertEqual(employees[0]["id"], "maintenance_001")
        self.assertEqual(employees[0]["skills"], [])


def recursive_keys(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from recursive_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from recursive_keys(item)


def recursive_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from recursive_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from recursive_strings(item)


if __name__ == "__main__":
    unittest.main()
