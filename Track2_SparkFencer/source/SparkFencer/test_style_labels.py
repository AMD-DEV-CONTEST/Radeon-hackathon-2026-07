from fencing_analysis.analysis.style import _style_label


def _profile(**overrides):
    profile = {
        "aggression": 0.5,
        "territory": 0.5,
        "tempo": 0.7,
        # Both fencers can share this match-level distance preference.
        "distance": 0.25,
        # This is the new per-fencer signal used for the archetype decision.
        "distance_control": 0.2,
        "counter_ratio": 0.2,
    }
    profile.update(overrides)
    return profile


def test_distance_manager_uses_individual_opening_control_not_shared_distance():
    assert _style_label(_profile(distance_control=0.68)) == "机动控距型"
    assert _style_label(_profile(distance_control=0.32)) == "稳健均衡型"


def test_higher_priority_attack_and_counter_labels_are_preserved():
    assert _style_label(_profile(aggression=0.7, territory=0.65, distance_control=0.8)) == "进攻压迫型"
    assert _style_label(_profile(aggression=0.3, counter_ratio=0.6, distance_control=0.8)) == "防守反击型"
