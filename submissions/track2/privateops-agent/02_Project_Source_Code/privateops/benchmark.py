from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BenchmarkStore:
    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.state_dir / "benchmarks.json"

    def record(self, payload: dict[str, Any]) -> dict[str, Any]:
        mode = str(payload.get("provider_mode", ""))
        verified = bool(payload.get("verified", False))
        if mode not in {"development", "rocm-local"}:
            raise ValueError("provider_mode must be development or rocm-local.")
        if mode == "development" and verified:
            raise ValueError("Development runs cannot be marked as verified GPU evidence.")
        gpu_name = str(payload.get("gpu_name", "")).strip()
        rocm_version = str(payload.get("rocm_version", "")).strip()
        rocminfo_excerpt = str(payload.get("rocminfo_excerpt", "")).strip()
        if verified and "amd radeon" not in gpu_name.lower():
            raise ValueError("Verified runs require an AMD Radeon GPU name.")
        if verified and (not rocm_version or not rocminfo_excerpt):
            raise ValueError("Verified runs require ROCm version and rocminfo proof.")
        try:
            latency_ms = float(payload.get("latency_ms", 0))
            tokens_per_second = float(payload.get("tokens_per_second", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("Benchmark metrics must be numeric.") from exc
        if latency_ms <= 0 or tokens_per_second < 0:
            raise ValueError("Latency must be positive and throughput cannot be negative.")
        run = {
            "run_id": f"bench-{uuid.uuid4().hex[:12]}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "label": str(payload.get("label", mode)).strip() or mode,
            "provider_mode": mode,
            "verified": verified,
            "gpu_name": gpu_name,
            "rocm_version": rocm_version,
            "model_name": str(payload.get("model_name", "")).strip(),
            "rocminfo_excerpt": rocminfo_excerpt[:1200],
            "latency_ms": round(latency_ms, 3),
            "tokens_per_second": round(tokens_per_second, 3),
            "prompt_tokens": int(payload.get("prompt_tokens", 0)),
            "completion_tokens": int(payload.get("completion_tokens", 0)),
            "notes": str(payload.get("notes", "")).strip(),
        }
        runs = self.load()
        runs.append(run)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
        return run

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    def compare(self) -> dict[str, Any]:
        runs = self.load()
        baseline = next((item for item in runs if item["provider_mode"] == "development"), None)
        rocm = next((item for item in reversed(runs) if item["provider_mode"] == "rocm-local" and item["verified"]), None)
        if not baseline or not rocm:
            return {"ready": False, "message": "Record a development baseline and a verified Radeon run."}
        return {
            "ready": True,
            "baseline_run_id": baseline["run_id"],
            "rocm_run_id": rocm["run_id"],
            "latency_speedup": round(baseline["latency_ms"] / rocm["latency_ms"], 3),
            "throughput_speedup": round(rocm["tokens_per_second"] / baseline["tokens_per_second"], 3)
            if baseline["tokens_per_second"] > 0
            else None,
        }

    def export(self) -> dict[str, Any]:
        return {"schema_version": "1.0", "runs": self.load(), "comparison": self.compare()}

    def export_csv(self) -> str:
        fields = [
            "run_id", "created_at", "label", "provider_mode", "verified", "gpu_name",
            "rocm_version", "model_name", "latency_ms", "tokens_per_second",
            "prompt_tokens", "completion_tokens", "notes",
        ]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(self.load())
        return stream.getvalue()
