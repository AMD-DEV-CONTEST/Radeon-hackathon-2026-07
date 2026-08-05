"""Bounded local provider smoke test.

Verifies provider availability via the existing compat harness +
fixture providers. Output is always captured as untrusted. No source
input. No patch generation. No corpus write. No training eligibility.
"""

from __future__ import annotations

from .live_model_admission import _NETWORK_PROVIDER_TOKENS
from .live_model_compat_harness import (
    FixtureProvider,
    LiveModelCompatHarness,
)
from .local_model_config_record import LocalModelConfigRecord
from .local_provider_smoke_record import (
    LOCAL_PROVIDER_SMOKE_STATUS_TOKENS,
    LocalProviderSmokeRecord,
)


class LocalProviderSmokeTest:
    """Stateless smoke runner."""

    def __init__(self, harness: LiveModelCompatHarness | None = None) -> None:
        self._harness = harness or LiveModelCompatHarness()

    def run(
        self,
        config: LocalModelConfigRecord,
        provider: FixtureProvider,
        *,
        schema_id: str = "diagnose_v1",
    ) -> LocalProviderSmokeRecord:
        # 1. Config must be written/admitted.
        if config is None or not config.config_path:
            return self._blocked(
                "LOCAL_PROVIDER_SMOKE_BLOCKED_NOT_CONFIGURED",
                config_path="",
                provider=getattr(provider, "name", ""),
                model_id=getattr(provider, "model_id", ""),
                note="config is None or missing config_path",
            )

        # 2. Network provider refused outright.
        if config.provider in _NETWORK_PROVIDER_TOKENS or config.network_required:
            return self._blocked(
                "LOCAL_PROVIDER_SMOKE_BLOCKED_NETWORK_PROVIDER",
                config_path=config.config_path,
                provider=config.provider,
                model_id=config.model_id,
                note="network provider rejected",
            )

        # 3. Exercise harness against the fixture provider.
        resp = self._harness.invoke(
            provider,
            task_class="VERIFIER_SUMMARY",
            schema_id="verifier_v1",
            payload={"probe": "smoke"},
        )

        statuses_seen: list[str] = ["LOCAL_PROVIDER_SMOKE_OUTPUT_UNTRUSTED"]

        if resp.status == "MODEL_COMPAT_HARNESS_PASSED":
            return LocalProviderSmokeRecord(
                decision="LOCAL_PROVIDER_SMOKE_PASSED",
                provider=config.provider,
                model_id=config.model_id,
                config_path=config.config_path,
                elapsed_ms=resp.elapsed_ms,
                response_chars=resp.response_chars,
                output_trusted=False,
                statuses_seen=tuple(statuses_seen),
                notes=("smoke test passed; output remains untrusted",),
            )

        if resp.status == "MODEL_COMPAT_HARNESS_BLOCKED_PROVIDER_UNAVAILABLE":
            decision = "LOCAL_PROVIDER_SMOKE_BLOCKED_PROVIDER_UNAVAILABLE"
        elif resp.status == "MODEL_COMPAT_HARNESS_BLOCKED_TIMEOUT":
            decision = "LOCAL_PROVIDER_SMOKE_BLOCKED_TIMEOUT"
        else:
            decision = "LOCAL_PROVIDER_SMOKE_BLOCKED_MALFORMED_OUTPUT"

        return LocalProviderSmokeRecord(
            decision=decision,
            provider=config.provider,
            model_id=config.model_id,
            config_path=config.config_path,
            elapsed_ms=resp.elapsed_ms,
            response_chars=resp.response_chars,
            output_trusted=False,
            statuses_seen=tuple(statuses_seen) + (decision,),
            notes=(resp.status,),
        )

    @staticmethod
    def _blocked(
        decision: str,
        *,
        config_path: str,
        provider: str,
        model_id: str,
        note: str,
    ) -> LocalProviderSmokeRecord:
        return LocalProviderSmokeRecord(
            decision=decision,
            provider=provider,
            model_id=model_id,
            config_path=config_path,
            elapsed_ms=0,
            response_chars=0,
            output_trusted=False,
            statuses_seen=(decision, "LOCAL_PROVIDER_SMOKE_OUTPUT_UNTRUSTED"),
            notes=(note,),
        )


__all__ = [
    "LocalProviderSmokeTest",
    "LocalProviderSmokeRecord",
    "LOCAL_PROVIDER_SMOKE_STATUS_TOKENS",
]
