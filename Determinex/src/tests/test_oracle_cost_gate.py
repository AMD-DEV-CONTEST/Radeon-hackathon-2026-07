"""An oracle must know what a job costs, say so, and never misreport giving up.

FOUND LIVE 2026-08-02, driving the IDE's own backend surface against a real repository.
`repair_diagnose` on C:/Dev/Determinex blocked with no output for ten minutes and then
reported:

    passed=False   test_id=pytest   name=collection/run
    "pytest exited -3 with no parsed test failures (collection or environment error)"

The repository was fine. Its test suite takes 43 minutes; the oracle's budget is 600s. Two
independent defects produced that line:

  1. `_run` rebuilt a subprocess.CompletedProcess from the hardened runner's result and
     DROPPED `res.timed_out`, so all 19 verify_fns saw "non-zero exit, no parsed failures"
     and blamed the user's environment for a limit Determinex imposed on itself.

  2. Nothing measured the job first. Ryan: "if it needs it it should tell you it will take
     that long, get permission to run and then come back, if not not do it."

These tests pin both, plus the three layers that were quietly upgrading the bad news to
success on its way to the frontend.
"""

from __future__ import annotations

import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import determinex_oracle as O  # noqa: E402


def _ws(**files: str) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, body in files.items():
        (d / name.replace("__", ".")).write_text(textwrap.dedent(body), encoding="utf-8")
    return d


# ── 1. a timeout is not a verdict ───────────────────────────────────────────────────────


def test_a_timeout_raises_rather_than_blaming_the_repository():
    """THE BUG. A healthy repo whose tests merely sleep was reported as having a pytest
    collection or environment error."""
    ws = _ws(test_slow__py="""
        import time
        def test_healthy_but_slow():
            time.sleep(60)
            assert True
    """)
    orig = O._run
    O._run = lambda cmd, cwd, timeout=6: orig(cmd, cwd, timeout=6)
    try:
        with pytest.raises(O.OracleTimedOut) as ei:
            O._verify_python(ws)
    finally:
        O._run = orig
    assert ei.value.seconds == 6
    assert "NOT a finding about the code" in str(ei.value)


def test_the_timeout_is_raised_at_the_choke_point_so_every_language_gets_it():
    """There are 24 `_run` call sites across 19 verify functions and every one had this bug,
    because none of them could see the flag that distinguishes 'broken' from 'we stopped
    waiting'. Fixing it in `_run` fixes all of them; pinning that it lives there stops
    someone reintroducing per-language handling that misses eighteen cases."""
    import inspect

    src = inspect.getsource(O._run)
    assert "res.timed_out" in src and "OracleTimedOut" in src


# ── 2. measure the cost, then ask ───────────────────────────────────────────────────────


def test_a_job_over_budget_asks_before_starting(monkeypatch):
    monkeypatch.setenv("DETERMINEX_ORACLE_BUDGET_S", "10")
    monkeypatch.delenv("DETERMINEX_ORACLE_APPROVED", raising=False)
    # Patch the PREFLIGHT, which is what verify() consults. Patching only the estimator left
    # the gate reading the real collection while the test asserted on a value nothing used --
    # a stub wired to the wrong seam, which is its own small version of the bug being tested.
    monkeypatch.setitem(
        O._PREFLIGHTS, "python",
        lambda _w: O.Preflight(oracle="python", collectible=9000, estimate_s=3600.0),
    )
    with pytest.raises(O.OracleNeedsApproval) as ei:
        O.get_oracle("python").verify(_ws(test_a__py="def test_a():\n    assert True\n"))
    assert ei.value.estimate_s == 3600.0
    assert "9000 tests collectible" in ei.value.detail
    assert "60 min" in str(ei.value), "the operator is owed the number, in units they read"


def test_a_job_within_budget_is_not_gated(monkeypatch):
    """Negative control. A gate that fires on everything would be worse than none: people
    would set DETERMINEX_ORACLE_APPROVED=1 permanently and it would protect nothing."""
    monkeypatch.setenv("DETERMINEX_ORACLE_BUDGET_S", "120")
    monkeypatch.delenv("DETERMINEX_ORACLE_APPROVED", raising=False)
    res = O.get_oracle("python").verify(_ws(test_a__py="def test_a():\n    assert True\n"))
    assert res.passed is True


