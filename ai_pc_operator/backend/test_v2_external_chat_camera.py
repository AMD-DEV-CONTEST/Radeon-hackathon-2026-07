"""Screen-AI OS v2.0 regression tests: external reasoning, camera, chat mode.

Covers the v2.0 spec:
  - ExternalPlanner: env-var config, no-key short-circuit, plan/chat parsing
  - Camera policy: take_camera_photo intent, media_camera fix, capture tool
  - Chat mode: local rule-based replies fall through when no rules match
  - v1.0 regressions preserved
"""

import asyncio
import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))


async def test_external_planner_config():
    """Env-var config with sane defaults; no key => not configured."""
    from app.agent.external_planner import ExternalPlanner

    print("\nTesting external planner config...")
    old_key = os.environ.get("SCREEN_AI_EXTERNAL_API_KEY")
    if "SCREEN_AI_EXTERNAL_API_KEY" in os.environ:
        del os.environ["SCREEN_AI_EXTERNAL_API_KEY"]

    p = ExternalPlanner()
    assert p.is_configured() is False
    assert p._base_url() == "https://developer.amd.com.cn/radeon/api/v1"
    assert p._model() == "DeepSeek-V4-Flash"
    assert p._timeout() == 30
    assert p._max_retries() == 1

    os.environ["SCREEN_AI_EXTERNAL_API_KEY"] = "rc-test-key"
    assert p.is_configured() is True

    os.environ["SCREEN_AI_EXTERNAL_BASE_URL"] = "https://example.com/v1"
    os.environ["SCREEN_AI_EXTERNAL_MODEL"] = "Test-Model"
    assert p._base_url() == "https://example.com/v1"
    assert p._model() == "Test-Model"

    # Restore
    if old_key is None:
        os.environ.pop("SCREEN_AI_EXTERNAL_API_KEY", None)
    else:
        os.environ["SCREEN_AI_EXTERNAL_API_KEY"] = old_key
    os.environ.pop("SCREEN_AI_EXTERNAL_BASE_URL", None)
    os.environ.pop("SCREEN_AI_EXTERNAL_MODEL", None)
    print("[ok] external planner config")


async def test_external_planner_no_key():
    """With no key, create_plan/chat_reply return None without network."""
    from app.agent.external_planner import ExternalPlanner

    print("\nTesting external planner no-key short-circuit...")
    old_key = os.environ.get("SCREEN_AI_EXTERNAL_API_KEY")
    if "SCREEN_AI_EXTERNAL_API_KEY" in os.environ:
        del os.environ["SCREEN_AI_EXTERNAL_API_KEY"]

    p = ExternalPlanner()
    assert await p.create_plan("open chrome") is None
    assert await p.chat_reply("hello") is None

    if old_key is None:
        os.environ.pop("SCREEN_AI_EXTERNAL_API_KEY", None)
    else:
        os.environ["SCREEN_AI_EXTERNAL_API_KEY"] = old_key
    print("[ok] no-key short-circuit")


async def test_external_planner_parse():
    """Plan/chat parsing and step validation."""
    from app.agent.external_planner import ExternalPlanner

    print("\nTesting external planner parsing...")
    p = ExternalPlanner()

    # Plan JSON extraction
    plan = p._parse_json('{"intent":"open_website","risk_level":1,"plan":[{"tool":"browser.open","args":{"url":"https://x.com"}}]}')
    assert plan is not None
    assert plan["intent"] == "open_website"

    # Fenced/embedded JSON
    plan2 = p._parse_json('Here is the plan: ```json\n{"intent":"search_web","steps":[{"tool":"browser.search","args":{"query":"test"}}]}\n```')
    assert plan2 is not None
    assert plan2["intent"] == "search_web"

    # Step validation: allowed tools pass, unknown tools rejected
    steps = p._validate_steps([{"tool": "system.open_app", "args": {"name": "chrome"}}])
    assert steps is not None
    steps = p._validate_steps([{"tool": "evil.delete_everything", "args": {}}])
    assert steps is None
    # Missing args defaults to {} (matches executor's step.get("args", {}))
    steps = p._validate_steps([{"tool": "system.open_app"}])
    assert steps == [{"tool": "system.open_app", "args": {}}]

    # Risk clamp
    assert p._clamp_risk(9) == 5
    assert p._clamp_risk("abc") == 1
    assert p._clamp_risk(3) == 3

    # Text extraction from a chat response
    chat = p._extract_text({"choices": [{"message": {"content": "Hello there"}}]})
    assert chat == "Hello there"
    print("[ok] external planner parsing")


