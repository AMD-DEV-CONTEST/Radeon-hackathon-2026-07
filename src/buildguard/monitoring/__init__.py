"""Hardware monitoring adapters."""

from buildguard.monitoring.amd_smi import AmdSmiMonitor
from buildguard.monitoring.base import CompositeMonitor
from buildguard.monitoring.nvidia_smi import NvidiaSmiMonitor
from buildguard.monitoring.process_monitor import ProcessMonitor
from buildguard.monitoring.rocm_smi import RocmSmiMonitor

__all__ = [
    "AmdSmiMonitor",
    "CompositeMonitor",
    "NvidiaSmiMonitor",
    "ProcessMonitor",
    "RocmSmiMonitor",
]
