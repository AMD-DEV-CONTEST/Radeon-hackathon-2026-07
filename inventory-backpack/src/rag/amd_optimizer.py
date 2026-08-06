"""AMD ROCm specialized optimization tools"""

import os
import torch

def optimize_for_amd():
    """
    Configure optimal AMD Radeon GPU settings
    Called at main.py startup
    """
    if not torch.cuda.is_available():
        print("⚠️ 未检测到AMD GPU，使用CPU模式")
        return
    
    device_name = torch.cuda.get_device_name(0)
    print(f"✅ AMD GPU: {device_name}")
    
    # ROCm environment variable optimization
    os.environ["HIP_VISIBLE_DEVICES"] = "0"
    os.environ["PYTORCH_HIP_ALLOC_CONF"] = "max_split_size_mb:512"

    # PyTorch settings
    torch.backends.cudnn.benchmark = True  # Auto-find optimal algorithm

    # Memory optimization
    torch.cuda.empty_cache()
    
    print(" AMD ROCm优化配置完成")

def get_gpu_stats():
    """Get GPU usage stats"""
    if not torch.cuda.is_available():
        return {"error": "No GPU"}
    
    return {
        "device": torch.cuda.get_device_name(0),
        "memory_allocated": f"{torch.cuda.memory_allocated() / 1e9:.2f} GB",
        "memory_reserved": f"{torch.cuda.memory_reserved() / 1e9:.2f} GB",
        "utilization": "使用rocm-smi获取"  # Requires subprocess call to rocm-smi
    }