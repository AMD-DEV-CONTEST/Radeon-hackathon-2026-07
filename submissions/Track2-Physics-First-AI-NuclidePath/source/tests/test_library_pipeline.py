import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from nuclear_agent.demo import main as demo_main
from nuclear_agent.pipeline import run_library_scenario
from nuclear_agent.report_safety import ReportSafetyGate


ROOT = Path(__file__).parents[1]
ENTRY = json.loads((ROOT / "scenarios/library/conservative_uncertainty_v1.json").read_text())


def test_library_scenario_emits_validated_receptor_report_and_manifest(tmp_path):
    artifacts = run_library_scenario(ENTRY, tmp_path, samples=32, seed=17)

    assert set(artifacts) == {"report_json", "report_markdown", "receptors_svg", "validation_json", "manifest_json"}
    report = json.loads(artifacts["report_json"].read_text())
    assert report["scenario_library_version"] == "scenario-library-0.4"
    assert report["scenario_validation"]["valid"] is True
    assert report["report_safety_gate"]["passed"] is True
    assert ReportSafetyGate().assert_safe(report) == report["report_safety_gate"]
    assert len(report["virtual_receptors"]["receptors"]) == 2
    markdown = artifacts["report_markdown"].read_text()
    assert "Virtual receptor screening" in markdown
    assert "Sampled maximum" in markdown
    assert "no regulatory interpretation" in markdown
    assert artifacts["receptors_svg"].read_text().startswith("<svg")
    manifest = json.loads(artifacts["manifest_json"].read_text())
    for relative, expected in manifest["sha256"].items():
        assert hashlib.sha256((tmp_path / relative).read_bytes()).hexdigest() == expected


def test_cli_runs_a_versioned_library_entry(tmp_path):
    scenario_path = ROOT / "scenarios/library/conservative_uncertainty_v1.json"
    assert demo_main(["--scenario", str(scenario_path), "--output", str(tmp_path),
                      "--samples", "32", "--seed", "17"]) == 0
    assert (tmp_path / "scenario_validation.json").exists()
    assert (tmp_path / "virtual_receptors.svg").exists()
