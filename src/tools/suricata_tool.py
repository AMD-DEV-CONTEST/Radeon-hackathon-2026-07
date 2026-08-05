"""Suricata connector — fetch network alerts.

demo mode: reads data/sample_alerts/suricata_sample.json
live mode: TODO — tail/parse eve.json (SURICATA_LOG_PATH) or pull via Wazuh integration
"""
import json
import os
from pathlib import Path


class SuricataTool:
    name = "get_recent_suricata_alerts"

    def __init__(self, mode: str = "demo"):
        self.mode = mode
        self.log_path = os.getenv("SURICATA_LOG_PATH", "/var/log/suricata/eve.json")
        self.sample_path = Path("data/sample_alerts/suricata_sample.json")

    def get_recent_alerts(self, limit: int = 5) -> list[dict]:
        if self.mode == "demo":
            data = json.loads(self.sample_path.read_text())
            return data[:limit]
        raise NotImplementedError("Live Suricata mode not yet implemented")

    def as_tool_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Fetch recent network intrusion alerts from Suricata.",
                "parameters": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "description": "Max alerts to return"}},
                },
            },
        }
