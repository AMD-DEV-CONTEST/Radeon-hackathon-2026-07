"""SSD-backed runtime tier planning inspired by colibri/codiii.

Screen-AI does not stream MoE experts token-by-token. The useful adaptation is
the same memory hierarchy: resident rules/UIA, warm tiny perception models, and
cold heavy models left on SSD until explicitly needed.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.runtime.artifact_store import ArtifactStore
from app.runtime.resource_budget import RuntimeBudget


ROOT = Path(__file__).resolve().parents[4]
STATE_DIR = ROOT / "ai_pc_operator" / "data" / "memory"
USAGE_PATH = STATE_DIR / "model_usage.json"


@dataclass(frozen=True)
class ModelPlacement:
    name: str
    tier: str
    reason: str
    artifact_mb: float
    estimated_ram_mb: int
    prefetch: bool
    mmap: bool


@dataclass(frozen=True)
class SSDTierPlan:
    mode: str
    available_mb: int
    model_budget_mb: int
    reserve_mb: int
    prefetch_depth: int
    mmap_enabled: bool
    placements: dict[str, ModelPlacement]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["placements"] = {
            name: asdict(placement)
            for name, placement in self.placements.items()
        }
        return payload


class SSDTierManager:
    """Plans model placement across resident RAM and SSD-cold tiers."""

    def __init__(self, usage_path: Path = USAGE_PATH) -> None:
        self.usage_path = usage_path
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        self.usage = self._load_usage()

    def plan(
        self,
        budget: RuntimeBudget,
        artifacts: ArtifactStore,
        reserve_mb: int,
    ) -> SSDTierPlan:
        mmap_enabled = self._env_bool("SCREEN_AI_MMAP", default=True)
        prefetch_depth = self._env_int("SCREEN_AI_PREFETCH", default=1)
        allow_cold_llm = self._env_bool("SCREEN_AI_ALLOW_COLD_LLM", default=False)

        placements: dict[str, ModelPlacement] = {}
        specs = {
            "ocr-mobile": 120,
            "ui-detector-int8": 220,
            "qwen-1.5b-q4": 1050,
            "vault-crypto": 32,
            "browser-warmup": 64,
        }

        for name, estimated in specs.items():
            artifact = artifacts.find(name)
            artifact_mb = artifact.size_mb if artifact else 0.0
            heat = self.usage.get(name, {}).get("uses", 0)

            if name in {"vault-crypto", "browser-warmup"}:
                tier, reason, prefetch = "resident", "tiny dependency warmup", heat > 0
            elif name == "qwen-1.5b-q4":
                if budget.model_budget_mb >= estimated and allow_cold_llm:
                    tier, reason, prefetch = "ssd-cold", "large GGUF mmap-loaded on demand", False
                else:
                    tier, reason, prefetch = "ssd-off", "kept on SSD for 4GB RAM safety", False
            elif budget.model_budget_mb >= estimated:
                tier = "warm"
                reason = "small perception model can lazy-load"
                prefetch = heat > 2 and prefetch_depth > 0
            else:
                tier = "ssd-cold"
                reason = "artifact stays on SSD until command requires it"
                prefetch = False

            placements[name] = ModelPlacement(
                name=name,
                tier=tier,
                reason=reason,
                artifact_mb=artifact_mb,
                estimated_ram_mb=estimated,
                prefetch=prefetch,
                mmap=mmap_enabled and name == "qwen-1.5b-q4",
            )

        return SSDTierPlan(
            mode=budget.mode,
            available_mb=budget.available_mb,
            model_budget_mb=budget.model_budget_mb,
            reserve_mb=reserve_mb,
            prefetch_depth=prefetch_depth,
            mmap_enabled=mmap_enabled,
            placements=placements,
        )

    def can_load(self, name: str, plan: SSDTierPlan) -> bool:
        placement = plan.placements.get(name)
        if not placement:
            return False
        if placement.tier == "ssd-off":
            return False
        return placement.tier in {"resident", "warm", "ssd-cold"}

    def should_prefetch(self, name: str, plan: SSDTierPlan) -> bool:
        placement = plan.placements.get(name)
        return bool(placement and placement.prefetch)

    def record_use(self, name: str) -> None:
        item = self.usage.setdefault(name, {"uses": 0, "last_used": 0.0})
        item["uses"] = int(item.get("uses", 0)) + 1
        item["last_used"] = time.time()
        self._save_usage()

    def status(self) -> dict[str, Any]:
        return {
            "usage_path": str(self.usage_path),
            "usage": self.usage,
            "env": {
                "SCREEN_AI_MMAP": os.environ.get("SCREEN_AI_MMAP", "1"),
                "SCREEN_AI_PREFETCH": os.environ.get("SCREEN_AI_PREFETCH", "1"),
                "SCREEN_AI_ALLOW_COLD_LLM": os.environ.get("SCREEN_AI_ALLOW_COLD_LLM", "0"),
                "SCREEN_AI_RAM_MB": os.environ.get("SCREEN_AI_RAM_MB", ""),
            },
        }

    def _load_usage(self) -> dict[str, dict[str, Any]]:
        if not self.usage_path.exists():
            return {}
        try:
            return json.loads(self.usage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_usage(self) -> None:
        self.usage_path.write_text(json.dumps(self.usage, indent=2), encoding="utf-8")

    def _env_bool(self, name: str, default: bool) -> bool:
        value = os.environ.get(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _env_int(self, name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, str(default)))
        except ValueError:
            return default
