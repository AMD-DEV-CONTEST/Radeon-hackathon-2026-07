"""
系统监控模块 — CPU、GPU、内存、磁盘实时信息采集
"""

import os
import sys
import time
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SystemInfo:
    """系统信息快照"""
    timestamp: float = 0.0
    # CPU
    cpu_model: str = ""
    cpu_cores: int = 0
    cpu_usage_percent: float = 0.0
    cpu_load_1m: float = 0.0
    cpu_load_5m: float = 0.0
    cpu_load_15m: float = 0.0
    # 内存
    memory_total_gb: float = 0.0
    memory_used_gb: float = 0.0
    memory_available_gb: float = 0.0
    memory_percent: float = 0.0
    swap_total_gb: float = 0.0
    swap_used_gb: float = 0.0
    # 磁盘
    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0
    disk_free_gb: float = 0.0
    disk_percent: float = 0.0
    # GPU
    gpu_count: int = 0
    gpu_info: list = field(default_factory=list)
    # 系统
    os_name: str = ""
    kernel: str = ""
    hostname: str = ""
    uptime_hours: float = 0.0
    # Python 环境
    python_version: str = ""
    torch_version: str = ""
    rocm_version: str = ""
    diffusers_version: str = ""
    gradio_version: str = ""
    accelerate_version: str = ""
    transformers_version: str = ""
    cuda_available: bool = False


