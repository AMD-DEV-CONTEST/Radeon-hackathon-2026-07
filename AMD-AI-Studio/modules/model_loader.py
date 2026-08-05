"""
模型加载管理器 — 统一管理模型路径、加载、缓存、后台下载
支持 Hugging Face Hub / ModelScope 国内源
"""

import os
import sys
import json
import time
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field

import torch

logger = logging.getLogger(__name__)


# ============================================================
# 模型状态常量
# ============================================================
STATUS_NOT_DOWNLOADED = "not_downloaded"
STATUS_DOWNLOADING = "downloading"
STATUS_DOWNLOADED = "downloaded"
STATUS_ERROR = "error"
STATUS_LOADING = "loading"
STATUS_LOADED = "loaded"


# ============================================================
# 默认模型注册表
# ============================================================
DEFAULT_MODEL_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ==================== 文生图 / 图生图 ====================
    "sdxl-base": {
        "repo_id": "stabilityai/stable-diffusion-xl-base-1.0",
        "type": "txt2img",
        "pipeline": "sdxl",
        "description": "SDXL 文生图（高质量，7GB）",
        "size_gb": 7.0,
        "variant": "fp16",
        "required": True,
        "alternate": {"modelscope": "AI-ModelScope/stable-diffusion-xl-base-1.0"},
    },
    "sd15": {
        "repo_id": "runwayml/stable-diffusion-v1-5",
        "type": "txt2img",
        "pipeline": "sd15",
        "description": "SD1.5 轻量文生图（1.5GB，省显存首选）",
        "size_gb": 1.5,
        "variant": "fp16",
        "required": False,
        "alternate": {"modelscope": "AI-ModelScope/stable-diffusion-v1-5"},
    },
    "sd21": {
        "repo_id": "stabilityai/stable-diffusion-2-1",
        "type": "txt2img",
        "pipeline": "sd15",
        "description": "SD2.1 文生图（2GB，质量均衡）",
        "size_gb": 2.0,
        "variant": "fp16",
        "required": False,
        "alternate": {"modelscope": "AI-ModelScope/stable-diffusion-v2-1"},
    },
    "sdxl-turbo": {
        "repo_id": "stabilityai/sdxl-turbo",
        "type": "txt2img",
        "pipeline": "sdxl",
        "description": "SDXL Turbo 快速生成（1~4步推理，7GB）",
        "size_gb": 7.0,
        "variant": "fp16",
        "required": False,
        "alternate": {"modelscope": "AI-ModelScope/sdxl-turbo"},
    },
    "sdxl-lightning": {
        "repo_id": "ByteDance/SDXL-Lightning",
        "type": "txt2img",
        "pipeline": "sdxl",
        "description": "SDXL Lightning 快速生成（2~4步推理）",
        "size_gb": 3.0,
        "variant": "fp16",
        "required": False,
        "alternate": {"modelscope": "AI-ModelScope/SDXL-Lightning"},
    },
    # ==================== VAE ====================
    "sdxl-vae-fp16": {
        "repo_id": "madebyollin/sdxl-vae-fp16-fix",
        "type": "vae",
        "pipeline": "vae",
        "description": "SDXL VAE fp16 优化版（省显存）",
        "size_gb": 0.3,
        "required": True,
        "alternate": {"modelscope": "AI-ModelScope/sdxl-vae-fp16-fix"},
    },
    # ==================== 图像修复 ====================
    "sd-inpaint": {
        "repo_id": "runwayml/stable-diffusion-inpainting",
        "type": "inpainting",
        "pipeline": "sd15",
        "description": "SD1.5 图像修复模型（1.5GB，轻量）",
        "size_gb": 1.5,
        "variant": "fp16",
        "required": False,
        "alternate": {"modelscope": "AI-ModelScope/stable-diffusion-inpainting"},
    },
    # ==================== 图生视频 ====================
    "svd": {
        "repo_id": "stabilityai/stable-video-diffusion-img2vid",
        "type": "img2video",
        "pipeline": "svd",
        "description": "SVD 图生视频（8GB，较省显存版）",
        "size_gb": 8.0,
        "variant": "fp16",
        "required": False,
        "alternate": {"modelscope": "AI-ModelScope/stable-video-diffusion-img2vid"},
    },
    # ==================== LoRA ====================
    "lcm-lora-sdxl": {
        "repo_id": "latent-consistency/lcm-lora-sdxl",
        "type": "lora",
        "pipeline": "lora",
        "description": "LCM LoRA 快速推理（4步生成，0.1GB）",
        "size_gb": 0.1,
        "required": False,
        "alternate": {"modelscope": "AI-ModelScope/lcm-lora-sdxl"},
    },
    # ==================== Krea-2-Turbo 系列 ====================
    "krea-2-turbo": {
        "repo_id": "krea/Krea-2-Turbo",
        "type": "txt2img",
        "pipeline": "krea2",
        "description": "Krea-2-Turbo 快速生成模型（Flux 架构变体，6GB）",
        "size_gb": 6.0,
        "variant": "fp16",
        "required": False,
        "alternate": {"modelscope": "krea/Krea-2-Turbo"},
    },
    "krea-2-turbo-zishi": {
        "repo_id": "krea/Krea-2-Turbo",
        "type": "lora",
        "pipeline": "lora",
        "description": "Krea-2-Turbo-zishi 风格 LoRA（紫狮风格，224MB）",
        "size_gb": 0.22,
        "variant": "fp16",
        "required": False,
        "alternate": {"modelscope": "jonathanfu/Krea-2-Turbo-zishi"},
        "base_model": "krea-2-turbo",
    },
}


