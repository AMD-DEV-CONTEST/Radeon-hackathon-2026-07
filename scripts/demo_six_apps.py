#!/usr/bin/env python3
"""Demo all six Track-2 application modes (practical + ROCm-ready)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.agent import PrivateAgent
from src.agent.multi_agent import MultiAgentOrchestrator
from src.agent.tools import ToolRegistry
from src.apps import APP_MODES, list_app_modes
from src.config import load_settings
from src.llm.backend import build_llm
from src.memory.memory import SessionMemory
from src.privacy.audit import AuditTrail
from src.rag.store import VectorStore
from src.skills import SkillRegistry


def main() -> None:
    print(list_app_modes())
    settings = load_settings()
    store = VectorStore(settings)
    n = store.add_directory(settings.resolve(settings.paths.sample_docs))
    print(f"[ingest] upsert={n} total={store.count()}")

    memory = SessionMemory(settings.resolve(settings.agent.memory_path))
    skills = SkillRegistry(settings.resolve(settings.paths.generated_projects))
    tools = ToolRegistry(
        store,
        memory,
        settings.resolve(settings.paths.upload_dir),
        skill_registry=skills,
    )
    audit = AuditTrail(settings.resolve("data/memory/audit.jsonl"))
    llm = build_llm(settings.llm)
    agent = PrivateAgent(
        llm,
        tools,
        memory,
        max_steps=settings.agent.max_steps,
        audit=audit,
    )
    orch = MultiAgentOrchestrator(agent, tools)

    # One prompt per mode (override via argv)
    if len(sys.argv) > 2:
        mode, q = sys.argv[1], " ".join(sys.argv[2:])
        modes = [(mode, q)]
    else:
        modes = [(m.id, m.demo_prompts[0]) for m in APP_MODES]

    for mode, q in modes:
        print("\n" + "=" * 64)
        print(f"APP_MODE={mode}")
        print("Q:", q)
        r = orch.run(q, mode=mode)
        print("Specialist:", r.specialist)
        print("Route:", r.route)
        print("Plan:", " -> ".join(r.plan))
        print("Tools:", ", ".join(r.used_tools[:8]))
        print("A:", r.answer[:1200])

    print("\n[ok] six-app demo finished")


if __name__ == "__main__":
    main()
