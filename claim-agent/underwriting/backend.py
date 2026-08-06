# -*- coding: utf-8 -*-
"""
underwriting/backend.py — 核保风险 Agent FastAPI 后端（端口 8002）

复用 ``backend/main.py`` 的 FastAPI + SSE 模式（同步生成器 + StreamingResponse +
``data: {json}\\n\\n`` 推送），但路由前缀统一为 ``/api/underwriting``，端口用
``cfg.UNDERWRITING_PORT``（默认 8002），与理赔后端（8001）/Gradio（7860）/VLM（8000）
完全隔离。

端点（对齐 spec.md「FastAPI 后端与 SSE」）：
- ``GET  /api/health``                            → ``{"ok": true}``
- ``POST /api/underwriting/process``              → 单份核保 SSE（status / done / session）
- ``POST /api/underwriting/batch``                → 批量核保 SSE（progress / done / session）
- ``POST /api/underwriting/followup``             → 追问 SSE（reasoning / content / done / error / session）
- ``GET  /api/underwriting/session/{id}/csv``     → 批量结果 CSV（UTF-8 BOM）
- ``GET  /``                                      → 前端首页（underwriting/static/index.html）
- ``/static/*``                                   → 静态资源

SSE 设计要点（沿用 backend/main.py）：
- 同步生成器 ``def gen():`` 让 Starlette 在 threadpool 跑同步代码，不阻塞事件循环；
- 响应头强制 ``Cache-Control: no-cache`` + ``X-Accel-Buffering: no``，禁止中间层缓冲，
  保证思考链逐 chunk 实时下发；
- 每个 chunk 立即 yield，绝不累积多个 chunk 再 yield（followup 端点尤其关键）。

会话隔离（SubTask 9.3）：所有 SSE 端点透传 session_id 给底层流水线/追问；未提供时
用 ``uuid4().hex[:12]`` 生成，并随首条 SSE 事件 ``{"type":"session","session_id":...}``
返回给前端，让前端能记录并后续追问/导出 CSV。

入口：``python -m underwriting.backend``
"""

# ---- 顶部先把项目根注入 sys.path，再 import 项目内模块 ----
# 直接 `python -m underwriting.backend` 运行时，需显式补项目根，
# 否则 `import config` / `import underwriting` 会 ModuleNotFoundError。
import os as _os
import sys as _sys
_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

import underwriting  # noqa: F401  注入 sys.path（确保 import config 可用）
import config as cfg  # noqa: F401

# 日志脱敏中间件：尽早安装，确保后续所有 logging 输出都被脱敏拦截
import log_sanitizer
log_sanitizer.install_sanitizer()
import logging
logger = logging.getLogger(__name__)

from auth import create_access_token, verify_token, authenticate

# ---- 标准库与第三方 ----
import os
import json
import uuid
import tempfile
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import StreamingResponse, Response, HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

# ---- 项目内模块（直接调用已实现的核保流水线/批量/Agent/记忆）----
from underwriting import config as uwcfg
from underwriting.pipeline import process_report_stream
from underwriting.batch_pipeline import process_batch_stream, export_batch_csv
from underwriting.agent import stream_followup
from underwriting.memory import get_store


