"""Screen perception cache used by the agent runtime."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
CACHE = ROOT / "ai_pc_operator" / "data" / ".screen_ai_cache"


class ScreenCache:
    """Small JSON cache for UI maps, OCR results, and detector results."""

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

    def key_text(self, text: str, context: str = "") -> str:
        return self.key_bytes(text.encode("utf-8", errors="ignore"), context)

    def read_json(
        self,
        group: str,
        key: str,
        max_age_sec: int = 300,
    ) -> dict[str, Any] | None:
        path = self._group_dir(group) / f"{key}.json"
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > max_age_sec:
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, group: str, key: str, payload: dict[str, Any]) -> None:
        path = self._group_dir(group) / f"{key}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def stats(self) -> dict[str, Any]:
        return {
            "cache_dir": str(self.cache_dir),
            "ui_maps": self._count(self.ui_maps),
            "ocr_results": self._count(self.ocr_results),
            "detector_results": self._count(self.detector_results),
        }

    def _group_dir(self, group: str) -> Path:
        if group == "ui":
            return self.ui_maps
        if group == "ocr":
            return self.ocr_results
        if group == "detector":
            return self.detector_results
        raise ValueError(f"unknown cache group: {group}")

    def _count(self, path: Path) -> int:
        return sum(1 for item in path.glob("*.json") if item.is_file())
