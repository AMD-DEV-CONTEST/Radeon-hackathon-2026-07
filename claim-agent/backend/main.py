# -*- coding: utf-8 -*-
"""
backend/main.py — 智能理赔 Agent FastAPI 后端

提供 5 个 /api/* 端点（单张 SSE / 批量 SSE / 追问 SSE / CSV 导出 / 健康检查），
并在根路径挂载静态文件目录（供前端构建产物托管）。

所有 SSE 端点使用同步生成器（`def gen():`），让 Starlette 在 threadpool 跑同步
代码，避免阻塞事件循环；响应头强制 `Cache-Control: no-cache` + `X-Accel-Buffering: no`，
禁止中间层缓冲，保证思考链逐 chunk 实时下发。
"""

# ---- 顶部先把项目根（backend 的父目录）注入 sys.path，再 import 项目内模块 ----
# 直接 `python backend/main.py` 运行时，sys.path[0] 是 backend/ 自身，需显式补项目根，
# 否则 `import agent` / `import config` 都会 ModuleNotFoundError。
import os as _os
import sys as _sys
_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

import config as cfg  # noqa: F401

# 日志脱敏中间件：尽早安装，确保后续所有 logging 输出都被脱敏拦截
import log_sanitizer
log_sanitizer.install_sanitizer()
import logging
logger = logging.getLogger(__name__)

from auth import create_access_token, verify_token, authenticate

import agent  # noqa: F401

# ---- 标准库与第三方 ----
import os
import json
import uuid
import tempfile
import asyncio
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

# ---- 项目内模块 ----
from agent.pipeline import process_invoice_stream, format_result_text, format_decision_card
from agent.batch_pipeline import process_batch_stream, list_images
from agent.agent import stream_followup
from tools.export_tool import export_batch_csv
from agent.memory import get_store


# --------------------------------------------------------------------------- #
# 应用与中间件
# --------------------------------------------------------------------------- #
app = FastAPI(title="Smart Claim Agent API", version="1.0")

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
    """把 dict 序列化为 SSE data 行。"""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _save_upload(upload: UploadFile) -> str:
    """把 UploadFile 保存到 tempfile（保留扩展名），返回临时文件路径。"""
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
    return uuid.uuid4().hex[:12]


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
# Task 1: 健康检查（无需鉴权，放行）
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "claim-agent-backend"}


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
# Task 2: 单张发票处理（SSE）
# --------------------------------------------------------------------------- #
@app.post("/api/invoice/process")
def process_invoice(
    image: UploadFile = File(...),
    do_verify: bool = Form(False),
    session_id: Optional[str] = Form(None),
    _: str = Depends(verify_token),
):
    tmp_path = _save_upload(image)
    if not session_id:
        session_id = _new_session_id()
    logger.info(f"[access] invoice_process session={session_id} file={image.filename}")

    def gen():
        try:
            for ev in process_invoice_stream(
                tmp_path, do_verify=do_verify, session_id=session_id
            ):
                if "status" in ev:
                    yield _sse({"type": "status", "text": ev["status"]})
                elif ev.get("done"):
                    yield _sse({"type": "done", "result": ev.get("result")})
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


# --------------------------------------------------------------------------- #
# Task 3: 批量发票处理（SSE）
# --------------------------------------------------------------------------- #
@app.post("/api/batch/process")
def process_batch(
    files: List[UploadFile] = File(...),
    do_verify: bool = Form(False),
    session_id: Optional[str] = Form(None),
    _: str = Depends(verify_token),
):
    tmp_paths = [_save_upload(f) for f in files]
    if not session_id:
        session_id = _new_session_id()
    logger.info(f"[access] batch_process session={session_id} files={len(files)}")

    def gen():
        try:
            for ev in process_batch_stream(
                tmp_paths, do_verify=do_verify, session_id=session_id
            ):
                if "status" in ev:
                    yield _sse({"type": "status", "text": ev["status"]})
                elif ev.get("done"):
                    yield _sse({"type": "done", "result": ev.get("result")})
        finally:
            for p in tmp_paths:
                if os.path.exists(p):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


# --------------------------------------------------------------------------- #
# Task 4: 追问（SSE，思考链逐 chunk 实时下发，禁止批处理）
# --------------------------------------------------------------------------- #
@app.post("/api/followup")
def followup(req: FollowupReq, _: str = Depends(verify_token)):
    message = req.message
    session_id = req.session_id or _new_session_id()
    logger.info(f"[access] followup session={session_id} message={message!r}")

    def gen():
        # 关键约束：每个 chunk 立即 yield，绝不累积多个 chunk 再 yield
        try:
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
# Task 5: 批量结果 CSV 导出
# --------------------------------------------------------------------------- #
@app.get("/api/session/{session_id}/csv")
def export_session_csv(session_id: str, _: str = Depends(verify_token)):
    logger.info(f"[access] export_csv session={session_id}")
    batch = get_store().get_batch_claim(session_id)
    if not batch or not batch.get("ok"):
        raise HTTPException(status_code=404, detail="Batch review results not found for this session")

    # export_batch_csv(batch_result) 返回带 UTF-8 BOM 的 CSV 字符串。
    # 直接用 UTF-8 编码为 bytes，无需落盘临时文件（BOM 已由 export_batch_csv 写入）。
    content = export_batch_csv(batch).encode("utf-8")

    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=batch_{session_id}.csv"},
    )


# --------------------------------------------------------------------------- #
# 静态文件挂载（必须在所有路由定义之后，避免吞掉 /api/* 路由）
# --------------------------------------------------------------------------- #
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
