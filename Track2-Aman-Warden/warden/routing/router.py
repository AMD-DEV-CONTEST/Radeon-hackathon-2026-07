"""
The Intelligent Routing Engine — Warden's central nervous system.

Every input flows through this router. It decides:
1. WHAT tier(s) to invoke (Tier 0 / Tier 1 / Tier 2)
2. IN WHAT ORDER (cascade: cheap first, escalate if uncertain)
3. WHETHER to batch with other pending checks (GPU efficiency)
4. WHETHER to skip entirely (known-safe / known-blocked from memory)

NOTE: the P-LLM / Q-LLM trust-based routing path was prototyped but
descoped for this hackathon (see progress.md "Known Gaps"). The router
runs the tier cascade regardless of trust; tool-call data-flow
enforcement lives in the CaMeL capability tracker, not here.
"""

from __future__ import annotations

import logging
import hashlib
from typing import Optional

from warden.config import Decision, RoutingConfig, WardenConfig
from warden.tiers.base import CheckResult, RoutingResult, SecurityEvent
from warden.tiers.tier0_regex import Tier0RegexChecker
from warden.tiers.tier1_classifier import Tier1Classifier
from warden.tiers.tier2_llm import Tier2LLM

logger = logging.getLogger(__name__)


class ThrottleRouter:
    """
    The Intelligent Routing Engine.

    Routing Decision Matrix (descoped: dual-LLM P/Q path removed):
    ┌──────────────┬──────────────┬──────────────┬────────────────┐
    │ Source       │ Confidence  │ Tier reached │ Action         │
    ├──────────────┼──────────────┼──────────────┼────────────────┤
    │ Any          │ High threat  │ Tier 0       │ BLOCK          │
    │ Any          │ Ambiguous    │ → Tier 1     │ Re-evaluate    │
    │ Any          │ Low (T1)     │ → Tier 2     │ GPU escalation │
    │ Known-bad    │ —            │ Memory skip  │ AUTO-BLOCK     │
    │ Known-safe   │ —            │ Memory skip  │ ALLOW          │
    └──────────────┴──────────────┴──────────────┴────────────────┘

    Tool-call data-flow enforcement (untrusted data in control args)
    is handled by the CaMeL capability tracker in the orchestrator, not
    in the router itself.
    """

    def __init__(
        self,
        tier0: Tier0RegexChecker,
        tier1: Optional[Tier1Classifier] = None,
        tier2: Optional[Tier2LLM] = None,
        memory: Optional[object] = None,       # AuditLog (optional)
        rag: Optional[object] = None,          # WardenRetriever (optional)
        policy: Optional[object] = None,       # PolicyEngine (optional)
        config: Optional[RoutingConfig] = None,
        pattern_tracker: Optional[object] = None, # PatternTracker (optional)
    ):
        self.tier0 = tier0
        self.tier1 = tier1
        self.tier2 = tier2
        self.memory = memory
        self.rag = rag
        self.policy = policy
        self.pattern_tracker = pattern_tracker
        self.config = config or RoutingConfig()

        # Stats tracking
        self._stats = {
            "total_checks": 0,
            "tier0_resolved": 0,
            "tier1_resolved": 0,
            "tier2_resolved": 0,
            "memory_shortcuts": 0,
            "policy_shortcuts": 0,
        }

        # Initialize Batch Scheduler if Tier 2 and batching are enabled
        self.batch_scheduler = None
        # Use getattr to safely check enable_batch in case config is RoutingConfig
        enable_batch = getattr(self.config, "enable_batch", True)
        if self.tier2 and enable_batch:
            from warden.routing.batch_scheduler import BatchScheduler
            # Wrap tier2.check_injection to handle batches
            def _tier2_batch_executor(texts: list[str], contexts: list[str]) -> list[CheckResult]:
                if hasattr(self.tier2, "check_injection_batch"):
                    return self.tier2.check_injection_batch(texts, contexts)
                return [self.tier2.check_injection(t, c) for t, c in zip(texts, contexts)]
            
            # self.config could be WardenConfig (which has .routing.max_batch_size) 
            # or RoutingConfig (which has .max_batch_size directly)
            max_batch = getattr(self.config, "max_batch_size", getattr(getattr(self.config, "routing", None), "max_batch_size", 8))
            batch_window = getattr(self.config, "batch_window_ms", getattr(getattr(self.config, "routing", None), "batch_window_ms", 100))

            self.batch_scheduler = BatchScheduler(
                executor_fn=_tier2_batch_executor,
                max_batch_size=max_batch,
                batch_window_ms=batch_window
            )

    def route(self, text: str, source: str = "unknown") -> RoutingResult:
        """
        Main routing logic. Returns the full decision chain.
        """
        result = RoutingResult()
        result.start_timer()
        self._stats["total_checks"] += 1

        input_hash = hashlib.sha256(text.encode()).hexdigest()

        # Step 1: Memory shortcut
        if self.memory:
            try:
                if hasattr(self.memory, 'is_known_blocked') and self.memory.is_known_blocked(input_hash):
                    self._stats["memory_shortcuts"] += 1
                    return self._record_and_return(result.auto_block("Previously blocked pattern"), text, input_hash, source, skip_tracker=True)
                if hasattr(self.memory, 'is_known_safe') and self.memory.is_known_safe(input_hash):
                    self._stats["memory_shortcuts"] += 1
                    return self._record_and_return(result.auto_allow("Previously verified safe"), text, input_hash, source, skip_tracker=True)
            except Exception as e:
                logger.warning(f"Memory check failed (degraded): {e}")

        # Step 2: Policy check & shortcut
        policy_flag_warning = ""
        if self.policy:
            try:
                if hasattr(self.policy, 'evaluate'):
                    policy_decision = self.policy.evaluate(text, source)
                    if policy_decision:
                        if policy_decision.get("is_definitive"):
                            self._stats["policy_shortcuts"] += 1
                            decision = Decision(policy_decision["decision"])
                            return self._record_and_return(result.policy_decision(decision, policy_decision.get("reason", "")), text, input_hash, source)
                        elif policy_decision.get("decision") == "flag":
                            policy_flag_warning = policy_decision.get("reason", "Policy rule flagged content")
            except Exception as e:
                logger.warning(f"Policy check failed (degraded): {e}")

        # Step 3: Tier 0 (regex, ~0ms)
        t0_result = self.tier0.check(text)
        result.add_tier_result(0, t0_result)

        if t0_result.is_definitive:
            if t0_result.decision == Decision.ALLOW and policy_flag_warning:
                logger.debug("Tier 0 ALLOW overridden by policy FLAG — escalating to deeper tiers")
            else:
                self._stats["tier0_resolved"] += 1
                return self._record_and_return(result.finalize(t0_result.decision, t0_result.explanation), text, input_hash, source)

        # NOTE: user_direct fast-path REMOVED — persona jailbreaks, soft instruction
        # overrides and multi-turn adversarial attacks score 0 at Tier 0 and must
        # reach Tier 1 (NLP classifier) for semantic evaluation. All uncertain Tier 0
        # results now escalate to Tier 1 regardless of source.
        # See: GitHub issue "persona jailbreak 'You are Alex' slipped through router"

        # Step 4: Tier 1 (classifier, ~20ms) — only if available
        if self.tier1 and self.tier1.is_available():
            t1_result = self.tier1.check(text)
            result.add_tier_result(1, t1_result)

            if t1_result.confidence >= self.config.auto_block:
                self._stats["tier1_resolved"] += 1
                return self._record_and_return(result.finalize(Decision.BLOCK, f"High-confidence threat (Tier 1: {t1_result.confidence:.2f})"), text, input_hash, source)

            if t1_result.confidence <= self.config.auto_allow:
                if policy_flag_warning:
                    logger.debug("Tier 1 ALLOW overridden by policy FLAG — escalating to GPU tier")
                else:
                    self._stats["tier1_resolved"] += 1
                    return self._record_and_return(result.finalize(Decision.ALLOW, f"High-confidence clean (Tier 1: {t1_result.confidence:.2f})"), text, input_hash, source)

        # Step 5: RAG augment (only for uncertain cases heading to Tier 2)
        rag_context = ""
        if self.rag:
            try:
                if hasattr(self.rag, 'retrieve_for_check'):
                    rag_result = self.rag.retrieve_for_check(text)
                    rag_context = str(rag_result) if rag_result else ""
                    result.rag_context_used = bool(rag_context)
            except Exception as e:
                logger.warning(f"RAG retrieval failed (degraded): {e}")

        # Step 6: Tier 2 (GPU LLM, ~500ms) — only if available
        if self.tier2 and self.tier2.is_available():
            if self.batch_scheduler:
                t2_result = self.batch_scheduler.submit(text, context=rag_context)
            else:
                t2_result = self.tier2.check(text, context=rag_context)
                
            result.add_tier_result(2, t2_result)
            # Only count as resolved if it ran without errors and returned a definitive or flag answer
            if not getattr(t2_result, "errored", False) and (t2_result.decision != Decision.UNCERTAIN or t2_result.confidence != 0.5):
                self._stats["tier2_resolved"] += 1
            
            final_decision = t2_result.decision
            final_exp = t2_result.explanation
            if final_decision == Decision.ALLOW and policy_flag_warning:
                final_decision = Decision.FLAG
                final_exp = f"{final_exp} (Warning: {policy_flag_warning})"
            return self._record_and_return(result.finalize(final_decision, final_exp), text, input_hash, source)

        # Fallback: if we get here, no tier gave a definitive answer
        if result.tier_results:
            last = result.tier_results[-1]
            if last.confidence >= 0.5 or policy_flag_warning:
                exp = policy_flag_warning or "Uncertain — flagged for review"
                return self._record_and_return(result.finalize(Decision.FLAG, exp), text, input_hash, source)
            else:
                return self._record_and_return(result.finalize(Decision.ALLOW, "No definitive threat detected (limited tiers available)"), text, input_hash, source)

        if policy_flag_warning:
            return self._record_and_return(result.finalize(Decision.FLAG, policy_flag_warning), text, input_hash, source)
        return self._record_and_return(result.finalize(Decision.ALLOW, "No checks performed"), text, input_hash, source)

    def _record_and_return(self, result: RoutingResult, text: str, input_hash: str, source: str, skip_tracker: bool = False) -> RoutingResult:
        """Record event to AuditLog and PatternTracker, then return."""
            
        # 1. Log to SQLite audit db if connected
        if self.memory and hasattr(self.memory, 'log_event'):
            try:
                event = SecurityEvent(
                    input_hash=input_hash,
                    input_preview=text[:200],
                    source=source,
                    trust_level="trusted" if source == "user_direct" else "untrusted",
                    tier_reached=result.tier_reached,
                    decision=result.decision.value if result.decision else "unknown",
                    confidence=result.confidence,
                    latency_ms=result.total_latency_ms,
                    explanation_chain=[result.explanation] if result.explanation else [],
                )
                self.memory.log_event(event)
            except Exception as e:
                logger.warning(f"Failed to record audit event: {e}")

        # 2. Track repeat offender patterns for auto-blocking
        if not skip_tracker and self.pattern_tracker and hasattr(self.pattern_tracker, 'record'):
            try:
                self.pattern_tracker.record(
                    content_hash=input_hash,
                    decision=result.decision,
                    explanation=result.explanation
                )
            except Exception as e:
                logger.warning(f"Failed to record in pattern tracker: {e}")

        return result

    def get_stats(self) -> dict:
        """Return routing statistics for benchmarking."""
        total = self._stats["total_checks"] or 1
        return {
            **self._stats,
            "tier0_pct": self._stats["tier0_resolved"] / total * 100,
            "tier1_pct": self._stats["tier1_resolved"] / total * 100,
            "tier2_pct": self._stats["tier2_resolved"] / total * 100,
            "memory_pct": self._stats["memory_shortcuts"] / total * 100,
            "gpu_utilization_pct": self._stats["tier2_resolved"] / total * 100,
        }
