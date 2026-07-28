import pytest
import ctypes
from vte.bridge.memory import SlabAllocator, MemoryRegion
from vte.bridge.errors import HIPSafetyError
from vte.config import CACHE_LINE_SIZE

class MockHIPRuntime:
    def __init__(self):
        self._vram = bytearray(1024 * 1024)
        
    def safe_malloc(self, size, tag):

        self.buf = ctypes.create_string_buffer(size)
        return ctypes.c_void_p(ctypes.addressof(self.buf))

@pytest.fixture
def allocator():
    hip = MockHIPRuntime()
    alloc = SlabAllocator(hip, 1024 * 1024)
    alloc.initialize()
    return alloc

def test_allocation_alignment(allocator):
    block = allocator.allocate(10, "test1", MemoryRegion.SCRATCH)
    assert block.aligned_size == CACHE_LINE_SIZE
    assert block.offset % CACHE_LINE_SIZE == 0
    
    block2 = allocator.allocate(65, "test2", MemoryRegion.SCRATCH)
    assert block2.aligned_size == CACHE_LINE_SIZE * 2
    assert block2.offset % CACHE_LINE_SIZE == 0

def test_free_list_reuse(allocator):
    b1 = allocator.allocate(100, "b1", MemoryRegion.SCRATCH)
    b2 = allocator.allocate(100, "b2", MemoryRegion.SCRATCH)
    
    allocator.free(b1)
    assert len(allocator.free_list) == 1
    
    b3 = allocator.allocate(50, "b3", MemoryRegion.SCRATCH)
    assert b3.offset == b1.offset
    
    stats = allocator.get_stats()
    assert stats["active_blocks"] == 2

def test_pointer_validation(allocator):
    b1 = allocator.allocate(100, "b1", MemoryRegion.SCRATCH)
    
    assert allocator.validate_pointer(b1.ptr + 10, 50) is True
    
    assert allocator.validate_pointer(b1.ptr + 80, 100) is False
    
    assert allocator.validate_pointer(allocator.slab_base + allocator.total_size + 10, 10) is False

def test_overlap_rejection(allocator):

    allocator.allocate(100, "b1", MemoryRegion.SCRATCH)
    allocator.current_offset = 0
    
    with pytest.raises(HIPSafetyError, match="Sobreposição detectada"):
        allocator.allocate(100, "b2", MemoryRegion.SCRATCH)

def test_oom_rejection(allocator):
    with pytest.raises(HIPSafetyError, match="OOM no Slab"):
        allocator.allocate(allocator.total_size + 1, "too_big", MemoryRegion.SCRATCH)
