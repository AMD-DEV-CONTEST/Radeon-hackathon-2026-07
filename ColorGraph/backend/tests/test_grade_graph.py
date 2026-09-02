import pytest
from pydantic import ValidationError

from colorgraph.domain.grade_graph import (
    Keyframe,
    ParameterTrack,
    SpatialKind,
    SpatialScope,
    TimeRange,
)


def test_time_range_rejects_reverse_order() -> None:
    with pytest.raises(ValidationError):
        TimeRange(start_seconds=2, end_seconds=1)


def test_parameter_track_requires_sorted_unique_keyframes() -> None:
    with pytest.raises(ValidationError):
        ParameterTrack(
            parameter="exposure",
            keyframes=[
                Keyframe(time_seconds=2, value=0),
                Keyframe(time_seconds=1, value=1),
            ],
        )


def test_composite_scope_requires_expression() -> None:
    with pytest.raises(ValidationError):
        SpatialScope(kind=SpatialKind.COMPOSITE, target="protected_sky")
    with pytest.raises(ValidationError):
        SpatialScope(
            kind=SpatialKind.SEMANTIC,
            target="sky",
            expression="sky AND NOT mountain",
        )
