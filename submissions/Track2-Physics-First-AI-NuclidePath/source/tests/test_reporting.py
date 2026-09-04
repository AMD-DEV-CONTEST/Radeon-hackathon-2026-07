import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from nuclear_agent.reporting import generate_demo_artifacts


SCENARIO = {
    "scenario_id": "report-demo",
    "initial_concentration_bq_m3": 1.0e6,
    "distance_m": 100.0,
    "evaluation_times_s": [0.0, 5.0e9, 1.0e10],
    "distribution_coefficient_m3_kg": 0.2,
    "groundwater_velocity_m_s": 1.0e-5,
    "potassium_mg_l": 20.0,
}


def test_generate_demo_artifacts_writes_json_markdown_and_svg(tmp_path):
    artifacts = generate_demo_artifacts(SCENARIO, tmp_path, potassium_levels=(0.0, 20.0))

    assert set(artifacts) == {"json", "markdown", "svg"}
    assert all(path.exists() for path in artifacts.values())

    report = json.loads(artifacts["json"].read_text())
    assert report["report_version"] == "report-0.2"
    assert report["execution"]["mode"] == "offline"
    assert report["scenario"]["potassium_mg_l"] == 20.0
    assert [run["potassium_mg_l"] for run in report["runs"]] == [0.0, 20.0]
    assert report["runs"][0]["effective_kd_m3_kg"] > report["runs"][1]["effective_kd_m3_kg"]
    assert report["runs"][0]["retardation_factor"] > report["runs"][1]["retardation_factor"]
    assert "sampled_max_concentration_bq_m3" in report["runs"][0]
    assert "peak_concentration_bq_m3" not in report["runs"][0]
    assert len(report["runs"][0]["points"]) == 3

    markdown = artifacts["markdown"].read_text()
    assert "K+ = 0 mg/L" in markdown
    assert "K+ = 20 mg/L" in markdown
    assert "not validated for operational radiological assessment" in markdown

    svg = artifacts["svg"].read_text()
    assert svg.startswith("<svg")
    assert "K+ = 0 mg/L" in svg
    assert "K+ = 20 mg/L" in svg
    assert "Time (years)" in svg


def test_generate_demo_artifacts_rejects_empty_potassium_comparison(tmp_path):
    try:
        generate_demo_artifacts(SCENARIO, tmp_path, potassium_levels=())
    except ValueError as exc:
        assert "potassium" in str(exc)
    else:
        raise AssertionError("empty potassium comparison should fail")
