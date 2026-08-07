"""
NodeFlow — FastAPI 后端入口

提供文生图、图生图、风格列表、健康检查、模型管理、LoRA 管理、模型商店等 API。
运行在 AMD Radeon GPU (ROCm) 上,支持多模型 + 双模式 (快速版 / 专家版)。

架构:
    main.py (API 层)
        └── engine.py (FluxEngine 兼容门面)
                └── model_manager.py (真正的模型加载/切换/LoRA)
    store_service.py (模型商店,聚合 HF + Civitai)
"""
from __future__ import annotations

import base64
import io
import logging
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from config import (
    ALLOWED_IMAGE_TYPES,
    ASPECT_RATIOS,
    DEFAULT_ASPECT_RATIO,
    DEFAULT_MODE,
    MAX_IMAGE_SIZE_MB,
    MAX_PROMPT_LENGTH,
    MAX_RESOLUTION,
    MIN_RESOLUTION,
    MODEL_REGISTRY,
    RATIO_MAPPINGS,
    SUPPORTED_MODES,
)
from engine import FluxEngine
from store_service import store_service

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("main")

app = FastAPI(
    title="NodeFlow API",
    description="Node-style workflow canvas — AMD GPU + multi-model (fast/expert)",
    version="2.0.0",
)

# CORS — 允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局引擎实例 (单例门面,内部委托给 ModelManager)
engine = FluxEngine()


# ---------------------------------------------------------------------------
# LoRA 临时加载/卸载辅助函数 (免模式限制)
# ---------------------------------------------------------------------------

def _apply_temporary_loras(
    lora_paths: list[str],
    weights: Optional[list[float]] = None,
) -> list[str]:
    """
    在生成前加载临时 LoRA,返回 lora_id 列表。
    生成结束后应调用 _cleanup_temporary_loras() 清理。

    Args:
        lora_paths: LoRA 文件路径列表
        weights: 对应权重列表 (None 则使用默认权重 0.8)

    Returns:
        已加载的 lora_id 列表
    """
    loaded: list[str] = []
    for i, path in enumerate(lora_paths):
        w = weights[i] if weights and i < len(weights) else 0.8
        try:
            lid = engine.load_lora(path=path, weight=w)
            loaded.append(lid)
            logger.info("Temporary LoRA loaded: %s (weight=%.2f)", lid, w)
        except Exception as e:
            logger.warning("Failed to load temporary LoRA %s: %s", path, e)
    return loaded


def _cleanup_temporary_loras(lora_ids: list[str]) -> None:
    """生成后清理临时 LoRA。"""
    for lid in lora_ids:
        try:
            engine.unload_lora(lid)
            logger.info("Temporary LoRA unloaded: %s", lid)
        except Exception as e:
            logger.warning("Failed to unload temporary LoRA %s: %s", lid, e)


# ---------------------------------------------------------------------------
# 启动事件
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event() -> None:
    """启动时预加载默认模型 (快速版)。加载失败不阻断服务启动。"""
    logger.info("=" * 50)
    logger.info("NodeFlow Backend Starting (v2.0.0, dual-mode)")
    logger.info("Pre-loading default model (fast mode) on AMD GPU...")
    try:
        engine.load()
    except Exception as exc:  # noqa: BLE001 — 启动期容错
        logger.error("Default model load failed: %s", exc, exc_info=True)
        logger.error("API will start anyway; /api/health will report model_loaded=false.")
    logger.info("=" * 50)


# 前端静态文件目录 (npm run build 后生成)
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


# ===========================================================================
# 基础端点
# ===========================================================================
@app.get("/", response_model=None)
async def root():
    """返回前端页面"""
    index_path = FRONTEND_DIST / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse(
        """
        <html><body style="font-family:monospace;padding:40px">
        <h2>前端尚未构建</h2>
        <p>请在 frontend 目录运行:</p>
        <pre>npm run build</pre>
        <p>然后刷新此页面</p>
        </body></html>
        """
    )


