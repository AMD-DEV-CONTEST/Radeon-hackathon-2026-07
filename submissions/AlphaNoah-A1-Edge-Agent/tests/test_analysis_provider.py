from __future__ import annotations

import io
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from alphanoah_a1.demo import (  # noqa: E402
    build_parser,
    run_analysis,
    run_read_only,
)
from alphanoah_a1.exceptions import (
    HumanActorRequired,
    InvalidStateTransition,
    ProviderInputError,
    ProviderOutputError,
    ProviderTransportError,
)  # noqa: E402
from alphanoah_a1.golden_path import build_restaurant_aircon_golden_path  # noqa: E402
from alphanoah_a1.web_adapter import RestaurantAirconWebAdapter  # noqa: E402
from alphanoah_a1.models import (
    AnalysisResult,
    EventStatus,
    HumanReviewOutcome,
)  # noqa: E402
from alphanoah_a1.providers import (  # noqa: E402
    ANALYSIS_OUTPUT_SCHEMA,
    OllamaAnalysisProvider,
)
from alphanoah_a1.providers.base import (  # noqa: E402
    analysis_system_instructions,
)
from alphanoah_a1.runtime import AlphaNoahRuntime  # noqa: E402


def valid_model_output() -> dict[str, Any]:
    return {
        "issue_summary": "Abnormal sound reported at packaging equipment.",
        "possible_causes": [
            "A moving component may require inspection.",
            "A loose guard may be producing vibration.",
        ],
        "recommended_actions": [
            "Keep the equipment in its current safe state.",
            "Have an authorized technician inspect the reported area.",
        ],
        "severity": "high",
        "confidence": 0.84,
        "evidence_used": [
            "Operator description",
            "Asset identifier",
        ],
        "limitations": [
            "No physical inspection was performed.",
            "No vibration measurement was supplied.",
        ],
        "requires_human_review": True,
    }


def valid_chinese_model_output() -> dict[str, Any]:
    return {
        "issue_summary": "A08 包厢空调在闭店后仍持续运行。",
        "possible_causes": [
            "排程状态可能尚未同步。",
            "现场关闭确认可能尚未完成。",
        ],
        "recommended_actions": [
            "先确认包厢无人使用。",
            "经授权人员确认后执行关闭流程。",
        ],
        "severity": "high",
        "confidence": 0.86,
        "evidence_used": ["事件描述", "设备标识"],
        "limitations": ["尚未进行现场检查。"],
        "requires_human_review": True,
    }


def ollama_envelope(output: Any) -> bytes:
    return json.dumps(
        {
            "model": "test-model:fixture",
            "response": json.dumps(output),
            "done": True,
        }
    ).encode("utf-8")


