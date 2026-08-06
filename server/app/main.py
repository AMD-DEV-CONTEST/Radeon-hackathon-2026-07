"""独立游戏 AI 资产生成平台 - 后端 API（P2/P3/P4）"""
import json
import shutil
import time
from contextlib import asynccontextmanager
from math import ceil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import comfy, db, translator

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOWS_DIR = PROJECT_ROOT / "workflows"
WEB_DIR = PROJECT_ROOT / "web"
COMFY_INPUT_DIR = PROJECT_ROOT / "ComfyUI" / "input"

# 工作流名 → 模板文件名
TEMPLATE_FILES = {
    "W1": "W1_concept.json",
    "W2": "W2_depth.json",
    "W3": "W3_material.json",
    "W4": "W4_music.json",
    "W5": "W5_sfx.json",
    "W6": "W6_sprite.json",
    "W7": "W7_model.json",
}

# 每个工作流允许从网页覆盖的参数 → (节点id, 输入名) 或 [(节点id, 输入名), ...]
PARAM_MAP = {
    "W1": {
        "text": ("2", "text"),
        "negative": ("3", "text"),
        "width": ("4", "width"),
        "height": ("4", "height"),
        "seed": ("5", "seed"),
        "steps": ("5", "steps"),
        "cfg": ("5", "cfg"),
    },
    "W2": {"resolution": ("11", "resolution")},
    "W3": {
        "resolution": ("11", "resolution"),
        "strength": ("12", "strength"),
        "roughness_scale": ("12", "roughness_scale"),
        "metalness": ("12", "metalness"),
    },
    "W4": {"prompt": ("20", "prompt"), "duration": ("20", "duration"), "seed": ("20", "seed")},
    "W5": {"kind": ("22", "kind"), "duration": ("22", "duration"), "seed": ("22", "seed")},
    "W6": {
        "text": ("2", "text"),
        "negative": ("3", "text"),
        "action": ("32", "action"),
        "frames": [("32", "frames"), ("36", "amount")],
        "width": [("35", "width"), ("32", "width")],
        "height": [("35", "height"), ("32", "height")],
        "seed": ("5", "seed"),
        "steps": ("5", "steps"),
        "cfg": ("5", "cfg"),
        "denoise": ("5", "denoise"),
        "strength": ("34", "strength"),
    },
    "W7": {
        "geometry_resolution": ("3", "geometry_resolution"),
        "threshold": ("3", "threshold"),
        "chunk_size": ("2", "chunk_size"),
    },
}

WORKFLOW_META = {
    "W1": {
        "title": "W1 · 概念原画",
        "description": "文本设定 → 高清概念图（SDXL）",
        "inputs": ["text", "negative", "width", "height", "seed", "steps", "cfg"],
        "accepts_image": False,
    },
    "W2": {
        "title": "W2 · 深度图",
        "description": "概念图 → 灰度深度图（MiDaS）",
        "inputs": ["resolution"],
        "accepts_image": True,
    },
    "W3": {
        "title": "W3 · 3D 贴图材质",
        "description": "概念图 → 深度 → 法线/高度/粗糙度/金属度",
        "inputs": ["resolution", "strength", "roughness_scale", "metalness"],
        "accepts_image": True,
    },
    "W4": {
        "title": "W4 · 背景音乐",
        "description": "音乐风格文本 → 暗黑氛围电子乐（MusicGen）",
        "inputs": ["prompt", "duration", "seed"],
        "accepts_image": False,
    },
    "W5": {
        "title": "W5 · 环境音效",
        "description": "玻璃杯碰撞 / 含糊交谈 / 酒吧环境音",
        "inputs": ["kind", "duration", "seed"],
        "accepts_image": False,
    },
    "W6": {
        "title": "W6 · 序列帧图集",
        "description": "角色设定图 + 动作指令 → 帧图集 + JSON 配置",
        "inputs": ["text", "negative", "action", "frames", "width", "height", "seed", "steps", "cfg", "denoise", "strength"],
        "accepts_image": True,
    },
    "W7": {
        "title": "W7 · 2D 转 3D 角色模型",
        "description": "角色设定图 → 3D 模型（TripoSR）",
        "inputs": ["geometry_resolution", "threshold", "chunk_size"],
        "accepts_image": True,
    },
}

FRAME_DURATIONS = {"run": 80, "attack": 110, "idle": 160}

MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
    ".json": "application/json",
    ".glb": "model/gltf-binary",
    ".obj": "text/plain",
    ".mtl": "text/plain",
}


