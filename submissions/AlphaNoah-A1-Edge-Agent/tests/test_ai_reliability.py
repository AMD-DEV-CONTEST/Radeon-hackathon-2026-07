"""Focused tests for the Task 04.5A model reliability boundary."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from alphanoah_a1.ai_reliability import (  # noqa: E402
    ModelFailureCode,
    ReliabilityPolicy,
    ReliableAnalysisProvider,
    ValidationStatus,
)
from alphanoah_a1.exceptions import (  # noqa: E402
    ProviderOutputError,
    ProviderTransportError,
)
from alphanoah_a1.models import AnalysisResult, EventStatus  # noqa: E402
from alphanoah_a1.providers import OllamaAnalysisProvider  # noqa: E402
from alphanoah_a1.runtime import AlphaNoahRuntime  # noqa: E402


def valid_analysis_result() -> AnalysisResult:
    return AnalysisResult(
        detected_issue="Preliminary abnormal sound report.",
        decision_type="ai_assisted_incident_analysis",
        reasoning_summary=(
            "Possible cause only; isolate safely and request human inspection."
        ),
        evidence=[
            "evidence_used=synthetic operator report",
            "suggested_human_action=authorized inspection",
        ],
        model_or_rule="fake:reliability-model",
        confidence=0.74,
        requires_human_review=True,
        severity="HIGH",
    )


def valid_model_json() -> dict[str, object]:
    return {
        "issue_summary": "Preliminary abnormal sound report.",
        "possible_causes": ["Loose component"],
        "recommended_actions": ["Request authorized inspection"],
        "severity": "high",
        "confidence": 0.74,
        "evidence_used": ["Synthetic operator report"],
        "limitations": ["No physical inspection was performed"],
        "requires_human_review": True,
    }


class StaticProvider:
    provider_id = "fake:reliability"
    model = "fixture-model:v1"
    prompt_version = "fixture-prompt-v1"

    def __init__(self, result: object):
        self.result = result
        self.calls = 0

    def analyze(self, event: object) -> object:
        self.calls += 1
        return self.result


class SlowProvider(StaticProvider):
    def analyze(self, event: object) -> object:
        self.calls += 1
        time.sleep(0.15)
        return self.result


class FlakyConnectionProvider(StaticProvider):
    def __init__(self, result: object, failures: int):
        super().__init__(result)
        self.failures = failures

    def analyze(self, event: object) -> object:
        self.calls += 1
        if self.calls <= self.failures:
            raise ProviderTransportError(
                "Synthetic connection failure.",
                code="connection_error",
            )
        return self.result


class ReliabilityLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        database = Path(self.temporary_directory.name) / "runtime.sqlite3"
        self.runtime = AlphaNoahRuntime(str(database))

    def create_event(self):
        return self.runtime.create_event(
            source="manual_report",
            actor="test:reliability",
            event_type="equipment_issue_report",
            asset_id="PACK-003",
            location="Packaging-Line-A",
            description="Synthetic abnormal sound report.",
            metadata={"data_classification": "Synthetic demo data"},
        )

    @staticmethod
    def reliable(provider: object, **policy: object):
        return ReliableAnalysisProvider(
            provider,
            policy=ReliabilityPolicy(**policy),
        )

    def test_01_normal_json_is_accepted_and_model_metadata_is_audited(
        self,
    ) -> None:
        event = self.create_event()
        raw_provider = OllamaAnalysisProvider(
            base_url="http://127.0.0.1:11434",
            model="fixture-model:v1",
        )
        envelope = json.dumps(
            {
                "model": "fixture-model:v1",
                "response": json.dumps(valid_model_json()),
                "done": True,
            }
        ).encode("utf-8")
        provider = self.reliable(
            raw_provider,
            timeout_seconds=1.0,
            max_retry=0,
        )

        with patch.object(
            raw_provider, "_post_generate", return_value=envelope
        ):
            decision, _ = self.runtime.analyze_event_with_provider(
                event.event_id,
                provider=provider,
            )

        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.PENDING_HUMAN_REVIEW,
        )
        self.assertTrue(decision.requires_human_review)
        decision_audit = next(
            record
            for record in self.runtime.store.list_audit(event.trace_id)
            if record.action == "decision_created"
        )
        metadata = decision_audit.details["model_metadata"]
        self.assertEqual(metadata["model_name"], "fixture-model:v1")
        self.assertEqual(metadata["provider_name"], "ollama")
        self.assertEqual(
            metadata["validation_status"], ValidationStatus.VALID.value
        )
        self.assertEqual(
            metadata["prompt_version"], "ollama-industrial-analysis-v4"
        )
        self.assertEqual(metadata["attempt_count"], 1)

    def test_02_plain_text_becomes_model_output_invalid(self) -> None:
        event = self.create_event()
        raw_provider = OllamaAnalysisProvider(
            base_url="http://127.0.0.1:11434",
            model="fixture-model:v1",
        )
        envelope = json.dumps(
            {
                "model": "fixture-model:v1",
                "response": "ordinary text",
                "done": True,
            }
        ).encode("utf-8")
        provider = self.reliable(
            raw_provider,
            timeout_seconds=1.0,
            max_retry=1,
        )

        with patch.object(
            raw_provider, "_post_generate", return_value=envelope
        ):
            with self.assertRaises(ProviderOutputError) as context:
                self.runtime.analyze_event_with_provider(
                    event.event_id,
                    provider=provider,
                )

        self.assertEqual(
            context.exception.code,
            ModelFailureCode.MODEL_OUTPUT_INVALID.value,
        )
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.FAILED,
        )
        failure = self.runtime.store.list_audit(event.trace_id)[-1]
        self.assertEqual(
            failure.details["model_metadata"]["validation_status"],
            ValidationStatus.INVALID_SCHEMA.value,
        )
        self.assertEqual(
            failure.details["model_metadata"]["attempt_count"], 1
        )

    def test_03_missing_json_field_is_rejected_without_repair(self) -> None:
        event = self.create_event()
        incomplete = valid_analysis_result().to_dict()
        del incomplete["reasoning_summary"]
        provider = self.reliable(
            StaticProvider(incomplete),
            timeout_seconds=1.0,
            max_retry=1,
        )

        with self.assertRaises(ProviderOutputError) as context:
            self.runtime.analyze_event_with_provider(
                event.event_id,
                provider=provider,
            )

        self.assertEqual(
            context.exception.code,
            ModelFailureCode.MODEL_OUTPUT_INVALID.value,
        )
        failure = self.runtime.store.list_audit(event.trace_id)[-1]
        self.assertEqual(
            failure.details["model_metadata"]["validation_status"],
            ValidationStatus.MISSING_FIELD.value,
        )
        self.assertEqual(
            failure.details["model_metadata"]["attempt_count"], 1
        )
        self.assertEqual(self.runtime.store.list_decisions(event.event_id), [])

    def test_04_total_timeout_fails_safely_without_overlapping_retry(
        self,
    ) -> None:
        event = self.create_event()
        raw_provider = SlowProvider(valid_analysis_result())
        provider = self.reliable(
            raw_provider,
            timeout_seconds=0.03,
            max_retry=1,
        )

        with self.assertRaises(ProviderTransportError) as context:
            self.runtime.analyze_event_with_provider(
                event.event_id,
                provider=provider,
            )

        self.assertEqual(
            context.exception.code,
            ModelFailureCode.MODEL_TIMEOUT.value,
        )
        self.assertEqual(raw_provider.calls, 1)
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.FAILED,
        )
        failure = self.runtime.store.list_audit(event.trace_id)[-1]
        metadata = failure.details["model_metadata"]
        self.assertEqual(metadata["attempt_count"], 1)
        self.assertEqual(
            metadata["validation_status"],
            ValidationStatus.NOT_VALIDATED.value,
        )
        self.assertEqual(self.runtime.store.list_decisions(event.event_id), [])

    def test_05_first_transient_failure_then_retry_success(self) -> None:
        event = self.create_event()
        raw_provider = FlakyConnectionProvider(
            valid_analysis_result(), failures=1
        )
        provider = self.reliable(
            raw_provider,
            timeout_seconds=1.0,
            max_retry=1,
        )

        self.runtime.analyze_event_with_provider(
            event.event_id,
            provider=provider,
        )

        self.assertEqual(raw_provider.calls, 2)
        self.assertEqual(
            len(self.runtime.store.list_decisions(event.event_id)), 1
        )
        decision_audit = next(
            record
            for record in self.runtime.store.list_audit(event.trace_id)
            if record.action == "decision_created"
        )
        metadata = decision_audit.details["model_metadata"]
        self.assertEqual(metadata["attempt_count"], 2)
        self.assertEqual(
            metadata["validation_status"], ValidationStatus.VALID.value
        )
        self.assertEqual(
            metadata["source_error_codes"], ["connection_error"]
        )

    def test_06_retry_limit_exhaustion_is_audited_and_creates_no_decision(
        self,
    ) -> None:
        event = self.create_event()
        raw_provider = FlakyConnectionProvider(
            valid_analysis_result(), failures=5
        )
        provider = self.reliable(
            raw_provider,
            timeout_seconds=1.0,
            max_retry=1,
        )

        with self.assertRaises(ProviderTransportError) as context:
            self.runtime.analyze_event_with_provider(
                event.event_id,
                provider=provider,
            )

        self.assertEqual(
            context.exception.code,
            ModelFailureCode.MODEL_CONNECTION_ERROR.value,
        )
        self.assertEqual(raw_provider.calls, 2)
        self.assertEqual(self.runtime.store.list_decisions(event.event_id), [])
        failure = self.runtime.store.list_audit(event.trace_id)[-1]
        metadata = failure.details["model_metadata"]
        self.assertEqual(metadata["attempt_count"], 2)
        self.assertEqual(metadata["max_retry"], 1)
        self.assertEqual(
            metadata["model_failure_code"],
            ModelFailureCode.MODEL_CONNECTION_ERROR.value,
        )
        self.assertEqual(
            metadata["source_error_codes"],
            ["connection_error", "connection_error"],
        )

    def test_07_human_review_bypass_is_unsafe_output(self) -> None:
        event = self.create_event()
        unsafe = valid_analysis_result().to_dict()
        unsafe["requires_human_review"] = False
        provider = self.reliable(
            StaticProvider(unsafe),
            timeout_seconds=1.0,
            max_retry=1,
        )

        with self.assertRaises(ProviderOutputError):
            self.runtime.analyze_event_with_provider(
                event.event_id,
                provider=provider,
            )

        failure = self.runtime.store.list_audit(event.trace_id)[-1]
        self.assertEqual(
            failure.details["model_metadata"]["validation_status"],
            ValidationStatus.UNSAFE_OUTPUT.value,
        )
        self.assertEqual(self.runtime.store.list_decisions(event.event_id), [])


if __name__ == "__main__":
    unittest.main()