def test_approval_skips_the_gate_and_not_the_verification(monkeypatch):
    """`approved=True` means "I accept the cost", never "assume it passed". An approval that
    short-circuited the check would be the silent pass this project forbids everywhere."""
    monkeypatch.setenv("DETERMINEX_ORACLE_BUDGET_S", "1")
    monkeypatch.setitem(O._PREFLIGHTS, "python",
                        lambda _w: O.Preflight(oracle="python", collectible=9999, estimate_s=9999.0))
    ws = _ws(test_bad__py="def test_a():\n    assert 1 == 2\n")
    res = O.get_oracle("python").verify(ws, approved=True)
    assert res.passed is False, "the real oracle must still have run"
    assert res.failures, "and must still report the real failure"


def test_an_unestimatable_oracle_is_not_gated_on_an_invented_number():
    """Only python has a measured estimator. An oracle with no entry must run, not be
    blocked by a guess -- an absent measurement must never become a fabricated one."""
    assert O.estimate_work("rust", Path(".")) is None
    assert O.estimate_work("no-such-oracle", Path(".")) is None


def test_the_estimate_is_derived_from_pytests_own_collection():
    """A count from pytest is the only honest source for 'how many tests are there'. This
    also documents the rate's provenance: 0.46 s/test comes from THIS repository's suite
    (5,670 tests in 2,608s), so it is calibration, not independent validation."""
    ws = _ws(**{f"test_{i}__py": f"def test_{i}():\n    assert True\n" for i in range(3)})
    est = O.estimate_python_work(ws)
    assert est is not None
    seconds, detail = est
    assert "3 tests collected" in detail
    assert 0 < seconds < 10


# ── 3. the three layers that were upgrading bad news to success ─────────────────────────


def test_repair_reports_needs_approval_as_its_own_status_not_as_an_error(monkeypatch):
    """`repair_workspace` caught every exception into status='error'. So "we did not start,
    because we did not have permission" reached the user as "your repository is broken"."""
    import determinex_repair as R

    monkeypatch.setenv("DETERMINEX_ORACLE_BUDGET_S", "1")
    monkeypatch.delenv("DETERMINEX_ORACLE_APPROVED", raising=False)
    monkeypatch.setitem(O._PREFLIGHTS, "python",
                        lambda _w: O.Preflight(oracle="python", collectible=5709, estimate_s=2600.0))
    res = R.repair_workspace(_ws(test_a__py="def test_a():\n    assert True\n"))
    assert res.oracle == "needs_approval", res.oracle
    assert res.oracle != "error"
    assert any("approval required" in n for n in res.notes)


def test_the_bridge_never_defaults_an_unknown_status_to_ok(monkeypatch):
    """THE THIRD LAYER. `status_map.get(status, "TAURI_COMMAND_OK")` reported any status the
    table had not been taught as SUCCESS -- including, when it was first added, the
    NEEDS_APPROVAL whose whole job is to stop the frontend acting as if work was done.

    Asserted by DRIVING the bridge with an unmapped status rather than by reading its
    source: the first version of this test grepped for the offending expression and failed
    because it matched the comment explaining the fix. A check that inspects a proxy for the
    behaviour is the thing this file exists to catch.
    """
    from ide.tauri_backend_bridge import TauriBackendBridge

    class _Inner:
        status = "IDE_COMMAND_SOMETHING_NOBODY_MAPPED"
        payload: dict = {}
        notes: tuple = ()

    b = TauriBackendBridge()
    monkeypatch.setattr(b._surface, "call", lambda *a, **k: _Inner())
    res = b.call("get_governance_status")
    assert res.status != "TAURI_COMMAND_OK", "an unmapped status must not become success"
    assert res.status == "TAURI_COMMAND_SOMETHING_NOBODY_MAPPED", (
        f"it should propagate mechanically, got {res.status!r}"
    )


def test_the_bridge_still_maps_the_statuses_it_knows(monkeypatch):
    """Negative control for the change above: the mechanical fallback must not shadow the
    explicit table, or a rename in the table would silently stop taking effect."""
    from ide.tauri_backend_bridge import TauriBackendBridge

    class _Inner:
        status = "IDE_COMMAND_BLOCKED_UNKNOWN_COMMAND"
        payload: dict = {}
        notes: tuple = ()

    b = TauriBackendBridge()
    monkeypatch.setattr(b._surface, "call", lambda *a, **k: _Inner())
    assert b.call("get_governance_status").status == "TAURI_COMMAND_BLOCKED_UNKNOWN"


