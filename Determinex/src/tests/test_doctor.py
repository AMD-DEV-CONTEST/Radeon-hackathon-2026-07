"""tests/test_doctor.py — determinex_doctor smoke + verdict logic.

The doctor wraps subprocess calls so we can't easily mock out tools without
patching shutil.which / subprocess.run. We test:
  - the verdict-computation function is correct for synthetic check lists
  - the Check dataclass round-trips through to_dict
  - the demo-mode verdict is well-defined for each status combination
  - api_keys check NEVER includes key values in extra/detail
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import determinex_doctor as doc  # noqa: E402

# ---------------------------------------------------------------------------
# Check + verdict logic
# ---------------------------------------------------------------------------


def _ck(name: str, category: str, status: str) -> doc.Check:
    return doc.Check(name=name, category=category, status=status)


def test_check_to_dict_round_trip():
    c = doc.Check(
        name="t", category="core", status=doc.ACTIVE, detail="ok", extra={"key": "value"}, fix=""
    )
    d = c.to_dict()
    assert d["name"] == "t"
    assert d["status"] == doc.ACTIVE
    assert d["extra"]["key"] == "value"


def test_demo_verdict_full_capability_path():
    """All the right checks ACTIVE → all four demo capabilities YES."""
    checks = [
        _ck("python_version", "core", doc.ACTIVE),
        _ck("bash", "core", doc.ACTIVE),
        _ck("git", "core", doc.ACTIVE),
        _ck("docker_daemon", "core", doc.ACTIVE),
        _ck("ollama", "ai", doc.ACTIVE),
        _ck("api_keys", "ai", doc.ACTIVE),
        _ck("programbench_dir", "data", doc.ACTIVE),
    ]
    v = doc.deterministic_demo_verdict(checks)
    assert v["can_run_demo_without_models"] is True
    assert v["can_run_local_inference"] is True
    assert v["can_run_cloud_inference"] is True
    assert v["can_run_full_benchmarks"] is True
    assert v["missing_for_full_capability"] == []


def test_demo_verdict_minimal_demo_path():
    """Only core ACTIVE → demo YES but others NO."""
    checks = [
        _ck("python_version", "core", doc.ACTIVE),
        _ck("bash", "core", doc.ACTIVE),
        _ck("git", "core", doc.ACTIVE),
        _ck("docker_daemon", "core", doc.UNAVAIL),
        _ck("ollama", "ai", doc.UNAVAIL),
        _ck("api_keys", "ai", doc.UNAVAIL),
        _ck("programbench_dir", "data", doc.UNAVAIL),
    ]
    v = doc.deterministic_demo_verdict(checks)
    assert v["can_run_demo_without_models"] is True
    assert v["can_run_local_inference"] is False
    assert v["can_run_cloud_inference"] is False
    assert v["can_run_full_benchmarks"] is False
    # ollama + api_keys both UNAVAIL → reported in missing list
    assert set(v["missing_for_full_capability"]) >= {"ollama", "api_keys"}


def test_demo_verdict_broken_core_blocks_demo():
    """If even core checks fail, can_run_demo_without_models is False."""
    checks = [
        _ck("python_version", "core", doc.UNAVAIL),
        _ck("bash", "core", doc.ACTIVE),
        _ck("git", "core", doc.ACTIVE),
        _ck("docker_daemon", "core", doc.UNAVAIL),
        _ck("ollama", "ai", doc.UNAVAIL),
        _ck("api_keys", "ai", doc.UNAVAIL),
        _ck("programbench_dir", "data", doc.UNAVAIL),
    ]
    v = doc.deterministic_demo_verdict(checks)
    assert v["can_run_demo_without_models"] is False


# ---------------------------------------------------------------------------
# Privacy: api_keys check NEVER includes the key VALUE
# ---------------------------------------------------------------------------


def test_api_keys_check_never_logs_key_value(monkeypatch):
    """The api_keys check returns presence flags only. The actual KEY VALUES
    must never appear in detail, extra, or anywhere the user might paste."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-PROPRIETARY-do-not-leak-1234")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-SECRET-9999")
    c = doc.check_api_keys()
    blob = c.detail + " " + str(c.extra) + " " + (c.fix or "")
    assert "PROPRIETARY" not in blob
    assert "SECRET" not in blob
    assert "sk-test" not in blob
    assert "sk-deepseek" not in blob
    # Presence is reported correctly
    assert "ANTHROPIC_API_KEY" in c.extra.get("present", [])
    assert "DEEPSEEK_API_KEY" in c.extra.get("present", [])


# ---------------------------------------------------------------------------
# Real-system smoke
# ---------------------------------------------------------------------------


def test_run_all_returns_one_check_per_function():
    checks = doc.run_all()
    assert len(checks) == len(doc.ALL_CHECKS)
    # Every check has a name
    assert all(c.name for c in checks)
    # Every check has a known status
    valid = {doc.ACTIVE, doc.UNAVAIL, doc.PARTIAL, doc.DESIGN_ONLY}
    assert all(c.status in valid for c in checks), (
        f"unknown statuses: {[(c.name, c.status) for c in checks if c.status not in valid]}"
    )


def test_python_version_check_finds_311_or_better():
    """We require Python ≥3.11 to even import this module."""
    c = doc.check_python_version()
    assert c.status == doc.ACTIVE
    assert c.extra.get("version", "").startswith(("3.11", "3.12", "3.13"))


def test_unknown_status_marker_falls_back_to_question():
    """render_table tolerates unexpected statuses without crashing."""
    checks = [doc.Check(name="weird", category="core", status="WEIRD")]
    out = doc.render_table(checks)
    assert "weird" in out
    assert "WEIRD" in out
