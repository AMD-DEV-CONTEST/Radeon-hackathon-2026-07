from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent_factory.create_agent.model_tool_access import load_model_contract
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.model_pool.resolver import (
    resolve_available_chat_model,
    resolve_chat_model_binding,
    resolve_chat_model_profile,
)
from agent_factory.model_pool.schema import ModelProfileBinding
from agent_factory.models import create_chat_model_from_settings
from agent_factory.models.reasoning import apply_reasoning_intensity, coerce_reasoning_content
from agent_factory.tip_system.schema import TipCreateRequest, TipMessage, TipRecord
from agent_factory.tip_system.store import TipStore


TIP_SYSTEM_PROMPT = """You answer a focused side question about a selected passage from an existing assistant message.
Explain only what is needed to resolve the side question. Preserve technical accuracy and use the user's language.
Do not continue the main conversation, claim to modify its history, or introduce unrelated work."""


class TipService:
    def __init__(self, store: TipStore | None = None) -> None:
        self.store = store or TipStore()

    def list_scope(self, scope_type: str, scope_id: str) -> list[TipRecord]:
        return self.store.list_scope(scope_type.strip(), scope_id.strip())

    def create_and_answer(self, request: TipCreateRequest) -> TipRecord:
        tip = self.store.create(
            TipRecord(
                scope_type=request.scope_type,
                scope_id=request.scope_id,
                source_message_id=request.source_message_id,
                source_role=request.source_role,
                source_content=request.source_content,
                selected_text=request.selected_text,
                selection_start=request.selection_start,
                selection_end=request.selection_end,
                agent_package_id=request.agent_package_id,
                model_profile_id=request.model_profile_id,
                reasoning_intensity=request.reasoning_intensity,
                messages=[TipMessage(role="user", content=request.question)],
            )
        )
        return self._answer(tip)

    def follow_up(self, tip_id: str, question: str) -> TipRecord:
        tip = self.store.require(tip_id)
        self.store.append_message(tip_id, TipMessage(role="user", content=question))
        tip = self.store.set_status(tip_id, "answering", error=None)
        return self._answer(tip)

    def delete(self, tip_id: str) -> bool:
        return self.store.delete(tip_id)

    def _answer(self, tip: TipRecord) -> TipRecord:
        try:
            model = self._model(tip)
            response = model.invoke(self._messages(tip))
            answer = _message_text(response)
            if not answer:
                raise ValueError("Tip model returned an empty response")
            self.store.append_message(tip.tip_id, TipMessage(role="assistant", content=answer))
            return self.store.set_status(tip.tip_id, "completed", error=None)
        except Exception as exc:
            self.store.set_status(tip.tip_id, "failed", error=f"{type(exc).__name__}: {exc}")
            raise

    def _model(self, tip: TipRecord) -> Any:
        if tip.model_profile_id:
            resolved = resolve_chat_model_profile(
                ModelProfileBinding(
                    profile_id=tip.model_profile_id,
                    selection_source="manual",
                    reason="Tiping side explanation",
                ),
                role="main",
            )
            settings = resolved.settings
            model = resolved.model
        elif tip.agent_package_id and tip.agent_package_id != "factory_chat":
            package = AgentPackageRuntimeManager().load_package(tip.agent_package_id)
            contract = load_model_contract(package.package_root)
            if contract is None or contract.config.bindings.get("main") is None:
                raise ValueError(f"agent package has no main model binding: {tip.agent_package_id}")
            resolved = resolve_chat_model_binding(contract.config.bindings["main"], role="main")
            settings = resolved.settings
            model = resolved.model
        else:
            resolved = resolve_available_chat_model("main")
            if resolved is None:
                raise ValueError("main model is not configured in the model pool")
            settings = resolved.settings
            model = resolved.model

        if tip.reasoning_intensity is None:
            return model
        runtime_settings = apply_reasoning_intensity(settings, tip.reasoning_intensity)
        runtime_model = create_chat_model_from_settings(runtime_settings)
        if runtime_model is None:
            raise ValueError("Tip model is not configured")
        return runtime_model

    @staticmethod
    def _messages(tip: TipRecord) -> list[Any]:
        system_context = (
            f"{TIP_SYSTEM_PROMPT}\n\n"
            "Source assistant message:\n"
            f"{tip.source_content}\n\n"
            "Selected passage:\n"
            f"{tip.selected_text}"
        )
        messages: list[Any] = [SystemMessage(content=system_context)]
        for message in tip.messages:
            message_type = HumanMessage if message.role == "user" else AIMessage
            messages.append(message_type(content=message.content))
        return messages


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = coerce_reasoning_content(item.get("text") or item.get("content"))
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    return str(content or "").strip()
