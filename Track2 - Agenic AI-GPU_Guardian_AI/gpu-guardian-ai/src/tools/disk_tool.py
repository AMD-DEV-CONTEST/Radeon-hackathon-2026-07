"""
disk_tool.py

Collects the live disk statistics.
"""

import psutil

def get_disk_status():
    """
    Collect live disk metrics.

    Returns:
        dict: Disk Information
    """

    disk = psutil.disk_usage("/")

    return {
        "total_gb": round(disk.total / (1024 ** 3), 2),
        "used_gb": round(disk.used / (1024 ** 3), 2),
        "free_gb": round(disk.free / (1024 ** 3), 2),
        "disk_usage": disk.percent

    }
