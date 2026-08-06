"""
cpu_tool.py

Collects live CPU metrics for GPU Guardian AI.
"""

import psutil
import os


def get_cpu_status():
    """
    Collect live CPU information.

    Returns:
        dict: CPU metrics
    """

    cpu = {
        "cpu_usage":psutil.cpu_percent(interval=1),
        "cpu_cores_physical": psutil.cpu_count(logical=False),
        "cpu_cores_logical": psutil.cpu_count(logical=True),
        "cpu_frequency": round(psutil.cpu_freq().current, 2),
        "load_average": os.getloadavg()

    }

    return cpu
