"""DSPy runtime wiring for Bunker.

Binds DSPy's default language model based on config.inference.backend
("vllm", "ollama", or "radeon_api") and configures it as the process-wide default.
Import this module at application startup so every DSPy module resolves to the
served model. No un-audited traffic leaves localhost.

Every LM call is wrapped by :class:`_TelemetryLM`, which routes token/latency
telemetry through :class:`InferenceTelemetry` (AuditLogger + DataFlowMonitor).
The backend label attached to each event is ``vllm``, ``ollama``, or
``radeon_api`` depending on config.inference.backend; Radeon Cloud is recorded
as external.
"""

import logging
import time
from typing import Optional

import dspy  # https://dspy.ai/api/models/LM

from .config import get_config
from .privacy.telemetry import (
    BACKEND_FAILED,
    telemetry,
)

logger = logging.getLogger(__name__)


def configure_telemetry(
    audit_logger: Optional[object] = None,
    data_flow_monitor: Optional[object] = None,
    backend: Optional[str] = None,
) -> None:
    """Attach privacy sinks to the process-wide inference telemetry.

    Called at application startup (``src.main``) with the shared
    AuditLogger and DataFlowMonitor so every DSPy LM call and every
    ``ModelManager`` fallback call is audited. Calling it with no arguments
    detaches the sinks (used by tests and on shutdown).
    """
    if audit_logger is None and data_flow_monitor is None and backend is None:
        telemetry.reset()
        return
    telemetry.configure(
        audit_logger=audit_logger,
        data_flow_monitor=data_flow_monitor,
        backend=backend,
    )


class _TelemetryLM(dspy.LM):
    """dspy.LM wrapper that records every call via InferenceTelemetry.

    ``forward``/``aforward`` are wrapped so prompt/completion tokens and
    latency are captured from the response ``usage``; failures are recorded
    with backend ``failed``. Telemetry is a no-op until sinks are configured.
    """

    def forward(self, prompt=None, messages=None, **kwargs):
        start = time.perf_counter()
        try:
            response = super().forward(prompt=prompt, messages=messages, **kwargs)
        except Exception as exc:
            telemetry.record_inference(
                model=self.model,
                backend=BACKEND_FAILED,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                error=exc,
            )
            raise
        usage = getattr(response, "usage", None) or {}
        telemetry.record_inference(
            model=self.model,
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=(time.perf_counter() - start) * 1000.0,
        )
        return response

    async def aforward(self, prompt=None, messages=None, **kwargs):
        start = time.perf_counter()
        try:
            response = await super().aforward(prompt=prompt, messages=messages, **kwargs)
        except Exception as exc:
            telemetry.record_inference(
                model=self.model,
                backend=BACKEND_FAILED,
                latency_ms=(time.perf_counter() - start) * 1000.0,
                error=exc,
            )
            raise
        usage = getattr(response, "usage", None) or {}
        telemetry.record_inference(
            model=self.model,
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=(time.perf_counter() - start) * 1000.0,
        )
        return response

def build_lm(config=None) -> dspy.LM:
    """Build a dspy.LM instance based on the inference configuration."""
    if config is None:
        config = get_config()
    
    backend = getattr(config.inference, "backend", "vllm").lower()
    
    if backend == "ollama":
        model_name = config.inference.ollama_model
        if not model_name.startswith("openai/"):
            model_string = f"openai/{model_name}"
        else:
            model_string = model_name
        api_base = config.inference.ollama_base_url
        api_key = "ollama"
    elif backend == "radeon_api":
        model_name = config.inference.radeon_model
        if not model_name.startswith("openai/"):
            model_string = f"openai/{model_name}"
        else:
            model_string = model_name
        api_base = config.inference.radeon_api_url
        api_key = config.inference.radeon_api_key or "EMPTY"
    else:  # default to vllm
        backend = "vllm"
        model_name = config.inference.primary_model
        if not model_name.startswith("openai/"):
            model_string = f"openai/{model_name}"
        else:
            model_string = model_name
        api_base = f"http://{config.inference.vllm_host}:{config.inference.vllm_port}/v1"
        api_key = "EMPTY"
        
    logger.info(f"Configuring DSPy LM with backend='{backend}', model='{model_string}', api_base='{api_base}'")

    # Label telemetry with this LM's backend + model so every wrapped call is
    # classified as local (vllm/ollama) or external (radeon_api).
    telemetry.configure(backend=backend, model_label=model_string)
    
    # https://dspy.ai/api/models/LM
    return _TelemetryLM(
        model=model_string,
        api_base=api_base,
        api_key=api_key,
        max_tokens=config.agent.max_tokens_per_turn,
        temperature=0.0,
        cache=False,  # required by DataFlowMonitor: every request must be observable
    )

_config = get_config()
BUNKER_LM = build_lm(_config)

# Set the process-wide default LM. https://dspy.ai/api/models/LM
dspy.configure(lm=BUNKER_LM)

