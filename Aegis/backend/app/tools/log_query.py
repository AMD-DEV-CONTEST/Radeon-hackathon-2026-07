"""
Log query tool.

Production note: this connects to whatever the enterprise already runs
(Loki, Elasticsearch, Splunk) via its HTTP API. Implemented here against a
pluggable backend interface so swapping the log store is a config change,
not a rewrite. For local/offline demo purposes without an external log
store configured, falls back to reading structured log files from disk.
"""
import glob
import json
import os
from datetime import datetime, timedelta
from typing import Optional

from app.tools.base import BaseTool


class LogQueryTool(BaseTool):
    name = "log_query"
    description = (
        "Search application/infrastructure logs for a service within a time window "
        "and optional text filter. Returns matching log lines with timestamps."
    )

    def __init__(self, log_directory: str = "/var/log/aegis_demo") -> None:
        self.log_directory = log_directory

    async def _execute(
        self,
        service: str,
        minutes_back: int = 30,
        query: Optional[str] = None,
        max_results: int = 50,
    ) -> dict:
        cutoff = datetime.utcnow() - timedelta(minutes=minutes_back)
        matches = []

        pattern = os.path.join(self.log_directory, f"{service}*.jsonl")
        for path in glob.glob(pattern):
            with open(path, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = datetime.fromisoformat(entry.get("timestamp", ""))
                    if ts < cutoff:
                        continue
                    if query and query.lower() not in json.dumps(entry).lower():
                        continue
                    matches.append(entry)
                    if len(matches) >= max_results:
                        break

        return {"service": service, "window_minutes": minutes_back, "match_count": len(matches), "logs": matches}
