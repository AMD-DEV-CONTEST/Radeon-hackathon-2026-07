import pytest
import torch
from pydantic import ValidationError

from colorgraph.domain.grade_graph import Interpolation, Keyframe, ParameterTrack
from colorgraph.grading.keyframes import evaluate_track, evaluate_track_batch


def test_linear_track_interpolation() -> None:
    track = ParameterTrack(
        parameter="exposure",
        interpolation=Interpolation.LINEAR,
        keyframes=[
            Keyframe(time_seconds=0, value=0),
            Keyframe(time_seconds=10, value=1),
        ],
    )
    assert evaluate_track(track, 5) == pytest.approx(0.5)
    assert evaluate_track(track, -1) == 0
    assert evaluate_track(track, 11) == 1


def test_velocity_limit_bounds_cubic_interpolation() -> None:
    track = ParameterTrack(
        parameter="exposure",
        interpolation=Interpolation.PCHIP,
        max_velocity=0.5,
        keyframes=[
            Keyframe(time_seconds=0, value=0),
            Keyframe(time_seconds=2, value=1),
            Keyframe(time_seconds=4, value=0),
        ],
    )
    assert evaluate_track(track, 0.5) <= 0.25 + 1e-6


def test_pchip_is_the_default_and_uses_nonuniform_keyframe_intervals() -> None:
    track = ParameterTrack(
        parameter="exposure",
        keyframes=[
            Keyframe(time_seconds=0, value=0),
            Keyframe(time_seconds=1, value=1),
            Keyframe(time_seconds=4, value=2),
        ],
    )

    assert track.interpolation == Interpolation.PCHIP
    assert evaluate_track(track, 2) == pytest.approx(446 / 297)


def test_saved_cubic_spline_tracks_keep_legacy_catmull_rom_response() -> None:
    track = ParameterTrack(
        parameter="exposure",
        interpolation=Interpolation.CUBIC,
        keyframes=[
            Keyframe(time_seconds=0, value=0),
            Keyframe(time_seconds=2, value=1),
            Keyframe(time_seconds=4, value=0),
        ],
    )

    assert evaluate_track(track, 0.5) == pytest.approx(0.2265625)


def test_pchip_keeps_monotone_plateaus_inside_their_data_range() -> None:
    track = ParameterTrack(
        parameter="temperature",
        keyframes=[
            Keyframe(time_seconds=0, value=1),
            Keyframe(time_seconds=0.5, value=1),
            Keyframe(time_seconds=2, value=2),
            Keyframe(time_seconds=5, value=2),
        ],
    )

    samples = [evaluate_track(track, index * 0.025) for index in range(201)]
    assert min(samples) == pytest.approx(1)
    assert max(samples) == pytest.approx(2)
    assert all(left <= right for left, right in zip(samples, samples[1:], strict=False))
    assert evaluate_track(track, 0.25) == pytest.approx(1)
    assert evaluate_track(track, 3.5) == pytest.approx(2)


def test_pchip_clamps_boundaries_and_hits_every_keyframe() -> None:
    track = ParameterTrack(
        parameter="exposure",
        keyframes=[
            Keyframe(time_seconds=1, value=-0.5),
            Keyframe(time_seconds=2.5, value=0.25),
            Keyframe(time_seconds=7, value=0.1),
        ],
    )

    assert evaluate_track(track, -10) == pytest.approx(-0.5)
    assert evaluate_track(track, 1) == pytest.approx(-0.5)
    assert evaluate_track(track, 2.5) == pytest.approx(0.25)
    assert evaluate_track(track, 7) == pytest.approx(0.1)
    assert evaluate_track(track, 20) == pytest.approx(0.1)


def test_pchip_has_continuous_first_derivative_at_internal_keys() -> None:
    track = ParameterTrack(
        parameter="exposure",
        keyframes=[
            Keyframe(time_seconds=0, value=-0.2),
            Keyframe(time_seconds=1, value=0.6),
            Keyframe(time_seconds=4, value=1.1),
            Keyframe(time_seconds=5.5, value=0.4),
        ],
    )
    epsilon = 1e-5

    for timestamp in (1.0, 4.0):
        value = evaluate_track(track, timestamp)
        left_derivative = (value - evaluate_track(track, timestamp - epsilon)) / epsilon
        right_derivative = (evaluate_track(track, timestamp + epsilon) - value) / epsilon
        assert left_derivative == pytest.approx(right_derivative, abs=2e-5)


def test_parameter_track_rejects_duplicate_keyframe_times() -> None:
    with pytest.raises(ValidationError, match="cannot share the same time_seconds"):
        ParameterTrack(
            parameter="exposure",
            keyframes=[
                Keyframe(time_seconds=1, value=0),
                Keyframe(time_seconds=1, value=1),
            ],
        )


@pytest.mark.parametrize(
    "interpolation",
    [
        Interpolation.HOLD,
        Interpolation.LINEAR,
        Interpolation.PCHIP,
        Interpolation.CUBIC,
    ],
)
def test_batch_track_evaluation_matches_scalar_reference(
    interpolation: Interpolation,
) -> None:
    track = ParameterTrack(
        parameter="exposure",
        interpolation=interpolation,
        max_velocity=1.25,
        max_acceleration=2.5,
        keyframes=[
            Keyframe(time_seconds=0.2, value=-0.3),
            Keyframe(time_seconds=1.1, value=0.8),
            Keyframe(time_seconds=2.7, value=0.15),
            Keyframe(time_seconds=4.0, value=0.55),
        ],
    )
    timestamps = [-1.0, *[index * 0.037 for index in range(130)], 7.0]

    batch = evaluate_track_batch(track, timestamps)
    reference = [evaluate_track(track, timestamp) for timestamp in timestamps]

    assert batch.dtype == torch.float64
    assert batch.tolist() == pytest.approx(reference, rel=0, abs=2e-15)


def test_batch_track_evaluation_preserves_shape_and_single_keyframe() -> None:
    track = ParameterTrack(
        parameter="contrast",
        keyframes=[Keyframe(time_seconds=2.0, value=0.25)],
    )
    timestamps = torch.tensor([[0.0, 2.0], [3.0, 8.0]])

    evaluated = evaluate_track_batch(track, timestamps)

    assert evaluated.shape == timestamps.shape
    assert evaluated.tolist() == [[0.25, 0.25], [0.25, 0.25]]
