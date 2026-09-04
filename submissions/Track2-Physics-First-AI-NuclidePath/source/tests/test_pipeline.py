import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from nuclear_agent.analysis import ParameterRange
from nuclear_agent.demo import build_parser, main as demo_main, validate_llm_base_url
from nuclear_agent.pipeline import run_full_demo
from nuclear_agent.workflow import DeterministicWorkflowPlanner, LocalWorkflowPlanner


def case():
    return {
        "site": {
            "site_id": "pipeline-site",
            "event_type": "hypothetical_subsurface_release",
            "radionuclide": "Cs-137",
            "release_pathway": "groundwater",
            "source_description": "Hypothetical maintained boundary release",
            "data_provenance": "demonstration",
            "data_classification": "public",
        },
        "transport": {
            "scenario_id": "pipeline-demo",
            "initial_concentration_bq_m3": 1.0e6,
            "distance_m": 100.0,
            "evaluation_times_s": [0.0, 5.0e9, 1.0e10],
            "distribution_coefficient_m3_kg": 0.2,
            "groundwater_velocity_m_s": 1.0e-5,
            "potassium_mg_l": 20.0,
        },
        "query": "potassium competition cesium sorption retardation",
    }


def ranges():
    return {
        "distribution_coefficient_m3_kg": ParameterRange(
            0.05, 5.0, "log_uniform", "literature-range", "IAEA TECDOC-2095"
        ),
        "potassium_mg_l": ParameterRange(
            0.0, 40.0, "uniform", "demonstration-range", "sensitivity scenario"
        ),
    }


def test_full_pipeline_creates_reproducible_submission_artifacts(tmp_path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "source.md").write_text(
        "# Cesium source\nPotassium competition affects cesium sorption and retardation.\n"
        "Source: https://example.org/source\n"
    )
    output = tmp_path / "output"

    artifacts = run_full_demo(
        case(),
        output,
        knowledge_dir=knowledge,
        parameter_ranges=ranges(),
        uncertainty_samples=64,
        seed=7,
        session_id="pipeline-session",
    )

    required = {
        "report_json",
        "report_markdown",
        "concentration_svg",
        "workflow_json",
        "sensitivity_json",
        "sensitivity_csv",
        "uncertainty_json",
        "uncertainty_csv",
        "uncertainty_svg",
        "manifest_json",
        "memory_jsonl",
    }
    assert set(artifacts) == required
    assert all(path.exists() for path in artifacts.values())

    workflow = json.loads(artifacts["workflow_json"].read_text())
    assert all(workflow["capabilities"].values())
    report = json.loads(artifacts["report_json"].read_text())
    assert report["agent_workflow"]["session_id"] == "pipeline-session"
    assert report["uncertainty"]["samples"] == 64
    assert "Local knowledge citations" in artifacts["report_markdown"].read_text()
    uncertainty_svg = artifacts["uncertainty_svg"].read_text()
    assert "P05" in uncertainty_svg and "P50" in uncertainty_svg and "P95" in uncertainty_svg
    assert "Travel time (years)" in uncertainty_svg

    manifest = json.loads(artifacts["manifest_json"].read_text())
    for relative_path, expected_hash in manifest["sha256"].items():
        actual = hashlib.sha256((output / relative_path).read_bytes()).hexdigest()
        assert actual == expected_hash

    with artifacts["sensitivity_csv"].open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    baseline_rows = [row for row in rows if row["case"] == "baseline"]
    assert baseline_rows and all(row["value"] for row in baseline_rows)

    repeated = run_full_demo(
        case(),
        tmp_path / "repeated",
        knowledge_dir=knowledge,
        parameter_ranges=ranges(),
        uncertainty_samples=64,
        seed=7,
        session_id="pipeline-session",
    )
    assert all(
        artifacts[name].read_bytes() == repeated[name].read_bytes()
        for name in artifacts
    )


def test_cli_runs_full_private_agent_pipeline(tmp_path):
    case_path = tmp_path / "case.json"
    ranges_path = tmp_path / "ranges.json"
    knowledge = tmp_path / "knowledge"
    output = tmp_path / "cli-output"
    knowledge.mkdir()
    case_path.write_text(json.dumps(case()))
    ranges_path.write_text(
        json.dumps({name: value.to_dict() for name, value in ranges().items()})
    )
    (knowledge / "source.md").write_text(
        "# Cesium source\nPotassium competition affects cesium sorption.\n"
    )

    exit_code = demo_main(
        [
            "--scenario",
            str(case_path),
            "--output",
            str(output),
            "--knowledge-dir",
            str(knowledge),
            "--uncertainty-ranges",
            str(ranges_path),
            "--samples",
            "32",
            "--session-id",
            "cli-session",
        ]
    )

    assert exit_code == 0
    assert (output / "workflow.json").exists()
    assert (output / "uncertainty.json").exists()
    assert build_parser().get_default("scenario").is_file()
    assert validate_llm_base_url("http://127.0.0.1:8000/v1") == "http://127.0.0.1:8000/v1"
    with pytest.raises(ValueError, match="loopback"):
        validate_llm_base_url("https://example.org/v1")
    with pytest.raises(ValueError, match="credentials"):
        validate_llm_base_url("http://user:secret@127.0.0.1:8000/v1")
    with pytest.raises(ValueError, match="credentials"):
        validate_llm_base_url("http://@127.0.0.1:8000/v1")
    with pytest.raises(ValueError, match="credentials"):
        validate_llm_base_url("http://:@127.0.0.1:8000/v1")


