from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent_factory.create_agent.models import ResourceRequest
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.runtime_contracts import ResourcesContract
from agent_factory.runtime_contracts.schema import ResourceDescriptor


def load_resource_descriptors(workspace: CreateAgentWorkspace) -> list[ResourceDescriptor]:
    path = workspace.root / "contracts" / "resources.json"
    if not path.is_file():
        return []
    contract = ResourcesContract.model_validate_json(path.read_text(encoding="utf-8"))
    return list(contract.config.resource_descriptors)


def resource_request_payloads(
    workspace: CreateAgentWorkspace,
    requests: Sequence[ResourceRequest],
) -> list[dict[str, Any]]:
    descriptors = {item.resource_id: item for item in load_resource_descriptors(workspace)}
    missing = [request.resource_id for request in requests if request.resource_id not in descriptors]
    if missing:
        resource_ids = ", ".join(dict.fromkeys(missing))
        raise ValueError(
            "Resource requests must reference descriptors already declared in contracts/resources.json: "
            f"{resource_ids}. Declare the complete descriptor through create_agent_authoring before asking the user."
        )
    payloads: list[dict[str, Any]] = []
    for request in requests:
        descriptor = descriptors[request.resource_id]
        if not descriptor.value_schema:
            raise ValueError(
                f"Resource request requires a non-empty value_schema before asking the user: {request.resource_id}"
            )
        payload = request.model_dump(mode="json")
        payload.update(
            {
                "description": request.description or descriptor.description,
                "required": descriptor.required,
                "value_schema": descriptor.value_schema,
                "secret_fields": list(descriptor.secret_fields),
            }
        )
        payloads.append(payload)
    return payloads
