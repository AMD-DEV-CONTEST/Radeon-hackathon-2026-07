"""Deterministic, fail-closed model selection."""
from dataclasses import dataclass
from typing import Any, Mapping
from types import MappingProxyType

@dataclass(frozen=True)
class ModelCandidate:
    name: str
    capabilities: tuple[str, ...] = ()
    applicability: tuple[str, ...] = ()
    priority: int = 0
    def __post_init__(self):
        if not isinstance(self.name,str) or not self.name.strip(): raise ValueError("model name required")
        if not isinstance(self.capabilities,(list,tuple)) or not isinstance(self.applicability,(list,tuple)): raise ValueError("capabilities/applicability must be lists or tuples")
        if any(not isinstance(x,str) or not x.strip() for x in (*self.capabilities,*self.applicability)): raise ValueError("capability/applicability values must be non-empty strings")
        if isinstance(self.priority,bool) or not isinstance(self.priority,int): raise ValueError("priority must be int")
        object.__setattr__(self,"capabilities",tuple(self.capabilities)); object.__setattr__(self,"applicability",tuple(self.applicability))

@dataclass(frozen=True)
class SelectionResult:
    eligible: tuple[str, ...]
    selected: tuple[str, ...]
    rejected: Mapping[str, tuple[str, ...]]
    def __post_init__(self):
        object.__setattr__(self,"rejected",MappingProxyType(dict(self.rejected)))

class ModelSelectionAgent:
    def __init__(self, required_capabilities: tuple[str, ...] = ()):
        self.required_capabilities = tuple(required_capabilities)

    def select(self, request: Mapping[str, Any], candidates: list[ModelCandidate]) -> SelectionResult:
        needed = set(request.get("capabilities", self.required_capabilities) or self.required_capabilities)
        target = request.get("radionuclide")
        eligible, rejected = [], {}
        for model in candidates:
            reasons = []
            if not model.name: reasons.append("missing model name")
            if not needed.issubset(model.capabilities): reasons.append("missing required capability")
            if not target: reasons.append("missing radionuclide applicability data")
            elif not model.applicability or target not in model.applicability: reasons.append("model applicability not established")
            if reasons: rejected[model.name] = tuple(reasons)
            else: eligible.append(model)
        eligible.sort(key=lambda m: (m.priority, m.name))
        names = tuple(m.name for m in eligible)
        return SelectionResult(names, names[:1], rejected)