# --------------------------------------------------------------------------- #
# 应用与中间件
# --------------------------------------------------------------------------- #
app = FastAPI(title="Underwriting Risk Agent API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# 通用辅助
# --------------------------------------------------------------------------- #
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def _sse(obj: dict) -> str:
    """把 dict 序列化为 SSE data 行（与 backend/main.py 一致）。"""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _save_upload(upload: UploadFile) -> str:
    """把 UploadFile 保存到 tempfile（保留扩展名），返回临时文件路径。

    与 backend/main.py 的 _save_upload 一致；异常时清理临时文件并 re-raise。
    """
    suffix = ""
    if upload.filename:
        _, ext = os.path.splitext(upload.filename)
        if ext:
            suffix = ext
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            while True:
                chunk = upload.file.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise
    return tmp_path


def _new_session_id() -> str:
    """生成 12 位会话标识（与 backend/main.py 一致）。"""
    return uuid.uuid4().hex[:12]


def _cleanup(*paths: str):
    """清理一个或多个临时文件，忽略不存在/OSError。"""
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.unlink(p)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# Pydantic 请求体
# --------------------------------------------------------------------------- #
class FollowupReq(BaseModel):
    message: str
    session_id: Optional[str] = None


class LoginReq(BaseModel):
    username: str
    password: str


# --------------------------------------------------------------------------- #
# SubTask 9.1: 健康检查（无需鉴权，放行）
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    """健康检查：返回 ``{"ok": true}``（对齐 spec.md 场景）。"""
    return {"ok": True}


# --------------------------------------------------------------------------- #
# 登录：校验用户名密码 → 签发 JWT（无需鉴权，放行）
# --------------------------------------------------------------------------- #
@app.post("/api/login")
def login(req: LoginReq):
    if not authenticate(req.username, req.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token, expires_in = create_access_token(req.username)
    logger.info(f"[access] login success user={req.username}")
    return {"token": token, "expires_in": expires_in, "username": req.username}


# --------------------------------------------------------------------------- #
# SubTask 9.2: 单份核保 SSE
# --------------------------------------------------------------------------- #
@app.post("/api/underwriting/process")
def process_report(
    image: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    _: str = Depends(verify_token),
):
    """单份核保 SSE：保存图片 → 调用 process_report_stream → 逐事件转发。

    SSE 事件：
      - ``{"type":"session","session_id":...}``  仅在未提供 session_id 时作为首条事件
      - ``{"type":"status","text":...}``         来自 pipeline 的 ``{"status":...}``
      - ``{"type":"done","result":{...}}``       来自 pipeline 的 ``{"done":True,"result":...}``
    """
    tmp_path = _save_upload(image)
    generated = False
    if not session_id:
        session_id = _new_session_id()
        generated = True
    logger.info(f"[access] underwriting_process session={session_id}")

    def gen():
        try:
            if generated:
                # 首条事件回传生成的 session_id，让前端能记录并后续追问/导出
                yield _sse({"type": "session", "session_id": session_id})
            for ev in process_report_stream(tmp_path, session_id=session_id):
                if "status" in ev:
                    yield _sse({"type": "status", "text": ev["status"]})
                elif ev.get("done"):
                    yield _sse({"type": "done", "result": ev.get("result")})
        finally:
            _cleanup(tmp_path)

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


# --------------------------------------------------------------------------- #
# SubTask 9.2: 批量核保 SSE
# --------------------------------------------------------------------------- #
@app.post("/api/underwriting/batch")
def process_batch(
    files: List[UploadFile] = File(...),
    session_id: Optional[str] = Form(None),
    _: str = Depends(verify_token),
):
    """批量核保 SSE：保存多图 → 调用 process_batch_stream → 逐事件转发。

    SSE 事件：
      - ``{"type":"session","session_id":...}``  仅在未提供 session_id 时作为首条事件
      - ``{"type":"progress",...}``              来自 batch 的 ``{"type":"progress",...}``
        （字段：status/index/total/filename/stage/conclusion）
      - ``{"type":"done","result":{...}}``       来自 batch 的 ``{"type":"done","result":...}``
    """
    tmp_paths = [_save_upload(f) for f in files]
    generated = False
    if not session_id:
        session_id = _new_session_id()
        generated = True
    logger.info(f"[access] underwriting_batch session={session_id} files={len(files)}")

    def gen():
        try:
            if generated:
                yield _sse({"type": "session", "session_id": session_id})
            for ev in process_batch_stream(tmp_paths, session_id=session_id):
                t = ev.get("type")
                if t == "progress":
                    yield _sse({
                        "type": "progress",
                        "status": ev.get("status"),
                        "index": ev.get("index"),
                        "total": ev.get("total"),
                        "filename": ev.get("filename"),
                        "stage": ev.get("stage"),
                        "conclusion": ev.get("conclusion"),
                    })
                elif t == "done":
                    yield _sse({"type": "done", "result": ev.get("result")})
        finally:
            _cleanup(*tmp_paths)

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


# --------------------------------------------------------------------------- #
# SubTask 9.2: 追问 SSE（思考链逐 chunk 实时下发，禁止批处理）
# --------------------------------------------------------------------------- #
@app.post("/api/underwriting/followup")
def followup(req: FollowupReq, _: str = Depends(verify_token)):
    """追问 SSE：调用 stream_followup → 逐 chunk 立即转发。

    SSE 事件：
      - ``{"type":"session","session_id":...}``  仅在未提供 session_id 时作为首条事件
      - ``{"type":"reasoning","text":...}``      思考链片段（Qwen3 reasoning_content）
      - ``{"type":"content","text":...}``        正文片段
      - ``{"type":"done"}``                      流式结束
      - ``{"type":"error","text":...}``          异常情况

    关键约束（与 backend/main.py 的 followup 端点一致）：每个 chunk 立即 yield，
    绝不累积多个 chunk 再 yield，保证思考链完整不断。
    """
    message = req.message
    generated = False
    logger.info(f"[access] underwriting_followup session={req.session_id} message={message!r}")
    if not req.session_id:
        session_id = _new_session_id()
        generated = True
    else:
        session_id = req.session_id

    def gen():
        try:
            if generated:
                yield _sse({"type": "session", "session_id": session_id})
            for ev in stream_followup(message, session_id=session_id):
                t = ev.get("type")
                if t == "reasoning":
                    yield _sse({"type": "reasoning", "text": ev.get("text", "")})
                elif t == "content":
                    yield _sse({"type": "content", "text": ev.get("text", "")})
                elif t == "done":
                    yield _sse({"type": "done"})
                    return
                elif t == "error":
                    yield _sse({"type": "error", "text": ev.get("text", "")})
                    return
        except Exception as e:
            # 生成器异常时尝试下发 error 事件，避免前端无限等待
            yield _sse({"type": "error", "text": f"Backend generator error: {e}"})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


# --------------------------------------------------------------------------- #
# SubTask 9.2: 批量结果 CSV 导出
# --------------------------------------------------------------------------- #
@app.get("/api/underwriting/session/{session_id}/csv")
def export_session_csv(session_id: str, _: str = Depends(verify_token)):
    """导出批量核保结果为带 UTF-8 BOM 的 CSV（Excel 友好）。

    从 memory 取 ``get_store().get_batch_report(session_id)``：
      - 不存在或 ok=False → 404 ``{"detail":"未找到批量结果"}``
      - 存在 → 调用 ``export_batch_csv(batch)`` 拿到带 BOM 的 CSV 字符串，
        encode("utf-8") 作为 Response content 返回（BOM 已由 export_batch_csv 写入）。
    """
    logger.info(f"[access] underwriting_export_csv session={session_id}")
    batch = get_store().get_batch_report(session_id)
    if not batch or not batch.get("ok"):
        raise HTTPException(status_code=404, detail="Batch results not found")

    content = export_batch_csv(batch).encode("utf-8")
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=underwriting_{session_id}.csv",
        },
    )


