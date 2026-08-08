"""Generic Compound-Command Planner regression tests.

Covers:
  - Splitting chained commands into action segments (URLs/filenames/app
    names preserved)
  - The spec example: Explorer -> Desktop -> find x.file -> GX Browser ->
    web.whatsapp.com -> attach -> send -> verify
  - Generality: any chained command decomposes (common fix, not app-specific)
  - Single-intent commands are NOT hijacked
  - Named compound patterns (research_collect, send_file) still win
  - v1.0/v2.0 regressions preserved
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))


async def test_split_segments():
    """Splitting preserves URLs, filenames, and multi-word app names."""
    from app.agent.task_planner import TaskPlanner

    print("\nTesting compound split...")
    p = TaskPlanner()

    segments = p._split_compound(
        "Go to File Explorer, open Desktop, find x.file, open GX Browser, "
        "navigate to https://web.whatsapp.com search for the contact, "
        "attach the file and send it"
    )
    assert len(segments) >= 6, f"expected >=6 segments, got {len(segments)}"
    assert any("File Explorer" in s for s in segments), "File Explorer split!"
    assert any("web.whatsapp.com" in s for s in segments), "URL split!"
    assert any("x.file" in s for s in segments), "filename split!"

    # Multi-word app protected
    segments = p._split_compound("open Visual Studio Code, then search git")
    assert any("Visual Studio Code" in s for s in segments), "VS Code split!"
    print("[ok] split preserves URLs/filenames/app names")


async def test_example_command():
    """The full spec example decomposes into one chained plan."""
    from app.agent.task_planner import TaskPlanner

    print("\nTesting example command...")
    p = TaskPlanner()
    plan = p.plan(
        "Go to File Explorer, open Desktop, find x.file, open GX Browser, "
        "navigate to https://web.whatsapp.com search for the contact, "
        "attach the file and send it"
    )
    assert plan is not None
    assert plan.intent == "compound_sequence"

    tools = [s["tool"] for s in plan.steps]
    # All key actions present
    assert "system.open_app" in tools
    assert "file.search" in tools
    assert "browser.open" in tools
    assert tools.count("screen.click_text") >= 2  # attach + send
    assert any("https://web.whatsapp.com" in str(s.get("args", {}))
               for s in plan.steps)

    # Every step carries per-phase metadata
    for s in plan.steps:
        for key in ("objective", "pipeline", "models", "verification",
                    "recovery", "risk"):
            assert key in s, f"step missing {key}: {s.get('tool')}"
        assert s["pipeline"]
    print(f"[ok] example command: {len(plan.steps)} steps")


async def test_generic_not_specific():
    """Any chained command decomposes — the fix is common, not app-specific."""
    from app.agent.task_planner import TaskPlanner

    print("\nTesting generic compound commands...")
    p = TaskPlanner()

    plan = p.plan("open Chrome, then search AMD ROCm, then screenshot")
    assert plan is not None and plan.intent == "compound_sequence"
    tools = [s["tool"] for s in plan.steps]
    assert "system.open_app" in tools
    assert "browser.search" in tools
    assert "media.screenshot" in tools

    plan = p.plan("open Notepad, then type hello, then save the file")
    assert plan is not None and plan.intent == "compound_sequence"
    print("[ok] generic compound commands")


async def test_single_intent_not_split():
    """A single-action command is NOT treated as compound."""
    from app.agent.task_planner import TaskPlanner

    print("\nTesting single-intent guard...")
    p = TaskPlanner()
    assert p.plan("open chrome") is None
    assert p.plan("take a screenshot") is None
    assert p.plan("open youtube") is None
    print("[ok] single-intent not hijacked")


async def test_named_patterns_win():
    """research_collect / send_file still win over the generic split."""
    from app.agent.task_planner import TaskPlanner

    print("\nTesting named-pattern priority...")
    p = TaskPlanner()

    research = p.plan(
        "open chrome and search about AMD ROCm and go to 10 random websites "
        "and copy all text and save it"
    )
    assert research is not None and research.intent == "research_collect"

    send = p.plan("send report.pdf to Alice on whatsapp")
    assert send is not None and send.intent == "send_file"
    print("[ok] named patterns win")


async def test_v1_v2_regressions():
    """v1.0/v2.0 behavior preserved."""
    from app.agent.planner import Planner, semantic_ocr_match

    print("\nTesting v1.0/v2.0 regressions...")
    planner = Planner()

    assert await planner.classify_intent("Open Chrome") == "browser_open"
    assert await planner.classify_intent("open YouTube") == "open_website"
    assert await planner.classify_intent("close browser") == "browser_close"
    assert await planner.classify_intent("take my picture") == "take_camera_photo"
    assert semantic_ocr_match("login", "sign in") >= 0.9

    # Sync twins agree with async
    assert planner.classify_intent_sync("open chrome") == "browser_open"
    plan = planner.create_plan_sync("open chrome", "browser_open")
    assert plan["steps"][0]["tool"] == "system.open_app"
    print("[ok] v1.0/v2.0 regressions preserved")


async def main():
    tests = [
        test_split_segments,
        test_example_command,
        test_generic_not_specific,
        test_single_intent_not_split,
        test_named_patterns_win,
        test_v1_v2_regressions,
    ]
    failures = []
    for test in tests:
        try:
            await test()
        except Exception as e:
            failures.append((test.__name__, e))
            print(f"[fail] {test.__name__}: {e}")
    print()
    if failures:
        print(f"FAILED: {len(failures)} / {len(tests)}")
        for name, e in failures:
            print(f"  - {name}: {e}")
        sys.exit(1)
    print(f"All compound-sequence tests passed! ({len(tests)}/{len(tests)})")


if __name__ == "__main__":
    asyncio.run(main())
