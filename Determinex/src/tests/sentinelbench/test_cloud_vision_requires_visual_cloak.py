"""SentinelBench: cloud vision API calls require Visual Cloak to be active."""


def test_cloud_vision_blocked_without_cloak(governor):
    allowed, reason = governor.check_cloud_vision_allowed(
        screenshot_path="/tmp/screenshot.png",
        cloak_active=False,
    )
    assert not allowed, "Cloud vision must be BLOCKED when cloak_active=False"
    assert "Visual Cloak" in reason or "cloak" in reason.lower()


def test_cloud_vision_allowed_with_cloak(governor):
    allowed, reason = governor.check_cloud_vision_allowed(
        screenshot_path="/tmp/screenshot.png",
        cloak_active=True,
    )
    assert allowed, f"Cloud vision must be ALLOWED when cloak_active=True, got: {reason}"