# ── 4. pre-flight triage: what compiles, what doesn't, what isn't ours ──────────────────
# Ryan, 2026-08-02: "our onboard runtimes should tell us what compiles what doesn't from the
# jump, we should filter what doesn't work. or what paths are clunky for looking at. it's
# about finding the patterns, fixing and correcting."
#
# The cost gate alone was honest but blunt -- it priced a 44-minute job and asked. Usually
# the real answer is that 44 minutes was never the right job.


def test_vendored_trees_are_not_counted_or_verified():
    """A node_modules with its own suite would be collected, estimated, and RUN. Verifying
    somebody else's dependencies is not a wrong-ish estimate, it is the wrong job -- and it
    is the single biggest reason a quick check becomes a forty-minute one. pytest's default
    norecursedirs catches `.*`, build, dist and venv; it does not catch this."""
    ws = _ws(test_mine__py="def test_a():\n    assert True\n")
    vendored = ws / "node_modules" / "somepkg"
    vendored.mkdir(parents=True)
    for i in range(30):
        (vendored / f"test_v{i}.py").write_text("def test_v():\n    assert True\n", encoding="utf-8")

    pf = O.preflight_python(ws)
    assert pf.collectible == 1, f"expected only our own test, got {pf.collectible}"
    assert "node_modules" in pf.noise_paths


def test_a_file_that_does_not_import_is_reported_in_seconds():
    """'What compiles and what doesn't, from the jump.' These are real findings that cost a
    collection pass, and before this they were invisible until the full run finished -- or
    forever, on a repo whose full run never finishes."""
    ws = _ws(
        test_ok__py="def test_a():\n    assert True\n",
        test_bad__py="import a_module_that_does_not_exist\n\ndef test_b():\n    assert True\n",
    )
    pf = O.preflight_python(ws)
    assert pf.broken_paths, "a non-importable module must be named"
    path, reason = pf.broken_paths[0]
    assert "test_bad" in path
    assert reason, "and must carry why, not just that"
    assert pf.actionable is True


def test_a_clean_workspace_reports_nothing_to_act_on():
    """Negative control. A triage that always finds something is noise, and noise gets
    ignored -- which is how the original gap survived."""
    pf = O.preflight_python(_ws(test_a__py="def test_a():\n    assert True\n"))
    assert pf.broken_paths == []
    assert pf.noise_paths == []
    assert pf.actionable is False
    assert pf.collectible == 1


def test_the_approval_prompt_states_the_cheap_findings_before_the_expensive_run(monkeypatch):
    """A user deciding whether to spend 44 minutes should be told what we already know for
    free. Often that IS the answer they came for."""
    monkeypatch.setenv("DETERMINEX_ORACLE_BUDGET_S", "1")
    monkeypatch.delenv("DETERMINEX_ORACLE_APPROVED", raising=False)
    # Enough REAL tests to clear the 1s budget floor on a genuine estimate. Stubbing the
    # preflight here would defeat the test: the point is that the message quotes what the
    # cheap pass actually found, so the cheap pass has to actually run.
    files = {f"test_{i}__py": "def test_a():\n    assert True\n" for i in range(12)}
    files["test_bad__py"] = "import nope_not_here\n\ndef test_b():\n    assert True\n"
    ws = _ws(**files)
    with pytest.raises(O.OracleNeedsApproval) as ei:
        O.get_oracle("python").verify(ws)
    msg = str(ei.value)
    assert "do not import" in msg
    assert "test_bad" in msg


def test_noise_discovery_does_not_walk_into_the_trees_it_is_excluding():
    """This repo carries ~155,000 vendored files. Walking them to discover they are vendored
    costs more than the check saves, so the walk prunes as it goes."""
    ws = _ws(test_a__py="def test_a():\n    assert True\n")
    deep = ws / "node_modules" / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    for i in range(20):
        (deep / f"junk{i}.py").write_text("x = 1\n", encoding="utf-8")
    found = O.find_noise_paths(ws)
    assert found == ["node_modules"], f"must report the root of the tree only, got {found}"
