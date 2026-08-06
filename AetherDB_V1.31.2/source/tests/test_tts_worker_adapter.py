from services.model_runtime.worker_process import KokoroTTSWorkerAdapter


def test_kokoro_baseline_advertises_only_bundled_language_runtimes(tmp_path):
    adapter = KokoroTTSWorkerAdapter(tmp_path)

    assert adapter.capabilities()["languages"] == [
        "en",
        "en-gb",
        "en-us",
        "zh",
        "zh-cn",
    ]
