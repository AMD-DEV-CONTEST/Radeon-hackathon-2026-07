"""
diagnosis_tool.py

Provides intelligent diagnosis based on
GPU, CPU, Memory, Disk and Network health.
"""


def check_gpu_cpu_correlation(gpu, cpu):
    observations = []

    gpu_usage = gpu.get("gpu_usage", 0)
    cpu_usage = cpu.get("cpu_usage", 0)

    if gpu_usage < 20 and cpu_usage > 80:
        observations.append({
              "severity": "Warning",
              "category": "GPU/CPU",
              "finding": "CPU Bottleneck",
              "root_cause": (
                    # "CPU utilization is high while GPU utilization remains low."
                    "The workload appears to be CPU-bound, indicating that GPU acceleration "      
    "may not be fully utilized or CPU-side processing has become the bottleneck."
              ),
              "impact": (
                     "GPU resources are underutilized and inference performance may be reduced."
              ),
              "recommendation": (
                     "Verify that GPU acceleration is enabled. "
                     "Check whether inference is running on the GPU or if "
                     "CPU preprocessing is becoming the bottleneck."
              )
      })
        #observations.append({
         #   "severity": "Warning",
          #  "category": "GPU/CPU",
          #  "title": "CPU Bottleneck",
          #  "description": (
          #      "CPU utilization is high while GPU utilization is low."
          #  ),
          #  "recommendation": (
          #      "Verify that GPU acceleration is enabled. "
          #      "Check whether inference is running on the GPU or if "
          #      "CPU preprocessing is becoming the bottleneck."
          #  )
       # })

    elif gpu_usage > 90 and cpu_usage < 40:
        observations.append({
            "severity": "Info",
            "category": "GPU/CPU",
            "finding": "GPU Intensive Workload",
            #"title": "GPU Intensive Workload",
            "root_cause":(
                #"CPU utilization is low and GPU utilization is high" 
                "The workload is primarily executing on the GPU, which is expected for "
    "GPU-accelerated AI inference or compute-intensive tasks."
            ),
            "impact": (
                "High GPU utilization is expected during AI inference, but prolonged usage "
    "may increase GPU temperature, power consumption, and inference latency."
            ),
            "recommendation": (
                "This is expected for GPU-heavy inference workloads. "
                "Continue monitoring GPU temperature and VRAM utilization."
            )
        })

    return observations


def check_memory_cpu_correlation(memory, cpu):
    """
    Memory-specific diagnosis rules.
    """
    observations = []

    memory_usage = memory.get("memory_usage", 0)
    cpu_usage = cpu.get("cpu_usage", 0)

    # Possible memory leak
    if memory_usage > 90 and cpu_usage < 40:
        observations.append({
            "severity": "Warning",
            "category": "Memory",
            "finding": "Possible Memory Leak",
            "root_cause": (
                "Memory consumption remains high despite low CPU activity, indicating possible excessive memory allocation, caching, or a memory leak."
            ),
            "impact": (
                "Sustained high memory usage may reduce system responsiveness and eventually lead to out-of-memory conditions."
            ),
            "recommendation": (
                "Investigate running processes for memory leaks or excessive caching."
            )
        })

    # High memory utilization
    elif memory_usage > 80:
        observations.append({
            "severity": "Warning",
            "category": "Memory",
            "finding": "High Memory Utilization",
            "root_cause": (
                "System memory utilization has exceeded the recommended operating threshold."
            ),
            "impact": (
                "Applications may experience slower response times due to memory pressure."
            ),
            "recommendation": (
                "Review memory-intensive applications and release unused memory."
            )
        })

    # Memory idle
    elif memory_usage < 20:
        observations.append({
            "severity": "Info",
            "category": "Memory",
            "finding": "Memory Operating Normally",
            "root_cause": (
                "Memory utilization is well within normal operating limits."
            ),
            "impact": (
                "Sufficient memory resources are available for additional workloads."
            ),
            "recommendation": (
                "No action required."
            )
        })

    return observations

