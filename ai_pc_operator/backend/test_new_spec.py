"""Tests for the new spec modules: skill registry, task graph, verification, memory."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault(
    "SCREEN_AI_DB_PATH",
    str(Path(tempfile.gettempdir()) / "screen_ai_test_new_spec.db"),
)

from app.db.database import init_db, close_db  # noqa: E402
from app.skills.contracts import (  # noqa: E402
    SkillDefinition,
    SkillInputSpec,
    SkillOutputSpec,
    SkillPermission,
    SkillStatus,
    SkillVerificationSpec,
)
from app.skills.registry import SkillRegistry  # noqa: E402
from app.skills.verification import VerificationEngine  # noqa: E402
from app.skills.runtime import SkillRuntime  # noqa: E402
from app.skills.mvp_pack import build_mvp_skills, seed_mvp_skills  # noqa: E402
from app.agent.task_graph import TaskGraphExecutor, NodeType, TaskStatus  # noqa: E402
from app.agent.memory_engine import MemoryEngine  # noqa: E402
from app.observability.tracer import Tracer  # noqa: E402


async def _run() -> int:
    await init_db()
    failures: list[str] = []

    # ------------------------------------------------------------------
    # Skill registry
    # ------------------------------------------------------------------
    registry = SkillRegistry()
    skill = SkillDefinition(
        id="test.echo",
        domain="meta",
        name="Echo test",
        description="Echo back the input.",
        handler="app.skills.handlers.meta_echo",
        risk_level=0,
        inputs=[SkillInputSpec(name="text", type="string", required=False, default="")],
        outputs=[SkillOutputSpec(name="echo", type="string")],
        permissions=[SkillPermission.FS_READ],
    )
    await registry.register(skill)
    fetched = await registry.get("test.echo")
    if fetched is None or fetched.handler != "app.skills.handlers.meta_echo":
        failures.append("registry.get failed")
    listed = await registry.list(domain="meta")
    if not any(s.id == "test.echo" for s in listed):
        failures.append("registry.list failed")
    metrics = await registry.metrics("test.echo")
    if metrics["skill_id"] != "test.echo":
        failures.append("registry.metrics failed")

    # ------------------------------------------------------------------
    # Verification engine
    # ------------------------------------------------------------------
    engine = VerificationEngine()
    v = await engine.verify(
        [
            SkillVerificationSpec(method="file_exists", config={"path": str(ROOT / "test_new_spec.py")}),
            SkillVerificationSpec(method="file_exists", config={"path": str(ROOT / "does_not_exist.xyz")}, required=False),
        ],
        {},
    )
    if not v["passed"]:
        failures.append(f"verification should pass: {v}")
    v2 = await engine.verify(
        [SkillVerificationSpec(method="file_exists", config={"path": "/no/such/path"})],
        {},
    )
    if v2["passed"]:
        failures.append("verification should fail for missing path")

    # ------------------------------------------------------------------
    # Skill runtime
    # ------------------------------------------------------------------
    runtime = SkillRuntime(registry, engine)
    result = await runtime.execute("test.echo", {"text": "hello"})
    if result.status != SkillStatus.SUCCESS:
        failures.append(f"runtime.execute failed: {result.error}")
    if result.outputs.get("echo") != "hello":
        failures.append(f"runtime.execute wrong output: {result.outputs}")

    # ------------------------------------------------------------------
    # MVP pack
    # ------------------------------------------------------------------
    mvp = build_mvp_skills()
    if len(mvp) != 50:
        failures.append(f"MVP pack should have 50 skills, got {len(mvp)}")
    domains = {s.domain for s in mvp}
    expected_domains = {"files", "os", "browser", "app", "meta"}
    if not expected_domains.issubset(domains):
        failures.append(f"MVP pack missing domains: {expected_domains - domains}")

    # Seed into a fresh registry
    registry2 = SkillRegistry()
    registry2.invalidate_cache()
    seeded = await seed_mvp_skills(registry2)
    if seeded != 50:
        failures.append(f"seed_mvp_skills should seed 50, got {seeded}")
    all_skills = await registry2.list(enabled_only=False)
    if len(all_skills) != 50:
        failures.append(f"after seed, registry should have 50, got {len(all_skills)}")

    # ------------------------------------------------------------------
    # Task graph
    # ------------------------------------------------------------------
    executor = TaskGraphExecutor(registry2, engine)
    task = await executor.create_task(
        "echo-twice",
        [
            {
                "id": "n1",
                "node_type": "act",
                "skill_id": "meta.echo",
                "inputs": {"text": "first"},
            },
            {
                "id": "n2",
                "node_type": "act",
                "skill_id": "meta.echo",
                "depends_on": ["n1"],
                "inputs": {"text": "second"},
            },
        ],
    )
    ctx = {"skill_runtime": runtime}
    task = await executor.run(task, ctx)
    if task.status != TaskStatus.COMPLETED:
        failures.append(f"task should complete: {task.status} {task.error}")
    if task.nodes[0].outputs.get("echo") != "first":
        failures.append("node n1 wrong output")
    if task.nodes[1].outputs.get("echo") != "second":
        failures.append("node n2 wrong output")

    # ------------------------------------------------------------------
    # Memory engine
    # ------------------------------------------------------------------
    mem = MemoryEngine()
    await mem.remember("fact", "user_name", "Alice")
    entry = await mem.recall("fact", "user_name")
    if entry is None or entry["value"] != "Alice":
        failures.append("memory.remember/recall failed")
    await mem.save_template(
        "tpl-echo",
        "Echo template",
        [{"node_type": "act", "skill_id": "meta.echo", "inputs": {"text": "hi"}}],
        trigger_text="say hi",
    )
    matched = await mem.match_template("please say hi to everyone")
    if matched is None or matched["id"] != "tpl-echo":
        failures.append("memory.match_template failed")

    # ------------------------------------------------------------------
    # Tracer
    # ------------------------------------------------------------------
    tracer = Tracer()
    eid = await tracer.event("plan", task_id=task.id, payload={"x": 1})
    if eid <= 0:
        failures.append("tracer.event failed")
    trace = await tracer.trace_task(task.id)
    if trace["event_count"] < 1:
        failures.append("tracer.trace_task returned no events")

    await close_db()
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All new-spec tests passed.")
    return 0


def test_new_spec_modules():
    """Pytest entry point for the new spec integration checks."""
    assert asyncio.run(_run()) == 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
