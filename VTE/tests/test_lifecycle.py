import pytest
import time
import threading
from vte.core.model import VTEModel
from vte.core.lifecycle import ModelLifecycleManager

def test_unload_prevents_race_condition():
    """Testa que unload e generate nao concorrem."""

    class MockModel:
        def __init__(self):
            self._hip = None
            self._allocator = None
            self._graph = None
        def _load(self):
            time.sleep(0.1)
            pass
            
    model = MockModel()
    manager = ModelLifecycleManager(model, idle_timeout_seconds=300, enable_auto_unload=False)
    manager._is_loaded = True
    manager._wipe_on_next_load = False
    
    unload_thread = threading.Thread(target=manager.unload)
    unload_thread.start()
    
    time.sleep(0.01)
    
    manager.ensure_loaded()
    
    assert manager._is_loaded == True
    
    unload_thread.join()

def test_lazy_wipe_performance():
    """Testa que lazy wipe e rapido"""
    class MockModel:
        def __init__(self):
            self._hip = None
            self._allocator = None
            self._graph = None
        def _load(self):
            pass
            
    model = MockModel()
    manager = ModelLifecycleManager(model, idle_timeout_seconds=300, enable_auto_unload=False)
    manager._is_loaded = True
    
    start = time.perf_counter()
    manager.unload(secure_wipe=False)
    unload_time = time.perf_counter() - start
    
    assert unload_time < 0.1, f"Unload demorou {unload_time:.2f}s (esperado <0.1s)"
    assert manager._wipe_on_next_load == True
    assert manager._is_loaded == False
    
    start = time.perf_counter()
    manager.reload()
    reload_time = time.perf_counter() - start
    
    assert manager._wipe_on_next_load == False
    assert manager._is_loaded == True
