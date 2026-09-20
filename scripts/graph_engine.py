#!/usr/bin/env python3
"""Safe graph-based diagnose -> repair -> verify loop for the local Agent stack.

The first graph targets the Open WebUI/vLLM/RAG context failure mode. It is
deliberately conservative: only a small allow-list of Open WebUI settings can
be changed, every change is backed up, and a failed verification rolls back.

Examples:
    python scripts/graph_engine.py --target remote
    python scripts/graph_engine.py --target remote --apply --max-rounds 5
    python scripts/graph_engine.py --target local --apply
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen


SAFE_CONFIG = {
    "openai.api_base_urls": '["http://127.0.0.1:8000/v1"]',
    "chat.context_compaction.enable": "true",
    "chat.context_compaction.token_threshold": "20000",
    "chat.context_compaction.token_cap": "24000",
    "chat.context_compaction.retention_percentage": "40",
    "rag.chunk_size": "512",
    "rag.chunk_overlap": "128",
    "rag.full_context": "false",
}


@dataclass
class Finding:
    node: str
    severity: str
    message: str
    repairable: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunReport:
    target: str
    apply: bool
    rounds: int = 0
    status: str = "unknown"
    findings: list[Finding] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n")


class Executor:
    """Run a fixed command locally or over SSH; no arbitrary repair command is accepted."""

    def __init__(self, args: argparse.Namespace):
        self.args = args

    def run(self, command: str, timeout: int = 30) -> tuple[int, str]:
        if self.args.target == "local":
            argv = ["bash", "-lc", command]
        else:
            ssh = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", f"ConnectTimeout={self.args.ssh_timeout}",
                "-i", self.args.ssh_key,
                "-p", str(self.args.ssh_port),
                f"{self.args.ssh_user}@{self.args.ssh_host}",
                command,
            ]
            argv = ssh
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 124, str(exc)
        output = (result.stdout + result.stderr).strip()
        return result.returncode, output


class ContextGraph:
    def __init__(self, executor: Executor, report: RunReport):
        self.x = executor
        self.report = report
        self.db = "/workspace/persistent/open-webui/data/webui.db"
        self.backup = "/workspace/persistent/open-webui/data/webui.db.graph-engine.bak"

    def record(self, node: str, severity: str, message: str, repairable: bool = False, **evidence: Any) -> None:
        self.report.findings.append(Finding(node, severity, message, repairable, evidence))

    def health_node(self) -> bool:
        """Check the two services without reading credentials or model contents."""
        code, web = self.x.run("curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:8082/", 20)
        if code != 0 or web != "200":
            self.record("health", "error", "Open WebUI is not returning HTTP 200", True, output=web)
            return False
        code, models = self.x.run("curl -fsS http://127.0.0.1:8000/v1/models", 20)
        if code != 0 or "models/qwen-trader-merged" not in models:
            self.record("health", "error", "vLLM model endpoint is unavailable or model name differs", False, output=models[:500])
            return False
        return True

    def config_node(self) -> dict[str, str]:
        keys = ",".join("'" + k + "'" for k in SAFE_CONFIG)
        command = (
            f"sqlite3 -separator '|' {shlex.quote(self.db)} "
            f"\"select key,value from config where key in ({keys});\""
        )
        code, output = self.x.run(command)
        current: dict[str, str] = {}
        if code == 0:
            for line in output.splitlines():
                if "|" in line:
                    key, value = line.split("|", 1)
                    current[key] = value
        for key, expected in SAFE_CONFIG.items():
            if current.get(key) != expected:
                self.record("config", "warning", f"{key}={current.get(key)!r}, expected {expected!r}", True, key=key, current=current.get(key), expected=expected)
        return current

    def repair_node(self, current: dict[str, str]) -> bool:
        if not self.report.apply:
            self.report.actions.append("DRY-RUN: would back up and repair Open WebUI context/RAG settings")
            return True
        backup_cmd = f"cp -p {shlex.quote(self.db)} {shlex.quote(self.backup)}"
        code, output = self.x.run(backup_cmd)
        if code != 0:
            self.record("repair", "error", "Could not create Open WebUI database backup", False, output=output)
            return False
        statements = ["BEGIN"]
        now = "strftime('%s','now')*1000"
        for key, value in SAFE_CONFIG.items():
            statements.append(
                "INSERT INTO config(key,value,updated_at) VALUES "
                f"('{key}','{value}',{now}) ON CONFLICT(key) DO UPDATE SET "
                f"value='{value}',updated_at={now}"
            )
        statements.append("COMMIT")
        sql = "; ".join(statements) + ";"
        code, output = self.x.run(f"sqlite3 {shlex.quote(self.db)} {shlex.quote(sql)}")
        if code != 0:
            self.record("repair", "error", "Open WebUI configuration update failed", False, output=output)
            return False
        self.x.run("kill -TERM $(pgrep -f '/open-webui serve' | head -1)", 10)
        self.x.run("sleep 2; nohup /workspace/persistent/open-webui/venv/bin/open-webui serve --port 8082 >/workspace/persistent/open-webui/open-webui.log 2>&1 </dev/null &", 20)
        self.report.actions.append("Backed up and repaired Open WebUI context compaction and RAG chunk settings")
        return True

    def verify_node(self) -> bool:
        time.sleep(3)
        code, web = self.x.run("curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:8082/", 20)
        code2, models = self.x.run("curl -fsS http://127.0.0.1:8000/v1/models", 20)
        ok = code == 0 and web == "200" and code2 == 0 and "models/qwen-trader-merged" in models
        if not ok:
            self.record("verify", "error", "Post-repair health verification failed", True, web=web, vllm=models[:300])
        return ok

    def rollback_node(self) -> bool:
        if not self.report.apply:
            self.report.actions.append("DRY-RUN: would restore the Open WebUI database backup")
            return True
        code, output = self.x.run(f"cp -p {shlex.quote(self.backup)} {shlex.quote(self.db)} && kill -TERM $(pgrep -f '/open-webui serve' | head -1) || true")
        if code == 0:
            self.report.actions.append("Restored Open WebUI database backup after failed verification")
        else:
            self.record("rollback", "critical", "Rollback failed", False, output=output)
        return code == 0

    def run(self, max_rounds: int) -> RunReport:
        for round_no in range(1, max_rounds + 1):
            self.report.rounds = round_no
            start_findings = len(self.report.findings)
            healthy = self.health_node()
            current = self.config_node()
            needs_repair = len(self.report.findings) > start_findings
            if not needs_repair and healthy:
                self.report.status = "healthy"
                return self.report
            if not self.repair_node(current):
                self.report.status = "blocked"
                return self.report
            if self.verify_node():
                self.report.status = "fixed" if needs_repair else "healthy"
                return self.report
            self.rollback_node()
        self.report.status = "blocked"
        return self.report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local", "remote"), default="local")
    parser.add_argument("--apply", action="store_true", help="perform allow-listed repairs; default is diagnosis only")
    parser.add_argument("--max-rounds", type=int, default=5)
    parser.add_argument("--report", type=Path, default=Path("artifacts/graph_engine_report.json"))
    parser.add_argument("--ssh-host", default="***REMOVED***")
    parser.add_argument("--ssh-port", type=int, default=31036)
    parser.add_argument("--ssh-user", default="root")
    parser.add_argument("--ssh-key", default="/Users/simon/WorkBuddy/2026-07-17-00-23-02/.workbuddy/radeon_ssh/id_ed25519")
    parser.add_argument("--ssh-timeout", type=int, default=15)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = RunReport(target=args.target, apply=args.apply)
    result = ContextGraph(Executor(args), report).run(max(1, args.max_rounds))
    result.write(args.report)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.status in {"healthy", "fixed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
