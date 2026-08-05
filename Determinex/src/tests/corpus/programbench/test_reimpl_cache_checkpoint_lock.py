"""Locks for the 2026-07-02 reimpl throughput fixes.

Three mechanisms that make kills/restarts cheap and long local runs observable:
  1. Observation cache -- the observe phase is deterministic per tool+image but was
     re-paid on every relaunch (paid 4x for cmatrix in one day). Cache key includes
     the corpus-learned-probe signature: the drive's self-feed loop grows probes
     between iterations, and growth MUST invalidate the cache or the compounding
     oracle silently freezes.
  2. Station checkpoint -- decompose restarted from station 0 on every kill,
     discarding all accepted stations (a 1.5h run's progress vanished per config fix).
  3. VerifiedSearch heartbeat + concurrency cap -- a healthy 30-60min station was
     indistinguishable from a hang, and k-way fan-out against a 1-4-slot local
     ollama left queued requests burning their own timeout (observed: 11.7 min
     queued then dead).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import determinex_observe as OBS  # noqa: E402
import determinex_pb_reimpl as reimpl  # noqa: E402


def _fake_obs():
    return [
        OBS.Observation(OBS.Probe("p1", ["-h"], None, {}, {}), "out", "err", 0),
        OBS.Observation(
            OBS.Probe("p2", [], "stdin", {"f.txt": "x"}, {}, env={"NO_COLOR": "1"}), "o2", "", 1
        ),
    ]


def test_obs_cache_round_trips_all_probe_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(reimpl, "ROOT", tmp_path)
    sig = reimpl._corpus_probes_sig([{"name": "learned1", "argv": ["-x"]}])
    reimpl._save_obs_cache("t__f.abc", "img:task", sig, _fake_obs())
    back = reimpl._load_obs_cache("t__f.abc", "img:task", sig)
    assert back is not None and len(back) == 2
    assert back[0].probe.argv == ["-h"] and back[0].returncode == 0
    assert back[1].probe.env == {"NO_COLOR": "1"} and back[1].probe.stdin == "stdin"


def test_obs_cache_invalidated_by_image_change(tmp_path, monkeypatch):
    monkeypatch.setattr(reimpl, "ROOT", tmp_path)
    sig = reimpl._corpus_probes_sig([])
    reimpl._save_obs_cache("t__f.abc", "img:task", sig, _fake_obs())
    assert reimpl._load_obs_cache("t__f.abc", "OTHER:task", sig) is None


def test_obs_cache_invalidated_by_corpus_growth(tmp_path, monkeypatch):
    # LOAD-BEARING: the drive self-feed loop adds probes between iterations; a cache
    # that survived corpus growth would freeze the compounding oracle.
    monkeypatch.setattr(reimpl, "ROOT", tmp_path)
    sig0 = reimpl._corpus_probes_sig([])
    reimpl._save_obs_cache("t__f.abc", "img:task", sig0, _fake_obs())
    sig1 = reimpl._corpus_probes_sig([{"name": "new-divergence", "argv": ["-z"]}])
    assert sig0 != sig1
    assert reimpl._load_obs_cache("t__f.abc", "img:task", sig1) is None


def test_obs_cache_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(reimpl, "ROOT", tmp_path)
    assert reimpl._load_obs_cache("never__saved.xyz", "img:task", "s") is None


def test_checkpoint_write_shape_and_atomicity(tmp_path):
    ck = tmp_path / "x_stations.ckpt.json"
    reimpl._save_ckpt(ck, "sig123", "int main(){}", {"b", "a"}, 2)
    d = json.loads(ck.read_text(encoding="utf-8"))
    assert d == {"obs_sig": "sig123", "current": "int main(){}", "done": ["a", "b"], "stations": 2}
    assert not ck.with_suffix(".tmp").exists()  # atomic replace, no tmp left behind


def test_stations_sig_depends_on_probe_names():
    a = reimpl._stations_sig(_fake_obs())
    b = reimpl._stations_sig(list(reversed(_fake_obs())))
    assert a != b  # order matters: resume indices are positional


def test_verified_search_concurrency_cap_and_heartbeat(monkeypatch, capsys):
    monkeypatch.setenv("DETERMINEX_VS_MAX_CONCURRENCY", "1")
    from determinex_verified_search import VerifiedSearch

    class R:
        def __init__(self, p):
            self.passed = p
            self.failures = [] if p else ["x"]
            self.score = 1.0 if p else 0.0

    in_flight = {"now": 0, "max": 0}

    def gen(prompt, temp):
        in_flight["now"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["now"])
        try:
            return f"cand-{temp}"
        finally:
            in_flight["now"] -= 1

    vs = VerifiedSearch(verify=lambda t: R(t == "cand-0.4"), k=4, rounds=1)
    res = vs.solve(gen, "p")
    assert res.solved
    assert in_flight["max"] == 1  # the cap held: never more than 1 in flight
    out = capsys.readouterr().out
    assert "[vs] r1 s1/4" in out  # heartbeat printed per sample


def test_verified_search_heartbeat_can_be_silenced(monkeypatch, capsys):
    monkeypatch.setenv("DETERMINEX_VS_HEARTBEAT", "0")
    from determinex_verified_search import VerifiedSearch

    class R:
        passed = True
        failures: list = []
        score = 1.0

    vs = VerifiedSearch(verify=lambda t: R(), k=2, rounds=1)
    res = vs.solve(lambda p, t: f"c-{t}", "p")
    assert res.solved
    assert "[vs]" not in capsys.readouterr().out
