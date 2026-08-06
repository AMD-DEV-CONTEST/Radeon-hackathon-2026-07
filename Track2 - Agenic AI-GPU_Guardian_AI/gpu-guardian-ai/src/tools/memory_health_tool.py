"""
memory_health_tool.py

Evaluates system memory health based on live memory metrics.
"""


def evaluate_memory_health(metrics):
    """
    Evaluate memory health.

    Args:
        metrics (dict): Dictionary returned by get_memory_status()

    Returns:
        dict: Memory health report
    """

    memory_usage = float(metrics["memory_usage"])

    health = {
        "overall": "Healthy",
        "memory_usage": "Normal",
        "recommendation": "No action required."
    }

    if memory_usage >= 90:
        health["overall"] = "Critical"
        health["memory_usage"] = "Critical"
        health["recommendation"] = (
            "Memory usage is critically high. Investigate running processes."
        )

    elif memory_usage >= 70:
        health["overall"] = "Warning"
        health["memory_usage"] = "Warning"
        health["recommendation"] = (
            "Memory usage is elevated. Continue monitoring."
        )

    elif memory_usage < 10:
        health["memory_usage"] = "Idle"

    return health
