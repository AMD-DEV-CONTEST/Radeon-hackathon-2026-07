import pytest
import ctypes
from vte.bridge.hip_runtime import HIPRuntime
from vte.bridge.errors import HIPSafetyError, HIPRuntimeError

@pytest.fixture
def mock_hip():
    hip = HIPRuntime.__new__(HIPRuntime)
    hip._lib = None
    hip._initialized = True
    hip._active_allocations = {}
    hip._in_cleanup_mode = False
    hip._vram_total = 8 * 1024 * 1024 * 1024
    hip._counted_as_live = False
    return hip


@pytest.fixture(autouse=True)
def _reset_process_wide_hip_state():
    """_process_wide_allocated_bytes/_live_instance_count are HIPRuntime
    CLASS attributes (shared across every instance in the process, see the
    "Fase 5" comment in hip_runtime.py -- needed so two coexisting
    HIPRuntime instances see each other's allocations for the real 95% VRAM
    guard). Tests construct throwaway instances via __new__, but a class
    attribute mutated by one test leaks into every test that runs after it
    in the same process. Snapshot and restore around each test."""
    saved_bytes = HIPRuntime._process_wide_allocated_bytes
    saved_count = HIPRuntime._live_instance_count
    yield
    HIPRuntime._process_wide_allocated_bytes = saved_bytes
    HIPRuntime._live_instance_count = saved_count

def test_malloc_rejects_zero(mock_hip):
    with pytest.raises(HIPSafetyError):
        mock_hip.safe_malloc(0)

def test_malloc_rejects_negative(mock_hip):
    with pytest.raises(HIPSafetyError):
        mock_hip.safe_malloc(-1)

def test_malloc_rejects_oversized(mock_hip):
    """Nenhuma alocação única pode exceder a VRAM física real do device
    (self._vram_total, medido em initialize() -- ver o comentário em
    safe_malloc sobre o bug real do teto fixo de 8GB que isso substituiu)."""
    with pytest.raises(HIPSafetyError):
        mock_hip.safe_malloc(mock_hip._vram_total + 1)

def test_malloc_rejects_vram_overflow(mock_hip):
    # The 95% guard sums HIPRuntime._process_wide_allocated_bytes (a
    # process-wide class counter), not this instance's _active_allocations
    # -- see the "Fase 5" comment on HIPRuntime for why (two HIPRuntime
    # instances in the same process, e.g. draft + target model, must see
    # each other's allocations against the same physical VRAM).
    HIPRuntime._process_wide_allocated_bytes = int(mock_hip._vram_total * 0.9)
    with pytest.raises(HIPSafetyError):
        mock_hip.safe_malloc(int(mock_hip._vram_total * 0.1))

def test_memcpy_rejects_invalid_dst(mock_hip):
    dst = ctypes.c_void_p(999)
    with pytest.raises(HIPSafetyError):
        mock_hip.safe_memcpy_host_to_device(dst, b"test")

def test_memcpy_rejects_buffer_overflow(mock_hip):
    ptr_val = 123
    mock_hip._active_allocations[ptr_val] = (10, "small_buffer")
    dst = ctypes.c_void_p(ptr_val)
    src = b"1234567890123"
    with pytest.raises(HIPSafetyError):
        mock_hip.safe_memcpy_host_to_device(dst, src)

def test_free_rejects_untracked_ptr(mock_hip):
    ptr = ctypes.c_void_p(999)
    with pytest.raises(HIPSafetyError):
        mock_hip.safe_free(ptr)

def test_ops_before_init_rejected():
    hip = HIPRuntime.__new__(HIPRuntime)
    hip._lib = None
    hip._initialized = False
    hip._vram_total = 1000
    with pytest.raises(HIPSafetyError):
        hip.safe_malloc(100)

def test_cleanup_releases_all():
    hip = HIPRuntime.__new__(HIPRuntime)
    hip._lib = None
    hip._initialized = True
    hip._in_cleanup_mode = False
    hip._counted_as_live = False

    def mock_free(ptr, tag=""):
        val = ptr.value or 0
        if val in hip._active_allocations:
            del hip._active_allocations[val]
        return True
    hip.safe_free = mock_free
    
    hip._active_allocations = {1: (10, "a"), 2: (20, "b")}
    hip.cleanup()
    assert len(hip._active_allocations) == 0
    assert hip._initialized is False

def test_cleanup_logs_untracked(caplog):
    hip = HIPRuntime.__new__(HIPRuntime)
    hip._lib = None
    hip._initialized = True
    hip._in_cleanup_mode = True
    hip._active_allocations = {}
    
    ptr = ctypes.c_void_p(999)
    result = hip.safe_free(ptr)
    
    assert result is False
    assert "não rastreável durante cleanup" in caplog.text

def test_device_validation():
    from vte.bridge.hip_runtime import HIPDeviceProperties
    props = HIPDeviceProperties(
        name="Test",
        total_global_mem=1024,
        shared_mem_per_block=64,
        max_threads_per_block=1024,
        warp_size=32,
        multi_processor_count=2,
        compute_capability="10.0"
    )
    is_valid, msg = props.validate_for_vte()
    assert is_valid is False
    assert "VRAM insuficiente" in msg


