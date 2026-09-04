import json
import http.client
import sys
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from nuclear_agent.web import DashboardApplication, create_server


def app(tmp_path):
    data = Path(__file__).parents[1] / "src/nuclear_agent/data"
    case = data / "scenarios/cs137_emergency_full.json"
    ranges = data / "scenarios/uncertainty_ranges.json"
    knowledge = data / "knowledge"
    return DashboardApplication(case, knowledge, ranges, tmp_path / "results")


def test_e4_versioned_read_only_endpoints_and_replay_scope(tmp_path):
    application = app(tmp_path)
    server = create_server(application, port=0)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert json.load(urlopen(base + "/api/v1/models/gcs/primary"))["model_version"]
        paper = json.load(urlopen(base + "/api/v1/paper-rocks"))
        assert paper["schema_version"] == "1.0.0" and paper["rocks"]
        assert json.load(urlopen(base + "/api/v1/source-terms"))["contract_version"] == "source-term-1.0"
        req = Request(base + "/api/v1/model-selection", data=json.dumps({
            "request": {"radionuclide": "Cs-137", "capabilities": ["primary_gcs"]},
            "candidates": [{"name": "gcs", "capabilities": ["primary_gcs"], "applicability": ["Cs-137"]}, {"name": "bad"}],
        }).encode(), headers={"Content-Type": "application/json"}, method="POST")
        selection = json.load(urlopen(req)); assert selection["selected"] == ["gcs"]
        assert selection["rejected"]["bad"]
        with open(tmp_path / "outside.json", "w") as f: f.write("x")
        req = Request(base + "/api/v1/replay/verify", data=json.dumps({"path": str(tmp_path / "outside.json")}).encode(), headers={"Content-Type": "application/json"}, method="POST")
        try: urlopen(req)
        except HTTPError as e: assert e.code == 403
        else: raise AssertionError("outside results root accepted")

        for route in ("/api/v1/replay/verify", "/api/v1/model-selection"):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
            connection.putrequest("POST", route)
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(1_000_001))
            connection.endheaders()
            assert connection.getresponse().status == 400
            connection.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
