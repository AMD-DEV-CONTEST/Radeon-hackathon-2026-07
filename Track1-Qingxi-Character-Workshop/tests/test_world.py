import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.world import load_world, WorldConfig


def test_load_world_has_six_affinities():
    w = load_world()
    assert isinstance(w, WorldConfig)
    assert len(w.affinities) == 6
    assert w.world_name
    names = {a.name for a in w.affinities}
    assert names == {"Form", "Mind", "Life", "Matter", "Void", "Time"}


def test_affinity_ids_unique():
    w = load_world()
    ids = [a.id for a in w.affinities]
    assert len(ids) == len(set(ids))


def test_banned_check():
    w = load_world()
    assert w.contains_banned("我想要罗小黑同款") is True
    assert w.contains_banned("a Void traveler with a paper lantern") is False
