import logging

from cortex.node.embedder import Embedder


def test_embedder_logs_device_info_on_load(caplog):
    caplog.set_level(logging.INFO)
    Embedder(model="BAAI/bge-small-en-v1.5", backend="cpu", batch_size=4)
    assert "device=" in caplog.text
    assert "device=cpu" in caplog.text
    assert "hip=" in caplog.text