def _mock_hip_with_devices(names, monkeypatch):
    """HIPRuntime com hipGetDeviceCount/hipGetDeviceProperties mockados para
    simular `len(names)` devices HIP visíveis, na ordem dada. Usado por
    test_select_device_index_* -- não há iGPU+dGPU físicas nesta máquina de
    teste (só a RX 7600 discreta), então a lógica de desambiguação de
    múltiplos devices só pode ser verificada com mocks."""
    from unittest.mock import MagicMock

    monkeypatch.delenv("VTE_DEVICE_INDEX", raising=False)
    monkeypatch.delenv("VTE_TARGET_ARCH_FAMILY", raising=False)
    hip = HIPRuntime.__new__(HIPRuntime)
    hip._lib = MagicMock()

    def fake_count(ptr):
        ptr._obj.value = len(names)
        return 0

    def fake_props(props_ptr, device_id):
        props_ptr._obj.name = names[device_id].encode("utf-8")
        props_ptr._obj.totalGlobalMem = 0
        props_ptr._obj.sharedMemPerBlock = 0
        props_ptr._obj.maxThreadsPerBlock = 0
        props_ptr._obj.warpSize = 0
        props_ptr._obj.multiProcessorCount = 0
        props_ptr._obj.major = 0
        props_ptr._obj.minor = 0
        # Vazio de propósito -- os testes de _select_device_index exercitam o
        # fallback por nome comercial (ver _identify_device_arch), não a
        # detecção via gcnArchName (coberta em separado por
        # test_get_gpu_architecture_prefers_gcn_arch_name).
        props_ptr._obj.gcnArchName = b""
        return 0

    hip._lib.hipGetDeviceCount.side_effect = fake_count
    hip._lib.hipGetDevicePropertiesR0600.side_effect = fake_props
    return hip


def test_identify_device_arch_prefers_gcn_arch_name_over_generic_name(monkeypatch):
    """Workstation/server GPUs (W7900 included) report the generic name 'AMD
    Radeon Graphics' via ROCm -- name-pattern matching alone can't tell them
    apart (confirmed live against a real W7900, see hip_runtime.py's
    get_gpu_architecture docstring). gcnArchName is the actual ISA reported
    by the driver and must win over the name whenever it's populated."""
    hip = _mock_hip_with_devices(["AMD Radeon Graphics"], monkeypatch)

    def fake_props(props_ptr, device_id):
        props_ptr._obj.name = b"AMD Radeon Graphics"
        props_ptr._obj.gcnArchName = b"gfx1100"
        return 0

    hip._lib.hipGetDevicePropertiesR0600.side_effect = fake_props
    name, arch = hip._identify_device_arch(0)
    assert name == "AMD Radeon Graphics"
    assert arch == "gfx1100"


def test_select_device_index_skips_igpu_when_dgpu_is_second(monkeypatch):
    hip = _mock_hip_with_devices(
        ["AMD Radeon(TM) 780M Graphics", "AMD Radeon RX 7600"], monkeypatch
    )
    assert hip._select_device_index() == 1


def test_select_device_index_picks_dgpu_when_dgpu_is_first(monkeypatch):
    hip = _mock_hip_with_devices(
        ["AMD Radeon RX 7900 XTX", "AMD Radeon(TM) 890M Graphics"], monkeypatch
    )
    assert hip._select_device_index() == 0


def test_select_device_index_falls_back_when_nothing_matches(monkeypatch, caplog):
    hip = _mock_hip_with_devices(
        ["AMD Radeon(TM) 780M Graphics", "AMD Radeon(TM) 890M Graphics"], monkeypatch
    )
    assert hip._select_device_index() == 0
    assert "Nenhum" in caplog.text


def test_select_device_index_respects_explicit_override(monkeypatch):
    hip = _mock_hip_with_devices(["AMD Radeon RX 7600", "AMD Radeon RX 7900 XTX"], monkeypatch)
    monkeypatch.setenv("VTE_DEVICE_INDEX", "1")
    assert hip._select_device_index() == 1


def test_select_device_index_skips_enumeration_for_single_device(monkeypatch):
    hip = _mock_hip_with_devices(["AMD Radeon RX 7600"], monkeypatch)
    assert hip._select_device_index() == 0


def test_select_device_index_target_family_picks_matching_generation(monkeypatch):
    hip = _mock_hip_with_devices(["AMD Radeon RX 6800 XT", "AMD Radeon RX 7600"], monkeypatch)
    monkeypatch.setenv("VTE_TARGET_ARCH_FAMILY", "gfx110X")
    assert hip._select_device_index() == 1


def test_select_device_index_target_family_rejects_mismatched_generation(monkeypatch):
    hip = _mock_hip_with_devices(["AMD Radeon RX 6800 XT"], monkeypatch)
    monkeypatch.setenv("VTE_TARGET_ARCH_FAMILY", "gfx110X")
    with pytest.raises(HIPRuntimeError):
        hip._select_device_index()


def test_select_device_index_target_family_rejects_when_only_other_generation_present(monkeypatch):
    hip = _mock_hip_with_devices(["AMD Radeon RX 6800 XT", "AMD Radeon RX 6900 XT"], monkeypatch)
    monkeypatch.setenv("VTE_TARGET_ARCH_FAMILY", "gfx110X")
    with pytest.raises(HIPRuntimeError):
        hip._select_device_index()


def test_select_device_index_without_target_family_ignores_generation(monkeypatch):
    """Without VTE_TARGET_ARCH_FAMILY, enumeration order wins regardless of
    generation -- this is exactly the gap the env var closes: RDNA2 first in
    enumeration order gets picked even though an RDNA3 card is also present."""
    hip = _mock_hip_with_devices(["AMD Radeon RX 6800 XT", "AMD Radeon RX 7600"], monkeypatch)
    assert hip._select_device_index() == 0
