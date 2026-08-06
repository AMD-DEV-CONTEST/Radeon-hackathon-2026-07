from __future__ import annotations

import json
from pathlib import Path

from agent_factory.scheduler_system.schema import SchedulerExecutionReport


class SchedulerReportWriter:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def write(self, report: SchedulerExecutionReport) -> str:
        target = self.root / report.job_id / f"{report.run_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        return str(target)
