import os
import time

def show_banner():
    os.system("clear")

    CYAN = "\033[1;36m"
    GREEN = "\033[1;32m"
    YELLOW = "\033[1;33m"
    WHITE = "\033[1;37m"
    NC = "\033[0m"

    print(CYAN)
    print("======================================================================")
    print()
    print("  ██████╗ ██████╗ ██╗   ██╗     ██████╗ ██╗   ██╗ █████╗ ██████╗ ██████╗ ")
    print(" ██╔════╝ ██╔══██╗██║   ██║    ██╔════╝ ██║   ██║██╔══██╗██╔══██╗██╔══██╗")
    print(" ██║  ███╗██████╔╝██║   ██║    ██║  ███╗██║   ██║███████║██████╔╝██║  ██║")
    print(" ██║   ██║██╔═══╝ ██║   ██║    ██║   ██║██║   ██║██╔══██║██╔══██╗██║  ██║")
    print(" ╚██████╔╝██║     ╚██████╔╝    ╚██████╔╝╚██████╔╝██║  ██║██║  ██║██████╔╝")
    print("  ╚═════╝ ╚═╝      ╚═════╝      ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ")
    print()

    print(WHITE + "           Private AI Agent for Intelligent System Health Monitoring")
    print()
    print(GREEN + "                 Powered by AMD Radeon™ GPU + ROCm")
    print()
    print(CYAN + "======================================================================" + NC)

    time.sleep(1)

    for message in [
        "Initializing AI Engine",
        "Loading System Telemetry",
        "Loading AI Model",
    ]:
        print(YELLOW + message, end="", flush=True)
        for _ in range(3):
            print(".", end="", flush=True)
            time.sleep(0.5)
        print()

    print()
    print(GREEN + "✓ GPU Guardian AI is Ready" + NC)

    time.sleep(1.5)

    os.system("clear")
