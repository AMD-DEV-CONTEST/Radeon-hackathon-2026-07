from __future__ import annotations

import json
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from privateops.agent import PrivateOpsAgent


class LocalStabilityProvider:
    name = "software-stability-local"

    def complete(self, prompt, evidence, memory, execution_context=None):
        return "Local stability response grounded in the supplied execution context."


class VisibleFailingProvider:
    name = "software-stability-failure"

    def complete(self, prompt, evidence, memory, execution_context=None):
        raise OSError("simulated local model outage")


def run_stability_check(iterations: int = 10) -> dict[str, object]:
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        knowledge = root / "knowledge"
        knowledge.mkdir()
        (knowledge / "permission.md").write_text(
            "PrivateOps uses local evidence, read-only tools, explicit confirmation, and audit records.",
            encoding="utf-8",
        )
        (root / "README.md").write_text("PrivateOps stability fixture", encoding="utf-8")
        agent = PrivateOpsAgent(knowledge_dir=knowledge, state_dir=root / "state", workspace_dir=root)
        agent.provider = LocalStabilityProvider()
        latencies = []
        successful = 0
        for index in range(iterations):
            response = agent.ask(f"Review local workspace evidence for stability run {index + 1}.")
            if response.provider == LocalStabilityProvider.name and response.tool_results:
                successful += 1
            latencies.append(float(response.metrics["latency_ms"]))

        memory_response = agent.ask("Remember that permission evidence is the review priority.")
        memory_persisted = bool(memory_response.memory_updates) and bool(agent.memory().get("user_note"))

        agent.provider = VisibleFailingProvider()
        visible_failures = 0
        silent_fallbacks = 0
        try:
            agent.ask("Review evidence while the local model is unavailable.")
        except OSError:
            visible_failures += 1
        else:
            silent_fallbacks += 1

        audit_entries = len(agent.audit_trail(limit=iterations + 5))
        all_passed = (
            successful == iterations
            and visible_failures == 1
            and silent_fallbacks == 0
            and memory_persisted
            and audit_entries == iterations + 1
        )
        return {
            "software_only": True,
            "iterations": iterations,
            "successful_requests": successful,
            "provider_failures_visible": visible_failures,
            "silent_fallbacks": silent_fallbacks,
            "memory_persisted": memory_persisted,
            "audit_entries": audit_entries,
            "mean_software_workflow_latency_ms": round(statistics.mean(latencies), 3),
            "all_passed": all_passed,
            "hardware_claim": None,
        }


def main() -> None:
    result = run_stability_check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
