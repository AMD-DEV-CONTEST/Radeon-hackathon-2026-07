#!/usr/bin/env python3
"""AMD GPU 性能监控工具 - 用于演示视频"""

import subprocess
import time
import json
from datetime import datetime


def run_rocm_smi():
    """获取ROCm GPU状态"""
    try:
        result = subprocess.run(
            ["rocm-smi", "--showmeminfo", "VRAM", "--showuse", "--json"],
            capture_output=True, text=True, timeout=5
        )
        return json.loads(result.stdout) if result.returncode == 0 else None
    except:
        return None


def get_gpu_stats():
    """获取GPU统计（兼容模式）"""
    try:
        import torch
        if torch.cuda.is_available():
            return {
                "device": torch.cuda.get_device_name(0),
                "memory_allocated": f"{torch.cuda.memory_allocated() / 1e9:.2f} GB",
                "memory_reserved": f"{torch.cuda.memory_reserved() / 1e9:.2f} GB",
                "timestamp": datetime.now().isoformat()
            }
    except ImportError:
        pass
    return {"error": "GPU不可用"}


def benchmark_embedding(embedder, texts, iterations=3):
    """测试Embedding性能"""
    import time
    
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        _ = embedder.encode(texts)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    
    avg_time = sum(times) / len(times)
    total_chars = sum(len(t) for t in texts)
    
    return {
        "avg_time_ms": avg_time * 1000,
        "texts_per_second": len(texts) / avg_time,
        "chars_per_second": total_chars / avg_time
    }


if __name__ == "__main__":
    print("AMD GPU 监控工具")
    print(get_gpu_stats())