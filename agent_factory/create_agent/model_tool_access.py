from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_factory.runtime_contracts.schema import ModelContract


MODEL_CONTRACT_PATH = Path("contracts/model.json")


def model_tool_ids_from_contract(contract: Any) -> set[str]:
    if isinstance(contract, ModelContract):
        return set(contract.config.tool_bindings)
    if isinstance(contract, dict):
        parsed = ModelContract.model_validate(contract)
        return set(parsed.config.tool_bindings)
    return set()


def model_tool_ids_from_package_root(package_root: str | Path) -> set[str]:
    contract = load_model_contract(package_root)
    return set(contract.config.tool_bindings) if contract is not None else set()


def load_model_contract(package_root: str | Path) -> ModelContract | None:
    path = Path(package_root).expanduser().resolve() / MODEL_CONTRACT_PATH
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{MODEL_CONTRACT_PATH.as_posix()} must contain a JSON object")
    return ModelContract.model_validate(payload)


def model_bindings_ready(package_root: str | Path) -> bool:
    contract = load_model_contract(package_root)
    if contract is None:
        return False
    main = contract.config.bindings.get("main")
    return bool(main and str(main.profile_id or "").strip())
