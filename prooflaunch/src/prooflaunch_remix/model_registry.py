from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Iterable


class ModelRoutingError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    key: str
    model_id: str
    role: str
    modalities: tuple[str, ...]
    license: str
    min_vram_gb: float
    priority: int
    gate_state: str
    source: str


@dataclass(frozen=True)
class ExecutionPhase:
    order: int
    role: str
    model_key: str
    model_id: str
    load: str
    unload_after: bool
    min_vram_gb: float


class RadeonModelRouter:
    """Builds a single-GPU, non-co-resident local model execution plan."""

    role_order = (
        "vision_language_audit",
        "audio_transcription",
        "open_set_detection",
        "affect_critic",
        "image_generation",
        "image_text_scoring",
        "video_generation",
        "temporal_segmentation",
        "audio_text_scoring",
    )

    def __init__(self, registry: dict | None = None) -> None:
        self.registry = registry or self.load_default_registry()
        self._validate_registry()
        self.models = tuple(self._parse_model(item) for item in self.registry["models"])

    @staticmethod
    def load_default_registry() -> dict:
        path = files("prooflaunch_remix").joinpath("model_registry.json")
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _parse_model(item: dict) -> ModelSpec:
        return ModelSpec(
            key=item["key"],
            model_id=item["modelId"],
            role=item["role"],
            modalities=tuple(item["modalities"]),
            license=item["license"],
            min_vram_gb=float(item["minVramGb"]),
            priority=int(item["priority"]),
            gate_state=item["gateState"],
            source=item["source"],
        )

    def _validate_registry(self) -> None:
        policy = self.registry.get("selectionPolicy", {})
        if policy.get("localOnly") is not True:
            raise ModelRoutingError("competition registry must be local-only")
        if policy.get("closedOnlineApiAllowedForCore") is not False:
            raise ModelRoutingError("closed online API cannot be a core dependency")
        models = self.registry.get("models")
        if not isinstance(models, list) or not models:
            raise ModelRoutingError("model registry is empty")
        required = {
            "key",
            "modelId",
            "role",
            "modalities",
            "license",
            "minVramGb",
            "priority",
            "gateState",
            "source",
        }
        keys: set[str] = set()
        for item in models:
            missing = required - set(item)
            if missing:
                raise ModelRoutingError(
                    f"model entry missing fields: {', '.join(sorted(missing))}"
                )
            if item["key"] in keys:
                raise ModelRoutingError(f"duplicate model key: {item['key']}")
            if not item["license"] or item["license"].lower() == "unknown":
                raise ModelRoutingError(f"unknown license: {item['key']}")
            if float(item["minVramGb"]) <= 0:
                raise ModelRoutingError(f"invalid VRAM floor: {item['key']}")
            keys.add(item["key"])

    def plan(
        self,
        *,
        available_vram_gb: float,
        required_roles: Iterable[str],
        include_candidates: bool = False,
    ) -> list[ExecutionPhase]:
        requested = tuple(dict.fromkeys(required_roles))
        unknown = set(requested) - set(self.role_order)
        if unknown:
            raise ModelRoutingError(f"unknown roles: {', '.join(sorted(unknown))}")
        phases: list[ExecutionPhase] = []
        for role in self.role_order:
            if role not in requested:
                continue
            choices = [
                item
                for item in self.models
                if item.role == role
                and item.min_vram_gb <= available_vram_gb
                and (include_candidates or item.gate_state == "required")
            ]
            if not choices:
                raise ModelRoutingError(
                    f"no local {role} model fits {available_vram_gb:.1f} GB VRAM"
                )
            selected = min(choices, key=lambda item: (item.priority, item.min_vram_gb))
            phases.append(
                ExecutionPhase(
                    order=len(phases) + 1,
                    role=role,
                    model_key=selected.key,
                    model_id=selected.model_id,
                    load=f"load {selected.key} on Radeon",
                    unload_after=True,
                    min_vram_gb=selected.min_vram_gb,
                )
            )
        if len(phases) != len(requested):
            missing = set(requested) - {phase.role for phase in phases}
            raise ModelRoutingError(f"unplanned roles: {', '.join(sorted(missing))}")
        return phases

    def report(
        self,
        *,
        available_vram_gb: float,
        roles: Iterable[str],
        include_candidates: bool = False,
    ) -> dict:
        phases = self.plan(
            available_vram_gb=available_vram_gb,
            required_roles=roles,
            include_candidates=include_candidates,
        )
        return {
            "schema": "ProofLaunchRadeonExecutionPlanV1",
            "available_vram_gb": available_vram_gb,
            "co_resident_models": 1,
            "local_only": True,
            "closed_online_api_on_core_path": False,
            "phases": [phase.__dict__ for phase in phases],
        }