def _media_type(filename: str) -> str:
    return MIME_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


# 需要自动中→英翻译的提示词字段
PROMPT_FIELDS = {"W1": ["text", "negative"], "W4": ["prompt"], "W6": ["text", "negative"]}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    COMFY_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Indie Game Asset Studio", version="0.4.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/scene.html")
def scene_page():
    return FileResponse(WEB_DIR / "scene.html")


def _load_template(name: str) -> dict:
    path = WORKFLOWS_DIR / TEMPLATE_FILES.get(name, f"{name}.json")
    if not path.exists():
        raise HTTPException(404, f"工作流 {name} 不存在")
    return json.loads(path.read_text(encoding="utf-8"))


def _apply_params(workflow: dict, name: str, params: dict, batch: str) -> dict:
    for key, value in params.items():
        targets = PARAM_MAP.get(name, {}).get(key)
        if targets is None:
            continue
        if not isinstance(targets, list):
            targets = [targets]
        for node_id, input_name in targets:
            if node_id in workflow:
                workflow[node_id]["inputs"][input_name] = value
    # 输出按「批次/可读标签」归档，例如 废土酒吧/W1_concept_00001_.png
    for node in workflow.values():
        if node["class_type"] in ("SaveImage", "SaveAudioAdvanced", "SaveMeshGLB"):
            label = node["inputs"].get("filename_prefix") or name
            label = Path(label).name or name
            node["inputs"]["filename_prefix"] = f"{batch}/{label}"
    return workflow


def _collect_outputs(history: dict) -> list[dict]:
    outputs = []
    for node_output in (history.get("outputs") or {}).values():
        for image in node_output.get("images", []):
            outputs.append(
                {
                    "filename": image["filename"],
                    "subfolder": image.get("subfolder", ""),
                    "type": image.get("type", "output"),
                    "kind": "image",
                }
            )
        for audio in node_output.get("audio", []):
            outputs.append(
                {
                    "filename": audio["filename"],
                    "subfolder": audio.get("subfolder", ""),
                    "type": audio.get("type", "output"),
                    "kind": "audio",
                }
            )
        # 兼容新旧 ComfyUI：ui 可能位于顶层或 "ui" 键下
        mesh_list = node_output.get("ui", {}).get("mesh", []) or node_output.get("mesh", [])
        for mesh in mesh_list:
            outputs.append(
                {
                    "filename": mesh["filename"],
                    "subfolder": mesh.get("subfolder", ""),
                    "type": mesh.get("type", "output"),
                    "kind": "mesh",
                }
            )
    return outputs


def _refresh_job(job: dict) -> dict:
    """查询 ComfyUI，把排队/运行中的任务状态同步到本地"""
    if not job or not job.get("prompt_id"):
        return job
    try:
        history = comfy.get_history(job["prompt_id"])
    except Exception:
        return job
    if history is None:
        return job
    status = (history.get("status") or {}).get("status_str")
    if status == "success":
        db.update_job(
            job["id"],
            status="done",
            outputs=json.dumps(_collect_outputs(history), ensure_ascii=False),
        )
    elif status == "error":
        err = "未知错误"
        for msg in (history.get("status") or {}).get("messages", []):
            if msg[0] == "execution_error":
                err = msg[1].get("exception_message", err)
        db.update_job(job["id"], status="error", error=err)
    return db.get_job(job["id"])


@app.get("/api/workflows")
def list_workflows():
    return [{"name": k, **v} for k, v in WORKFLOW_META.items()]


@app.get("/api/files")
def list_files(location: str = "input"):
    """列出服务器上的图片文件（输入目录或输出目录，输出目录含批次子文件夹）"""
    base = COMFY_INPUT_DIR if location == "input" else PROJECT_ROOT / "ComfyUI" / "output"
    if not base.exists():
        return []
    files = []
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    if location == "input":
        for p in base.iterdir():
            if p.is_file() and p.suffix.lower() in exts:
                st = p.stat()
                files.append({"name": p.name, "size": st.st_size, "mtime": st.st_mtime})
    else:
        for sub in base.iterdir():
            if sub.is_dir():
                for p in sub.iterdir():
                    if p.is_file() and p.suffix.lower() in exts:
                        st = p.stat()
                        files.append({"name": f"{sub.name}/{p.name}", "size": st.st_size, "mtime": st.st_mtime})
            elif sub.is_file() and sub.suffix.lower() in exts:
                st = sub.stat()
                files.append({"name": sub.name, "size": st.st_size, "mtime": st.st_mtime})
    files.sort(key=lambda f: f["mtime"], reverse=True)
    return files


