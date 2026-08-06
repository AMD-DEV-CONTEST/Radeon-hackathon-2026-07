from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_factory.runtime_contracts.builtins import (
    default_context_contract,
    default_dependencies_contract,
    default_model_contract,
    default_resources_contract,
    default_scheduler_contract,
    default_scheduler_seed_contract,
    default_tools_contract,
)
from agent_factory.runtime_contracts.schema import REQUIRED_AGENT_PACKAGE_CONTRACTS


OPTIONAL_BASE_CONTRACTS = ("scheduler_seed",)


def system_resources(system_id: str, *, include_example: bool = False) -> tuple[str, ...]:
    resources = [
        f"references/{system_id}.schema.json",
        f"references/{system_id}.repair_hints.md",
    ]
    if include_example:
        resources.insert(1, f"examples/{system_id}.capability.json")
    return tuple(resources)


@dataclass(frozen=True, slots=True)
class CreateAgentContractCatalogItem:
    contract_key: str
    path: str
    default_factory: Callable[[], Any]

    def default_payload(self) -> dict[str, Any]:
        contract = self.default_factory()
        return contract.model_dump(mode="json", by_alias=True, exclude_none=True)


def base_contract_paths() -> dict[str, str]:
    keys = sorted({*REQUIRED_AGENT_PACKAGE_CONTRACTS, *OPTIONAL_BASE_CONTRACTS})
    return {key: contract_item(key).path for key in keys}


def contract_item(contract_key: str) -> CreateAgentContractCatalogItem:
    try:
        return _CONTRACT_CATALOG[contract_key]
    except KeyError as exc:
        raise ValueError(f"unknown create-agent contract key: {contract_key}") from exc


def default_contract_payload(contract_key: str) -> dict[str, Any]:
    return contract_item(contract_key).default_payload()


def _item(
    contract_key: str,
    *,
    default_factory: Callable[[], Any],
) -> CreateAgentContractCatalogItem:
    return CreateAgentContractCatalogItem(
        contract_key=contract_key,
        path=f"contracts/{contract_key}.json",
        default_factory=default_factory,
    )


_CONTRACT_CATALOG = {
    "context": _item(
        "context",
        default_factory=default_context_contract,
    ),
    "dependencies": _item(
        "dependencies",
        default_factory=default_dependencies_contract,
    ),
    "model": _item(
        "model",
        default_factory=default_model_contract,
    ),
    "resources": _item(
        "resources",
        default_factory=default_resources_contract,
    ),
    "scheduler": _item(
        "scheduler",
        default_factory=default_scheduler_contract,
    ),
    "scheduler_seed": _item(
        "scheduler_seed",
        default_factory=default_scheduler_seed_contract,
    ),
    "tools": _item(
        "tools",
        default_factory=default_tools_contract,
    ),
}


_missing = sorted(REQUIRED_AGENT_PACKAGE_CONTRACTS - set(_CONTRACT_CATALOG))
if _missing:
    raise RuntimeError("create-agent contract catalog missing required contracts: " + ", ".join(_missing))
