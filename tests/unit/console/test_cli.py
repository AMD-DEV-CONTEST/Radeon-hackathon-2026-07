from pathlib import Path

import pytest

from cortex.console.__main__ import build_app, parse_args


def test_parse_args_defaults():
    args = parse_args(["--broker", "wss://localhost:7432", "--static", "dist", "--registry", "reg.json"])
    assert args.broker == "wss://localhost:7432"
    assert args.port == 8080
    assert args.static == "dist"
    assert args.registry == "reg.json"


@pytest.mark.asyncio
async def test_build_app_wires_broker_subscriber(tmp_path: Path):
    app, lifecycle = build_app(broker_url="wss://localhost:7432", static_dir=tmp_path, registry_path=tmp_path / "r.json")
    assert app.title == "cortex-console"
    await lifecycle.stop()
