"""
cpu_health_tool.py

Evaluates CPU health based on live CPU metrics.
"""


def evaluate_cpu_health(metrics):
    """
    Evaluate CPU health.

    Args:
        metrics (dict): Dictionary returned by get_cpu_status()

    Returns:
        dict: CPU health report
    """

    cpu_usage = float(metrics["cpu_usage"])

    health = {
        "overall": "Healthy",
        "cpu_usage": "Normal",
        "recommendation": "No action required."
    }

    if cpu_usage >= 90:
        health["overall"] = "Critical"
        health["cpu_usage"] = "Critical"
        health["recommendation"] = (
            "CPU usage is critically high. Investigate running processes."
        )

    elif cpu_usage >= 70:
        health["overall"] = "Warning"
        health["cpu_usage"] = "Warning"
        health["recommendation"] = (
            "CPU usage is elevated. Monitor the workload."
        )

    elif cpu_usage < 10:
        health["cpu_usage"] = "Idle"

    return health
