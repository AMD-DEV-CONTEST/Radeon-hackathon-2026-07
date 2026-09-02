"""Experiment configuration shared by mini-SWE and external harnesses.

The historical runner exposed a flat C/J/V switch.  The final Track 2
experiments use four independent axes so that controller policy is not
mistaken for repository context and verifier repair is not mistaken for a
JSON transport protocol.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SamplingConfig:
    temperature: float = 0.6
    top_p: float = 0.95
    top_k: int = 20
    presence_penalty: float = 0.0
    max_completion_tokens: int = 8192
    seed: int | None = 0

    def to_openai_kwargs(self) -> dict[str, Any]:
        """Return provider-neutral request fields.

        ``top_k`` is sent through ``extra_body`` by the caller because it is
        not part of the OpenAI core schema.  The other fields are accepted by
        vLLM's OpenAI-compatible endpoint.
        """
        result: dict[str, Any] = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "presence_penalty": self.presence_penalty,
            "max_tokens": self.max_completion_tokens,
        }
        if self.seed is not None:
            result["seed"] = self.seed
        return result

    def to_extra_body(self) -> dict[str, Any]:
        return {"top_k": self.top_k}


@dataclass(frozen=True)
class BudgetConfig:
    max_model_turns: int = 12
    max_tool_calls: int = 30
    max_wall_time_seconds: int = 900
    command_timeout_seconds: int = 120
    max_json_retries: int = 1
    verifier_repair_turns: int = 2


@dataclass(frozen=True)
class ExperimentConfig:
    context: str = "C0"
    controller_policy: str = "A0"
    action_protocol: str = "J0"
    verifier: str = "V0"
    sampling: SamplingConfig = SamplingConfig()
    budget: BudgetConfig = BudgetConfig()

    @classmethod
    def from_legacy_variant(
        cls,
        variant: str,
        *,
        sampling: SamplingConfig | None = None,
        budget: BudgetConfig | None = None,
    ) -> "ExperimentConfig":
        """Parse ``C1-J3-V1`` and the final ``A1/V1R1`` names.

        Legacy C5 remains readable for historical artifacts, but new runs
        should use ``controller_policy=A1`` explicitly.
        """
        parts = [part.strip().upper() for part in variant.split("-") if part.strip()]
        if len(parts) not in {3, 4}:
            raise ValueError(f"expected C-J-V or C-J-A-V variant, got {variant!r}")
        if len(parts) == 3:
            context, action, verifier = parts
            controller = "A1" if context == "C5" else "A0"
            if context == "C5":
                context = "C0"
        else:
            context, action, controller, verifier = parts
        return cls(
            context=context,
            controller_policy=controller,
            action_protocol=action,
            verifier=verifier,
            sampling=sampling or SamplingConfig(),
            budget=budget or BudgetConfig(),
        ).validated()

    def validated(self) -> "ExperimentConfig":
        if self.context not in {"C0", "C1", "C2"}:
            raise ValueError(f"unsupported final context: {self.context}")
        if self.controller_policy not in {"A0", "A1"}:
            raise ValueError(f"unsupported controller policy: {self.controller_policy}")
        if self.action_protocol not in {"J0", "J3"}:
            raise ValueError(f"unsupported final action protocol: {self.action_protocol}")
        if self.verifier not in {"V0", "V1", "V1R1"}:
            raise ValueError(f"unsupported final verifier: {self.verifier}")
        if self.budget.max_model_turns < 1 or self.budget.max_tool_calls < 1:
            raise ValueError("model and tool budgets must be positive")
        if self.budget.max_wall_time_seconds < 1:
            raise ValueError("wall-time budget must be positive")
        return self

    @property
    def legacy_variant(self) -> str:
        verifier = "V1" if self.verifier == "V1R1" else self.verifier
        return f"{self.context}-{self.action_protocol}-{verifier}"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["legacy_variant"] = self.legacy_variant
        return value


def config_from_mapping(value: Mapping[str, Any]) -> ExperimentConfig:
    """Build a validated config from a JSON object or CLI mapping."""
    if "variant" in value:
        return ExperimentConfig.from_legacy_variant(str(value["variant"]))
    sampling_value = value.get("sampling", {}) or {}
    budget_value = value.get("budget", {}) or {}
    sampling = SamplingConfig(**{key: sampling_value[key] for key in SamplingConfig.__dataclass_fields__ if key in sampling_value})
    budget = BudgetConfig(**{key: budget_value[key] for key in BudgetConfig.__dataclass_fields__ if key in budget_value})
    return ExperimentConfig(
        context=str(value.get("context", "C0")).upper(),
        controller_policy=str(value.get("controller_policy", "A0")).upper(),
        action_protocol=str(value.get("action_protocol", "J0")).upper(),
        verifier=str(value.get("verifier", "V0")).upper(),
        sampling=sampling,
        budget=budget,
    ).validated()
