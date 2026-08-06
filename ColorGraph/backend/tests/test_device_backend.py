from colorgraph.devices import TorchComputeBackend


def test_backend_reports_runtime() -> None:
    backend = TorchComputeBackend("auto")
    assert backend.info.available is True
    assert backend.info.runtime in {"cuda", "rocm", "cpu"}
    assert backend.info.migration_compatible is True