@dataclass
class ModelStatus:
    """模型状态跟踪"""
    key: str = ""
    status: str = STATUS_NOT_DOWNLOADED
    progress: float = 0.0        # 0-100
    message: str = ""
    error: str = ""
    download_start_time: float = 0.0
    download_end_time: float = 0.0
    load_time_ms: float = 0.0


class ModelLoader:
    """模型加载管理器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._loaded_pipelines: Dict[str, Any] = {}
        self._model_status: Dict[str, ModelStatus] = {}
        self._download_threads: Dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._source = os.environ.get("MODEL_SOURCE", "modelscope")

        # 初始化状态
        for key in DEFAULT_MODEL_REGISTRY:
            self._model_status[key] = ModelStatus(key=key, status=STATUS_NOT_DOWNLOADED)

        # 设置 Hugging Face 镜像
        self._setup_mirror()
        self.device = self._detect_device()

    def _setup_mirror(self):
        """自动配置国内镜像"""
        if self._source == "modelscope":
            return
        if "HF_ENDPOINT" not in os.environ:
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            logger.info("已自动设置 HF_ENDPOINT=https://hf-mirror.com")

    def _detect_device(self) -> str:
        try:
            if torch.cuda.is_available():
                ver = getattr(torch.version, "rocm", None)
                if ver:
                    logger.info(f"检测到 ROCm {ver}, GPU: {torch.cuda.get_device_name(0)}")
                return "cuda"
        except Exception:
            pass
        return "cpu"

    # ─── 模型状态 ───

    def get_model_status(self, key: str) -> ModelStatus:
        return self._model_status.get(key, ModelStatus(key=key, status=STATUS_NOT_DOWNLOADED))

    def get_all_status(self) -> Dict[str, ModelStatus]:
        # 刷新已下载状态
        for key in self._model_status:
            if self._model_status[key].status == STATUS_NOT_DOWNLOADED:
                if self._check_downloaded(key):
                    self._model_status[key].status = STATUS_DOWNLOADED
        return dict(self._model_status)

    def _get_local_cache_path(self, key: str) -> Optional[Path]:
        """获取模型本地缓存路径，返回 HF 缓存快照路径或 ModelScope 路径，None 表示未缓存"""
        registry = DEFAULT_MODEL_REGISTRY.get(key)
        if not registry:
            return None
        repo_id = registry["repo_id"]
        pipeline = registry.get("pipeline", "")
        hf_home = os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface"))

        # 模型标识文件：pipeline 用 model_index.json，单组件（vae/lora）用 config.json
        if pipeline in ("sdxl", "sd15", "svd", "krea2"):
            marker = "model_index.json"
        elif pipeline == "lora":
            marker = None  # lora 模型没有标准标识文件，检查是否有 safetensors 文件
        else:
            marker = "config.json"

        def _check_marker(path: Path, m: Optional[str]) -> bool:
            """检查路径是否包含合法的模型标识文件"""
            if not path.exists():
                return False
            if m is None:
                # LoRA 模型：检查是否有 safetensors 文件
                try:
                    return any(f.suffix == '.safetensors' for f in path.iterdir())
                except Exception:
                    return False
            return (path / m).exists()

        # 1. HuggingFace 标准缓存格式: {HF_HOME}/hub/models--owner--name/snapshots/{hash}/
        hf_cache_dir = Path(hf_home) / "hub" / f"models--{repo_id.replace('/', '--')}"
        if hf_cache_dir.exists():
            # 读取 refs/main 获取最新快照 hash
            refs_file = hf_cache_dir / "refs" / "main"
            if refs_file.exists():
                with open(refs_file) as f:
                    snapshot_hash = f.read().strip()
                snap_path = hf_cache_dir / "snapshots" / snapshot_hash
                if snap_path.exists() and _check_marker(snap_path, marker):
                    return snap_path
            # 没有 refs 文件时，直接检查 snapshots 下是否有合法子目录
            snap_dir = hf_cache_dir / "snapshots"
            if snap_dir.exists():
                for entry in snap_dir.iterdir():
                    if _check_marker(entry, marker):
                        return entry

        # 1.5 HuggingFace snapshot_download 直接写入格式: {HF_HOME}/models--owner--name/snapshots/{hash}/
        hf_cache_dir_direct = Path(hf_home) / f"models--{repo_id.replace('/', '--')}"
        if hf_cache_dir_direct.exists():
            refs_file = hf_cache_dir_direct / "refs" / "main"
            if refs_file.exists():
                with open(refs_file) as f:
                    snapshot_hash = f.read().strip()
                snap_path = hf_cache_dir_direct / "snapshots" / snapshot_hash
                if snap_path.exists() and _check_marker(snap_path, marker):
                    return snap_path

        # 2. ModelScope 缓存格式: {cache}/models/{owner}/{name}
        ms_cache = os.environ.get("MODELSCOPE_CACHE", str(Path.home() / ".cache" / "modelscope" / "hub"))
        for candidate in [
            Path(ms_cache) / "models" / repo_id,
            Path(ms_cache) / "models" / repo_id.replace(".", "___"),
        ]:
            if candidate.exists() and _check_marker(candidate, marker):
                return candidate

        # 2.5 ModelScope 备用 ID 格式（registry 中 alternate.modelscope 指定的路径）
        alt = registry.get("alternate", {}).get("modelscope")
        if alt:
            for candidate in [
                Path(ms_cache) / "models" / alt,
                Path(ms_cache) / "models" / alt.replace(".", "___"),
            ]:
                if candidate.exists() and _check_marker(candidate, marker):
                    return candidate

        return None

    def _check_downloaded(self, key: str) -> bool:
        return self._get_local_cache_path(key) is not None

    def is_model_downloaded(self, key: str) -> bool:
        return self._check_downloaded(key)

    # ─── 后台下载 ───

    def start_download(self, key: str, source: str = "modelscope",
                       progress_callback: Optional[Callable] = None) -> bool:
        """启动后台下载"""
        if key in self._download_threads and self._download_threads[key].is_alive():
            return False  # 已在下载中

        registry = DEFAULT_MODEL_REGISTRY.get(key)
        if not registry:
            return False

        with self._lock:
            self._model_status[key].status = STATUS_DOWNLOADING
            self._model_status[key].progress = 0.0
            self._model_status[key].message = f"正在下载 {registry['description']}..."
            self._model_status[key].download_start_time = time.time()
            self._model_status[key].error = ""

        thread = threading.Thread(
            target=self._download_worker,
            args=(key, registry, source, progress_callback),
            daemon=True,
        )
        self._download_threads[key] = thread
        thread.start()
        return True

    def _download_worker(self, key: str, registry: Dict, source: str,
                         progress_callback: Optional[Callable]):
        """下载工作线程"""
        try:
            repo_id = registry["repo_id"]
            # 优先使用 alternate.modelscope 作为 ModelScope 的 repo_id
            alt = registry.get("alternate", {}).get("modelscope", repo_id)

            with self._lock:
                self._model_status[key].message = f"正在下载 {repo_id}..."

            if source == "modelscope":
                # 从 ModelScope 下载（魔塔社区国内源，速度快）
                success = self._download_from_modelscope(key, alt)
                # 如果 ModelScope 下载失败，降级到 HuggingFace 镜像
                if not success:
                    logger.warning(f"ModelScope 下载失败，降级到 HuggingFace 镜像: {repo_id}")
                    success = self._download_from_mirror(key, repo_id, "https://hf-mirror.com")
            else:
                success = self._download_huggingface(key, repo_id)

            if success:
                with self._lock:
                    self._model_status[key].status = STATUS_DOWNLOADED
                    self._model_status[key].progress = 100.0
                    self._model_status[key].download_end_time = time.time()
                    self._model_status[key].message = "下载完成 ✅"
                    self._model_status[key].error = ""
            else:
                with self._lock:
                    self._model_status[key].status = STATUS_ERROR
                    self._model_status[key].message = "下载失败"

        except Exception as e:
            with self._lock:
                self._model_status[key].status = STATUS_ERROR
                self._model_status[key].error = str(e)
                self._model_status[key].message = f"下载异常: {e}"

    def _download_from_modelscope(self, key: str, repo_id: str) -> bool:
        """从 ModelScope（魔塔社区）下载模型，使用 modelscope 官方 SDK"""
        try:
            import subprocess
            ms_cache = os.environ.get(
                "MODELSCOPE_CACHE",
                str(Path.home() / ".cache" / "modelscope" / "hub"),
            )
            result = subprocess.run(
                [sys.executable, "-c", f"""
