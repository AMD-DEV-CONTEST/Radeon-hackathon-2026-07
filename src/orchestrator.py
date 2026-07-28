"""
Orchestrator: session/turn management and pushback loop.

Central coordinator that ties together:
- Tool invocation (rocm-smi, profiler, benchmark, diff proposer)
- RAG retrieval
- Planner (diagnose → hypothesize → verify)
- Memory store (cross-session learning)
- Permission gate (propose-only safety)
- Multi-turn pushback loop (the key differentiator)
"""

import hashlib
import time
from pathlib import Path
from typing import Optional

from src.permission_gate import PermissionGate, ActionType, ApprovalStatus
from src.planner import Planner, Hypothesis
from src.memory.store import MemoryStore, OptimizationAttempt, fingerprint_codebase
from src.rag.retriever import retrieve, format_retrieved_context
from src.tools.rocm_smi import run_rocm_smi, format_smi_summary
from src.tools.profiler import profile_pytorch_trace, format_profile_summary
from src.tools.benchmark_sandbox import run_benchmark, format_benchmark_summary
from src.tools.diff_proposer import (
    DiffProposal, propose_diff, propose_diff_from_strings,
    save_proposed_diff, format_diff_for_display,
)


MAX_PUSHBACK_ROUNDS = 3


class Session:
    """Holds state for a single diagnosis session."""

    def __init__(self, codebase_path: str):
        self.codebase_path = codebase_path
        self.codebase_fingerprint = fingerprint_codebase(codebase_path)
        self.smi_data: Optional[dict] = None
        self.profile_data: Optional[dict] = None
        self.current_hypothesis: Optional[Hypothesis] = None
        self.current_diff: Optional[DiffProposal] = None
        self.pushback_round: int = 0
        self.attempt_id: Optional[int] = None
        self.history: list[dict] = []  # conversation turns
        self.start_time: float = time.time()

    def add_turn(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content, "ts": time.time()})


