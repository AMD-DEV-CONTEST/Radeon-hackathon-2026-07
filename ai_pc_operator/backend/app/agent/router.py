"""Agent router - main command processing pipeline.

This is the core of the agent brain. It receives user commands,
classifies intent, assesses risk, plans actions, and executes tools.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Optional, Dict, Any, List

from app.agent.llm_planner import LLMPlanner
from app.agent.external_planner import ExternalPlanner
from app.agent.planner import Planner
from app.agent.task_planner import TaskPlanner
from app.agent.memory import Memory
from app.security.risk import RiskClassifier
from app.security.permissions import PermissionEngine
from app.approvals.manager import ApprovalManager
from app.tools.system_tools import SystemTools
from app.tools.file_tools import FileTools
from app.tools.browser_tools import BrowserTools
from app.tools.auth_tools import AuthTools
from app.tools.screen_tools import ScreenTools
from app.db.database import db_session
from app.logs.redactor import LogRedactor
from app.runtime.artifact_store import ArtifactStore
from app.runtime.heatmap import ToolHeatMap
from app.runtime.io_pool import IOPool
from app.runtime.model_loaders import (
    browser_warmup_loader,
    ocr_mobile_loader,
    qwen_gguf_loader,
    ui_detector_loader,
    vault_crypto_loader,
)
from app.runtime.model_insights import ModelInsights
from app.runtime.model_registry import ModelRegistry, ModelSpec
from app.runtime.resource_budget import ResourceBudget
from app.runtime.screen_cache import ScreenCache
from app.runtime.ssd_tier import SSDTierManager
from app.runtime.tier_manager import AgentTierManager
from app.runtime.strategy import StrategyRouter
from app.runtime.telemetry import Telemetry
from app.skills.registry import SkillRegistry
from app.skills.runtime import SkillRuntime
from app.skills.verification import VerificationEngine
from app.skills.mvp_pack import seed_mvp_skills
from app.agent.task_graph import TaskGraphExecutor, TaskContext
from app.agent.memory_engine import MemoryEngine
from app.agent.graph_schema import (
    NODE_TYPES as GRAPH_NODE_TYPES,
    RISK_LEVELS as GRAPH_RISK_LEVELS,
    plan_to_graph,
    validate_node as validate_graph_node,
    insert_approval_nodes as graph_insert_approval_nodes,
)
from app.observability.tracer import Tracer
from app.agent.intent_engine import IntentEngine, IntentResult
from app.agent.planner_engine import PlannerEngine, Plan

logger = logging.getLogger(__name__)


class AgentRouter:
    """Main agent router that processes commands."""

    def __init__(
        self,
        approval_manager: ApprovalManager,
        system_tools: SystemTools,
        file_tools: FileTools,
        browser_tools: BrowserTools,
        auth_tools: AuthTools,
        screen_tools: ScreenTools,
    ):
        """Initialize agent router."""
        self.planner = Planner()
        self.task_planner = TaskPlanner()
        self.llm_planner = LLMPlanner()
        self.external_planner = ExternalPlanner()
        self.memory = Memory()
        self.redactor = LogRedactor()
        self.risk_classifier = RiskClassifier()
        self.permission_engine = PermissionEngine()
        self.approval_manager = approval_manager
        self.resource_budget = ResourceBudget()
        self.io_pool = IOPool(max_workers=2)
        self.artifacts = ArtifactStore()
        self.model_insights = ModelInsights(self.artifacts)
        self.ssd_tier = SSDTierManager()
        self.screen_cache = ScreenCache()
        self.model_registry = ModelRegistry(self.resource_budget, self.io_pool, self.ssd_tier)
        self.heatmap = ToolHeatMap()
        self.tier_manager = AgentTierManager()
        self.strategy = StrategyRouter()
        self.telemetry = Telemetry()
        self._register_lazy_models()

        # New spec modules (ag.md §3-§7)
        self.skill_registry = SkillRegistry()
        self.verification_engine = VerificationEngine()
        self.skill_runtime = SkillRuntime(self.skill_registry, self.verification_engine)
        self.task_graph = TaskGraphExecutor(
            self.skill_registry,
            self.verification_engine,
        )
        self.memory_engine = MemoryEngine()
        self.tracer = Tracer()
        self._skills_seeded = False

        # Intent Engine + Planner Engine (new 6+7 stage pipelines)
        self.intent_engine = IntentEngine()
        self.planner_engine = PlannerEngine()

        # Tool registry
        self.tools = {
            "system": system_tools,
            "file": file_tools,
            "browser": browser_tools,
            "auth": auth_tools,
            "screen": screen_tools,
        }

        self.emergency_stopped = False

    # Natural-language status phrases per tool (Phase 6: user-visible status).
    # Keys support "{arg}" placeholders substituted from the step args.
    TOOL_STATUS_PHRASES: Dict[str, str] = {
        "system.open_app": "Opening {name}...",
        "system.close_app": "Closing {name}...",
        "system.capture_photo": "Capturing photo...",
        "system.keep_awake": "Keeping the PC awake...",
        "system.mouse_jiggle": "Moving the mouse to stay active...",
        "browser.open": "Opening {url}...",
        "browser.search": "Searching for {query}...",
        "browser.close": "Closing the browser...",
        "browser.download": "Downloading {url}...",
        "screen.click_text": "Clicking {text}...",
        "screen.scan": "Scanning the screen...",
        "file.list": "Listing files...",
        "file.read": "Reading file...",
        "file.quarantine": "Moving to quarantine...",
        "file.restore": "Restoring file...",
        "memory.remember": "Remembering that...",
        "memory.recall": "Recalling...",
    }

    def _register_lazy_models(self) -> None:
        """Register lazy model loaders for RAM-aware prefetch."""
        self.model_registry.register(
            ModelSpec("ocr-mobile", 160, ocr_mobile_loader(self.artifacts))
        )
        self.model_registry.register(
            ModelSpec("ui-detector-int8", 350, ui_detector_loader(self.artifacts))
        )
        self.model_registry.register(
            ModelSpec(
                "qwen-1.5b-q4",
                1200,
                qwen_gguf_loader(self.artifacts),
                idle_ttl_sec=300,
            )
        )
        self.model_registry.register(
            ModelSpec("vault-crypto", 64, vault_crypto_loader(self.artifacts))
        )
        self.model_registry.register(
            ModelSpec("browser-warmup", 128, browser_warmup_loader(self.artifacts))
        )

    async def process_command(
        self,
        text: str,
        device_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process a user command through the full pipeline.

        Pipeline:
        1. Save command to database
        2. Classify intent
        3. Assess risk
        4. Check permissions
        5. Request approval if needed
        6. Plan actions
        7. Execute tools
        8. Verify results
        9. Log and return
        """
        if self.emergency_stopped:
            return {
                "status": "blocked",
                "error": "Emergency stop is active",
            }

        logger.info(f"Processing command: {text}")
        pipeline_start = time.time()

        # Step 1: Save command
        command_id = await self._save_command(text, device_id)

        try:
            # Step 2: classify intent while a RAM snapshot runs off-loop.
            budget_task = asyncio.create_task(
                asyncio.to_thread(self.resource_budget.measure)
            )
            task_plan = self.task_planner.plan(text)
            intent = task_plan.intent if task_plan else await self.planner.classify_intent(text)
            budget = await budget_task
            ssd_plan = self.ssd_tier.plan(
                budget,
                self.artifacts,
                self.resource_budget.reserve_mb,
            )
            logger.info(f"Intent: {intent}")

            # Step 2a: Teach the planner from this command so future similar
            # inputs match even when phrasing differs.
            try:
                self.planner.remember(text, intent)
            except Exception:
                pass

            llm_plan: Dict[str, Any] | None = None
            qwen_allowed = self.ssd_tier.can_load("qwen-1.5b-q4", ssd_plan)
            if intent == "unknown" and budget.allow_llm and qwen_allowed:
                qwen = await self.model_registry.get("qwen-1.5b-q4")
                llm_plan = await self.llm_planner.create_plan(text, qwen)
                if llm_plan:
                    intent = llm_plan.get("intent", intent)
                    logger.info("LLM planner produced a plan for unknown intent")

            # Advisory external reasoning model (OpenAI-compatible endpoint).
            # Consulted only when intent is still unknown; the key comes from
            # the SCREEN_AI_EXTERNAL_API_KEY env var and is never logged.
            if intent == "unknown" and self.external_planner.is_configured():
                external_plan = await self.external_planner.create_plan(text)
                if external_plan:
                    llm_plan = external_plan
                    intent = external_plan.get("intent", intent)
                    logger.info(
                        "External reasoning model produced a plan for unknown intent"
                    )
            model_plan = self.model_insights.plan_for_command(
                text,
                intent,
                budget,
                self.heatmap.hot_models_for_intent(intent),
            )

            # Step 3: assess risk while runtime tiers/prefetch are decided.
            risk_task = asyncio.create_task(
                self.risk_classifier.assess(text, intent)
            )
            hot_models = self.heatmap.hot_models_for_intent(intent)
            tier_decision = self.tier_manager.decide(intent, budget, hot_models)
            prefetch_models = [
                name
                for name in [*tier_decision.prefetch_models, *model_plan.get("prefetch", [])]
                if self.ssd_tier.should_prefetch(name, ssd_plan)
            ]
            self.model_registry.prefetch(prefetch_models)
            self._prefetch_hot_tools(self.heatmap.hot_tools(intent), budget.model_budget_mb)
            risk_level = await risk_task
            if llm_plan:
                risk_level = max(risk_level, int(llm_plan.get("risk_level", 1)))
            logger.info(f"Risk level: {risk_level}")
            logger.info(f"Tier decision: {tier_decision}")
            await self._update_command_metadata(command_id, intent, risk_level)

            # Step 2b: Run Intent Engine + Planner Engine for enriched understanding
            engine_enrichment = self._run_intent_and_planner_engines(
                text, intent, {}
            )
            if engine_enrichment.get("enriched_params"):
                logger.info(
                    f"Engine enrichment: params={engine_enrichment['enriched_params']}"
                )

            # Step 4: Check permissions
            requires_approval = self.permission_engine.requires_approval(
                risk_level, intent
            )

            # Step 5: Request approval if needed. wait_for_approval uses
            # asyncio.wait_for and yields control while mobile approval is pending.
            if requires_approval:
                approval_id = await self.approval_manager.create_approval(
                    command_id=command_id,
                    risk_level=risk_level,
                    action_type=intent,
                    target=self.redactor.redact(text),
                    description=f"Execute: {self.redactor.redact(text)}",
                )

                # Wait for approval
                approved = await self.approval_manager.wait_for_approval(
                    approval_id, timeout=300
                )

                if not approved:
                    await self._update_command_status(
                        command_id, "rejected", "User rejected approval"
                    )
                    return {
                        "command_id": command_id,
                        "status": "rejected",
                        "result": "User rejected the action",
                    }

            # Step 6: Plan actions (cognitive planner when no compound/LLM plan)
            built = await self._build_cognitive_plan(
                text, intent, task_plan, llm_plan
            )
            plan = built["plan"]
            steps = built["steps"]
            cognitive_plan = built["cognitive_plan"]
            logger.info(f"Plan: {plan}")
            self.heatmap.record_plan(intent, steps)
            self._write_plan_cache(text, intent, plan, tier_decision.to_dict())

            if not steps:
                message = (
                    plan.get("error")
                    or "I could not map that command to a safe tool plan yet."
                )
                # Chat mode: when the command couldn't be mapped to tools,
                # answer conversationally (local rules first, then the
                # external model if configured).
                chat_reply: Optional[str] = None
                if intent == "unknown":
                    chat_reply = await self._chat_reply(text)
                response = {
                    "command_id": command_id,
                    "status": "chat" if chat_reply else "unsupported",
                    "result": chat_reply or message,
                    "requires_approval": requires_approval,
                    "runtime": tier_decision.to_dict(),
                    "ssd_tier": ssd_plan.to_dict(),
                    "model_plan": model_plan,
                    "cognitive_plan": cognitive_plan,
                }
                await self._update_command_status(
                    command_id,
                    response["status"],
                    response["result"],
                )
                await self.memory.add(self.redactor.redact(text), intent, response)
                return response

            # Step 7: Execute tools via strategy engine (circuit breaker + retry)
            results = []
            statuses: List[str] = []
            for step in steps:
                if self.emergency_stopped:
                    break

                tool_name = step.get("tool")
                tool_args = step.get("args", {})
                tool_start = time.time()

                # User-visible status (Phase 6): natural phrase per step.
                statuses.append(self._step_status(tool_name or "unknown", tool_args))

                # Use strategy engine for circuit breaker + adaptive retry
                async def _exec(tool, args):
                    return await self._execute_tool(tool, args, command_id)

                result = await self.strategy.execute_with_strategy(
                    tool_name, tool_args, _exec, intent=intent, command_id=command_id
                )

                # Record telemetry for tool call
                tool_latency = (time.time() - tool_start) * 1000
                self.telemetry.record_tool_call(
                    command_id, tool_name, tool_latency,
                    result.get("status") == "success"
                )
                results.append(result)

            # Step 8: Verify results
            verified = all(r.get("status") == "success" for r in results)

            # Step 8b: Wrap the plan in the planning-engine execution-graph schema
            goal = self._derive_goal(text, intent)
            execution_graph = self._build_execution_graph(plan, risk_level, goal=goal)

            # Step 9: Format response with telemetry + strategy data
            pipeline_ms = (time.time() - pipeline_start) * 1000
            response = {
                "command_id": command_id,
                "intent": intent,
                "risk": risk_level,
                "status": "completed" if verified else "partial",
                "result": self._format_results(results),
                "statuses": statuses,
                "goal": goal,
                "requires_approval": requires_approval,
                "runtime": tier_decision.to_dict(),
                "ssd_tier": ssd_plan.to_dict(),
                "model_plan": model_plan,
                "execution_graph": execution_graph,
                "cognitive_plan": cognitive_plan,
                "telemetry": {
                    "pipeline_ms": round(pipeline_ms, 1),
                    "tools_executed": len(results),
                    "tools_succeeded": sum(1 for r in results if r.get("status") == "success"),
                    "strategy": self.strategy.status(),
                },
                "engines": engine_enrichment,
            }

            await self._update_command_status(
                command_id,
                "completed" if verified else "partial",
                response["result"],
            )

            # Record intent success in telemetry
            self.telemetry.record_intent(intent)

            # Save to memory
            await self.memory.add(self.redactor.redact(text), intent, response)
            await self._maintenance()

            return response

        except Exception as e:
            logger.error(f"Error processing command: {e}", exc_info=True)
            await self._update_command_status(
                command_id, "failed", error=str(e)
            )
            return {
                "command_id": command_id,
                "status": "failed",
                "error": str(e),
            }
        finally:
            await self._maintenance()

    def _run_intent_and_planner_engines(
        self,
        text: str,
        intent: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run the Intent Engine and Planner Engine to enrich the plan.

        Returns a dict with:
            - intent_result: full IntentResult from IntentEngine
            - plan: full Plan from PlannerEngine
            - enriched_params: params merged with extracted entities
        """
        try:
            # Run Intent Engine for richer understanding
            intent_result: IntentResult = self.intent_engine.process(text)

            # Use intent engine's params if available, else fall back
            enriched_params = intent_result.params or params

            # Run Planner Engine for structured plan
            plan: Plan = self.planner_engine.plan(
                intent=intent,
                params=enriched_params,
            )

            return {
                "intent_result": intent_result.to_dict(),
                "plan": plan.to_dict(),
                "enriched_params": enriched_params,
            }
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"Intent/Planner engine enrichment failed: {e}")
            return {
                "intent_result": None,
                "plan": None,
                "enriched_params": params,
                "error": str(e),
            }

    def _build_execution_graph(
        self,
        plan: Dict[str, Any],
        risk_level: int,
        goal: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Wrap a legacy plan in the planning-engine execution-graph schema.

        Returns a dict with:
            - nodes: list of planning-engine nodes
            - validation: {ok, errors}
            - node_count: int
            - approval_required: bool
        """
        try:
            nodes = plan_to_graph(plan, risk_level=risk_level, goal=goal)
            validation = validate_graph_node(nodes)
            approval_required = any(
                n.get("type") == "approval" for n in nodes
            )
            return {
                "nodes": nodes,
                "validation": validation,
                "node_count": len(nodes),
                "approval_required": approval_required,
            }
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"Failed to build execution graph: {e}")
            return {
                "nodes": [],
                "validation": {"ok": False, "errors": [str(e)]},
                "node_count": 0,
                "approval_required": False,
            }

    async def _build_cognitive_plan(
        self,
        text: str,
        intent: str,
        task_plan: Any = None,
        llm_plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a plan for the command, attaching cognitive metadata when
        the regular planner produced it.

        Returns a dict with:
            - plan: the step-based plan (task/LLM plans keep their shape,
              otherwise the cognitive plan's execution_graph)
            - steps: list of tool steps
            - cognitive_plan: full cognitive metadata dict, or {} when the
              task/LLM planner produced the plan (they have their own shape)
        """
        cognitive_plan: Dict[str, Any] = {}
        if task_plan is not None:
            plan = task_plan.to_dict()
        elif llm_plan:
            plan = llm_plan
        else:
            try:
                cognitive_plan = await self.planner.create_cognitive_plan(
                    text, intent
                )
                plan = {"steps": cognitive_plan.get("execution_graph", [])}
            except Exception as e:  # defensive: never break the command path
                logger.warning(
                    "create_cognitive_plan failed, falling back: %s", e
                )
                plan = await self.planner.create_plan(text, intent)
        steps = plan.get("steps", [])
        return {
            "plan": plan,
            "steps": steps,
            "cognitive_plan": cognitive_plan,
        }

    async def _chat_reply(self, text: str) -> Optional[str]:
        """Return a conversational reply for a non-command message.

        Local rule-based smalltalk first (fast, no API cost); falls through
        to the external reasoning model when configured; otherwise None.
        """
        local = self._rule_chat_reply(text)
        if local:
            return local
        if self.external_planner.is_configured():
            try:
                reply = await self.external_planner.chat_reply(text)
                if reply:
                    return reply
            except Exception:  # defensive: chat must never break the pipeline
                logger.warning("external chat_reply failed")
        return None

    def _rule_chat_reply(self, text: str) -> Optional[str]:
        """Small local conversational rules for common non-command messages."""
        lower = (text or "").lower().strip()
        if not lower:
            return None
        if re.search(r"\b(hi|hello|hey|yo|howdy)\b", lower) and len(lower) < 40:
            return "Hello! I'm Screen-AI, your local desktop operator. What can I help you with?"
        if re.search(r"\b(how are you|how's it going|how do you do)\b", lower):
            return "I'm running smoothly. What would you like me to do on your PC?"
        if re.search(r"\b(who|what)\s+(are|is)\s+you\b", lower):
            return "I'm Screen-AI — a local AI desktop operator that can open apps, browse, manage files, and more, all on your machine."
        if re.search(r"\b(what can you do|what do you do|help me|capabilities|features)\b", lower):
            return "I can open apps and websites, search the web, manage files, check system status, take screenshots, and more. Just tell me what you need."
        if re.search(r"\b(thank you|thanks|thx|ty)\b", lower):
            return "You're welcome! Let me know if you need anything else."
        if re.search(r"\b(good\s*(morning|afternoon|evening)|good\s*night)\b", lower):
            return "Hello! What can I help you with?"
        return None

    async def preview_plan(self, text: str) -> Dict[str, Any]:
        """Return the planned interpretation of a command without executing it."""
        try:
            return await asyncio.wait_for(
                self._preview_plan_impl(text),
                timeout=25.0,
            )
        except asyncio.TimeoutError:
            logger.warning("preview_plan timed out for text=%r", text[:80])
            return {
                "status": "timeout",
                "input": self.redactor.redact(text),
                "intent": "unknown",
                "risk_level": 0,
                "requires_approval": False,
                "plan": {},
                "step_count": 0,
                "execution_graph": {
                    "nodes": [],
                    "validation": {"ok": False, "errors": ["preview timed out"]},
                    "node_count": 0,
                    "approval_required": False,
                },
                "runtime": {},
                "ssd_tier": {},
                "model_plan": {},
                "engines": {},
                "message": "Preview timed out. Try a simpler command or restart the server.",
            }
        except Exception as e:
            logger.exception("preview_plan failed: %s", e)
            return {
                "status": "failed",
                "input": self.redactor.redact(text),
                "intent": "unknown",
                "risk_level": 0,
                "requires_approval": False,
                "plan": {},
                "step_count": 0,
                "execution_graph": {
                    "nodes": [],
                    "validation": {"ok": False, "errors": [str(e)]},
                    "node_count": 0,
                    "approval_required": False,
                },
                "runtime": {},
                "ssd_tier": {},
                "model_plan": {},
                "engines": {},
                "message": f"Preview failed: {e}",
            }

    async def _preview_plan_impl(self, text: str) -> Dict[str, Any]:
        """Internal implementation of preview_plan with timeout protection."""
        budget = await asyncio.to_thread(self.resource_budget.measure)
        task_plan = self.task_planner.plan(text)
        intent = task_plan.intent if task_plan else await self.planner.classify_intent(text)
        ssd_plan = self.ssd_tier.plan(
            budget,
            self.artifacts,
            self.resource_budget.reserve_mb,
        )
        llm_plan: Dict[str, Any] | None = None
        qwen_allowed = self.ssd_tier.can_load("qwen-1.5b-q4", ssd_plan)
        if intent == "unknown" and budget.allow_llm and qwen_allowed:
            qwen = await self.model_registry.get("qwen-1.5b-q4")
            llm_plan = await self.llm_planner.create_plan(text, qwen)
            if llm_plan:
                intent = llm_plan.get("intent", intent)

        if intent == "unknown" and self.external_planner.is_configured():
            external_plan = await self.external_planner.create_plan(text)
            if external_plan:
                llm_plan = external_plan
                intent = external_plan.get("intent", intent)

        risk_level = await self.risk_classifier.assess(text, intent)
        if llm_plan:
            risk_level = max(risk_level, int(llm_plan.get("risk_level", 1)))
        requires_approval = self.permission_engine.requires_approval(
            risk_level,
            intent,
        )
        model_plan = self.model_insights.plan_for_command(
            text,
            intent,
            budget,
            self.heatmap.hot_models_for_intent(intent),
        )
        built = await self._build_cognitive_plan(text, intent, task_plan, llm_plan)
        plan = built["plan"]
        steps = built["steps"]
        cognitive_plan = built["cognitive_plan"]
        goal = self._derive_goal(text, intent)
        execution_graph = self._build_execution_graph(plan, risk_level, goal=goal)
        return {
            "status": "planned" if steps else "unsupported",
            "input": self.redactor.redact(text),
            "intent": intent,
            "risk_level": risk_level,
            "requires_approval": requires_approval,
            "plan": self.redactor.redact_dict(plan),
            "step_count": len(steps),
            "goal": goal,
            "execution_graph": execution_graph,
            "cognitive_plan": self.redactor.redact_dict(cognitive_plan)
            if cognitive_plan
            else {},
            "runtime": self.tier_manager.decide(
                intent,
                budget,
                self.heatmap.hot_models_for_intent(intent),
            ).to_dict(),
            "ssd_tier": ssd_plan.to_dict(),
            "model_plan": model_plan,
            "engines": self._run_intent_and_planner_engines(text, intent, {}),
            "message": (
                "Ready to execute after Send."
                if steps
                else plan.get("error", "No safe executable plan was found.")
            ),
        }

    async def _execute_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        command_id: int,
    ) -> Dict[str, Any]:
        """Execute a single tool."""
        try:
            # Parse tool name (e.g., "file.list" -> category="file", method="list")
            if "." in tool_name:
                category, method = tool_name.split(".", 1)
            else:
                category = "system"
                method = tool_name

            tool = self.tools.get(category)
            if not tool:
                return {
                    "status": "failed",
                    "error": f"Unknown tool category: {category}",
                }

            method_func = getattr(tool, method, None)
            if not method_func:
                return {
                    "status": "failed",
                    "error": f"Unknown method: {method}",
                }

            # Execute
            if asyncio.iscoroutinefunction(method_func):
                result = await method_func(**args)
            else:
                result = await self.io_pool.run(method_func, **args)

            tool_status = "success"
            if isinstance(result, dict) and result.get("status") == "failed":
                tool_status = "failed"

            # Log action
            await self._log_action(
                command_id, tool_name, args, result, tool_status
            )

            response = {
                "status": tool_status,
                "tool": tool_name,
                "result": result,
            }
            if tool_status == "failed":
                response["error"] = result.get("error", "Tool reported failure")
            return response

        except Exception as e:
            logger.error(f"Tool execution failed: {e}", exc_info=True)
            await self._log_action(
                command_id, tool_name, args, None, "failed", error=str(e)
            )
            return {
                "status": "failed",
                "tool": tool_name,
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # New spec API: skills, task graph, memory, observability
    # ------------------------------------------------------------------

    async def ensure_skills_seeded(self) -> int:
        """Seed the MVP skill pack on first boot. Idempotent."""
        if self._skills_seeded:
            return 0
        existing = await self.skill_registry.list(enabled_only=False)
        if existing:
            self._skills_seeded = True
            return 0
        count = await seed_mvp_skills(self.skill_registry)
        self._skills_seeded = True
        return count

    async def execute_skill(
        self,
        skill_id: str,
        inputs: Optional[Dict[str, Any]] = None,
        command_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute a registered skill by id."""
        await self.ensure_skills_seeded()
        await self.tracer.event(
            "act",
            skill_id=skill_id,
            payload={"inputs": inputs or {}},
        )
        result = await self.skill_runtime.execute(
            skill_id,
            inputs or {},
            command_id=command_id,
        )
        await self.tracer.event(
            "verify" if result.verification_passed else "error",
            skill_id=skill_id,
            payload={
                "status": result.status.value,
                "duration_ms": result.duration_ms,
                "verification_passed": result.verification_passed,
            },
            duration_ms=result.duration_ms,
        )
        return result.model_dump()

    async def run_task(
        self,
        name: str,
        nodes: List[Dict[str, Any]],
        command_id: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create and run a task graph (DAG)."""
        await self.ensure_skills_seeded()
        task = await self.task_graph.create_task(name, nodes, command_id=command_id)
        await self.tracer.event("plan", task_id=task.id, payload={"name": name, "node_count": len(nodes)})
        ctx = {"skill_runtime": self.skill_runtime}
        if context:
            ctx.update(context)
        task = await self.task_graph.run(task, ctx)
        await self.tracer.event(
            "summarize" if task.status.value == "completed" else "error",
            task_id=task.id,
            payload={"status": task.status.value, "error": task.error},
        )
        return {
            "task_id": task.id,
            "status": task.status.value,
            "current_node": task.current_node,
            "error": task.error,
            "nodes": [
                {
                    "id": n.id,
                    "node_type": n.node_type.value,
                    "skill_id": n.skill_id,
                    "status": n.status,
                    "attempts": n.attempts,
                    "error": n.error,
                    "outputs": n.outputs,
                }
                for n in task.nodes
            ],
        }

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Return a task and its trace events."""
        task = await self.task_graph.get(task_id)
        if task is None:
            return None
        trace = await self.tracer.trace_task(task_id)
        return {
            "task_id": task.id,
            "name": task.name,
            "status": task.status.value,
            "current_node": task.current_node,
            "error": task.error,
            "nodes": [
                {
                    "id": n.id,
                    "node_type": n.node_type.value,
                    "skill_id": n.skill_id,
                    "status": n.status,
                    "attempts": n.attempts,
                    "error": n.error,
                }
                for n in task.nodes
            ],
            "trace": trace,
        }

    async def cancel_task(self, task_id: str) -> bool:
        return await self.task_graph.cancel(task_id)

    async def list_skills(
        self,
        domain: Optional[str] = None,
        query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        await self.ensure_skills_seeded()
        if query:
            skills = await self.skill_registry.search(query)
        else:
            skills = await self.skill_registry.list(domain=domain)
        return [s.model_dump() for s in skills]

    async def skill_metrics(self, skill_id: str) -> Dict[str, Any]:
        return await self.skill_registry.metrics(skill_id)

    async def remember(
        self,
        kind: str,
        key: str,
        value: str,
        confidence: float = 1.0,
        source: str = "user",
    ) -> None:
        await self.memory_engine.remember(kind, key, value, confidence, source)

    async def recall(self, kind: str, key: str) -> Optional[Dict[str, Any]]:
        return await self.memory_engine.recall(kind, key)

    async def search_memory(
        self,
        query: str,
        kind: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        return await self.memory_engine.search_memory(query, kind=kind, limit=limit)

    async def save_workflow_template(
        self,
        template_id: str,
        name: str,
        plan: List[Dict[str, Any]],
        description: str = "",
        trigger_text: str = "",
    ) -> None:
        await self.memory_engine.save_template(
            template_id, name, plan, description, trigger_text
        )

    async def list_workflow_templates(self) -> List[Dict[str, Any]]:
        return await self.memory_engine.list_templates()

    async def match_workflow_template(self, text: str) -> Optional[Dict[str, Any]]:
        return await self.memory_engine.match_template(text)

    async def _save_command(
        self, text: str, device_id: Optional[str]
    ) -> int:
        """Save command to database."""
        async with db_session() as db:
            cursor = await db.execute(
                """
                INSERT INTO commands (source, device_id, input_text, status)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "mobile" if device_id else "pc",
                    device_id,
                    self.redactor.redact(text),
                    "pending",
                ),
            )
            await db.commit()
            command_id = cursor.lastrowid
        return command_id

    async def _update_command_metadata(
        self,
        command_id: int,
        intent: str,
        risk_level: int,
    ) -> None:
        """Persist classified intent and risk for history/audit views."""
        async with db_session() as db:
            await db.execute(
                """
                UPDATE commands
                SET intent = ?, risk_level = ?
                WHERE id = ?
                """,
                (intent, risk_level, command_id),
            )
            await db.commit()

    async def _update_command_status(
        self,
        command_id: int,
        status: str,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update command status."""
        async with db_session() as db:
            await db.execute(
                """
                UPDATE commands
                SET status = ?, result = ?, error = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, result, error, command_id),
            )
            await db.commit()

    async def _log_action(
        self,
        command_id: int,
        tool: str,
        input_data: Dict[str, Any],
        output_data: Optional[Dict[str, Any]],
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Log action to database."""
        import json

        async with db_session() as db:
            await db.execute(
                """
                INSERT INTO actions (command_id, tool, input_json, output_json, status, error)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    command_id,
                    tool,
                    json.dumps(self.redactor.redact_dict(input_data)),
                    json.dumps(self.redactor.redact_dict(output_data)) if output_data else None,
                    status,
                    self.redactor.redact(error) if error else None,
                ),
            )
            await db.commit()

    def _derive_goal(self, text: str, intent: str) -> str:
        """Derive a short human-readable goal for the user's request.

        Used by the graph's verify_goal node and surfaced in the response.
        """
        if not text or not text.strip():
            return "complete the request"
        # Prefer a capitalized/natural form of the raw command, trimmed to a
        # single line; fall back to the intent name.
        goal = " ".join(text.strip().split())
        if len(goal) > 120:
            goal = goal[:117].rstrip() + "..."
        return goal or intent.replace("_", " ").title()

    def _step_status(self, tool: str, args: Dict[str, Any]) -> str:
        """Return a natural-language status line for a tool step."""
        phrase = self.TOOL_STATUS_PHRASES.get(tool)
        if phrase:
            try:
                return phrase.format(**{k: str(v) for k, v in args.items()})
            except (KeyError, ValueError):
                pass
        return f"Running {tool}..."

    def _format_results(self, results: List[Dict[str, Any]]) -> str:
        """Format tool results into human-readable response."""
        if not results:
            return "No actions taken"

        lines = []
        for r in results:
            if r["status"] == "success":
                tool = r.get("tool", "unknown")
                result = self._human_tool_result(r.get("result", ""))
                lines.append(f"✓ {tool}: {result}")
            else:
                tool = r.get("tool", "unknown")
                error = r.get("error")
                if not error and isinstance(r.get("result"), dict):
                    error = r["result"].get("error")
                error = error or "Unknown error"
                lines.append(f"✗ {tool}: {error}")

        return "\n".join(lines)

    def _human_tool_result(self, result: Any) -> str:
        """Prefer user-readable tool messages over raw dict payloads."""
        if isinstance(result, dict):
            for key in ("message", "summary", "page", "prepared"):
                value = result.get(key)
                if value:
                    return str(value)
            if result.get("status") == "success":
                return "Done"
            return str(self.redactor.redact_dict(result))
        return str(result)

    async def emergency_stop(self) -> None:
        """Activate emergency stop."""
        self.emergency_stopped = True
        logger.warning("Emergency stop activated")

    def reset_emergency_stop(self) -> None:
        """Reset emergency stop."""
        self.emergency_stopped = False
        logger.info("Emergency stop reset")

    async def shutdown(self) -> None:
        """Release heavy tool resources before app shutdown."""
        browser_tools = self.tools.get("browser")
        if browser_tools and hasattr(browser_tools, "close"):
            await browser_tools.close()
        await self.model_registry.shutdown()
        self.io_pool.shutdown()

    async def _maintenance(self) -> None:
        """Unload idle heavy resources between commands."""
        browser_tools = self.tools.get("browser")
        if browser_tools and hasattr(browser_tools, "unload_idle"):
            await browser_tools.unload_idle()
        self.model_registry.unload_idle()

    def _prefetch_hot_tools(self, tool_names: list[str], model_budget_mb: int) -> None:
        """Warm safe tool dependencies from heat-map predictions."""
        if model_budget_mb < 128:
            return

        categories = []
        for tool_name in tool_names:
            if "." in tool_name:
                category, _ = tool_name.split(".", 1)
                categories.append(category)

        for category in dict.fromkeys(categories):
            tool = self.tools.get(category)
            prepare = getattr(tool, "prepare", None)
            if not prepare:
                continue
            if asyncio.iscoroutinefunction(prepare):
                asyncio.create_task(prepare())

    def _write_plan_cache(
        self,
        text: str,
        intent: str,
        plan: Dict[str, Any],
        runtime: Dict[str, Any],
    ) -> None:
        """Record plan metadata in the screen cache hierarchy."""
        key = self.screen_cache.key_text(text, context=intent)
        self.screen_cache.write_json(
            "ui",
            key,
            {
                "command": self.redactor.redact(text),
                "intent": intent,
                "plan": self.redactor.redact_dict(plan),
                "runtime": runtime,
            },
        )