from pydantic import BaseModel


class TranslateRequest(BaseModel):
    text: str


@app.post("/api/translate")
def translate_text(req: TranslateRequest):
    """中文 → 英文；纯英文原样返回"""
    try:
        return {
            "text": translator.translate(req.text),
            "translated": translator.needs_translation(req.text),
        }
    except Exception as exc:
        raise HTTPException(502, f"翻译失败: {exc}")


@app.post("/api/jobs")
async def create_job(
    workflow: str = Form(...),
    params: str = Form("{}"),
    image: UploadFile | None = File(None),
    image_filename: str = Form(""),
    image_location: str = Form("input"),
    batch: str = Form(""),
):
    if workflow not in WORKFLOW_META:
        raise HTTPException(404, "未知工作流")
    try:
        params = json.loads(params)
    except json.JSONDecodeError:
        raise HTTPException(400, "params 必须是合法 JSON")

    # 提示词字段：中文自动翻译成英文（英文原样保留），失败则用原文
    for field in PROMPT_FIELDS.get(workflow, []):
        if field in params and isinstance(params[field], str):
            try:
                params[field] = translator.translate(params[field])
            except Exception:
                pass

    # 批次名：留空按时间自动生成；去掉路径分隔符等危险字符
    if not batch.strip():
        batch = time.strftime("%Y%m%d_%H%M%S")
    batch = "".join(c if c not in '/\\:*?"<>|' else "_" for c in batch.strip()) or "untitled"

    job_id = db.create_job(workflow, params, batch)
    template = _load_template(workflow)

    # 图片来源一：上传新文件 → 保存到 ComfyUI/input
    if image is not None and image.filename:
        filename = f"{job_id}_{Path(image.filename).name}"
        dest = COMFY_INPUT_DIR / filename
        with dest.open("wb") as f:
            shutil.copyfileobj(image.file, f)
    # 图片来源二：选择服务器已有图片（输出目录的会先复制到输入目录）
    elif image_filename:
        safe = Path(image_filename).name
        if image_location == "output":
            out_root = (PROJECT_ROOT / "ComfyUI" / "output").resolve()
            src = (out_root / image_filename.strip()).resolve()
            if out_root not in src.parents:
                raise HTTPException(400, "非法文件路径")
            if src.is_file():
                shutil.copy2(src, COMFY_INPUT_DIR / src.name)
            else:
                raise HTTPException(400, f"服务器输出目录不存在该图片: {image_filename}")
        if not (COMFY_INPUT_DIR / safe).is_file():
            raise HTTPException(400, f"服务器输入目录不存在该图片: {safe}")
        filename = safe
    else:
        filename = None

    if filename is not None:
        for node in template.values():
            if node["class_type"] == "LoadImage":
                node["inputs"]["image"] = filename

    workflow_json = _apply_params(template, workflow, params, batch)
    try:
        prompt_id = comfy.submit(workflow_json)
    except Exception as exc:
        db.update_job(job_id, status="error", error=str(exc))
        raise HTTPException(502, f"提交 ComfyUI 失败: {exc}")
    db.update_job(job_id, status="running", prompt_id=prompt_id)
    return db.get_job(job_id)