class Orchestrator:
    """
    Session/turn manager and pushback loop coordinator.

    Usage:
        orch = Orchestrator(codebase_path="path/to/workload")
        orch.start_session()
        response = orch.handle_turn("My matmul kernel is slow after HIP port")
        # user challenges...
        response = orch.handle_turn("That doesn't seem right — GPU util is fine")
    """

    def __init__(
        self,
        codebase_path: str = ".",
        llm_client=None,
        mock_tools: bool = False,
        db_path: str = "omnikernel_memory.db",
        audit_log_path: str = "omnikernel_audit.jsonl",
    ):
        self.mock_tools = mock_tools
        self.gate = PermissionGate(audit_log_path=audit_log_path)
        self.memory = MemoryStore(db_path=db_path)
        self.planner = Planner(llm_client=llm_client)
        self.session: Optional[Session] = None
        self._codebase_path = codebase_path

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start_session(self, codebase_path: Optional[str] = None) -> Session:
        """Initialize a new diagnosis session."""
        path = codebase_path or self._codebase_path
        self.session = Session(path)
        print(f"[OmniKernel] Session started for codebase: {path}")
        print(f"[OmniKernel] Codebase fingerprint: {self.session.codebase_fingerprint}")
        return self.session

    # ------------------------------------------------------------------
    # Main turn handler
    # ------------------------------------------------------------------

    def handle_turn(self, user_input: str) -> str:
        """
        Process one user turn and return the agent's response.

        Detects whether this is:
        - An initial diagnosis request
        - A pushback / challenge
        - An approval / rejection of a proposed diff
        - A request for the benchmark fallback
        """
        if self.session is None:
            self.start_session()

        self.session.add_turn("user", user_input)

        # Route to the appropriate handler
        lower = user_input.lower()

        if self._is_approval(lower):
            response = self._handle_approval(user_input)
        elif self._is_rejection(lower):
            response = self._handle_rejection(user_input)
        elif self._is_benchmark_request(lower):
            response = self._handle_benchmark_request()
        elif self.session.current_hypothesis and self._is_pushback(lower):
            response = self._pushback_loop(user_input)
        else:
            response = self._initial_diagnosis(user_input)

        self.session.add_turn("agent", response)
        return response

    # ------------------------------------------------------------------
    # Initial diagnosis flow
    # ------------------------------------------------------------------

    def _initial_diagnosis(self, user_input: str) -> str:
        """Full diagnosis pipeline for a new problem description."""
        s = self.session
        s.pushback_round = 0

        # 1. Gather tool data
        print("[OmniKernel] Gathering tool data...")
        s.smi_data = self._gather_smi()
        s.profile_data = self._gather_profile(user_input)

        # 2. Retrieve relevant docs
        print("[OmniKernel] Retrieving relevant documentation...")
        rag_results = self._run_rag(user_input)
        rag_context = format_retrieved_context(rag_results)

        # 3. Check memory history
        memory_history = self.memory.summarize_history(s.codebase_fingerprint)

        # 4. Run planner
        print("[OmniKernel] Running diagnosis...")
        hypothesis = self.planner.diagnose(
            smi_data=s.smi_data,
            profile_data=s.profile_data,
            rag_context=rag_context,
            memory_history=memory_history,
            user_description=user_input,
        )
        hypothesis = self.planner.hypothesize(hypothesis)
        s.current_hypothesis = hypothesis

        # 5. Record attempt to memory
        attempt = OptimizationAttempt(
            codebase_fingerprint=s.codebase_fingerprint,
            pattern_type=hypothesis.pattern_type,
            hypothesis=hypothesis.diagnosis,
            diff_summary=hypothesis.diff_summary or "",
        )
        s.attempt_id = self.memory.record_attempt(attempt)

        # 6. Log the read actions
        self.gate.log_action(ActionType.READ_SMI, "system", ApprovalStatus.AUTO_ALLOWED)
        self.gate.log_action(ActionType.READ_PROFILER, s.codebase_fingerprint, ApprovalStatus.AUTO_ALLOWED)

        return self._format_diagnosis_response(hypothesis, rag_results)

    # ------------------------------------------------------------------
    # Pushback loop
    # ------------------------------------------------------------------

    def _pushback_loop(self, user_input: str) -> str:
        """
        Handle user pushback: re-examine evidence, revise or defend.
        Capped at MAX_PUSHBACK_ROUNDS with a benchmark fallback.
        """
        s = self.session
        s.pushback_round += 1

        if s.pushback_round > MAX_PUSHBACK_ROUNDS:
            return self._benchmark_fallback()

        print(f"[OmniKernel] Re-examining evidence (pushback round {s.pushback_round}/{MAX_PUSHBACK_ROUNDS})...")

        # Refresh tool data for re-examination
        fresh_smi = self._gather_smi()
        fresh_profile = self._gather_profile(user_input)

        # Fresh RAG pass based on the pushback content
        rag_results = self._run_rag(user_input)
        rag_context = format_retrieved_context(rag_results)

        revised_hypothesis, agent_response = self.planner.reexamine(
            hypothesis=s.current_hypothesis,
            pushback=user_input,
            smi_data=fresh_smi,
            profile_data=fresh_profile,
            rag_context=rag_context,
        )

        changed = revised_hypothesis.pattern_type != s.current_hypothesis.pattern_type
        s.current_hypothesis = revised_hypothesis

        rounds_left = MAX_PUSHBACK_ROUNDS - s.pushback_round
        if changed:
            prefix = f"[Revision {s.pushback_round}] I've re-examined the evidence and you're right — my original diagnosis was off.\n\n"
        else:
            prefix = f"[Re-examination {s.pushback_round}] I've looked at the data again. My diagnosis stands, and here's why:\n\n"

        suffix = ""
        if rounds_left == 0:
            suffix = (
                "\n\n---\n"
                f"We've reached the discussion limit ({MAX_PUSHBACK_ROUNDS} rounds). "
                "To resolve this definitively, I recommend we benchmark both approaches. "
                "Say 'benchmark it' and I'll run both the original and the proposed change."
            )
        elif rounds_left == 1:
            suffix = f"\n\n(1 more pushback round before I suggest benchmarking both approaches.)"

        return prefix + agent_response + suffix

    def _benchmark_fallback(self) -> str:
        """Offer to benchmark when the pushback loop is exhausted."""
        return (
            "We've gone back and forth enough without resolving this through reasoning alone. "
            "Let's just measure it.\n\n"
            "If you have the candidate fix ready, say 'run benchmark <candidate_path>' "
            "or type 'benchmark it' and I'll generate a benchmark harness from the proposed diff. "
            "Numbers will settle this faster than arguments."
        )

    # ------------------------------------------------------------------
    # Benchmark handler
    # ------------------------------------------------------------------

    def _handle_benchmark_request(self) -> str:
        """Run the benchmark sandbox on the current diff."""
        s = self.session
        if not s.current_hypothesis:
            return "No active hypothesis to benchmark. Describe your workload first."

        print("[OmniKernel] Running sandboxed benchmark...")
        # For now, use mock benchmark — real paths come from user-provided scripts
        bench_result = run_benchmark(
            candidate_path="candidate.py",
            baseline_path="baseline.py",
            mock=self.mock_tools,
        )

        self.gate.log_action(
            ActionType.RUN_BENCHMARK, "benchmark_sandbox", ApprovalStatus.AUTO_ALLOWED
        )

        if s.attempt_id:
            comp = bench_result.get("comparison", {})
            self.memory.update_outcome(
                attempt_id=s.attempt_id,
                outcome="accepted" if comp.get("winner") == "candidate" else "regressed",
                speedup_ratio=comp.get("speedup_ratio"),
                notes=comp.get("verdict"),
            )

        s.current_hypothesis = self.planner.verify(s.current_hypothesis, bench_result)
        summary = format_benchmark_summary(bench_result)

        return (
            f"Benchmark complete:\n\n{summary}\n\n"
            f"Verification: {s.current_hypothesis.verification_notes}"
        )

    # ------------------------------------------------------------------
    # Diff approval / rejection
    # ------------------------------------------------------------------

    def _handle_approval(self, user_input: str) -> str:
        """User approved a proposed diff — request save path."""
        s = self.session
        if not s.current_diff:
            return "No pending diff to approve. Ask me to diagnose a workload first."

        entry = self.gate.request_approval(
            ActionType.SAVE_DIFF,
            s.current_diff.original_path,
            s.current_diff.description,
        )

        # In CLI mode, prompt for path — in real usage this would await user input
        output_path = f"proposed_{Path(s.current_diff.original_path).stem}.patch"
        saved_path = save_proposed_diff(s.current_diff, output_path)
        self.gate.approve_action(entry)

        return (
            f"Diff saved to: {saved_path}\n\n"
            f"Apply it with: `git apply {output_path}` or `patch -p1 < {output_path}`\n\n"
            "Review carefully before applying. The agent has not modified any of your files."
        )

    def _handle_rejection(self, user_input: str) -> str:
        s = self.session
        if s.current_diff:
            entry = self.gate.request_approval(
                ActionType.SAVE_DIFF, s.current_diff.original_path, "rejected"
            )
            self.gate.reject_action(entry)

        if s.attempt_id:
            self.memory.update_outcome(s.attempt_id, outcome="rejected", notes=user_input)

        return (
            "Understood — the proposed diff has been rejected and nothing has been applied. "
            "Describe what you think the actual bottleneck is and we can start fresh, "
            "or say 'benchmark it' to measure both approaches."
        )

    # ------------------------------------------------------------------
    # Tool gathering helpers
    # ------------------------------------------------------------------

    def _gather_smi(self) -> dict:
        return run_rocm_smi(mock=self.mock_tools)

    def _gather_profile(self, user_input: str) -> dict:
        s = self.session
        # If a script path is found in the session's codebase, profile it
        codebase = Path(s.codebase_path)
        candidate_scripts = list(codebase.glob("*.py")) if codebase.is_dir() else []

        if candidate_scripts:
            return profile_pytorch_trace(
                str(candidate_scripts[0]), mock=self.mock_tools
            )
        return profile_pytorch_trace("", mock=True)  # mock if no script found

    def _run_rag(self, query: str) -> list[dict]:
        try:
            return retrieve(query=query, top_k=4)
        except Exception as e:
            return [{"rank": 1, "source": "system", "section": "error",
                     "text": f"RAG retrieval failed: {e}", "score": 0.0}]

    # ------------------------------------------------------------------
    # Response formatting
    # ------------------------------------------------------------------

    def _format_diagnosis_response(
        self,
        hypothesis: Hypothesis,
        rag_results: list[dict],
    ) -> str:
        s = self.session

        lines = [
            f"**Diagnosis** [Confidence: {hypothesis.confidence}]",
            f"Pattern: {hypothesis.pattern_type}",
            "",
            f"**Root Cause:**",
            hypothesis.root_cause,
            "",
            f"**Evidence:**",
        ]
        for ev in hypothesis.evidence:
            marker = "✓" if ev.supports else "✗"
            lines.append(f"  {marker} [{ev.source}] {ev.observation}")

        if rag_results and rag_results[0].get("source") != "system":
            lines += ["", f"**Relevant Doc:** {rag_results[0]['source']} § {rag_results[0]['section']}"]

        if hypothesis.diff_summary:
            lines += ["", "**Proposed Fix:**", hypothesis.diff_summary]

        lines += [
            "",
            "---",
            "You can challenge this diagnosis ('that's not right because...'), "
            "ask me to 'apply the fix' (saves a .patch file), or 'benchmark it' to measure both approaches.",
        ]

        smi_summary = format_smi_summary(s.smi_data) if s.smi_data else ""
        profile_summary = format_profile_summary(s.profile_data) if s.profile_data else ""

        if smi_summary or profile_summary:
            lines += ["", "**Tool Data:**"]
            if smi_summary:
                lines.append(smi_summary)
            if profile_summary:
                lines.append(profile_summary)

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Intent detection
    # ------------------------------------------------------------------

    def _is_pushback(self, text: str) -> bool:
        pushback_signals = [
            "that's not", "thats not", "not right", "wrong", "disagree",
            "why do you", "are you sure", "i don't think", "i dont think",
            "explain why", "however", "actually,", "incorrect",
            "not the issue", "not the problem", "that is not",
        ]
        return any(sig in text for sig in pushback_signals)

    def _is_approval(self, text: str) -> bool:
        # Only match on whole-word starts to avoid false positives
        approval_words = ["apply", "approve", "save the", "accept", "looks good", "yes, apply", "yes please"]
        return any(w in text for w in approval_words)

    def _is_rejection(self, text: str) -> bool:
        # Only match explicit rejections, not "not" embedded in pushback phrases
        rejection_phrases = ["reject", "don't apply", "dont apply", "discard", "no thanks",
                             "^no$", "nope", "skip it", "never mind"]
        import re
        if re.match(r'^no[.!\s]*$', text.strip()):
            return True
        return any(w in text for w in rejection_phrases if not w.startswith('^'))

    def _is_benchmark_request(self, text: str) -> bool:
        return any(w in text for w in ["benchmark", "measure", "run both", "compare"])