# --------------------------------------------------------------------------- #
# SubTask 9.1: 前端首页 + 静态托管
# --------------------------------------------------------------------------- #
# 确保静态目录存在（Task 10 会创建真实前端；当前先保证挂载不报错）
os.makedirs(STATIC_DIR, exist_ok=True)


@app.get("/")
def index():
    """返回前端首页 ``underwriting/static/index.html``。

    Task 10 会创建真实前端；当前若 index.html 不存在则返回占位 HTML，
    指向 /api/health 便于冒烟验证，但 app 不应崩溃。
    """
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path, media_type="text/html")
    # 占位 HTML（Task 10 会替换为真实前端）
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Underwriting Risk Agent</title></head>"
        "<body style='font-family:sans-serif;padding:24px;'>"
        "<h1>Underwriting Risk Agent backend is ready</h1>"
        "<p>Frontend page (underwriting/static/index.html) not yet created (Task 10).</p>"
        "<p>Health check: <a href='/api/health'>/api/health</a></p>"
        "<ul>"
        "<li>POST /api/underwriting/process — Single report underwriting SSE</li>"
        "<li>POST /api/underwriting/batch — Batch underwriting SSE</li>"
        "<li>POST /api/underwriting/followup — Follow-up SSE</li>"
        "<li>GET /api/underwriting/session/{id}/csv — CSV export</li>"
        "</ul></body></html>"
    )


# 静态文件挂载（必须在所有路由定义之后，避免吞掉 /api/* 与 / 路由）
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=uwcfg.UNDERWRITING_PORT)