class SystemMonitor:
    """系统监控器"""

    def __init__(self):
        self._cache = {}
        self._cache_time = {}
        self._cache_ttl = 2.0  # 缓存 2 秒

    def _get_cached(self, key: str, func, *args, **kwargs):
        now = time.time()
        if key in self._cache_time and (now - self._cache_time[key]) < self._cache_ttl:
            return self._cache[key]
        result = func(*args, **kwargs)
        self._cache[key] = result
        self._cache_time[key] = now
        return result

    def get_system_info(self) -> SystemInfo:
        """获取系统信息快照"""
        info = SystemInfo()
        info.timestamp = time.time()

        # --- CPU ---
        try:
            if os.path.exists("/proc/cpuinfo"):
                with open("/proc/cpuinfo") as f:
                    content = f.read()
                lines = content.split("\n")
                for line in lines:
                    if line.startswith("model name"):
                        info.cpu_model = line.split(":")[-1].strip()
                        break
                info.cpu_cores = sum(1 for l in lines if l.startswith("processor"))
        except Exception:
            pass

        try:
            import psutil
            info.cpu_usage_percent = psutil.cpu_percent(interval=0.1)
            load = os.getloadavg()
            info.cpu_load_1m, info.cpu_load_5m, info.cpu_load_15m = load
        except Exception:
            pass

        # --- 内存 ---
        try:
            import psutil
            mem = psutil.virtual_memory()
            info.memory_total_gb = mem.total / 1024**3
            info.memory_used_gb = mem.used / 1024**3
            info.memory_available_gb = mem.available / 1024**3
            info.memory_percent = mem.percent
            swap = psutil.swap_memory()
            info.swap_total_gb = swap.total / 1024**3
            info.swap_used_gb = swap.used / 1024**3
        except Exception:
            pass

        # --- 磁盘 ---
        try:
            import psutil
            disk = psutil.disk_usage("/")
            info.disk_total_gb = disk.total / 1024**3
            info.disk_used_gb = disk.used / 1024**3
            info.disk_free_gb = disk.free / 1024**3
            info.disk_percent = disk.percent
        except Exception:
            pass

        # --- GPU ---
        try:
            import torch
            info.cuda_available = torch.cuda.is_available()
            if torch.cuda.is_available():
                info.gpu_count = torch.cuda.device_count()
                info.rocm_version = getattr(torch.version, "rocm", "N/A") or "N/A"
                for i in range(info.gpu_count):
                    props = torch.cuda.get_device_properties(i)
                    try:
                        used = torch.cuda.memory_allocated(i) / 1024**3
                        total = props.total_memory / 1024**3
                    except Exception:
                        used = 0
                        total = props.total_memory / 1024**3
                    info.gpu_info.append({
                        "index": i,
                        "name": torch.cuda.get_device_name(i),
                        "total_gb": round(total, 1),
                        "used_gb": round(used, 1),
                        "free_gb": round(total - used, 1),
                        "usage_pct": round(used / total * 100, 1) if total > 0 else 0,
                    })
        except Exception:
            pass

        # 补充通过 rocm-smi 获取 GPU 温度等信息
        if not info.gpu_info:
            try:
                result = subprocess.run(
                    ["rocm-smi", "--json"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    import json
                    data = json.loads(result.stdout)
                    for gpu_id, gpu_data in data.items():
                        if gpu_id.startswith("card"):
                            info.gpu_info.append({
                                "index": gpu_id,
                                "name": gpu_data.get("Product Name", "AMD GPU"),
                                "temperature": gpu_data.get("Temperature (Sensor edge) (C)", "N/A"),
                                "vram_total": gpu_data.get("VRAM Total Memory (VRAM)", "N/A"),
                                "vram_used": gpu_data.get("VRAM Used Memory (VRAM)", "N/A"),
                                "power": gpu_data.get("Power Draw", "N/A"),
                            })
                            info.gpu_count = len(info.gpu_info)
            except Exception:
                pass

        # --- 系统 ---
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME"):
                            info.os_name = line.split("=")[-1].strip().strip('"')
                            break
            info.kernel = os.uname().release
            info.hostname = os.uname().nodename
            with open("/proc/uptime") as f:
                uptime_sec = float(f.read().split()[0])
                info.uptime_hours = round(uptime_sec / 3600, 1)
        except Exception:
            pass

        # --- 工具版本 ---
        info.python_version = sys.version.split()[0]

        try:
            import torch
            info.torch_version = torch.__version__
        except Exception:
            info.torch_version = "未安装"

        try:
            import diffusers
            info.diffusers_version = diffusers.__version__
        except Exception:
            info.diffusers_version = "未安装"

        try:
            import gradio
            info.gradio_version = gradio.__version__
        except Exception:
            info.gradio_version = "未安装"

        try:
            import accelerate
            info.accelerate_version = accelerate.__version__
        except Exception:
            info.accelerate_version = "未安装"

        try:
            import transformers
            info.transformers_version = transformers.__version__
        except Exception:
            info.transformers_version = "未安装"

        return info

    def format_html(self) -> str:
        """格式化为 HTML 展示"""
        info = self.get_system_info()
        lines = []

        lines.append("### 🖥️ 系统信息")
        lines.append(f"| 项目 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 主机名 | `{info.hostname}` |")
        lines.append(f"| 操作系统 | {info.os_name} |")
        lines.append(f"| 内核 | `{info.kernel}` |")
        lines.append(f"| 运行时间 | {info.uptime_hours} 小时 |")

        lines.append("\n### 🧠 CPU")
        lines.append(f"| 项目 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 型号 | `{info.cpu_model}` |")
        lines.append(f"| 核心数 | {info.cpu_cores} |")
        lines.append(f"| 使用率 | {info.cpu_usage_percent:.1f}% |")
        lines.append(f"| 负载(1/5/15m) | {info.cpu_load_1m:.2f} / {info.cpu_load_5m:.2f} / {info.cpu_load_15m:.2f} |")

        lines.append("\n### 💾 内存")
        lines.append(f"| 项目 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 总量 | {info.memory_total_gb:.1f} GB |")
        lines.append(f"| 已用 | {info.memory_used_gb:.1f} GB ({info.memory_percent:.1f}%) |")
        lines.append(f"| 可用 | {info.memory_available_gb:.1f} GB |")
        if info.swap_total_gb > 0:
            lines.append(f"| 交换 | {info.swap_used_gb:.1f} / {info.swap_total_gb:.1f} GB |")

        lines.append("\n### 💽 磁盘")
        lines.append(f"| 项目 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 总量 | {info.disk_total_gb:.1f} GB |")
        lines.append(f"| 已用 | {info.disk_used_gb:.1f} GB ({info.disk_percent:.1f}%) |")
        lines.append(f"| 可用 | {info.disk_free_gb:.1f} GB |")

        lines.append("\n### 🎮 GPU")
        if info.gpu_info:
            for gpu in info.gpu_info:
                lines.append(f"\n**GPU {gpu.get('index', 0)}**: `{gpu.get('name', 'Unknown')}`")
                if 'total_gb' in gpu:
                    lines.append(f"- 显存: {gpu['used_gb']:.1f} / {gpu['total_gb']:.1f} GB ({gpu['usage_pct']:.1f}%)")
                if 'temperature' in gpu:
                    lines.append(f"- 温度: {gpu['temperature']}°C")
                if 'vram_total' in gpu:
                    lines.append(f"- VRAM: {gpu.get('vram_total', 'N/A')}")
                if 'power' in gpu:
                    lines.append(f"- 功耗: {gpu['power']}")
        else:
            lines.append("\n未检测到 GPU")
        lines.append(f"\n- ROCm: `{info.rocm_version or 'N/A'}`")
        lines.append(f"- CUDA 可用: `{info.cuda_available}`")

        lines.append("\n### 📦 工具版本")
        lines.append(f"| 工具 | 版本 |")
        lines.append(f"|------|------|")
        lines.append(f"| Python | `{info.python_version}` |")
        lines.append(f"| PyTorch | `{info.torch_version}` |")
        lines.append(f"| Diffusers | `{info.diffusers_version}` |")
        lines.append(f"| Gradio | `{info.gradio_version}` |")
        lines.append(f"| Accelerate | `{info.accelerate_version}` |")
        lines.append(f"| Transformers | `{info.transformers_version}` |")
        lines.append(f"| ROCm | `{info.rocm_version}` |")

        return "\n".join(lines)


# 全局单例
global_monitor = SystemMonitor()