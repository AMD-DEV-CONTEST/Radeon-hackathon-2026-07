import time
import ctypes
from vte.bridge.hip_runtime import HIPRuntime
from vte.bridge.memory import SlabAllocator
from vte.core.lifecycle import ModelLifecycleManager

class RealMemoryMockModel:
    def __init__(self):
        self._hip = HIPRuntime()
        self._hip.initialize()
        
        # Alocar 2 GB de VRAM real (isso sera altamente visivel no Task Manager)
        # O limite da RX 7600 e 8GB, 2GB cabe tranquilo sem OOM.
        self._total_vram = 2 * 1024 * 1024 * 1024 
        self._allocator = None
        self._graph = None
        
    def _load(self):
        print(f"\n[!] Carregando modelo na VRAM... (Alocando {self._total_vram / 1024**3:.2f} GB Fisicamente)")
        self._allocator = SlabAllocator(self._hip, self._total_vram)
        self._allocator.initialize()
        print("\n[+] -> VRAM ALOCADA COM SUCESSO! <-")
        print("    >> ABRA O GERENCIADOR DE TAREFAS (Aba Desempenho -> GPU) AGORA! <<")
        print("    Voce tem exatos 10 segundos antes do Auto-Unload disparar e remover a memoria.\n")

if __name__ == "__main__":
    print("Iniciando Teste de Visibilidade de VRAM (Hardware Real)...")
    
    model = RealMemoryMockModel()
    
    # Timeout de 10 segundos 
    manager = ModelLifecycleManager(model, idle_timeout_seconds=10, enable_auto_unload=True)
    
    model._load()
    manager.start_monitoring()
    
    print("Contagem regressiva do Idle Timeout:")
    for i in range(1, 16):
        print(f"[{i}s] Monitorando...")
        time.sleep(1)
        if not manager._is_loaded and manager.model._allocator is None:
            print("\n[!] -> AUTO-UNLOAD EXECUTADO! <-")
            print("    A VRAM DEVE TER CAIDO EM 2GB NO SEU GERENCIADOR DE TAREFAS NESTE EXATO MOMENTO!\n")
            break
            
    print("Fim do teste. A aplicacao encerrara em 3 segundos.")
    time.sleep(3)