@app.get("/api/info")
async def api_info() -> JSONResponse:
    """API 基础信息 (动态模型信息)"""
    try:
        current = engine.get_current_model_info() or {}
    except Exception:  # noqa: BLE001
        current = {}
    return JSONResponse(
        {
            "status": "ok",
            "service": "NodeFlow API",
            "version": "2.0.0",
            "gpu": "AMD Radeon PRO W7900",
            "runtime": "ROCm 7.2.1 + PyTorch 2.12",
            "supported_modes": SUPPORTED_MODES,
            "default_mode": DEFAULT_MODE,
            "model_loaded": engine.is_loaded(),
            "current_model": current,
        }
    )


@app.get("/api/health")
async def health_check() -> JSONResponse:
    """详细健康检查 — 含 GPU 状态、显存信息、当前模型"""
    gpu_info = engine.get_gpu_info()
    try:
        current = engine.get_current_model_info() or {}
    except Exception:  # noqa: BLE001
        current = {}
    return JSONResponse(
        {
            "status": "ok",
            "model_loaded": engine.is_loaded(),
            "current_model": current,
            "gpu": gpu_info,
            "styles_available": list(engine.get_styles().keys()),
        }
    )


@app.get("/api/styles")
async def get_styles() -> JSONResponse:
    """获取可用风格列表"""
    styles = engine.get_styles()
    return JSONResponse(
        {
            "styles": [
                {
                    "key": k,
                    "label": k.replace("_", " ").title(),
                    "prompt_prefix": v,
                }
                for k, v in styles.items()
            ]
        }
    )


# ===========================================================================
# 模型管理端点
# ===========================================================================
@app.get("/api/models")
async def list_models(mode: str = DEFAULT_MODE) -> JSONResponse:
    """
    获取指定模式下可用模型列表。

    Query:
        mode: ``"fast"`` | ``"expert"`` (默认 fast)
    """
    if mode not in SUPPORTED_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode {mode!r}. Supported: {SUPPORTED_MODES}",
        )
    models = engine.get_available_models(mode)
    return JSONResponse(
        {
            "status": "ok",
            "mode": mode,
            "count": len(models),
            "models": models,
        }
    )


@app.get("/api/models/current")
async def get_current_model() -> JSONResponse:
    """获取当前已加载模型与模式"""
    info = engine.get_current_model_info() or {}
    return JSONResponse(
        {
            "status": "ok",
            "model_loaded": engine.is_loaded(),
            "current": info,
        }
    )


@app.get("/api/models/{model_id}/config")
async def get_model_config(model_id: str) -> JSONResponse:
    """
    获取某模型的参数配置与推荐比例选项。

    Path:
        model_id: 模型标识 (单段路径,不含 ``/``;含斜杠的 ID 请先 URL 编码)。
    """
    try:
        config = engine.get_model_config(model_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=404, detail=f"Model config not found for {model_id!r}: {exc}"
        )

    # 补充完整的比例详情 (width/height/recommended)
    arch = config.get("architecture", "sdxl")
    ratio_key = "flux" if "flux" in arch else "sdxl"
    all_ratios = RATIO_MAPPINGS.get(ratio_key, {})
    model_ratio_names = set(config.get("supported_ratios", []))
    ratio_details = [r for r in all_ratios.values() if r["ratio"] in model_ratio_names]

    config["ratio_details"] = ratio_details

    return JSONResponse({"status": "ok", "model_id": model_id, "config": config})


class SwitchModelRequest(BaseModel):
    """切换模型请求体"""
    model_id: str = Field(..., min_length=1, description="目标模型标识")


