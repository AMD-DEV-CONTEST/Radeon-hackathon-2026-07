from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse


class RadeonEvidenceStore:
    REQUIRED_FILES = (
        "README.md",
        "rocm-verified/radeon-benchmark-run.json",
        "rocm-verified/rocm-verified-diagnostics.txt",
        "rocm-verified/rocm-agent-live-latency-zh.txt",
        "rocm-verified/rocm-agent-live-response-zh.json",
        "rocm-verified/rocm-audit-export.json",
    )

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def summary(self) -> dict[str, object]:
        paths = {relative: self.root / relative for relative in self.REQUIRED_FILES}
        if not all(path.is_file() for path in paths.values()):
            return {"available": False, "reason": "evidence_missing"}
        try:
            readme = paths["README.md"].read_text(encoding="utf-8")
            benchmark = json.loads(
                paths["rocm-verified/radeon-benchmark-run.json"].read_text(encoding="utf-8")
            )
            diagnostics = paths["rocm-verified/rocm-verified-diagnostics.txt"].read_text(encoding="utf-8")
            agent_latency_ms = round(
                float(paths["rocm-verified/rocm-agent-live-latency-zh.txt"].read_text().strip()) * 1000,
                3,
            )
            app_status = self._section_json(diagnostics, "app status")
            parsed = self._parse_diagnostics(diagnostics)
            instance_id = self._match(readme, r"instance\s+`([^`]+)`")
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return {"available": False, "reason": "evidence_invalid"}

        if not self._consistent(benchmark, app_status, parsed, instance_id):
            return {"available": False, "reason": "evidence_inconsistent"}

        return {
            "available": True,
            "verification": "verified",
            "captured_at": str(benchmark["created_at"]),
            "verified_at": parsed["verified_at"],
            "instance_id": instance_id,
            "gpu": {
                "name": str(benchmark["gpu_name"]),
                "architecture": parsed["architecture"],
                "vram_bytes": parsed["vram_bytes"],
            },
            "runtime": {
                "rocm_version": str(benchmark["rocm_version"]),
                "pytorch_version": parsed["pytorch_version"],
                "hip_version": parsed["hip_version"],
                "vllm_version": parsed["vllm_version"],
            },
            "model": {
                "name": str(benchmark["model_name"]),
                "endpoint": str(app_status["model_endpoint"]),
                "provider": str(app_status["provider"]),
                "provider_mode": str(app_status["provider_mode"]),
                "location": str(app_status["core_inference_location"]),
            },
            "metrics": {
                "latency_ms": round(float(benchmark["latency_ms"]), 3),
                "tokens_per_second": round(float(benchmark["tokens_per_second"]), 3),
                "prompt_tokens": int(benchmark["prompt_tokens"]),
                "completion_tokens": int(benchmark["completion_tokens"]),
                "agent_latency_ms": agent_latency_ms,
            },
            "sources": [
                {"name": Path(relative).name, "path": relative.replace("\\", "/")}
                for relative in self.REQUIRED_FILES
            ],
        }

    @staticmethod
    def _match(text: str, pattern: str) -> str:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if not match:
            raise ValueError("Required evidence field is missing.")
        return match.group(1).strip()

    def _parse_diagnostics(self, diagnostics: str) -> dict[str, object]:
        vllm_section = re.search(r"=== vllm ===\s*\n([^\r\n]+)", diagnostics)
        if not vllm_section:
            raise ValueError("vLLM evidence is missing.")
        return {
            "verified_at": self._match(diagnostics, r"^PrivateOps Radeon Cloud verified evidence\s*\n([^\r\n]+)"),
            "architecture": self._match(diagnostics, r"GFX Version:\s*(gfx\d+)")
            if "GFX Version:" in diagnostics
            else self._match(diagnostics, r"Name:\s*(gfx\d+)"),
            "vram_bytes": int(self._match(diagnostics, r"VRAM Total Memory \(B\):\s*(\d+)")),
            "pytorch_version": self._match(diagnostics, r"^torch=([^\r\n]+)"),
            "hip_version": self._match(diagnostics, r"^hip=([^\r\n]+)"),
            "vllm_version": vllm_section.group(1).strip(),
        }

    @staticmethod
    def _section_json(text: str, section: str) -> dict[str, object]:
        match = re.search(rf"=== {re.escape(section)} ===\s*\n(\{{[^\r\n]+\}})", text)
        if not match:
            raise ValueError(f"{section} evidence is missing.")
        data = json.loads(match.group(1))
        if not isinstance(data, dict):
            raise ValueError(f"{section} evidence is invalid.")
        return data

    @staticmethod
    def _consistent(
        benchmark: dict[str, object],
        app_status: dict[str, object],
        parsed: dict[str, object],
        instance_id: str,
    ) -> bool:
        required_benchmark = {
            "created_at", "gpu_name", "rocm_version", "model_name", "latency_ms",
            "tokens_per_second", "prompt_tokens", "completion_tokens",
        }
        if not required_benchmark.issubset(benchmark):
            return False
        endpoint = str(app_status.get("model_endpoint", ""))
        hostname = (urlparse(endpoint).hostname or "").lower()
        rocm_family = ".".join(str(benchmark.get("rocm_version", "")).split(".")[:2])
        return all(
            (
                benchmark.get("verified") is True,
                benchmark.get("provider_mode") == "rocm-local",
                app_status.get("provider_mode") == "rocm-local",
                app_status.get("provider") == "openai-compatible-rocm",
                app_status.get("core_inference_location") == "same-instance loopback",
                benchmark.get("model_name") == app_status.get("model_name"),
                "amd radeon" in str(benchmark.get("gpu_name", "")).lower(),
                bool(rocm_family) and str(parsed.get("hip_version", "")).startswith(rocm_family + "."),
                hostname in {"127.0.0.1", "localhost", "::1"},
                instance_id.startswith("u-"),
            )
        )
