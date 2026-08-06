from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from agent_factory.runtime_contracts.contribution import RuntimeContribution
from agent_factory.runtime_contracts.schema import RuntimeContractEnvelope


class RuntimeContractBuilder(Protocol):
    contract_type: str
    contract_version: str

    def build(self, contract: BaseModel, context: Any) -> RuntimeContribution:
        ...


@dataclass(frozen=True, slots=True)
class RuntimeContractDefinition:
    contract_type: str
    version: str
    model: type[BaseModel]
    builder: RuntimeContractBuilder


class RuntimeContractRegistryError(ValueError):
    pass


class RuntimeContractRegistry:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], RuntimeContractDefinition] = {}

    def register(
        self,
        *,
        contract_type: str,
        version: str,
        model: type[BaseModel],
        builder: RuntimeContractBuilder,
    ) -> None:
        key = (contract_type, version)
        if key in self._definitions:
            raise RuntimeContractRegistryError(f"duplicate runtime contract definition: {contract_type}@{version}")
        if builder.contract_type != contract_type or builder.contract_version != version:
            raise RuntimeContractRegistryError(
                f"builder identity mismatch for runtime contract: {contract_type}@{version}"
            )
        self._definitions[key] = RuntimeContractDefinition(
            contract_type=contract_type,
            version=version,
            model=model,
            builder=builder,
        )

    def parse(self, payload: dict[str, object]) -> BaseModel:
        envelope = RuntimeContractEnvelope.model_validate(payload)
        definition = self.definition(envelope.type, envelope.version)
        return definition.model.model_validate(payload)

    def builder_for(self, contract: BaseModel) -> RuntimeContractBuilder:
        contract_type = str(getattr(contract, "type"))
        version = str(getattr(contract, "version"))
        return self.definition(contract_type, version).builder

    def definition(self, contract_type: str, version: str) -> RuntimeContractDefinition:
        key = (contract_type, version)
        try:
            return self._definitions[key]
        except KeyError as exc:
            raise RuntimeContractRegistryError(f"unknown runtime contract: {contract_type}@{version}") from exc

    def known_contracts(self) -> list[str]:
        return [f"{contract_type}@{version}" for contract_type, version in sorted(self._definitions)]
