from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "SourceAttachmentInput": ".harness_service",
    "ChatbotEvent": ".chatbot_events",
    "ChatbotEventAuthor": ".chatbot_events",
    "ChatbotEventKind": ".chatbot_events",
    "ChatbotEventStatus": ".chatbot_events",
    "build_activity_chatbot_event": ".chatbot_events",
    "build_thinking_chatbot_event": ".chatbot_events",
    "enrich_chatbot_events_with_source_attachments": ".chatbot_events",
    "project_chatbot_events": ".chatbot_events",
    "thinking_chatbot_event_id": ".chatbot_events",
    "AgentHarnessService": ".harness_service",
    "AgentHarnessStreamEvent": ".harness_service",
    "AttachmentImportProgress": ".harness_service",
    "AttachmentImportStatus": ".harness_service",
    "DatasetAttachmentInput": ".harness_service",
    "SubmitUserTurnInput": ".harness_service",
    "OpenAICompatibleChatProvider": ".providers",
    "ProviderMessage": ".providers",
    "ProviderResponse": ".providers",
    "ProviderStreamEvent": ".providers",
    "ProviderToolCall": ".providers",
    "ScriptedAgentProvider": ".providers",
    "AgentSkill": ".skill_catalog",
    "AgentSkillCatalog": ".skill_catalog",
    "AgentSettings": ".settings",
    "AgentSettingsService": ".settings",
    "LLMDialect": "..llm",
    "LLMModelOption": "..llm",
    "LLMProviderConfig": "..llm",
    "LLMService": "..llm",
    "LLMSettings": "..llm",
    "LLMSettingsService": "..llm",
    "AgentToolRegistry": ".tools",
    "HeadlessAgentServices": ".composition",
    "build_headless_agent_services": ".composition",
    "ToolPresentation": ".tool_presentations",
    "tool_presentation_for_name": ".tool_presentations",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> object:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *__all__])
