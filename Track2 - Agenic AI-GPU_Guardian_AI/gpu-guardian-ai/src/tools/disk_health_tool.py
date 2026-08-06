"""
disk_health_tool.py

Evaluates disk health based on live disk metrics.
"""

def evaluate_disk_health(metrics):
    """
    Evauate disk health.

    Args:
        metrics(dict): Dictionary returned by get_disk_status()

    Returns:
        dict: Disk health report

    """
    
    disk_usage = float(metrics["disk_usage"])

    health = {
        "overall": "Healthy",
        "disk_usage": "Normal",
        "recommendation": "No action required"
    }

    if disk_usage >= 90:
        health["overall"] = "Critical"
        health["disk_usage"] = "Critical"
        health["recommendation"] = (
            "Disk usage is critically high. Free up disk immediately."
        )

    elif disk_usage >= 75:
        health["overall"] = "Warning"
        health["disk_usage"] = "Warning"
        health["recommendation"] = (
            "Disk usage is increasing. Consider cleaning old files."
        )

    elif disk_usage < 20:
        health["disk_usage"] = "Idle"

    return health
