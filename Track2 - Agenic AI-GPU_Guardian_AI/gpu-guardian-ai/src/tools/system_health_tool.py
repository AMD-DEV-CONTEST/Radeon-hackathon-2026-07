"""
system_health_tool.py

Evaluates overall system health by combining
GPU, CPU, Memory, Disk and Network health.
"""


def evaluate_system_health(
    gpu_health,
    cpu_health,
    memory_health,
    disk_health,
    network_health
):
    """
    Evaluate overall system health.

    Returns:
        dict
    """

    health_modules = [
        gpu_health,
        cpu_health,
        memory_health,
        disk_health,
        network_health
    ]

    overall = "Healthy"
    severity = "Low"
    summary = "All monitored resources are operating normally.\n"
    recommendation = "No action required."

    for module in health_modules:

        status = module.get("overall", "Healthy")

        if status == "Critical":
            overall = "Critical"
            severity = "High"
            summary = "Critical issues detected in one or more system resources."
            recommendation = (
                "Immediate investigation is recommended."
            )
            break

        elif status == "Warning":
            overall = "Warning"
            severity = "Medium"
            summary = "One or more system resources require attention."
            recommendation = (
                "Review the affected subsystem."
            )

    return {
        "overall": overall,
        "severity": severity,
        "summary": summary,
        "recommendation": recommendation
    }
