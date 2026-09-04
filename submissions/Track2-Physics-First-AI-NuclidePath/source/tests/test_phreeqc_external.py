import json
import os
from pathlib import Path
import re
import shutil

import pytest

from nuclear_agent.phreeqc_qualification import (
    BannerMatcher, QualificationConfig,
    normalize_selected_output, parse_selected_output, run_qualification,
    sha256_file, stage_qualification, write_qualification_replay,
)
from nuclear_agent.replay import ReplayVerificationError, verify_bundle
from nuclear_agent.phreeqc_scenario import (
    compile_phreeqc_scenario, run_phreeqc_scenario, write_scenario_replay,
)


INPUT_SHA256 = "bff24cafb046ebcb0fd54263f6617fd3bddea1fe21da079d9e13af5ebecdbcc5"
SELECTED_SHA256 = "d83b5148c6350aaac58c18ba5cffa4b8837b0254f7d8cac4a8d45c7681d6cfec"
DATABASE_SHA256 = "5b80d45c989cd1db7aab485e198321ba550d5902be8097c8be26d85ba03da278"
BANNER = "PHREEQC 3.8.9, October 13, 2025"


def _required_environment():
    names = (
        "PHREEQC_EXECUTABLE", "PHREEQC_DATABASE",
        "PHREEQC_EXECUTABLE_SHA256", "PHREEQC_DATABASE_SHA256",
    )
    missing = [name for name in names if not os.environ.get(name)]
    assert not missing, "missing required external-solver environment: " + ", ".join(missing)
    return {name: os.environ[name] for name in names}


@pytest.mark.external_solver
def test_real_phreeqc_example2_is_replayable_but_not_a_scientific_oracle(request, tmp_path):
    if not request.config.getoption("--run-external-solver"):
        pytest.skip("real external PHREEQC solver is not configured; use --run-external-solver")
    environment = _required_environment()
    executable = Path(environment["PHREEQC_EXECUTABLE"])
    database = Path(environment["PHREEQC_DATABASE"])
    for path in (executable, database):
        assert path.is_absolute() and path.is_file() and not path.is_symlink()
    executable_digest = environment["PHREEQC_EXECUTABLE_SHA256"]
    database_digest = environment["PHREEQC_DATABASE_SHA256"]
    assert re.fullmatch(r"[0-9a-f]{64}", executable_digest)
    assert re.fullmatch(r"[0-9a-f]{64}", database_digest)
    assert sha256_file(executable) == executable_digest
    assert database_digest == DATABASE_SHA256 == sha256_file(database)
    fixture = Path(__file__).parent / "fixtures/phreeqc/example2.pqi"
    expected_selected = fixture.with_name("example2-selected-output.txt")
    assert sha256_file(fixture) == INPUT_SHA256
    assert sha256_file(expected_selected) == SELECTED_SHA256

    runs = []
    for name in ("run-one", "run-two"):
        work = tmp_path / name
        work.mkdir()
        config = QualificationConfig(
            executable, database, fixture, work, executable_digest, database_digest,
            INPUT_SHA256, BannerMatcher(re.escape(BANNER)), 30.0,
        )
        staged = stage_qualification(config)
        result = run_qualification(staged)
        assert result.banner == BANNER
        assert result.process.exit_status == 0 and not result.process.timed_out
        selected = result.working_directory / "ex2.sel"
        assert result.output_hashes["ex2.sel"] == SELECTED_SHA256 == sha256_file(selected)
        parsed = result.parsed_selected_output
        assert sum(row.state == "i_soln" for row in parsed.rows) == 1
        assert sum(row.state == "react" for row in parsed.rows) == 51
        runs.append((staged, result, parsed, selected.read_bytes()))

    assert runs[0][3] == runs[1][3]
    assert normalize_selected_output(runs[0][2]) == normalize_selected_output(runs[1][2])
    bundle = write_qualification_replay(tmp_path / "bundle-one", *runs[0][:2],
        "No independent machine-readable numerical oracle is available.")
    bundle_two = write_qualification_replay(tmp_path / "bundle-two", *runs[1][:2],
        "No independent machine-readable numerical oracle is available.")
    payload_one = json.loads((bundle.path / "results.json").read_text())
    payload_two = json.loads((bundle_two.path / "results.json").read_text())
    assert payload_one == payload_two
    classification = payload_one["qualification_content"]["classification"]
    assert classification["process_qualified"] and classification["scientific_input_qualified"]
    assert not classification["scientific_result_qualified"]
    assert verify_bundle(bundle.path, expected_manifest_sha256=bundle.manifest_sha256).valid
    tampered = tmp_path / "tampered-bundle"
    shutil.copytree(bundle.path, tampered)
    payload = json.loads((tampered / "results.json").read_text())
    payload["qualification_content"]["classification"]["process_qualified"] = False
    (tampered / "results.json").write_text(json.dumps(payload))
    with pytest.raises(ReplayVerificationError):
        verify_bundle(tampered)


@pytest.mark.external_solver
def test_real_phreeqc_cs_k_scenario_projection_is_replayable(request, tmp_path):
    if not request.config.getoption("--run-external-solver"):
        pytest.skip("real external PHREEQC solver is not configured; use --run-external-solver")
    environment = _required_environment()
    executable = Path(environment["PHREEQC_EXECUTABLE"])
    database = Path(environment["PHREEQC_DATABASE"])
    scenario_path = Path(__file__).parent / "fixtures/phreeqc/cs137_exchange_scenario.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    # Keep the external syntax/integration check short; the compiler itself
    # derives the shift count from the declared evaluation times.
    scenario["transport"]["evaluation_times_s"] = [0.0, 10_000_000.0, 20_000_000.0]
    compiled = compile_phreeqc_scenario(scenario)
    run_root = tmp_path / "scenario-root"
    run_root.mkdir()
    run = run_phreeqc_scenario(
        compiled,
        executable=executable,
        database=database,
        executable_sha256=environment["PHREEQC_EXECUTABLE_SHA256"],
        database_sha256=environment["PHREEQC_DATABASE_SHA256"],
        working_directory=run_root,
    )
    assert run.process.exit_status == 0
    assert any(row.state == "transp" for row in run.selected_output.rows)
    assert any(row.cs_exchange_mol_kgw >= 0.0 for row in run.selected_output.rows)
    bundle = write_scenario_replay(tmp_path / "scenario-bundle", run)
    assert verify_bundle(bundle.path).valid