def test_offline_and_llm_planned_pipelines_are_physically_identical(tmp_path):
    class FakePrivateClient:
        def chat(self, messages):
            assert "local-only" in messages[0]["content"]
            return (
                '["validate_permissions", "site_agent", "knowledge_retrieval", '
                '"environment_agent", "store_memory", "synthesize_report"]'
            )

    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "source.md").write_text(
        "# Cesium source\nPotassium competition affects cesium sorption.\n"
    )
    parity_case = case()
    parity_case["transport"]["potassium_mg_l"] = 30.0
    offline = run_full_demo(
        parity_case,
        tmp_path / "offline",
        knowledge_dir=knowledge,
        parameter_ranges=ranges(),
        uncertainty_samples=32,
        seed=42,
        session_id="offline-parity",
    )
    llm = run_full_demo(
        parity_case,
        tmp_path / "llm",
        knowledge_dir=knowledge,
        parameter_ranges=ranges(),
        uncertainty_samples=32,
        seed=42,
        session_id="llm-parity",
        planner=LocalWorkflowPlanner(FakePrivateClient()),
    )

    offline_report = json.loads(offline["report_json"].read_text())
    llm_report = json.loads(llm["report_json"].read_text())
    assert offline_report["agent_workflow"]["tool_result"] == llm_report["agent_workflow"]["tool_result"]
    assert offline_report["runs"] == llm_report["runs"]
    assert offline_report["sensitivity"] == llm_report["sensitivity"]
    assert offline_report["uncertainty"] == llm_report["uncertainty"]
    assert offline_report["comparison"]["potassium_levels_mg_l"] == [0.0, 30.0]
    assert offline_report["execution"]["planner"] == "deterministic"
    assert llm_report["execution"] == {
        "mode": "llm-planned-local",
        "planner": "local_llm",
        "physics_source": "simulate_transport",
        "llm_required": True,
    }
    assert "plan" not in llm_report["runs"][0]
    assert "deterministic_tool_plan" in llm_report["runs"][0]


def test_pipeline_rejects_unclassified_planner_provenance(tmp_path):
    class UnclassifiedPlanner:
        def plan(self, payload):
            return [
                "validate_permissions",
                "site_agent",
                "knowledge_retrieval",
                "environment_agent",
                "store_memory",
                "synthesize_report",
            ]

    class SpoofedDeterministicPlanner(DeterministicWorkflowPlanner):
        def plan(self, payload):
            return super().plan(payload)

    class SpoofedLocalPlanner(LocalWorkflowPlanner):
        def __init__(self):
            pass

        def plan(self, payload):
            return [
                "validate_permissions",
                "site_agent",
                "knowledge_retrieval",
                "environment_agent",
                "store_memory",
                "synthesize_report",
            ]

    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "source.md").write_text("# Local source\nCesium screening.\n")
    for candidate in (
        UnclassifiedPlanner(),
        SpoofedDeterministicPlanner(),
        SpoofedLocalPlanner(),
    ):
        with pytest.raises(ValueError, match="classified planner"):
            run_full_demo(
                case(),
                tmp_path / type(candidate).__name__,
                knowledge_dir=knowledge,
                parameter_ranges=ranges(),
                uncertainty_samples=20,
                planner=candidate,
            )


def test_full_pipeline_compiles_opt_in_phreeqc_bridge(tmp_path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "source.md").write_text(
        "# Cs/K source\nCompetitive exchange requires calibration.\n"
    )
    demo_case = case()
    demo_case["transport"].update({
        "bulk_density_kg_m3": 1700.0,
        "porosity": 0.35,
        "dispersion_m2_s": 1.0e-5,
        "half_life_years": 30.018,
        "competition_coefficient_l_mg": 0.01,
    })
    demo_case["phreeqc"] = {
        "water_density_kg_m3": 1000.0,
        "water": {
            "units": "mmol/kgw",
            "pH": 7.0,
            "pe": 12.0,
            "temperature_c": 25.0,
            "ions_mmol_kgw": {"K": 0.511, "Na": 1.0, "Ca": 0.6, "Cl": 2.711},
        },
        "exchange": {
            "cec_mmolc_kg": 100.0,
            "log_k": {"Cs": 1.2, "K": 0.4, "Na": 0.0, "Ca": 0.2},
        },
        "discretization": {"cells": 20},
        "provenance": {
            "water": "synthetic demonstration",
            "cec": "synthetic demonstration",
            "selectivity": "synthetic demonstration",
        },
    }
    output = tmp_path / "output"
    artifacts = run_full_demo(
        demo_case,
        output,
        knowledge_dir=knowledge,
        parameter_ranges=ranges(),
        uncertainty_samples=20,
        seed=7,
        session_id="phreeqc-bridge",
    )

    assert {"phreeqc_input", "phreeqc_metadata"} <= set(artifacts)
    assert "SOLUTION_MASTER_SPECIES" in artifacts["phreeqc_input"].read_text()
    report = json.loads(artifacts["report_json"].read_text())
    bridge = report["phreeqc_bridge"]
    assert bridge["status"] == "compiled-not-run"
    assert bridge["scientific_result_qualified"] is False
    assert bridge["cells"] == 20
    metadata = json.loads(artifacts["phreeqc_metadata"].read_text())
    assert metadata["schema"] == "nuclidepath-phreeqc-chemistry-2"
    assert metadata["metadata"]["canonical_empirical_model"]["available"] is True
    markdown = artifacts["report_markdown"].read_text()
    assert "PHREEQC chemistry bridge" in markdown
    manifest = json.loads(artifacts["manifest_json"].read_text())
    for name in ("phreeqc-input.pqi", "phreeqc-metadata.json"):
        assert name in manifest["sha256"]
