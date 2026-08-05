"""
ROCm 工具模块 - AMD GPU 检测、监控与优化工具
"""

import subprocess
import os
import logging
from typing import Optional, Dict, List, Tuple

logger = logging.getLogger(__name__)


def is_rocm_available() -> bool:
    """检测 ROCm 是否可用"""
    try:
        import torch
        cuda_ok = torch.cuda.is_available()
        # 检查 torch.version.rocm 属性是否存在（部分 ROCm 编译版本可能没有该属性）
        rocm_ver = getattr(torch.version, 'rocm', None)
        return cuda_ok and (rocm_ver is not None or 'rocm' in torch.__version__.lower())
    except ImportError:
        return False
    except Exception:
        return False


def get_rocm_version() -> Optional[str]:
    """获取 ROCm 版本号"""
    try:
        import torch
        if torch.cuda.is_available() and torch.version.rocm:
            return torch.version.rocm
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["rocminfo", "--version"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_gpu_info() -> List[Dict[str, str]]:
    """获取 GPU 信息列表"""
    gpus = []
    try:
        result = subprocess.run(
            ["rocm-smi", "--showproductname", "--json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            for gpu_id, info in data.items():
                if gpu_id.startswith("card"):
                    gpus.append({
                        "id": gpu_id,
                        "name": info.get("Product Name", "Unknown"),
                        "vram": info.get("VRAM Total", "N/A"),
                    })
    except Exception:
        pass

    if not gpus:
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    props = torch.cuda.get_device_properties(i)
                    gpus.append({
                        "id": f"cuda:{i}",
                        "name": torch.cuda.get_device_name(i),
                        "vram": f"{props.total_memory / 1024**3:.1f} GB",
                    })
        except Exception:
            pass

    return gpus


def get_gpu_status() -> Dict[str, str]:
    """获取 GPU 实时状态（显存、温度、使用率）"""
    status = {}
    try:
        result = subprocess.run(
            ["rocm-smi", "--json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            for gpu_id, info in data.items():
                if gpu_id.startswith("card"):
                    status["gpu"] = gpu_id
                    status["温度"] = info.get("Temperature (Sensor edge) (C)", "N/A") + "°C"
                    status["显存使用"] = info.get("VRAM Total Memory (VRAM)", "N/A")
                    status["显存剩余"] = info.get("VRAM Free Memory (VRAM)", "N/A")
                    status["利用率"] = info.get("GPU Use (%)", "N/A") + "%"
                    break
    except Exception:
        status = {"状态": "rocm-smi 不可用"}

    try:
        import torch
        if torch.cuda.is_available():
            i = 0
            allocated = torch.cuda.memory_allocated(i) / 1024**3
            reserved = torch.cuda.memory_reserved(i) / 1024**3
            status["PyTorch 已分配显存"] = f"{allocated:.2f} GB"
            status["PyTorch 预留显存"] = f"{reserved:.2f} GB"
    except Exception:
        pass

    return status


def get_optimal_device() -> str:
    """获取最优设备（优先 ROCm GPU）"""
    if is_rocm_available():
        return "cuda"
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def get_device_map() -> Dict[str, str]:
    """获取 Diffusers 模型加载的设备映射"""
    device = get_optimal_device()
    if device == "cuda":
        return {"device_map": "auto", "torch_dtype": "float16"}
    return {"device_map": "cpu"}


def optimize_memory():
    """应用 ROCm/PyTorch 内存优化"""
    try:
        import torch

        # 启用 TF32 加速（AMD CDNA 架构支持）
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True

        # 启用 cuDNN 自动调优
        if hasattr(torch.backends, 'cudnn'):
            torch.backends.cudnn.benchmark = True

        logger.info("内存优化已应用")
    except Exception as e:
        logger.warning(f"内存优化失败: {e}")


def clear_gpu_cache():
    """清理 GPU 缓存"""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.info("GPU 缓存已清理")
    except Exception:
        pass


def format_gpu_info() -> str:
    """格式化显示 GPU 信息"""
    lines = []
    lines.append("=" * 50)
    lines.append("🖥️  AMD GPU 状态")
    lines.append("=" * 50)

    if is_rocm_available():
        lines.append(f"✅ ROCm 版本: {get_rocm_version()}")
    else:
        lines.append("❌ ROCm 未检测到")

    gpus = get_gpu_info()
    if gpus:
        for gpu in gpus:
            lines.append(f"  GPU: {gpu['name']} | 显存: {gpu['vram']}")
    else:
        lines.append("  未检测到 GPU")

    status = get_gpu_status()
    for k, v in status.items():
        lines.append(f"  {k}: {v}")

    lines.append("=" * 50)
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(format_gpu_info())
