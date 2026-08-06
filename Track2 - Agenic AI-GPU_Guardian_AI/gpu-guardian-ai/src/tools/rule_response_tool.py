"""
rule_response_tool.py

Deterministic responses for factual system health questions.

This avoids unnecessary LLM usage and eliminates hallucinations
for simple monitoring queries.
"""

BOLD = "\033[1m"

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"

RESET = "\033[0m"


def heading(title):
    return (
        f"{BOLD}{CYAN}{title}{RESET}\n"
        "────────────────────────────────────────\n"
    )


def status_color(status):
    s = status.lower()

    if s == "healthy":
        return GREEN

    if s == "warning":
        return YELLOW

    return RED

def generate_rule_response(
    intent,
    gpu,
    gpu_health,
    cpu,
    cpu_health,
    memory,
    memory_health,
    disk,
    disk_health,
    network,
    network_health,
    system_health,
):
    intent = intent.lower()

    # GPU
    if intent == "gpu":

        if gpu_health["gpu_usage"] == "Idle":
            return (
                heading("GPU Summary")
                + f"Your GPU is currently idle ({gpu['gpu_usage']}% utilization).\n\n"

                + heading("Reason")
                + "No AI inference or compute-intensive workload is currently running.\n\n"

                + heading("Status")
                + f"{status_color(gpu_health['overall'])}{gpu_health['overall']}{RESET}\n\n"

                + heading("Recommendation")
                + f"{gpu_health['recommendation']}"
            )
        return (
            heading("GPU Summary")
            + f"Current GPU utilization : {gpu['gpu_usage']}%\n\n"

            + heading("Status")
            + f"{status_color(gpu_health['overall'])}{gpu_health['overall']}{RESET}\n\n"

            + heading("Recommendation")
            + gpu_health["recommendation"]
        )
    # CPU
    elif intent == "cpu":

        if cpu_health["cpu_usage"] == "Idle":
            return (
                heading("CPU Summary")
                + f"Your CPU is currently idle ({cpu['cpu_usage']}% usage).\n\n"

                + heading("Reason")
                + "The system is processing minimal workload.\n\n"

                + heading("Status")
                + f"{status_color(cpu_health['overall'])}{cpu_health['overall']}{RESET}\n\n"

                + heading("Recommendation")
                + cpu_health["recommendation"]
            )
        return (
            heading("CPU Summary")
            + f"Current CPU usage : {cpu['cpu_usage']}%\n\n"

            + heading("Status")
            + f"{status_color(cpu_health['overall'])}{cpu_health['overall']}{RESET}\n\n"

            + heading("Recommendation")
            + cpu_health["recommendation"]
        )
    # Memory
    elif intent == "memory":
        return (
            heading("Memory Summary")
            + f"Current Memory Usage : {memory['memory_usage']}%\n\n"

            + heading("Status")
            + f"{status_color(memory_health['overall'])}{memory_health['overall']}{RESET}\n\n"

            + heading("Recommendation")
            + memory_health["recommendation"]
        )
    # Disk
    elif intent == "disk":
        return (
            heading("Disk Summary")
            + f"Current Disk Usage : {disk['disk_usage']}%\n\n"

            + heading("Status")
            + f"{status_color(disk_health['overall'])}{disk_health['overall']}{RESET}\n\n"

            + heading("Recommendation")
            + disk_health["recommendation"]
        )

    # Network
    elif intent == "network":
        return (
            heading("Network Summary")

            + heading("Status")
            + f"{status_color(network_health['overall'])}{network_health['overall']}{RESET}\n\n"

            + heading("Recommendation")
            + network_health["recommendation"]
        )

    # ROCm
    elif intent == "rocm":

        if gpu["available"]:
            return (
                heading("ROCm Runtime")
                + f"{GREEN}✓ AMD ROCm successfully detected a compatible GPU.{RESET}\n\n"
                + "The system is ready for GPU accelerated AI workloads."
            )
        return "No compatible ROCm GPU detected."

    # Recommendations
    elif intent == "recommendations":

        recommendations = []

        if gpu_health["recommendation"] != "No action required.":
            recommendations.append(f"GPU: {gpu_health['recommendation']}")

        if cpu_health["recommendation"] != "No action required.":
            recommendations.append(f"CPU: {cpu_health['recommendation']}")

        if memory_health["recommendation"] != "No action required.":
            recommendations.append(f"Memory: {memory_health['recommendation']}")

        if disk_health["recommendation"] not in [
            "No action required.",
            "No action required"
        ]:
            recommendations.append(f"Disk: {disk_health['recommendation']}")

        if network_health["recommendation"] != "No action required.":
            recommendations.append(f"Network: {network_health['recommendation']}")

        if not recommendations:
            return (
                f"{BOLD}{CYAN}Overall Assessment{RESET}\n"
                "────────────────────────────────────────\n"
                "All monitored components are operating normally.\n\n"

                f"{BOLD}{CYAN}Recommendations{RESET}\n"
                "────────────────────────────────────────\n"
                "• No immediate action is required.\n"
                "• GPU is idle because no AI workload is currently running.\n"
                "• CPU utilization is within the normal range.\n"
                "• Memory, disk, and network are healthy.\n\n"

                f"{BOLD}{GREEN}System Status{RESET}\n"
                "────────────────────────────────────────\n"
                "The system is ready for additional workloads."
            )
        return "\n".join(recommendations)

    # Overall
    elif intent == "overall":
        return (
            f"{BOLD}{CYAN}Overall System Health{RESET}\n"
            "══════════════════════════════════════════════════\n\n"

            + f"{BOLD}Status:{RESET} "
            + f"{status_color(system_health['overall'])}"
            + f"{system_health['overall']}{RESET}\n"

            + f"{BOLD}Severity:{RESET} {system_health['severity']}\n\n"

            + heading("Summary")
            + f"{system_health['summary']}\n\n"

            + heading("Component Summary")
            + f"GPU      : {status_color(gpu_health['overall'])}{gpu_health['overall']}{RESET}\n"
            + f"CPU      : {status_color(cpu_health['overall'])}{cpu_health['overall']}{RESET}\n"
            + f"Memory   : {status_color(memory_health['overall'])}{memory_health['overall']}{RESET}\n"
            + f"Disk     : {status_color(disk_health['overall'])}{disk_health['overall']}{RESET}\n"
            + f"Network  : {status_color(network_health['overall'])}{network_health['overall']}{RESET}\n\n"

            + heading("Recommendation")
            + system_health["recommendation"]
        )
    return None
