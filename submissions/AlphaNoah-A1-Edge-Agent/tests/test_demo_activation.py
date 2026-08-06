"""F03-C synthetic Digital Employee activation boundary tests."""

from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from alphanoah_a1.demo_activation import (  # noqa: E402
    DEMO_ACTOR,
    DEMO_ASSET_ID,
    DEMO_DATA_CLASSIFICATION,
    DEMO_INCIDENT_NOTICE,
    DEMO_LOCATION,
    DEMO_SOURCE,
    build_demo_activation_application,
)
from alphanoah_a1.demo_activation_adapter import (  # noqa: E402
    DemoActivationWebAdapter,
    DemoActivationWebError,
)
from alphanoah_a1.exceptions import ProviderTransportError  # noqa: E402
from alphanoah_a1.golden_path import (  # noqa: E402
    SCENARIO_ID,
    RestaurantAirconFakeAnalysisProvider,
    build_restaurant_aircon_golden_path,
)
from alphanoah_a1.models import EventStatus  # noqa: E402
from alphanoah_a1.notifications import NotificationStatus  # noqa: E402
from alphanoah_a1.responsibility import (  # noqa: E402
    ResponsibilityDirectory,
)
from alphanoah_a1.web_adapter import WebErrorCode  # noqa: E402
from alphanoah_a1.web_api import create_server  # noqa: E402


class FailingActivationProvider(RestaurantAirconFakeAnalysisProvider):
    provider_id = "fake:f03c-provider-unavailable"

    def analyze_with_contexts(self, event, skill_context, knowledge_context):
        self.calls += 1
        raise ProviderTransportError(
            "Synthetic provider transport failure.",
            code="connection_error",
        )


def activation_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "scenario_id": SCENARIO_ID,
        "description": "Synthetic A08 air conditioner remains on.",
        "request_id": "f03c-request-001",
    }
    payload.update(overrides)
    return payload


