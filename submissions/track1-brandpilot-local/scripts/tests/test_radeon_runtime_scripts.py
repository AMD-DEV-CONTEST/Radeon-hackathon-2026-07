from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def source(name: str) -> str:
    return (ROOT / "scripts" / name).read_text(encoding="utf-8")


def test_bootstrap_preserves_torch_and_pins_runtime_packages():
    script = source("bootstrap_radeon_runtime.sh")
    assert "torch==" not in script
    assert "pip install torch" not in script
    for version in ("0.39.0", "4.57.6", "1.13.0", "0.7.0"):
        assert version in script
    assert "pydantic-core|pydantic_core|2.33.2" in script
    assert "/opt/venv/bin/python" in script
    assert "brandpilot-wheelhouse" in script
    assert "--only-binary=:all:" in script
    assert "--no-deps" in script


def test_start_script_binds_loopback_and_does_not_pass_token_as_argument():
    script = source("start_radeon_demo.sh")
    assert "--host 127.0.0.1" in script
    assert "rc-tunnel" in script
    assert 'expose --port "$PORT"' in script
    assert 'bash "$SCRIPT_DIR/bootstrap_radeon_runtime.sh"' in script
    assert "--token" not in script
    assert "DEMO_AUTH_TOKEN=" not in script
    assert "Bearer \" + os.environ[\"DEMO_AUTH_TOKEN\"]" in script


def test_stop_script_targets_only_the_recorded_uvicorn_process():
    script = source("stop_radeon_demo.sh")
    assert "uvicorn app.main:app" in script
    assert "--port ${PORT}" in script
    assert "killall" not in script
    assert "pkill" not in script
    assert '"$RC_TUNNEL" stop' in script
