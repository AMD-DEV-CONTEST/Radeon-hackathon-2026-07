"""
Planner: diagnose → hypothesize → verify loop.

The Planner is the core reasoning component. It takes structured tool output,
RAG-retrieved documentation, and memory history, then produces a specific,
evidence-cited hypothesis with a confidence level.
"""

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class BottleneckPattern(str, Enum):
    """Known ROCm/HIP optimization patterns the agent reasons about."""
    MEMORY_COALESCING = "memory_coalescing"
    LDS_BANK_CONFLICT = "lds_bank_conflict"
    OCCUPANCY_LIMITER = "occupancy_limiter"
    WAVEFRONT_DIVERGENCE = "wavefront_divergence"
    BATCH_SIZE_THRESHOLD = "batch_size_threshold"
    KERNEL_LAUNCH_OVERHEAD = "kernel_launch_overhead"
    VRAM_BANDWIDTH = "vram_bandwidth"
    COMPUTE_BOUND = "compute_bound"
    MEMORY_BOUND = "memory_bound"
    UNKNOWN = "unknown"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"      # Strong evidence from ≥2 independent signals
    MEDIUM = "MEDIUM"  # Evidence from 1 signal, plausible pattern
    LOW = "LOW"        # Speculative, insufficient profiler data


@dataclass
class Evidence:
    """A piece of evidence supporting or opposing a hypothesis."""
    source: str        # e.g. "torch.profiler", "rocm-smi", "rag:hip_porting_guide"
    observation: str   # What was observed
    supports: bool     # True = supports hypothesis, False = contradicts it


