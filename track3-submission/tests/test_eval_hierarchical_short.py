import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "eval_hierarchical_short", ROOT / "scripts/eval_hierarchical_short.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def row(distance, ball_x, latency, reward, fallen=False, scored=False):
    return {"distance_m": distance, "ball_x_m": ball_x, "inference_s": latency,
            "reward": reward, "fallen": fallen, "scored": scored}


def test_summary_metrics_and_event_edges():
    result = MODULE.summarize([
        row(2.0, 0.0, .010, 1.0),
        row(1.0, 0.2, .020, 2.0, fallen=True),
        row(0.5, 0.6, .030, -1.0, fallen=True, scored=True),
    ])
    assert result["events"]["falls"] == {"status": "observed", "count": 1}
    assert result["events"]["goals"] == {"status": "observed", "count": 1}
    assert result["base_to_ball_m"]["status"] == "observed"
    assert result["base_to_ball_m"]["mean"] == pytest.approx(7 / 6)
    assert result["ball_x_progress_m"]["net"] == pytest.approx(.6)
    assert result["inference"]["latency_mean_ms"] == pytest.approx(20)
    assert result["inference"]["latency_p95_ms"] == pytest.approx(30)
    assert result["inference"]["fps"] == pytest.approx(50)
    assert result["reward"] == pytest.approx(
        {"sum": 2, "mean": 2 / 3, "min": -1, "max": 2, "final": -1})


def test_missing_explicit_extra_is_unknown_not_inferred():
    sample = row(.1, 8.0, .01, 0.0)
    sample["fallen"] = None
    sample["scored"] = None
    result = MODULE.summarize([sample])
    assert result["events"]["falls"]["status"] == "unknown"
    assert result["events"]["falls"]["count"] is None
    assert result["events"]["goals"]["status"] == "unknown"
    assert result["events"]["goals"]["count"] is None


def test_extra_signal_supports_nested_tensor_like_values():
    found, value = MODULE.extra_signal({"soccer": {"fallen": [True]}}, "fallen")
    assert found is True
    assert value is True
    assert MODULE.extra_signal({"episode": {}}, "scored") == (False, False)


def test_parser_defaults_are_canonical_models():
    args = MODULE.build_parser().parse_args([])
    assert args.controller == "onnx"
    assert args.steps == 100
    assert args.seed == 42
    assert args.onnx == ROOT / "models/chase_v8_policy.onnx"
    assert args.walk_model == ROOT / "models/pretrained/t1_walk.pt"


class FakeInput:
    name = "policy_obs"


class FakeSession:
    def __init__(self):
        self.received = None

    def get_inputs(self):
        return [FakeInput()]

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def run(self, outputs, feed):
        self.received = feed["policy_obs"].copy()
        return [[[.2, -.1, .01]]]


def test_onnx_receives_environment_observation_element_for_element():
    session = FakeSession()
    observation = [i + .25 for i in range(19)]
    action = MODULE.onnx_action(session, observation)
    assert session.received.shape == (1, 19)
    assert session.received[0].tolist() == pytest.approx(observation)
    assert action.tolist() == pytest.approx([.2, -.1, .01])
    assert session.get_providers() == ["CPUExecutionProvider"]


def test_terminal_state_is_used_and_missing_terminal_does_not_pollute_metrics():
    terminal = MODULE.terminal_positions({
        "terminal_state": {"base_pos": [[1, 2, .5]], "ball_pos": [[4, 6, .1]]}})
    assert terminal[0].tolist() == [1, 2, .5]
    assert terminal[1].tolist() == [4, 6, .1]
    assert MODULE.terminal_positions({"episode": {}}) is None

    good = row(1, 0, .01, 0)
    skipped = row(None, None, .01, 0, fallen=True, scored=True)
    result = MODULE.summarize([good, skipped], initial_ball_x=-1)
    assert result["base_to_ball_m"]["status"] == "partial_unknown"
    assert result["base_to_ball_m"]["observed_steps"] == 1
    assert result["base_to_ball_m"]["final"] is None
    assert result["base_to_ball_m"]["last_observed"] == 1
    assert result["base_to_ball_m"]["last_observed_step"] == 1
    assert result["ball_x_progress_m"]["final"] is None
    assert result["ball_x_progress_m"]["net"] is None
    assert result["ball_x_progress_m"]["last_observed_net"] == 1


def test_termination_reason_prefers_explicit_and_never_guesses_from_pose():
    assert MODULE.termination_reason({"termination_reason": "solver_error"}) == "solver_error"
    assert MODULE.termination_reason({"scored": [True]}) == "scored"
    assert MODULE.termination_reason({"time_outs": [1]}) == "time_out"
    assert MODULE.termination_reason({}) == "unknown"


def test_reward_component_contract_and_aggregation_preserve_unknowns():
    extras = {"reward_components": {
        "approach_ball": {"raw": [.25], "weighted": [.5]},
        "fall_penalty": {"raw": [0.0], "weighted": [-0.0]},
    }}
    parsed = MODULE.reward_components(extras)
    assert parsed == {
        "approach_ball": {"raw": .25, "weighted": .5},
        "fall_penalty": {"raw": 0.0, "weighted": 0.0},
    }

    first = row(1, 0, .01, .5)
    first["reward_components"] = parsed
    second = row(.5, .2, .02, 1.0)
    second["reward_components"] = {
        "approach_ball": {"raw": .5, "weighted": 1.0}}
    result = MODULE.summarize([first, second])["reward_components"]
    assert result["approach_ball"] == {
        "status": "observed", "observed_steps": 2,
        "raw": {"mean": .375, "sum": .75, "min": .25, "max": .5},
        "weighted": {"mean": .75, "sum": 1.5, "min": .5, "max": 1.0},
    }
    assert result["fall_penalty"]["status"] == "partial_unknown"
    assert result["fall_penalty"]["observed_steps"] == 1
    assert result["ball_control"] == {
        "status": "unknown", "observed_steps": 0,
        "raw": {"mean": None, "sum": None, "min": None, "max": None},
        "weighted": {"mean": None, "sum": None, "min": None, "max": None},
    }


def test_missing_reward_component_contract_is_unknown():
    assert MODULE.reward_components({}) is None
    result = MODULE.summarize([row(1, 0, .01, 0.0)])
    assert all(component["status"] == "unknown"
               for component in result["reward_components"].values())
