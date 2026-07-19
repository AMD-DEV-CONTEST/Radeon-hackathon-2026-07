from dataclasses import dataclass
from enum import IntEnum
from typing import Optional
from vte.bridge.errors import HIPSafetyError
from vte.bridge.logger import get_logger
from vte.config import CACHE_LINE_SIZE

logger = get_logger(__name__)

class MemoryRegion(IntEnum):
    WEIGHTS = 0
    KV_CACHE = 1
    ACTIVATIONS = 2
    SCRATCH = 3

@dataclass
class MemoryBlock:
    offset: int
    size: int
    aligned_size: int
    ptr: int
    tag: str
    region: MemoryRegion
    in_use: bool = True

class SlabAllocator:
    def __init__(self, hip_runtime, total_vram_bytes: int, requested_pool_size: int = None):
        self._hip = hip_runtime
        self._total_vram = total_vram_bytes
        
        if requested_pool_size:
            self.total_size = requested_pool_size
        else:
            # Fallback para heurística antiga
            self.total_size = int(total_vram_bytes * 0.85)
            
        max_allowed = int(total_vram_bytes * 0.80)
        if self.total_size > max_allowed:
            logger.warning(
                f"Pool solicitado ({self.total_size / (1024**3):.2f}GB) "
                f"excede 80% da VRAM. Limitando para {max_allowed / (1024**3):.2f}GB"
            )
            self.total_size = max_allowed
            
        self.slab_base: int = 0
        
        self.blocks: list[MemoryBlock] = []
        self.free_list: list[tuple[int, int]] = []
        self.current_offset = 0
        
        self._initialized = False

    def initialize(self):
        """Aloca slab gigante na VRAM via safe_malloc."""
        if self._initialized:
            raise HIPSafetyError("SlabAllocator já inicializado")
            
        c_ptr = self._hip.safe_malloc(self.total_size, "VTE_GIANT_SLAB")
        self.slab_base = c_ptr.value
        if not self.slab_base:
            raise HIPSafetyError("Falha ao resolver base do slab (ptr nulo)")
            
        self._initialized = True
        logger.info(f"Slab Allocator inicializado. Base: 0x{self.slab_base:016X}, Size: {self.total_size/1024**3:.2f} GB")

    def allocate(self, size: int, tag: str, region: MemoryRegion) -> MemoryBlock:
        """Sub-aloca com alinhamento de 64 bytes."""
        if not self._initialized:
            raise HIPSafetyError("SlabAllocator não inicializado")
            
        if size <= 0:
            raise HIPSafetyError(f"Tentativa de alocar tamanho inválido no slab: {size}")

        aligned_size = (size + CACHE_LINE_SIZE - 1) & ~(CACHE_LINE_SIZE - 1)
        
        best_fit_idx = -1
        best_fit_diff = float('inf')
        
        for i, (free_offset, free_size) in enumerate(self.free_list):
            if free_size >= aligned_size:
                diff = free_size - aligned_size
                if diff < best_fit_diff:
                    best_fit_diff = diff
                    best_fit_idx = i
                    
        if best_fit_idx != -1:
            free_offset, free_size = self.free_list.pop(best_fit_idx)
            block = MemoryBlock(
                offset=free_offset,
                size=size,
                aligned_size=aligned_size,
                ptr=self.slab_base + free_offset,
                tag=tag,
                region=region
            )
            self._check_overlap(block)
            self.blocks.append(block)
            logger.debug(f"Reusado bloco livre: [{tag}] {size} bytes")
            
            if best_fit_diff > 1024 * 1024:
                self.free_list.append((free_offset + aligned_size, best_fit_diff))
                
            return block
            
        if self.current_offset + aligned_size > self.total_size:
            raise HIPSafetyError(f"OOM no Slab: Não há {aligned_size} bytes contíguos (offset atual: {self.current_offset})")
            
        block = MemoryBlock(
            offset=self.current_offset,
            size=size,
            aligned_size=aligned_size,
            ptr=self.slab_base + self.current_offset,
            tag=tag,
            region=region
        )
        
        self._check_overlap(block)
        
        self.blocks.append(block)
        self.current_offset += aligned_size
        logger.debug(f"Alocado bloco novo: [{tag}] {size} bytes")
        
        return block

    def _check_overlap(self, new_block: MemoryBlock):
        """Verifica se o novo bloco não sobrepõe blocos existentes ativos."""
        new_start = new_block.offset
        new_end = new_start + new_block.aligned_size
        
        for existing in self.blocks:
            if existing.in_use:
                existing_start = existing.offset
                existing_end = existing_start + existing.aligned_size
                if not (new_end <= existing_start or new_start >= existing_end):
                    raise HIPSafetyError(f"Sobreposição detectada: {new_block.tag} conflita com {existing.tag}")

    def free(self, block: MemoryBlock):
        """Libera bloco e adiciona ao free-list."""
        if not block.in_use:
            raise HIPSafetyError(f"Bloco já liberado: {block.tag}")
            
        block.in_use = False
        self.free_list.append((block.offset, block.aligned_size))
        logger.debug(f"Liberado bloco: [{block.tag}]")
        self._merge_adjacent_free_blocks()

    def _merge_adjacent_free_blocks(self):
        """Desfragmentação simples."""
        if len(self.free_list) < 2:
            return
            
        self.free_list.sort(key=lambda x: x[0])
        merged = []
        current_offset, current_size = self.free_list[0]
        
        for next_offset, next_size in self.free_list[1:]:
            if current_offset + current_size == next_offset:
                current_size += next_size
            else:
                merged.append((current_offset, current_size))
                current_offset, current_size = next_offset, next_size
                
        merged.append((current_offset, current_size))
        self.free_list = merged

    def validate_pointer(self, ptr: int, size: int) -> bool:
        """Valida que ponteiro está dentro do slab e não viola fronteiras ativas."""
        if not (self.slab_base <= ptr < self.slab_base + self.total_size):
            return False
            
        if ptr + size > self.slab_base + self.total_size:
            return False
            
        found_parent = False
        for block in self.blocks:
            if block.in_use:
                block_start = self.slab_base + block.offset
                block_end = block_start + block.aligned_size
                if block_start <= ptr and (ptr + size) <= block_end:
                    found_parent = True
                    break
        
        return found_parent

    def get_stats(self) -> dict:
        used = sum(b.aligned_size for b in self.blocks if b.in_use)
        free = self.total_size - used
        return {
            "total_bytes": self.total_size,
            "used_bytes": used,
            "free_bytes": free,
            "active_blocks": sum(1 for b in self.blocks if b.in_use)
        }

    def cleanup(self):
        """Não faz hipFree diretamente (fica a cargo do __exit__ do HIPRuntime).
           Apenas limpa as estruturas de controle."""
        self.blocks.clear()
        self.free_list.clear()
        self.current_offset = 0
        self.slab_base = 0
        self._initialized = False
