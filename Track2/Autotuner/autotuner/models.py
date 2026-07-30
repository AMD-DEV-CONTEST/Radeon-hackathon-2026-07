from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Candidate:
    engine: str
    model: str
    quantization: str
    attention_backend: str
    kv_cache_dtype: str
    max_num_seqs: int
    gpu_memory_utilization: float
    max_model_len: int
    speculative_model: str = ""
    num_speculative_tokens: int = 0

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "Candidate":
        return cls(
            engine=str(value["engine"]),
            model=str(value["model"]),
            quantization=str(value.get("quantization", "none")),
            attention_backend=str(value.get("attention_backend", "auto")),
            kv_cache_dtype=str(value.get("kv_cache_dtype", "auto")),
            max_num_seqs=int(value.get("max_num_seqs", 8)),
            gpu_memory_utilization=float(
                value.get("gpu_memory_utilization", 0.9)
            ),
            max_model_len=int(value.get("max_model_len", 4096)),
            speculative_model=str(value.get("speculative_model", "")),
            num_speculative_tokens=int(
                value.get("num_speculative_tokens", 0)
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def key(self) -> str:
        payload = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf8")
        return hashlib.sha256(payload).hexdigest()[:12]

    def label(self) -> str:
        speculative = (
            str(self.num_speculative_tokens)
            if self.speculative_model
            else "off"
        )
        return (
            f"{self.engine} | {self.quantization} | "
            f"{self.attention_backend} | kv {self.kv_cache_dtype} | "
            f"seqs {self.max_num_seqs} | memory "
            f"{self.gpu_memory_utilization:.2f} | spec {speculative}"
        )


@dataclass
class BenchmarkResult:
    output_tokens: int
    duration_seconds: float
    tokens_per_second: float
    latency_p50_ms: float
    latency_p95_ms: float
    error_rate: float
    quality_score: float
    peak_vram_mb: float
    responses: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "BenchmarkResult":
        return cls(
            output_tokens=int(value["output_tokens"]),
            duration_seconds=float(value["duration_seconds"]),
            tokens_per_second=float(value["tokens_per_second"]),
            latency_p50_ms=float(value["latency_p50_ms"]),
            latency_p95_ms=float(value["latency_p95_ms"]),
            error_rate=float(value["error_rate"]),
            quality_score=float(value["quality_score"]),
            peak_vram_mb=float(value.get("peak_vram_mb", 0.0)),
            responses=list(value.get("responses", [])),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Trial:
    index: int
    candidate: Candidate
    result: BenchmarkResult
    hypothesis: str
    started_at: str
    completed_at: str
    accepted: bool
    rejection_reason: str = ""
    profile_directory: str = ""

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "Trial":
        return cls(
            index=int(value["index"]),
            candidate=Candidate.from_dict(value["candidate"]),
            result=BenchmarkResult.from_dict(value["result"]),
            hypothesis=str(value.get("hypothesis", "")),
            started_at=str(value.get("started_at", "")),
            completed_at=str(value.get("completed_at", "")),
            accepted=bool(value.get("accepted", False)),
            rejection_reason=str(value.get("rejection_reason", "")),
            profile_directory=str(value.get("profile_directory", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["candidate"] = self.candidate.to_dict()
        result["result"] = self.result.to_dict()
        return result


@dataclass
class Proposal:
    candidate: Candidate
    hypothesis: str
    source: str


@dataclass
class RunRecord:
    run_id: str
    name: str
    started_at: str
    completed_at: str
    mode: str
    hardware: Dict[str, Any]
    config: Dict[str, Any]
    trials: List[Trial]
    best_candidate_key: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "name": self.name,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "mode": self.mode,
            "hardware": self.hardware,
            "config": self.config,
            "trials": [trial.to_dict() for trial in self.trials],
            "best_candidate_key": self.best_candidate_key,
        }
