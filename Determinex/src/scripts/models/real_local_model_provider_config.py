"""Real local-model provider config — the production save path.

Wraps the locked LocalModelConfigWizard with a deterministic on-disk
layout the IDE/Tauri layer actually uses. Save NEVER calls a live
model. Network providers are blocked. Stale and unpinned ids are
blocked. Default mode is dry-run.

The frontend's LocalModelSettingsPanel save flow is intended to route
to this module's ``save_config`` rather than the underlying wizard
directly — this layer pins the rung's exact status tokens and records
the real-config-path on disk.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .live_model_admission import _LOCAL_PROVIDERS, _NETWORK_PROVIDER_TOKENS
from .local_model_admission_policy import ModelProvider
from .local_model_config_record import LocalModelConfigRecord
from .local_model_config_wizard import LocalModelConfigWizard, WizardConfig
from .model_router import CURRENT_MODEL_IDS, STALE_MODEL_IDS, TaskClass
from .real_local_model_provider_config_record import (
    REAL_LOCAL_MODEL_PROVIDER_CONFIG_STATUS_TOKENS,
    RealLocalModelProviderConfigRecord,
)

# Stable on-disk root the IDE writes configs into. Kept inside the
# repo so the Tauri build and tests share one location. Absolute path
# is derived from this module so callers do not need a CWD assumption.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_ROOT = _REPO_ROOT / "assurance" / "runtime" / "local_model_configs"


def _local_decision(provider: str) -> str:
    if provider == ModelProvider.NO_MODEL.value:
        return "REAL_LOCAL_MODEL_CONFIG_DRY_RUN_DEFAULT"
    return "REAL_LOCAL_MODEL_CONFIG_SAVE_NO_LIVE_CALL"


def save_config(
    *,
    provider: str,
    model_id: str,
    digest: str = "",
    capabilities: Iterable[str] = (),
    task_classes_allowed: Iterable[str] = (
        TaskClass.BUILD_DIAGNOSIS.value,
        TaskClass.PATCH_GENERATION.value,
    ),
    enabled: bool = False,
    dry_run_default: bool = True,
    config_root: Path | None = None,
) -> RealLocalModelProviderConfigRecord:
    """Save a local-model config. Never calls a live model.

    Returns a record describing the decision (READY / DRY_RUN_DEFAULT /
    BLOCKED_*) and the resolved on-disk config path when written.
    """
    capabilities_t = tuple(c for c in capabilities if c)
    task_classes_t = tuple(t for t in task_classes_allowed if t)

    # 1. Network provider → hard block.
    if provider in _NETWORK_PROVIDER_TOKENS:
        return _blocked(
            provider,
            model_id,
            digest,
            capabilities_t,
            task_classes_t,
            "REAL_LOCAL_MODEL_CONFIG_BLOCKED_NETWORK_PROVIDER",
            f"provider {provider!r} is a network provider",
            network_provider_admitted=False,
        )

    # 2. Unknown provider.
    if provider not in _LOCAL_PROVIDERS:
        return _blocked(
            provider,
            model_id,
            digest,
            capabilities_t,
            task_classes_t,
            "REAL_LOCAL_MODEL_CONFIG_BLOCKED_UNKNOWN_PROVIDER",
            f"provider {provider!r} not recognized",
        )

    # 3. Stale id.
    if model_id and model_id in STALE_MODEL_IDS:
        return _blocked(
            provider,
            model_id,
            digest,
            capabilities_t,
            task_classes_t,
            "REAL_LOCAL_MODEL_CONFIG_BLOCKED_STALE_MODEL_ID",
            f"model_id {model_id!r} is stale",
        )

    # 4. Unpinned id (skip for no_model — id can be empty).
    if provider != ModelProvider.NO_MODEL.value and model_id not in CURRENT_MODEL_IDS:
        return _blocked(
            provider,
            model_id,
            digest,
            capabilities_t,
            task_classes_t,
            "REAL_LOCAL_MODEL_CONFIG_BLOCKED_UNPINNED_MODEL",
            f"model_id {model_id!r} not pinned in CURRENT_MODEL_IDS",
        )

    # 5. Delegate the actual disk write to the locked wizard.
    root = (config_root or DEFAULT_CONFIG_ROOT).resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _blocked(
            provider,
            model_id,
            digest,
            capabilities_t,
            task_classes_t,
            "REAL_LOCAL_MODEL_CONFIG_BLOCKED_INVALID_LOCATION",
            f"config_root not writable: {exc}",
        )

    wiz = LocalModelConfigWizard(WizardConfig(config_root=root))
    inner: LocalModelConfigRecord = wiz.write_config(
        provider=provider,
        model_id=model_id,
        model_digest_or_revision=digest,
        capabilities=capabilities_t,
        task_classes_allowed=task_classes_t,
        network_required=False,
        enabled=enabled,
        dry_run_default=dry_run_default,
    )

    # If the wizard refused for any reason, forward the refusal under
    # the rung's namespaced status tokens.
    if inner.is_blocked:
        # Map the wizard's namespaced decision to ours where the shape matches.
        mapping = {
            "LOCAL_MODEL_CONFIG_BLOCKED_NETWORK_PROVIDER": "REAL_LOCAL_MODEL_CONFIG_BLOCKED_NETWORK_PROVIDER",
            "LOCAL_MODEL_CONFIG_BLOCKED_UNKNOWN_PROVIDER": "REAL_LOCAL_MODEL_CONFIG_BLOCKED_UNKNOWN_PROVIDER",
            "LOCAL_MODEL_CONFIG_BLOCKED_STALE_MODEL_ID": "REAL_LOCAL_MODEL_CONFIG_BLOCKED_STALE_MODEL_ID",
            "LOCAL_MODEL_CONFIG_BLOCKED_UNPINNED_MODEL": "REAL_LOCAL_MODEL_CONFIG_BLOCKED_UNPINNED_MODEL",
            "LOCAL_MODEL_CONFIG_BLOCKED_INVALID_LOCATION": "REAL_LOCAL_MODEL_CONFIG_BLOCKED_INVALID_LOCATION",
        }
        return _blocked(
            provider,
            model_id,
            digest,
            capabilities_t,
            task_classes_t,
            mapping.get(inner.decision, "REAL_LOCAL_MODEL_CONFIG_BLOCKED_UNKNOWN_PROVIDER"),
            "; ".join(inner.notes) or inner.decision,
        )

    decision = _local_decision(provider)
    return RealLocalModelProviderConfigRecord(
        provider=provider,
        model_id=model_id,
        digest=digest,
        capabilities=capabilities_t,
        task_classes_allowed=task_classes_t,
        dry_run_default=dry_run_default,
        enabled=enabled,
        local_only=True,
        config_path=inner.config_path,
        decision=decision,
        live_model_called_on_save=False,
        network_provider_admitted=False,
        notes=(
            "save did not call a live model",
            "config written to disk only",
        ),
    )


def _blocked(
    provider: str,
    model_id: str,
    digest: str,
    capabilities: tuple[str, ...],
    task_classes: tuple[str, ...],
    decision: str,
    reason: str,
    *,
    network_provider_admitted: bool = False,
) -> RealLocalModelProviderConfigRecord:
    return RealLocalModelProviderConfigRecord(
        provider=provider,
        model_id=model_id,
        digest=digest,
        capabilities=capabilities,
        task_classes_allowed=task_classes,
        dry_run_default=True,
        enabled=False,
        local_only=True,
        config_path="",
        decision=decision,
        live_model_called_on_save=False,
        network_provider_admitted=network_provider_admitted,
        notes=(reason,),
    )


__all__ = [
    "save_config",
    "RealLocalModelProviderConfigRecord",
    "REAL_LOCAL_MODEL_PROVIDER_CONFIG_STATUS_TOKENS",
    "DEFAULT_CONFIG_ROOT",
]
