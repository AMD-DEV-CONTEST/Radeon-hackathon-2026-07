"""
insight_tool.py

Generates high-level insights from system telemetry.
"""


def generate_insights(
    gpu,
    cpu,
    memory,
    disk,
    network
):
    insights = []

    # GPU
    if gpu["gpu_usage"] < 5:
        insights.append(
            "GPU is currently idle."
        )
    elif gpu["gpu_usage"] > 90:
        insights.append(
            "GPU is heavily utilized."
        )

    # CPU
    if cpu["cpu_usage"] > 80:
        insights.append(
            "CPU is experiencing high utilization."
        )

    # Memory
    if memory["memory_usage"] > 80:
        insights.append(
            "Memory utilization is high."
        )

    # Disk
    if disk["disk_usage"] > 85:
        insights.append(
            "Disk capacity is approaching its limit."
        )

    # Network
    if (
        network["errors_in"] > 0
        or network["errors_out"] > 0
        or network["drops_in"] > 0
        or network["drops_out"] > 0
    ):
        insights.append(
            "Network errors or packet drops detected."
        )

    if not insights:
        insights.append(
            "No significant observations detected."
        )

    return insights
