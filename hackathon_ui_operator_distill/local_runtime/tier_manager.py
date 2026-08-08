from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".screen_ai_cache"


@dataclass
class TierDecision:
    tier: str
    reason: str
    model: str | None = None
    cache_hit: bool = False


class ScreenCache:
    def __init__(self, cache_dir: Path = CACHE) -> None:
        self.cache_dir = cache_dir
        self.ui_maps = cache_dir / "ui_maps"
        self.ocr_results = cache_dir / "ocr_results"
        self.detector_results = cache_dir / "detector_results"
        for path in [self.ui_maps, self.ocr_results, self.detector_results]:
            path.mkdir(parents=True, exist_ok=True)

    def key_bytes(self, image_bytes: bytes, context: str = "") -> str:
        digest = hashlib.sha256()
        digest.update(image_bytes)
        digest.update(context.encode("utf-8", errors="ignore"))
        return digest.hexdigest()[:24]

    def read_json(self, group: str, key: str, max_age_sec: int = 300) -> dict[str, Any] | None:
        path = self._group_dir(group) / f"{key}.json"
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > max_age_sec:
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, group: str, key: str, payload: dict[str, Any]) -> None:
        path = self._group_dir(group) / f"{key}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _group_dir(self, group: str) -> Path:
        if group == "ui":
            return self.ui_maps
        if group == "ocr":
            return self.ocr_results
        if group == "detector":
            return self.detector_results
        raise ValueError(f"unknown cache group: {group}")


class TierManager:
    def __init__(self, ram_budget_mb: int = 1024) -> None:
        self.ram_budget_mb = ram_budget_mb
        self.cache = ScreenCache()
        self.loaded_models: dict[str, Any] = {}
        self.last_used: dict[str, float] = {}

    def choose_for_click(self, uia_found: bool, ocr_available: bool, detector_available: bool) -> TierDecision:
        if uia_found:
            return TierDecision(tier="tier0", reason="UI Automation found exact target", cache_hit=True)
        if ocr_available:
            return TierDecision(tier="tier1", reason="Need text OCR fallback", model="paddleocr-mobile")
        if detector_available:
            return TierDecision(tier="tier1", reason="Need tiny UI detector fallback", model="ui-detector-int8.onnx")
        return TierDecision(tier="tier2", reason="Need heavy parser or cloud fallback", model="omniparser-optional")

    def unload_idle(self, idle_sec: int = 120) -> list[str]:
        now = time.time()
        unloaded = []
        for name in list(self.loaded_models):
            if now - self.last_used.get(name, now) > idle_sec:
                del self.loaded_models[name]
                self.last_used.pop(name, None)
                unloaded.append(name)
        return unloaded

    def record_decision(self, decision: TierDecision) -> dict[str, Any]:
        return asdict(decision)

