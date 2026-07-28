import time
import hashlib
from vte.bridge.memory import SlabAllocator
from vte.bridge.logger import get_logger

logger = get_logger("VTE.VRAMProfiler")

class VRAMProfiler:
    """Perfil detalhado de uso de sub-alocações no Slab Allocator da VRAM"""
    
    def __init__(self, allocator: SlabAllocator):
        self.allocator = allocator
        self.allocations = []
        self._tensor_hashes = set()
    
    def track_allocation(self, name: str, size_mb: float, region: str, tensor_hash: str = None):
        """Registra alocação e detecta duplicações silenciosas"""
        if tensor_hash:
            if tensor_hash in self._tensor_hashes:
                logger.warning(f"Possivel duplicacao detectada: {name} (hash {tensor_hash} ja alocado)")
            self._tensor_hashes.add(tensor_hash)
            
        self.allocations.append({
            'name': name,
            'size_mb': size_mb,
            'region': region,
            'tensor_hash': tensor_hash,
            'timestamp': time.time()
        })
        
        logger.info(f"VRAM: {name} = {size_mb:.1f} MB ({region})")
        
    def get_summary_dict(self) -> dict:
        total = sum(a['size_mb'] for a in self.allocations)
        
        weights = sum(a['size_mb'] for a in self.allocations if a['region'] == 'WEIGHTS')
        kv_cache = sum(a['size_mb'] for a in self.allocations if a['region'] == 'KV_CACHE')
        arena = sum(a['size_mb'] for a in self.allocations if a['region'] == 'ACTIVATIONS')
        scratch = sum(a['size_mb'] for a in self.allocations if a['region'] == 'SCRATCH')
        
        return {
            'total_mb': total,
            'weights_mb': weights,
            'kv_cache_mb': kv_cache,
            'arena_mb': arena,
            'scratch_mb': scratch
        }

    def print_summary(self):
        """Imprime resumo visual de uso no terminal"""
        total = sum(a['size_mb'] for a in self.allocations)
        
        print("\n" + "="*60)
        print("PERFIL DE SUB-ALOCACOES DA VRAM (DENTRO DO SLAB)")
        print("="*60)
        
        by_region = {}
        for alloc in self.allocations:
            region = alloc['region']
            if region not in by_region:
                by_region[region] = []
            by_region[region].append(alloc)
            
        for region, allocs in by_region.items():
            region_total = sum(a['size_mb'] for a in allocs)
            print(f"\n{region}: {region_total:.1f} MB")
            
        print(f"\n{'='*60}")
        print(f"TOTAL USADO NO POOL: {total:.1f} MB")
        print(f"Slab Pool Disponível: {self.allocator.total_size / (1024*1024):.1f} MB")
        print("="*60 + "\n")

    def detect_anomalies(self) -> list[str]:
        """Verifica se há desperdício nas alocações feitas"""
        anomalies = []
        
        kv_total = sum(a['size_mb'] for a in self.allocations if a['region'] == 'KV_CACHE')
        if kv_total > 500:
            anomalies.append(f"KV Cache muito grande: {kv_total:.1f} MB (esperado ~114 MB ou menos)")
            
        arena_total = sum(a['size_mb'] for a in self.allocations if a['region'] == 'ACTIVATIONS')
        if arena_total > 200:
            anomalies.append(f"Activation Arena muito grande: {arena_total:.1f} MB (esperado ~70 MB ou menos)")
            
        names = [a['name'] for a in self.allocations]
        duplicates = [n for n in names if names.count(n) > 1]
        if duplicates:
            anomalies.append(f"Possiveis duplicacoes nominais: {set(duplicates)}")
            
        return anomalies