def check_disk_health(disk):
    """
    Disk-specific diagnosis rules.
    """
    observations = []

    disk_usage = disk.get("disk_usage", 0)

    # Critical disk usage
    if disk_usage > 95:
        observations.append({
            "severity": "Critical",
            "category": "Disk",
            "finding": "Disk Critically Full",
            "root_cause": (
                "Available disk space has reached a critical level."
            ),
            "impact": (
                "Applications may fail to write data, logging may stop, and system stability may be affected."
            ),
            "recommendation": (
                "Immediately free disk space or extend storage capacity."
            )
        })

    # High disk usage
    elif disk_usage > 90:
        observations.append({
            "severity": "Warning",
            "category": "Disk",
            "finding": "Disk Almost Full",
            "root_cause": (
                "Available disk capacity has fallen below the recommended operating threshold."
            ),
            "impact": (
                "Low available disk space may affect application performance, logging, and future data writes."
            ),
            "recommendation": (
                "Free up storage space before it impacts system performance."
            )
        })

    # Healthy disk
    elif disk_usage < 70:
        observations.append({
            "severity": "Info",
            "category": "Disk",
            "finding": "Disk Operating Normally",
            "root_cause": (
                "Disk utilization is within normal operating limits."
            ),
            "impact": (
                "Sufficient storage capacity is available."
            ),
            "recommendation": (
                "No action required."
            )
        })

    return observations

def check_network_health(network):
    """
    Network-specific diagnosis rules.
    """
    observations = []

    errors = (
        network.get("errors_in", 0) +
        network.get("errors_out", 0)
    )

    drops = (
        network.get("drops_in", 0) +
        network.get("drops_out", 0)
    )

    # Network errors
    if errors > 0 or drops > 0:
        observations.append({
            "severity": "Warning",
            "category": "Network",
            "finding": "Network Anomaly",
            "root_cause": (
                "Network interface statistics indicate packet drops or transmission errors."
            ),
            "impact": (
                "Packet loss or transmission errors may result in degraded network performance, increased latency, or unstable connections."
            ),
            "recommendation": (
                "Check network connectivity, interface health, switch/router status, and interface statistics."
            )
        })

    else:
        observations.append({
            "severity": "Info",
            "category": "Network",
            "finding": "Network Operating Normally",
            "root_cause": (
                "No packet drops or transmission errors were detected."
            ),
            "impact": (
                "Network connectivity appears stable."
            ),
            "recommendation": (
                "No action required."
            )
        })

    return observations

def check_gpu_rules(gpu, gpu_health):
    """
    GPU-specific diagnosis rules.
    """
    observations = []

    gpu_usage = gpu.get("gpu_usage", 0)
    edge_temp = gpu.get("edge_temp", 0)
    vram_usage = gpu.get("vram_usage", 0)

    # GPU Idle
    if gpu_usage < 5:
        observations.append({
            "severity": "Info",
            "category": "GPU",
            "finding": "GPU Idle",
            "root_cause": (
                "The GPU is currently processing little or no workload."
            ),
            "impact": (
                "This is expected when no AI inference or compute-intensive tasks are running."
            ),
            "recommendation": (
                "No action required unless GPU acceleration is expected."
            )
        })

    # GPU Busy
    elif gpu_usage > 90:
        observations.append({
            "severity": "Info",
            "category": "GPU",
            "finding": "High GPU Utilization",
            "root_cause": (
                "The GPU is actively processing compute-intensive workloads."
            ),
            "impact": (
                "High GPU utilization is expected during AI inference or model execution."
            ),
            "recommendation": (
                "Continue monitoring GPU temperature and VRAM utilization."
            )
        })

    # High Temperature
    if edge_temp > 80:
        observations.append({
            "severity": "Warning",
            "category": "GPU",
            "finding": "High GPU Temperature",
            "root_cause": (
                "GPU temperature has exceeded the recommended operating range."
            ),
            "impact": (
                "Prolonged high temperatures may reduce performance through thermal throttling."
            ),
            "recommendation": (
                "Improve cooling, verify fan operation, and reduce sustained workload if necessary."
            )
        })

    # High VRAM
    if vram_usage > 90:
        observations.append({
            "severity": "Warning",
            "category": "GPU",
            "finding": "High VRAM Utilization",
            "root_cause": (
                "Most of the available GPU memory is currently allocated."
            ),
            "impact": (
                "Future workloads may fail due to insufficient GPU memory."
            ),
            "recommendation": (
                "Reduce model size, batch size, or release unused GPU memory."
            )
        })

    return observations

