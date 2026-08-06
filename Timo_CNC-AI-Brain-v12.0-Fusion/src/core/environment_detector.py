"""
环境探测器 — 自动探测 CPU/GPU/内存/模型/Skill/Expert。
零硬编码路径，完全基于运行时发现。
所有输出为标准 JSON。
"""
import os
import json
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any


class EnvironmentDetector:
    """自动探测运行环境。零硬编码。"""

    def __init__(self, project_root: Optional[Path] = None):
        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent.parent
        self.project_root = project_root

    def detect(self) -> Dict[str, Any]:
        """完整环境探测，返回标准 JSON dict。"""
        result = {
            "hostname": platform.node(),
            "os": platform.system(),
            "os_release": platform.release(),
            "cpu": self._detect_cpu(),
            "memory_gb": self._detect_memory(),
            "disk_free_gb": self._detect_disk(),
            "gpu": self._detect_gpu(),
            "models": self._discover_models(),
            "skills": self._discover_skills(),
            "experts": self._discover_experts(),
            "ollama": self._detect_ollama(),
        "occ": self._detect_occ(),
        }
        return result

    def get_json_report(self) -> str:
        """返回标准 JSON 字符串。所有模块间通信使用此格式。"""
        return json.dumps(self.detect(), ensure_ascii=False, indent=2)

    # ── CPU ──────────────────────────────────────────

    def _detect_cpu(self) -> Dict[str, Any]:
        info = {
            "brand": platform.processor() or "Unknown",
            "cores_physical": os.cpu_count() or 1,
            "architecture": platform.machine(),
        }
        try:
            with open("/proc/cpuinfo") as f:
                content = f.read().lower()
            info["avx2"] = "avx2" in content
            info["avx512"] = "avx512" in content
        except Exception:
            info["avx2"] = False
            info["avx512"] = False
        return info

    # ── 内存 ──────────────────────────────────────────

    def _detect_memory(self) -> float:
        """跨平台物理内存探测 (GB)。Windows 用 ctypes GlobalMemoryStatusEx，
        POSIX 优先 psutil(若已安装)，否则 os.sysconf。"""
        # Windows: os.sysconf 不存在，改用 GlobalMemoryStatusEx
        if os.name == "nt":
            try:
                import ctypes

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                    return round(stat.ullTotalPhys / (1024**3), 1)
            except Exception:
                pass
            return 0.0
        # POSIX: 优先 psutil(可选依赖，未安装则回退 sysconf)
        try:
            import psutil
            return round(psutil.virtual_memory().total / (1024**3), 1)
        except Exception:
            pass
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            total_pages = os.sysconf("SC_PHYS_PAGES")
            return round(page_size * total_pages / (1024**3), 1)
        except Exception:
            return 0.0

    # ── 磁盘 ──────────────────────────────────────────

    def _detect_disk(self) -> float:
        """跨平台磁盘可用空间探测 (GB)。优先 shutil.disk_usage
        (标准库、Windows/POSIX 通用)，失败再兜底 os.statvfs(仅 POSIX)。"""
        try:
            usage = shutil.disk_usage(str(self.project_root))
            return round(usage.free / (1024**3), 1)
        except Exception:
            pass
        try:
            stat = os.statvfs(self.project_root)
            return round(stat.f_frsize * stat.f_bavail / (1024**3), 1)
        except Exception:
            return 0.0

    # ── GPU ──────────────────────────────────────────

    def _detect_gpu(self) -> List[Dict[str, Any]]:
        gpus: List[Dict[str, Any]] = []
        # NVIDIA (pynvml)
        try:
            import pynvml
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            for i in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                gpus.append({
                    "vendor": "NVIDIA",
                    "name": pynvml.nvmlDeviceGetName(handle).decode() if isinstance(pynvml.nvmlDeviceGetName(handle), bytes) else pynvml.nvmlDeviceGetName(handle),
                    "vram_gb": round(mem.total / (1024**3), 1),
                    "vram_free_gb": round(mem.free / (1024**3), 1),
                })
            pynvml.nvmlShutdown()
            if gpus:
                return gpus
        except Exception:
            pass

        # AMD ROCm (rocm-smi)
        try:
            r = subprocess.run(["rocm-smi", "--showproductname"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                gpus.append({"vendor": "AMD", "name": "ROCm GPU", "vram_gb": 0})
                return gpus
        except Exception:
            pass

        # Intel (clinfo)
        try:
            r = subprocess.run(["clinfo"], capture_output=True, text=True, timeout=5)
            if "Intel" in r.stdout:
                gpus.append({"vendor": "Intel", "name": "Intel GPU", "vram_gb": 0})
                return gpus
        except Exception:
            pass

        return gpus

    # ── Ollama 服务 ──────────────────────────────────

    @staticmethod
    def _detect_occ() -> Dict[str, Any]:
        """检测pythonocc-core是否可用。"""
        try:
            import OCC.Core
            from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder
            result = {"available": True, "reason": "", "version": getattr(OCC.Core, "__version__", "unknown")}
        except ImportError as e:
            result = {"available": False, "reason": f"OCC未安装: {e}", "version": None}
        return result

    def _detect_ollama(self) -> Dict[str, Any]:
        """检测本地 Ollama 服务及已安装模型。"""
        try:
            import urllib.request
            req = urllib.request.Request("http://localhost:11434/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            models = []
            for m in data.get("models", []):
                models.append({
                    "name": m.get("name", "unknown"),
                    "size_gb": round(m.get("size", 0) / 1e9, 2),
                    "format": m.get("details", {}).get("format", "gguf"),
                    "param_size": m.get("details", {}).get("parameter_size", "unknown"),
                })
            return {"available": True, "models": models}
        except Exception as e:
            return {"available": False, "error": str(e)}

    # ── 模型文件发现 ──────────────────────────────────

    def _discover_models(self) -> List[Dict[str, Any]]:
        exts = [".gguf", ".bin", ".onnx"]
        found: List[Dict[str, Any]] = []
        models_dir = self.project_root / "models"
        if not models_dir.exists():
            return found
        for ext in exts:
            for mf in models_dir.rglob(f"*{ext}"):
                size_gb = round(mf.stat().st_size / (1024**3), 2)
                found.append({
                    "path": str(mf),
                    "name": mf.name,
                    "size_gb": size_gb,
                    "format": ext.replace(".", ""),
                    "estimated_params_b": self._estimate_params(size_gb, ext),
                })
        return found

    def _estimate_params(self, size_gb: float, fmt: str) -> float:
        """GGUF Q4 ≈ 0.7 GB/B，其他保守 2 GB/B。"""
        if fmt == "gguf":
            return round(size_gb / 0.7, 1)
        return round(size_gb / 2, 1)

    # ── Skill 配置发现 ────────────────────────────────

    def _discover_skills(self) -> List[Dict[str, str]]:
        import yaml
        skills: List[Dict[str, str]] = []
        sd = self.project_root / "config" / "skills"
        if not sd.exists():
            return skills
        for yf in sd.rglob("*.yaml"):
            try:
                with open(yf) as f:
                    cfg = yaml.safe_load(f)
                skills.append({"name": cfg.get("name"), "path": str(yf)})
            except Exception:
                pass
        return skills

    # ── Expert 配置发现 ───────────────────────────────

    def _discover_experts(self) -> List[Dict[str, str]]:
        import yaml
        experts: List[Dict[str, str]] = []
        ed = self.project_root / "config" / "experts"
        if not ed.exists():
            return experts
        for yf in ed.rglob("*.yaml"):
            try:
                with open(yf) as f:
                    cfg = yaml.safe_load(f)
                experts.append({"name": cfg.get("name"), "path": str(yf)})
            except Exception:
                pass
        return experts