@app.post("/api/models/switch")
async def switch_model(req: SwitchModelRequest) -> JSONResponse:
    """切换当前加载的模型"""
    logger.info("Switching model -> %s", req.model_id)
    try:
        result = engine.switch_model(req.model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("switch_model failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Switch failed: {exc}"
        )
    return JSONResponse({"status": "ok", "model_id": req.model_id, "result": result})


# ===========================================================================
# LoRA 管理端点
# ===========================================================================
@app.get("/api/loras")
async def list_loras() -> JSONResponse:
    """已加载 LoRA 列表"""
    loras = engine.get_loaded_loras()
    return JSONResponse(
        {
            "status": "ok",
            "count": len(loras) if isinstance(loras, dict) else 0,
            "loras": loras,
        }
    )


class LoadLoraRequest(BaseModel):
    """加载 LoRA 请求体"""
    path: str = Field(..., min_length=1, description="LoRA 文件路径或远端标识")
    weight: float = Field(default=1.0, ge=0.0, le=2.0, description="LoRA 强度")


@app.post("/api/loras/load")
async def load_lora(req: LoadLoraRequest) -> JSONResponse:
    """加载 LoRA"""
    try:
        lora_id = engine.load_lora(path=req.path, weight=req.weight)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("load_lora failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Load LoRA failed: {exc}")
    return JSONResponse(
        {"status": "ok", "lora_id": lora_id, "path": req.path, "weight": req.weight}
    )


class UnloadLoraRequest(BaseModel):
    """卸载 LoRA 请求体"""
    lora_id: str = Field(..., min_length=1, description="load_lora 返回的标识")


@app.post("/api/loras/unload")
async def unload_lora(req: UnloadLoraRequest) -> JSONResponse:
    """卸载指定 LoRA"""
    try:
        engine.unload_lora(req.lora_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("unload_lora failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Unload LoRA failed: {exc}")
    return JSONResponse({"status": "ok", "lora_id": req.lora_id})


# ===========================================================================
# 模型商店端点
# ===========================================================================
@app.get("/api/store/models")
async def store_models(source: str = "hf", limit: int = 20) -> JSONResponse:
    """
    浏览模型商店热门 Checkpoint。

    Query:
        source: ``"hf"`` | ``"civitai"`` (默认 hf)
        limit: 1-100 (默认 20)
    """
    result = await store_service.get_trending_models(source=source, limit=limit)
    status_code = 200 if result.get("status") == "ok" else 503
    return JSONResponse(result, status_code=status_code)


@app.get("/api/store/loras")
async def store_loras(
    source: str = "civitai",
    base_model: str = "SDXL 1.0",
    limit: int = 20,
) -> JSONResponse:
    """
    浏览模型商店热门 LoRA。

    Query:
        source: 目前仅 ``"civitai"``
        base_model: 基础模型过滤 (默认 "SDXL 1.0")
        limit: 1-100 (默认 20)
    """
    result = await store_service.get_trending_loras(
        source=source, base_model=base_model, limit=limit
    )
    status_code = 200 if result.get("status") == "ok" else 503
    return JSONResponse(result, status_code=status_code)


class StoreDownloadRequest(BaseModel):
    """商店下载请求体"""
    url: str = Field(..., min_length=1, description="文件直链")
    target_path: str = Field(..., min_length=1, description="本地保存路径")
    type: str = Field(
        default="model",
        description="下载类型: model | lora (仅用于日志/归类)",
    )


@app.post("/api/store/download")
async def store_download(req: StoreDownloadRequest) -> JSONResponse:
    """
    下载模型 / LoRA 到本地 (异步流式,带大小校验)。
    """
    logger.info("Store download: type=%s url=%s -> %s", req.type, req.url, req.target_path)
    try:
        result = await store_service.download_model(
            url=req.url, target_path=req.target_path
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("store download failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Download failed: {exc}")
    return JSONResponse({"status": "ok", "type": req.type, **result})


# ===========================================================================
# GPU 状态端点
# ===========================================================================
@app.get("/api/gpu/status")
async def gpu_status() -> JSONResponse:
    """独立 GPU 状态 (显存占用等)"""
    return JSONResponse({"status": "ok", "gpu": engine.get_gpu_info()})


# ===========================================================================
# 生成端点
# ===========================================================================
def _resolve_dimensions(
    aspect_ratio: Optional[str],
    width: Optional[int],
    height: Optional[int],
    warnings: list[str],
) -> tuple[int, int]:
    """
    根据 aspect_ratio / width / height 解析最终输出尺寸。

    优先级:显式 width+height > aspect_ratio > 默认 1:1。
    会做合法性校验并把提示写入 warnings。
    """
    if width is not None and height is not None:
        for name, val in (("width", width), ("height", height)):
            if not (MIN_RESOLUTION <= val <= MAX_RESOLUTION):
                raise ValueError(
                    f"{name} must be between {MIN_RESOLUTION} and {MAX_RESOLUTION}, got {val}"
                )
        return int(width), int(height)

    ar = aspect_ratio or DEFAULT_ASPECT_RATIO
    if ar not in ASPECT_RATIOS:
        warnings.append(
            f"Unknown aspect_ratio {ar!r}, falling back to {DEFAULT_ASPECT_RATIO!r}"
        )
        ar = DEFAULT_ASPECT_RATIO
    return ASPECT_RATIOS[ar]


def _maybe_switch_model(model_id: Optional[str], warnings: list[str]) -> None:
    """若请求指定了模型且与当前不同,则切换。"""
    if not model_id:
        return
    try:
        current = engine.get_current_model_info() or {}
    except Exception:  # noqa: BLE001
        current = {}
    current_id = current.get("model_id")
    if current_id and model_id == current_id:
        return
    logger.info("Request specifies model %s (current=%s), switching...", model_id, current_id)
    try:
        engine.switch_model(model_id)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Failed to switch to model {model_id!r}: {exc}")


def _check_aspect_ratio_for_model(
    aspect_ratio: Optional[str], warnings: list[str]
) -> None:
    """对照当前模型推荐比例给出告警 (尽力而为,不阻断)。"""
    if not aspect_ratio or aspect_ratio == DEFAULT_ASPECT_RATIO:
        return
    try:
        info = engine.get_current_model_info() or {}
    except Exception:  # noqa: BLE001
        return
    recommended = info.get("recommended_aspect_ratios")
    if recommended and aspect_ratio not in recommended:
        warnings.append(
            f"aspect_ratio {aspect_ratio!r} is not in the recommended list "
            f"for current model ({recommended}); result may be suboptimal."
        )


def _encode_image(img: Image.Image) -> str:
    """PIL Image -> data:image/png;base64,..."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}"


class TextToImageRequest(BaseModel):
    """文生图请求体 (JSON)"""

    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_LENGTH)
    mode: str = Field(default=DEFAULT_MODE, description='"fast" | "expert"')
    model: Optional[str] = Field(default=None, description="指定模型 (可选)")
    style: str = "cyberpunk"
    aspect_ratio: str = DEFAULT_ASPECT_RATIO
    width: Optional[int] = Field(default=None, ge=MIN_RESOLUTION, le=MAX_RESOLUTION)
    height: Optional[int] = Field(default=None, ge=MIN_RESOLUTION, le=MAX_RESOLUTION)
    # Expert 模式可选参数
    num_inference_steps: Optional[int] = Field(default=None, ge=1, le=150)
    guidance_scale: Optional[float] = Field(default=None, ge=0.0, le=30.0)
    seed: Optional[int] = Field(default=None, ge=0, description="随机种子")
    negative_prompt: Optional[str] = Field(default=None, max_length=MAX_PROMPT_LENGTH)
    loras: Optional[list[str]] = Field(
        default=None, description="LoRA 文件路径列表 (所有模式均可用)"
    )
    lora_weights: Optional[list[float]] = Field(
        default=None, description="LoRA 权重列表 (仅 Expert 模式生效;Fast 模式使用默认权重)"
    )


@app.post("/api/generate/text2img")
async def generate_from_text(req: TextToImageRequest) -> JSONResponse:
    """
    文生图: 文字提示 → 生成

    快速版 (fast): 少步模型,固定推荐参数,忽略 expert 字段。
    专家版 (expert): 可自定义步数/引导/种子/负向提示/LoRA。
    """
    if req.mode not in SUPPORTED_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode {req.mode!r}. Supported: {SUPPORTED_MODES}",
        )

    warnings: list[str] = []

    # 1) 解析尺寸
    width, height = _resolve_dimensions(
        req.aspect_ratio, req.width, req.height, warnings
    )

    # 2) 模型切换 (如指定)
    _maybe_switch_model(req.model, warnings)

    # 3) 比例推荐告警
    _check_aspect_ratio_for_model(req.aspect_ratio, warnings)

    # 4) 组装生成参数
    params: dict[str, Any] = {"width": width, "height": height}
    if req.mode == "expert":
        if req.num_inference_steps is not None:
            params["num_inference_steps"] = req.num_inference_steps
        if req.guidance_scale is not None:
            params["guidance_scale"] = req.guidance_scale
        if req.seed is not None:
            params["seed"] = req.seed
        if req.negative_prompt:
            params["negative_prompt"] = req.negative_prompt
    else:
        # fast 模式:专家参数被忽略,给出告警
        ignored: list[str] = []
        if req.num_inference_steps is not None:
            ignored.append("num_inference_steps")
        if req.guidance_scale is not None:
            ignored.append("guidance_scale")
        if req.seed is not None:
            ignored.append("seed")
        if req.negative_prompt:
            ignored.append("negative_prompt")
        if req.lora_weights:
            ignored.append("lora_weights")
        if ignored:
            warnings.append(
                f"Expert parameters ({', '.join(ignored)}) are ignored in fast mode"
            )

    # LoRA 全局可用 (不限模式);权重仅在 expert 模式自定义
    temp_loras: list[str] = []
    if req.loras:
        lora_weights = req.lora_weights if req.mode == "expert" else None
        temp_loras = _apply_temporary_loras(req.loras, lora_weights)

    logger.info(
        "text2img: mode=%s prompt=%r style=%s size=%dx%d params=%s",
        req.mode,
        req.prompt[:60],
        req.style,
        width,
        height,
        {k: v for k, v in params.items() if k not in ("width", "height")},
    )

    start_ts = time.time()
    try:
        result = engine.generate_from_text(prompt=req.prompt, style=req.style, **params)
    except ValueError as exc:
        _cleanup_temporary_loras(temp_loras)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("text2img failed: %s", exc, exc_info=True)
        _cleanup_temporary_loras(temp_loras)
        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}")

    # 生成成功后清理临时 LoRA
    _cleanup_temporary_loras(temp_loras)
    elapsed = time.time() - start_ts

    # 5) 当前模型信息 (切换后)
    try:
        current = engine.get_current_model_info() or {}
    except Exception:  # noqa: BLE001
        current = {}
    model_id = current.get("model_id") or req.model or "default"

    return JSONResponse(
        {
            "status": "ok",
            "image": _encode_image(result),
            "prompt": req.prompt,
            "style": req.style,
            "mode": req.mode,
            "model": model_id,
            "width": width,
            "height": height,
            "aspect_ratio": req.aspect_ratio,
            "params_used": params,
            "generation_time_sec": round(elapsed, 2),
            "warnings": warnings,
        }
    )


@app.post("/api/generate/img2img")
async def generate_from_image(
    file: UploadFile = File(...),
    mode: str = Form(DEFAULT_MODE),
    model: Optional[str] = Form(None),
    style: str = Form("cyberpunk"),
    aspect_ratio: str = Form(DEFAULT_ASPECT_RATIO),
    strength: float = Form(0.8),
    width: Optional[int] = Form(None),
    height: Optional[int] = Form(None),
    num_inference_steps: Optional[int] = Form(None),
    guidance_scale: Optional[float] = Form(None),
    seed: Optional[int] = Form(None),
    negative_prompt: Optional[str] = Form(None),
    loras: Optional[list[str]] = Form(None),
    lora_weights: Optional[str] = Form(None),
) -> JSONResponse:
    """
    图生图: 上传图片 → 风格化生成 (Form 字段,因为要传文件)

    快速版 (fast): 少步模型,忽略 expert 字段。
    专家版 (expert): 可自定义步数/引导/种子/负向提示/LoRA。
    LoRA 在所有模式均可用,权重仅在 expert 模式自定义。
    """
    if mode not in SUPPORTED_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode {mode!r}. Supported: {SUPPORTED_MODES}",
        )

    warnings: list[str] = []

    # 1) 校验文件类型与大小
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: {file.content_type}. "
                f"Allowed: {sorted(ALLOWED_IMAGE_TYPES)}"
            ),
        )
    image_data = await file.read()
    if len(image_data) > MAX_IMAGE_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"Image too large. Max size: {MAX_IMAGE_SIZE_MB}MB",
        )
    try:
        image = Image.open(io.BytesIO(image_data)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid image: {exc}")

    # 2) 解析尺寸
    out_w, out_h = _resolve_dimensions(aspect_ratio, width, height, warnings)

    # 3) 模型切换
    _maybe_switch_model(model, warnings)

    # 4) 比例推荐告警
    _check_aspect_ratio_for_model(aspect_ratio, warnings)

    # 5) 组装生成参数
    params: dict[str, Any] = {
        "strength": max(0.1, min(1.0, float(strength))),
        "width": out_w,
        "height": out_h,
    }
    if mode == "expert":
        if num_inference_steps is not None:
            params["num_inference_steps"] = num_inference_steps
        if guidance_scale is not None:
            params["guidance_scale"] = guidance_scale
        if seed is not None:
            params["seed"] = seed
        if negative_prompt:
            params["negative_prompt"] = negative_prompt
    else:
        ignored: list[str] = []
        if num_inference_steps is not None:
            ignored.append("num_inference_steps")
        if guidance_scale is not None:
            ignored.append("guidance_scale")
        if seed is not None:
            ignored.append("seed")
        if negative_prompt:
            ignored.append("negative_prompt")
        if lora_weights:
            ignored.append("lora_weights")
        if ignored:
            warnings.append(
                f"Expert parameters ({', '.join(ignored)}) are ignored in fast mode"
            )

    # 6) LoRA 全局可用 (不限模式)
    temp_loras: list[str] = []
    if loras:
        parsed_weights: Optional[list[float]] = None
        if mode == "expert" and lora_weights:
            try:
                parsed_weights = [float(w.strip()) for w in lora_weights.split(",")]
            except (ValueError, TypeError):
                warnings.append("lora_weights 解析失败,使用默认权重 0.8")
        temp_loras = _apply_temporary_loras(loras, parsed_weights)

    logger.info(
        "img2img: mode=%s file=%s size=%dx%d style=%s strength=%.2f",
        mode,
        file.filename,
        out_w,
        out_h,
        style,
        params["strength"],
    )

    start_ts = time.time()
    try:
        result = engine.generate_from_image(image=image, style=style, **params)
    except ValueError as exc:
        _cleanup_temporary_loras(temp_loras)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("img2img failed: %s", exc, exc_info=True)
        _cleanup_temporary_loras(temp_loras)
        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}")

    # 生成成功后清理临时 LoRA
    _cleanup_temporary_loras(temp_loras)
    elapsed = time.time() - start_ts

    try:
        current = engine.get_current_model_info() or {}
    except Exception:  # noqa: BLE001
        current = {}
    model_id = current.get("model_id") or model or "default"

    return JSONResponse(
        {
            "status": "ok",
            "image": _encode_image(result),
            "style": style,
            "mode": mode,
            "model": model_id,
            "width": out_w,
            "height": out_h,
            "aspect_ratio": aspect_ratio,
            "strength": params["strength"],
            "params_used": params,
            "generation_time_sec": round(elapsed, 2),
            "warnings": warnings,
        }
    )


# ===========================================================================
# 静态文件挂载 (必须在所有 API 路由之后)
# ===========================================================================
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")
    logger.info("Frontend static files mounted from %s", FRONTEND_DIST)
else:
    logger.warning(
        "Frontend dist not found at %s. Run 'npm run build' in frontend dir.",
        FRONTEND_DIST,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
