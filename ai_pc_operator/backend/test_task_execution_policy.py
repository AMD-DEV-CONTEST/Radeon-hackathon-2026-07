"""Task Planning & Execution Policy (10-phase spec) regression tests.

Covers:
  - Phase 3/4: per-node pipeline + model metadata on the execution graph
  - Phase 10: goal-level completion verification (verify_goal node)
  - Phase 6: user-visible status messages
  - Phase 2: WhatsApp compound flow (18-step graph with per-step metadata)
  - v1.0/v2.0 regressions preserved
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))


async def test_plan_to_graph_metadata():
    """Phase 3/4 + Phase 10: act nodes carry pipeline/models; verify_goal exists."""
    from app.agent.graph_schema import plan_to_graph, validate_node

    print("\nTesting execution-graph metadata...")
    nodes = plan_to_graph(
        {
            "intent": "open_app",
            "steps": [
                {"tool": "system.open_app", "args": {"name": "chrome"}},
                {"tool": "browser.open", "args": {"url": "https://youtube.com"}},
            ],
        },
        risk_level=1,
        goal="Open Chrome and YouTube",
    )

    # Observe + 2 act + verify_all + verify_goal + finish
    assert len(nodes) == 6

    act_nodes = [n for n in nodes if n["type"] == "act"]
    assert len(act_nodes) == 2
    assert act_nodes[0]["pipeline"] == "application"
    assert act_nodes[0]["models"]  # non-empty model list
    assert act_nodes[1]["pipeline"] == "browser"
    assert act_nodes[1]["models"] == ["browser_automation"]

    verify_goal = [n for n in nodes if n["id"] == "verify_goal"]
    assert verify_goal, "verify_goal node missing"
    assert verify_goal[0]["goal"] == "Open Chrome and YouTube"
    assert verify_goal[0]["verification"]["method"] == "goal_achieved"

    # Graph must still validate (approval auto-insertion works too)
    assert validate_node(nodes)["ok"] is True
    print("[ok] per-node pipeline/models + verify_goal")


async def test_goal_derivation():
    """Phase 10: goal string is human-readable."""
    from app.agent.router import AgentRouter

    print("\nTesting goal derivation...")
    derive = AgentRouter._derive_goal
    self_stub = object()
    assert derive(self_stub, "open chrome", "browser_open") == "open chrome"
    assert derive(self_stub, "send Desktop/1.txt to SHEISDANGER on WhatsApp",
                  "whatsapp_send_file") == (
        "send Desktop/1.txt to SHEISDANGER on WhatsApp"
    )
    assert derive(self_stub, "", "unknown") == "complete the request"
    long_text = "x " * 200
    assert len(derive(self_stub, long_text, "unknown")) <= 121
    print("[ok] goal derivation")


async def test_status_messages():
    """Phase 6: natural status lines per step."""
    from app.agent.router import AgentRouter

    print("\nTesting status messages...")
    step_status = AgentRouter._step_status
    # Stub with the class-level TOOL_STATUS_PHRASES attached (the method
    # reads self.TOOL_STATUS_PHRASES).
    class _Stub:
        TOOL_STATUS_PHRASES = AgentRouter.TOOL_STATUS_PHRASES

    self_stub = _Stub()
    assert step_status(self_stub, "system.open_app", {"name": "chrome"}) == "Opening chrome..."
    assert step_status(self_stub, "browser.open", {"url": "https://youtube.com"}) == "Opening https://youtube.com..."
    assert step_status(self_stub, "browser.search", {"query": "AMD ROCm"}) == "Searching for AMD ROCm..."
    assert step_status(self_stub, "screen.click_text", {"text": "Send"}) == "Clicking Send..."
    assert step_status(self_stub, "system.capture_photo", {}) == "Capturing photo..."
    # Unknown tool falls back to generic
    assert step_status(self_stub, "dev.git", {"action": "status"}) == "Running dev.git..."
    print("[ok] status messages")


async def test_send_file_plan():
    """Generic send-file compound flow (goal-oriented, entity-driven)."""
    from app.agent.task_planner import TaskPlanner

    print("\nTesting send-file compound plan...")
    planner = TaskPlanner()

    plan = planner.plan(
        "Go to File Explorer, open Desktop, locate 1.txt, open GX Browser, "
        "navigate to web.whatsapp.com, find the contact SHEISDANGER, "
        "and send the file"
    )
    assert plan is not None, "send-file plan not produced"
    assert plan.intent == "send_file"
    assert plan.risk_level == 2

    tools = [s["tool"] for s in plan.steps]
    assert "system.open_app" in tools
    assert "browser.open" in tools
    assert "screen.click_text" in tools
    assert any("whatsapp" in str(s["args"]).lower() for s in plan.steps)

    # Every step carries the per-phase metadata
    for s in plan.steps:
        for key in ("objective", "pipeline", "models", "verification", "recovery"):
            assert key in s, f"step missing {key}: {s.get('tool')}"
        assert s["pipeline"], f"step missing pipeline: {s.get('tool')}"
    print(f"[ok] send-file plan: {len(plan.steps)} steps with metadata")

    # The generic planner must NOT hijack non-send-file commands
    assert planner.plan("open chrome") is None
    assert planner.plan("send an email") is None


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

    # Existing cognitive plan still works with the new graph
    cognitive = await planner.create_cognitive_plan("Open Chrome")
    assert cognitive["intent"] == "browser_open"
    assert cognitive["execution_graph"]
    print("[ok] v1.0/v2.0 regressions preserved")


async def main():
    tests = [
        test_plan_to_graph_metadata,
        test_goal_derivation,
        test_status_messages,
        test_send_file_plan,
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
    print(f"All task-execution-policy tests passed! ({len(tests)}/{len(tests)})")


if __name__ == "__main__":
    asyncio.run(main())