@contextmanager
def fake_ollama_server(
    body: bytes,
    *,
    status: int = 200,
    delay_seconds: float = 0.0,
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    requests: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            content_length = int(self.headers.get("Content-Length", "0"))
            request_body = self.rfile.read(content_length)
            try:
                payload = json.loads(request_body)
            except json.JSONDecodeError:
                payload = {"invalid_request_json": True}
            requests.append({"path": self.path, "payload": payload})
            if delay_seconds:
                time.sleep(delay_seconds)
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                pass

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class FakeProvider:
    provider_id = "fake:analysis"

    def __init__(self, result: AnalysisResult):
        self.result = result
        self.calls = 0

    def analyze(self, event: object) -> AnalysisResult:
        self.calls += 1
        return self.result


class OllamaAnalysisProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "runtime.sqlite3"
        self.runtime = AlphaNoahRuntime(str(self.database))

    def create_event(self):
        return self.runtime.create_event(
            source="manual_report",
            actor="adapter:qr-incident-report",
            event_type="equipment_issue_report",
            location="Packaging-Line-A",
            asset_id="PACK-003",
            reporter="demo-operator",
            description="Synthetic abnormal sound report.",
            attachments=["photo_ref_001"],
            metadata={
                "data_classification": "Synthetic demo data",
                "private_note": "must-not-be-sent",
            },
        )

    @staticmethod
    def provider(base_url: str, **overrides: Any):
        settings = {
            "base_url": base_url,
            "model": "test-model:fixture",
            "connect_timeout_seconds": 1.0,
            "total_timeout_seconds": 2.0,
            "max_prompt_bytes": 65_536,
            "max_request_bytes": 131_072,
            "max_response_bytes": 16_384,
        }
        settings.update(overrides)
        return OllamaAnalysisProvider(**settings)

    def test_01_valid_http_output_creates_one_human_review_decision(self) -> None:
        event = self.create_event()
        with fake_ollama_server(
            ollama_envelope(valid_model_output())
        ) as (base_url, requests):
            decision, hook = self.runtime.analyze_event_with_provider(
                event.event_id,
                provider=self.provider(base_url),
            )

        persisted_event = self.runtime.store.get_event(event.event_id)
        self.assertEqual(
            persisted_event.status, EventStatus.PENDING_HUMAN_REVIEW
        )
        self.assertEqual(hook.target_status, EventStatus.PENDING_HUMAN_REVIEW)
        self.assertTrue(decision.requires_human_review)
        self.assertEqual(
            len(self.runtime.store.list_decisions(event.event_id)), 1
        )
        self.assertEqual(self.runtime.store.list_tasks(decision.decision_id), [])
        self.assertEqual(requests[0]["path"], "/api/generate")
        self.assertFalse(requests[0]["payload"]["stream"])
        self.assertFalse(requests[0]["payload"]["think"])

    def test_02_human_review_policy_cannot_be_bypassed(self) -> None:
        event = self.create_event()
        provider = FakeProvider(
            AnalysisResult(
                detected_issue="Preliminary issue",
                decision_type="ai_assisted_incident_analysis",
                reasoning_summary="Possible cause; not a diagnosis.",
                evidence=["operator report"],
                model_or_rule="fake:model",
                confidence=0.9,
                requires_human_review=True,
                severity="HIGH",
            )
        )
        decision, _ = self.runtime.analyze_event_with_provider(
            event.event_id, provider=provider
        )

        with self.assertRaises(HumanActorRequired):
            self.runtime.submit_human_review(
                decision.decision_id,
                reviewer="provider:fake",
                outcome=HumanReviewOutcome.APPROVED,
                comment="Model cannot approve.",
            )
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.PENDING_HUMAN_REVIEW,
        )

    def test_03_non_json_model_output_fails_and_is_audited(self) -> None:
        event = self.create_event()
        body = json.dumps(
            {"model": "test", "response": "not-json", "done": True}
        ).encode("utf-8")
        with fake_ollama_server(body) as (base_url, _):
            with self.assertRaises(ProviderOutputError):
                self.runtime.analyze_event_with_provider(
                    event.event_id,
                    provider=self.provider(base_url),
                )

        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.FAILED,
        )
        self.assertEqual(self.runtime.store.list_decisions(event.event_id), [])
        failure = self.runtime.store.list_audit(event.trace_id)[-1]
        self.assertEqual(failure.action, "provider_analysis_failed")
        self.assertEqual(failure.details["failure_type"], "output")
        self.assertEqual(failure.details["error_code"], "invalid_model_json")

        class RecursionOutputProvider:
            provider_id = "fake:recursive-json"

            def analyze(self, event: object) -> AnalysisResult:
                envelope = {
                    "model": "test",
                    "response": "{}",
                    "done": True,
                }
                with patch(
                    "alphanoah_a1.providers.ollama.json.loads",
                    side_effect=[
                        envelope,
                        RecursionError("synthetic parser recursion"),
                    ],
                ):
                    return OllamaAnalysisProvider._extract_model_output(b"{}")

        nested_event = self.create_event()
        with self.assertRaises(ProviderOutputError) as nested_context:
            self.runtime.analyze_event_with_provider(
                nested_event.event_id,
                provider=RecursionOutputProvider(),
            )
        self.assertEqual(nested_context.exception.code, "invalid_model_json")
        self.assertEqual(
            self.runtime.store.get_event(nested_event.event_id).status,
            EventStatus.FAILED,
        )
        self.assertEqual(
            self.runtime.store.list_decisions(nested_event.event_id), []
        )
        nested_failure = self.runtime.store.list_audit(
            nested_event.trace_id
        )[-1]
        self.assertEqual(nested_failure.details["failure_type"], "output")
        self.assertEqual(
            nested_failure.details["error_code"], "invalid_model_json"
        )

    def test_04_missing_required_field_is_rejected(self) -> None:
        output = valid_model_output()
        del output["limitations"]
        with fake_ollama_server(ollama_envelope(output)) as (base_url, _):
            with self.assertRaisesRegex(
                ProviderOutputError, "missing fields: limitations"
            ):
                self.provider(base_url).analyze(self.create_event())

    def test_05_invalid_confidence_is_rejected(self) -> None:
        for confidence in (-0.1, 1.1, True, float("nan")):
            with self.subTest(confidence=confidence):
                output = valid_model_output()
                output["confidence"] = confidence
                with fake_ollama_server(
                    ollama_envelope(output)
                ) as (base_url, _):
                    with self.assertRaisesRegex(
                        ProviderOutputError, "confidence"
                    ):
                        self.provider(base_url).analyze(self.create_event())

    def test_06_invalid_severity_is_rejected(self) -> None:
        invalid_outputs = []
        invalid_severity = valid_model_output()
        invalid_severity["severity"] = "urgent"
        invalid_outputs.append(invalid_severity)
        empty_causes = valid_model_output()
        empty_causes["possible_causes"] = []
        invalid_outputs.append(empty_causes)
        long_summary = valid_model_output()
        long_summary["issue_summary"] = "x" * 501
        invalid_outputs.append(long_summary)
        for output in invalid_outputs:
            with self.subTest(output=output):
                with fake_ollama_server(
                    ollama_envelope(output)
                ) as (base_url, _):
                    with self.assertRaises(ProviderOutputError):
                        self.provider(base_url).analyze(self.create_event())

    def test_07_false_human_review_and_extra_control_fields_are_rejected(
        self,
    ) -> None:
        false_output = valid_model_output()
        false_output["requires_human_review"] = False
        extra_output = valid_model_output()
        extra_output["approval"] = "approved"
        for output in (false_output, extra_output):
            with self.subTest(keys=sorted(output)):
                with fake_ollama_server(
                    ollama_envelope(output)
                ) as (base_url, _):
                    with self.assertRaises(ProviderOutputError):
                        self.provider(base_url).analyze(self.create_event())

        event = self.create_event()
        fake_provider = FakeProvider(
            AnalysisResult(
                detected_issue="Unsafe provider result",
                decision_type="no_issue",
                reasoning_summary="Attempted policy bypass.",
                evidence=["untrusted"],
                model_or_rule="fake:model",
                confidence=1.0,
                requires_human_review=False,
                severity="LOW",
            )
        )
        with self.assertRaises(ProviderOutputError) as context:
            self.runtime.analyze_event_with_provider(
                event.event_id, provider=fake_provider
            )
        self.assertEqual(context.exception.code, "human_review_required")
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.FAILED,
        )
        self.assertEqual(self.runtime.store.list_decisions(event.event_id), [])

    def test_08_connection_failure_is_transport_failure_and_audited(
        self,
    ) -> None:
        event = self.create_event()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            unused_port = probe.getsockname()[1]
        provider = self.provider(f"http://127.0.0.1:{unused_port}")

        with self.assertRaises(ProviderTransportError) as context:
            self.runtime.analyze_event_with_provider(
                event.event_id, provider=provider
            )

        self.assertIn(context.exception.code, {"connection_error", "timeout"})
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.FAILED,
        )
        self.assertEqual(self.runtime.store.list_decisions(event.event_id), [])
        failure = self.runtime.store.list_audit(event.trace_id)[-1]
        self.assertEqual(failure.details["failure_type"], "transport")

    def test_09_total_timeout_is_enforced(self) -> None:
        with fake_ollama_server(
            ollama_envelope(valid_model_output()),
            delay_seconds=0.2,
        ) as (base_url, _):
            provider = self.provider(
                base_url,
                connect_timeout_seconds=0.03,
                total_timeout_seconds=0.05,
            )
            with self.assertRaises(ProviderTransportError) as context:
                provider.analyze(self.create_event())
        self.assertEqual(context.exception.code, "timeout")

    def test_10_non_2xx_is_a_transport_failure(self) -> None:
        with fake_ollama_server(
            b'{"error":"synthetic"}',
            status=500,
        ) as (base_url, _):
            with self.assertRaises(ProviderTransportError) as context:
                self.provider(base_url).analyze(self.create_event())
        self.assertEqual(context.exception.code, "http_error")

    def test_11_response_body_limit_is_enforced_before_json_parsing(self) -> None:
        with fake_ollama_server(b"x" * 300) as (base_url, _):
            with self.assertRaises(ProviderTransportError) as context:
                self.provider(
                    base_url, max_response_bytes=256
                ).analyze(self.create_event())
        self.assertEqual(context.exception.code, "response_too_large")

    def test_12_duplicate_analysis_creates_no_second_decision(self) -> None:
        event = self.create_event()
        result = AnalysisResult(
            detected_issue="Preliminary issue",
            decision_type="ai_assisted_incident_analysis",
            reasoning_summary="Possible cause; not a diagnosis.",
            evidence=["operator report"],
            model_or_rule="fake:model",
            confidence=0.9,
            requires_human_review=True,
            severity="HIGH",
        )
        provider = FakeProvider(result)
        self.runtime.analyze_event_with_provider(
            event.event_id, provider=provider
        )
        with self.assertRaises(InvalidStateTransition):
            self.runtime.analyze_event_with_provider(
                event.event_id, provider=provider
            )
        self.assertEqual(provider.calls, 1)
        self.assertEqual(
            len(self.runtime.store.list_decisions(event.event_id)), 1
        )

    def test_13_provider_alone_does_not_write_database_or_read_attachments(
        self,
    ) -> None:
        secret_file = Path(self.temporary_directory.name) / "secret.txt"
        secret_file.write_text("SECRET-FILE-CONTENT", encoding="utf-8")
        event = self.runtime.create_event(
            source="manual_report",
            actor="test",
            event_type="equipment_issue_report",
            description="Synthetic report.",
            attachments=[str(secret_file), "photo_ref_001"],
            metadata={"private_note": "SECRET-METADATA"},
        )
        with fake_ollama_server(
            ollama_envelope(valid_model_output())
        ) as (base_url, requests):
            result = self.provider(base_url).analyze(event)

        self.assertIsInstance(result, AnalysisResult)
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.NEW,
        )
        self.assertEqual(self.runtime.store.list_decisions(event.event_id), [])
        prompt = requests[0]["payload"]["prompt"]
        self.assertNotIn("SECRET-FILE-CONTENT", prompt)
        self.assertNotIn("SECRET-METADATA", prompt)
        self.assertNotIn("private_note", prompt)
        self.assertNotIn(str(secret_file), prompt)
        self.assertIn("photo_ref_001", prompt)

    def test_14_cli_analyze_and_read_only_decision_use_same_database(self) -> None:
        event = self.create_event()
        with fake_ollama_server(
            ollama_envelope(valid_model_output())
        ) as (base_url, _):
            args = build_parser().parse_args(
                [
                    "--db",
                    str(self.database),
                    "analyze",
                    "event",
                    event.event_id,
                    "--base-url",
                    base_url,
                    "--model",
                    "test-model:fixture",
                ]
            )
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                exit_code = run_analysis(args)

        self.assertEqual(exit_code, 0)
        analysis_summary = json.loads(output.getvalue())
        self.assertEqual(
            analysis_summary["event_status"], "PENDING_HUMAN_REVIEW"
        )
        self.assertTrue(analysis_summary["requires_human_review"])

        show_args = build_parser().parse_args(
            [
                "--db",
                str(self.database),
                "show",
                "decision",
                analysis_summary["decision_id"],
            ]
        )
        decision_output = io.StringIO()
        with redirect_stdout(decision_output):
            show_exit_code = run_read_only(show_args)
        self.assertEqual(show_exit_code, 0)
        self.assertEqual(
            json.loads(decision_output.getvalue())["decision_id"],
            analysis_summary["decision_id"],
        )

    def test_15_provider_configuration_is_explicit_and_loopback_only(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            OllamaAnalysisProvider(
                base_url="https://example.com",
                model="test-model:fixture",
            )
        with self.assertRaises(ValueError):
            OllamaAnalysisProvider(
                base_url="http://127.0.0.1:11434",
                model="",
            )
        with self.assertRaises(ValueError):
            OllamaAnalysisProvider(
                base_url="http://127.0.0.1:11434",
                model="test-model:fixture",
                model_digest="unconfirmed",
            )

    def test_16_oversized_direct_runtime_event_never_reaches_http(self) -> None:
        event = self.runtime.create_event(
            source="manual_report",
            actor="test",
            event_type="equipment_issue_report",
            description="x" * 10_000,
        )
        with fake_ollama_server(
            ollama_envelope(valid_model_output())
        ) as (base_url, requests):
            with self.assertRaises(ProviderInputError) as context:
                self.runtime.analyze_event_with_provider(
                    event.event_id,
                    provider=self.provider(
                        base_url,
                        max_prompt_bytes=4_096,
                        max_request_bytes=8_192,
                    ),
                )

        self.assertEqual(context.exception.code, "prompt_too_large")
        self.assertEqual(requests, [])
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.FAILED,
        )
        self.assertEqual(self.runtime.store.list_decisions(event.event_id), [])
        failure = self.runtime.store.list_audit(event.trace_id)[-1]
        self.assertEqual(failure.details["failure_type"], "input")
        self.assertEqual(failure.details["error_code"], "prompt_too_large")

    def test_17_default_language_is_chinese_with_stable_schema(self) -> None:
        event = self.create_event()
        with fake_ollama_server(
            ollama_envelope(valid_chinese_model_output())
        ) as (base_url, requests):
            result = self.provider(base_url).analyze(event)

        payload = requests[0]["payload"]
        self.assertIn(
            "response_language = zh-CN",
            payload["prompt"],
        )
        self.assertIn(
            "All human-readable business content must use Simplified Chinese",
            analysis_system_instructions(),
        )
        self.assertEqual(payload["format"], ANALYSIS_OUTPUT_SCHEMA)
        self.assertEqual(payload["model"], "test-model:fixture")
        self.assertIs(
            payload["format"]["properties"]["requires_human_review"][
                "const"
            ],
            True,
        )
        self.assertEqual(
            payload["format"]["properties"]["severity"]["enum"],
            ["critical", "high", "low", "medium"],
        )
        self.assertEqual(
            result.detected_issue,
            "A08 包厢空调在闭店后仍持续运行。",
        )
        self.assertIn("可能原因", result.reasoning_summary)
        self.assertIn("须经人工确认的建议操作", result.reasoning_summary)
        self.assertEqual(
            result.decision_type,
            "ai_assisted_incident_analysis",
        )
        self.assertEqual(result.severity, "HIGH")
        self.assertTrue(result.requires_human_review)


    def test_20_web_event_prompt_uses_web_provenance_without_qr_claim(self) -> None:
        with fake_ollama_server(
            ollama_envelope(valid_model_output())
        ) as (base_url, requests):
            application = build_restaurant_aircon_golden_path(
                self.database,
                raw_provider=self.provider(base_url),
            )
            adapter = RestaurantAirconWebAdapter(application)
            created = adapter.create_event(
                {
                    "location": "B03",
                    "asset_type": "air_conditioner",
                    "description": (
                        "The air conditioner in B03 is cooling less effectively "
                        "than usual and the outlet temperature appears higher "
                        "than normal."
                    ),
                }
            )
            application.analyze(created["event_id"])

        event = application.runtime.store.get_event(created["event_id"])
        prompt = requests[0]["payload"]["prompt"]
        self.assertEqual(event.source, "web_event_report")
        self.assertEqual(
            event.metadata["input_adapter"],
            "web_event_report_v1",
        )
        self.assertIn('"source":"web_event_report"', prompt)
        self.assertNotIn("qr", prompt.casefold())
        self.assertNotIn("二维码", prompt)
        self.assertEqual(
            event.status,
            EventStatus.PENDING_HUMAN_REVIEW,
        )


if __name__ == "__main__":
    unittest.main()
