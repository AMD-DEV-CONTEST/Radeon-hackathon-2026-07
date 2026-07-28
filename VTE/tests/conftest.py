import pytest
import ctypes
from pathlib import Path
from vte.bridge.dll_discovery import find_hip_dll

@pytest.fixture
def project_root():
    return Path(__file__).parent

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "gpu_required: mark test to run only if AMD GPU (HIP SDK) is available"
    )

def pytest_collection_modifyitems(config, items):
    dll_path = find_hip_dll()
    if not dll_path:
        skip_gpu = pytest.mark.skip(reason="amdhip64.dll não encontrada (GPU ausente)")
        for item in items:
            if "gpu_required" in item.keywords:
                item.add_marker(skip_gpu)
