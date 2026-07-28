"""
Client-side metrics collector for tracking CLI session performance and decision metrics.
Records execution metrics such as time-to-first-token (TTFT), turn duration, gate decision counts, and egress violations to JSONL log files.
"""

import json
import os
import time
from typing import Any, Dict, Optional


class MetricsCollector:
    def __init__(self, log_dir: Optional[str] = None):
        if not log_dir:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            log_dir = os.path.abspath(os.path.join(current_dir, "..", "..", "logs", "metrics"))
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_file = os.path.join(self.log_dir, "cli_metrics.jsonl")
        
        self.start_time: float = 0.0
        self.first_token_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.token_count: int = 0
        self.human_decisions: int = 0
        self.automated_decisions: int = 0
        self.denials: int = 0

    def start_turn(self) -> None:
        self.start_time = time.time()
        self.first_token_time = None
        self.end_time = None
        self.token_count = 0

    def record_token(self) -> None:
        if self.first_token_time is None:
            self.first_token_time = time.time()
        self.token_count += 1

    def record_decision(self, is_automated: bool, is_allowed: bool) -> None:
        if is_automated:
            self.automated_decisions += 1
        else:
            self.human_decisions += 1

        if not is_allowed:
            self.denials += 1

    def end_turn(self, session_id: str = "", mode: str = "chat", exit_code: int = 0) -> Dict[str, Any]:
        self.end_time = time.time()
        ttft = (self.first_token_time - self.start_time) if self.first_token_time else 0.0
        duration = self.end_time - self.start_time

        metric_record = {
            "timestamp": time.time(),
            "session_id": session_id,
            "mode": mode,
            "duration_seconds": round(duration, 4),
            "ttft_seconds": round(ttft, 4),
            "tokens_generated": self.token_count,
            "human_decisions": self.human_decisions,
            "automated_decisions": self.automated_decisions,
            "denials": self.denials,
            "exit_code": exit_code,
        }

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(metric_record) + "\n")
        except Exception:
            pass

        return metric_record
