"""F03-D3 Web composition tests for the resolved Provider Runtime."""

from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from alphanoah_a1.golden_path import (  # noqa: E402
    SCENARIO_ID,
    RestaurantAirconFakeAnalysisProvider,
    build_restaurant_aircon_golden_path,
)
from alphanoah_a1.provider_config import (  # noqa: E402
    AIRuntimeConfig,
    ProviderKind,
    ProviderSettings,
    save_runtime_config,
)
from alphanoah_a1.provider_discovery import (  # noqa: E402
    DiscoveryStatus,
    ProviderDiscoveryResult,
)
from alphanoah_a1.provider_orchestration import (  # noqa: E402
    ProviderExecutionMode,
    ProviderHealthStatus,
    ProviderRuntimeOrchestrator,
    ProviderRuntimeStatus,
    ProviderSelectionSource,
    ResolvedProviderRuntime,
    StartupProviderOptions,
    UnavailableAnalysisProvider,
)
from alphanoah_a1.providers import (  # noqa: E402
    OllamaAnalysisProvider,
    OpenAICompatibleAnalysisProvider,
    ReadinessFakeAnalysisProvider,
)
from alphanoah_a1.web_api import build_parser, create_server  # noqa: E402


PUBLIC_RUNTIME_KEYS = {
    "version",
    "status",
    "provider",
    "model",
    "execution",
    "selection_source",
    "health",
}


class AvailableDiscovery:
    def __init__(
        self,
        overrides: dict[ProviderKind, DiscoveryStatus] | None = None,
    ):
        self.overrides = dict(overrides or {})
        self.calls = 0

    def discover(
        self,
        config: AIRuntimeConfig,
    ) -> tuple[ProviderDiscoveryResult, ...]:
        self.calls += 1
        return tuple(
            ProviderDiscoveryResult(
                kind=settings.kind,
                status=self.overrides.get(
                    settings.kind,
                    (
                        DiscoveryStatus.AVAILABLE
                        if (
                            settings.kind is ProviderKind.FAKE
                            or (
                                settings.enabled
                                and settings.endpoint
                                and settings.model
                            )
                        )
                        else DiscoveryStatus.NOT_CONFIGURED
                    ),
                ),
                configured_model=settings.model,
                available_models=(
                    (settings.model,) if settings.model else ()
                ),
                endpoint=settings.endpoint,
                detail="Synthetic Web composition boundary.",
                configured_model_digest=settings.model_digest,
                discovered_model_digest=settings.model_digest,
            )
            for settings in config.providers
        )


@contextmanager
def serving(server: object) -> Iterator[int]:
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
) -> tuple[int, object]:
    body = (
        None
        if payload is None
        else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )
    headers = {"Content-Type": "application/json"} if body else {}
    connection = http.client.HTTPConnection(
        "127.0.0.1",
        port,
        timeout=3,
    )
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        encoded = response.read()
        return response.status, json.loads(encoded)
    finally:
        connection.close()


def activation_payload() -> dict[str, object]:
    return {
        "scenario_id": SCENARIO_ID,
        "description": "Synthetic provider-unconfigured activation.",
        "request_id": "f03-d3-unconfigured-001",
    }


def runtime_failure(
    status: ProviderRuntimeStatus,
    health: ProviderHealthStatus,
    *,
    kind: ProviderKind | None = None,
    source: ProviderSelectionSource = ProviderSelectionSource.NONE,
) -> ResolvedProviderRuntime:
    return ResolvedProviderRuntime(
        provider_instance=None,
        provider_type=kind,
        model="safe-model" if kind is not None else None,
        execution_mode=(
            ProviderExecutionMode.LOCAL
            if kind is not None
            else ProviderExecutionMode.NONE
        ),
        selection_source=source,
        health_status=health,
        status=status,
        diagnostic_code="private diagnostic must remain internal",
    )


class ProviderWebCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.database = self.directory / "runtime.sqlite3"
        self.config_path = self.directory / "ai_runtime_config.json"

    @staticmethod
    def raw_provider(server: object) -> object:
        return server.adapter.application.provider.provider

    def test_web_cli_exposes_all_provider_startup_options(self) -> None:
        cases = (
            ("fake", ProviderKind.FAKE),
            ("ollama", ProviderKind.OLLAMA),
            ("vllm", ProviderKind.VLLM),
            ("openai-compatible", ProviderKind.OPENAI_COMPATIBLE),
        )
        for value, expected in cases:
            with self.subTest(provider=value):
                args = build_parser().parse_args(
                    [
                        "--config",
                        str(self.config_path),
                        "--provider",
                        value,
                        "--model",
                        "safe-model",
                        "--base-url",
                        "http://127.0.0.1:8000/v1",
                        "--timeout-seconds",
                        "120",
                        "--model-digest",
                        "a" * 64,
                        "--credential-env",
                        "ALPHANOAH_TEST_PROVIDER_KEY",
                        "--discovery-timeout",
                        "3",
                    ]
                )
                self.assertEqual(args.provider, expected)
                self.assertEqual(args.timeout_seconds, 120.0)
                self.assertEqual(args.discovery_timeout, 3.0)

    def test_explicit_fake_injects_factory_fake_not_restaurant_fake(
        self,
    ) -> None:
        save_runtime_config(
            self.config_path,
            AIRuntimeConfig(
                providers=(ProviderSettings(kind=ProviderKind.FAKE),)
            ),
        )
        server = create_server(
            self.database,
            port=0,
            config_path=self.config_path,
            startup_options=StartupProviderOptions(
                provider=ProviderKind.FAKE
            ),
            orchestrator=ProviderRuntimeOrchestrator(
                environment={},
                discovery=AvailableDiscovery(),
            ),
        )
        self.addCleanup(server.server_close)

        provider = self.raw_provider(server)

        self.assertIsInstance(provider, ReadinessFakeAnalysisProvider)
        self.assertNotIsInstance(
            provider,
            RestaurantAirconFakeAnalysisProvider,
        )
        self.assertIs(provider, server.provider_runtime.provider_instance)
        self.assertEqual(
            server.provider_runtime.selection_source,
            ProviderSelectionSource.COMMAND_LINE,
        )
        self.assertTrue(server.provider_runtime.ready)
        with serving(server) as port:
            status, payload = request(
                port,
                "POST",
                "/api/demo/events",
                {
                    **activation_payload(),
                    "request_id": "f03-d3-explicit-fake-001",
                },
            )
        self.assertEqual(status, 201)
        self.assertEqual(
            payload["event"]["status"],
            "PENDING_HUMAN_REVIEW",
        )
        self.assertIsNotNone(payload["analysis"])
        self.assertIsNotNone(payload["human_review"])

    def test_saved_selection_changes_the_web_runtime_provider(self) -> None:
        save_runtime_config(
            self.config_path,
            AIRuntimeConfig(
                providers=(
                    ProviderSettings(kind=ProviderKind.FAKE),
                    ProviderSettings(
                        kind=ProviderKind.VLLM,
                        endpoint="http://127.0.0.1:8000/v1",
                        model="saved-web-model",
                    ),
                ),
                selected=ProviderKind.VLLM,
            ),
        )
        server = create_server(
            self.database,
            port=0,
            config_path=self.config_path,
            orchestrator=ProviderRuntimeOrchestrator(
                environment={},
                discovery=AvailableDiscovery(),
            ),
        )
        self.addCleanup(server.server_close)

        provider = self.raw_provider(server)

        self.assertIsInstance(provider, OpenAICompatibleAnalysisProvider)
        self.assertEqual(provider.provider_id, "vllm:saved-web-model")
        self.assertIs(provider, server.provider_runtime.provider_instance)
        self.assertEqual(
            server.provider_runtime.selection_source,
            ProviderSelectionSource.SAVED_CONFIG,
        )
        self.assertNotIsInstance(
            provider,
            RestaurantAirconFakeAnalysisProvider,
        )

    def test_web_constructs_each_real_provider_kind_through_factory(
        self,
    ) -> None:
        cases = (
            (
                ProviderSettings(
                    kind=ProviderKind.OLLAMA,
                    endpoint="http://127.0.0.1:11434",
                    model="ollama-web-model",
                ),
                {},
                OllamaAnalysisProvider,
                "ollama:ollama-web-model",
            ),
            (
                ProviderSettings(
                    kind=ProviderKind.VLLM,
                    endpoint="http://127.0.0.1:8000/v1",
                    model="vllm-web-model",
                ),
                {},
                OpenAICompatibleAnalysisProvider,
                "vllm:vllm-web-model",
            ),
            (
                ProviderSettings(
                    kind=ProviderKind.OPENAI_COMPATIBLE,
                    endpoint="https://models.example.test/v1",
                    model="compatible-web-model",
                    api_key_env="ALPHANOAH_TEST_PROVIDER_KEY",
                ),
                {
                    "ALPHANOAH_TEST_PROVIDER_KEY":
                        "synthetic-private-credential"
                },
                OpenAICompatibleAnalysisProvider,
                "openai_compatible:compatible-web-model",
            ),
        )

        for index, (settings, environment, expected_type, provider_id) in (
            enumerate(cases)
        ):
            with self.subTest(kind=settings.kind):
                config_path = self.directory / f"provider-{index}.json"
                database = self.directory / f"provider-{index}.sqlite3"
                save_runtime_config(
                    config_path,
                    AIRuntimeConfig(
                        providers=(settings,),
                        selected=settings.kind,
                    ),
                )
                server = create_server(
                    database,
                    port=0,
                    config_path=config_path,
                    orchestrator=ProviderRuntimeOrchestrator(
                        environment=environment,
                        discovery=AvailableDiscovery(),
                    ),
                )
                try:
                    provider = self.raw_provider(server)
                    self.assertIsInstance(provider, expected_type)
                    self.assertEqual(provider.provider_id, provider_id)
                    self.assertIs(
                        provider,
                        server.provider_runtime.provider_instance,
                    )
                    self.assertTrue(server.provider_runtime.ready)
                finally:
                    server.server_close()

    def test_default_without_selection_is_not_restaurant_fake(self) -> None:
        missing_config = self.directory / "does-not-exist.json"
        discovery = AvailableDiscovery()

        server = create_server(
            self.database,
            port=0,
            config_path=missing_config,
            orchestrator=ProviderRuntimeOrchestrator(
                environment={},
                discovery=discovery,
            ),
        )
        self.addCleanup(server.server_close)
        provider = self.raw_provider(server)

        self.assertEqual(discovery.calls, 1)
        self.assertEqual(
            server.provider_runtime.status,
            ProviderRuntimeStatus.UNCONFIGURED,
        )
        self.assertIsInstance(provider, UnavailableAnalysisProvider)
        self.assertNotIsInstance(
            provider,
            RestaurantAirconFakeAnalysisProvider,
        )

    def test_runtime_endpoint_projects_ready_unconfigured_and_unavailable(
        self,
    ) -> None:
        ready = ResolvedProviderRuntime(
            provider_instance=ReadinessFakeAnalysisProvider(),
            provider_type=ProviderKind.FAKE,
            model=None,
            execution_mode=ProviderExecutionMode.DEMO,
            selection_source=ProviderSelectionSource.COMMAND_LINE,
            health_status=ProviderHealthStatus.SYNTHETIC,
            status=ProviderRuntimeStatus.READY,
        )
        cases = (
            (ready, "ready"),
            (
                runtime_failure(
                    ProviderRuntimeStatus.UNCONFIGURED,
                    ProviderHealthStatus.NOT_CONFIGURED,
                ),
                "unconfigured",
            ),
            (
                runtime_failure(
                    ProviderRuntimeStatus.UNAVAILABLE,
                    ProviderHealthStatus.UNAVAILABLE,
                    kind=ProviderKind.OLLAMA,
                    source=ProviderSelectionSource.SAVED_CONFIG,
                ),
                "unavailable",
            ),
        )

        for index, (provider_runtime, expected_status) in enumerate(cases):
            with self.subTest(status=expected_status):
                server = create_server(
                    self.directory / f"status-{index}.sqlite3",
                    port=0,
                    provider_runtime=provider_runtime,
                )
                with serving(server) as port:
                    status, payload = request(port, "GET", "/api/runtime")

                self.assertEqual(status, 200)
                self.assertEqual(set(payload), PUBLIC_RUNTIME_KEYS)
                self.assertEqual(payload["status"], expected_status)
                rendered = json.dumps(payload)
                for forbidden in (
                    "credential",
                    "endpoint",
                    "Traceback",
                    str(self.directory),
                    "diagnostic",
                ):
                    self.assertNotIn(forbidden, rendered)

    def test_unconfigured_activation_returns_503_without_creating_event(
        self,
    ) -> None:
        provider_runtime = runtime_failure(
            ProviderRuntimeStatus.UNCONFIGURED,
            ProviderHealthStatus.NOT_CONFIGURED,
        )
        server = create_server(
            self.database,
            port=0,
            provider_runtime=provider_runtime,
        )

        with serving(server) as port:
            status, payload = request(
                port,
                "POST",
                "/api/demo/events",
                activation_payload(),
            )

        self.assertEqual(status, 503)
        self.assertEqual(payload["error_code"], "PROVIDER_UNAVAILABLE")
        self.assertNotIn("Traceback", json.dumps(payload))
        self.assertEqual(
            server.adapter.application.runtime.store.list_events(),
            [],
        )

    def test_injected_application_cannot_publish_arbitrary_model_text(
        self,
    ) -> None:
        class PrivateTextProvider(ReadinessFakeAnalysisProvider):
            provider_id = "ollama:C:\\private\\credential.txt"
            model = "sk-private-value"

        application = build_restaurant_aircon_golden_path(
            self.database,
            raw_provider=PrivateTextProvider(),
        )
        server = create_server(
            self.database,
            port=0,
            application=application,
        )

        with serving(server) as port:
            status, payload = request(port, "GET", "/api/runtime")

        self.assertEqual(status, 200)
        self.assertEqual(payload["provider"], "ollama")
        self.assertIsNone(payload["model"])
        rendered = json.dumps(payload)
        self.assertNotIn("private", rendered)
        self.assertNotIn("credential", rendered)

    def test_application_and_runtime_status_must_use_same_provider(
        self,
    ) -> None:
        application = build_restaurant_aircon_golden_path(self.database)
        reported_provider = ReadinessFakeAnalysisProvider()
        reported = ResolvedProviderRuntime(
            provider_instance=reported_provider,
            provider_type=ProviderKind.FAKE,
            model=None,
            execution_mode=ProviderExecutionMode.DEMO,
            selection_source=ProviderSelectionSource.COMMAND_LINE,
            health_status=ProviderHealthStatus.SYNTHETIC,
            status=ProviderRuntimeStatus.READY,
        )

        with self.assertRaisesRegex(
            ValueError,
            "application Provider and provider_runtime must match",
        ):
            create_server(
                self.database,
                port=0,
                application=application,
                provider_runtime=reported,
            )


if __name__ == "__main__":
    unittest.main()
