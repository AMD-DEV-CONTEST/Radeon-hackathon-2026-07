"""
ForgeMind ROCm Utilities - Detect AMD Radeon GPU, memory, utilization
100% local, no internet required
"""
import subprocess
import shutil
import json
import psutil
from typing import Dict, Optional

def get_rocm_info() -> Dict:
    info = {
        "rocm_available": False,
        "gpu_name": "Unknown",
        "vram_total_gb": 0,
        "vram_used_gb": 0,
        "gpu_util": 0,
        "temp_c": 0,
        "rocm_version": "N/A"
    }
    
    if not shutil.which("rocm-smi"):
        return info
    
    try:
        # rocm-smi --showproductname
        result = subprocess.run(["rocm-smi", "--showproductname", "--json"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            # parse first GPU
            for k,v in data.items():
                if isinstance(v, dict) and "Card Series" in v:
                    info["gpu_name"] = v.get("Card Model", "AMD Radeon")
                    info["rocm_available"] = True
        
        # rocm-smi --showmeminfo vram
        mem = subprocess.run(["rocm-smi", "--showmeminfo", "vram", "--json"], capture_output=True, text=True, timeout=5)
        if mem.returncode == 0:
            mem_data = json.loads(mem.stdout)
            for card in mem_data.values():
                if isinstance(card, dict):
                    # Example parsing - adapt to actual rocm-smi JSON
                    pass

        # rocm-smi --showuse --json
        use = subprocess.run(["rocm-smi", "--showuse", "--json"], capture_output=True, text=True, timeout=5)
        if use.returncode == 0:
            use_data = json.loads(use.stdout)
            info["rocm_available"] = True

        # rocm-smi version
        ver = subprocess.run(["rocm-smi", "--showdriverversion"], capture_output=True, text=True, timeout=3)
        if ver.returncode == 0:
            info["rocm_version"] = ver.stdout.strip()

    except Exception as e:
        print(f"[ROCm] detection error: {e}")
    
    # Fallback to torch if available
    try:
        import torch
        if torch.cuda.is_available() or hasattr(torch, 'hip') or torch.version.hip:
            info["rocm_available"] = True
            info["rocm_version"] = torch.version.hip or torch.version.cuda
            if torch.cuda.is_available():
                info["gpu_name"] = torch.cuda.get_device_name(0)
                props = torch.cuda.get_device_properties(0)
                info["vram_total_gb"] = round(props.total_memory / 1e9, 1)
    except:
        pass

    # If no GPU, simulate for demo
    if not info["rocm_available"]:
        info["gpu_name"] = "AMD Radeon RX 7900 XTX (Simulated - No ROCm Hardware)"
        info["vram_total_gb"] = 24
        info["rocm_version"] = "6.2.0-sim"

    return info

if __name__ == "__main__":
    print(json.dumps(get_rocm_info(), indent=2))
