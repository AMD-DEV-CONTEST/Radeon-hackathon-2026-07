import torch

from reward import compute_reward_components


def test_acceptance_components_use_production_formulas_and_weights():
    obs = {
        "dist_to_ball": torch.tensor([0.2, 0.5]),
        "prev_dist_to_ball": torch.tensor([0.3, 0.4]),
        "ball_goal_dist": torch.tensor([4.0, 5.5]),
        "prev_ball_goal_dist": torch.tensor([4.25, 5.0]),
        "min_foot_dist": torch.tensor([0.1, 0.2]),
        "scored": torch.tensor([True, False]),
        "fallen": torch.tensor([False, True]),
    }
    weights = {
        "_ball_radius": 0.11,
        "approach_ball": 2.0,
        "ball_control": 3.0,
        "ball_contact": 4.0,
        "ball_progress": 5.0,
        "goal_scored": 6.0,
        "fall_penalty": -7.0,
    }

    components = compute_reward_components(obs, weights, "chase_hl")

    assert set(components) == set(weights) - {"_ball_radius"}
    assert torch.allclose(components["approach_ball"]["raw"], torch.tanh(torch.tensor([0.1, -0.1])))
    assert torch.allclose(
        components["ball_control"]["raw"],
        torch.exp(-torch.clamp(obs["dist_to_ball"] - 0.11, min=0.0) * 3.0),
    )
    assert torch.equal(components["ball_contact"]["raw"], torch.tensor([1.0, 0.0]))
    assert torch.equal(components["ball_progress"]["raw"], torch.tensor([0.25, -0.5]))
    assert torch.equal(components["goal_scored"]["raw"], torch.tensor([1.0, 0.0]))
    assert torch.equal(components["fall_penalty"]["raw"], torch.tensor([0.0, 1.0]))
    for name, component in components.items():
        assert torch.allclose(component["weighted"], weights[name] * component["raw"])


def test_inactive_components_are_omitted_not_fabricated_as_zero():
    obs = {"fallen": torch.tensor([False])}
    result = compute_reward_components(obs, {"fall_penalty": -1.0}, "balance_hl")
    assert set(result) == {"fall_penalty"}

