"""Broker config loader."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class BrokerConfig:
    host: str = "127.0.0.1"
    port: int = 7432
    registry_path: Path = Path("./registry/org_registry.json")
    replay_window_sec: int = 600
    event_channel_max_clients: int = 16
    metrics_channel_max_clients: int = 16


def load_config(path: Path | str) -> BrokerConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    section = raw.get("broker", {})
    return BrokerConfig(
        host=section.get("host", "127.0.0.1"),
        port=int(section.get("port", 7432)),
        registry_path=Path(section.get("registry", "./registry/org_registry.json")),
        replay_window_sec=int(section.get("replay_window_sec", 600)),
        event_channel_max_clients=int(section.get("event_channel_max_clients", 16)),
        metrics_channel_max_clients=int(section.get("metrics_channel_max_clients", 16)),
    )
