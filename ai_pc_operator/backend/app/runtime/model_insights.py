"""Static model intelligence extracted from local inspection reports.

This module is intentionally metadata-only. It lets the router choose model
lanes without importing torch, onnxruntime, or llama.cpp during startup.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.runtime.artifact_store import ArtifactStore, ROOT
from app.runtime.resource_budget import RuntimeBudget


MODELS_DIR = ROOT / "ai_pc_operator" / "data" / "models"


@dataclass(frozen=True)
class ModelCard:
    name: str
    registry_name: str
    role: str
    format: str
    preferred_path: str
    report_path: str
    estimated_ram_mb: int
    artifact_mb: float
    residency: str
    low_ram_policy: str
    parallel_group: str
    prefetch_policy: str
    facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, models_dir: Path, store: ArtifactStore) -> dict[str, Any]:
        artifact = store.find(self.registry_name)
        preferred = models_dir / self.preferred_path
        report = models_dir / self.report_path
        payload = asdict(self)
        payload["preferred_path"] = str(preferred)
        payload["report_path"] = str(report)
        payload["exists"] = {
            "preferred": preferred.exists(),
            "report": report.exists(),
            "discovered": artifact.to_dict() if artifact else None,
        }
        return payload


class ModelInsights:
    """Command-to-model lane planner for the local Screen-AI stack."""

    def __init__(
        self,
        store: ArtifactStore,
        models_dir: Path = MODELS_DIR,
    ) -> None:
        self.store = store
        self.models_dir = models_dir
        self.cards = self._cards()

    def summary(self) -> dict[str, Any]:
        return {
            "source": "local inspection reports",
            "policy": "resident rules first, OCR warm, Qwen mmap cold, OmniParser teacher only",
            "models": {
                name: card.to_dict(self.models_dir, self.store)
                for name, card in self.cards.items()
            },
            "lanes": {
                "fast-perception": ["ocr-det-v3", "ocr-rec-english"],
                "reasoning": ["qwen-1.5b-q4"],
                "teacher": ["omniparser-v2-icon-detect"],
            },
        }

    def card(self, name: str) -> dict[str, Any] | None:
        card = self.cards.get(name)
        if not card:
            return None
        return card.to_dict(self.models_dir, self.store)

    def plan_for_command(
        self,
        text: str,
        intent: str,
        budget: RuntimeBudget,
        hot_models: list[str] | None = None,
    ) -> dict[str, Any]:
        lower = text.lower()
        hot_models = hot_models or []
        needs_screen = intent in {"screen_scan", "screen_click", "click_text"} or any(
            word in lower
            for word in ("screen", "button", "click", "window", "ui", "ocr", "read")
        )
        needs_browser = intent in {"search_web", "open_website", "research_collect"} or any(
            word in lower
            for word in ("chrome", "browser", "search", "website", "webpage", "download")
        )
        needs_vault = intent in {"login", "auth"} or any(
            word in lower
            for word in ("login", "password", "passkey", "credential", "vault")
        )
        needs_reasoning = intent == "unknown" or any(
            word in lower
            for word in ("plan", "compare", "research", "summarize", "analyze", "decide")
        )

        lanes: list[dict[str, Any]] = []
        recommended: list[str] = []
        prefetch: list[str] = []

        if needs_screen:
            lane_models = ["ocr-det-v3", "ocr-rec-english"]
            lanes.append(
                {
                    "lane": "fast-perception",
                    "models": lane_models,
                    "mode": "parallel",
                    "why": "screen/UI commands need detection and recognition together",
                }
            )
            recommended.extend(["ocr-mobile", "ui-detector-int8"])
            if budget.allow_ocr:
                prefetch.append("ocr-mobile")
            if budget.allow_detector and budget.model_budget_mb >= 500:
                prefetch.append("ui-detector-int8")

        if needs_browser:
            lanes.append(
                {
                    "lane": "browser-tools",
                    "models": ["browser-warmup"],
                    "mode": "warm-import",
                    "why": "browser tasks benefit from Playwright warmup",
                }
            )
            recommended.append("browser-warmup")
            prefetch.append("browser-warmup")

        if needs_vault:
            lanes.append(
                {
                    "lane": "secure-vault",
                    "models": ["vault-crypto"],
                    "mode": "resident",
                    "why": "credential/passkey actions need crypto modules warm",
                }
            )
            recommended.append("vault-crypto")
            prefetch.append("vault-crypto")

        if needs_reasoning and budget.allow_llm:
            lanes.append(
                {
                    "lane": "reasoning",
                    "models": ["qwen-1.5b-q4"],
                    "mode": "ssd-mmap-on-demand",
                    "why": "complex/unknown command can use local GGUF planner",
                }
            )
            recommended.append("qwen-1.5b-q4")
        elif needs_reasoning:
            lanes.append(
                {
                    "lane": "reasoning",
                    "models": ["rule-planner"],
                    "mode": "low-ram",
                    "why": "Qwen is kept cold/off when RAM budget is too small",
                }
            )

        if "ui-detector-int8" in hot_models and budget.allow_detector:
            prefetch.append("ui-detector-int8")
        if "ocr-mobile" in hot_models and budget.allow_ocr:
            prefetch.append("ocr-mobile")

        teacher_available = bool(self.store.find("ui-detector-int8")) or (
            self.models_dir / "teachers" / "omniparser_v2_icon_detect.pt"
        ).exists()

        return {
            "budget_mode": budget.mode,
            "model_budget_mb": budget.model_budget_mb,
            "recommended": self._dedupe(recommended),
            "prefetch": self._dedupe(
                name for name in prefetch if name != "qwen-1.5b-q4"
            ),
            "lanes": lanes or [
                {
                    "lane": "tier0-rules",
                    "models": ["rule-planner", "native-core"],
                    "mode": "resident",
                    "why": "simple command can stay in lightweight rules/tools",
                }
            ],
            "teacher_fallback": {
                "model": "omniparser-v2-icon-detect",
                "enabled_by_default": False,
                "available": teacher_available,
                "why": "teacher model is for cloud distillation or explicit high-confidence fallback, not 4GB resident mode",
            },
        }

    def _cards(self) -> dict[str, ModelCard]:
        return {
            "qwen-1.5b-q4": ModelCard(
                name="qwen-1.5b-q4",
                registry_name="qwen-1.5b-q4",
                role="local planner/reasoner",
                format="GGUF Q4_0",
                preferred_path="qwen2.5-coder-1.5b-instruct-q4_0.gguf",
                report_path="qwen2.5-coder-1.5b-instruct-q4_0_INSPECTION.txt",
                estimated_ram_mb=1200,
                artifact_mb=0.0,
                residency="ssd-mmap-on-demand",
                low_ram_policy="ctx 512-768, 2 CPU threads, no speculative prefetch",
                parallel_group="reasoning",
                prefetch_policy="never prefetch on 4GB profile",
                facts={
                    "architecture": "qwen2",
                    "context_length": 32768,
                    "block_count": 28,
                    "embedding_length": 1536,
                    "attention_heads": 12,
                    "kv_heads": 2,
                },
            ),
            "ocr-det-v3": ModelCard(
                name="ocr-det-v3",
                registry_name="ocr-mobile",
                role="text region detector",
                format="ONNX opset 14",
                preferred_path="ocr_det_v3.onnx",
                report_path="ocr_det_v3_DEEP_REPORT.txt",
                estimated_ram_mb=32,
                artifact_mb=2.32,
                residency="resident-or-warm",
                low_ram_policy="safe to keep warm; dynamic H/W input",
                parallel_group="fast-perception",
                prefetch_policy="prefetch for screen_scan/screen_click when OCR budget exists",
                facts={
                    "input": "N x 3 x H x W",
                    "output": "N x 1 x H x W",
                    "nodes": 572,
                    "dominant_ops": ["Constant", "Conv", "BatchNormalization", "Add"],
                },
            ),
            "ocr-rec-english": ModelCard(
                name="ocr-rec-english",
                registry_name="ocr-mobile",
                role="English text recognizer",
                format="ONNX opset 14",
                preferred_path="ocr_rec_english.onnx",
                report_path="ocr_rec_english_DEEP_REPORT.txt",
                estimated_ram_mb=80,
                artifact_mb=7.47,
                residency="warm-after-detector",
                low_ram_policy="height 48 preprocessing, dynamic width, load with OCR lane",
                parallel_group="fast-perception",
                prefetch_policy="load with detector for screen text tasks",
                facts={
                    "input": "N x 3 x 48 x W",
                    "output": "N x T x 438",
                    "nodes": 746,
                    "dominant_ops": ["Constant", "Add", "Mul", "Reshape", "Conv"],
                },
            ),
            "omniparser-v2-icon-detect": ModelCard(
                name="omniparser-v2-icon-detect",
                registry_name="ui-detector-int8",
                role="teacher icon detector / distillation source",
                format="Ultralytics YOLO",
                preferred_path="teachers/omniparser_v2_icon_detect.pt",
                report_path="teachers/omniparser_v2_icon_detect_INSPECTION.txt",
                estimated_ram_mb=800,
                artifact_mb=38.74,
                residency="cloud-teacher-or-explicit-fallback",
                low_ram_policy="do not keep resident on 4GB laptop",
                parallel_group="teacher",
                prefetch_policy="never prefetch locally; use exported INT8 student instead",
                facts={
                    "nc": 1,
                    "scale": "m",
                    "yaml_file": "yolo11m.yaml",
                    "reported_memory_mb": 76.68,
                },
            ),
        }

    def _dedupe(self, values) -> list[str]:
        return list(dict.fromkeys(values))