import os, sys
os.environ['MODELSCOPE_CACHE'] = '{ms_cache}'
try:
    from modelscope.hub.snapshot_download import snapshot_download
    snapshot_download('{repo_id}', cache_dir='{ms_cache}', max_workers=1)
    print('OK')
except Exception as e:
    print(f'FAIL: {{e}}', file=sys.stderr)
    sys.exit(1)
"""],
                capture_output=True, text=True, timeout=1800,
            )
            if result.returncode != 0:
                logger.error(f"ModelScope 下载失败 [{repo_id}]: {result.stderr[:300]}")
                return False
            return "OK" in result.stdout
        except Exception as e:
            logger.error(f"ModelScope 下载异常 [{repo_id}]: {e}")
            return False

    def _download_from_mirror(self, key: str, repo_id: str, endpoint: str) -> bool:
        """从指定的 HuggingFace 镜像站下载到 HF 缓存（保证 from_pretrained 可识别）"""
        try:
            import subprocess
            result = subprocess.run(
                [sys.executable, "-c", f"""
import os
os.environ['HF_ENDPOINT'] = '{endpoint}'
os.environ['HF_HOME'] = '{os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface"))}'
os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = '0'
from huggingface_hub import snapshot_download
snapshot_download(repo_id='{repo_id}', max_workers=1, ignore_patterns=['*.md', '*.txt'])
print('OK')
"""],
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode != 0:
                logger.error(f"镜像下载失败: {result.stderr[:200]}")
            return "OK" in result.stdout
        except Exception as e:
            logger.error(f"镜像下载异常: {e}")
            return False

    def _download_huggingface(self, key: str, repo_id: str) -> bool:
        """从 Hugging Face 官方源下载（走 HF 缓存）"""
        try:
            import subprocess
            result = subprocess.run(
                [sys.executable, "-c", f"""
