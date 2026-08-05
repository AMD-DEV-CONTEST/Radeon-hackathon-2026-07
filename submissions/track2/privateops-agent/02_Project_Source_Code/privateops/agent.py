from __future__ import annotations

import re
import time
from pathlib import Path

from privateops.audit import AuditTrail
from privateops.benchmark import BenchmarkStore
from privateops.config import Settings, is_competition_eligible
from privateops.llm import DeterministicProvider, OpenAICompatibleProvider
from privateops.langchain_tools import LangChainToolAdapter
from privateops.memory import LocalMemory
from privateops.models import AgentResponse, RocmProfile
from privateops.permissions import ConfirmationStore, classify_intent
from privateops.planner import Planner
from privateops.retrieval import DocumentStore
from privateops.tools import ToolRegistry


class PrivateOpsAgent:
    MODEL_CONTEXT_ITEM_LIMIT = 25

    def __init__(
        self,
        knowledge_dir: str | Path = "data/knowledge",
        state_dir: str | Path = "data/state",
        use_rocm_provider: bool = False,
        workspace_dir: str | Path = ".",
        settings: Settings | None = None,
    ):
        if settings is not None:
            knowledge_dir = settings.knowledge_dir
            state_dir = settings.state_dir
            workspace_dir = settings.workspace_dir
            use_rocm_provider = settings.provider_mode == "rocm-local"
        self.settings = settings
        self.knowledge_dir = Path(knowledge_dir)
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.state = LocalMemory(state_dir)
        self.audit = AuditTrail(state_dir)
        self.store = DocumentStore(self.knowledge_dir)
        self.workspace_dir = Path(workspace_dir).resolve()
        self.tools = ToolRegistry(self.workspace_dir)
        self.framework = LangChainToolAdapter(self.tools)
        self.planner = Planner()
        self.confirmations = ConfirmationStore()
        self.benchmarks = BenchmarkStore(state_dir)
        self._runtime_provider_status = None
        if use_rocm_provider:
            self.provider = OpenAICompatibleProvider(
                endpoint=settings.model_endpoint if settings else None,
                model=settings.model_name if settings else None,
                api_key=settings.model_api_key if settings else None,
                timeout=settings.request_timeout_seconds if settings else 90,
                allow_remote=settings.allow_remote_model if settings else False,
            )
        else:
            self.provider = DeterministicProvider()

    def ask(
        self,
        prompt: str,
        confirmation_token: str = "",
        response_language: str = "en",
    ) -> AgentResponse:
        started = time.perf_counter()
        self.store.refresh()
        evidence = self.store.search(prompt, limit=4)
        permission = classify_intent(prompt)
        plan = self.planner.plan(prompt)
        plan[0].status = "completed"
        plan[0].result = f"Retrieved {len(evidence)} evidence items."
        tool_results = []
        tool_steps = [step for step in plan if step.kind == "tool"]
        action = prompt.strip()
        allowed = permission.level == "safe"
        if permission.level == "confirm" and confirmation_token:
            allowed = self.confirmations.consume(confirmation_token, action)
        if permission.level == "blocked":
            for tool_step in tool_steps:
                tool_step.status = "blocked"
                tool_step.result = permission.reason
        elif allowed:
            for tool_step in tool_steps:
                result = self.framework.invoke(tool_step.tool_name, {})
                tool_results.append(result)
                tool_step.status = result.status
                tool_step.result = result.summary
        else:
            for tool_step in tool_steps:
                tool_step.status = "waiting_confirmation"
                tool_step.result = "Issue and submit a one-use confirmation token to continue."
        memory_updates = self._extract_memory(prompt)
        if memory_updates:
            memory = self.state.update(memory_updates)
        else:
            memory = self.state.load()
        language_instruction = "请用中文回答。" if response_language == "zh-CN" else "Please answer in English."
        inference_prompt = f"{prompt}\n\n{language_instruction}"
        execution_context = {
            "permission": permission.to_dict(),
            "plan": [step.to_dict() for step in plan],
            "tool_results": [self._tool_result_for_model(result) for result in tool_results],
        }
        answer = self.provider.complete(inference_prompt, evidence, memory, execution_context)
        synthesize_step = next(step for step in plan if step.kind == "synthesize")
        synthesize_step.status = "completed"
        synthesize_step.result = "Returned an evidence-backed response."
        metrics = {"latency_ms": round((time.perf_counter() - started) * 1000, 3)}
        response = AgentResponse(
            answer,
            evidence,
            permission,
            memory_updates,
            self.provider.name,
            plan=plan,
            tool_results=tool_results,
            metrics=metrics,
        )
        entry = self.audit.append(prompt, response)
        response.audit_id = entry["audit_id"]
        return response

    def search(self, query: str):
        self.store.refresh()
        return self.store.search(query)

    def memory(self) -> dict[str, str]:
        return self.state.load()

    def audit_trail(self, limit: int = 20) -> list[dict]:
        return self.audit.load(limit=limit)

    def issue_confirmation(self, prompt: str):
        if classify_intent(prompt).level != "confirm":
            raise ValueError("Only confirmation-required requests can receive a token.")
        return self.confirmations.issue(prompt.strip())

    def status(self) -> dict[str, object]:
        base = self.settings.public_status() if self.settings else {
            "provider_mode": "rocm-local" if self.provider.name == "openai-compatible-rocm" else "development",
            "workspace": str(self.workspace_dir),
            "knowledge_dir": str(self.knowledge_dir.resolve()),
            "model_endpoint": getattr(self.provider, "endpoint", ""),
            "model_name": getattr(self.provider, "model", ""),
            "remote_model_allowed": False,
        }
        if self._runtime_provider_status:
            base.update(self._runtime_provider_status)
        is_remote_model = bool(base.get("remote_model_allowed"))
        base["competition_eligible"] = is_competition_eligible(
            str(base.get("provider_mode", "")),
            str(base.get("model_endpoint", "")),
            is_remote_model,
        )
        base.update(
            {
                "app": "PrivateOps Agent",
                "version": "1.0.0",
                "provider": self.provider.name,
                "agent_framework": self.framework.framework_name,
                "runtime_mode": "amd-cloud-api" if is_remote_model else base["provider_mode"],
                "inference_runtime": (
                    "OpenAI-compatible HTTPS API" if is_remote_model else "vLLM OpenAI-compatible"
                ),
                "core_inference_location": (
                    "AMD Cloud shared API" if is_remote_model else "same-instance loopback"
                ),
                "indexed_documents": len(self.store.documents),
                "privacy_boundary": "workspace-confined; local state; audited tools",
            }
        )
        return base

    def configure_provider(self, provider, endpoint: str, model: str, allow_remote: bool) -> dict[str, object]:
        self.provider = provider
        self._runtime_provider_status = {
            "provider_mode": "development" if allow_remote else "rocm-local",
            "model_endpoint": endpoint,
            "model_name": model,
            "remote_model_allowed": allow_remote,
            "competition_eligible": is_competition_eligible(
                "development" if allow_remote else "rocm-local",
                endpoint,
                allow_remote,
            ),
        }
        return self.status()

    def save_rocm_profile(
        self,
        gpu_name: str,
        rocm_version: str,
        model_endpoint: str,
        notes: str,
    ) -> RocmProfile:
        profile = RocmProfile(gpu_name, rocm_version, model_endpoint, notes)
        self.state.save_json("rocm_profile.json", profile.to_dict())
        return profile

    def load_rocm_profile(self) -> RocmProfile:
        data = self.state.load_json("rocm_profile.json")
        return RocmProfile(
            gpu_name=str(data.get("gpu_name", "")),
            rocm_version=str(data.get("rocm_version", "")),
            model_endpoint=str(data.get("model_endpoint", "")),
            notes=str(data.get("notes", "")),
        )

    def _extract_memory(self, prompt: str) -> dict[str, str]:
        text = prompt.strip()
        if not re.search(r"\bremember\b|记住|重点|focus", text, re.IGNORECASE):
            return {}
        lower = text.lower()
        if "demo" in lower or "演示" in text:
            return {"demo_focus": text}
        return {"user_note": text}

    def _tool_result_for_model(self, result):
        payload = result.to_dict()
        output = dict(payload.get("output", {}))
        truncated_fields = []
        for key, values in list(output.items()):
            if isinstance(values, list) and len(values) > self.MODEL_CONTEXT_ITEM_LIMIT:
                output[key] = values[: self.MODEL_CONTEXT_ITEM_LIMIT]
                truncated_fields.append(key)
        if truncated_fields:
            output["model_context_truncated"] = True
            output["model_context_truncated_fields"] = truncated_fields
        payload["output"] = output
        return payload
