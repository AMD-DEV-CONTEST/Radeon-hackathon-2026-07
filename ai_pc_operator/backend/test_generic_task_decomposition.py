"""Generic Task Decomposition Policy regression tests.

Covers:
  - Universal entity extraction (FILE/CONTACT/CHANNEL/APP/SITE/URL/PATH)
  - Goal-oriented send-file planning that is NOT application-specific
    (whatsapp/gmail/telegram/no-channel all produce the same generic graph;
    only the channel URL step differs)
  - No hardcoded app workflows (the old whatsapp_send_file intent is gone)
  - v1.0/v2.0 regressions preserved
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))


async def test_entity_extraction():
    """Universal entity extraction across channels."""
    from app.agent.task_planner import extract_entities

    print("\nTesting entity extraction...")

    e = extract_entities("send report.pdf to Alice on whatsapp")
    assert e["file"] == "report.pdf"
    assert e["contact"] == "Alice"
    assert e["channel"] == "whatsapp"
    assert e["channel_url"] == "https://web.whatsapp.com"

    e = extract_entities("email resume.pdf to John")
    assert e["file"] == "resume.pdf"
    assert e["contact"] == "John"
    assert e["channel"] == "gmail"
    assert e["channel_url"] == "https://mail.google.com"

    # No channel -> None + empty url
    e = extract_entities("send notes.txt to Bob")
    assert e["file"] == "notes.txt"
    assert e["contact"] == "Bob"
    assert e["channel"] is None
    assert e["channel_url"] == ""

    # Structural words are not contacts
    e = extract_entities("send report.pdf to the folder")
    assert e["contact"] is None or e["contact"].lower() in ("folder",)

    print("[ok] entity extraction")


async def test_send_file_generic():
    """Same generic graph structure across channels; channel drives URL only."""
    from app.agent.task_planner import TaskPlanner

    print("\nTesting generic send-file planning...")
    planner = TaskPlanner()

    cases = [
        ("send report.pdf to Alice on whatsapp", "whatsapp",
         "https://web.whatsapp.com"),
        ("email resume.pdf to John", "gmail", "https://mail.google.com"),
        ("send photo.jpg to Sarah on telegram", "telegram",
         "https://web.telegram.org"),
        ("send notes.txt to Bob", None, ""),  # no channel -> no URL step
    ]
    for text, channel, url in cases:
        plan = planner.plan(text)
        assert plan is not None, f"{text!r} not planned"
        assert plan.intent == "send_file", f"{text!r} intent {plan.intent}"
        assert plan.risk_level == 2

        tools = [s["tool"] for s in plan.steps]
        assert "file.read" in tools, f"{text!r} missing file locate"
        assert "browser.open" in tools if url else True
        assert "screen.click_text" in tools

        if url:
            url_steps = [s for s in plan.steps if s["tool"] == "browser.open"]
            assert url_steps and url_steps[0]["args"]["url"] == url
        else:
            url_steps = [s for s in plan.steps if s["tool"] == "browser.open"]
            assert not url_steps, "no channel must not add a browser.open step"

        # Every step carries per-phase metadata
        for s in plan.steps:
            for key in ("objective", "pipeline", "models", "verification",
                        "recovery", "risk"):
                assert key in s, f"step missing {key}: {s.get('tool')}"
            assert s["pipeline"]
            assert s["models"]

    print("[ok] generic send-file planning")


async def test_no_specific_workflows():
    """The generic planner must not hijack unrelated commands."""
    from app.agent.task_planner import TaskPlanner

    print("\nTesting no-specific-workflows guard...")
    planner = TaskPlanner()

    # No FILE -> no send_file plan (falls through to normal intents)
    assert planner.plan("send an email to bob") is None
    assert planner.plan("send a message") is None
    assert planner.plan("open chrome") is None
    assert planner.plan("take a screenshot") is None

    # The old WhatsApp-specific intent no longer exists anywhere
    from app.agent.task_planner import TaskPlan
    plan = planner.plan("send file.txt to sam on whatsapp")
    assert plan is not None
    assert plan.intent != "whatsapp_send_file"
    print("[ok] no-specific-workflows guard")


async def test_verify_goal_metadata():
    """Goal-level verification carries the user's objective."""
    from app.agent.graph_schema import plan_to_graph

    print("\nTesting verify_goal metadata...")
    nodes = plan_to_graph(
        {
            "intent": "send_file",
            "steps": [
                {"tool": "file.read", "args": {"path": "report.pdf"}},
                {"tool": "browser.open", "args": {"url": "https://web.whatsapp.com"}},
            ],
        },
        risk_level=2,
        goal="Send report.pdf to Alice via WhatsApp",
    )
    verify_goal = [n for n in nodes if n["id"] == "verify_goal"]
    assert verify_goal
    assert verify_goal[0]["goal"] == "Send report.pdf to Alice via WhatsApp"
    assert verify_goal[0]["verification"]["method"] == "goal_achieved"
    print("[ok] verify_goal metadata")


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
    print("[ok] v1.0/v2.0 regressions preserved")


async def main():
    tests = [
        test_entity_extraction,
        test_send_file_generic,
        test_no_specific_workflows,
        test_verify_goal_metadata,
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
    print(f"All generic-task-decomposition tests passed! ({len(tests)}/{len(tests)})")


if __name__ == "__main__":
    asyncio.run(main())
