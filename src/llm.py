"""
LLM client: wrapper around a local quantized model served via vLLM or llama.cpp.

Implements an OpenAI-compatible API client (vLLM exposes this endpoint),
so switching between vLLM, llama.cpp server, or the actual OpenAI API
requires only a URL/key change.
"""

import os
import time
from dataclasses import dataclass
from typing import Optional


DEFAULT_BASE_URL = "http://localhost:8000/v1"   # vLLM default
DEFAULT_MODEL = "qwen2.5-coder-7b-instruct"     # or "llama-3.1-8b-instruct"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.2  # Low temperature for diagnosis consistency


@dataclass
class LLMConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    timeout: int = 60
    api_key: str = "not-needed"  # vLLM / llama.cpp don't require a real key


class LLMClient:
    """
    Thin wrapper around the OpenAI-compatible local inference server.

    Compatible with:
    - vLLM (ROCm backend): `vllm serve <model> --port 8000`
    - llama.cpp server:    `./server -m model.gguf --port 8000`
    - OpenAI API (for testing): set base_url to "https://api.openai.com/v1"
    """

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        try:
            from openai import OpenAI
            self._client = OpenAI(
                base_url=self.config.base_url,
                api_key=self.config.api_key,
            )
        except ImportError:
            self._client = None  # Fall back to HTTP requests below

    def generate(
        self,
        prompt: str,
        system: str = "",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Generate a completion from the local LLM.

        Args:
            prompt: The user-turn prompt.
            system: Optional system prompt.
            max_tokens: Override for this specific call.
            temperature: Override for this specific call.

        Returns:
            The generated text string.
        """
        if self._client is not None:
            return self._openai_generate(prompt, system, max_tokens, temperature)
        else:
            return self._http_generate(prompt, system, max_tokens, temperature)

    def health_check(self) -> dict:
        """
        Verify the LLM server is reachable and return model info.
        Call this on startup to surface environment issues early.
        """
        try:
            if self._client:
                models = self._client.models.list()
                return {
                    "status": "ok",
                    "models": [m.id for m in models.data],
                    "base_url": self.config.base_url,
                }
        except Exception as e:
            pass

        return {
            "status": "unreachable",
            "error": f"Cannot connect to LLM server at {self.config.base_url}",
            "hint": (
                "Start the server with: `vllm serve <model> --port 8000` "
                "or `./llama-server -m model.gguf --port 8000`"
            ),
            "base_url": self.config.base_url,
        }

    def measure_throughput(self, prompt: str = "Hello, world!", runs: int = 3) -> dict:
        """
        Measure inference throughput in tokens/sec.
        Used to generate the 'before/after' inference speed numbers for the demo.
        """
        latencies = []
        for _ in range(runs):
            start = time.perf_counter()
            response = self.generate(prompt, max_tokens=50)
            elapsed = time.perf_counter() - start
            tokens = len(response.split())  # rough token estimate
            latencies.append({"latency_s": elapsed, "tokens": tokens})

        if not latencies:
            return {"tokens_per_sec": None, "error": "All runs failed"}

        latencies.sort(key=lambda x: x["latency_s"])
        median = latencies[len(latencies) // 2]

        return {
            "tokens_per_sec": round(median["tokens"] / median["latency_s"], 1),
            "median_latency_s": round(median["latency_s"], 3),
            "runs": runs,
        }

    # ------------------------------------------------------------------
    # Backends
    # ------------------------------------------------------------------

    def _openai_generate(
        self, prompt: str, system: str, max_tokens: Optional[int], temperature: Optional[float]
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            response = self._client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                max_tokens=max_tokens or self.config.max_tokens,
                temperature=temperature if temperature is not None else self.config.temperature,
                timeout=self.config.timeout,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            return f"[LLM error] {e}"

    def _http_generate(
        self, prompt: str, system: str, max_tokens: Optional[int], temperature: Optional[float]
    ) -> str:
        """Fallback using raw HTTP if openai package not installed."""
        import json
        import urllib.request
        import urllib.error

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = json.dumps({
            "model": self.config.model,
            "messages": messages,
            "max_tokens": max_tokens or self.config.max_tokens,
            "temperature": temperature if temperature is not None else self.config.temperature,
        }).encode("utf-8")

        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.config.api_key}"},
        )

        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"]
        except urllib.error.URLError as e:
            return f"[LLM HTTP error] {e}"
        except Exception as e:
            return f"[LLM error] {e}"


class MockLLMClient:
    """
    Deterministic mock LLM for unit tests and offline development.
    Returns realistic-looking canned responses.
    """

    def generate(self, prompt: str, system: str = "", **kwargs) -> str:
        if "pushback" in system.lower() or "re-examine" in prompt.lower():
            import re
            # Extract ONLY the developer's actual pushback text, not the full prompt
            # The PUSHBACK_PROMPT_TEMPLATE embeds prior diagnosis text which would
            # pollute keyword matching if we searched the whole prompt.
            pb_match = re.search(
                r"Developer's pushback:\n(.*?)\n\nFresh evidence",
                prompt, re.DOTALL | re.IGNORECASE
            )
            pushback_text = pb_match.group(1).strip() if pb_match else prompt
            pushback_lower = pushback_text.lower()

            # Pushback about compute-bound / GPU utilization
            if any(kw in pushback_lower for kw in ["compute", "utilization", "util", "87", "compute-bound"]):
                return """{
  "pattern_type": "memory_coalescing",
  "title": "Uncoalesced memory access — utilization does not indicate compute-bound",
  "diagnosis": "High GPU utilization does not rule out memory-boundedness. rocm-smi reports 'busy' cycles, not arithmetic cycles.",
  "root_cause": "A wavefront stalled on a cache miss is counted as 'busy' by rocm-smi. The aten::convolution hotspot (73.2% CUDA time across only 8 calls) is too expensive per-call for a compute-bound kernel — this is memory latency, not arithmetic throughput.",
  "proposed_fix": "Ensure input tensors are contiguous before kernel launch: `x = x.contiguous()`. To definitively confirm, run `rocprof` and compare MemUnitBusy vs VALUUtilization.",
  "confidence": "HIGH",
  "doc_citation": "HIP Programming Guide § Memory Coalescing"
}

My diagnosis stands. The key distinction: rocm-smi's 'GPU utilization' measures whether the CU is doing *anything*, not whether it's doing compute. A wavefront blocked on a VRAM fetch still counts as 'active'. The profiler confirms: aten::convolution dominates at 73.2% of CUDA time across just 8 calls — that's 6.5ms per call average. For a compute-bound convolution of this size, you'd expect far lower per-call latency. The excess time is memory latency from strided access patterns."""

            # Pushback about occupancy
            elif any(kw in pushback_lower for kw in ["occupancy", "register", "wavefront", "block size", "launch bound"]):
                return """{
  "pattern_type": "memory_coalescing",
  "title": "Uncoalesced memory access — distinguished from occupancy limiter",
  "diagnosis": "An occupancy limiter reduces parallelism at kernel launch time. The profiler data pattern here is consistent with per-call memory latency, not a scheduling bottleneck.",
  "root_cause": "If occupancy were the primary limiter, we would see long wall-clock time with low kernel count and relatively uniform per-call cost. Instead, aten::convolution shows 8 calls at 52.1ms total — the per-call cost of 6.5ms is excessive for the computation performed, consistent with multiple cache line fetches per wavefront.",
  "proposed_fix": "Ensure `x = x.contiguous()` for coalesced layout. To rule out occupancy: run `rocprof --stats` and check `Wavefronts` vs theoretical maximum. If achieved occupancy exceeds 60% of theoretical, occupancy is not the bottleneck.",
  "confidence": "HIGH",
  "doc_citation": "HIP Programming Guide § Wavefront Execution and Memory Coalescing"
}

Occupancy and coalescing are two separate effects. An occupancy limiter (register pressure, LDS overuse) prevents the hardware from scheduling enough wavefronts — you'd see low GPU utilization as a result. We see 87% utilization, which argues *against* an occupancy limiter. The issue is what happens *inside* each wavefront execution: adjacent threads in the wavefront are hitting non-contiguous cache lines, multiplying the memory transaction count. That's coalescing, not occupancy."""

            # Generic / "why" pushback
            else:
                return """{
  "pattern_type": "memory_coalescing",
  "title": "Uncoalesced memory access — evidence re-examined",
  "diagnosis": "Re-examining all available signals: the profiler hotspot distribution and VRAM access pattern remain consistent with non-coalesced global memory access.",
  "root_cause": "Adjacent threads in a wavefront (64 threads on CDNA/RDNA) must access the same 128-byte cache line for a coalesced transaction. Strided or scattered access forces N separate cache line fetches instead of 1, multiplying effective memory latency by up to N.",
  "proposed_fix": "Restructure data layout so threadIdx.x maps to the contiguous (fastest-varying) dimension. For PyTorch ops: `x = x.contiguous()` before the call. For custom HIP kernels: verify the indexing formula `row * COLS + col` has `col` driven by threadIdx.x.",
  "confidence": "HIGH",
  "doc_citation": "HIP Programming Guide § Memory Coalescing — Cache Line Utilization"
}

After re-examining the data: aten::convolution at 73.2% of CUDA time across 8 calls remains the dominant signal. The VRAM usage (63% of 24GB) and the profiler hotspot together are inconsistent with compute saturation. I maintain the memory_coalescing diagnosis. If you have a rocprof trace with MemUnitBusy counters, I can give you a definitive answer rather than a probabilistic one."""

        return """{
  "pattern_type": "memory_coalescing",
  "title": "Non-coalesced global memory access",
  "diagnosis": "Top profiler hot-spot indicates strided memory access pattern causing inefficient VRAM transactions.",
  "root_cause": "Threads in the same wavefront access non-contiguous VRAM addresses, requiring multiple memory transactions where one would suffice if the data were laid out contiguously.",
  "proposed_fix": "Ensure input tensors are contiguous before kernel launch: `x = x.contiguous()`. For custom HIP kernels, restructure the indexing so threadIdx.x maps to the fastest-varying dimension.",
  "confidence": "MEDIUM",
  "doc_citation": "ROCm Performance Guide § Memory Coalescing"
}"""

    def health_check(self) -> dict:
        return {"status": "ok", "models": ["mock-model"], "base_url": "mock://"}

    def measure_throughput(self, **kwargs) -> dict:
        return {"tokens_per_sec": 120.5, "median_latency_s": 0.415, "runs": 3}
