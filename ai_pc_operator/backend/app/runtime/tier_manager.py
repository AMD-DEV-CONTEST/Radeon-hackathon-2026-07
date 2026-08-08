"""Agent runtime tier decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.runtime.resource_budget import RuntimeBudget


@dataclass(frozen=True)
class TierDecision:
    tier: str
    reason: str
    allowed_models: list[str]
    prefetch_models: list[str]
    budget_mode: str
    model_budget_mb: int

    def to_dict(self) -> dict:
        return asdict(self)


class AgentTierManager:
    """Turns RAM budget + intent + learned heat into runtime decisions."""

    def decide(
        self,
        intent: str,
        budget: RuntimeBudget,
        hot_models: list[str],
    ) -> TierDecision:
        allowed: list[str] = []
        if budget.allow_ocr:
            allowed.append("ocr-mobile")
        if budget.allow_detector:
            allowed.append("ui-detector-int8")
        if budget.allow_llm:
            allowed.append("qwen-1.5b-q4")

        prefetch = [name for name in hot_models if name in allowed or name in {"browser-warmup", "vault-crypto"}]

        if intent in {"screen_click", "click_text"} and "ocr-mobile" in allowed:
            tier = "tier1"
            reason = "screen command can use OCR/detector fallback"
        elif budget.mode == "tier0-only":
            tier = "tier0"
            reason = "RAM budget only allows resident scanner/rules"
        elif budget.allow_llm:
            tier = "tier1"
            reason = "RAM budget allows small local reasoning model"
        else:
            tier = "tier0"
            reason = "rule planner with lazy perception fallback"

        return TierDecision(
            tier=tier,
            reason=reason,
            allowed_models=allowed,
            prefetch_models=prefetch,
            budget_mode=budget.mode,
            model_budget_mb=budget.model_budget_mb,
        )