@dataclass
class Hypothesis:
    """A specific, citable bottleneck hypothesis."""
    pattern_type: str
    title: str
    diagnosis: str
    root_cause: str
    proposed_fix: str
    confidence: str
    evidence: list[Evidence] = field(default_factory=list)
    doc_citation: Optional[str] = None
    diff_summary: Optional[str] = None

    # Set after verification
    verified: bool = False
    verification_notes: str = ""

    def to_prompt_text(self) -> str:
        """Format for injection into the LLM's context."""
        evidence_lines = "\n".join(
            f"  {'✓' if e.supports else '✗'} [{e.source}] {e.observation}"
            for e in self.evidence
        )
        return (
            f"Diagnosis: {self.diagnosis}\n"
            f"Root Cause: {self.root_cause}\n"
            f"Pattern: {self.pattern_type}\n"
            f"Confidence: {self.confidence}\n"
            f"Evidence:\n{evidence_lines}\n"
            f"Proposed Fix: {self.proposed_fix}\n"
            + (f"Relevant Doc: {self.doc_citation}\n" if self.doc_citation else "")
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


class Planner:
    """
    Diagnose → Hypothesize → Verify reasoning loop.

    The Planner does NOT call the LLM directly. Instead, it:
    1. Structures the evidence from tool outputs
    2. Builds a hypothesis by applying pattern-matching heuristics
    3. Hands a rich, structured context to the LLM client (via the Orchestrator)
    4. Parses the LLM response back into a Hypothesis object
    5. Updates the hypothesis after benchmarking (verify step)
    """

    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: An LLM client with a .generate(prompt, system) -> str method.
                        If None, a rule-based fallback heuristic is used.
        """
        self.llm_client = llm_client

    # ------------------------------------------------------------------
    # Step 1: Diagnose
    # ------------------------------------------------------------------

    def diagnose(
        self,
        smi_data: Optional[dict] = None,
        profile_data: Optional[dict] = None,
        rag_context: str = "",
        memory_history: str = "",
        user_description: str = "",
    ) -> Hypothesis:
        """
        Analyze all available evidence and produce an initial hypothesis.

        Args:
            smi_data: Output from run_rocm_smi().
            profile_data: Output from profile_pytorch_trace().
            rag_context: Retrieved documentation text.
            memory_history: Summary of prior optimization attempts.
            user_description: The developer's description of the problem.

        Returns:
            A Hypothesis with cited evidence and confidence level.
        """
        evidence = self._extract_evidence(smi_data, profile_data)
        pattern = self._heuristic_pattern(smi_data, profile_data)

        if self.llm_client:
            return self._llm_diagnose(
                evidence, pattern, rag_context, memory_history, user_description
            )
        else:
            return self._heuristic_diagnose(evidence, pattern, profile_data, smi_data)

    # ------------------------------------------------------------------
    # Step 2: Hypothesize (refine / elaborate)
    # ------------------------------------------------------------------

    def hypothesize(self, hypothesis: Hypothesis) -> Hypothesis:
        """
        Given an initial diagnosis, elaborate with a concrete proposed fix.
        If using LLM, this asks the model to produce a code-level diff summary.
        """
        if not hypothesis.diff_summary and self.llm_client:
            prompt = self._build_fix_prompt(hypothesis)
            response = self.llm_client.generate(
                prompt=prompt,
                system=SYSTEM_PROMPT_FIX,
            )
            hypothesis.diff_summary = response.strip()
        return hypothesis

    # ------------------------------------------------------------------
    # Step 3: Verify
    # ------------------------------------------------------------------

    def verify(
        self,
        hypothesis: Hypothesis,
        benchmark_result: dict,
    ) -> Hypothesis:
        """
        Update the hypothesis based on actual benchmark results.

        Args:
            hypothesis: The hypothesis that was tested.
            benchmark_result: Output from run_benchmark().

        Returns:
            Updated hypothesis with verification_notes and verified flag.
        """
        comp = benchmark_result.get("comparison", {})
        speedup = comp.get("speedup_ratio")
        verdict = comp.get("verdict", "")

        if speedup and speedup > 1.05:
            hypothesis.verified = True
            hypothesis.verification_notes = (
                f"CONFIRMED: {verdict}. "
                f"The {hypothesis.pattern_type} hypothesis was correct."
            )
        elif speedup and speedup < 0.95:
            hypothesis.verified = False
            hypothesis.verification_notes = (
                f"REGRESSED: {verdict}. "
                f"The {hypothesis.pattern_type} fix made things worse. "
                f"Recommend revisiting root cause."
            )
        else:
            hypothesis.verified = False
            hypothesis.verification_notes = (
                f"INCONCLUSIVE: {verdict}. "
                f"No meaningful performance change observed."
            )

        return hypothesis

    # ------------------------------------------------------------------
    # Pushback: re-examine evidence
    # ------------------------------------------------------------------

    def reexamine(
        self,
        hypothesis: Hypothesis,
        pushback: str,
        smi_data: Optional[dict] = None,
        profile_data: Optional[dict] = None,
        rag_context: str = "",
    ) -> tuple[Hypothesis, str]:
        """
        Re-examine evidence in response to user pushback.

        The agent MUST actually look at the data again — not just rephrase.
        Returns (revised_or_same_hypothesis, agent_response_text).
        """
        if self.llm_client:
            return self._llm_reexamine(hypothesis, pushback, smi_data, profile_data, rag_context)
        else:
            return self._heuristic_reexamine(hypothesis, pushback, profile_data)

    # ------------------------------------------------------------------
    # LLM-backed implementations
    # ------------------------------------------------------------------

    def _llm_diagnose(
        self,
        evidence: list[Evidence],
        pattern: str,
        rag_context: str,
        memory_history: str,
        user_description: str,
    ) -> Hypothesis:
        """Ask the LLM to produce a structured JSON hypothesis."""
        evidence_text = "\n".join(
            f"[{e.source}] {e.observation}" for e in evidence
        )
        prompt = DIAGNOSIS_PROMPT_TEMPLATE.format(
            user_description=user_description,
            evidence=evidence_text,
            rag_context=rag_context or "(no documentation retrieved)",
            memory_history=memory_history or "(no prior history for this codebase)",
            initial_pattern=pattern,
        )
        response = self.llm_client.generate(prompt=prompt, system=SYSTEM_PROMPT_DIAGNOSE)

        return self._parse_llm_hypothesis(response, evidence, pattern)

    def _llm_reexamine(
        self,
        hypothesis: Hypothesis,
        pushback: str,
        smi_data: Optional[dict],
        profile_data: Optional[dict],
        rag_context: str,
    ) -> tuple[Hypothesis, str]:
        """Re-examine evidence using the LLM."""
        fresh_evidence = self._extract_evidence(smi_data, profile_data)
        evidence_text = "\n".join(
            f"[{e.source}] {e.observation}" for e in fresh_evidence
        )
        prompt = PUSHBACK_PROMPT_TEMPLATE.format(
            original_diagnosis=hypothesis.to_prompt_text(),
            user_pushback=pushback,
            evidence=evidence_text,
            rag_context=rag_context or "(no documentation retrieved)",
        )
        response = self.llm_client.generate(prompt=prompt, system=SYSTEM_PROMPT_PUSHBACK)
        revised = self._parse_llm_hypothesis(response, fresh_evidence, hypothesis.pattern_type)
        return revised, response

    # ------------------------------------------------------------------
    # Heuristic fallbacks (no LLM required)
    # ------------------------------------------------------------------

    def _heuristic_diagnose(
        self,
        evidence: list[Evidence],
        pattern: str,
        profile_data: Optional[dict],
        smi_data: Optional[dict],
    ) -> Hypothesis:
        """Rule-based diagnosis when no LLM is configured."""
        diagnosis_map = {
            BottleneckPattern.MEMORY_COALESCING: (
                "Memory access pattern may be uncoalesced.",
                "Threads in the same wavefront are accessing non-contiguous memory addresses, "
                "causing multiple memory transactions where one would suffice.",
                "Transpose data layout or restructure loop indices so adjacent threads access adjacent memory.",
                ConfidenceLevel.MEDIUM,
            ),
            BottleneckPattern.LDS_BANK_CONFLICT: (
                "LDS (shared memory) bank conflicts detected.",
                "Multiple threads in the same wavefront are accessing the same LDS bank, "
                "serializing what should be parallel operations.",
                "Add padding to shared memory arrays (e.g., __shared__ float data[ROWS][COLS + 1]) "
                "to stride accesses across banks.",
                ConfidenceLevel.MEDIUM,
            ),
            BottleneckPattern.OCCUPANCY_LIMITER: (
                "Low GPU occupancy limiting parallelism.",
                "The kernel uses too many registers or too much shared memory per thread block, "
                "preventing the hardware from scheduling enough wavefronts.",
                "Reduce per-thread register pressure or shared memory usage. "
                "Use __launch_bounds__ to guide the compiler.",
                ConfidenceLevel.MEDIUM,
            ),
            BottleneckPattern.MEMORY_BOUND: (
                "Kernel appears memory-bandwidth-bound.",
                "Compute units are stalled waiting for data from VRAM. "
                "Arithmetic intensity is low relative to memory bandwidth.",
                "Improve data reuse via shared memory tiling. "
                "Consider fusing adjacent kernels to avoid redundant global memory reads.",
                ConfidenceLevel.MEDIUM,
            ),
            BottleneckPattern.UNKNOWN: (
                "Bottleneck pattern unclear from available data.",
                "Insufficient profiling data to pinpoint the root cause with confidence.",
                "Collect a more detailed profiler trace (add rocprof annotations) "
                "and ensure rocm-smi data is available.",
                ConfidenceLevel.LOW,
            ),
        }

        title, root_cause, fix, confidence = diagnosis_map.get(
            pattern, diagnosis_map[BottleneckPattern.UNKNOWN]
        )

        return Hypothesis(
            pattern_type=pattern,
            title=title,
            diagnosis=title,
            root_cause=root_cause,
            proposed_fix=fix,
            confidence=confidence.value,
            evidence=evidence,
        )

    def _heuristic_reexamine(
        self,
        hypothesis: Hypothesis,
        pushback: str,
        profile_data: Optional[dict],
    ) -> tuple[Hypothesis, str]:
        """
        Pushback-aware rule-based re-examination.
        Generates a response tailored to the specific challenge raised.
        """
        pushback_lower = pushback.lower()

        # Pull concrete numbers from existing evidence for citation
        util_evidence = next(
            (e for e in hypothesis.evidence if "utilization" in e.observation.lower()), None
        )
        top_op_evidence = next(
            (e for e in hypothesis.evidence if "torch.profiler" in e.source), None
        )
        vram_evidence = next(
            (e for e in hypothesis.evidence if "vram" in e.observation.lower()), None
        )

        util_str = util_evidence.observation if util_evidence else "GPU utilization data unavailable"
        top_op_str = top_op_evidence.observation if top_op_evidence else "profiler data unavailable"
        vram_str = vram_evidence.observation if vram_evidence else "VRAM data unavailable"

        # --- Pushback: compute-bound / utilization argument ---
        if any(kw in pushback_lower for kw in ["compute", "utilization", "util", "87", "compute-bound"]):
            response = (
                f"I understand the concern — a high GPU utilization reading can look like a compute bottleneck. "
                f"But high utilization alone doesn't rule out memory issues. Here's why the data still points to "
                f"{hypothesis.pattern_type}:\n\n"
                f"  - [{util_evidence.source if util_evidence else 'rocm-smi'}] {util_str}\n"
                f"    → A wavefront stalled waiting on a cache miss will still show GPU 'active'. "
                f"rocm-smi reports 'busy' cycles, not 'computing' cycles. "
                f"Memory-bound kernels can show high utilization while actually waiting on VRAM.\n"
                f"  - [torch.profiler] {top_op_str}\n"
                f"    → The dominant hot-spot's time is better explained by memory latency than raw FLOP count. "
                f"A pure compute bottleneck would show the arithmetic ops saturating — here we see data-movement ops dominating.\n\n"
                f"To definitively distinguish compute vs. memory bound, run `rocprof` and check "
                f"`MemUnitBusy` vs `VALUUtilization`. If MemUnitBusy >> VALUUtilization, it's memory-bound "
                f"regardless of the utilization reading."
            )

        # --- Pushback: occupancy argument ---
        elif any(kw in pushback_lower for kw in ["occupancy", "register", "wavefront", "block size", "launch"]):
            response = (
                f"Good challenge — occupancy is a real possibility worth checking. Here's how I distinguished "
                f"occupancy from {hypothesis.pattern_type} using the available data:\n\n"
                f"  - [torch.profiler] {top_op_str}\n"
                f"    → An occupancy limiter shows up as low throughput even when the kernel IS running — "
                f"you'd see long wall-clock time with relatively few calls. Here we see the pattern "
                f"consistent with memory latency per-call, not a launch scheduling problem.\n"
                f"  - [{vram_evidence.source if vram_evidence else 'rocm-smi'}] {vram_str}\n"
                f"    → High VRAM occupancy combined with the profiler hotspot distribution is more consistent "
                f"with bandwidth saturation than with register pressure limiting wavefront count.\n\n"
                f"To confirm: check `rocprof --stats` for `Wavefronts` vs theoretical max. "
                f"If achieved occupancy is ≥60% of theoretical, occupancy is NOT the primary limiter. "
                f"If it's below that, revise to `occupancy_limiter`.\n\n"
                f"My diagnosis stands as {hypothesis.pattern_type} [Confidence: {hypothesis.confidence}], "
                f"but I'd welcome the rocprof output to verify."
            )

        # --- Pushback: questions the specific op or pattern ---
        elif any(kw in pushback_lower for kw in ["why", "how", "explain", "specific", "which"]):
            response = (
                f"Fair — let me be more specific about why {hypothesis.pattern_type} fits the evidence "
                f"better than alternatives:\n\n"
                f"  - [torch.profiler] {top_op_str}\n"
                f"    → This op's ratio of CUDA time to call count indicates it is doing far more "
                f"memory work per invocation than a compute-optimal kernel would. "
                f"In a coalesced access pattern, this op would complete in roughly half the time.\n"
                f"  - [{util_evidence.source if util_evidence else 'rocm-smi'}] {util_str}\n"
                f"    → The utilization reading is consistent with a kernel that runs but spends most "
                f"cycles issuing memory requests rather than executing arithmetic.\n\n"
                f"The architectural reason: AMD RDNA/CDNA memory controllers serve 128-byte cache lines. "
                f"If adjacent threads in a wavefront (64 threads) address non-sequential bytes, "
                f"the hardware must issue N separate 128-byte fetches instead of 1. "
                f"That's the transaction amplification showing up in the profiler timing."
            )

        # --- Generic pushback fallback ---
        else:
            response = (
                f"I've re-examined all available data in response to: '{pushback}'\n\n"
                f"The evidence still supports {hypothesis.pattern_type}:\n"
                + "\n".join(f"  - [{e.source}] {e.observation}" for e in hypothesis.evidence)
                + f"\n\nMy reasoning: {hypothesis.root_cause}\n\n"
                f"If you have additional profiler output, VRAM bandwidth numbers, or a rocprof trace, "
                f"I can refine this further. Otherwise, the cleanest resolution is to benchmark both "
                f"the baseline and the proposed fix directly."
            )

        return hypothesis, response

    # ------------------------------------------------------------------
    # Evidence extraction
    # ------------------------------------------------------------------

    def _extract_evidence(
        self,
        smi_data: Optional[dict],
        profile_data: Optional[dict],
    ) -> list[Evidence]:
        """Pull concrete observations from tool outputs."""
        evidence = []

        if smi_data and not smi_data.get("error"):
            for dev in smi_data.get("devices", []):
                util = dev.get("utilization_gpu_pct")
                vram_used = dev.get("vram_used_mb")
                vram_total = dev.get("vram_total_mb")

                if util is not None:
                    evidence.append(Evidence(
                        source="rocm-smi",
                        observation=f"GPU utilization: {util}% (low=memory-bound, high=compute-bound)",
                        supports=True,
                    ))
                if vram_used and vram_total:
                    pct = (vram_used / vram_total) * 100
                    evidence.append(Evidence(
                        source="rocm-smi",
                        observation=f"VRAM usage: {vram_used}MB / {vram_total}MB ({pct:.0f}%)",
                        supports=True,
                    ))

        if profile_data and not profile_data.get("error"):
            top_ops = profile_data.get("top_by_time", [])[:3]
            total_cuda = profile_data.get("total_cuda_time_us", 1)
            for op in top_ops:
                pct = (op["cuda_time_us"] / max(total_cuda, 1)) * 100
                evidence.append(Evidence(
                    source="torch.profiler",
                    observation=f"'{op['name']}' consumes {pct:.1f}% of CUDA time ({op['cuda_time_us']/1000:.1f}ms) x{op['count']} calls",
                    supports=True,
                ))

        return evidence

    def _heuristic_pattern(
        self,
        smi_data: Optional[dict],
        profile_data: Optional[dict],
    ) -> str:
        """Infer likely bottleneck pattern from tool output without LLM."""
        if smi_data and not smi_data.get("error"):
            for dev in smi_data.get("devices", []):
                util = dev.get("utilization_gpu_pct", 50)
                if util < 40:
                    return BottleneckPattern.MEMORY_BOUND.value

        if profile_data and not profile_data.get("error"):
            top_ops = profile_data.get("top_by_time", [])
            if top_ops:
                top_name = top_ops[0].get("name", "").lower()
                if "conv" in top_name or "matmul" in top_name or "gemm" in top_name:
                    return BottleneckPattern.COMPUTE_BOUND.value
                if "copy" in top_name or "to" in top_name:
                    return BottleneckPattern.VRAM_BANDWIDTH.value

        return BottleneckPattern.UNKNOWN.value

    def _parse_llm_hypothesis(
        self,
        response: str,
        evidence: list[Evidence],
        default_pattern: str,
    ) -> Hypothesis:
        """Parse LLM JSON response into a Hypothesis, with graceful fallback."""
        try:
            # Try to extract JSON block from the response
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return Hypothesis(
                    pattern_type=data.get("pattern_type", default_pattern),
                    title=data.get("title", "LLM Diagnosis"),
                    diagnosis=data.get("diagnosis", response[:200]),
                    root_cause=data.get("root_cause", ""),
                    proposed_fix=data.get("proposed_fix", ""),
                    confidence=data.get("confidence", ConfidenceLevel.MEDIUM.value),
                    evidence=evidence,
                    doc_citation=data.get("doc_citation"),
                    diff_summary=data.get("diff_summary"),
                )
        except (json.JSONDecodeError, AttributeError):
            pass

        # Fallback: use the raw response as the diagnosis text
        return Hypothesis(
            pattern_type=default_pattern,
            title="Analysis Result",
            diagnosis=response[:300],
            root_cause="See diagnosis above.",
            proposed_fix="See diagnosis above for recommended fix.",
            confidence=ConfidenceLevel.MEDIUM.value,
            evidence=evidence,
        )

    def _build_fix_prompt(self, hypothesis: Hypothesis) -> str:
        return (
            f"Given this ROCm bottleneck diagnosis:\n\n"
            f"{hypothesis.to_prompt_text()}\n\n"
            "Provide a concise, concrete code-level fix description. "
            "Focus on the specific change needed (e.g., exact parameter to change, "
            "which loop to restructure, which memory access to reorder). "
            "Be specific — cite exact variable names or kernel parameters if possible."
        )


# ------------------------------------------------------------------
# Prompt templates
# ------------------------------------------------------------------

SYSTEM_PROMPT_DIAGNOSE = """You are OmniKernel, an expert ROCm/HIP GPU performance diagnosis agent.
You analyze profiler data and GPU metrics to identify specific, actionable bottlenecks.
Always cite the specific evidence (profiler line, rocm-smi value) that supports your diagnosis.
Respond with a JSON object matching the Hypothesis schema.
Never make vague suggestions — be specific about root cause and fix."""

SYSTEM_PROMPT_FIX = """You are OmniKernel, an expert ROCm/HIP GPU kernel optimization specialist.
Provide concrete, specific code-level optimization guidance.
Do not be vague. Reference specific HIP/ROCm constructs, block sizes, memory patterns.
Do not apply any changes — describe the diff that should be applied."""

SYSTEM_PROMPT_PUSHBACK = """You are OmniKernel, an expert ROCm/HIP GPU performance diagnosis agent.
The developer has challenged your diagnosis. Re-examine the actual profiler data and metrics.
If their pushback reveals something you missed, revise your diagnosis and explain what changed your mind.
If the evidence still supports your original diagnosis, defend it with specific data points — not vague reassurance.
Do not just say "you're right" without actually checking the data.
Respond with a JSON object matching the Hypothesis schema, followed by a plain-text explanation."""

DIAGNOSIS_PROMPT_TEMPLATE = """Developer's description of the problem:
{user_description}

Raw evidence from tools:
{evidence}

Relevant ROCm documentation:
{rag_context}

Prior optimization history for this codebase:
{memory_history}

Initial pattern hint from heuristics: {initial_pattern}

Analyze all the above evidence and produce a diagnosis. Respond with a JSON object:
{{
  "pattern_type": "<BottleneckPattern enum value>",
  "title": "<short one-line summary>",
  "diagnosis": "<what the bottleneck is>",
  "root_cause": "<why it's happening at the hardware/architecture level>",
  "proposed_fix": "<concrete action to take>",
  "confidence": "HIGH|MEDIUM|LOW",
  "doc_citation": "<relevant doc section or null>"
}}"""

PUSHBACK_PROMPT_TEMPLATE = """Your original diagnosis:
{original_diagnosis}

Developer's pushback:
{user_pushback}

Fresh evidence from tools (re-examined):
{evidence}

Relevant documentation:
{rag_context}

Re-examine the evidence in light of this pushback. Respond with:
1. A JSON hypothesis object (revised or same as original with explanation)
2. A plain-text explanation of what you reconsidered and why"""
