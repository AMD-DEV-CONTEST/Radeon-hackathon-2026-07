from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent_factory.create_agent.models import CreateAgentIntentDecision
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.models import get_main_model, get_task_model
from agent_factory.runtime_kernel.model_operations import ModelOperationService


def classify_create_agent_intent(
    *,
    user_input: str,
    workspace: CreateAgentWorkspace,
    model: Any | None = None,
) -> CreateAgentIntentDecision:
    classifier = model or get_task_model() or get_main_model()
    if classifier is None:
        raise RuntimeError("create-agent intent classification requires a configured task or main model")
    result = ModelOperationService(model=classifier).structured_json(
        output_model=CreateAgentIntentDecision,
        state=None,
        prebuilt_messages=_intent_messages(user_input=user_input, workspace=workspace),
        config_tags=["nostream"],
        operation_metadata={"operation": "create_agent_intent_classification"},
    )
    return result if isinstance(result, CreateAgentIntentDecision) else CreateAgentIntentDecision.model_validate(result)


def _intent_messages(*, user_input: str, workspace: CreateAgentWorkspace) -> list[Any]:
    return [
        SystemMessage(
            content=(
                "Classify a /create-agent user message. "
                "Return only JSON that matches the CreateAgentIntentDecision schema. "
                "The required classification field is named intent; do not use alternate field names such as decision. "
                "Return manufacture_agent only when the user is asking to create, modify, repair, "
                "validate, or continue manufacturing a RuntimeKernel AgentPackage. "
                "Requests to create, generate, build, scaffold, design, or continue an agent are manufacture_agent. "
                "If the message describes desired agent behavior, capabilities, schedules, tools, resources, "
                "or runtime features for an agent to be built, choose manufacture_agent. "
                "When the package manifest does not exist yet, a request to make/design an assistant or Agent "
                "with described capabilities is the start of manufacturing, not workspace assistance. "
                "Return workspace_assist when the user asks about the current create-agent workspace, "
                "files, skills, tools, package location, validation status, or wants ordinary workspace operations "
                "without asking to change, validate, repair, continue, or manufacture the package. "
                "Return chat for casual conversation or questions not directed at manufacturing an AgentPackage. "
                "Do not infer manufacturing intent from the fact that the user is in /create-agent mode."
            )
        ),
        HumanMessage(
            content=(
                f"Workspace path: {workspace.root}\n"
                f"Workspace exists: {workspace.root.exists()}\n"
                f"Package manifest exists: {workspace.package_manifest_path().exists()}\n"
                f"User message:\n{user_input}"
            )
        ),
    ]