import os
os.environ['HF_HOME'] = '{os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface"))}'
os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = '0'
from huggingface_hub import snapshot_download
snapshot_download(repo_id='{repo_id}', max_workers=1, ignore_patterns=['*.md', '*.txt'])
print('OK')
"""],
                capture_output=True, text=True, timeout=600,
            )
            return "OK" in result.stdout
        except Exception as e:
            logger.error(f"HuggingFace 下载失败: {e}")
            return False

    def get_download_progress(self, key: str) -> float:
        return self._model_status.get(key, ModelStatus()).progress

    def is_downloading(self, key: str) -> bool:
        return self._model_status.get(key, ModelStatus()).status == STATUS_DOWNLOADING

    # ─── 模型注册表查询 ───

    def list_models(self, status: bool = False) -> Dict[str, Dict[str, Any]]:
        result = {}
        for key, info in DEFAULT_MODEL_REGISTRY.items():
            entry = dict(info)
            if status:
                ms = self.get_model_status(key)
                entry["status"] = ms.status
                entry["progress"] = ms.progress
                entry["message"] = ms.message
            result[key] = entry
        return result

    def search_models(self, query: str) -> Dict[str, Dict[str, Any]]:
        """搜索模型（按名称、描述、类型）"""
        q = query.lower()
        result = {}
        for key, info in DEFAULT_MODEL_REGISTRY.items():
            if q in key.lower() or q in info["description"].lower() or q in info.get("type", "").lower():
                entry = dict(info)
                ms = self.get_model_status(key)
                entry["status"] = ms.status
                entry["progress"] = ms.progress
                result[key] = entry
        return result

    def get_models_by_type(self, model_type: str) -> Dict[str, Dict[str, Any]]:
        return {k: v for k, v in DEFAULT_MODEL_REGISTRY.items() if v.get("type") == model_type}

    def get_models_for_function(self, function_type: str) -> List[str]:
        """获取支持某功能的模型列表"""
        # txt2img 功能: sdxl-base, sd-turbo
        # img2img 功能: sdxl-base, sd-turbo
        # img2video: svd-xt
        # inpainting: sdxl-inpaint
        mapping = {
            "txt2img": ["sdxl-base", "sd-turbo"],
            "img2img": ["sdxl-base", "sd-turbo"],
            "img2video": ["svd-xt"],
            "inpainting": ["sdxl-inpaint"],
        }
        return mapping.get(function_type, [])

    def get_model_params(self, model_key: str) -> Dict[str, Any]:
        """获取模型推荐参数"""
        params = {
            "sdxl-base": {
                "default_steps": 30, "min_steps": 10, "max_steps": 80,
                "default_guidance": 7.5, "min_guidance": 1.0, "max_guidance": 20.0,
                "default_width": 1024, "default_height": 1024,
                "description": "标准质量，推荐30步",
            },
            "sd-turbo": {
                "default_steps": 4, "min_steps": 1, "max_steps": 10,
                "default_guidance": 1.0, "min_guidance": 1.0, "max_guidance": 5.0,
                "default_width": 512, "default_height": 512,
                "description": "超快速，4步即可",
            },
            "svd-xt": {
                "default_steps": 25, "min_steps": 10, "max_steps": 50,
                "default_frames": 14, "min_frames": 6, "max_frames": 25,
                "default_fps": 7,
                "description": "高质量视频生成",
            },
            "sdxl-inpaint": {
                "default_steps": 30, "min_steps": 10, "max_steps": 80,
                "default_guidance": 7.5,
                "default_strength": 0.85,
                "description": "高质量图像修复",
            },
        }
        return params.get(model_key, {})

    # ─── Pipeline 加载 ───

    def load_pipeline(self, model_key: str, function_type: str,
                      progress_callback: Optional[Callable] = None):
        """加载模型 pipeline（异步，带状态跟踪）
        缓存键包含 model_key + function_type，确保不同功能类型使用不同 pipeline"""
        cache_key = f"{model_key}:{function_type}"
        if cache_key in self._loaded_pipelines:
            return self._loaded_pipelines[cache_key]

        with self._lock:
            self._model_status[model_key].status = STATUS_LOADING
            self._model_status[model_key].message = f"正在加载 {model_key} ({function_type})..."

        start = time.time()
        try:
            pipe = self._do_load_pipeline(model_key, function_type)
            elapsed = (time.time() - start) * 1000
            with self._lock:
                self._model_status[model_key].status = STATUS_LOADED
                self._model_status[model_key].load_time_ms = round(elapsed, 1)
                self._model_status[model_key].message = f"已加载 ({elapsed:.0f}ms)"
            self._loaded_pipelines[cache_key] = pipe
            return pipe
        except Exception as e:
            with self._lock:
                self._model_status[model_key].status = STATUS_ERROR
                self._model_status[model_key].error = str(e)
                self._model_status[model_key].message = f"加载失败: {e}"
            raise

    def _do_load_pipeline(self, model_key: str, function_type: str):
        """根据模型注册表中的 pipeline 类型加载对应 pipeline"""
        registry = DEFAULT_MODEL_REGISTRY.get(model_key)
        if not registry:
            raise ValueError(f"未知模型: {model_key}")

        repo_id = registry["repo_id"]
        pipeline_family = registry.get("pipeline", "sdxl")  # 默认 sdxl

        # 优先使用本地缓存路径（避免 repo_id 远程查找）
        local_path = self._get_local_cache_path(model_key)
        model_source = str(local_path) if local_path else repo_id
        torch_dtype = torch.float16 if self.device == "cuda" else torch.float32

        from diffusers import (
            StableDiffusionPipeline,
            StableDiffusionImg2ImgPipeline,
            StableDiffusionInpaintPipeline,
            StableDiffusionXLPipeline,
            StableDiffusionXLImg2ImgPipeline,
            StableDiffusionXLInpaintPipeline,
            StableVideoDiffusionPipeline,
            AutoencoderKL,
            DiffusionPipeline,
        )

        # 根据 pipeline 家族 + 功能类型选择正确的类
        # VAE 本地路径（已下载时使用）
        vae_local = self._get_local_cache_path("sdxl-vae-fp16")

        if pipeline_family == "svd":
            # 图生视频
            pipe = StableVideoDiffusionPipeline.from_pretrained(
                model_source, torch_dtype=torch_dtype,
                variant="fp16", use_safetensors=True,
            )

        elif pipeline_family == "sd15":
            # SD1.5 / SD2.1 系列
            if function_type == "txt2img":
                pipe = StableDiffusionPipeline.from_pretrained(
                    model_source, torch_dtype=torch_dtype,
                    safety_checker=None, requires_safety_checker=False,
                )
            elif function_type == "img2img":
                pipe = StableDiffusionImg2ImgPipeline.from_pretrained(
                    model_source, torch_dtype=torch_dtype,
                    safety_checker=None, requires_safety_checker=False,
                )
            elif function_type == "inpainting":
                pipe = StableDiffusionInpaintPipeline.from_pretrained(
                    model_source, torch_dtype=torch_dtype,
                    safety_checker=None, requires_safety_checker=False,
                )
            else:
                pipe = StableDiffusionPipeline.from_pretrained(
                    model_source, torch_dtype=torch_dtype,
                    safety_checker=None, requires_safety_checker=False,
                )

        elif pipeline_family == "krea2":
            # Krea-2-Turbo 系列（使用 DiffusionPipeline 自动检测类）
            pipe = DiffusionPipeline.from_pretrained(
                model_source, torch_dtype=torch_dtype,
                variant="fp16", use_safetensors=True,
            )

        else:
            # SDXL 系列（默认）
            if function_type == "txt2img":
                pipe = StableDiffusionXLPipeline.from_pretrained(
                    model_source, torch_dtype=torch_dtype,
                    variant="fp16", use_safetensors=True,
                )
                # SDXL 加载专用 VAE（使用本地路径）
                vae = AutoencoderKL.from_pretrained(
                    str(vae_local) if vae_local else "madebyollin/sdxl-vae-fp16-fix",
                    torch_dtype=torch_dtype,
                )
                pipe.vae = vae
            elif function_type == "img2img":
                pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
                    model_source, torch_dtype=torch_dtype,
                    variant="fp16", use_safetensors=True,
                )
                vae = AutoencoderKL.from_pretrained(
                    str(vae_local) if vae_local else "madebyollin/sdxl-vae-fp16-fix",
                    torch_dtype=torch_dtype,
                )
                pipe.vae = vae
            elif function_type == "inpainting":
                pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
                    model_source, torch_dtype=torch_dtype,
                    variant="fp16", use_safetensors=True,
                )
                vae = AutoencoderKL.from_pretrained(
                    str(vae_local) if vae_local else "madebyollin/sdxl-vae-fp16-fix",
                    torch_dtype=torch_dtype,
                )
                pipe.vae = vae
            else:
                raise ValueError(f"SDXL 不支持的功能类型: {function_type}")

        # 优化
        pipe.enable_attention_slicing()
        try:
            pipe.enable_vae_tiling()
        except Exception:
            pass  # 部分模型不支持 VAE tiling
        if self.device == "cuda":
            if pipeline_family in ("svd", "krea2"):
                # SVD / Krea2 模型较大，用 to('cuda') 直接移到 GPU 比 sequential_cpu_offload 快得多
                pipe.to(self.device)
            else:
                pipe.enable_sequential_cpu_offload()
        else:
            pipe.to(self.device)

        return pipe

    def unload_pipeline(self, model_key: str) -> float:
        """卸载指定模型的所有 pipeline，返回释放的显存（GB）"""
        import gc
        import torch

        mem_before = 0
        try:
            if torch.cuda.is_available():
                mem_before = torch.cuda.memory_allocated(0) / 1024**3
        except Exception:
            pass

        # 卸载所有匹配该 model_key 的 pipeline（可能多个 function_type）
        keys_to_remove = [k for k in self._loaded_pipelines if k.startswith(f"{model_key}:")]
        for cache_key in keys_to_remove:
            pipe = self._loaded_pipelines.pop(cache_key, None)
            if pipe is not None:
                try:
                    if hasattr(pipe, "to"):
                        pipe.to("cpu")
                    del pipe
                except Exception:
                    pass

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        with self._lock:
            self._model_status[model_key].status = STATUS_DOWNLOADED
            self._model_status[model_key].message = "已卸载"

        mem_after = 0
        try:
            if torch.cuda.is_available():
                mem_after = torch.cuda.memory_allocated(0) / 1024**3
        except Exception:
            pass
        freed = mem_before - mem_after
        if freed > 0:
            logger.info(f"模型已卸载: {model_key}, 释放显存: {freed:.2f}GB")
        return max(0, freed)

    def clear_cache(self):
        import gc
        for key, pipe in self._loaded_pipelines.items():
            try:
                if hasattr(pipe, "to"):
                    pipe.to("cpu")
                del pipe
            except Exception:
                pass
        self._loaded_pipelines.clear()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("模型缓存已全部清理")


# 全局单例
global_loader = ModelLoader()