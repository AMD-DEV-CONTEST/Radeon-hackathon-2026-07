"""Tests that EXPECT add() to add. Will FAIL on the broken fixture."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from calc import add, multiply  # noqa: E402


def test_add_two_plus_three_equals_five():
    assert add(2, 3) == 5


def test_multiply_three_times_four_equals_twelve():
    assert multiply(3, 4) == 12
