import os

os.system("clear")


BOLD = "\033[1m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


def status_colour(status):

    status = status.lower()

    if status == "healthy":
        return GREEN

    if status == "warning":
        return YELLOW

    return RED


def one_line_snapshot(
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
):

    print("─" * 78)

    print(
        f"GPU: {status_colour(gpu_health['overall'])}{gpu_health['gpu_usage']} ({gpu['gpu_usage']}%){RESET}"
        f" | CPU: {status_colour(cpu_health['overall'])}{cpu_health['overall']} ({cpu['cpu_usage']}%){RESET}"
        f" | Memory: {status_colour(memory_health['overall'])}{memory_health['overall']} ({memory['memory_usage']}%){RESET}"
        f" | Disk: {status_colour(disk_health['overall'])}{disk_health['overall']} ({disk['disk_usage']}%){RESET}"
        f" | Network: {status_colour(network_health['overall'])}{network_health['overall']}{RESET}"
    )

    print("─" * 78)
    print()

def color(status):

    status = status.lower()

    if status == "healthy":
        return GREEN

    if status == "warning":
        return YELLOW

    return RED


def clear_screen():
    os.system("clear")


def show_dashboard(gpu, gpu_health,
                   cpu, cpu_health,
                   memory, memory_health,
                   disk, disk_health,
                   network, network_health):

    clear_screen()

    print(f"{BOLD}{CYAN}")
    print("==============================================================")
    print("                    GPU GUARDIAN AI")
    print("==============================================================")
    print(RESET)

    print(f"{BOLD}System Snapshot{RESET}")
    print("────────────────────────────────────────")

    print(
        f"GPU      : {color(gpu_health['overall'])}"
        f"{gpu_health['gpu_usage']} ({gpu['gpu_usage']}%)"
        f"{RESET}"
    )

    print(
        f"CPU      : {color(cpu_health['overall'])}"
        f"{cpu_health['overall']} ({cpu['cpu_usage']}%)"
        f"{RESET}"
    )

    print(
        f"Memory   : {color(memory_health['overall'])}"
        f"{memory_health['overall']} ({memory['memory_usage']}%)"
        f"{RESET}"
    )

    print(
        f"Disk     : {color(disk_health['overall'])}"
        f"{disk_health['overall']} ({disk['disk_usage']}%)"
        f"{RESET}"
    )

    print(
        f"Network  : {color(network_health['overall'])}"
        f"{network_health['overall']}"
        f"{RESET}"
    )

    print("\n==============================================================\n")
