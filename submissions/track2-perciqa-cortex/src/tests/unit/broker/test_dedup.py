from cortex.broker.dedup import Deduplicator


def test_is_replay_for_unseen_msg_id_returns_false():
    d = Deduplicator(replay_window_sec=600)
    assert d.is_replay(msg_id="m1", ts=1_000, now=1_100) is False


def test_is_replay_for_seen_msg_id_returns_true():
    d = Deduplicator(replay_window_sec=600)
    d.record(msg_id="m1", ts=1_000)
    assert d.is_replay(msg_id="m1", ts=1_000, now=1_100) is True


def test_is_replay_for_stale_ts_returns_true():
    d = Deduplicator(replay_window_sec=600)
    assert d.is_replay(msg_id="m2", ts=1_000, now=1_000 + 700) is True


def test_is_replay_for_future_ts_far_outside_window_returns_true():
    d = Deduplicator(replay_window_sec=600)
    assert d.is_replay(msg_id="m3", ts=2_000, now=1_000) is True


def test_lru_evicts_oldest_beyond_cap():
    d = Deduplicator(replay_window_sec=600, cap=3)
    d.record("a", 100)
    d.record("b", 200)
    d.record("c", 300)
    d.record("d", 400)
    assert d.is_replay(msg_id="a", ts=100, now=100) is False
    assert d.is_replay(msg_id="b", ts=200, now=200) is True


def test_record_idempotent():
    d = Deduplicator(replay_window_sec=600)
    d.record("x", 1)
    d.record("x", 1)
    assert d.is_replay("x", 1, 1) is True