@app.get("/api/scene")
def scene_config(batch: str = ""):
    """按批次汇总资产，生成 3D 场景配置（前端 scene.html 使用）"""
    if not batch:
        raise HTTPException(400, "缺少 batch 参数")
    jobs = [j for j in db.list_jobs(200, batch) if j.get("status") == "done"]
    if not jobs:
        raise HTTPException(404, f"批次「{batch}」下没有已完成的任务")
    latest = {}
    for j in jobs:
        if j["workflow"] not in latest or j["created_at"] > latest[j["workflow"]]["created_at"]:
            latest[j["workflow"]] = j

    def first(job, idx=0):
        outs = job.get("outputs") or []
        if idx >= len(outs):
            return None
        return {"url": f"/api/jobs/{job['id']}/file/{idx}", "filename": outs[idx]["filename"]}

    # 概念图取该批次最早完成的 W1（环境），角色不参与场景主体
    w1_done = sorted(
        [j for j in jobs if j["workflow"] == "W1" and j.get("outputs")],
        key=lambda j: j["created_at"],
    )
    concept = first(w1_done[0]) if w1_done else None

    # 材质贴图按文件名识别（W3_normal/height/roughness/metalness），不依赖输出顺序
    w3 = latest.get("W3")
    materials = {"normal": None, "height": None, "roughness": None, "metalness": None}
    if w3 and w3.get("outputs"):
        for idx, out in enumerate(w3["outputs"]):
            fn = out["filename"].lower()
            for key in materials:
                if materials[key] is None and key in fn:
                    materials[key] = first(w3, idx)

    assets = {
        "concept": concept,
        "depth": first(latest.get("W2")),
        "materials": materials,
        "music": first(latest.get("W4")),
        "sfx": [first(j) for j in jobs if j["workflow"] == "W5" and j.get("outputs")],
    }

    w6 = latest.get("W6")
    if w6 and w6.get("outputs"):
        outs = w6["outputs"]
        assets["atlas"] = first(w6, len(outs) - 1)
        assets["frames"] = [first(w6, i) for i in range(len(outs) - 1)]
        p = w6["params"]
        frames = max(1, int(p.get("frames", 8)))
        width = int(p.get("width", 512))
        height = int(p.get("height", 512))
        action = p.get("action", "run")
        columns = min(4, frames)
        assets["sprite_config"] = {
            "action": action,
            "frames": frames,
            "frame_width": width,
            "frame_height": height,
            "columns": columns,
            "rows": ceil(frames / columns),
            "frame_duration_ms": FRAME_DURATIONS.get(action, 80),
        }
    else:
        assets["atlas"] = assets["frames"] = assets["sprite_config"] = None

    # W7 3D 模型（GLB 单文件优先）
    assets["model"] = None
    w7 = latest.get("W7")
    if w7 and w7.get("outputs"):
        assets["model"] = next(
            (first(w7, idx) for idx, out in enumerate(w7["outputs"]) if out["filename"].lower().endswith(".glb")),
            None,
        )

    return {"batch": batch, "assets": assets, "jobs": [{"id": j["id"], "workflow": j["workflow"], "status": j["status"]} for j in jobs]}

@app.get("/api/jobs")
def jobs_list(limit: int = 20, batch: str = ""):
    return [_refresh_job(j) for j in db.list_jobs(limit, batch)]


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str):
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    return _refresh_job(job)


@app.get("/api/jobs/{job_id}/outputs")
def job_outputs(job_id: str):
    job = _refresh_job(db.get_job(job_id))
    if job is None:
        raise HTTPException(404, "任务不存在")
    return job.get("outputs", [])


@app.get("/api/jobs/{job_id}/sprite-config")
def sprite_config(job_id: str):
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    if job["workflow"] != "W6":
        raise HTTPException(400, "仅 W6 序列帧任务有图集配置")
    p = job["params"]
    frames = max(1, int(p.get("frames", 8)))
    width = int(p.get("width", 512))
    height = int(p.get("height", 512))
    action = p.get("action", "run")
    columns = min(4, frames)
    rows = ceil(frames / columns)
    return {
        "action": action,
        "frames": frames,
        "frame_width": width,
        "frame_height": height,
        "columns": columns,
        "rows": rows,
        "frame_duration_ms": FRAME_DURATIONS.get(action, 80),
        "files": job.get("outputs", []),
    }


@app.get("/api/jobs/{job_id}/file/{index}")
def job_file(job_id: str, index: int):
    """代理输出文件字节（图片/音频），浏览器只访问 8000，不直连 8188"""
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    outputs = job.get("outputs") or []
    if index < 0 or index >= len(outputs):
        raise HTTPException(404, "输出不存在")
    out = outputs[index]
    try:
        data = comfy.fetch_file(out["filename"], out.get("subfolder", ""), out.get("type", "output"))
    except Exception as exc:
        raise HTTPException(502, f"读取输出失败: {exc}")
    return Response(data, media_type=_media_type(out["filename"]))


@app.get("/api/jobs/{job_id}/image")
def job_image(job_id: str):
    """第一个输出（兼容旧接口），同样走代理"""
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    outputs = job.get("outputs") or []
    if not outputs:
        raise HTTPException(404, "任务还没有输出")
    first = outputs[0]
    try:
        data = comfy.fetch_file(first["filename"], first.get("subfolder", ""), first.get("type", "output"))
    except Exception as exc:
        raise HTTPException(502, f"读取输出失败: {exc}")
    return Response(data, media_type=_media_type(first["filename"]))


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
