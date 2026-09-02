"""Locks for the 2026-07-02 throughput audit fixes (oracle dedup + early escalation).

Audit finding on the live cmatrix run: the 48 probes collapse to only 6 distinct
behavior classes ((rc, stdout, stderr) identity -- 30x the same 'Error opening
terminal' stderr, 7x usage, 5x version, 4x segfault, ...), so:
  1. ORACLE DEDUP -- every candidate verify inside the router's search paid ~8x
     redundant probe-runs. The SEARCH oracle now uses one representative per class
     (+ always the station's own probe); ACCEPTANCE stays on the FULL accepted set,
     so a rep-gaming candidate is never admitted -- soundness untouched.
  2. VERIFY MEMO -- the per-station skip-check re-ran the whole accepted prefix
     (O(n^2) probe-runs / run) even though `current` only changes on acceptance.
     While code is unchanged and all prior probes are known-passing, the skip-check
     runs ONLY the one new probe.
  3. EARLY ESCALATE -- 7b burned its full k*rounds budget (~15 min) at score 0.00
     on a station 14b then solved in 2 samples. A whole round of distinct samples
     at exactly 0.00 = the tier has no traction and feedback can't rescue (there is
     no partial to refine) -> hand the leaf up the ladder now. Router sets this for
     every tier that HAS a next tier; the top tier keeps its full round budget.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import determinex_observe as OBS  # noqa: E402
import determinex_pb_reimpl as reimpl  # noqa: E402
from determinex_router import ModelEntry, ModelRouter  # noqa: E402
from determinex_verified_search import VerifiedSearch  # noqa: E402


def _obs(name, argv, stdout="", stderr="", rc=0):
    return OBS.Observation(OBS.Probe(name, list(argv), None, {}, {}), stdout, stderr, rc)


# ---------------------------------------------------------------- oracle dedup


def test_dedup_one_rep_per_behavior_class():
    same_err = [
        _obs(f"e{i}", [f"-{c}"], "", "Error opening terminal: unknown.\n", 1)
        for i, c in enumerate("abcd")
    ]
    help_o = _obs("help", ["-h"], "usage: x\n")
    reps = reimpl._dedup_reps(same_err + [help_o], help_o)
    assert len(reps) == 2  # one error-class rep + help
    assert reps[0].probe.name == "e0" and reps[1].probe.name == "help"


def test_dedup_always_includes_the_focus_probe():
    # focus shares a class with an earlier rep but is a DIFFERENT probe (different argv)
    a = _obs("a", ["-a"], "", "boom\n", 1)
    b = _obs("b", ["-b"], "", "boom\n", 1)
    reps = reimpl._dedup_reps([a, b], b)
    assert any(x is b for x in reps)  # the station's own behavior is always asserted


def test_dedup_distinct_classes_all_kept():
    xs = [
        _obs("h", ["-h"], "usage\n"),
        _obs("v", ["-V"], "v1.0\n"),
        _obs("seg", ["-u", "0"], "", "Segmentation fault\n", 139),
    ]
    assert len(reimpl._dedup_reps(xs, xs[-1])) == 3


def test_incremental_solve_skip_checks_use_verify_memo():
    # 3 probes, code never changes (everything passes) -> without the memo the skip
    # checks cost 1+2+3=6 probe-runs; with it: 1 full + 1 solo + 1 solo = 3.
    calls = {"n": 0}

    def runner(code, probe):
        calls["n"] += 1
        return "x\n", "", 0

    obs = [_obs(f"p{i}", [f"-{i}"], "x\n") for i in range(3)]
    code, stations = reimpl.incremental_solve(obs, ladder=[], helptext="", short="t", runner=runner)
    assert stations == 0
    assert calls["n"] == 3  # memo held: one probe-run per station, not the full prefix


def test_incremental_solve_acceptance_still_uses_full_set(monkeypatch):
    # A candidate that passes the DEDUPED reps but regresses a duplicate probe on the
    # full set must NOT be admitted (soundness of dedup rests on this).
    monkeypatch.setattr(reimpl, "_LANG", "c")
    # two probes in one class + one distinct; runner keys off argv so a candidate can
    # pass -a but fail -b even though they share a behavior class
    obs = [_obs("a", ["-a"], "same\n"), _obs("b", ["-b"], "same\n"), _obs("c", ["-c"], "other\n")]

    def runner(code, probe):
        if "GOOD" in code:
            return ("same\n" if probe.argv[0] in ("-a", "-b") else "other\n"), "", 0
        if "GAME" in code:  # passes reps (-a, -c) but fails duplicate -b
            if probe.argv[0] == "-a":
                return "same\n", "", 0
            if probe.argv[0] == "-c":
                return "other\n", "", 0
            return "WRONG\n", "", 0
        return "", "", 1

    gamed = reimpl._dedup_reps(obs, obs[2])
    game_res = OBS.make_verify(gamed, runner=runner)("int GAME;")
    full_res = OBS.make_verify(obs, runner=runner)("int GAME;")
    assert game_res.passed and not full_res.passed  # the gap dedup opens...
    # ...and the acceptance check closes: full verify of GAME shows the -b failure
    assert any(f.name == "b" for f in full_res.failures)


def test_composite_search_keeps_working_after_rep_overfit(monkeypatch):
    # LIVE BUG (cmatrix station 5, 2026-07-02): a candidate passed the deduped reps,
    # the router returned "solved", acceptance rejected it on the full set -- and the
    # station moved on unsolved without ever escalating. The composite search oracle
    # (rep-pass pays for a full verify INSIDE the search) must keep the search
    # iterating past a rep-overfit candidate until a full pass.
    monkeypatch.setenv("DETERMINEX_VS_HEARTBEAT", "0")
    monkeypatch.setattr(reimpl, "_LANG", "c")
    obs = [
        _obs("a", ["-a"], "same\n"),
        _obs("b", ["-b"], "same\n"),
        _obs("c", ["-c"], "same\n"),
    ]  # one behavior class x3 -> dedup active at st.3

    def runner(code, probe):
        ok_by = {
            "GOODA": ("-a",),
            "GAME": ("-a", "-c"),
            "AB": ("-a", "-b"),
            "GOOD": ("-a", "-b", "-c"),
        }
        for key, argvs in ok_by.items():
            if key in code:
                return ("same\n" if probe.argv[0] in argvs else "WRONG\n"), "", 0
        return "", "", 1

    seq = iter(["GOODA", "GAME", "AB", "GAME", "GOOD"])
    calls = {"n": 0}

    def gen(prompt, temp):
        calls["n"] += 1
        return next(seq)

    ladder = [ModelEntry("scripted", tier=1, cost=0.0, generate=gen)]
    code, stations = reimpl.incremental_solve(
        obs, ladder=ladder, helptext="", short="t", k=1, rounds=5, runner=runner
    )
    # station 3's GAME passes both reps (a, c) but fails duplicate b on the full set:
    # the composite oracle must NOT let the search return solved there -- the next
    # sample (GOOD) is required. 5 generations total proves the search continued.
    assert "GOOD" in code and "GAME" not in code
    assert calls["n"] == 5


def test_monotone_acceptance_rejects_behavior_swaps(monkeypatch):
    # LIVE BUG (cmatrix station 7, 2026-07-02): candidate added -s but DROPPED the
    # already-solved -n; both scored 4/5, and `n_pass >= cur` accepted the swap --
    # silently regressing a done probe. Acceptance must be monotone: never admit a
    # candidate that fails anything the current program passes.
    monkeypatch.setenv("DETERMINEX_VS_HEARTBEAT", "0")
    monkeypatch.setattr(reimpl, "_LANG", "c")
    obs = [
        _obs("n", ["-n"], "", "Error opening terminal: unknown.\n", 1),
        _obs("s", ["-s"], "", "Error opening terminal: unknown.\n", 1),
    ]

    def runner(code, probe):
        flags = {"HAS_N": ("-n",), "SWAP": ("-s",), "BOTH": ("-n", "-s")}
        for key, argvs in flags.items():
            if key in code and probe.argv[0] in argvs:
                return "", "Error opening terminal: unknown.\n", 1
        return "", "", 0  # unhandled flag: silently exits 0 (wrong)

    # seed: station 1 solves -n (HAS_N); station 2's model offers only the SWAP
    # candidate (passes -s, drops -n) -- must be REJECTED, leaving HAS_N in place.
    seq = iter(["HAS_N", "SWAP", "SWAP2 SWAP", "SWAP3 SWAP"])

    def gen(prompt, temp):
        return next(seq, "SWAP_more SWAP")

    ladder = [ModelEntry("swappy", tier=1, cost=0.0, generate=gen)]
    code, _ = reimpl.incremental_solve(
        obs, ladder=ladder, helptext="", short="t", k=1, rounds=3, runner=runner
    )
    assert "HAS_N" in code  # the solved behavior survived
    assert "SWAP" not in code  # the swap candidate was refused


def test_unsolved_station_is_not_checkpointed_done(tmp_path, monkeypatch):
    monkeypatch.setenv("DETERMINEX_VS_HEARTBEAT", "0")
    monkeypatch.setattr(reimpl, "_LANG", "c")
    import json

    obs = [_obs("a", ["-a"], "same\n")]

    def runner(code, probe):
        return "WRONG\n", "", 0  # nothing ever passes

    ladder = [ModelEntry("hopeless", tier=1, cost=0.0, generate=lambda p, t: f"junk{t}")]
    ck = tmp_path / "t_stations.ckpt.json"
    reimpl.incremental_solve(
        obs, ladder=ladder, helptext="", short="t", k=1, rounds=1, runner=runner, checkpoint_path=ck
    )
    d = json.loads(ck.read_text(encoding="utf-8"))
    assert d["done"] == []  # unsolved behavior stays retryable on restart
    assert d["stations"] == 1  # ...but the work attempt is still recorded


# ------------------------------------------------------------- early escalation


class _R:
    def __init__(self, passed, score):
        self.passed = passed
        self.failures = [] if passed else ["x"]
        self.score = score


def test_zero_signal_round_escalates_early(monkeypatch):
    monkeypatch.setenv("DETERMINEX_VS_HEARTBEAT", "0")
    calls = {"n": 0}

    def gen(prompt, temp):
        calls["n"] += 1
        return f"junk-{temp}-{calls['n']}"

    vs = VerifiedSearch(verify=lambda t: _R(False, 0.0), k=4, rounds=3, early_escalate=True)
    res = vs.solve(gen, "p")
    assert not res.solved and res.rounds_used == 1
    assert calls["n"] == 4  # one round of k, not rounds*k
    assert "zero-signal" in res.proof


def test_partial_signal_keeps_all_rounds_even_with_early_escalate(monkeypatch):
    monkeypatch.setenv("DETERMINEX_VS_HEARTBEAT", "0")
    calls = {"n": 0}

    def gen(prompt, temp):
        calls["n"] += 1
        return f"junk-{calls['n']}"

    vs = VerifiedSearch(verify=lambda t: _R(False, 0.4), k=4, rounds=3, early_escalate=True)
    res = vs.solve(gen, "p")
    assert res.rounds_used == 3  # score > 0 -> feedback rounds get their chance
    assert calls["n"] == 12


def test_early_escalate_defaults_off(monkeypatch):
    monkeypatch.setenv("DETERMINEX_VS_HEARTBEAT", "0")
    calls = {"n": 0}

    def gen(prompt, temp):
        calls["n"] += 1
        return f"junk-{calls['n']}"

    vs = VerifiedSearch(verify=lambda t: _R(False, 0.0), k=4, rounds=3)
    res = vs.solve(gen, "p")
    assert res.rounds_used == 3  # historical behavior preserved when flag is off


def test_router_early_escalates_lower_tier_but_not_top(monkeypatch):
    monkeypatch.setenv("DETERMINEX_VS_HEARTBEAT", "0")
    tier_calls = {"weak": 0, "strong": 0}

    def weak(prompt, temp):
        tier_calls["weak"] += 1
        return f"weak-{tier_calls['weak']}"

    def strong(prompt, temp):
        tier_calls["strong"] += 1
        return f"strong-{tier_calls['strong']}"

    router = ModelRouter(
        [
            ModelEntry("weak", tier=1, cost=0.0, generate=weak),
            ModelEntry("strong", tier=2, cost=1.0, generate=strong),
        ],
        k=4,
        rounds=3,
    )
    rr = router.solve_leaf(verify=lambda t: _R(False, 0.0), prompt="p", start_tier=1)
    assert not rr.solved
    assert tier_calls["weak"] == 4  # zero-signal round 1 -> escalated immediately
    assert tier_calls["strong"] == 12  # top tier keeps its full k*rounds budget


def test_router_top_tier_solve_still_returns_solved(monkeypatch):
    monkeypatch.setenv("DETERMINEX_VS_HEARTBEAT", "0")

    def weak(prompt, temp):
        return "weak"

    def strong(prompt, temp):
        return "RIGHT"

    router = ModelRouter(
        [
            ModelEntry("weak", tier=1, cost=0.0, generate=weak),
            ModelEntry("strong", tier=2, cost=1.0, generate=strong),
        ],
        k=2,
        rounds=2,
    )
    rr = router.solve_leaf(
        verify=lambda t: _R(t == "RIGHT", 1.0 if t == "RIGHT" else 0.0), prompt="p", start_tier=1
    )
    assert rr.solved and rr.model_used == "strong" and rr.escalations == 1
