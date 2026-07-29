#!/usr/bin/env python3
"""Canonical judge demo — identical prompts to START_HERE.md / video / Web UI."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.agent import PrivateAgent
from src.agent.multi_agent import MultiAgentOrchestrator
from src.agent.tools import ToolRegistry
from src.apps.judge_script import JUDGE_SEQUENCE, PR_URL, VIDEO_URL, ensure_judge_ocr_image
from src.apps.modes import list_app_modes
from src.config import load_settings
from src.llm.backend import build_llm
from src.memory.memory import SessionMemory
from src.privacy.audit import AuditTrail
from src.rag.store import VectorStore
from src.skills import SkillRegistry


def _run(orch: MultiAgentOrchestrator, mode: str, q: str) -> None:
    print("\n" + "=" * 64)
    print(f"APP_MODE={mode}")
    print("Q:", q)
    r = orch.run(q, mode=mode)
    print("Specialist:", getattr(r, "specialist", "?"))
    print("Route:", getattr(r, "route", "?"))
    plan = getattr(r, "plan", None) or []
    if plan:
        print("Plan:", " -> ".join(plan))
    print("Tools:", ", ".join((r.used_tools or [])[:8]) or "(none)")
    print("A:", (r.answer or "")[:1200])


def main() -> None:
    print("=== PrivateLocalAgent · Judge Demo ===")
    print("Matches: START_HERE.md · docs/JUDGE_DEMO.md · Demo video · Web 推荐问题")
    print("Video:", VIDEO_URL)
    print("PR:", PR_URL)
    print(list_app_modes())

    settings = load_settings()
    store = VectorStore(settings)
    n = store.add_directory(settings.resolve(settings.paths.sample_docs))
    print(f"[ingest] upsert={n} total={store.count()}")

    upload_dir = settings.resolve(settings.paths.upload_dir)
    sample_img = ensure_judge_ocr_image(upload_dir)
    print(f"[vision] sample image = {sample_img.name}")

    memory = SessionMemory(settings.resolve(settings.agent.memory_path))
    skills = SkillRegistry(settings.resolve(settings.paths.generated_projects))
    tools = ToolRegistry(store, memory, upload_dir, skill_registry=skills)
    audit = AuditTrail(settings.resolve("data/memory/audit.jsonl"))
    llm = build_llm(settings.llm)
    agent = PrivateAgent(llm, tools, memory, settings.agent.max_steps, audit=audit)
    orch = MultiAgentOrchestrator(agent, tools)

    sequence = list(JUDGE_SEQUENCE)
    if len(sys.argv) > 2:
        sequence = [(sys.argv[1], " ".join(sys.argv[2:]))]

    for mode, q in sequence:
        _run(orch, mode, q)

    print("\n[ok] judge demo finished — all modes exercised")
    print("Web (same prompts): PLA_ALLOW_PUBLIC=1 python scripts/run_cloudflare_tunnel.py")
    print("Guide: START_HERE.md")


if __name__ == "__main__":
    main()
