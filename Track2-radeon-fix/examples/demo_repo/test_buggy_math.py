from buggy_math import clamp


def test_clamp_regular_interval():
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0
    assert clamp(11, 0, 10) == 10


def test_clamp_reversed_interval_keeps_lower_bound():
    assert clamp(5, 10, 0) == 10
