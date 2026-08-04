"""Greenbone/OpenVAS connector — vulnerability scan lookups.

demo mode: reads data/sample_alerts/greenbone_sample.json, filters by host_ip
live mode: TODO — query GMP/REST API using GREENBONE_URL / GREENBONE_USER / GREENBONE_PASSWORD
"""
import json
import os
from pathlib import Path


class GreenboneTool:
    name = "get_vulns_for_host"

    def __init__(self, mode: str = "demo"):
        self.mode = mode
        self.base_url = os.getenv("GREENBONE_URL")
        self.sample_path = Path("data/sample_alerts/greenbone_sample.json")

    def get_vulns_for_host(self, host_ip: str) -> list[dict]:
        if self.mode == "demo":
            data = json.loads(self.sample_path.read_text())
            return [v for v in data if v.get("host") == host_ip]
        raise NotImplementedError("Live Greenbone mode not yet implemented")

    def as_tool_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Look up known vulnerabilities (CVEs) for a given host IP from Greenbone scans.",
                "parameters": {
                    "type": "object",
                    "properties": {"host_ip": {"type": "string", "description": "Host IP address to check"}},
                    "required": ["host_ip"],
                },
            },
        }
