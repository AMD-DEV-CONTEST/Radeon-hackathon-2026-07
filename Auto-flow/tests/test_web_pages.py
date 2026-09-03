import threading
from http.client import HTTPConnection
from urllib.request import urlopen

from autoflow.webapp import create_server


def test_home_agent_and_model_center_are_separate_pages():
    server = create_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/", timeout=3) as response:
            home = response.read().decode("utf-8")
        with urlopen(base + "/agent.html", timeout=3) as response:
            agent = response.read().decode("utf-8")
        with urlopen(base + "/models.html", timeout=3) as response:
            models = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    assert "首页只负责导航" in home
    assert "id=\"conversation\"" not in home
    assert "任务区已准备好" in agent
    assert "id=\"conversation\"" in agent
    assert "id=\"silent-mode\"" in agent
    assert "11 个明确入口" in home
    assert "provider-grid" in models
    assert "Windows 凭据库" in models
    assert "API 地址" not in models
    assert "endpoint-copy" not in models

    models_script = (server.webui_root / "models.js").read_text(encoding="utf-8")
    assert "item.base_url||\"自定义地址\"" not in models_script

    agent_script = (server.webui_root / "agent.js").read_text(encoding="utf-8")
    agent_styles = (server.webui_root / "agent.css").read_text(encoding="utf-8")
    assert 'card.classList.toggle("final-answer",terminal)' in agent_script
    assert 'copy.textContent=session.message' in agent_script
    assert 'silent:q("#silent-mode").checked' in agent_script
    assert ".message.final-answer p" in agent_styles
    assert "color: #182019" in agent_styles


def test_local_api_requires_exact_origin_and_json_content_type():
    server = create_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    def post(origin, content_type="application/json", host=None):
        connection = HTTPConnection("127.0.0.1", port, timeout=3)
        headers = {"Content-Type": content_type, "Origin": origin, "Host": host or f"127.0.0.1:{port}"}
        connection.request("POST", "/api/agent/stop", body='{"session_id":"missing"}', headers=headers)
        response = connection.getresponse()
        status = response.status
        response.read()
        connection.close()
        return status

    try:
        assert post(f"http://127.0.0.1:{port}") == 400
        assert post(f"http://127.0.0.1:{port}0") == 403
        assert post(f"http://127.0.0.1:{port}", content_type="text/plain") == 415
        assert post("", host=f"127.0.0.1.evil:{port}") == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
