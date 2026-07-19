import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.compiler.sanitizer import GGUFSanitizer
from vte.bridge.memory import SlabAllocator
from vte.bridge.hip_runtime import HIPRuntime

def verify_pass1():
    print("--- Iniciando Verificação do Passo 1 ---")
    
    try:
        sanitizer = GGUFSanitizer('Model/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf')

        sanitizer.validate()
        print("[OK] GGUF Sanitizer validado.")
    except Exception as e:
        print(f"[!] GGUF Sanitizer levantou aviso/erro esperado: {e}")
        
    try:
        with HIPRuntime() as hip:
            props = hip.get_device_properties()

            vram_limit = min(props['total_global_mem'], 100 * 1024 * 1024) 
            
            allocator = SlabAllocator(hip, vram_limit)
            allocator.initialize()
            print('Sandbox Validado. VRAM Alocada. Pronto para compilar.')
            allocator.cleanup()
    except Exception as e:
         print(f"[!] Slab/Runtime levantou erro (se você não tiver GPU HIP, este erro é esperado): {e}")

if __name__ == "__main__":
    verify_pass1()
