from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class TuneConfig:
    name: str
    endpoint: str
    host: str
    port: int
    manage_server: bool
    startup_timeout_seconds: int
    cooldown_seconds: float
    trials: int
    warmup_requests: int
    benchmark_requests: int
    concurrency: int
    prompts: List[str]
    max_tokens: int
    required_terms: List[str]
    quality_floor: float
    latency_limit_ms: float
    error_limit: float
    use_local_agent: bool
    profile_trials: List[int]
    seed: int
    engines: List[Dict[str, Any]]
    search_space: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


REQUIRED_FIELDS = {
    "name",
    "endpoint",
    "trials",
    "prompts",
    "engines",
    "search_space",
}


def load_config(path: Path) -> TuneConfig:
    with path.open("r", encoding="utf8") as handle:
        value = json.load(handle)
    missing = sorted(REQUIRED_FIELDS.difference(value))
    if missing:
        raise ValueError(
            "Configuration is missing fields: " + ", ".join(missing)
        )
    if not value["prompts"]:
        raise ValueError("At least one benchmark prompt is required")
    if not value["engines"]:
        raise ValueError("At least one engine profile is required")
    if int(value["trials"]) < 1:
        raise ValueError("Trial count must be positive")
    return TuneConfig(
        name=str(value["name"]),
        endpoint=str(value["endpoint"]).rstrip("/"),
        host=str(value.get("host", "127.0.0.1")),
        port=int(value.get("port", 8000)),
        manage_server=bool(value.get("manage_server", True)),
        startup_timeout_seconds=int(
            value.get("startup_timeout_seconds", 600)
        ),
        cooldown_seconds=float(value.get("cooldown_seconds", 2)),
        trials=int(value["trials"]),
        warmup_requests=int(value.get("warmup_requests", 2)),
        benchmark_requests=int(value.get("benchmark_requests", 12)),
        concurrency=int(value.get("concurrency", 4)),
        prompts=[str(item) for item in value["prompts"]],
        max_tokens=int(value.get("max_tokens", 128)),
        required_terms=[
            str(item).lower() for item in value.get("required_terms", [])
        ],
        quality_floor=float(value.get("quality_floor", 0.95)),
        latency_limit_ms=float(value.get("latency_limit_ms", 30000)),
        error_limit=float(value.get("error_limit", 0.02)),
        use_local_agent=bool(value.get("use_local_agent", True)),
        profile_trials=[
            int(item) for item in value.get("profile_trials", [1])
        ],
        seed=int(value.get("seed", 7)),
        engines=list(value["engines"]),
        search_space=dict(value["search_space"]),
    )


def engine_profile(
    config: TuneConfig, engine_name: str
) -> Dict[str, Any]:
    for profile in config.engines:
        if profile.get("name") == engine_name:
            return profile
    raise ValueError(f"No engine profile named {engine_name}")