async def test_camera_intents():
    """Camera policy: open camera vs take a photo classify and plan correctly."""
    from app.agent.planner import Planner

    print("\nTesting camera intents...")
    planner = Planner()

    # Open camera -> media_camera
    intent = await planner.classify_intent("open camera")
    assert intent == "media_camera", f"open camera -> {intent}"
    plan = await planner.create_plan("open camera", intent)
    assert plan["steps"][0]["tool"] == "system.open_app"
    assert plan["steps"][0]["args"]["name"] == "camera"
    print("[ok] open camera -> system.open_app (dangling media.camera fixed)")

    # Take a picture -> take_camera_photo
    for cmd in ["take my picture", "take a photo", "capture a selfie",
                "use webcam", "take a picture of me", "click a photo"]:
        intent = await planner.classify_intent(cmd)
        assert intent == "take_camera_photo", f"'{cmd}' -> {intent}"
        plan = await planner.create_plan(cmd, intent)
        tools = [s["tool"] for s in plan["steps"]]
        assert tools == ["system.open_app", "system.capture_photo"], tools
    print("[ok] take_camera_photo -> launch + capture graph")

    # Risk + metadata
    from app.agent.planner import compute_risk, get_required_models, get_verification_steps
    assert compute_risk("take_camera_photo") == 1
    assert "camera" in get_required_models("take_camera_photo")
    assert "verify_photo_saved" in get_verification_steps("take_camera_photo")


async def test_capture_photo_missing_tool():
    """Capture gracefully fails with a clear message when no ffmpeg backend."""
    from app.tools.system_tools import SystemTools

    print("\nTesting capture_photo graceful failure...")
    tools = SystemTools()
    # Force the no-ffmpeg path by monkeypatching which() to return None
    import shutil
    original_which = shutil.which
    try:
        shutil.which = lambda name: None  # type: ignore[assignment]
        result = tools._capture_photo_sync()
    finally:
        shutil.which = original_which

    assert result["status"] == "failed"
    assert "ffmpeg" in result["error"].lower()
    assert "hint" in result
    print("[ok] graceful failure with clear message")


async def test_chat_rules():
    """Local rule-based chat replies; non-chat falls through to None."""
    from app.agent.router import AgentRouter

    print("\nTesting chat rules...")
    # Call the unbound method with a minimal self (no router construction).
    rule = AgentRouter._rule_chat_reply
    self_stub = object()

    assert rule(self_stub, "hello") is not None
    assert rule(self_stub, "Hello there!") is not None
    assert rule(self_stub, "who are you?") is not None
    assert rule(self_stub, "what can you do?") is not None
    assert rule(self_stub, "thanks a lot") is not None
    assert rule(self_stub, "run a marathon on saturday") is None
    assert rule(self_stub, "") is None
    print("[ok] chat rules")


async def test_v2_regressions():
    """v1.0 behavior preserved."""
    from app.agent.planner import Planner, semantic_ocr_match

    print("\nTesting v1.0 regressions preserved...")
    planner = Planner()

    intent = await planner.classify_intent("Open Chrome")
    assert intent == "browser_open"

    intent = await planner.classify_intent("open YouTube")
    assert intent == "open_website"

    intent = await planner.classify_intent("close browser")
    assert intent == "browser_close"

    assert semantic_ocr_match("login", "sign in") >= 0.9
    assert semantic_ocr_match("continue", "next") >= 0.9

    # The 132-case smoke's only pre-existing failure (docker build) stays unknown,
    # but must still produce a non-crashing path.
    intent = await planner.classify_intent("docker build")
    assert intent == "unknown" or intent in ("dev_build", "dev_docker")
    print("[ok] v1.0 regressions preserved")


async def main():
    tests = [
        test_external_planner_config,
        test_external_planner_no_key,
        test_external_planner_parse,
        test_camera_intents,
        test_capture_photo_missing_tool,
        test_chat_rules,
        test_v2_regressions,
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
    print(f"All v2 tests passed! ({len(tests)}/{len(tests)})")


if __name__ == "__main__":
    asyncio.run(main())
