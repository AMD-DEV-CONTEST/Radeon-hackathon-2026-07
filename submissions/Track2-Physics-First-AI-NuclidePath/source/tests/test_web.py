import json
import sys
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from nuclear_agent.web import DashboardApplication, create_server, validate_host


def fixture_files(tmp_path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "science.md").write_text(
        "# Cesium science\nPotassium competition affects cesium sorption.\n"
    )
    case = {
        "site": {
            "site_id": "web-demo",
            "event_type": "hypothetical_release",
            "radionuclide": "Cs-137",
            "release_pathway": "groundwater",
            "source_description": "Hypothetical pulse",
            "data_provenance": "demonstration",
            "data_classification": "public",
        },
        "transport": {
            "scenario_id": "web-demo",
            "initial_concentration_bq_m3": 1.0e6,
            "distance_m": 100.0,
            "evaluation_times_s": [0.0, 5.0e9, 1.0e10],
            "distribution_coefficient_m3_kg": 0.2,
            "groundwater_velocity_m_s": 1.0e-5,
            "potassium_mg_l": 20.0,
        },
        "query": "potassium cesium sorption",
    }
    ranges = {
        "potassium_mg_l": {
            "low": 0.0,
            "high": 40.0,
            "distribution": "uniform",
            "classification": "demonstration-range",
            "source": "demo",
        }
    }
    case_path = tmp_path / "case.json"
    ranges_path = tmp_path / "ranges.json"
    case_path.write_text(json.dumps(case))
    ranges_path.write_text(json.dumps(ranges))
    return knowledge, case_path, ranges_path


def test_dashboard_http_api_runs_full_pipeline(tmp_path):
    knowledge, case_path, ranges_path = fixture_files(tmp_path)
    app = DashboardApplication(
        scenario_path=case_path,
        knowledge_dir=knowledge,
        ranges_path=ranges_path,
        output_root=tmp_path / "runs",
        uncertainty_samples=32,
    )
    server = create_server(app, host="127.0.0.1", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        health = json.load(urlopen(base + "/api/health"))
        assert health == {"status": "ok", "mode": "local-only"}
        default_case = json.load(urlopen(base + "/api/default-case"))
        request = Request(
            base + "/api/run",
            data=json.dumps(
                {"case": default_case, "session_id": "web-test"}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        result = json.load(urlopen(request))
        assert all(result["workflow"]["capabilities"].values())
        assert result["report"]["scenario"]["scenario_id"] == "web-demo"
        assert "memory_jsonl" not in result["artifacts"]
        svg = urlopen(base + result["artifacts"]["concentration_svg"]).read()
        assert svg.startswith(b"<svg")
        with pytest.raises(HTTPError) as denied:
            urlopen(base + "/artifacts/web-test/memory.jsonl")
        assert denied.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_dashboard_rejects_public_bind_without_explicit_opt_in():
    with pytest.raises(ValueError, match="loopback"):
        validate_host("0.0.0.0", allow_network=False)
    with pytest.raises(ValueError, match="disabled"):
        validate_host("0.0.0.0", allow_network=True)
    assert validate_host("127.0.0.1", allow_network=False) == "127.0.0.1"


def test_create_server_enforces_loopback_for_programmatic_call(tmp_path):
    knowledge, case_path, ranges_path = fixture_files(tmp_path)
    app = DashboardApplication(
        scenario_path=case_path,
        knowledge_dir=knowledge,
        ranges_path=ranges_path,
        output_root=tmp_path / "runs",
    )
    server = None
    try:
        with pytest.raises(ValueError, match="loopback"):
            server = create_server(app, host="0.0.0.0", port=0)
    finally:
        if server is not None:
            server.server_close()


def test_dashboard_rejects_unsafe_session_id(tmp_path):
    knowledge, case_path, ranges_path = fixture_files(tmp_path)
    app = DashboardApplication(
        scenario_path=case_path,
        knowledge_dir=knowledge,
        ranges_path=ranges_path,
        output_root=tmp_path / "runs",
    )
    with pytest.raises(ValueError, match="session_id"):
        app.run_case(app.default_case, "../escape")


def test_dashboard_javascript_uses_current_report_contract():
    index = Path(__file__).parents[1] / "src" / "nuclear_agent" / "static" / "index.html"
    html = index.read_text(encoding="utf-8")
    assert "const p=run.points.at(-1)" in html
    assert "run.result.points" not in html
