"""
Proves the fleet contribution core: sealed-box crypto round-trips, and the ingest
keystone re-verifies (admits a passing item, drops a broken one, fails closed with
no sandbox). Uses Python items so the oracle is the local `python` oracle.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from fleet import crypto  # noqa: E402
from fleet.ingest_verify import ingest_shard, verify_item  # noqa: E402
from fleet.protocol import ContributionItem, Shard  # noqa: E402


def test_sealed_box_roundtrip():
    pub, priv = crypto.generate_node_keypair()
    msg = b"verified (error -> fix) pair, cloak-obfuscated"
    env = crypto.seal(pub, msg)
    assert env["ct"] != crypto._b64e(msg)  # actually encrypted
    assert crypto.open_sealed(priv, env) == msg  # node recovers it


def test_wrong_key_cannot_open():
    pub, _ = crypto.generate_node_keypair()
    _, other_priv = crypto.generate_node_keypair()
    env = crypto.seal(pub, b"secret")
    with pytest.raises(Exception):
        crypto.open_sealed(other_priv, env)


def test_ingest_fails_closed_without_sandbox():
    item = ContributionItem(
        lang="python", files={"m.py": "x = 1\n"}, pair={"conversations": [], "metadata": {}}
    )
    ok, reason = verify_item(item, sandbox=None)  # no sandbox, not allowed
    assert ok is False and "sandbox" in reason


def _py_pair(answer: str) -> dict:
    return {
        "conversations": [
            {"from": "human", "value": "write add"},
            {"from": "gpt", "value": answer},
        ],
        "metadata": {"lang": "python"},
    }


def test_ingest_admits_passing_drops_broken(tmp_path: Path):
    # a workdir the python oracle will PASS (a trivial pytest that passes)
    good = ContributionItem(
        lang="python",
        files={"test_ok.py": "def test_ok():\n    assert 1 + 1 == 2\n"},
        pair=_py_pair("1+1==2"),
    )
    # a workdir that FAILS verification (assertion is false)
    bad = ContributionItem(
        lang="python",
        files={"test_bad.py": "def test_bad():\n    assert 1 + 1 == 3\n"},
        pair=_py_pair("1+1==3 (poison)"),
    )
    shard = Shard(items=[good, bad])
    corpus = tmp_path / "corpus.jsonl"
    res = ingest_shard(shard, corpus, allow_unsandboxed=True, apply=True)

    assert good.id in res.admitted  # passing contribution accepted
    assert bad.id in res.dropped  # poison contribution rejected
    # only the admitted pair was written, tagged as re-verified
    lines = corpus.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    import json

    rec = json.loads(lines[0])
    assert rec["metadata"]["fleet_reverified"] is True
    assert rec["metadata"]["fleet_item_id"] == good.id


def test_cloak_no_leak_and_test_still_discoverable(tmp_path: Path):
    """Regression: Cloak must hide identifiers BUT keep test_* discoverable, else the
    node drops a legitimately-passing contribution."""
    from fleet.contribute import build_shard, render_preview
    from fleet.protocol import Shard

    raw = [
        {
            "lang": "python",
            "files": {
                "test_t.py": "def test_my_secret():\n    assert my_helper(2) == 4\n\n"
                "def my_helper(secret_value):\n    return secret_value * 2\n"
            },
            "pair": {
                "conversations": [{"from": "gpt", "value": "my_helper doubles secret_value"}],
                "metadata": {},
            },
            "origin": "verified_search",
        }
    ]
    shard = build_shard(raw, handle="t")
    payload = render_preview(shard)
    assert not any(s in payload for s in ("my_secret", "my_helper", "secret_value"))
    assert "test_x_" in payload  # discovery prefix preserved, name hidden

    pub, priv = crypto.generate_node_keypair()
    env = crypto.seal_json(pub, shard.to_dict())
    reopened = Shard.from_dict(crypto.open_json(priv, env))
    corpus = tmp_path / "c.jsonl"
    res = ingest_shard(reopened, corpus, allow_unsandboxed=True, apply=True)
    assert len(res.admitted) == 1 and not res.dropped


def test_dedup_skips_known_id(tmp_path: Path):
    good = ContributionItem(
        lang="python",
        files={"test_ok.py": "def test_ok():\n    assert True\n"},
        pair=_py_pair("ok"),
    )
    corpus = tmp_path / "corpus.jsonl"
    r1 = ingest_shard(Shard(items=[good]), corpus, allow_unsandboxed=True, apply=True)
    r2 = ingest_shard(Shard(items=[good]), corpus, allow_unsandboxed=True, apply=True)
    assert good.id in r1.admitted
    assert good.id in r2.duplicates and not r2.admitted
