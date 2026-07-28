"""
tools/validate_structs.py
Valida que nossas definições ctypes correspondem às do hip-python.
Executado apenas durante desenvolvimento/CI.
"""

import sys
import ctypes

def validate_device_properties() -> bool:
    """Compara nossa hipDeviceProp_t com a do hip-python."""
    import os
    import sys
    
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from vte.bridge.hip_runtime import hipDeviceProp_t as OurDeviceProp
    
    try:
        from hip._util import hipDeviceProp_t as HipPythonProp
        our_size = ctypes.sizeof(OurDeviceProp)
        hip_size = ctypes.sizeof(HipPythonProp)
        
        print(f"Nossa struct:  {our_size} bytes")
        print(f"hip-python:    {hip_size} bytes")
        
        if our_size != hip_size:
            print(f"[ERROR] MISMATCH: diferença de {abs(our_size - hip_size)} bytes")
            print("   Ação: Atualize _fields_ em hipDeviceProp_t")
            return False
            
        our_warp_offset = OurDeviceProp.warpSize.offset
        hip_warp_offset = HipPythonProp.warpSize.offset
        
        if our_warp_offset != hip_warp_offset:
            print(f"[ERROR] warpSize offset errado: nosso={our_warp_offset}, hip-python={hip_warp_offset}")
            return False
            
        print("[SUCCESS] Validação de struct bem-sucedida")
        return True
    except ImportError:
        print("[WARNING] hip-python não instalado. Pulando validação.")
        print("   Instale com: pip install -r requirements-dev.txt")
        return True

def validate_all_structs() -> bool:
    """Valida todas as structs críticas."""
    structs = [("hipDeviceProp_t", validate_device_properties)]
    all_passed = True
    for name, validator in structs:
        print(f"\nValidando {name}...")
        if not validator():
            all_passed = False
    return all_passed

if __name__ == "__main__":
    sys.exit(0 if validate_all_structs() else 1)
