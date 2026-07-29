#!/usr/bin/env python3
"""CLI demo covering RAG + memory + workflow + multi-agent routes."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.agent import PrivateAgent
from src.agent.multi_agent import MultiAgentOrchestrator
from src.agent.planner import build_task_plan
from src.agent.tools import ToolRegistry
from src.config import load_settings
from src.llm.backend import build_llm
from src.memory.memory import SessionMemory
from src.rag.store import VectorStore


def main() -> None:
    settings = load_settings()
    sample_dir = settings.resolve(settings.paths.sample_docs)
    upload_dir = settings.resolve(settings.paths.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    store = VectorStore(settings)
    if store.count() == 0:
        n = store.add_directory(sample_dir)
        print(f"[ingest] sample chunks = {n}")
    else:
        # refresh sample docs into KB if enterprise/dev docs were added
        n = store.add_directory(sample_dir)
        print(f"[ingest] upsert chunks = {n}")

    memory = SessionMemory(settings.resolve(settings.agent.memory_path))
    from src.skills import SkillRegistry

    skills = SkillRegistry(settings.resolve(settings.paths.generated_projects))
    tools = ToolRegistry(
        store=store,
        memory=memory,
        upload_dir=upload_dir,
        skill_registry=skills,
    )
    llm = build_llm(settings.llm)
    agent = PrivateAgent(llm=llm, tools=tools, memory=memory, max_steps=settings.agent.max_steps)
    orch = MultiAgentOrchestrator(agent, tools)

    questions = [
        "请假需要提前几天申请？",
        "列出可用开发技能",
        "帮我跑入职IT开通工作流",
        "如何确认 ROCm 可用？",
    ]
    if len(sys.argv) > 1:
        questions = [" ".join(sys.argv[1:])]

    for q in questions:
        print("\n" + "=" * 60)
        print("Q:", q)
        print("Plan:")
        for i, step in enumerate(build_task_plan(q), 1):
            print(f"  {i}. {step}")
        result = orch.run(q)
        print("Route:", getattr(result, "route", "?"))
        print("Specialist:", getattr(result, "specialist", "?"))
        print("Tools:", ", ".join(result.used_tools) or "(none)")
        print("A:", result.answer)

    print("\n[ok] multi-agent CLI demo finished.")


if __name__ == "__main__":
    main()
