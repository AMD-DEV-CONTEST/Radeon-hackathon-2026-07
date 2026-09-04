import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from nuclear_agent.scenario_library import ScenarioLibrary


ROOT = Path(__file__).parents[1]


def test_packaged_library_loads_three_versioned_demonstration_families():
    library = ScenarioLibrary.from_directory(ROOT / "scenarios" / "library")

    assert library.version == "scenario-library-0.4"
    assert library.ids() == (
        "cs137-baseline-1d-v1",
        "cs137-conservative-uncertainty-v1",
        "cs137-potassium-stress-v1",
    )
    for scenario_id in library.ids():
        entry = library.get(scenario_id)
        assert entry["schema_version"] == "nuclidepath-scenario-1.0"
        assert entry["scenario_classification"] == "demonstration"
        assert entry["parameter_sources"]
        assert entry["expected_qualitative_behavior"]
        assert entry["transport"]["scenario_id"] == scenario_id


def test_source_and_installed_package_scenarios_are_byte_for_byte_identical():
    source = ROOT / "scenarios" / "library"
    packaged = ROOT / "src" / "nuclear_agent" / "data" / "scenarios" / "library"
    assert [path.name for path in source.glob("*.json")] == [path.name for path in packaged.glob("*.json")]
    for source_path in source.glob("*.json"):
        assert source_path.read_bytes() == (packaged / source_path.name).read_bytes()


def test_library_rejects_duplicate_scenario_ids(tmp_path):
    payload = """{
      "schema_version": "nuclidepath-scenario-1.0",
      "library_version": "scenario-library-0.4",
      "scenario_classification": "demonstration",
      "parameter_sources": {"x": {"classification": "demonstration", "source": "demo"}},
      "expected_qualitative_behavior": ["demonstration only"],
      "transport": {"scenario_id": "duplicate"}
    }"""
    (tmp_path / "a.json").write_text(payload)
    (tmp_path / "b.json").write_text(payload)

    with pytest.raises(ValueError, match="duplicate scenario_id"):
        ScenarioLibrary.from_directory(tmp_path)
