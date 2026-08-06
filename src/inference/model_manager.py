import logging
import time
from typing import Optional, Generator

from ..config import InferenceConfig
from ..privacy.telemetry import telemetry
from .vllm_server import VLLMServer
from .radeon_api import RadeonCloudAPI

logger = logging.getLogger(__name__)

def _estimate_tokens(text: str) -> int:
    """Rough token estimate when a backend does not report usage."""
    if not text:
        return 0
    return max(0, len(str(text)) // 4)

class ModelManager:
    """Manages model inference with a resilient fallback chain.

    Every attempt is telemetry-tagged with a canonical backend label
    (``vllm``, ``local_secondary``, ``radeon_api``, or ``failed``) via the
    shared :mod:`src.privacy.telemetry` singleton, so AuditLogger and
    DataFlowMonitor see real local vs external counts.
    """

    def __init__(self, config: InferenceConfig, audit_logger=None, data_flow_monitor=None):
        """
        Initialises the ModelManager.

        Args:
            config: Inference configuration.
            audit_logger: Optional audit logger instance.
            data_flow_monitor: Optional DataFlowMonitor instance.
        """
        self.config = config
        self.audit_logger = audit_logger
        self.data_flow_monitor = data_flow_monitor
        self.vllm_primary: Optional[VLLMServer] = None
        self.vllm_secondary: Optional[VLLMServer] = None
        self.radeon_api: Optional[RadeonCloudAPI] = None
        
        self.fallback_stats = {
            "vllm": 0,
            "local_secondary": 0,
            "radeon_api": 0,
            "failed": 0,
        }
        self._current_backend: str = "none"

    def initialize(self) -> None:
        """Initialises the inference backends.

        The primary vLLM server is only auto-started when the configured
        backend is ``vllm``. The other backends (``ollama``, ``radeon_api``)
        leave the vLLM subprocesses unmanaged so a dev box never eagerly
        spawns a large-model server it does not need.
        """
        logger.info("Initialising ModelManager...")

        if self.config.backend.lower() == "vllm":
            # Primary local vLLM
            self.vllm_primary = VLLMServer(self.config, is_primary=True)
            if not self.vllm_primary.start():
                logger.warning("Primary vLLM failed to start. Will rely on fallback.")

            # Secondary local vLLM (initialise config, maybe don't start
            # immediately to save RAM). Assuming we start it if primary fails,
            # or keep it ready. For now, just initialise instance.
            self.vllm_secondary = VLLMServer(self.config, is_primary=False)
        else:
            logger.info("Backend is '%s'; skipping vLLM server management.", self.config.backend)

        # Radeon Cloud API
        if self.config.radeon_api_key:
            self.radeon_api = RadeonCloudAPI(
                api_key=self.config.radeon_api_key,
                model=self.config.radeon_model
            )
            logger.info("Radeon Cloud API configured as fallback.")

    def _record_inference(
        self,
        backend: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
        error: Optional[Exception] = None,
    ) -> None:
        """Increment fallback counters and emit telemetry for one attempt.

        Telemetry is a no-op until sinks are configured, so unit tests that
        exercise the fallback chain directly never touch disk.
        """
        self.fallback_stats[backend] = self.fallback_stats.get(backend, 0) + 1
        telemetry.record_inference(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            backend=backend,
            latency_ms=latency_ms,
            error=error,
        )

    def generate(self, messages: list[dict], max_tokens: int = 512, temperature: float = 0.7) -> str:
        """
        Generates text using the configured fallback chain.
        
        1. Try primary local vLLM (backend ``vllm``)
        2. Try secondary local vLLM (backend ``local_secondary``)
        3. Try Radeon Cloud API (backend ``radeon_api`` — external)
        4. Fail (backend ``failed``)
        """
        prompt_tokens = sum(_estimate_tokens(m.get("content", "")) for m in messages)

        # 1. Primary vLLM
        if self.vllm_primary and self.vllm_primary.is_healthy():
            try:
                self._current_backend = "vllm"
                start = time.perf_counter()
                res = self.vllm_primary.generate(messages, max_tokens, temperature)
                self._record_inference(
                    "vllm", self.vllm_primary.model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=_estimate_tokens(res),
                    latency_ms=(time.perf_counter() - start) * 1000.0,
                )
                return res
            except Exception as e:
                logger.error(f"Primary vLLM failed during generation: {e}")

        # 2. Secondary vLLM
        if self.vllm_secondary:
            if not self.vllm_secondary.is_healthy():
                logger.info("Attempting to start secondary vLLM...")
                self.vllm_secondary.start()
            
            if self.vllm_secondary.is_healthy():
                try:
                    self._current_backend = "local_secondary"
                    start = time.perf_counter()
                    res = self.vllm_secondary.generate(messages, max_tokens, temperature)
                    self._record_inference(
                        "local_secondary", self.vllm_secondary.model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=_estimate_tokens(res),
                        latency_ms=(time.perf_counter() - start) * 1000.0,
                    )
                    return res
                except Exception as e:
                    logger.error(f"Secondary vLLM failed during generation: {e}")

        # 3. Radeon Cloud API
        if self.radeon_api and self.radeon_api.is_available():
            try:
                self._current_backend = "radeon_api"
                start = time.perf_counter()
                res = self.radeon_api.generate(messages, max_tokens, temperature)
                self._record_inference(
                    "radeon_api", self.radeon_api.model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=_estimate_tokens(res),
                    latency_ms=(time.perf_counter() - start) * 1000.0,
                )
                return res
            except Exception as e:
                logger.error(f"Radeon API failed during generation: {e}")

        # 4. Fail
        self._current_backend = "failed"
        self._record_inference(
            "failed", getattr(self.config, "primary_model", "unknown"),
            prompt_tokens=prompt_tokens,
            error=RuntimeError("All inference backends failed."),
        )
        raise RuntimeError("All inference backends failed.")

    def stream_generate(self, messages: list[dict], max_tokens: int = 512, temperature: float = 0.7) -> Generator[str, None, None]:
        """
        Generates text via stream using the fallback chain.
        """
        prompt_tokens = sum(_estimate_tokens(m.get("content", "")) for m in messages)

        # 1. Primary vLLM
        if self.vllm_primary and self.vllm_primary.is_healthy():
            try:
                self._current_backend = "vllm"
                start = time.perf_counter()
                self._record_inference(
                    "vllm", self.vllm_primary.model,
                    prompt_tokens=prompt_tokens,
                    latency_ms=(time.perf_counter() - start) * 1000.0,
                )
                return self.vllm_primary.stream_generate(messages, max_tokens, temperature)
            except Exception as e:
                logger.error(f"Primary vLLM failed during stream generation: {e}")

        # 2. Secondary vLLM
        if self.vllm_secondary:
            if not self.vllm_secondary.is_healthy():
                self.vllm_secondary.start()
            if self.vllm_secondary.is_healthy():
                try:
                    self._current_backend = "local_secondary"
                    start = time.perf_counter()
                    self._record_inference(
                        "local_secondary", self.vllm_secondary.model,
                        prompt_tokens=prompt_tokens,
                        latency_ms=(time.perf_counter() - start) * 1000.0,
                    )
                    return self.vllm_secondary.stream_generate(messages, max_tokens, temperature)
                except Exception as e:
                    logger.error(f"Secondary vLLM failed during stream generation: {e}")

        # 3. Radeon Cloud API
        if self.radeon_api and self.radeon_api.is_available():
            try:
                self._current_backend = "radeon_api"
                start = time.perf_counter()
                self._record_inference(
                    "radeon_api", self.radeon_api.model,
                    prompt_tokens=prompt_tokens,
                    latency_ms=(time.perf_counter() - start) * 1000.0,
                )
                return self.radeon_api.stream_generate(messages, max_tokens, temperature)
            except Exception as e:
                logger.error(f"Radeon API failed during stream generation: {e}")

        # 4. Fail
        self._current_backend = "failed"
        self._record_inference(
            "failed", getattr(self.config, "primary_model", "unknown"),
            prompt_tokens=prompt_tokens,
            error=RuntimeError("All inference backends failed for streaming."),
        )
        raise RuntimeError("All inference backends failed for streaming.")

    def get_stats(self) -> dict:
        """Returns statistics on backend usage.

        Local tiers are ``vllm`` + ``local_secondary``; the Radeon Cloud API
        is external; ``failed`` never counts as local.
        """
        total = sum(self.fallback_stats.values())
        local_count = self.fallback_stats["vllm"] + self.fallback_stats["local_secondary"]
        external_count = self.fallback_stats["radeon_api"]
        failed_count = self.fallback_stats["failed"]
        return {
            **self.fallback_stats,
            "total": total,
            "local_count": local_count,
            "external_count": external_count,
            "failed_count": failed_count,
            "local_percentage": (local_count / total * 100) if total > 0 else 100.0,
            "current_backend": self._current_backend,
        }

    def shutdown(self) -> None:
        """Shuts down all managed inference servers."""
        if self.vllm_primary:
            self.vllm_primary.stop()
        if self.vllm_secondary:
            self.vllm_secondary.stop()
