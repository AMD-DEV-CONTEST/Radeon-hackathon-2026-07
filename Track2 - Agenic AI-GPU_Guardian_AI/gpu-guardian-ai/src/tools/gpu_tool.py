"""
gpu_tool.py

Collects live GPU metrics from AMD ROCm SMI
and PyTorch.
"""

import subprocess
import re
import torch


def collect_gpu_metrics():
    """
    Executes rocm-smi and returns its output.
    """

    result = subprocess.run(
        [
            "rocm-smi",
            "--showtemp",
            "--showuse",
            "--showmemuse",
            "--showpower",
        ],
        capture_output=True,
        text=True,
    )

    return result.stdout


def parse_metric(pattern, text, default=0.0):
    """
    Extracts the first regex match from text.
    """

    match = re.search(pattern, text)

    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return default

    return default


def get_gpu_status():
    """
    Collects live GPU metrics and device information.
    """

    output = collect_gpu_metrics()

    gpu = {
        "edge_temp": parse_metric(
            r"Sensor edge\) \(C\): ([0-9.]+)", output
        ),
        "junction_temp": parse_metric(
            r"Sensor junction\) \(C\): ([0-9.]+)", output
        ),
        "memory_temp": parse_metric(
            r"Sensor memory\) \(C\): ([0-9.]+)", output
        ),
        "power": parse_metric(
            r"Average Graphics Package Power \(W\): ([0-9.]+)", output
        ),
        "gpu_usage": parse_metric(
            r"GPU use \(%\): ([0-9.]+)", output
        ),
        "vram_usage": parse_metric(
            r"GPU Memory Allocated \(VRAM%\): ([0-9.]+)", output
        ),
    }

    if torch.cuda.is_available():
        gpu["available"] = True
        gpu["device"] = torch.cuda.get_device_name(0)
        gpu["device_count"] = torch.cuda.device_count()
    else:
        gpu["available"] = False
        gpu["device"] = None
        gpu["device_count"] = 0

    return gpu
