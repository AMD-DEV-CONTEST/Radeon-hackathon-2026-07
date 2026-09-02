"""Task 04.5C deterministic Skill boundary tests."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from alphanoah_a1.skill import (  # noqa: E402
    SkillContext,
    SkillDefinition,
    SkillStatus,
)
from alphanoah_a1.exceptions import (  # noqa: E402
    ProviderOutputError,
    ProviderTransportError,
    SkillConflictError,
    SkillNotFoundError,
)
from alphanoah_a1.ai_reliability import (  # noqa: E402
    ReliabilityPolicy,
    ReliableAnalysisProvider,
)
from alphanoah_a1.demo import build_parser  # noqa: E402
from alphanoah_a1.knowledge import (  # noqa: E402
    ContextBuilder,
    JsonKnowledgeRepository,
    KnowledgeContext,
    KnowledgeDocument,
)
from alphanoah_a1.models import (  # noqa: E402
    AnalysisResult,
    Event,
    EventStatus,
)
from alphanoah_a1.providers import OllamaAnalysisProvider  # noqa: E402
from alphanoah_a1.runtime import AlphaNoahRuntime  # noqa: E402
from alphanoah_a1.skills.demo import (  # noqa: E402
    DEMO_SKILL_DEFINITIONS,
    INDUSTRIAL_EQUIPMENT_SHUTDOWN_SKILL,
    RESTAURANT_AIRCON_TROUBLESHOOTING_SKILL,
)
from alphanoah_a1.skills.resolver import (  # noqa: E402
    DeterministicSkillResolver,
)


def minimal_definition(**overrides: object) -> SkillDefinition:
    values = {
        "skill_id": "synthetic-skill",
        "version": "1.0-demo",
        "status": SkillStatus.ACTIVE,
        "analysis_instructions": (
            "Analyze only the synthetic report and require human review."
        ),
        "supported_event_types": ("equipment_issue_report",),
        "supported_asset_types": ("industrial_machine",),
        "escalation_rules": ("Escalate to an authorized human.",),
        "knowledge_query_hints": ("shutdown guidance",),
    }
    values.update(overrides)
    return SkillDefinition(**values)


def synthetic_event(
    *,
    event_type: str = "equipment_fault_report",
    asset_type: object = "air_conditioner",
) -> Event:
    metadata = {}
    if asset_type is not None:
        metadata["asset_type"] = asset_type
    return Event.from_dict(
        {
            "event_id": "evt_synthetic_skill",
            "trace_id": "trace_synthetic_skill",
            "event_type": event_type,
            "source": "synthetic_test",
            "timestamp": "2026-07-26T00:00:00+00:00",
            "raw_input_ref": "synthetic://skill-guidance",
            "normalized_input": {},
            "detected_issue": "",
            "confidence": 0.0,
            "severity": "",
            "status": "NEW",
            "description": "Synthetic air-conditioner fault report.",
            "metadata": metadata,
        }
    )


def restaurant_definition(**overrides: object) -> SkillDefinition:
    values = {
        "skill_id": "restaurant-aircon-troubleshooting",
        "version": "1.0-demo",
        "status": SkillStatus.ACTIVE,
        "analysis_instructions": (
            "Analyze a synthetic restaurant air-conditioner troubleshooting report."
        ),
        "supported_event_types": ("equipment_fault_report",),
        "supported_asset_types": ("air_conditioner",),
        "knowledge_query_hints": ("safe fault triage",),
    }
    values.update(overrides)
    return SkillDefinition(**values)


def industrial_definition(**overrides: object) -> SkillDefinition:
    values = {
        "skill_id": "industrial-equipment-shutdown",
        "version": "1.0-demo",
        "status": SkillStatus.ACTIVE,
        "analysis_instructions": (
            "Analyze a synthetic industrial equipment shutdown report."
        ),
        "supported_event_types": ("device_not_shutdown",),
        "supported_asset_types": ("industrial_machine",),
        "knowledge_query_hints": ("equipment shutdown",),
    }
    values.update(overrides)
    return SkillDefinition(**values)


def valid_analysis_result() -> AnalysisResult:
    return AnalysisResult(
        detected_issue="Synthetic device shutdown exception",
        decision_type="ai_assisted_incident_analysis",
        reasoning_summary=(
            "A synthetic report requires authorized human verification."
        ),
        evidence=["Synthetic Event and bounded contexts"],
        model_or_rule="fake:skill-guided-analysis",
        confidence=0.75,
        requires_human_review=True,
        severity="HIGH",
    )


class ContextCapturingProvider:
    provider_id = "fake:skill-guided-analysis"
    model = "fixture-skill-model:v1"
    prompt_version = "fixture-skill-prompt-v1"

    def __init__(self) -> None:
        self.calls = 0
        self.skill_contexts: list[SkillContext] = []
        self.knowledge_contexts: list[KnowledgeContext] = []

    def analyze(self, event: Event) -> AnalysisResult:
        raise AssertionError("skill-guided path must be explicit")

    def analyze_with_context(
        self,
        event: Event,
        knowledge_context: KnowledgeContext,
    ) -> AnalysisResult:
        raise AssertionError("skill-guided path must include SkillContext")

    def analyze_with_contexts(
        self,
        event: Event,
        skill_context: SkillContext,
        knowledge_context: KnowledgeContext,
    ) -> AnalysisResult:
        self.calls += 1
        self.skill_contexts.append(skill_context)
        self.knowledge_contexts.append(knowledge_context)
        return valid_analysis_result()


class SlowSkillProvider(ContextCapturingProvider):
    def analyze_with_contexts(
        self,
        event: Event,
        skill_context: SkillContext,
        knowledge_context: KnowledgeContext,
    ) -> AnalysisResult:
        self.calls += 1
        time.sleep(0.15)
        return valid_analysis_result()


class ScenarioAwareFakeProvider(ContextCapturingProvider):
    def analyze_with_contexts(
        self,
        event: Event,
        skill_context: SkillContext,
        knowledge_context: KnowledgeContext,
    ) -> AnalysisResult:
        self.calls += 1
        self.skill_contexts.append(skill_context)
        self.knowledge_contexts.append(knowledge_context)
        if skill_context.skill_id == "restaurant-aircon-troubleshooting":
            summary = (
                "Synthetic restaurant air-conditioner troubleshooting and maintenance review."
            )
            issue = "synthetic_restaurant_aircon_fault_exception"
        else:
            summary = (
                "Synthetic residual-energy and authorized maintenance review."
            )
            issue = "synthetic_industrial_equipment_shutdown_exception"
        return AnalysisResult(
            detected_issue=issue,
            decision_type="ai_assisted_incident_analysis",
            reasoning_summary=summary,
            evidence=[
                f"skill_id={skill_context.skill_id}",
                f"knowledge_count={len(knowledge_context.documents)}",
            ],
            model_or_rule="fake:scenario-aware-skill-analysis",
            confidence=0.75,
            requires_human_review=True,
            severity="HIGH",
        )


class SkillContractTests(unittest.TestCase):
    def test_01_valid_definition_creates_bounded_context(self) -> None:
        definition = minimal_definition()

        context = definition.to_context(
            resolution_reason=(
                "matched:event_type,asset_type;specificity=2"
            )
        )

        self.assertIsInstance(context, SkillContext)
        self.assertEqual(context.skill_id, definition.skill_id)
        self.assertEqual(context.skill_version, definition.version)
        self.assertEqual(
            context.audit_metadata()["skill_resolution"],
            "matched:event_type,asset_type;specificity=2",
        )

    def test_02_blank_skill_id_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "skill_id"):
            minimal_definition(skill_id="")

    def test_03_blank_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "version"):
            minimal_definition(version="")

    def test_04_blank_analysis_instructions_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "analysis_instructions"):
            minimal_definition(analysis_instructions="")

    def test_05_invalid_status_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "status"):
            minimal_definition(status="unknown")

    def test_06_collections_are_normalized_deterministically(self) -> None:
        first = minimal_definition(
            supported_event_types=(
                "safety_observation",
                "equipment_issue_report",
                "safety_observation",
            ),
            knowledge_query_hints=("zeta hint", "alpha hint", "zeta hint"),
        )
        second = minimal_definition(
            supported_event_types=(
                "equipment_issue_report",
                "safety_observation",
            ),
            knowledge_query_hints=("alpha hint", "zeta hint"),
        )

        self.assertEqual(
            first.supported_event_types,
            second.supported_event_types,
        )
        self.assertEqual(
            first.knowledge_query_hints,
            second.knowledge_query_hints,
        )
        self.assertEqual(first.to_dict(), second.to_dict())


class DeterministicSkillResolverTests(unittest.TestCase):
    def test_07_restaurant_event_resolves_restaurant_skill(self) -> None:
        resolver = DeterministicSkillResolver(
            (industrial_definition(), restaurant_definition())
        )

        context = resolver.resolve(synthetic_event())

        self.assertEqual(context.skill_id, "restaurant-aircon-troubleshooting")

    def test_08_industrial_event_resolves_industrial_skill(self) -> None:
        resolver = DeterministicSkillResolver(
            (restaurant_definition(), industrial_definition())
        )

        context = resolver.resolve(
            synthetic_event(event_type="device_not_shutdown", asset_type="industrial_machine")
        )

        self.assertEqual(
            context.skill_id,
            "industrial-equipment-shutdown",
        )

    def test_09_unrelated_event_has_no_match(self) -> None:
        resolver = DeterministicSkillResolver((restaurant_definition(),))

        with self.assertRaisesRegex(
            SkillNotFoundError,
            "No active Skill",
        ) as caught:
            resolver.resolve(
                synthetic_event(event_type="unrelated_synthetic_event")
            )
        self.assertEqual(caught.exception.code, "skill_not_found")

    def test_10_deprecated_only_match_is_explicit(self) -> None:
        resolver = DeterministicSkillResolver(
            (
                restaurant_definition(
                    status=SkillStatus.DEPRECATED,
                ),
            )
        )

        with self.assertRaises(SkillNotFoundError) as caught:
            resolver.resolve(synthetic_event())
        self.assertEqual(
            caught.exception.code,
            "skill_deprecated_only",
        )

    def test_11_equal_specificity_is_a_conflict(self) -> None:
        resolver = DeterministicSkillResolver(
            (
                restaurant_definition(),
                restaurant_definition(
                    skill_id="restaurant-aircon-troubleshooting-secondary"
                ),
            )
        )

        with self.assertRaises(SkillConflictError) as caught:
            resolver.resolve(synthetic_event())
        self.assertEqual(
            caught.exception.code,
            "skill_resolution_conflict",
        )

    def test_12_definition_order_does_not_change_resolution(self) -> None:
        definitions = (restaurant_definition(), industrial_definition())
        event = synthetic_event(event_type="device_not_shutdown", asset_type="industrial_machine")

        first = DeterministicSkillResolver(definitions).resolve(event)
        second = DeterministicSkillResolver(
            tuple(reversed(definitions))
        ).resolve(event)

        self.assertEqual(first, second)

    def test_13_repeated_resolution_is_identical(self) -> None:
        resolver = DeterministicSkillResolver((restaurant_definition(),))
        event = synthetic_event()

        first = resolver.resolve(event)

        self.assertEqual(resolver.resolve(event), first)
        self.assertEqual(resolver.resolve(event), first)

    def test_14_missing_optional_asset_type_does_not_crash(self) -> None:
        event_only = restaurant_definition(
            supported_asset_types=(),
        )
        resolver = DeterministicSkillResolver((event_only,))

        context = resolver.resolve(synthetic_event(asset_type=None))

        self.assertEqual(context.skill_id, event_only.skill_id)
        self.assertEqual(
            context.resolution_reason,
            "matched:event_type;specificity=1",
        )

    def test_15_wrong_asset_type_does_not_select_skill(self) -> None:
        resolver = DeterministicSkillResolver((restaurant_definition(),))

        with self.assertRaises(SkillNotFoundError):
            resolver.resolve(
                synthetic_event(event_type="device_not_shutdown", asset_type="industrial_machine")
            )


class SkillAnalysisIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.runtime = AlphaNoahRuntime(str(root / "runtime.sqlite3"))
        self.repository = JsonKnowledgeRepository(root / "knowledge.json")
        self.repository.add_document(
            KnowledgeDocument(
                id="synthetic_skill_guidance_reference_v1",
                title="Synthetic closing guidance",
                content=(
                    "Synthetic closing checklist knowledge requiring "
                    "authorized human verification."
                ),
                document_type="RULE",
                source="synthetic_skill_guidance_reference",
                version="1.0-demo",
                effective_date="2026-07-26",
                metadata={"keywords": ["closing checklist"]},
            )
        )

    def create_event(
        self,
        *,
        asset_type: str = "air_conditioner",
    ) -> Event:
        return self.runtime.create_event(
            source="manual_report",
            actor="test:skill-guidance",
            event_type="equipment_fault_report",
            asset_id="SYNTHETIC-ASSET-001",
            location="Synthetic-Site",
            description="Synthetic device remained on.",
            metadata={
                "asset_type": asset_type,
                "data_classification": "Synthetic demo data",
            },
        )

    def provider(
        self,
        raw_provider: object,
        *,
        timeout_seconds: float = 1.0,
    ) -> ReliableAnalysisProvider:
        return ReliableAnalysisProvider(
            raw_provider,
            policy=ReliabilityPolicy(
                timeout_seconds=timeout_seconds,
                max_retry=0,
            ),
            context_builder=ContextBuilder(self.repository),
        )

    @staticmethod
    def resolver() -> DeterministicSkillResolver:
        return DeterministicSkillResolver((restaurant_definition(),))

    def test_16_skill_and_knowledge_contexts_enter_provider_explicitly(
        self,
    ) -> None:
        event = self.create_event()
        raw_provider = ContextCapturingProvider()

        decision, _ = self.runtime.analyze_event_with_provider(
            event.event_id,
            provider=self.provider(raw_provider),
            skill_resolver=self.resolver(),
        )

        self.assertTrue(decision.requires_human_review)
        self.assertEqual(raw_provider.calls, 1)
        self.assertEqual(
            raw_provider.skill_contexts[0].skill_id,
            "restaurant-aircon-troubleshooting",
        )
        self.assertEqual(
            [item.id for item in raw_provider.knowledge_contexts[0].documents],
            ["synthetic_skill_guidance_reference_v1"],
        )
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.PENDING_HUMAN_REVIEW,
        )

    def test_17_stub_skill_resolver_is_replaceable_and_audited(self) -> None:
        event = self.create_event()
        context = restaurant_definition().to_context(
            resolution_reason="matched:stub;specificity=1"
        )

        class StubResolver:
            def __init__(self) -> None:
                self.calls = 0

            def resolve(self, candidate: Event) -> SkillContext:
                self.calls += 1
                self.event = candidate
                return context

        resolver = StubResolver()
        raw_provider = ContextCapturingProvider()

        self.runtime.analyze_event_with_provider(
            event.event_id,
            provider=self.provider(raw_provider),
            skill_resolver=resolver,
        )

        self.assertEqual(resolver.calls, 1)
        decision_audit = next(
            record
            for record in self.runtime.store.list_audit(event.trace_id)
            if record.action == "decision_created"
        )
        metadata = decision_audit.details["model_metadata"]
        self.assertEqual(
            metadata["skill_id"],
            "restaurant-aircon-troubleshooting",
        )
        self.assertEqual(metadata["skill_version"], "1.0-demo")
        self.assertEqual(
            metadata["skill_resolution"],
            "matched:stub;specificity=1",
        )
        self.assertEqual(metadata["context_count"], 1)
        self.assertEqual(
            metadata["knowledge_sources"],
            ["synthetic_skill_guidance_reference@1.0-demo"],
        )

    def test_18_invalid_model_json_still_fails_safely(self) -> None:
        event = self.create_event()
        raw_provider = OllamaAnalysisProvider(
            base_url="http://127.0.0.1:11434",
            model="fixture-skill-model:v1",
        )
        invalid_envelope = json.dumps(
            {
                "model": "fixture-skill-model:v1",
                "response": "not-json",
                "done": True,
            }
        ).encode("utf-8")

        with patch.object(
            raw_provider,
            "_post_generate",
            return_value=invalid_envelope,
        ):
            with self.assertRaises(ProviderOutputError):
                self.runtime.analyze_event_with_provider(
                    event.event_id,
                    provider=self.provider(raw_provider),
                    skill_resolver=self.resolver(),
                )

        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.FAILED,
        )
        self.assertEqual(
            self.runtime.snapshot(event.event_id)["decisions"],
            [],
        )

    def test_19_skill_path_preserves_total_timeout(self) -> None:
        event = self.create_event()

        with self.assertRaises(ProviderTransportError) as caught:
            self.runtime.analyze_event_with_provider(
                event.event_id,
                provider=self.provider(
                    SlowSkillProvider(),
                    timeout_seconds=0.03,
                ),
                skill_resolver=self.resolver(),
            )

        self.assertEqual(caught.exception.code, "MODEL_TIMEOUT")
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.FAILED,
        )

    def test_20_no_skill_fails_explicitly_without_decision(self) -> None:
        event = self.create_event()
        resolver = DeterministicSkillResolver((industrial_definition(),))
        raw_provider = ContextCapturingProvider()

        with self.assertRaises(SkillNotFoundError) as caught:
            self.runtime.analyze_event_with_provider(
                event.event_id,
                provider=self.provider(raw_provider),
                skill_resolver=resolver,
            )

        self.assertEqual(caught.exception.code, "skill_not_found")
        self.assertEqual(raw_provider.calls, 0)
        self.assertEqual(
            self.runtime.store.get_event(event.event_id).status,
            EventStatus.FAILED,
        )
        self.assertEqual(
            self.runtime.snapshot(event.event_id)["decisions"],
            [],
        )
        failure_audit = next(
            record
            for record in self.runtime.store.list_audit(event.trace_id)
            if record.action == "skill_resolution_failed"
        )
        self.assertEqual(
            failure_audit.details["error_code"],
            "skill_not_found",
        )

    def test_21_ollama_prompt_has_separate_bounded_context_sections(
        self,
    ) -> None:
        event = self.create_event()
        skill_context = restaurant_definition().to_context(
            resolution_reason=(
                "matched:event_type,asset_type;specificity=2"
            )
        )
        knowledge_context = ContextBuilder(self.repository).build(
            event,
            skill_context=skill_context,
        )
        provider = OllamaAnalysisProvider(
            base_url="http://127.0.0.1:11434",
            model="fixture-skill-model:v1",
        )

        payload = json.loads(
            provider._build_request(
                event,
                knowledge_context,
                skill_context=skill_context,
            )
        )
        prompt = payload["prompt"]

        event_index = prompt.index("Incident Event:")
        skill_index = prompt.index("\nSkill Context (")
        knowledge_index = prompt.index("\nEnterprise Knowledge Context")
        output_index = prompt.index("Output JSON Schema:")
        self.assertLess(event_index, skill_index)
        self.assertLess(skill_index, knowledge_index)
        self.assertLess(knowledge_index, output_index)
        self.assertIn("restaurant-aircon-troubleshooting", prompt)
        self.assertIn("synthetic_skill_guidance_reference_v1", prompt)


class DemoSkillScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.runtime = AlphaNoahRuntime(str(root / "runtime.sqlite3"))
        self.repository = JsonKnowledgeRepository(
            REPOSITORY_ROOT / "examples" / "skill_demo_knowledge.json"
        )
        self.resolver = DeterministicSkillResolver(DEMO_SKILL_DEFINITIONS)
        self.raw_provider = ScenarioAwareFakeProvider()
        self.provider = ReliableAnalysisProvider(
            self.raw_provider,
            policy=ReliabilityPolicy(
                timeout_seconds=1.0,
                max_retry=0,
            ),
            context_builder=ContextBuilder(self.repository),
        )

    def create_event(self, asset_type: str) -> Event:
        return self.runtime.create_event(
            source="manual_report",
            actor="test:demo-skill-scenario",
            event_type=(
                "equipment_fault_report"
                if asset_type == "air_conditioner"
                else "device_not_shutdown"
            ),
            asset_id=f"SYNTHETIC-{asset_type.upper()}",
            location="Synthetic-Demo-Site",
            description="Synthetic equipment remained on after operation.",
            metadata={
                "asset_type": asset_type,
                "data_classification": "Synthetic demo data",
                "incident_notice": "Not a real production incident",
            },
        )

    def test_22_same_runtime_produces_two_controlled_scenarios(self) -> None:
        restaurant_event = self.create_event("air_conditioner")
        industrial_event = self.create_event("industrial_machine")

        restaurant_decision, _ = self.runtime.analyze_event_with_provider(
            restaurant_event.event_id,
            provider=self.provider,
            skill_resolver=self.resolver,
        )
        industrial_decision, _ = self.runtime.analyze_event_with_provider(
            industrial_event.event_id,
            provider=self.provider,
            skill_resolver=self.resolver,
        )

        self.assertIn(
            "air-conditioner troubleshooting",
            restaurant_decision.reasoning_summary,
        )
        self.assertIn(
            "residual-energy",
            industrial_decision.reasoning_summary,
        )
        self.assertNotEqual(
            restaurant_decision.reasoning_summary,
            industrial_decision.reasoning_summary,
        )
        self.assertEqual(
            [
                item.id
                for item in self.raw_provider.knowledge_contexts[0].documents
            ],
            ["synthetic_restaurant_aircon_troubleshooting_reference_v1"],
        )
        self.assertEqual(
            [
                item.id
                for item in self.raw_provider.knowledge_contexts[1].documents
            ],
            ["synthetic_industrial_equipment_shutdown_reference_v1"],
        )
        self.assertEqual(
            self.runtime.store.get_event(restaurant_event.event_id).status,
            EventStatus.PENDING_HUMAN_REVIEW,
        )
        self.assertEqual(
            self.runtime.store.get_event(industrial_event.event_id).status,
            EventStatus.PENDING_HUMAN_REVIEW,
        )

    def test_23_demo_skill_guidance_is_scenario_isolated(self) -> None:
        restaurant_text = json.dumps(
            RESTAURANT_AIRCON_TROUBLESHOOTING_SKILL.to_context(
                resolution_reason=(
                    "matched:event_type,asset_type;specificity=2"
                )
            ).to_prompt_payload(),
            ensure_ascii=False,
        ).casefold()
        industrial_text = json.dumps(
            INDUSTRIAL_EQUIPMENT_SHUTDOWN_SKILL.to_context(
                resolution_reason=(
                    "matched:event_type,asset_type;specificity=2"
                )
            ).to_prompt_payload(),
            ensure_ascii=False,
        ).casefold()

        self.assertNotIn("lockout/tagout", restaurant_text)
        self.assertNotIn("restaurant", industrial_text)
        self.assertNotIn("duty-staff", industrial_text)
        self.assertIn("safe fault triage", restaurant_text)
        self.assertIn("lockout/tagout", industrial_text)

    def test_24_skill_and_knowledge_audit_remain_traceable(self) -> None:
        event = self.create_event("industrial_machine")

        self.runtime.analyze_event_with_provider(
            event.event_id,
            provider=self.provider,
            skill_resolver=self.resolver,
        )

        decision_audit = next(
            record
            for record in self.runtime.store.list_audit(event.trace_id)
            if record.action == "decision_created"
        )
        metadata = decision_audit.details["model_metadata"]
        self.assertEqual(
            metadata["skill_id"],
            "industrial-equipment-shutdown",
        )
        self.assertEqual(metadata["skill_version"], "1.0-demo")
        self.assertEqual(metadata["context_count"], 1)
        self.assertEqual(
            metadata["knowledge_sources"],
            [
                "synthetic_industrial_equipment_shutdown_reference"
                "@1.0-demo"
            ],
        )

    def test_25_cli_demo_skill_flag_is_explicit_and_optional(self) -> None:
        parser = build_parser()
        without_skills = parser.parse_args(
            [
                "--db",
                "synthetic.sqlite3",
                "analyze",
                "event",
                "evt_synthetic",
                "--model",
                "fixture:model",
            ]
        )
        with_skills = parser.parse_args(
            [
                "--db",
                "synthetic.sqlite3",
                "analyze",
                "event",
                "evt_synthetic",
                "--model",
                "fixture:model",
                "--demo-skills",
            ]
        )

        self.assertFalse(without_skills.demo_skills)
        self.assertTrue(with_skills.demo_skills)

    def test_26_core_import_does_not_load_concrete_demo_modules(self) -> None:
        source_path = str(REPOSITORY_ROOT / "src")
        probe = (
            "import sys;"
            f"sys.path.insert(0, {source_path!r});"
            "import alphanoah_a1;"
            "forbidden=('alphanoah_a1.providers.ollama',"
            "'alphanoah_a1.skills.demo',"
            "'alphanoah_a1.knowledge.repository',"
            "'alphanoah_a1.knowledge.deterministic');"
            "loaded=[name for name in forbidden if name in sys.modules];"
            "print(','.join(loaded));"
            "raise SystemExit(1 if loaded else 0)"
        )

        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(
            completed.returncode,
            0,
            msg=completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
