"""
memory_tool.py

Collects live system memory statistics.
"""

import psutil


def get_memory_status():
    """
    Collect live memory metrics.

    Returns:
        dict: Memory information
    """

    memory = psutil.virtual_memory()

    return {
        "total_gb": round(memory.total / (1024 ** 3), 2),
        "used_gb": round(memory.used / (1024 ** 3), 2),
        "available_gb": round(memory.available / (1024 ** 3), 2),
        "memory_usage": memory.percent
    }