@contextmanager
def running_server(application) -> Iterator[int]:
    server = create_server(
        Path("unused-when-application-is-injected.sqlite3"),
        port=0,
        application=application,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(
    port: int,
    method: str,
    path: str,
    payload: object | None = None,
    *,
    raw_body: bytes | None = None,
) -> tuple[int, object]:
    body = raw_body
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"} if body is not None else {}
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        encoded = response.read()
        return response.status, json.loads(encoded)
    finally:
        connection.close()


class DemoActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = (
            Path(self.temporary_directory.name) / "f03c.sqlite3"
        )
        self.golden_path = build_restaurant_aircon_golden_path(
            self.database
        )
        self.application = build_demo_activation_application(
            self.golden_path
        )
        self.adapter = DemoActivationWebAdapter(self.application)

    def test_valid_activation_uses_real_runtime_boundaries(self) -> None:
        response = self.adapter.create_event(activation_payload())
        event_id = response["event"]["event_id"]
        event = self.golden_path.runtime.store.get_event(event_id)
        decisions = self.golden_path.runtime.store.list_decisions(event_id)
        notifications = (
            self.golden_path.runtime.store.list_notifications(event_id)
        )

        self.assertEqual(response["projection_version"], "f03c-demo-v1")
        self.assertFalse(response["replayed"])
        self.assertEqual(event.source, DEMO_SOURCE)
        self.assertEqual(event.event_type, "equipment_fault_report")
        self.assertEqual(event.asset_id, DEMO_ASSET_ID)
        self.assertEqual(event.location, DEMO_LOCATION)
        self.assertEqual(event.status, EventStatus.PENDING_HUMAN_REVIEW)
        self.assertEqual(event.metadata["asset_type"], "air_conditioner")
        self.assertEqual(event.metadata["scenario_id"], SCENARIO_ID)
        self.assertEqual(
            event.metadata["data_classification"],
            DEMO_DATA_CLASSIFICATION,
        )
        self.assertEqual(
            event.metadata["incident_notice"],
            DEMO_INCIDENT_NOTICE,
        )
        self.assertEqual(
            response["responsibility"]["owner_id"],
            "maintenance_001",
        )
        self.assertEqual(response["responsibility"]["match_type"], "asset")
        self.assertEqual(len(decisions), 1)
        self.assertEqual(
            decisions[0].status.value,
            "PENDING_HUMAN_REVIEW",
        )
        self.assertEqual(len(notifications), 1)
        self.assertEqual(
            notifications[0].status,
            NotificationStatus.CREATED,
        )
        self.assertEqual(
            self.golden_path.runtime.store.list_tasks(
                decisions[0].decision_id
            ),
            [],
        )
        self.assertEqual(response["human_review"]["allowed_actions"], [
            "approve",
            "reject",
        ])
        self.assertTrue(
            all(
                record["task_id"] is None
                for record in response["work_records"]
            )
        )
        self.assertEqual(
            response["quality"]["availability"],
            "available",
        )

    def test_input_adapter_writes_only_reviewed_synthetic_context(self) -> None:
        response = self.adapter.create_event(
            activation_payload(
                description="Bounded description.",
                request_id="source-shape-001",
            )
        )
        event = self.golden_path.runtime.store.get_event(
            response["event"]["event_id"]
        )

        self.assertEqual(event.source, DEMO_SOURCE)
        self.assertEqual(event.reporter, "synthetic:demo-activation")
        self.assertEqual(event.description, "Bounded description.")
        self.assertEqual(
            event.metadata["request_id"],
            "source-shape-001",
        )
        creation = self.golden_path.runtime.store.list_audit(
            event.trace_id
        )[0]
        self.assertEqual(creation.actor, DEMO_ACTOR)

    def test_invalid_exact_request_contract_creates_no_event(self) -> None:
        invalid_payloads = (
            {},
            activation_payload(description=""),
            activation_payload(description=" "),
            activation_payload(description="x" * 2_001),
            activation_payload(scenario_id="unknown-scenario"),
            activation_payload(request_id=""),
            activation_payload(request_id="contains/path"),
            activation_payload(request_id="../escape"),
            activation_payload(request_id="sk-syntheticsecretvalue"),
            activation_payload(request_id="x" * 129),
            {**activation_payload(), "owner_id": "maintenance_001"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(DemoActivationWebError) as context:
                    self.adapter.create_event(payload)
                self.assertEqual(
                    context.exception.code,
                    WebErrorCode.INVALID_REQUEST,
                )
        self.assertEqual(self.golden_path.runtime.store.list_events(), [])

    def test_request_id_is_idempotent_and_recovered_from_event_metadata(
        self,
    ) -> None:
        first = self.adapter.create_event(activation_payload())
        second = self.adapter.create_event(
            activation_payload(description="A duplicate command.")
        )
        restarted = DemoActivationWebAdapter(
            build_demo_activation_application(self.golden_path)
        )
        third = restarted.create_event(
            activation_payload(description="A post-restart replay.")
        )

        event_id = first["event"]["event_id"]
        self.assertEqual(second["event"]["event_id"], event_id)
        self.assertEqual(third["event"]["event_id"], event_id)
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.assertTrue(third["replayed"])
        self.assertEqual(
            len(self.golden_path.runtime.store.list_events()),
            1,
        )
        self.assertEqual(
            len(
                self.golden_path.runtime.store.list_notifications(event_id)
            ),
            1,
        )

    def test_concurrent_duplicate_requests_create_one_event(self) -> None:
        with ThreadPoolExecutor(max_workers=8) as executor:
            responses = list(
                executor.map(
                    lambda _: self.adapter.create_event(
                        activation_payload(
                            request_id="concurrent-request-001"
                        )
                    ),
                    range(8),
                )
            )

        event_ids = {
            response["event"]["event_id"] for response in responses
        }
        self.assertEqual(len(event_ids), 1)
        self.assertEqual(
            len(self.golden_path.runtime.store.list_events()),
            1,
        )
        self.assertEqual(
            sum(not response["replayed"] for response in responses),
            1,
        )

    def test_get_is_read_only_and_unknown_event_is_404(self) -> None:
        created = self.adapter.create_event(activation_payload())
        event_id = created["event"]["event_id"]
        provider = self.golden_path.provider.provider
        calls_before = provider.calls

        queried = self.adapter.get_event(event_id)

        self.assertEqual(queried["event"]["event_id"], event_id)
        self.assertEqual(provider.calls, calls_before)
        self.assertFalse(queried["replayed"])
        with self.assertRaises(DemoActivationWebError) as context:
            self.adapter.get_event("event_" + "0" * 32)
        self.assertEqual(context.exception.status, 404)
        self.assertEqual(
            context.exception.code,
            WebErrorCode.EVENT_NOT_FOUND,
        )

    def test_partial_failure_preserves_event_id_and_get_projection(self) -> None:
        failing_path = build_restaurant_aircon_golden_path(
            self.database,
            raw_provider=FailingActivationProvider(),
        )
        adapter = DemoActivationWebAdapter(
            build_demo_activation_application(failing_path)
        )

        with self.assertRaises(DemoActivationWebError) as context:
            adapter.create_event(
                activation_payload(request_id="failure-request-001")
            )

        error = context.exception.to_dict()
        event_id = error["event_id"]
        self.assertEqual(context.exception.status, 503)
        self.assertEqual(
            failing_path.runtime.store.get_event(event_id).status,
            EventStatus.FAILED,
        )
        partial = adapter.get_event(event_id)
        self.assertIsNone(partial["analysis"])
        self.assertIsNone(partial["notification"])
        self.assertEqual(partial["quality"]["availability"], "partial")
        self.assertEqual(
            failing_path.runtime.store.list_decisions(event_id),
            [],
        )

    def test_projection_excludes_private_analysis_and_audit_details(
        self,
    ) -> None:
        response = self.adapter.create_event(activation_payload())
        rendered = json.dumps(response, ensure_ascii=False)

        self.assertNotIn("analysis_instructions", rendered)
        self.assertNotIn("prompt_version", rendered)
        self.assertNotIn("model_metadata", rendered)
        self.assertNotIn("actor", rendered)
        self.assertNotIn("trace_id", rendered)
        self.assertNotIn(str(REPOSITORY_ROOT), rendered)
        self.assertNotIn("request_id", rendered)
        self.assertNotIn("skill_id", rendered)
        self.assertNotIn('"task_id": "task_', rendered)

    def test_http_routes_validate_duplicate_and_extra_fields(self) -> None:
        with running_server(self.golden_path) as port:
            created_status, created = request(
                port,
                "POST",
                "/api/demo/events",
                activation_payload(request_id="http-request-001"),
            )
            event_id = created["event"]["event_id"]
            get_status, queried = request(
                port,
                "GET",
                f"/api/demo/events/{event_id}",
            )
            duplicate_status, duplicate = request(
                port,
                "POST",
                "/api/demo/events",
                raw_body=(
                    b'{"scenario_id":"synthetic-restaurant-aircon-a08",'
                    b'"description":"one","description":"two",'
                    b'"request_id":"duplicate-key-001"}'
                ),
            )
            extra_status, extra = request(
                port,
                "POST",
                "/api/demo/events",
                {**activation_payload(), "status": "CLOSED"},
            )

        self.assertEqual(created_status, 201)
        self.assertEqual(get_status, 200)
        self.assertEqual(queried["event"]["event_id"], event_id)
        self.assertEqual(duplicate_status, 400)
        self.assertEqual(duplicate["error_code"], "INVALID_REQUEST")
        self.assertEqual(extra_status, 400)
        self.assertEqual(extra["error_code"], "INVALID_REQUEST")

    def test_existing_event_endpoint_behavior_remains_new_only(self) -> None:
        with running_server(self.golden_path) as port:
            status, existing = request(
                port,
                "POST",
                "/api/events",
                {
                    "location": "A08",
                    "asset_type": "air_conditioner",
                    "description": "The A08 air conditioner has abnormal airflow.",
                },
            )
            event = self.golden_path.runtime.store.get_event(
                existing["event_id"]
            )

        self.assertEqual(status, 201)
        self.assertEqual(existing["status"], "NEW")
        self.assertEqual(event.status, EventStatus.NEW)
        self.assertEqual(event.source, "web_event_report")
        self.assertEqual(
            event.metadata["input_adapter"],
            "web_event_report_v1",
        )
        self.assertEqual(
            self.golden_path.runtime.store.list_decisions(event.event_id),
            [],
        )

    def test_synthetic_responsibility_fixture_is_explicit(self) -> None:
        directory = ResponsibilityDirectory.from_file(
            REPOSITORY_ROOT
            / "examples"
            / "demo_activation_responsibility.json"
        )
        response = self.adapter.create_event(
            activation_payload(request_id="fixture-request-001")
        )
        event = self.golden_path.runtime.store.get_event(
            response["event"]["event_id"]
        )
        assignment = directory.resolve(event)

        self.assertEqual(assignment.owner_id, "maintenance_001")
        self.assertEqual(assignment.match_type, "asset")
        self.assertEqual(assignment.matched_key, "A08-AIRCON")

    def test_unknown_equipment_remains_unassigned(self) -> None:
        event = self.golden_path.runtime.create_event(
            source=DEMO_SOURCE,
            actor=DEMO_ACTOR,
            normalized_input={
                "location": "Unknown-Zone",
                "description": "Synthetic unknown equipment.",
            },
            event_type="unknown_demo_event",
            location="Unknown-Zone",
            asset_id="UNKNOWN-ASSET",
            reporter="synthetic:test",
            description="Synthetic unknown equipment.",
            metadata={"asset_type": "unknown_asset"},
        )

        assignment = self.application.responsibility_directory.resolve(event)

        self.assertEqual(
            assignment.owner_id,
            ResponsibilityDirectory.UNASSIGNED.owner_id,
        )
        self.assertEqual(assignment.match_type, "unassigned")

    def test_work_records_are_ordered_runtime_facts(self) -> None:
        response = self.adapter.create_event(
            activation_payload(request_id="timeline-request-001")
        )
        records = response["work_records"]

        self.assertGreaterEqual(len(records), 4)
        self.assertEqual(
            [record["sequence"] for record in records],
            sorted(record["sequence"] for record in records),
        )
        self.assertEqual(
            records[0]["kind"],
            "event_received",
        )
        self.assertEqual(
            records[-1]["kind"],
            "responsibility_matched",
        )
        self.assertTrue(
            all(
                record["event_id"] == response["event"]["event_id"]
                for record in records
            )
        )
        self.assertTrue(
            all(record["task_id"] is None for record in records)
        )


if __name__ == "__main__":
    unittest.main()
