import sys

import scripts.determinex_queue as Q


def test_status_is_alias_for_stats(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["determinex_queue.py", "status"])
    monkeypatch.setattr(Q, "_backend", lambda: "redis")
    monkeypatch.setattr(Q, "redis_stats", lambda: {"pending_light": 2, "done": 3})

    Q.main()

    out = capsys.readouterr().out
    assert "pending_light: 2" in out
    assert "done: 3" in out
