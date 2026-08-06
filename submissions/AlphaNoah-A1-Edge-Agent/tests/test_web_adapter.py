"""Task 05C-1 Web Adapter and local JSON API tests."""

from __future__ import annotations

import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stderr
from pathlib import Path
from threading import Barrier
from typing import Iterator
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from alphanoah_a1.exceptions import ProviderTransportError  # noqa: E402
from alphanoah_a1.ai_reliability import ModelOutputInvalidError  # noqa: E402
from alphanoah_a1.golden_path import (  # noqa: E402
    RestaurantAirconFakeAnalysisProvider,
    build_restaurant_aircon_golden_path,
)
from alphanoah_a1.models import EventStatus  # noqa: E402
from alphanoah_a1.web_adapter import (  # noqa: E402
    RestaurantAirconWebAdapter,
    WebAdapterError,
    WebErrorCode,
)
from alphanoah_a1.web_api import (  # noqa: E402
    MAX_REQUEST_BODY_BYTES,
    WebAdapterHTTPServer,
    create_server,
)


class FailingWebProvider(RestaurantAirconFakeAnalysisProvider):
    provider_id = "fake:web-provider-unavailable"

    def analyze_with_contexts(self, event, skill_context, knowledge_context):
        self.calls += 1
        raise ProviderTransportError(
            "Synthetic provider transport failure.",
            code="connection_error",
        )


class InvalidWebProvider(RestaurantAirconFakeAnalysisProvider):
    provider_id = "fake:web-provider-invalid"

    def analyze_with_contexts(self, event, skill_context, knowledge_context):
        self.calls += 1
        return "invalid output"


@contextmanager
def running_server(application) -> Iterator[tuple[object, int]]:
    server = create_server(
        Path("unused-when-application-is-injected.sqlite3"),
        port=0,
        application=application,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, server.server_address[1]
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
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], object | None]:
    body = raw_body
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if body is not None and "Content-Type" not in request_headers:
        request_headers["Content-Type"] = "application/json"
    connection = http.client.HTTPConnection(
        "127.0.0.1",
        port,
        timeout=3,
    )
    try:
        connection.request(
            method,
            path,
            body=body,
            headers=request_headers,
        )
        response = connection.getresponse()
        encoded = response.read()
        response_headers = {
            key.lower(): value for key, value in response.getheaders()
        }
        decoded = json.loads(encoded) if encoded else None
        return response.status, response_headers, decoded
    finally:
        connection.close()


def event_payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "location": "A08",
        "asset_type": "air_conditioner",
        "description": "A08 空调运行异常",
    }
    values.update(overrides)
    return values


class WebAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = (
            Path(self.temporary_directory.name) / "task05c1.sqlite3"
        )
        self.application = build_restaurant_aircon_golden_path(
            self.database
        )
        self.adapter = RestaurantAirconWebAdapter(self.application)

    def create_event(self) -> str:
        return self.adapter.create_event(event_payload())["event_id"]

    def analyze(self, event_id: str):
        return self.application.analyze(event_id)

    def approve_and_create_task(self, event_id: str):
        self.analyze(event_id)
        self.adapter.submit_review(
            event_id,
            {"action": "approve", "comment": "确认无人使用"},
        )
        result = self.adapter.create_task(event_id, {})
        return self.application.runtime.store.get_task(
            result["task"]["task_id"]
        )

    def test_01_event_creation_uses_existing_input_and_runtime_flow(
        self,
    ) -> None:
        created = self.adapter.create_event(event_payload())
        persisted = self.application.runtime.store.get_event(
            created["event_id"]
        )

        self.assertEqual(created["status"], EventStatus.NEW.value)
        self.assertEqual(persisted.status, EventStatus.NEW)
        self.assertEqual(persisted.source, "web_event_report")
        self.assertEqual(
            persisted.metadata["input_adapter"],
            "web_event_report_v1",
        )
        self.assertEqual(
            persisted.raw_input_ref,
            "local://web-event-report/form",
        )
        self.assertEqual(persisted.metadata["asset_type"], "air_conditioner")
        self.assertEqual(persisted.description, "A08 空调运行异常")

        queried = self.adapter.get_event(created["event_id"])
        self.assertIsNone(queried["analysis"])
        self.assertIsNone(queried["decision"])
        self.assertIsNone(queried["skill_id"])

    def test_02_invalid_or_secret_shaped_event_fields_are_rejected(
        self,
    ) -> None:
        invalid_payloads = (
            event_payload(description=""),
            event_payload(description="   "),
            event_payload(description="Write me a poem."),
            event_payload(description="写一首诗"),
            event_payload(description="今天天气怎么样"),
            event_payload(description="帮我写报告"),
            event_payload(description="你好"),
            event_payload(description="吃什么"),
            event_payload(description="x" * 2_001),
            event_payload(description="空调异常\n"),
            event_payload(location=""),
            event_payload(location=" A01"),
            event_payload(location="A01 "),
            event_payload(location="A/01"),
            event_payload(location="A.01"),
            event_payload(location="A01\n"),
            event_payload(location="x" * 65),
            event_payload(location="-A01"),
            event_payload(location="A01_"),
            event_payload(asset_type="industrial_machine"),
            {**event_payload(), "api_key": "synthetic-forbidden"},
            {**event_payload(), "file": "C:\\private\\evidence.txt"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(WebAdapterError) as context:
                    self.adapter.create_event(payload)
                self.assertEqual(
                    context.exception.code,
                    WebErrorCode.INVALID_REQUEST,
                )
        self.assertEqual(self.application.runtime.store.list_events(), [])

    def test_02a_natural_fault_variations_are_persisted_verbatim(self) -> None:
        cases = (
            ("A01", "The air conditioner is making an unusual rattling noise."),
            ("A08", "The air conditioner is leaking water."),
            ("B03", "Cooling performance is weaker than normal."),
            ("Workshop-A", "The air conditioner outlet temperature is unusually high."),
            ("Kitchen-2", "The air conditioner has abnormal airflow."),
            ("A01", "空调制冷差。"),
            ("A08", "空调不制冷"),
            ("A08", "空调出现不制冷"),
            ("A08", "空调无法制冷"),
            ("B03", "空调漏水"),
            ("A01", "空调有异响"),
            ("Workshop-A", "空调风变小了"),
            ("Kitchen-2", "空调出风很小"),
            ("A01", "空调开不了机"),
            ("B03", "空调无法启动"),
            ("B03", "空调运行时有异响。"),
            ("Workshop-A", "空调室内机漏水。"),
            ("Kitchen-2", "出风温度偏高并伴有异味。"),
        )

        for location, description in cases:
            with self.subTest(location=location, description=description):
                created = self.adapter.create_event(
                    event_payload(location=location, description=description)
                )
                persisted = self.application.runtime.store.get_event(
                    created["event_id"]
                )
                self.assertEqual(persisted.location, location)
                self.assertEqual(persisted.asset_id, f"{location}-AIRCON")
                self.assertEqual(persisted.description, description)
                self.assertEqual(
                    persisted.event_type, "equipment_fault_report"
                )
                self.assertEqual(persisted.status, EventStatus.NEW)

        self.assertEqual(
            len(self.application.runtime.store.list_events()),
            len(cases),
        )

    def test_03_analysis_query_does_not_trigger_provider(self) -> None:
        event_id = self.create_event()
        raw_provider = self.application.provider.provider

        with self.assertRaises(WebAdapterError) as context:
            self.adapter.get_analysis(event_id)

        self.assertEqual(
            context.exception.code,
            WebErrorCode.ANALYSIS_NOT_AVAILABLE,
        )
        self.assertEqual(raw_provider.calls, 0)
        self.assertEqual(
            self.application.runtime.store.get_event(event_id).status,
            EventStatus.NEW,
        )
        with self.assertRaises(WebAdapterError) as review_context:
            self.adapter.submit_review(
                event_id,
                {"action": "approve", "comment": "尚未分析"},
            )
        self.assertEqual(
            review_context.exception.code,
            WebErrorCode.HUMAN_REVIEW_REQUIRED,
        )

    def test_04_analysis_is_projected_from_existing_persistence_and_audit(
        self,
    ) -> None:
        event_id = self.create_event()
        summary = self.analyze(event_id)

        result = self.adapter.get_analysis(event_id)

        self.assertEqual(result["status"], "PENDING_HUMAN_REVIEW")
        self.assertEqual(
            result["analysis"]["decision_type"],
            "ai_assisted_incident_analysis",
        )
        self.assertTrue(
            result["analysis"]["requires_human_review"]
        )
        self.assertEqual(
            result["skill"]["skill_id"],
            summary.selected_skill_id,
        )
        self.assertEqual(len(result["knowledge_sources"]), 1)
        rendered = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("analysis_instructions", rendered)
        self.assertNotIn("prompt", rendered.casefold())
        self.assertNotIn(str(REPOSITORY_ROOT), rendered)

    def test_05_provider_failure_has_stable_safe_error(self) -> None:
        provider = FailingWebProvider()
        application = build_restaurant_aircon_golden_path(
            self.database,
            raw_provider=provider,
        )
        adapter = RestaurantAirconWebAdapter(application)
        event_id = adapter.create_event(event_payload())["event_id"]
        with self.assertRaises(ProviderTransportError):
            application.analyze(event_id)

        with self.assertRaises(WebAdapterError) as context:
            adapter.get_analysis(event_id)

        self.assertEqual(
            context.exception.code,
            WebErrorCode.PROVIDER_UNAVAILABLE,
        )
        self.assertEqual(context.exception.status, 503)
        self.assertNotIn("Synthetic", context.exception.message)
        self.assertEqual(
            application.runtime.store.list_decisions(event_id),
            [],
        )

    def test_06_human_approval_uses_runtime_and_does_not_create_task(
        self,
    ) -> None:
        event_id = self.create_event()
        analysis = self.analyze(event_id)

        reviewed = self.adapter.submit_review(
            event_id,
            {"action": "approve", "comment": "确认无人使用"},
        )

        self.assertEqual(reviewed["status"], EventStatus.APPROVED.value)
        self.assertEqual(reviewed["outcome"], "APPROVED")
        self.assertEqual(
            self.application.runtime.store.list_tasks(
                analysis.decision_id
            ),
            [],
        )

    def test_06b_task_command_requires_approval_and_is_recoverable(
        self,
    ) -> None:
        event_id = self.create_event()
        analysis = self.analyze(event_id)

        with self.assertRaises(WebAdapterError) as pending_context:
            self.adapter.create_task(event_id, {})
        self.assertEqual(
            pending_context.exception.code,
            WebErrorCode.INVALID_REQUEST,
        )
        self.assertEqual(pending_context.exception.status, 409)

        self.adapter.submit_review(
            event_id,
            {"action": "approve", "comment": "确认无人使用"},
        )
        created = self.adapter.create_task(event_id, {})
        repeated = self.adapter.create_task(event_id, {})

        self.assertEqual(created, repeated)
        self.assertEqual(created["task"]["status"], "CREATED")
        self.assertEqual(
            len(
                self.application.runtime.store.list_tasks(
                    analysis.decision_id
                )
            ),
            1,
        )
        with self.assertRaises(WebAdapterError) as payload_context:
            self.adapter.create_task(event_id, {"unexpected": "field"})
        self.assertEqual(
            payload_context.exception.code,
            WebErrorCode.INVALID_REQUEST,
        )

    def test_06c_human_review_commands_are_idempotent(self) -> None:
        event_id = self.create_event()
        analysis = self.analyze(event_id)
        barrier = Barrier(2)

        def concurrent_approve(_: int) -> dict[str, object]:
            barrier.wait()
            return self.adapter.submit_review(
                event_id,
                {"action": "approve", "comment": "批准"},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            approvals = list(pool.map(concurrent_approve, range(2)))

        self.assertEqual(
            approvals[0]["human_review_id"],
            approvals[1]["human_review_id"],
        )
        self.assertEqual(
            len(
                self.application.runtime.store.list_human_reviews(
                    analysis.decision_id
                )
            ),
            1,
        )

        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = list(
                pool.map(
                    lambda _: self.adapter.create_task(event_id, {}),
                    range(2),
                )
            )
        self.assertEqual(
            tasks[0]["task"]["task_id"],
            tasks[1]["task"]["task_id"],
        )
        self.assertEqual(
            len(
                self.application.runtime.store.list_tasks(
                    analysis.decision_id
                )
            ),
            1,
        )
        with self.assertRaises(WebAdapterError) as opposite_context:
            self.adapter.submit_review(
                event_id,
                {"action": "reject", "comment": "冲突决定"},
            )
        self.assertEqual(opposite_context.exception.status, 409)

        restarted = build_restaurant_aircon_golden_path(self.database)
        restarted_adapter = RestaurantAirconWebAdapter(restarted)
        recovered = restarted_adapter.submit_review(
            event_id,
            {"action": "approve", "comment": "重启后重试"},
        )
        recovered_task = restarted_adapter.create_task(event_id, {})
        self.assertEqual(
            recovered["human_review_id"], approvals[0]["human_review_id"]
        )
        self.assertEqual(
            recovered_task["task"]["task_id"],
            tasks[0]["task"]["task_id"],
        )

        rejected_event_id = self.create_event()
        rejected_analysis = self.analyze(rejected_event_id)
        first_rejection = self.adapter.submit_review(
            rejected_event_id,
            {"action": "reject", "comment": "拒绝"},
        )
        repeated_rejection = self.adapter.submit_review(
            rejected_event_id,
            {"action": "reject", "comment": "重复拒绝"},
        )
        self.assertEqual(
            first_rejection["human_review_id"],
            repeated_rejection["human_review_id"],
        )
        self.assertEqual(
            len(
                self.application.runtime.store.list_human_reviews(
                    rejected_analysis.decision_id
                )
            ),
            1,
        )
        self.assertEqual(
            self.application.runtime.store.list_tasks(
                rejected_analysis.decision_id
            ),
            [],
        )
        with self.assertRaises(WebAdapterError) as reverse_context:
            self.adapter.submit_review(
                rejected_event_id,
                {"action": "approve", "comment": "冲突决定"},
            )
        self.assertEqual(reverse_context.exception.status, 409)

    def test_06d_concurrent_http_review_never_returns_500(self) -> None:
        event_id = self.create_event()
        analysis = self.analyze(event_id)

        with running_server(self.application) as (_server, port):
            review_barrier = Barrier(2)

            def approve(_: int):
                review_barrier.wait()
                return request(
                    port,
                    "POST",
                    f"/api/events/{event_id}/review",
                    {"action": "approve", "comment": "批准"},
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                reviews = list(pool.map(approve, range(2)))

            task_barrier = Barrier(2)

            def create_task(_: int):
                task_barrier.wait()
                return request(
                    port,
                    "POST",
                    f"/api/events/{event_id}/task",
                    {},
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                tasks = list(pool.map(create_task, range(2)))

            conflict_status, _, conflict = request(
                port,
                "POST",
                f"/api/events/{event_id}/review",
                {"action": "reject", "comment": "冲突决定"},
            )

        self.assertEqual([status for status, _, _ in reviews], [200, 200])
        self.assertEqual(
            len({payload["human_review_id"] for _, _, payload in reviews}),
            1,
        )
        self.assertEqual([status for status, _, _ in tasks], [200, 200])
        self.assertEqual(
            len({payload["task"]["task_id"] for _, _, payload in tasks}),
            1,
        )
        self.assertEqual(conflict_status, 409)
        self.assertEqual(conflict["error_code"], "INVALID_REQUEST")
        self.assertEqual(
            len(
                self.application.runtime.store.list_human_reviews(
                    analysis.decision_id
                )
            ),
            1,
        )
        self.assertEqual(
            len(
                self.application.runtime.store.list_tasks(
                    analysis.decision_id
                )
            ),
            1,
        )

    def test_06a_invalid_analysis_has_stable_failed_error(self) -> None:
        application = build_restaurant_aircon_golden_path(
            self.database,
            raw_provider=InvalidWebProvider(),
        )
        adapter = RestaurantAirconWebAdapter(application)
        event_id = adapter.create_event(event_payload())["event_id"]
        with self.assertRaises(ModelOutputInvalidError):
            application.analyze(event_id)

        with self.assertRaises(WebAdapterError) as context:
            adapter.get_analysis(event_id)

        self.assertEqual(
            context.exception.code,
            WebErrorCode.ANALYSIS_FAILED,
        )
        self.assertEqual(context.exception.status, 422)
        self.assertEqual(
            application.runtime.store.list_decisions(event_id),
            [],
        )

    def test_07_rejection_and_duplicate_review_remain_controlled(
        self,
    ) -> None:
        event_id = self.create_event()
        self.analyze(event_id)

        rejected = self.adapter.submit_review(
            event_id,
            {"action": "reject", "comment": "现场情况不符"},
        )
        self.assertEqual(rejected["status"], EventStatus.REJECTED.value)

        with self.assertRaises(WebAdapterError) as context:
            self.adapter.submit_review(
                event_id,
                {"action": "approve", "comment": "重复操作"},
            )
        self.assertEqual(
            context.exception.code,
            WebErrorCode.INVALID_REQUEST,
        )

    def test_08_task_query_reads_existing_task_only(self) -> None:
        event_id = self.create_event()
        task = self.approve_and_create_task(event_id)

        queried = self.adapter.get_task(event_id)

        self.assertEqual(queried["task"]["task_id"], task.task_id)
        self.assertEqual(queried["task"]["status"], "CREATED")
        self.assertEqual(
            queried["task"]["owner"],
            "demo:restaurant-duty-operator",
        )

    def test_09_text_evidence_uses_runtime_without_file_upload(self) -> None:
        event_id = self.create_event()
        task = self.approve_and_create_task(event_id)
        self.application.start_task(task.task_id)

        result = self.adapter.submit_evidence(
            task.task_id,
            {"description": "已关闭空调"},
        )

        evidence = self.application.runtime.store.get_evidence(
            result["evidence_id"]
        )
        self.assertEqual(result["task_status"], "EVIDENCE_SUBMITTED")
        self.assertEqual(result["validation_status"], "PENDING")
        self.assertEqual(evidence.description, "已关闭空调")
        self.assertEqual(evidence.type, "synthetic_text_statement")
        self.assertTrue(
            evidence.file_or_data_ref.startswith(
                "synthetic://web-adapter/"
            )
        )

    def test_10_timeline_is_existing_audit_in_stable_order(self) -> None:
        event_id = self.create_event()
        self.analyze(event_id)

        timeline = self.adapter.get_timeline(event_id)

        self.assertEqual(
            [entry["sequence"] for entry in timeline],
            list(range(1, len(timeline) + 1)),
        )
        self.assertEqual(timeline[0]["action"], "event_created")
        self.assertIn("decision_created", {
            entry["action"] for entry in timeline
        })
        rendered = json.dumps(timeline)
        self.assertNotIn("model_metadata", rendered)
        self.assertNotIn("analysis_instructions", rendered)

    def test_11_all_required_http_endpoints_use_the_same_application(
        self,
    ) -> None:
        with running_server(self.application) as (_, port):
            status, headers, created = request(
                port,
                "POST",
                "/api/events",
                event_payload(),
            )
            event_id = created["event_id"]
            self.assertEqual(status, 201)
            self.assertEqual(headers["cache-control"], "no-store")
            self.assertEqual(headers["x-content-type-options"], "nosniff")
            health_status, _, health = request(port, "GET", "/api/health")
            self.assertEqual(health_status, 200)
            self.assertEqual(health["status"], "ok")
            self.assertEqual(health["database"], "ok")

            analysis_status, _, analyzed = request(
                port,
                "POST",
                f"/api/events/{event_id}/analysis",
                {},
            )
            self.assertEqual(analysis_status, 200)
            self.assertEqual(analyzed["status"], "PENDING_HUMAN_REVIEW")
            analysis_summary = self.application.runtime.store.list_decisions(
                event_id
            )[0]
            self.assertEqual(
                request(port, "GET", f"/api/events/{event_id}")[0],
                200,
            )
            analysis_status, _, analysis = request(
                port,
                "GET",
                f"/api/events/{event_id}/analysis",
            )
            self.assertEqual(analysis_status, 200)
            self.assertTrue(
                analysis["analysis"]["requires_human_review"]
            )

            review_status, _, reviewed = request(
                port,
                "POST",
                f"/api/events/{event_id}/review",
                {"action": "approve", "comment": "确认无人使用"},
            )
            self.assertEqual(review_status, 200)
            self.assertEqual(reviewed["status"], "APPROVED")

            task_create_status, _, task_created = request(
                port,
                "POST",
                f"/api/events/{event_id}/task",
                {},
            )
            self.assertEqual(task_create_status, 200)
            task = self.application.runtime.store.get_task(
                task_created["task"]["task_id"]
            )
            self.assertEqual(
                task.source_decision_id,
                analysis_summary.decision_id,
            )
            start_status, _, started = request(
                port,
                "POST",
                f"/api/tasks/{task.task_id}/start",
                {},
            )
            self.assertEqual(start_status, 200)
            self.assertEqual(started["task"]["status"], "IN_PROGRESS")
            task_status, _, task_result = request(
                port,
                "GET",
                f"/api/events/{event_id}/task",
            )
            self.assertEqual(task_status, 200)
            self.assertEqual(task_result["task"]["status"], "IN_PROGRESS")

            evidence_status, _, evidence = request(
                port,
                "POST",
                f"/api/tasks/{task.task_id}/evidence",
                {"description": "已关闭空调"},
            )
            self.assertEqual(evidence_status, 201)
            self.assertEqual(
                evidence["task_status"],
                "EVIDENCE_SUBMITTED",
            )

            begin_status, _, begun = request(
                port,
                "POST",
                f"/api/tasks/{task.task_id}/review/begin",
                {},
            )
            self.assertEqual(begin_status, 200)
            self.assertEqual(begun["task"]["status"], "UNDER_REVIEW")

            review_status, _, final_review = request(
                port,
                "POST",
                f"/api/tasks/{task.task_id}/review",
                {"action": "approve", "comment": "证据确认有效"},
            )
            self.assertEqual(review_status, 200)
            self.assertEqual(final_review["task"]["status"], "CLOSED")
            self.assertEqual(final_review["event_id"], event_id)
            self.assertTrue(final_review["review"]["closed"])
            self.assertEqual(
                self.application.runtime.store.get_event(event_id).status,
                EventStatus.CLOSED,
            )

            timeline_status, _, timeline = request(
                port,
                "GET",
                f"/api/events/{event_id}/timeline",
            )
            self.assertEqual(timeline_status, 200)
            self.assertEqual(
                [entry["sequence"] for entry in timeline],
                list(range(1, len(timeline) + 1)),
            )
            self.assertEqual(timeline[-1]["status"], "CLOSED")

    def test_12_http_errors_are_bounded_json_without_traceback_or_path(
        self,
    ) -> None:
        error_output = io.StringIO()
        with (
            running_server(self.application) as (server, port),
            redirect_stderr(error_output),
        ):
            missing_id = "event_" + "0" * 32
            status, _, missing = request(
                port,
                "GET",
                f"/api/events/{missing_id}",
            )
            self.assertEqual(status, 404)
            self.assertEqual(
                missing["error_code"],
                WebErrorCode.EVENT_NOT_FOUND.value,
            )

            invalid_status, _, invalid = request(
                port,
                "POST",
                "/api/events",
                {**event_payload(), "api_key": "forbidden"},
            )
            self.assertEqual(invalid_status, 400)
            self.assertEqual(invalid["error_code"], "INVALID_REQUEST")

            duplicate_status, _, duplicate = request(
                port,
                "POST",
                "/api/events",
                raw_body=(
                    b'{"location":"A08","location":"A08",'
                    b'"asset_type":"air_conditioner",'
                    b'"description":"synthetic"}'
                ),
            )
            self.assertEqual(duplicate_status, 400)
            self.assertEqual(duplicate["error_code"], "INVALID_REQUEST")

            too_large_status, _, too_large = request(
                port,
                "POST",
                "/api/events",
                raw_body=b"x" * (MAX_REQUEST_BODY_BYTES + 1),
            )
            self.assertEqual(too_large_status, 413)
            self.assertEqual(too_large["error_code"], "INVALID_REQUEST")

            method_status, method_headers, method_error = request(
                port,
                "PUT",
                "/api/events",
                event_payload(),
            )
            self.assertEqual(method_status, 405)
            self.assertEqual(method_headers["allow"], "GET, POST")
            self.assertEqual(
                method_error["error_code"],
                "INVALID_REQUEST",
            )

            windows_path = "C:" + "\\Users\\private\\runtime.sqlite3"
            sensitive = (
                windows_path + " ALPHANOAH_API_KEY=not-real"
            )
            with patch.object(
                server.adapter,
                "get_event",
                side_effect=RuntimeError(sensitive),
            ):
                internal_status, _, internal = request(
                    port,
                    "GET",
                    f"/api/events/{missing_id}",
                )
            self.assertEqual(internal_status, 500)
            rendered = json.dumps(internal)
            self.assertNotIn("Traceback", rendered)
            self.assertNotIn(windows_path, rendered)
            self.assertNotIn("not-real", rendered)

        self.assertNotIn("Traceback", error_output.getvalue())
        self.assertNotIn(str(self.database), error_output.getvalue())

    def test_12a_analysis_response_redacts_local_paths_and_secret_shapes(
        self,
    ) -> None:
        event_id = self.create_event()
        summary = self.analyze(event_id)
        decision = self.application.runtime.store.get_decision(
            summary.decision_id
        )
        windows_path = "C:" + "\\Users\\private\\runtime.sqlite3"
        token_shape = "sk-" + "syntheticsecretvalue"
        decision.reasoning_summary = (
            "Read " + windows_path
        )
        decision.evidence = ["API_KEY=synthetic-secret-shaped-value"]
        decision.model_or_rule = token_shape
        self.application.runtime.store.update_decision(decision)

        rendered = json.dumps(self.adapter.get_analysis(event_id))

        self.assertNotIn(windows_path, rendered)
        self.assertNotIn("synthetic-secret", rendered)
        self.assertNotIn(token_shape, rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_13_server_refuses_non_loopback_binding(self) -> None:
        with self.assertRaisesRegex(ValueError, "127.0.0.1"):
            WebAdapterHTTPServer(
                ("0.0.0.0", 0),
                self.adapter,
            )


if __name__ == "__main__":
    unittest.main()