#def check_cpu_rules(cpu, cpu_health):
#    """
#    CPU-specific diagnosis rules.
#    """
#    return []

def check_cpu_rules(cpu, cpu_health):
    """
    CPU-specific diagnosis rules.
    """
    observations = []

    cpu_usage = cpu.get("cpu_usage", 0)

    # Critical CPU utilization
    if cpu_usage > 95:
        observations.append({
            "severity": "Critical",
            "category": "CPU",
            "finding": "CPU Overloaded",
            "root_cause": (
                "CPU utilization has reached a critical level."
            ),
            "impact": (
                "Applications may become slow or unresponsive due to CPU resource exhaustion."
            ),
            "recommendation": (
                "Identify CPU-intensive processes and reduce workload or increase compute resources."
            )
        })

    # High CPU utilization
    elif cpu_usage > 80:
        observations.append({
            "severity": "Warning",
            "category": "CPU",
            "finding": "High CPU Utilization",
            "root_cause": (
                "The CPU is processing a sustained high workload."
            ),
            "impact": (
                "System responsiveness and application performance may degrade."
            ),
            "recommendation": (
                "Review running processes and optimize CPU-intensive workloads."
            )
        })

    # CPU idle
    elif cpu_usage < 5:
        observations.append({
            "severity": "Info",
            "category": "CPU",
            "finding": "CPU Idle",
            "root_cause": (
                "The CPU is currently processing minimal workload."
            ),
            "impact": (
                "This is expected when the system is not executing compute-intensive tasks."
            ),
            "recommendation": (
                "No action required."
            )
        })

    return observations

#def check_rocm_rules(gpu, gpu_health):
#    """
#    AMD ROCm specific diagnosis rules.
#    """
def check_rocm_rules(gpu, gpu_health):
    """
    AMD ROCm specific diagnosis rules.
    """
    observations = []

    available = gpu.get("available", False)
    device = gpu.get("device", "")

    if available:
        observations.append({
            "severity": "Info",
            "category": "ROCm",
            "finding": "ROCm Runtime Available",
            "root_cause": (
                "AMD ROCm runtime successfully detected a compatible GPU."
            ),
            "impact": (
                "The system is ready for GPU-accelerated AI inference workloads."
            ),
            "recommendation": (
                "No action required."
            )
        })
    else:
        observations.append({
            "severity": "Critical",
            "category": "ROCm",
            "finding": "ROCm Runtime Unavailable",
            "root_cause": (
                "AMD ROCm runtime could not detect a compatible GPU."
            ),
            "impact": (
                "GPU acceleration is unavailable and AI workloads will execute on the CPU."
            ),
            "recommendation": (
                "Verify ROCm installation, GPU drivers, and hardware compatibility."
            )
        })

    return observations

def generate_diagnosis(
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
    system_health
):
    """
    Generate intelligent diagnosis.

    Returns:
        list[dict]
    """

    diagnosis = []

    # Overall health
    diagnosis.append({
        "severity": system_health.get("severity", "Low"),
        "category": "System",
       # "title": "Overall System Health",
        "finding": "Overall System Health",
       # "root_cause": "System health calculatrd from all monitored resources.",
        "root_cause":(
            "Overall health status is derived from GPU, CPU, Memory, Disk and Network telemetry."
        ),
        "impact": system_health.get("summary",""),
      # "description": system_health.get("summary", ""),
        "recommendation": system_health.get("recommendation", "")
    })

    # Correlation Rules
    diagnosis.extend(check_gpu_cpu_correlation(gpu, cpu))
    diagnosis.extend(check_memory_cpu_correlation(memory, cpu))
    diagnosis.extend(check_disk_health(disk))
    diagnosis.extend(check_network_health(network))
    diagnosis.extend(check_gpu_rules(gpu, gpu_health))
    diagnosis.extend(check_cpu_rules(cpu, cpu_health))
    diagnosis.extend(check_rocm_rules(gpu, gpu_health))

    # No issues found
    if len(diagnosis) == 1:
        diagnosis.append({
            "severity": "Info",
            "category": "System",
            "finding": "No Issues Detected",
            "root_cause": (
                "No performance, stability, or resource utilization issues were detected."
            ),
            "impact": (
                "All monitored system resources are operating normally."
            ),
            "recommendation": "Continue routine monitoring."
        })

    return diagnosis
