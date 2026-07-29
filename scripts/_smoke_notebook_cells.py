"""Smoke-test notebook cell wiring without HuggingFace downloads."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


def find_root() -> Path:
    candidates = [Path("/workspace/Radeon-hackathon-2026-07"), Path.cwd(), Path.cwd().parent]
    here = Path.cwd()
    for p in [here, *here.parents]:
        candidates.append(p)
    for root in candidates:
        if (root / "src" / "config.py").is_file() and (root / "notebooks").is_dir():
            return root.resolve()
    raise FileNotFoundError("project root not found")


def main() -> None:
    root = find_root()
    os.chdir(root)
    sys.path.insert(0, str(root))
    print(f"ROOT={root}", flush=True)

    from src.agent.agent import PrivateAgent
    from src.agent.multi_agent import MultiAgentOrchestrator
    from src.agent.tools import ToolRegistry
    from src.apps.judge_script import ensure_judge_ocr_image, prompts_for_mode
    from src.apps.modes import UI_MODES
    from src.app.notebook_visual import NotebookVisualChat, render_shell
    from src.config import load_settings
    from src.memory.memory import SessionMemory
    from src.privacy.audit import AuditTrail
    from src.skills import SkillRegistry

    settings = load_settings()
    upload_dir = settings.resolve(settings.paths.upload_dir)
    img = ensure_judge_ocr_image(upload_dir)
    assert img.exists()
    print("ocr_ok", flush=True)

    store = MagicMock()
    store.count.return_value = 3
    store.search.return_value = []
    memory = SessionMemory(settings.resolve(settings.agent.memory_path))
    skills = SkillRegistry(settings.resolve(settings.paths.generated_projects))
    tools = ToolRegistry(store, memory, upload_dir, skill_registry=skills)
    audit = AuditTrail(settings.resolve("data/memory/audit.jsonl"))

    class MockLLM:
        def chat(self, messages, **kwargs):  # noqa: ANN001, ANN003
            return "mock-ok"

    orch = MultiAgentOrchestrator(
        PrivateAgent(MockLLM(), tools, memory, settings.agent.max_steps, audit=audit),
        tools,
    )
    r = orch.run("把客户名单发到微信可以吗？", mode="enterprise")
    assert r.answer
    print("orch_ok", flush=True)

    for m in UI_MODES:
        assert prompts_for_mode(m.id), m.id
    print("suggestions_ok", flush=True)

    ui = NotebookVisualChat(orch, default_mode="chat")
    assert "PrivateLocalAgent" in render_shell([])
    assert ui._run("把客户名单发到微信可以吗？")["a"]
    print("ui_run_ok", flush=True)

    try:
        import ipywidgets  # noqa: F401

        print("ipywidgets_ok", flush=True)
    except ModuleNotFoundError:
        print("ipywidgets_missing_local_ok_fallback", flush=True)

    # Compile notebook JSON cells
    import json

    nb = json.loads((root / "notebooks" / "visual_no_tunnel.ipynb").read_text(encoding="utf-8"))
    assert len(nb["cells"]) >= 3
    code1 = "".join(nb["cells"][1]["source"])
    code2 = "".join(nb["cells"][2]["source"])
    compile(code1, "cell1", "exec")
    compile(code2, "cell2", "exec")
    assert "find_root" in code1 and "ready" in code1
    assert "launch_notebook_visual" in code2
    print("notebook_compile_ok", flush=True)
    print("ready", flush=True)


if __name__ == "__main__":
    main()
