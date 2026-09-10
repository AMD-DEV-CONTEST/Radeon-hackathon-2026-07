"""Orchestrates deterministic tools, local RAG, memory, and the multi-agent layer.

Two modes:
- demo: fully local, labelled synthetic; runs without Pi or Radeon inference.
- pi:   delegates specialist generation to the localhost Pi bridge backed by a
        local ROCm model endpoint. Fails closed; never silently substitutes demo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from . import tools
from .memory import OpsMemory
from .models import AgentReport
from .pi_bridge import PiBridgeClient, PiBridgeError
from .rag import LocalRAG

AGENT_ROLES = [
    ("envdoctor", "Environment Doctor"),
    ("deployplanner", "Deployment Planner"),
    ("benchmarkrunner", "Benchmark Interpreter"),
    ("optimanalyst", "Optimization Analyst"),
]


@dataclass
class OpsRun:
    session_id: str
    mode: str
    environment: dict[str, Any] = field(default_factory=dict)
    telemetry: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    reports: list[AgentReport] = field(default_factory=list)
    summary: str = ""
    action_plan: list[dict[str, Any]] = field(default_factory=list)
    runtime: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "environment": self.environment,
            "telemetry": self.telemetry,
            "evidence": self.evidence,
            "reports": [report.to_dict() for report in self.reports],
            "summary": self.summary,
            "action_plan": self.action_plan,
            "runtime": self.runtime,
            "error": self.error,
        }


class OpsOrchestrator:
    def __init__(self, knowledge_path: str = "data/knowledge", db_path: str = "runtime/radeonpilot.sqlite3") -> None:
        self.rag = LocalRAG(knowledge_path)
        self.memory = OpsMemory(db_path)
        self.mode = tools.detect_mode()

    def gather_environment(self) -> dict[str, Any]:
        env = tools.gpu_environment()
        endpoint = tools.endpoint_status()
        return {"gpu_environment": env.data, "endpoint": endpoint.data, "errors": [env.error] if env.error else []}

    def run(self, user_message: str, role: str = "operator", session_id: str | None = None) -> OpsRun:
        session_id = session_id or uuid.uuid4().hex[:12]
        run = OpsRun(session_id=session_id, mode=self.mode)
        turn = self.memory.next_turn(session_id)
        self.memory.add_turn(session_id, turn, "user", user_message)

        run.environment = self.gather_environment()
        query = user_message or "diagnose and optimize the Radeon inference endpoint"
        evidence = self.rag.search(query, limit=4)
        run.evidence = [item.to_dict() for item in evidence]
        run.telemetry = {"mode": self.mode, "endpoint_reachable": run.environment["endpoint"].get("reachable", False)}

        self.memory.snapshot(session_id, "environment", run.environment)
        self.memory.audit(session_id, "ops_run_started", f"mode={self.mode}")

        if self.mode == "pi":
            self._run_pi(run, user_message, role)
        else:
            self._run_demo(run, user_message)

        self.memory.add_turn(session_id, turn, "assistant", run.summary or "(no summary)")
        self.memory.snapshot(session_id, "action_plan", {"action_plan": run.action_plan})
        return run

    def _run_demo(self, run: OpsRun, user_message: str) -> None:
        for key, title in AGENT_ROLES:
            run.reports.append(
                AgentReport(
                    key=key,
                    role=title,
                    ok=True,
                    text=f"[demo] {title} placeholder analysis",
                    duration_ms=0,
                    parsed={"role": title, "findings": [f"Deterministic {title} pass (demo mode)."], "confidence": "n/a"},
                )
            )
        run.summary = (
            "DEMO MODE: synthetic multi-agent pass. Connect the Pi bridge and a local ROCm "
            "endpoint for real Radeon inference. Request: " + (user_message or "(empty)")
        )
        run.action_plan = [
            {
                "step_id": "demo-1",
                "owner": "operator",
                "description": "Start the model endpoint and Pi bridge, then re-run in pi mode.",
                "dangerous": False,
                "required_role": "operator",
                "status": "proposed",
                "rationale": "Demo mode performs no real GPU work.",
            }
        ]
        run.runtime = {"radeon_attested": False, "mode": "demo", "note": "GPU UNATTESTED (demo)"}

    def _run_pi(self, run: OpsRun, user_message: str, role: str) -> None:
        client = PiBridgeClient()
        try:
            health = client.health()
            run.runtime = health.get("runtime", {})
        except PiBridgeError as exc:
            run.error = f"Pi bridge health check failed: {exc}"
            run.summary = "FAILED CLOSED: Pi bridge is unreachable. No demo fallback is substituted."
            self.memory.audit(run.session_id, "pi_bridge_unreachable", str(exc))
            return

        payload = {
            "session_id": run.session_id,
            "environment": run.environment,
            "telemetry": run.telemetry,
            "evidence": run.evidence,
            "memory": self.memory.history(run.session_id)[-6:],
            "user_message": user_message,
            "role": role,
        }
        try:
            result = client.run_agents(payload)
        except PiBridgeError as exc:
            run.error = f"Pi orchestration failed: {exc}"
            run.summary = "FAILED CLOSED: multi-agent orchestration error. No demo fallback is substituted."
            self.memory.audit(run.session_id, "pi_orchestration_failed", str(exc))
            return

        for agent in result.get("agents", []):
            run.reports.append(
                AgentReport(
                    key=agent.get("key", "?"),
                    role=agent.get("role", "?"),
                    ok=bool(agent.get("ok")),
                    text=agent.get("text", ""),
                    duration_ms=int(agent.get("duration_ms", 0)),
                    parsed=agent.get("parsed"),
                    error=(agent.get("error") or {}).get("message"),
                )
            )
        run.summary = result.get("summary", "")
        run.action_plan = result.get("action_plan", [])
        run.runtime = result.get("runtime", run.runtime)
        self.memory.audit(run.session_id, "pi_orchestration_ok", f"agents={len(run.reports)}")
