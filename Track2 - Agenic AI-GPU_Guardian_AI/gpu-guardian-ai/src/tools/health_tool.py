"""
health_tool.py

Evaluates the health of the AMD GPU based on
live metrics collected from gpu_tool.py.
"""

from config.settings import GPU_HEALTH_THRESHOLDS


def evaluate_gpu_health(metrics):
    """
    Evaluate GPU health based on collected metrics.

    Args:
        metrics (dict): Dictionary returned by get_gpu_status()

    Returns:
        dict: Health evaluation report.
    """

    health = {
        "overall": "Healthy",
        "temperature": "Normal",
        "gpu_usage": "Normal",
        "vram_usage": "Normal",
        "power": "Normal",
        "recommendation": "No action required."
    }

    # -------------------------
    # Temperature Check
    # -------------------------

    edge_temp = float(metrics["edge_temp"])

    if edge_temp >= GPU_HEALTH_THRESHOLDS["critical_temperature"]:
        health["overall"] = "Critical"
        health["temperature"] = "Critical"
        health["recommendation"] = "GPU temperature is critically high. Stop GPU-intensive workloads and investigate cooling."

    elif edge_temp >= GPU_HEALTH_THRESHOLDS["warning_temperature"]:
        health["overall"] = "Warning"
        health["temperature"] = "Warning"
        health["recommendation"] = "GPU temperature is elevated. Monitor the workload and cooling."

    # -------------------------
    # GPU Usage Check
    # -------------------------

    gpu_usage = float(metrics["gpu_usage"])

    if gpu_usage > 95:
        health["gpu_usage"] = "High"

    elif gpu_usage == 0:
        health["gpu_usage"] = "Idle"

    # -------------------------
    # VRAM Usage Check
    # -------------------------

    vram_usage = float(metrics["vram_usage"])

    if vram_usage > 90:
        health["vram_usage"] = "High"

    # -------------------------
    # Power Check
    # -------------------------

    power = float(metrics["power"])

    if power < 20:
        health["power"] = "Idle"

    return health
