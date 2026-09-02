"""F03-D3 Provider Runtime orchestration contract tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

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
    ENV_BASE_URL,
    ENV_MODEL,
    ENV_PROVIDER,
    ProviderExecutionMode,
    ProviderHealthStatus,
    ProviderRuntimeOrchestrator,
    ProviderRuntimeStatus,
    ProviderSelectionSource,
    ResolvedProviderRuntime,
    StartupProviderOptions,
)
from alphanoah_a1.provider_runtime import (  # noqa: E402
    AnalysisProviderFactory,
    ProviderFactoryError,
)
from alphanoah_a1.providers import (  # noqa: E402
    OllamaAnalysisProvider,
    ReadinessFakeAnalysisProvider,
)


PUBLIC_RUNTIME_KEYS = {
    "version",
    "status",
    "provider",
    "model",
    "execution",
    "selection_source",
    "health",
}


def runtime_config(
    *providers: ProviderSettings,
    selected: ProviderKind | None = None,
) -> AIRuntimeConfig:
    return AIRuntimeConfig(providers=providers, selected=selected)


class AvailableDiscovery:
    """Return deterministic discovery facts while recording every recheck."""

    def __init__(
        self,
        overrides: dict[ProviderKind, DiscoveryStatus] | None = None,
    ):
        self.overrides = dict(overrides or {})
        self.calls: list[AIRuntimeConfig] = []

    def discover(
        self,
        config: AIRuntimeConfig,
    ) -> tuple[ProviderDiscoveryResult, ...]:
        self.calls.append(config)
        results: list[ProviderDiscoveryResult] = []
        for settings in config.providers:
            status = self.overrides.get(settings.kind)
            if status is None:
                if not settings.enabled:
                    status = DiscoveryStatus.DISABLED
                elif settings.kind is ProviderKind.FAKE:
                    status = DiscoveryStatus.AVAILABLE
                elif not settings.endpoint or not settings.model:
                    status = DiscoveryStatus.NOT_CONFIGURED
                else:
                    status = DiscoveryStatus.AVAILABLE
            results.append(
                ProviderDiscoveryResult(
                    kind=settings.kind,
                    status=status,
                    configured_model=settings.model,
                    available_models=(
                        (settings.model,)
                        if settings.model
                        and status is DiscoveryStatus.AVAILABLE
                        else ()
                    ),
                    endpoint=settings.endpoint,
                    detail="Synthetic orchestration boundary.",
                    configured_model_digest=settings.model_digest,
                    discovered_model_digest=settings.model_digest,
                )
            )
        return tuple(results)


class SequenceDiscovery:
    """Return a new status for one selected provider on each resolve."""

    def __init__(
        self,
        kind: ProviderKind,
        statuses: tuple[DiscoveryStatus, ...],
    ):
        self.kind = kind
        self.statuses = statuses
        self.calls = 0

    def discover(
        self,
        config: AIRuntimeConfig,
    ) -> tuple[ProviderDiscoveryResult, ...]:
        index = min(self.calls, len(self.statuses) - 1)
        selected_status = self.statuses[index]
        self.calls += 1
        return tuple(
            ProviderDiscoveryResult(
                kind=settings.kind,
                status=(
                    selected_status
                    if settings.kind is self.kind
                    else DiscoveryStatus.AVAILABLE
                ),
                configured_model=settings.model,
                available_models=(
                    (settings.model,)
                    if settings.model
                    and (
                        settings.kind is not self.kind
                        or selected_status is DiscoveryStatus.AVAILABLE
                    )
                    else ()
                ),
                endpoint=settings.endpoint,
                detail="Synthetic revalidation boundary.",
            )
            for settings in config.providers
        )


class FailingFactory:
    def __init__(self):
        self.calls = 0

    def create(self, config: AIRuntimeConfig, kind: ProviderKind) -> object:
        self.calls += 1
        raise ProviderFactoryError("Synthetic construction failure.")


class RaisingDiscovery:
    def __init__(self, error: Exception):
        self.error = error

    def discover(self, config: AIRuntimeConfig) -> object:
        raise self.error


class ProviderRuntimeOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.config_path = self.directory / "ai_runtime_config.json"

    def save(self, config: AIRuntimeConfig) -> None:
        save_runtime_config(self.config_path, config)

    def test_command_line_precedes_environment_and_saved_selection(
        self,
    ) -> None:
        self.save(
            runtime_config(
                ProviderSettings(
                    kind=ProviderKind.OLLAMA,
                    endpoint="http://127.0.0.1:11434",
                    model="saved-ollama",
                ),
                ProviderSettings(
                    kind=ProviderKind.VLLM,
                    endpoint="http://127.0.0.1:8000/v1",
                    model="saved-vllm",
                ),
                selected=ProviderKind.VLLM,
            )
        )
        discovery = AvailableDiscovery()
        orchestrator = ProviderRuntimeOrchestrator(
            environment={
                ENV_PROVIDER: ProviderKind.OLLAMA.value,
                ENV_MODEL: "environment-model",
                ENV_BASE_URL: "http://127.0.0.1:11435",
            },
            discovery=discovery,
        )

        resolved = orchestrator.resolve(
            self.config_path,
            options=StartupProviderOptions(
                provider=ProviderKind.OLLAMA,
                model="command-model",
                base_url="http://127.0.0.1:11436",
            ),
        )

        self.assertTrue(resolved.ready)
        self.assertEqual(
            resolved.selection_source,
            ProviderSelectionSource.COMMAND_LINE,
        )
        self.assertEqual(resolved.provider_type, ProviderKind.OLLAMA)
        self.assertEqual(resolved.model, "command-model")
        self.assertIsInstance(
            resolved.provider_instance,
            OllamaAnalysisProvider,
        )
        self.assertEqual(
            resolved.provider_instance.base_url,
            "http://127.0.0.1:11436",
        )
        checked = discovery.calls[0].get(ProviderKind.OLLAMA)
        self.assertIsNotNone(checked)
        self.assertEqual(checked.model, "command-model")

    def test_environment_precedes_saved_selection(self) -> None:
        self.save(
            runtime_config(
                ProviderSettings(
                    kind=ProviderKind.OLLAMA,
                    endpoint="http://127.0.0.1:11434",
                    model="saved-ollama",
                ),
                ProviderSettings(
                    kind=ProviderKind.VLLM,
                    endpoint="http://127.0.0.1:8000/v1",
                    model="saved-vllm",
                ),
                selected=ProviderKind.VLLM,
            )
        )
        resolved = ProviderRuntimeOrchestrator(
            environment={
                ENV_PROVIDER: ProviderKind.OLLAMA.value,
                ENV_MODEL: "environment-model",
                ENV_BASE_URL: "http://127.0.0.1:11435",
            },
            discovery=AvailableDiscovery(),
        ).resolve(self.config_path)

        self.assertTrue(resolved.ready)
        self.assertEqual(
            resolved.selection_source,
            ProviderSelectionSource.ENVIRONMENT,
        )
        self.assertEqual(resolved.provider_type, ProviderKind.OLLAMA)
        self.assertEqual(resolved.model, "environment-model")
        self.assertEqual(
            resolved.provider_instance.base_url,
            "http://127.0.0.1:11435",
        )

    def test_command_field_overrides_keep_saved_selection_source(self) -> None:
        self.save(
            runtime_config(
                ProviderSettings(
                    kind=ProviderKind.OLLAMA,
                    endpoint="http://127.0.0.1:11434",
                    model="saved-ollama",
                    timeout_seconds=60,
                ),
                selected=ProviderKind.OLLAMA,
            )
        )

        resolved = ProviderRuntimeOrchestrator(
            environment={},
            discovery=AvailableDiscovery(),
        ).resolve(
            self.config_path,
            options=StartupProviderOptions(timeout_seconds=120),
        )

        self.assertTrue(resolved.ready)
        self.assertEqual(
            resolved.selection_source,
            ProviderSelectionSource.SAVED_CONFIG,
        )
        self.assertEqual(
            resolved.provider_instance.total_timeout_seconds,
            120,
        )

    def test_saved_selection_is_revalidated_on_every_resolve(self) -> None:
        self.save(
            runtime_config(
                ProviderSettings(
                    kind=ProviderKind.VLLM,
                    endpoint="http://127.0.0.1:8000/v1",
                    model="saved-model",
                ),
                selected=ProviderKind.VLLM,
            )
        )
        discovery = SequenceDiscovery(
            ProviderKind.VLLM,
            (
                DiscoveryStatus.AVAILABLE,
                DiscoveryStatus.UNAVAILABLE,
            ),
        )
        orchestrator = ProviderRuntimeOrchestrator(
            environment={},
            discovery=discovery,
        )

        first = orchestrator.resolve(self.config_path)
        second = orchestrator.resolve(self.config_path)

        self.assertTrue(first.ready)
        self.assertEqual(
            first.selection_source,
            ProviderSelectionSource.SAVED_CONFIG,
        )
        self.assertEqual(second.status, ProviderRuntimeStatus.UNAVAILABLE)
        self.assertIsNone(second.provider_instance)
        self.assertEqual(discovery.calls, 2)

    def test_available_candidates_never_trigger_automatic_selection(
        self,
    ) -> None:
        configurations = (
            runtime_config(ProviderSettings(kind=ProviderKind.FAKE)),
            runtime_config(
                ProviderSettings(
                    kind=ProviderKind.OLLAMA,
                    endpoint="http://127.0.0.1:11434",
                    model="candidate-a",
                ),
                ProviderSettings(
                    kind=ProviderKind.VLLM,
                    endpoint="http://127.0.0.1:8000/v1",
                    model="candidate-b",
                ),
                ProviderSettings(kind=ProviderKind.FAKE),
            ),
        )
        for index, config in enumerate(configurations):
            with self.subTest(candidate_count=len(config.providers)):
                path = self.directory / f"unselected-{index}.json"
                save_runtime_config(path, config)
                resolved = ProviderRuntimeOrchestrator(
                    environment={},
                    discovery=AvailableDiscovery(),
                ).resolve(path)

                self.assertEqual(
                    resolved.status,
                    ProviderRuntimeStatus.UNCONFIGURED,
                )
                self.assertEqual(
                    resolved.selection_source,
                    ProviderSelectionSource.NONE,
                )
                self.assertIsNone(resolved.provider_type)
                self.assertIsNone(resolved.provider_instance)
                self.assertTrue(resolved.discovery)
                self.assertTrue(
                    any(item.available for item in resolved.discovery)
                )

    def test_fake_requires_explicit_or_saved_selection_and_is_synthetic(
        self,
    ) -> None:
        unselected = runtime_config(
            ProviderSettings(kind=ProviderKind.FAKE)
        )
        self.save(unselected)
        orchestrator = ProviderRuntimeOrchestrator(
            environment={},
            discovery=AvailableDiscovery(),
        )

        automatic = orchestrator.resolve(self.config_path)
        explicit = orchestrator.resolve(
            self.config_path,
            options=StartupProviderOptions(provider=ProviderKind.FAKE),
        )
        self.save(
            runtime_config(
                ProviderSettings(kind=ProviderKind.FAKE),
                selected=ProviderKind.FAKE,
            )
        )
        saved = orchestrator.resolve(self.config_path)

        self.assertEqual(
            automatic.status,
            ProviderRuntimeStatus.UNCONFIGURED,
        )
        for resolved, source in (
            (explicit, ProviderSelectionSource.COMMAND_LINE),
            (saved, ProviderSelectionSource.SAVED_CONFIG),
        ):
            with self.subTest(source=source):
                self.assertTrue(resolved.ready)
                self.assertIsInstance(
                    resolved.provider_instance,
                    ReadinessFakeAnalysisProvider,
                )
                self.assertEqual(
                    resolved.execution_mode,
                    ProviderExecutionMode.DEMO,
                )
                self.assertEqual(
                    resolved.health_status,
                    ProviderHealthStatus.SYNTHETIC,
                )
                self.assertEqual(resolved.selection_source, source)

    def test_explicit_or_saved_unavailable_never_falls_back_to_fake(
        self,
    ) -> None:
        base = runtime_config(
            ProviderSettings(
                kind=ProviderKind.OLLAMA,
                endpoint="http://127.0.0.1:11434",
                model="required-model",
            ),
            ProviderSettings(kind=ProviderKind.FAKE),
        )
        discovery = AvailableDiscovery(
            {ProviderKind.OLLAMA: DiscoveryStatus.UNAVAILABLE}
        )
        cases = (
            (
                base,
                StartupProviderOptions(provider=ProviderKind.OLLAMA),
                ProviderSelectionSource.COMMAND_LINE,
            ),
            (
                runtime_config(
                    *base.providers,
                    selected=ProviderKind.OLLAMA,
                ),
                None,
                ProviderSelectionSource.SAVED_CONFIG,
            ),
        )

        for index, (config, options, source) in enumerate(cases):
            with self.subTest(source=source):
                path = self.directory / f"unavailable-{index}.json"
                save_runtime_config(path, config)
                resolved = ProviderRuntimeOrchestrator(
                    environment={},
                    discovery=discovery,
                ).resolve(path, options=options)

                self.assertEqual(
                    resolved.status,
                    ProviderRuntimeStatus.UNAVAILABLE,
                )
                self.assertEqual(resolved.provider_type, ProviderKind.OLLAMA)
                self.assertEqual(resolved.selection_source, source)
                self.assertIsNone(resolved.provider_instance)
                self.assertTrue(
                    next(
                        item
                        for item in resolved.discovery
                        if item.kind is ProviderKind.FAKE
                    ).available
                )

    def test_invalid_configuration_fails_closed(self) -> None:
        self.config_path.write_text(
            '{"schema_version":"wrong","providers":{}}',
            encoding="utf-8",
        )

        resolved = ProviderRuntimeOrchestrator(
            environment={},
            discovery=AvailableDiscovery(),
        ).resolve(self.config_path)

        self.assertEqual(
            resolved.status,
            ProviderRuntimeStatus.INVALID_CONFIGURATION,
        )
        self.assertEqual(
            resolved.health_status,
            ProviderHealthStatus.INVALID_CONFIGURATION,
        )
        self.assertEqual(
            resolved.diagnostic_code,
            "invalid_provider_configuration",
        )
        self.assertIsNone(resolved.provider_instance)

    def test_factory_construction_failure_has_safe_status(self) -> None:
        self.save(
            runtime_config(
                ProviderSettings(
                    kind=ProviderKind.VLLM,
                    endpoint="http://127.0.0.1:8000/v1",
                    model="construction-model",
                ),
                selected=ProviderKind.VLLM,
            )
        )
        factory = FailingFactory()

        resolved = ProviderRuntimeOrchestrator(
            environment={},
            discovery=AvailableDiscovery(),
            factory=factory,
        ).resolve(self.config_path)

        self.assertEqual(factory.calls, 1)
        self.assertEqual(
            resolved.status,
            ProviderRuntimeStatus.INVALID_CONFIGURATION,
        )
        self.assertEqual(
            resolved.health_status,
            ProviderHealthStatus.INVALID_CONFIGURATION,
        )
        self.assertEqual(
            resolved.diagnostic_code,
            "provider_construction_failed",
        )
        self.assertIsNone(resolved.provider_instance)

    def test_discovery_transport_and_internal_failures_are_distinct(
        self,
    ) -> None:
        self.save(
            runtime_config(
                ProviderSettings(
                    kind=ProviderKind.OLLAMA,
                    endpoint="http://127.0.0.1:11434",
                    model="failure-model",
                ),
                selected=ProviderKind.OLLAMA,
            )
        )
        cases = (
            (
                OSError("private transport detail"),
                ProviderRuntimeStatus.UNAVAILABLE,
                ProviderHealthStatus.UNAVAILABLE,
                "provider_discovery_failed",
            ),
            (
                RuntimeError("private implementation detail"),
                ProviderRuntimeStatus.DEGRADED,
                ProviderHealthStatus.DEGRADED,
                "provider_discovery_internal_error",
            ),
        )

        for error, expected_status, expected_health, code in cases:
            with self.subTest(error=type(error).__name__):
                resolved = ProviderRuntimeOrchestrator(
                    environment={},
                    discovery=RaisingDiscovery(error),
                ).resolve(self.config_path)

                self.assertEqual(resolved.status, expected_status)
                self.assertEqual(resolved.health_status, expected_health)
                self.assertEqual(resolved.diagnostic_code, code)
                self.assertIsNone(resolved.provider_instance)
                self.assertNotIn(
                    "private",
                    json.dumps(resolved.to_public_dict()),
                )

    def test_public_runtime_contract_is_exact_and_never_leaks_details(
        self,
    ) -> None:
        credential = "synthetic-private-credential"
        endpoint = "https://models.example.test/private"
        local_path = "C:\\Users\\private\\ai_runtime_config.json"
        traceback = "Traceback (most recent call last): private failure"
        resolved = ResolvedProviderRuntime(
            provider_instance=None,
            provider_type=ProviderKind.OPENAI_COMPATIBLE,
            model="public-model",
            execution_mode=ProviderExecutionMode.REMOTE,
            selection_source=ProviderSelectionSource.SAVED_CONFIG,
            health_status=ProviderHealthStatus.UNAVAILABLE,
            status=ProviderRuntimeStatus.UNAVAILABLE,
            discovery=(
                ProviderDiscoveryResult(
                    kind=ProviderKind.OPENAI_COMPATIBLE,
                    status=DiscoveryStatus.UNAVAILABLE,
                    configured_model="public-model",
                    endpoint=endpoint,
                    detail=f"{credential} {local_path} {traceback}",
                ),
            ),
            diagnostic_code=f"{credential}:{local_path}:{traceback}",
        )

        public = resolved.to_public_dict()
        rendered = json.dumps(public)

        self.assertEqual(set(public), PUBLIC_RUNTIME_KEYS)
        self.assertEqual(
            public,
            {
                "version": "runtime-status-v1",
                "status": "unavailable",
                "provider": "openai_compatible",
                "model": "public-model",
                "execution": "remote",
                "selection_source": "saved_config",
                "health": "unavailable",
            },
        )
        for forbidden in (
            credential,
            endpoint,
            local_path,
            "Traceback",
            "credential",
            "endpoint",
            "diagnostic_code",
            "discovery",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, rendered)

    def test_secret_shaped_model_is_rejected_or_redacted(self) -> None:
        secret_shaped = "sk-privatecredential12345678"
        with self.assertRaisesRegex(ValueError, "model is invalid"):
            ProviderSettings(
                kind=ProviderKind.VLLM,
                endpoint="http://127.0.0.1:8000/v1",
                model=secret_shaped,
            )

        manually_constructed = ResolvedProviderRuntime(
            provider_instance=None,
            provider_type=ProviderKind.VLLM,
            model=secret_shaped,
            execution_mode=ProviderExecutionMode.LOCAL,
            selection_source=ProviderSelectionSource.SAVED_CONFIG,
            health_status=ProviderHealthStatus.UNAVAILABLE,
            status=ProviderRuntimeStatus.UNAVAILABLE,
        )
        public = manually_constructed.to_public_dict()
        self.assertIsNone(public["model"])
        self.assertNotIn(secret_shaped, json.dumps(public))


if __name__ == "__main__":
    unittest.main()
