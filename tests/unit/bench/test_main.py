import importlib


class _FakeRunner:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.run_called = 0
        self.stop_called = 0

    async def run(self) -> None:
        self.run_called += 1

    async def stop(self) -> None:
        self.stop_called += 1


def test_main_constructs_runner_with_argv(monkeypatch):
    bench_main = importlib.import_module("cortex.bench.__main__")

    captured = {}
    fake = _FakeRunner()

    class _FakeBenchRunner:
        def __new__(cls, node_id, broker_url, config_path, **kw):
            captured["node_id"] = node_id
            captured["broker_url"] = broker_url
            captured["config_path"] = config_path
            return fake

    monkeypatch.setattr(bench_main, "BenchRunner", _FakeBenchRunner)

    argv = [
        "cortex.bench",
        "--node", "did:percq:org:soc-alpha",
        "--broker", "wss://broker.local:7432",
        "--config", "bench.yaml",
    ]
    monkeypatch.setattr("sys.argv", argv)
    bench_main.main()
    assert captured["node_id"] == "did:percq:org:soc-alpha"
    assert captured["broker_url"] == "wss://broker.local:7432"
    assert captured["config_path"] == "bench.yaml"
    assert fake.run_called == 1
