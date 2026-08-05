"""Wazuh connector — fetch alerts.

demo mode: reads data/sample_alerts/wazuh_sample.json
live mode: TODO — call the real Wazuh API using WAZUH_URL / WAZUH_USER / WAZUH_PASSWORD
"""
import json
import os
from pathlib import Path


class WazuhTool:
    name = "get_recent_wazuh_alerts"

    def __init__(self, mode: str = "demo"):
        self.mode = mode
        self.base_url = os.getenv("WAZUH_URL")
        self.sample_path = Path("data/sample_alerts/wazuh_sample.json")

    def get_recent_alerts(self, limit: int = 5) -> list[dict]:
        if self.mode == "demo":
            data = json.loads(self.sample_path.read_text())
            return data[:limit]
        # TODO live mode: authenticate + query real Wazuh API
        raise NotImplementedError("Live Wazuh mode not yet implemented")

    def as_tool_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Fetch recent security alerts from Wazuh (host-based IDS).",
                "parameters": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "description": "Max alerts to return"}},
                },
            },
        }
