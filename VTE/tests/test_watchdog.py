import pytest
import time
from vte.bridge.watchdog import KernelWatchdog

class MockHIPRuntime:
    pass

@pytest.fixture
def watchdog():
    wd = KernelWatchdog(MockHIPRuntime())
    wd.start()
    yield wd
    wd.stop()

def test_watchdog_lifecycle():
    wd = KernelWatchdog(MockHIPRuntime())
    assert wd._running is False
    wd.start()
    assert wd._running is True
    assert wd._thread is not None
    assert wd._thread.is_alive()
    wd.stop()
    assert wd._running is False

def test_normal_execution_completes_without_timeout(watchdog):
    eid = watchdog.register_execution("fast_kernel", estimated_ms=500)
    assert eid in watchdog._active_kernels
    
    watchdog.complete_execution(eid)
    
    assert eid not in watchdog._active_kernels
    assert not watchdog.should_abort(eid)

def test_timeout_sets_abort_flag(watchdog):

    eid = watchdog.register_execution("slow_kernel", estimated_ms=10, timeout_multiplier=1.0)
    
    time.sleep(0.3)
    
    assert watchdog.should_abort(eid) is True
    assert eid not in watchdog._active_kernels
    
    watchdog.complete_execution(eid)
