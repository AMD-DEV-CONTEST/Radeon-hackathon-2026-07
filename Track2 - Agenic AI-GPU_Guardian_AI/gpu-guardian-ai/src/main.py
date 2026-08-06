"""
GPU Guardian AI

Application Entry Point
"""

import os
import time

from utils.colors import *
from utils.dashboard import show_dashboard
from agents.supervisor import SupervisorAgent
from utils.banner import show_banner
from tools.gpu_tool import get_gpu_status
from tools.health_tool import evaluate_gpu_health

from tools.cpu_tool import get_cpu_status
from tools.cpu_health_tool import evaluate_cpu_health

from tools.memory_tool import get_memory_status
from tools.memory_health_tool import evaluate_memory_health

from tools.disk_tool import get_disk_status
from tools.disk_health_tool import evaluate_disk_health

from tools.network_tool import get_network_status
from tools.network_health_tool import evaluate_network_health

from utils.dashboard import one_line_snapshot


def main():

    agent = SupervisorAgent()

    gpu = get_gpu_status()
    gpu_health = evaluate_gpu_health(gpu)

    cpu = get_cpu_status()
    cpu_health = evaluate_cpu_health(cpu)

    memory = get_memory_status()
    memory_health = evaluate_memory_health(memory)

    disk = get_disk_status()
    disk_health = evaluate_disk_health(disk)

    network = get_network_status()
    network_health = evaluate_network_health(network)

    one_line_snapshot(
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
    )

    while True:

        question = input(f"\n{BOLD}{PROMPT}GPU Guardian AI Assistant{RESET} > ")
        
        if question.lower() == "exit":
            os.system("clear")

            print(f"\n{GREEN}Thank you for using GPU Guardian AI.{RESET}")
            time.sleep(2)
            os.system("clear")

            break


        #print("Question")
        #print("────────────────────────────────────────")
        #print(question)

        #print(f"\n{CYAN}Analyzing system telemetry...{RESET}\n")
        print(f"\n{CYAN}Collecting telemetry and generating AI insights...{RESET}\n")
        response = agent.process(question)

        print(response)

show_banner()

print(f"{BOLD}{LABEL}Model      :{RESET} {VALUE}Qwen2.5-3B-Instruct{RESET}")
print(f"{BOLD}{LABEL}Framework  :{RESET} {VALUE}PyTorch + ROCm{RESET}")
print(f"{BOLD}{LABEL}GPU        :{RESET} {GPU}AMD Radeon™{RESET}")
print(f"{BOLD}{LABEL}Inference  :{RESET} {LOCAL}Local{RESET}")
print(f"{BOLD}{LABEL}Version    :{RESET} {VALUE}Hackathon Demo v1.0{RESET}")

if __name__ == "__main__":
    main()

