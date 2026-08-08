"""Master Cognitive Planner v1.0 regression tests.

Covers the language-understanding examples from the spec:
  - "Open Chrome" / "Launch Chrome" / "Run Chrome" / "Fire up Chrome" /
    "Bring up Chrome" / "Start Chrome"  -> browser_open
  - "Go to YouTube" / "Visit youtube" / "Open youtube" / "Take me to youtube" /
    "Browse youtube"                     -> open_website
  - Aliases (Open DC -> Discord, VSCode, YT)
  - Spelling mistakes (opne chrom, lauch firefoxx)
  - Semantic OCR matching (login <-> sign in, continue <-> next)
  - The full cognitive plan metadata output
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))


async def test_browser_open_intent():
    """Spec: all open-browser phrasings map to browser_open."""
    from app.agent.planner import Planner

    print("\nTesting browser_open intent...")
    planner = Planner()
    cases = {
        "Open Chrome": "browser_open",
        "Launch Chrome": "browser_open",
        "Run Chrome": "browser_open",
        "Fire up Chrome": "browser_open",
        "Bring up Chrome": "browser_open",
        "Start Chrome": "browser_open",
        "open the browser": "browser_open",
        "open edge": "browser_open",
        "open firefox": "browser_open",
    }
    for command, expected in cases.items():
        intent = await planner.classify_intent(command)
        status = "[ok]" if intent == expected else "[fail]"
        print(f"{status} '{command}' -> {intent} (expected {expected})")
        assert intent == expected, f"'{command}' -> {intent}, expected {expected}"

    # Plan must resolve to system.open_app with a browser name
    plan = await planner.create_plan("Open Chrome", "browser_open")
    assert plan["steps"][0]["tool"] == "system.open_app"
    assert plan["steps"][0]["args"]["name"].lower() == "chrome"


async def test_open_website_intent():
    """Spec: go-to/visit/browse site phrasings map to open_website."""
    from app.agent.planner import Planner

    print("\nTesting open_website intent...")
    planner = Planner()
    cases = {
        "Go to YouTube": "open_website",
        "Visit youtube": "open_website",
        "Open youtube": "open_website",
        "Take me to youtube": "open_website",
        "Browse youtube": "open_website",
        "open github.com": "open_website",
    }
    for command, expected in cases.items():
        intent = await planner.classify_intent(command)
        status = "[ok]" if intent == expected else "[fail]"
        print(f"{status} '{command}' -> {intent} (expected {expected})")
        assert intent == expected, f"'{command}' -> {intent}, expected {expected}"

    plan = await planner.create_plan("Open youtube", "open_website")
    assert plan["steps"][0]["tool"] == "browser.open"
    assert plan["steps"][0]["args"]["url"] == "https://www.youtube.com"


async def test_aliases():
    """Spec: remember aliases (DC -> Discord, VSCode, YT)."""
    from app.agent.planner import Planner, resolve_user_alias

    print("\nTesting alias resolution...")
    assert resolve_user_alias("Open DC") == "Open discord"
    assert resolve_user_alias("VSCode please") == "visual studio code please"
    assert resolve_user_alias("open YT") == "open youtube"
    print("[ok] alias resolution")

    planner = Planner()
    intent = await planner.classify_intent("Open DC")
    print(f"[ok] 'Open DC' -> {intent}")
    assert intent == "open_app"
    intent = await planner.classify_intent("open YT")
    print(f"[ok] 'open YT' -> {intent}")
    assert intent == "open_website"


async def test_spelling_corrections():
    """Spec: never reject a command because of wording/typos."""
    from app.agent.planner import Planner

    print("\nTesting spelling corrections...")
    planner = Planner()
    intent = await planner.classify_intent("opne chrom")
    print(f"[ok] 'opne chrom' -> {intent}")
    assert intent == "browser_open"
    intent = await planner.classify_intent("lauch firefoxx")
    print(f"[ok] 'lauch firefoxx' -> {intent}")
    assert intent == "browser_open"


async def test_existing_behavior_preserved():
    """Existing hard-asserted cases must not regress."""
    from app.agent.planner import Planner

    print("\nTesting existing behavior preserved...")
    planner = Planner()

    intent = await planner.classify_intent("open YouTube")
    assert intent == "open_website"

    intent = await planner.classify_intent("Open gx browser")
    assert intent == "open_app"

    intent = await planner.classify_intent("open Opera GX browser")
    assert intent == "open_app"

    intent = await planner.classify_intent("close browser")
    assert intent == "browser_close"

    intent = await planner.classify_intent("search best air coolers in chrome")
    assert intent == "search_web"
    print("[ok] all existing hard-asserts preserved")


async def test_cognitive_pipeline_and_plan():
    """The full cognitive plan must include all metadata sections."""
    from app.agent.planner import Planner, cognitive_pipeline

    print("\nTesting cognitive pipeline + plan...")
    planner = Planner()

    cognitive = cognitive_pipeline("Launch Chrome please")
    for key in ("original", "spelling_corrected", "alias_resolved",
                "synonym_expanded", "canonical_actions", "normalized"):
        assert key in cognitive, f"missing cognitive key: {key}"
    print("[ok] cognitive_pipeline returns all 6 stages")

    plan = await planner.create_cognitive_plan("Open Chrome")
    for key in ("intent", "entities", "execution_graph", "pipelines",
                "models", "dependencies", "verification_steps",
                "recovery_plan", "confidence_score", "risk_score",
                "canonical_actions", "wait_strategies", "autonomous_steps"):
        assert key in plan, f"missing cognitive plan key: {key}"
    assert plan["intent"] == "browser_open"
    assert plan["execution_graph"], "execution_graph must be non-empty"
    assert plan["risk_score"] == 1
    assert 0.0 <= plan["confidence_score"] <= 1.0
    assert plan["models"] == ["browser_automation"]
    print("[ok] create_cognitive_plan returns all metadata sections")


async def test_semantic_ocr_match():
    """Spec: OCR must never rely on exact text."""
    from app.agent.planner import semantic_ocr_match
    from app.tools.screen_tools import ScreenTools

    print("\nTesting semantic OCR matching...")
    # Direct matcher
    assert semantic_ocr_match("login", "sign in") >= 0.9
    assert semantic_ocr_match("continue", "next") >= 0.9
    assert semantic_ocr_match("share", "Share") == 1.0
    print("[ok] semantic_ocr_match")

    # Wired into screen tools scoring
    tools = ScreenTools()
    score = tools._score("login", "sign in")
    print(f"[ok] ScreenTools._score('login','sign in') = {score}")
    assert score >= 0.85
    # Existing exact/contains behavior unchanged
    assert tools._score("share", "Share") == 1.0
    assert tools._score("send", "send message") == 0.9


async def test_risk_levels():
    """Risk scores per the spec's access model."""
    from app.agent.planner import Planner, compute_risk

    print("\nTesting risk scores...")
    planner = Planner()
    assert compute_risk("browser_open") == 1
    assert compute_risk("open_website") == 1
    assert compute_risk("delete_files") == 4
    intent = await planner.classify_intent("delete files in Downloads")
    assert compute_risk(intent) == 4
    print("[ok] risk scores")


async def main():
    tests = [
        test_browser_open_intent,
        test_open_website_intent,
        test_aliases,
        test_spelling_corrections,
        test_existing_behavior_preserved,
        test_cognitive_pipeline_and_plan,
        test_semantic_ocr_match,
        test_risk_levels,
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
    print(f"All cognitive planner tests passed! ({len(tests)}/{len(tests)})")


if __name__ == "__main__":
    asyncio.run(main())
