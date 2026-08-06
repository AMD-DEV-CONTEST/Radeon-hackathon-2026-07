"""
network_health_tool.py

Evaluates network health based on live network metrics.
"""

def evaluate_network_health(metrics):
    """
    Evaluate network health.

    Args:
        metrics(dict): Network metrics

    Returns:
        dict: Network health

    """

    errors = (
        metrics["errors_in"] +
        metrics["errors_out"]

    )

    drops = (
        metrics["drops_in"] +
        metrics["drops_out"]

    )

    health = {
        "overall": "Healthy",
        "network": "Normal",
        "recommendation": "No action required."
    }

    if errors > 0:
        health["overall"] = "Warning"
        health["network"] = "Errors Detected"
        health["recommendation"] = (
            "network interface is reporting transmission errors."
        )

    if drops > 0:
        health["overall"] = "Warning"
        health["network"] = "Packet Drops Detected"
        health["recommendation"] = (
            "Network packet drops detected. Check interface congestion."
        )

    return health 
