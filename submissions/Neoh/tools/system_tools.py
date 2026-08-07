import logging
import subprocess
import psutil
from typing import Dict, Any
from .registry import ToolDefinition, registry

logger = logging.getLogger(__name__)


def get_system_info() -> Dict[str, Any]:
    try:
        cpu_percent = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        
        info = {
            "success": True,
            "cpu": {
                "percent": cpu_percent,
                "cores": psutil.cpu_count(logical=False),
                "logical_cores": psutil.cpu_count(logical=True),
            },
            "memory": {
                "total_gb": round(memory.total / (1024**3), 2),
                "used_gb": round(memory.used / (1024**3), 2),
                "available_gb": round(memory.available / (1024**3), 2),
                "percent": memory.percent,
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": disk.percent,
            },
        }
        
        return info
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_gpu_info() -> Dict[str, Any]:
    try:
        import subprocess
        result = subprocess.run(
            ["rocm-smi", "--showproductname", "--showmeminfo", "vram"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        if result.returncode == 0:
            return {"success": True, "output": result.stdout}
        else:
            return {"success": False, "error": "ROCm GPU 信息获取失败", "stderr": result.stderr}
    except FileNotFoundError:
        return {"success": False, "error": "rocm-smi 命令未找到，可能未安装 ROCm"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "rocm-smi 命令超时（>10s），GPU 驱动可能异常"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_process_list() -> Dict[str, Any]:
    try:
        processes = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                processes.append({
                    "pid": proc.info["pid"],
                    "name": proc.info["name"],
                    "cpu_percent": proc.info["cpu_percent"],
                    "memory_percent": proc.info["memory_percent"],
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        return {"success": True, "processes": processes[:20]}
    except Exception as e:
        return {"success": False, "error": str(e)}


registry.register_tool(ToolDefinition(
    name="get_system_info",
    description="获取系统信息（CPU、内存、磁盘）",
    parameters={},
    function=get_system_info,
    requires_approval=False,
))

registry.register_tool(ToolDefinition(
    name="get_gpu_info",
    description="获取 GPU 信息（ROCm）",
    parameters={},
    function=get_gpu_info,
    requires_approval=False,
))

registry.register_tool(ToolDefinition(
    name="get_process_list",
    description="获取进程列表",
    parameters={},
    function=get_process_list,
    requires_approval=False,
))