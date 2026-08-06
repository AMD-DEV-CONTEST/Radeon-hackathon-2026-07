from pathlib import Path

import pytest

from xenix.exceptions import ValidationError
from xenix.services.analysis_profile import AnalysisProfileService, ProfileDatasetInput
from xenix.services.tabular import TabularRuntimeError


def _write_mixed_csv(tmp_path: Path) -> Path:
    source = tmp_path / "sales.csv"
    source.write_text(
        "\n".join(
            [
                "region,amount,score,active,date",
                "North,10,1.5,1,2026-01-01",
                "South,20,2.5,0,2026-01-02",
                "North,,2.0,1,2026-01-03",
                "South,20,3.0,0,2026-01-04",
                "South,20,3.0,0,2026-01-04",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return source


def test_analysis_profile_service_builds_bounded_markdown_report(tmp_path: Path) -> None:
    source = _write_mixed_csv(tmp_path)

    result = AnalysisProfileService().profile_dataset(
        ProfileDatasetInput(
            source_path=str(source.resolve()),
            dataset_name="Sales",
            target_columns=["amount"],
            top_n=2,
            correlation_column_limit=3,
        )
    )

    assert result.profile["basic_info"] == {
        "row_count": 5,
        "column_count": 5,
        "duplicate_row_count": 1,
    }
    assert result.profile["field_type_summary"]["continuous_numeric"]["columns"] == ["amount", "score"]
    assert result.profile["field_type_summary"]["binary"]["columns"] == ["active"]
    assert result.profile["field_type_summary"]["non_numeric"]["columns"] == ["region"]
    assert result.profile["field_type_summary"]["datetime"]["columns"] == ["date"]
    assert result.profile["datetime_statistics"] == [
        {
            "column": "date",
            "min": "2026-01-01T00:00:00",
            "max": "2026-01-04T00:00:00",
            "span_days": 3,
        }
    ]
    assert result.profile["target_group_statistics"]
    assert "# Dataset profile: Sales" in result.markdown
    assert "| Duplicate rows | 1 |" in result.markdown
    assert "## Numeric statistics" in result.markdown
    assert "## Target group statistics" in result.markdown


def test_analysis_profile_service_surfaces_structured_runtime_error(
    monkeypatch,
    tmp_path: Path,
    caplog,
) -> None:
    source = _write_mixed_csv(tmp_path)

    def fail_load(*_args, **_kwargs):
        raise TabularRuntimeError(
            "Polars failed to read the dataset file.",
            error_details={
                "engine": "polars",
                "phase": "read",
                "package_versions": {
                    "polars": "1.42.1",
                    "polars-runtime-32": "1.41.2",
                },
            },
        )

    monkeypatch.setattr("xenix.services.analysis_profile.load_tabular_frame", fail_load)

    with caplog.at_level("ERROR", logger="xenix.services.analysis_profile"):
        with pytest.raises(ValidationError) as exc_info:
            AnalysisProfileService().profile_dataset(
                ProfileDatasetInput(
                    source_path=str(source.resolve()),
                    dataset_name="Sales",
                )
            )

    assert "Dataset profile could not load the tabular runtime" in caplog.text
    assert exc_info.value.error_code == "tabular_runtime_unavailable"
    assert exc_info.value.error_details["operation"] == "analysis.profile"
    assert exc_info.value.error_details["tabular"]["package_versions"]["polars-runtime-32"] == "1.41.2"
    assert any("data.query" in hint for hint in exc_info.value.repair_hints)
    assert exc_info.value.retryable is True
