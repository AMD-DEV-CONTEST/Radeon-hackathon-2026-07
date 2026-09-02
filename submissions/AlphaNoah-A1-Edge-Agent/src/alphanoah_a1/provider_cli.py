"""CLI composition for provider discovery and stateless readiness checks."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .exceptions import AnalysisProviderError
from .knowledge.models import KnowledgeContext
from .models import Event, EventStatus
from .provider_config import (
    DEFAULT_CONFIG_FILENAME,
    ProviderKind,
    load_runtime_config,
    save_runtime_config,
)
from .provider_discovery import (
    ProviderDiscovery,
    ProviderSelectionError,
    ProviderSelector,
)
from .provider_orchestration import (
    ProviderRuntimeOrchestrator,
    StartupProviderOptions,
)
from .provider_runtime import (
    ProviderFactoryError,
    ProviderSmokeTester,
)
from .skill import SkillContext

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AI_RUNTIME_CONFIG = REPOSITORY_ROOT / DEFAULT_CONFIG_FILENAME


def _safe_discovery_payload(result: object) -> dict[str, Any]:
    return {
        "provider": result.kind.value,
        "status": result.status.value,
        "endpoint": result.endpoint,
        "configured_model": result.configured_model,
        "configured_model_digest": result.configured_model_digest,
        "discovered_model_digest": result.discovered_model_digest,
        "available_models": list(result.available_models),
        "detail": result.detail,
    }


def run_provider_management(args: argparse.Namespace) -> int:
    """Discover or persist one explicit provider selection."""

    try:
        config = load_runtime_config(args.config)
        results = ProviderDiscovery(
            timeout_seconds=args.discovery_timeout,
        ).discover(config)
        if args.provider_command == "discover":
            print(
                json.dumps(
                    {
                        "config": args.config.name,
                        "providers": [
                            _safe_discovery_payload(item) for item in results
                        ],
                        "mutated": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        selection = ProviderSelector().select(
            config,
            results,
            explicit=args.name,
        )
        save_runtime_config(
            args.config,
            config.with_selected(selection.kind),
        )
        print(
            json.dumps(
                {
                    "selected_provider": selection.kind.value,
                    "selection_source": selection.source,
                    "config": args.config.name,
                    "credentials_persisted": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except OSError:
        print(
            "Provider operation failed: local configuration could not be "
            "read or written.",
            file=sys.stderr,
        )
        return 1
    except (ValueError, ProviderSelectionError) as exc:
        print(f"Provider operation failed: {exc}", file=sys.stderr)
        return 1


def run_doctor(args: argparse.Namespace) -> int:
    """Report provider readiness and optionally run a stateless smoke check."""

    try:
        resolved = ProviderRuntimeOrchestrator(
            discovery_timeout_seconds=args.discovery_timeout,
        ).resolve(
            args.config,
            options=StartupProviderOptions(
                provider=args.provider,
                model=args.model,
                base_url=args.base_url,
                timeout_seconds=args.analysis_timeout,
                model_digest=args.model_digest,
                credential_env=args.credential_env,
            ),
        )
        results = resolved.discovery
        payload: dict[str, Any] = {
            "readiness": (
                "READY_SYNTHETIC"
                if (
                    resolved.ready
                    and resolved.provider_type is ProviderKind.FAKE
                )
                else resolved.status.value.upper()
            ),
            "selected_provider": (
                resolved.provider_type.value
                if resolved.provider_type is not None
                else None
            ),
            "selection_source": resolved.selection_source.value,
            "discovery": [
                _safe_discovery_payload(item) for item in results
            ],
            "smoke_test": "NOT_RUN",
            "runtime_state_changed": False,
            "credentials_exposed": False,
        }
        if not resolved.ready:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 1
        if args.smoke:
            event = Event(
                event_id="evt_synthetic_provider_doctor",
                source="synthetic_doctor",
                timestamp=datetime.now(UTC).isoformat(),
                raw_input_ref="synthetic:provider-doctor",
                normalized_input={},
                detected_issue="",
                confidence=0.0,
                severity="UNKNOWN",
                status=EventStatus.NEW,
                trace_id="trc_synthetic_provider_doctor",
                event_type="provider_readiness_check",
                description=(
                    "Synthetic provider readiness input; not a real incident."
                ),
                metadata={
                    "data_notice": "Synthetic demo data",
                    "incident_notice": "Not a real production incident",
                },
            )
            skill_context = SkillContext(
                skill_id="provider-readiness",
                skill_version="1.0",
                analysis_instructions=(
                    "Validate the provider interface without diagnosis."
                ),
                escalation_rules=("Always require human review.",),
                knowledge_query_hints=(),
                resolution_reason="Explicit synthetic doctor context.",
            )
            smoke = ProviderSmokeTester().run(
                resolved.provider_instance,
                event,
                skill_context,
                KnowledgeContext(),
            )
            payload["smoke_test"] = smoke.validation_status
            payload["smoke_provider_id"] = smoke.provider_id
            payload["runtime_state_changed"] = smoke.runtime_state_changed
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except OSError:
        print(
            "AI runtime doctor failed (readiness): a local resource was "
            "unavailable.",
            file=sys.stderr,
        )
        return 1
    except (
        AnalysisProviderError,
        ProviderFactoryError,
        ProviderSelectionError,
        TypeError,
        ValueError,
    ) as exc:
        failure_type = getattr(exc, "failure_type", "readiness")
        print(
            f"AI runtime doctor failed ({failure_type}): {exc}",
            file=sys.stderr,
        )
        return 1


def add_provider_commands(
    commands: Any,
) -> None:
    """Add Task 05B commands without changing existing command behavior."""

    provider_parser = commands.add_parser(
        "provider",
        help="Discover or select an AI runtime provider.",
    )
    provider_parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_AI_RUNTIME_CONFIG,
    )
    provider_parser.add_argument(
        "--discovery-timeout",
        type=float,
        default=2.0,
    )
    provider_commands = provider_parser.add_subparsers(
        dest="provider_command",
        required=True,
    )
    provider_commands.add_parser(
        "discover",
        help="Probe configured providers without changing configuration.",
    )
    select_parser = provider_commands.add_parser(
        "select",
        help="Persist one available explicit provider selection.",
    )
    select_parser.add_argument(
        "name",
        choices=tuple(item.value for item in ProviderKind),
    )
    doctor_parser = commands.add_parser(
        "doctor",
        help="Check AI runtime composition without changing Runtime state.",
    )
    doctor_parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_AI_RUNTIME_CONFIG,
    )
    doctor_parser.add_argument(
        "--provider",
        choices=tuple(item.value for item in ProviderKind),
        help="Explicit provider; unavailable selections fail without fallback.",
    )
    doctor_parser.add_argument(
        "--discovery-timeout",
        type=float,
        default=2.0,
    )
    doctor_parser.add_argument(
        "--analysis-timeout",
        type=float,
        help=(
            "Explicit Provider timeout override; saved setting is used when "
            "omitted."
        ),
    )
    doctor_parser.add_argument("--model")
    doctor_parser.add_argument("--base-url")
    doctor_parser.add_argument("--model-digest")
    doctor_parser.add_argument(
        "--credential-env",
        help="Environment variable name containing the Provider credential.",
    )
    doctor_parser.add_argument(
        "--smoke",
        action="store_true",
        help=(
            "Call Provider -> AnalysisResultGuard using synthetic in-memory "
            "input; no Event or Decision is persisted."
        ),
    )
