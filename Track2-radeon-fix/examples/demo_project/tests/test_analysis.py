from pycalc.analysis import mode, normalize


def test_mode_basic():
    assert mode([1, 2, 2, 3]) == 2


def test_mode_tie_returns_smaller():
    assert mode([3, 1, 3, 1]) == 1


def test_normalize_uses_range():
    assert normalize([10, 20, 30]) == [0.0, 0.5, 1.0]


def test_normalize_negative_values():
    assert normalize([-5, 0, 5]) == [0.0, 0.5, 1.0]


def test_normalize_equal_values():
    assert normalize([4, 4, 4]) == [0.0, 0.0, 0.0]


def test_normalize_empty():
    assert normalize([]) == []
