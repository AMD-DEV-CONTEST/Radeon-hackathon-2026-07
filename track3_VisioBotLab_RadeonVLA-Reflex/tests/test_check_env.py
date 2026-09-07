from radeonvla.check_env import collect_environment, run_tensor_smoke


def test_collect_environment_reports_local_runtime() -> None:
    environment = collect_environment()
    assert environment["python"].startswith("3.12")
    assert environment["torch"]
    assert environment["genesis"] == "1.1.2"
    assert environment["lerobot"] == "0.6.0"


def test_cpu_tensor_smoke() -> None:
    result = run_tensor_smoke(require_amd=False)
    assert result["tensor_device"] == "cpu"
    assert result["loss"] >= 0
