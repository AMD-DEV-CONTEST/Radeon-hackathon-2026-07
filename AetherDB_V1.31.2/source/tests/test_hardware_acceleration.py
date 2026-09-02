from services.hardware_acceleration import build_hardware_acceleration_status


def test_rocm_runtime_reports_active_acceleration():
    result = build_hardware_acceleration_status(
        {
            "available": True,
            "model_id": "BAAI/bge-m3",
            "revision": "test",
            "execution_provider": "MIGraphXExecutionProvider",
            "detail": "",
        },
        ["MIGraphXExecutionProvider", "CPUExecutionProvider"],
        {"detected": True, "vendor": "AMD", "gpu_name": "Test GPU"},
        "Linux",
    )
    assert result["status"] == "active"
    assert result["acceleration_active"] is True
    assert result["fallback_active"] is False


def test_failed_gpu_initialization_reports_visible_cpu_fallback():
    result = build_hardware_acceleration_status(
        {
            "available": True,
            "model_id": "BAAI/bge-m3",
            "revision": "test",
            "execution_provider": "CPUExecutionProvider",
            "detail": "MIGraphX initialization failed; using CPU fallback",
        },
        ["MIGraphXExecutionProvider", "CPUExecutionProvider"],
        {"detected": True, "vendor": "AMD"},
        "Linux",
    )
    assert result["status"] == "fallback"
    assert result["fallback_active"] is True
    assert result["fallback_mode"] == "cpu"


def test_cuda_runtime_reports_active_acceleration_without_rocm():
    result = build_hardware_acceleration_status(
        {
            "available": True,
            "model_id": "BAAI/bge-m3",
            "revision": "test",
            "execution_provider": "CUDAExecutionProvider",
            "detail": "",
        },
        ["CUDAExecutionProvider", "CPUExecutionProvider"],
        {"detected": True, "vendor": "NVIDIA", "gpu_name": "Test CUDA GPU"},
        "Windows",
    )
    assert result["status"] == "active"
    assert result["acceleration_active"] is True
    assert result["acceleration_backend"] == "cuda"
    assert result["cuda_supported"] is True
    assert result["rocm_supported"] is False
    assert result["supported_backends"] == ["cuda"]


def test_cold_worker_does_not_claim_cpu_or_gpu_execution():
    result = build_hardware_acceleration_status(
        {
            "available": True,
            "model_id": "BAAI/bge-m3",
            "revision": "test",
            "execution_provider": None,
            "detail": "BGE-M3 native Worker is cold",
        },
        ["CPUExecutionProvider"],
        {"detected": False, "vendor": "AMD"},
        "Windows",
    )
    assert result["status"] == "cold"
    assert result["acceleration_active"] is False
    assert result["acceleration_backend"] is None
    assert result["fallback_mode"] is None


def test_cpu_only_runtime_reports_rocm_as_unsupported():
    result = build_hardware_acceleration_status(
        {
            "available": True,
            "model_id": "BAAI/bge-m3",
            "revision": "test",
            "execution_provider": "CPUExecutionProvider",
            "detail": "",
        },
        ["CPUExecutionProvider"],
        {"detected": False, "vendor": "AMD"},
        "Windows",
    )
    assert result["status"] == "unsupported"
    assert result["supported"] is False
    assert result["fallback_mode"] == "cpu"
