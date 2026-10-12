import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field

from warden.config import Decision
from warden.routing.router import ThrottleRouter
from warden.camel.interpreter import CaMeLInterpreter
from warden.guards.diff_guard import DiffGuard
from warden.guards.policy import PolicyEngine
from warden.memory.audit_log import AuditLog

logger = logging.getLogger(__name__)

@dataclass
class GuardResult:
    """Result of an orchestrator guard check."""
    is_safe: bool
    decision: Decision
    explanation: str
    action: str = ""  # 'block', 'allow', 'log_only'
    extracted_data: Optional[Dict] = None


@dataclass
class GuardJob:
    """One unit of work for the orchestrator batch queue."""
    kind: str                       # "input" | "tool_call" | "commit"
    payload: Any
    context: str = ""
    result: Optional[GuardResult] = None
    error: str = ""


class WardenOrchestrator:
    """
    The main entry point for Warden integration.
    
    Acts as a native, dependency-free wrapper around all security modules.
    Intercepts:
    - Inputs (raw user/external data)
    - Tool calls (before execution)
    - Code Commits (diffs before applying)
    
    Modes:
    - ACTIVE: Enforces blocks and policy-based data-flow checks (CaMeL capability tracker)
    - SHADOW: Logs everything, allows everything (for enterprise onboarding)
    - REPORT: (Future) offline analysis mode
    """

    def __init__(
        self,
        router: ThrottleRouter,
        camel: CaMeLInterpreter,
        diff_guard: DiffGuard,
        policy: PolicyEngine,
        audit: AuditLog,
        mode: str = "active",
        batch_workers: int = 4,
    ):
        self.router = router
        self.camel = camel
        self.diff_guard = diff_guard
        self.policy = policy
        self.audit = audit
        self.mode = mode.lower()
        self.batch_workers = batch_workers

    def guard_input(self, text: str, source: str) -> GuardResult:
        """
        Intercept raw input coming from an external source or user.
        Routes it through the Intelligent Routing Engine.
        """
        logger.info(f"[Orchestrator] Guarding input from {source}")
        
        # 1. Route the input through the tier cascade
        routing_result = self.router.route(text=text, source=source)
        decision = routing_result.decision
        
        # 2. Apply Shadow Mode override
        if self.mode == "shadow":
            if decision in (Decision.BLOCK, Decision.FLAG):
                logger.warning(f"[Orchestrator][SHADOW MODE] Would have applied {decision.name}, but allowing.")
            return GuardResult(
                is_safe=True,
                decision=decision,
                explanation=routing_result.explanation,
                action="log_only"
            )

        # 3. Handle Active Mode Decisions
        if decision == Decision.BLOCK:
            return GuardResult(
                is_safe=False,
                decision=decision,
                explanation=routing_result.explanation,
                action="block"
            )
            
        # Default fallback for ALLOW/UNCERTAIN in Active Mode
        return GuardResult(
            is_safe=True,
            decision=decision,
            explanation=routing_result.explanation,
            action="allow"
        )

    def guard_tool_call(self, tool_name: str, args: Dict[str, Any], context: str = "") -> GuardResult:
        """
        Intercept a tool call before execution by the LLM.
        Applies the CaMeL capability tracker (data-flow / policy enforcement).
        """
        logger.info(f"[Orchestrator] Guarding tool call: {tool_name}")
        
        # 1. CaMeL Capability Tracker (Data Flow)
        is_safe = self.camel.check_tool_call(tool_name, args)
        if not is_safe:
            msg = f"Data flow or policy violation on tool '{tool_name}'"
            if self.mode == "shadow":
                logger.warning(f"[Orchestrator][SHADOW MODE] {msg}")
            else:
                return GuardResult(is_safe=False, decision=Decision.BLOCK, explanation=msg, action="block")

        # 2. Policy Engine (Declarative Rules)
        policy_result = self.policy.evaluate_tool_call(tool_name, args)
        if policy_result and policy_result.get("decision") == "block":
            msg = f"Policy violation: {policy_result.get('reason', 'Blocked by policy')}"
            if self.mode == "shadow":
                logger.warning(f"[Orchestrator][SHADOW MODE] {msg}")
            else:
                return GuardResult(is_safe=False, decision=Decision.BLOCK, explanation=msg, action="block")
                
        return GuardResult(is_safe=True, decision=Decision.ALLOW, explanation="Tool call authorized", action="allow")

    def guard_code_commit(self, diff: str) -> GuardResult:
        """
        Intercept a code patch before it is applied to the codebase.
        Uses DiffGuard (Semgrep + LLM).
        """
        logger.info("[Orchestrator] Guarding code commit via DiffGuard")
        
        scan_result = self.diff_guard.scan_diff(diff)
        
        if scan_result.has_findings:
            max_severity = scan_result.max_severity
            findings_summary = ", ".join([f"{v.vuln_type} ({v.severity})" for v in scan_result.vulnerabilities])
            msg = f"Vulnerabilities found by {scan_result.scanner}: {findings_summary}"
            
            if self.mode == "shadow":
                logger.warning(f"[Orchestrator][SHADOW MODE] {msg}")
                return GuardResult(is_safe=True, decision=Decision.FLAG, explanation=msg, action="log_only")
                
            # Usually block on critical/high, flag on medium/low
            if max_severity in ("critical", "high"):
                return GuardResult(is_safe=False, decision=Decision.BLOCK, explanation=msg, action="block")
            else:
                return GuardResult(is_safe=True, decision=Decision.FLAG, explanation=msg, action="allow")

        return GuardResult(is_safe=True, decision=Decision.ALLOW, explanation="No vulnerabilities detected", action="allow")

    # ------------------------------------------------------------------
    # Batch queue: concurrent diff/scan dispatch
    # ------------------------------------------------------------------

    def guard_batch(self, jobs: List[GuardJob]) -> List[GuardJob]:
        """Dispatch multiple guard checks concurrently and return them
        in submission order.

        Why: an agent editing a repo submits N diffs or fetches M
        external blobs in one turn. Guarding them serially (each ~20ms
        Tier 1 + possibly ~500ms Tier 2) turns a burst into a stall.
        This queue runs up to `batch_workers` checks in parallel and
        preserves call order on the result list so callers can zip
        results back to the originating jobs.

        Tiers are already thread-safe enough for this: Tier 0 is pure
        regex, Tier 1 is a loaded transformer (read-only inference),
        and Tier 2's BatchScheduler serializes GPU execution under a
        lock. Audit writes go through SQLite (single-writer, safe).
        """
        if not jobs:
            return jobs
        workers = max(1, min(self.batch_workers, len(jobs)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._dispatch_one, job): job
                for job in jobs
            }
            for future in as_completed(futures):
                job = futures[future]
                try:
                    job.result = future.result()
                except Exception as e:
                    job.error = str(e)
                    logger.error(f"Batch guard job ({job.kind}) failed: {e}")
        return jobs

    def _dispatch_one(self, job: GuardJob) -> GuardResult:
        """Route one batch job to the right guard. Raises on unknown kind."""
        if job.kind == "input":
            return self.guard_input(job.payload, job.context or "unknown")
        if job.kind == "tool_call":
            args = job.payload if isinstance(job.payload, dict) else {"args": job.payload}
            return self.guard_tool_call(args.get("tool_name", "unknown"), args.get("args", {}), job.context)
        if job.kind == "commit":
            return self.guard_code_commit(job.payload)
        raise ValueError(f"Unknown batch job kind: {job.kind}")

    def batch_inputs(self, texts: List[str], source: str = "unknown") -> List[GuardResult]:
        """Convenience: guard N inputs concurrently, results in order."""
        jobs = [GuardJob(kind="input", payload=t, context=source) for t in texts]
        return [j.result for j in self.guard_batch(jobs)]

    def batch_diffs(self, diffs: List[str]) -> List[GuardResult]:
        """Convenience: scan N code diffs concurrently, results in order."""
        jobs = [GuardJob(kind="commit", payload=d) for d in diffs]
        return [j.result for j in self.guard_batch(jobs)]
