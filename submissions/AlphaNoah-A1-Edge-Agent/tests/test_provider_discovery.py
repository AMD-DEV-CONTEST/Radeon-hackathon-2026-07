"""Task 05B provider discovery, selection, construction, and smoke tests."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from alphanoah_a1.demo import build_parser, run_doctor  # noqa: E402
from alphanoah_a1.ai_reliability import (  # noqa: E402
    ModelFailureCode,
    ReliabilityPolicy,
    ReliableAnalysisProvider,
)
from alphanoah_a1.exceptions import ProviderTransportError  # noqa: E402
from alphanoah_a1.knowledge.models import KnowledgeContext  # noqa: E402
from alphanoah_a1.models import Event, EventStatus  # noqa: E402
from alphanoah_a1.provider_config import (  # noqa: E402
    AIRuntimeConfig,
    ProviderKind,
    ProviderSettings,
    RuntimeSelectionMode,
    load_runtime_config,
    save_runtime_config,
)
from alphanoah_a1.provider_discovery import (  # noqa: E402
    DiscoveryHTTPError,
    DiscoveryStatus,
    ProviderDiscovery,
    ProviderDiscoveryResult,
    ProviderSelectionError,
    ProviderSelector,
)
from alphanoah_a1.provider_runtime import (  # noqa: E402
    AnalysisProviderFactory,
    ProviderFactoryError,
    ProviderSmokeTester,
)
from alphanoah_a1.providers import (  # noqa: E402
    OllamaAnalysisProvider,
    OpenAICompatibleAnalysisProvider,
    ReadinessFakeAnalysisProvider,
)
from alphanoah_a1.providers.base import (  # noqa: E402
    analysis_system_instructions,
)
from alphanoah_a1.skill import SkillContext  # noqa: E402


def provider_config(*providers: ProviderSettings, **kwargs: Any):
    return AIRuntimeConfig(providers=providers, **kwargs)


def synthetic_event() -> Event:
    return Event(
        event_id="evt_provider_test",
        source="synthetic_test",
        timestamp="2026-07-28T00:00:00+00:00",
        raw_input_ref="synthetic:test",
        normalized_input={},
        detected_issue="",
        confidence=0.0,
        severity="UNKNOWN",
        status=EventStatus.NEW,
        trace_id="trc_provider_test",
        event_type="provider_readiness_check",
        description="Synthetic provider readiness test.",
    )


def skill_context() -> SkillContext:
    return SkillContext(
        skill_id="provider-readiness",
        skill_version="1.0",
        analysis_instructions="Validate only the provider interface.",
        escalation_rules=("Human review remains mandatory.",),
        knowledge_query_hints=(),
        resolution_reason="Explicit synthetic test context.",
    )


def valid_model_output() -> dict[str, Any]:
    return {
        "issue_summary": "检测到合成设备异常。",
        "possible_causes": ["可能存在一项待核实的合成原因。"],
        "recommended_actions": ["请授权人员进行人工复核。"],
        "severity": "low",
        "confidence": 0.2,
        "evidence_used": ["合成测试输入"],
        "limitations": ["尚未进行现场检查。"],
        "requires_human_review": True,
    }


class RecordingTransport:
    def __init__(self, responses: Mapping[str, object]):
        self.responses = dict(responses)
        self.requests: list[dict[str, object]] = []

    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> object:
        self.requests.append(
            {
                "url": url,
                "headers": dict(headers),
                "timeout_seconds": timeout_seconds,
                "max_response_bytes": max_response_bytes,
            }
        )
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class AuthenticationFailureProvider:
    provider_id = "openai_compatible:synthetic"
    model = "synthetic"
    calls = 0

    def analyze(self, event: object) -> object:
        self.calls += 1
        raise ProviderTransportError(
            "Synthetic credential rejection.",
            code="authentication_error",
        )


@contextmanager
def openai_server(
    output: Mapping[str, Any],
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    requests: list[dict[str, Any]] = []
    response_body = json.dumps(
        {
            "choices": [
                {"message": {"role": "assistant", "content": json.dumps(output)}}
            ]
        }
    ).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            content_length = int(self.headers.get("Content-Length", "0"))
            requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": json.loads(self.rfile.read(content_length)),
                }
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class ProviderDiscoveryTests(unittest.TestCase):
    def test_01_ollama_discovery_requires_configured_model(self) -> None:
        digest = "a" * 64
        transport = RecordingTransport(
            {
                "http://127.0.0.1:11434/api/tags": {
                    "models": [
                        {
                            "name": "qwen:test",
                            "digest": f"sha256:{digest}",
                        }
                    ]
                }
            }
        )
        config = provider_config(
            ProviderSettings(
                kind=ProviderKind.OLLAMA,
                endpoint="http://127.0.0.1:11434",
                model="qwen:test",
                model_digest=digest.upper(),
            )
        )

        result = ProviderDiscovery(transport=transport).discover(config)[0]

        self.assertEqual(result.status, DiscoveryStatus.AVAILABLE)
        self.assertEqual(result.available_models, ("qwen:test",))
        self.assertEqual(result.configured_model_digest, digest)
        self.assertEqual(result.discovered_model_digest, digest)
        self.assertEqual(transport.requests[0]["headers"], {
            "Accept": "application/json"
        })

    def test_02_unavailable_provider_is_reported_without_mutation(self) -> None:
        transport = RecordingTransport(
            {"http://127.0.0.1:11434/api/tags": OSError("offline")}
        )
        settings = ProviderSettings(
            kind=ProviderKind.OLLAMA,
            endpoint="http://127.0.0.1:11434",
            model="qwen:test",
        )

        result = ProviderDiscovery(transport=transport).probe(settings)

        self.assertEqual(result.status, DiscoveryStatus.UNAVAILABLE)
        self.assertNotIn("offline", result.detail)

    def test_03_vllm_models_endpoint_is_detected(self) -> None:
        url = "http://127.0.0.1:8000/v1/models"
        transport = RecordingTransport(
            {url: {"object": "list", "data": [{"id": "local-model"}]}}
        )
        settings = ProviderSettings(
            kind=ProviderKind.VLLM,
            endpoint="http://127.0.0.1:8000/v1",
            model="local-model",
        )

        result = ProviderDiscovery(transport=transport).probe(settings)

        self.assertTrue(result.available)
        self.assertEqual(transport.requests[0]["url"], url)

    def test_04_remote_key_is_environment_only_and_never_in_result(self) -> None:
        url = "https://models.example.test/v1/models"
        transport = RecordingTransport(
            {url: {"data": [{"id": "reviewed-model"}]}}
        )
        settings = ProviderSettings(
            kind=ProviderKind.OPENAI_COMPATIBLE,
            endpoint="https://models.example.test/v1",
            model="reviewed-model",
            api_key_env="ALPHANOAH_TEST_API_KEY",
        )
        secret = "test-secret-must-not-leak"
        discovery = ProviderDiscovery(
            transport=transport,
            environment={"ALPHANOAH_TEST_API_KEY": secret},
        )

        result = discovery.probe(settings)

        self.assertTrue(result.available)
        self.assertEqual(
            transport.requests[0]["headers"]["Authorization"],
            f"Bearer {secret}",
        )
        self.assertNotIn(secret, repr(result))

        missing = ProviderDiscovery(
            transport=transport,
            environment={},
        ).probe(settings)
        self.assertEqual(
            missing.status,
            DiscoveryStatus.CREDENTIAL_MISSING,
        )
        self.assertEqual(len(transport.requests), 1)

    def test_05_discovery_never_selects_single_multiple_or_fake_candidates(
        self,
    ) -> None:
        config = provider_config(
            ProviderSettings(kind=ProviderKind.FAKE),
            ProviderSettings(
                kind=ProviderKind.VLLM,
                endpoint="http://127.0.0.1:8000/v1",
                model="model-v",
            ),
            ProviderSettings(
                kind=ProviderKind.OLLAMA,
                endpoint="http://127.0.0.1:11434",
                model="model-o",
            ),
        )
        results = (
            ProviderDiscoveryResult(
                ProviderKind.FAKE, DiscoveryStatus.AVAILABLE
            ),
            ProviderDiscoveryResult(
                ProviderKind.VLLM, DiscoveryStatus.AVAILABLE
            ),
            ProviderDiscoveryResult(
                ProviderKind.OLLAMA, DiscoveryStatus.AVAILABLE
            ),
        )

        candidate_sets = (
            results,
            (results[2],),
            (results[0],),
        )
        for candidates in candidate_sets:
            with self.subTest(candidates=candidates):
                with self.assertRaisesRegex(
                    ProviderSelectionError,
                    "explicit or saved",
                ):
                    ProviderSelector().select(config, candidates)

    def test_06_explicit_or_saved_unavailable_never_silently_falls_back(
        self,
    ) -> None:
        config = provider_config(
            ProviderSettings(
                kind=ProviderKind.OLLAMA,
                endpoint="http://127.0.0.1:11434",
                model="missing",
            ),
            ProviderSettings(kind=ProviderKind.FAKE),
            selected=ProviderKind.OLLAMA,
        )
        results = (
            ProviderDiscoveryResult(
                ProviderKind.OLLAMA,
                DiscoveryStatus.UNAVAILABLE,
            ),
            ProviderDiscoveryResult(
                ProviderKind.FAKE,
                DiscoveryStatus.AVAILABLE,
            ),
        )
        for explicit in (None, ProviderKind.OLLAMA):
            with self.subTest(explicit=explicit):
                with self.assertRaisesRegex(
                    ProviderSelectionError,
                    "no fallback",
                ):
                    ProviderSelector().select(
                        config,
                        results,
                        explicit=explicit,
                    )

    def test_07_manual_mode_requires_selection(self) -> None:
        config = provider_config(
            ProviderSettings(kind=ProviderKind.FAKE),
            mode=RuntimeSelectionMode.MANUAL,
        )
        with self.assertRaises(ProviderSelectionError):
            ProviderSelector().select(
                config,
                (
                    ProviderDiscoveryResult(
                        ProviderKind.FAKE,
                        DiscoveryStatus.AVAILABLE,
                    ),
                ),
            )

    def test_08_config_round_trip_persists_no_secret_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_runtime_config.json"
            digest = "a" * 64
            config = provider_config(
                ProviderSettings(
                    kind=ProviderKind.OLLAMA,
                    endpoint="http://127.0.0.1:11434",
                    model="qwen:test",
                    timeout_seconds=125,
                    model_digest=digest.upper(),
                ),
                ProviderSettings(
                    kind=ProviderKind.OPENAI_COMPATIBLE,
                    endpoint="https://models.example.test/v1",
                    model="reviewed-model",
                    api_key_env="ALPHANOAH_TEST_API_KEY",
                    timeout_seconds=45,
                ),
                selected=ProviderKind.OPENAI_COMPATIBLE,
            )
            save_runtime_config(path, config)

            encoded = path.read_text(encoding="utf-8")
            loaded = load_runtime_config(path)

        self.assertEqual(loaded, config)
        self.assertIn("ALPHANOAH_TEST_API_KEY", encoded)
        self.assertIn('"timeout_seconds": 125.0', encoded)
        self.assertIn(digest, encoded)
        self.assertNotIn("test-secret-must-not-leak", encoded)

    def test_09_factory_requires_credentials_and_builds_fake(self) -> None:
        remote = provider_config(
            ProviderSettings(
                kind=ProviderKind.OPENAI_COMPATIBLE,
                endpoint="https://models.example.test/v1",
                model="reviewed-model",
                api_key_env="ALPHANOAH_TEST_API_KEY",
            )
        )
        with self.assertRaises(ProviderFactoryError):
            AnalysisProviderFactory(environment={}).create(
                remote,
                ProviderKind.OPENAI_COMPATIBLE,
            )
        fake = AnalysisProviderFactory().create(
            provider_config(ProviderSettings(kind=ProviderKind.FAKE)),
            ProviderKind.FAKE,
        )
        self.assertIsInstance(fake, ReadinessFakeAnalysisProvider)
        vllm = AnalysisProviderFactory().create(
            provider_config(
                ProviderSettings(
                    kind=ProviderKind.VLLM,
                    endpoint="http://127.0.0.1:8000/v1",
                    model="fixture-model",
                )
            ),
            ProviderKind.VLLM,
        )
        self.assertIsInstance(vllm, OpenAICompatibleAnalysisProvider)
        self.assertEqual(vllm.provider_id, "vllm:fixture-model")

    def test_10_openai_compatible_adapter_is_bounded_and_guard_compatible(
        self,
    ) -> None:
        secret = "temporary-test-key"
        event = synthetic_event()
        event.attachments = [
            "safe_ref_001",
            "C:\\private\\attachment.txt",
        ]
        event.metadata = {"private_note": "must-not-enter-prompt"}
        with openai_server(valid_model_output()) as (endpoint, requests):
            provider = OpenAICompatibleAnalysisProvider(
                endpoint=endpoint,
                model="fixture-model",
                provider_kind=ProviderKind.VLLM,
                api_key=secret,
                timeout_seconds=2,
            )
            result = provider.analyze_with_contexts(
                event,
                skill_context(),
                KnowledgeContext(),
            )

        self.assertEqual(requests[0]["path"], "/v1/chat/completions")
        self.assertEqual(
            requests[0]["authorization"], f"Bearer {secret}"
        )
        self.assertNotIn(secret, repr(provider))
        self.assertTrue(result.requires_human_review)
        self.assertEqual(result.model_or_rule, "vllm:fixture-model")
        self.assertNotIn(secret, json.dumps(result.to_dict()))
        request_text = json.dumps(requests[0]["body"])
        self.assertNotIn(secret, request_text)
        self.assertNotIn("private", request_text)
        self.assertIn("safe_ref_001", request_text)
        self.assertEqual(
            requests[0]["body"]["messages"][0]["content"],
            analysis_system_instructions(),
        )
        self.assertEqual(
            json.loads(requests[0]["body"]["messages"][1]["content"])[
                "output_schema"
            ]["properties"]["severity"]["enum"],
            ["critical", "high", "low", "medium"],
        )

    def test_11_smoke_check_does_not_create_runtime_state(self) -> None:
        smoke = ProviderSmokeTester().run(
            ReadinessFakeAnalysisProvider(),
            synthetic_event(),
            skill_context(),
            KnowledgeContext(),
        )

        self.assertEqual(smoke.validation_status, "VALID")
        self.assertFalse(smoke.runtime_state_changed)
        self.assertEqual(
            smoke.result.decision_type,
            "synthetic_readiness_check",
        )
        self.assertEqual(
            smoke.result.detected_issue,
            "检测到事件 provider_readiness_check 的合成就绪性结果",
        )
        self.assertIn("未进行设备诊断", smoke.result.reasoning_summary)
        self.assertEqual(smoke.result.severity, "LOW")

    def test_12_doctor_fake_smoke_is_offline_and_state_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "ai_runtime_config.json"
            save_runtime_config(
                config_path,
                provider_config(
                    ProviderSettings(kind=ProviderKind.FAKE),
                    selected=ProviderKind.FAKE,
                ),
            )
            args = build_parser().parse_args(
                [
                    "doctor",
                    "--config",
                    str(config_path),
                    "--provider",
                    "fake",
                    "--smoke",
                ]
            )
            output = io.StringIO()
            errors = io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                exit_code = run_doctor(args)

            generated_files = sorted(
                item.name for item in Path(directory).iterdir()
            )

        self.assertEqual(exit_code, 0, errors.getvalue())
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["readiness"], "READY_SYNTHETIC")
        self.assertEqual(payload["smoke_test"], "VALID")
        self.assertFalse(payload["runtime_state_changed"])
        self.assertEqual(generated_files, ["ai_runtime_config.json"])

    def test_13_unconfigured_model_is_discovered_but_not_selected(
        self,
    ) -> None:
        transport = RecordingTransport(
            {
                "http://127.0.0.1:11434/api/tags": {
                    "models": [{"model": "available-but-not-selected"}]
                }
            }
        )
        settings = ProviderSettings(
            kind=ProviderKind.OLLAMA,
            endpoint="http://127.0.0.1:11434",
        )

        result = ProviderDiscovery(transport=transport).probe(settings)

        self.assertEqual(result.status, DiscoveryStatus.NOT_CONFIGURED)
        self.assertEqual(
            result.available_models,
            ("available-but-not-selected",),
        )
        self.assertFalse(result.available)

    def test_14_explicit_and_saved_available_selection_are_honored(
        self,
    ) -> None:
        config = provider_config(
            ProviderSettings(kind=ProviderKind.FAKE),
            ProviderSettings(
                kind=ProviderKind.VLLM,
                endpoint="http://127.0.0.1:8000/v1",
                model="fixture-model",
            ),
            selected=ProviderKind.FAKE,
        )
        results = (
            ProviderDiscoveryResult(
                ProviderKind.FAKE,
                DiscoveryStatus.AVAILABLE,
            ),
            ProviderDiscoveryResult(
                ProviderKind.VLLM,
                DiscoveryStatus.AVAILABLE,
            ),
        )

        saved = ProviderSelector().select(config, results)
        explicit = ProviderSelector().select(
            config,
            results,
            explicit=ProviderKind.VLLM,
        )

        self.assertEqual(saved.kind, ProviderKind.FAKE)
        self.assertEqual(saved.source, "saved")
        self.assertEqual(explicit.kind, ProviderKind.VLLM)
        self.assertEqual(explicit.source, "explicit")

    def test_15_rejected_api_credential_is_classified_without_body(
        self,
    ) -> None:
        url = "https://models.example.test/v1/models"
        transport = RecordingTransport(
            {url: DiscoveryHTTPError(401)}
        )
        settings = ProviderSettings(
            kind=ProviderKind.OPENAI_COMPATIBLE,
            endpoint="https://models.example.test/v1",
            model="reviewed-model",
            api_key_env="ALPHANOAH_TEST_API_KEY",
        )

        result = ProviderDiscovery(
            transport=transport,
            environment={"ALPHANOAH_TEST_API_KEY": "rejected-secret"},
        ).probe(settings)

        self.assertEqual(
            result.status,
            DiscoveryStatus.CREDENTIAL_REJECTED,
        )
        self.assertNotIn("rejected-secret", repr(result))

    def test_16_configured_missing_model_is_rejected(self) -> None:
        transport = RecordingTransport(
            {
                "http://127.0.0.1:11434/api/tags": {
                    "models": [{"name": "available-model"}]
                }
            }
        )
        result = ProviderDiscovery(transport=transport).probe(
            ProviderSettings(
                kind=ProviderKind.OLLAMA,
                endpoint="http://127.0.0.1:11434",
                model="requested-model",
            )
        )

        self.assertEqual(result.status, DiscoveryStatus.MODEL_MISSING)
        self.assertFalse(result.available)
        self.assertEqual(result.available_models, ("available-model",))

    def test_17_authentication_failure_is_non_retryable_and_classified(
        self,
    ) -> None:
        raw_provider = AuthenticationFailureProvider()
        provider = ReliableAnalysisProvider(
            raw_provider,
            policy=ReliabilityPolicy(timeout_seconds=1, max_retry=3),
        )

        with self.assertRaises(ProviderTransportError) as context:
            provider.analyze(synthetic_event())

        self.assertEqual(
            context.exception.code,
            ModelFailureCode.MODEL_AUTHENTICATION_ERROR.value,
        )
        self.assertEqual(raw_provider.calls, 1)
        self.assertEqual(
            provider.get_audit_metadata()["model_failure_code"],
            ModelFailureCode.MODEL_AUTHENTICATION_ERROR.value,
        )

    def test_18_ollama_digest_mismatch_or_absence_fails_discovery(
        self,
    ) -> None:
        configured_digest = "a" * 64
        settings = ProviderSettings(
            kind=ProviderKind.OLLAMA,
            endpoint="http://127.0.0.1:11434",
            model="qwen:test",
            model_digest=configured_digest,
        )
        url = "http://127.0.0.1:11434/api/tags"
        for reported_digest in ("b" * 64, None):
            with self.subTest(reported_digest=reported_digest):
                model: dict[str, object] = {"name": "qwen:test"}
                if reported_digest is not None:
                    model["digest"] = f"sha256:{reported_digest}"
                result = ProviderDiscovery(
                    transport=RecordingTransport(
                        {url: {"models": [model]}}
                    )
                ).probe(settings)

                self.assertEqual(
                    result.status,
                    DiscoveryStatus.MODEL_DIGEST_MISMATCH,
                )
                self.assertFalse(result.available)
                self.assertEqual(
                    result.configured_model_digest,
                    configured_digest,
                )
                self.assertEqual(
                    result.discovered_model_digest,
                    reported_digest,
                )
                self.assertNotIn(configured_digest, result.detail)
                if reported_digest is not None:
                    self.assertNotIn(reported_digest, result.detail)

    def test_19_config_strictly_validates_timeout_and_digest(self) -> None:
        digest = "A" * 64
        settings = ProviderSettings(
            kind=ProviderKind.OLLAMA,
            endpoint="http://127.0.0.1:11434",
            model="qwen:test",
            timeout_seconds=120,
            model_digest=digest,
        )
        self.assertEqual(settings.timeout_seconds, 120.0)
        self.assertEqual(settings.model_digest, digest.lower())
        encoded = provider_config(settings).to_dict()
        self.assertEqual(
            encoded["providers"]["ollama"]["timeout_seconds"],
            120.0,
        )
        self.assertEqual(
            encoded["providers"]["ollama"]["model_digest"],
            digest.lower(),
        )

        for invalid_timeout in (True, 0, -1, float("inf"), 1801):
            with self.subTest(invalid_timeout=invalid_timeout):
                with self.assertRaisesRegex(ValueError, "timeout_seconds"):
                    ProviderSettings(
                        kind=ProviderKind.OLLAMA,
                        timeout_seconds=invalid_timeout,
                    )
        for invalid_digest in ("", "abc", "g" * 64):
            with self.subTest(invalid_digest=invalid_digest):
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    ProviderSettings(
                        kind=ProviderKind.OLLAMA,
                        model_digest=invalid_digest,
                    )
        with self.assertRaisesRegex(ValueError, "only for ollama"):
            ProviderSettings(
                kind=ProviderKind.VLLM,
                model_digest="a" * 64,
            )
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            AIRuntimeConfig.from_dict(
                {
                    "schema_version": "ai-runtime-config-v1",
                    "providers": {
                        "fake": {
                            "enabled": True,
                            "unexpected": "rejected",
                        }
                    },
                }
            )

    def test_20_factory_builds_all_kinds_from_settings_and_fails_safe(
        self,
    ) -> None:
        digest = "c" * 64
        environment = {"ALPHANOAH_TEST_API_KEY": "temporary-test-key"}
        factory = AnalysisProviderFactory(environment=environment)

        fake = factory.create(
            provider_config(ProviderSettings(kind=ProviderKind.FAKE)),
            ProviderKind.FAKE,
        )
        self.assertIsInstance(fake, ReadinessFakeAnalysisProvider)

        ollama = factory.create(
            provider_config(
                ProviderSettings(
                    kind=ProviderKind.OLLAMA,
                    endpoint="http://127.0.0.1:11434",
                    model="qwen:test",
                    timeout_seconds=17,
                    model_digest=digest,
                )
            ),
            ProviderKind.OLLAMA,
        )
        self.assertIsInstance(ollama, OllamaAnalysisProvider)
        self.assertEqual(ollama.total_timeout_seconds, 17.0)
        self.assertEqual(ollama.model_digest, digest)

        vllm = factory.create(
            provider_config(
                ProviderSettings(
                    kind=ProviderKind.VLLM,
                    endpoint="http://127.0.0.1:8000/v1",
                    model="fixture-model",
                    timeout_seconds=18,
                )
            ),
            ProviderKind.VLLM,
        )
        self.assertIsInstance(vllm, OpenAICompatibleAnalysisProvider)
        self.assertEqual(vllm.provider_kind, ProviderKind.VLLM)
        self.assertEqual(vllm.timeout_seconds, 18.0)

        compatible = factory.create(
            provider_config(
                ProviderSettings(
                    kind=ProviderKind.OPENAI_COMPATIBLE,
                    endpoint="https://models.example.test/v1",
                    model="reviewed-model",
                    api_key_env="ALPHANOAH_TEST_API_KEY",
                    timeout_seconds=19,
                )
            ),
            ProviderKind.OPENAI_COMPATIBLE,
        )
        self.assertIsInstance(
            compatible,
            OpenAICompatibleAnalysisProvider,
        )
        self.assertEqual(
            compatible.provider_kind,
            ProviderKind.OPENAI_COMPATIBLE,
        )
        self.assertEqual(compatible.timeout_seconds, 19.0)
        self.assertNotIn("temporary-test-key", repr(compatible))

        missing_reference = provider_config(
            ProviderSettings(
                kind=ProviderKind.OPENAI_COMPATIBLE,
                endpoint="https://models.example.test/v1",
                model="reviewed-model",
            )
        )
        with self.assertRaisesRegex(
            ProviderFactoryError,
            "credential environment variable reference",
        ):
            factory.create(
                missing_reference,
                ProviderKind.OPENAI_COMPATIBLE,
            )
        for settings, expected in (
            (
                ProviderSettings(
                    kind=ProviderKind.VLLM,
                    model="fixture-model",
                ),
                "endpoint",
            ),
            (
                ProviderSettings(
                    kind=ProviderKind.VLLM,
                    endpoint="http://127.0.0.1:8000/v1",
                ),
                "model",
            ),
        ):
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(
                    ProviderFactoryError,
                    expected,
                ):
                    factory.create(
                        provider_config(settings),
                        ProviderKind.VLLM,
                    )
        with self.assertRaisesRegex(ProviderFactoryError, "kind is invalid"):
            factory.create(
                provider_config(ProviderSettings(kind=ProviderKind.FAKE)),
                "unknown",
            )


if __name__ == "__main__":
    unittest.main()
