# -*- coding: utf-8 -*-
"""Private RAG Agent —— 自研 Web 服务（FastAPI + SSE 流式）。

为什么不用 Gradio：Gradio 组件受框架约束，无法做到"无 AI 味的专业级"三栏界面。
这里用原生 HTML/CSS/JS 前端 + FastAPI 后端：
  - /api/chat            SSE 流式对话（单 Agent / 多 Agent 并行），活动事件实时推送
  - /api/ingest          上传文档入库
  - /api/documents       列出知识库文档（已入库 + 待导入）
  - /api/documents/{doc} 删除文档
  - /api/sessions        会话管理（新建/切换/清空）
  - /api/gpu             AMD GPU 实时监控（rocm-smi / pyamdgpuinfo，本地无 AMD 时演示数据）
  - /api/health          服务与后端状态

启动：python main.py ui   （或 python -m uvicorn ui.server:app）
"""
import asyncio
import json
import os
import shutil
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

with open("config.yaml", "r", encoding="utf-8") as _f:
    CFG = yaml.safe_load(_f)

SERVER_CFG = CFG.get("server", {})
HOST = SERVER_CFG.get("host", "0.0.0.0")
PORT = SERVER_CFG.get("port", 7860)
DOCS_DIR = CFG.get("rag", {}).get("docs_dir", "./data/docs")
DEMO_GPU = SERVER_CFG.get("demo_gpu", True)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# 共享后端实例（llm/rag 全局单例；每个会话独立 Agent 实例）
from agent.llm import LLMBackend
from agent.rag import RAGStore
from agent.agent import Agent
from agent.multi_agent import MultiAgentOrchestrator

LLM = None
RAG = None
SESSIONS: dict = {}          # sid -> {"agent": Agent, "title": str, "created": ts}
MAIN_ORCH = None

# 初始化锁：首次 _get_shared() 时可能有多个并发请求（/api/chat SSE +
# /api/documents 轮询）同时看到 RAG is None。ChromaDB 同一路径同进程只允许
# 一个 PersistentClient，并发创建第二个会抛 "Could not connect to tenant"
# 并污染其共享系统状态，导致后续所有检索崩溃。此锁保证单例只创建一次。
_INIT_LOCK = threading.Lock()


def _get_shared():
    global LLM, RAG, MAIN_ORCH
    if LLM is not None and RAG is not None and MAIN_ORCH is not None:
        return LLM, RAG, MAIN_ORCH
    with _INIT_LOCK:
        if LLM is None:
            LLM = LLMBackend()
        if RAG is None:
            RAG = RAGStore(LLM)
        if MAIN_ORCH is None:
            MAIN_ORCH = MultiAgentOrchestrator(Agent(llm=LLM, rag=RAG), n_workers=3)
    return LLM, RAG, MAIN_ORCH


def _get_agent(sid: str) -> Agent:
    if sid not in SESSIONS:
        llm, rag, _ = _get_shared()
        SESSIONS[sid] = {
            "agent": Agent(llm=llm, rag=rag),
            "title": "新会话",
            "created": time.time(),
        }
    return SESSIONS[sid]["agent"]


def _stream_bridge(gen, q: asyncio.Queue, loop):
    """把同步生成器的事件桥接到 asyncio 队列（线程安全）。"""
    def run():
        try:
            for ev in gen:
                asyncio.run_coroutine_threadsafe(q.put(ev), loop)
        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                q.put({"type": "error", "error": str(e)[:300]}), loop)
        finally:
            asyncio.run_coroutine_threadsafe(q.put(None), loop)
    threading.Thread(target=run, daemon=True).start()


# ------------------------------------------------------------------ FastAPI
from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

app = FastAPI(title="Private RAG Agent")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str = "default"
    mode: str = "single"          # single | multi
    n_workers: int = 3
    tools_enabled: bool = True    # 工具调用开关（false = 纯问答，不触发工具）


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    _get_shared()
    agent = _get_agent(req.session_id)
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    if req.mode == "multi":
        orch = MultiAgentOrchestrator(agent, n_workers=req.n_workers)
        _stream_bridge(orch.run_events(req.message, n=req.n_workers), q, loop)
    else:
        _stream_bridge(agent.ask_events(req.message, tools_enabled=req.tools_enabled), q, loop)

    async def event_gen():
        while True:
            ev = await q.get()
            if ev is None:
                break
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ----------------------------------------------------------------- 知识库
@app.post("/api/ingest")
async def api_ingest(file: UploadFile = File(...)):
    llm, rag, _ = _get_shared()
    os.makedirs(DOCS_DIR, exist_ok=True)
    safe_name = os.path.basename(file.filename or "")
    if not safe_name:
        raise HTTPException(400, "空文件名")
    path = os.path.join(DOCS_DIR, safe_name)
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        n = rag.add_document(path)
        return {"ok": True, "file": safe_name, "chunks": n, "note": "已入库" if n else "未变化/解析为空"}
    except Exception as e:
        raise HTTPException(500, f"解析失败: {e}")


@app.post("/api/ingest_many")
async def api_ingest_many(files: list[UploadFile] = File(...)):
    """批量导入：一次接收多个文件（用于"扫描文件夹"的浏览器文件夹选择器）。"""
    llm, rag, _ = _get_shared()
    os.makedirs(DOCS_DIR, exist_ok=True)
    total, ok = 0, 0
    for f in files:
        safe = os.path.basename(f.filename or "")
        if not safe:
            continue
        path = os.path.join(DOCS_DIR, safe)
        try:
            with open(path, "wb") as out:
                shutil.copyfileobj(f.file, out)
            total += rag.add_document(path)
            ok += 1
        except Exception:
            pass
    return {"ok": True, "total_chunks": total, "count": ok}


# 全盘扫描时跳过的目录（缓存 / 依赖 / 系统 / 应用数据 / 浏览器数据，避免无关内容）
_SKIP_DIRS = {"appdata", "application data", "roaming", "local", "locallow",
              "node_modules", "venv", ".venv", "env", ".env", ".git",
              "__pycache__", ".cache", ".gradle", ".m2", ".idea", ".vscode",
              "site-packages", ".claude", ".kimi", ".grok", ".cursor", "mempalace",
              "temp", "tmp", "windows", "program files", "program files (x86)",
              "programdata", "recycle", "onedrive",
              "user data", "chrome", "chromeprofilebackup", "mozilla", "firefox",
              "google", "chrome profile"}
_MAX_ALL_FILES = 200          # 全盘读取的文件数上限（防过载）
_MAX_FILE_MB = 50             # 单文件大小上限
# "全部读取"只收真正的文档格式（排除 .json 配置 / .txt 日志等噪声）
_ALL_DOC_EXTS = {".pdf", ".docx", ".md", ".csv", ".xlsx", ".pptx"}


@app.post("/api/ingest_all")
def api_ingest_all():
    """全部读取：扫描本机用户目录下的文档，全部导入知识库。

    只收真正的文档格式（PDF / Word / Markdown / Excel / PPT），
    自动跳过缓存、依赖、系统、应用数据与浏览器数据目录——
    避免把配置文件和日志等噪声收进来。
    """
    llm, rag, _ = _get_shared()
    home = os.path.expanduser("~")
    found = []
    for root, dirs, files in os.walk(home):
        dirs[:] = [d for d in dirs
                   if d.lower() not in _SKIP_DIRS and not d.startswith(".")]
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in _ALL_DOC_EXTS:
                continue
            p = os.path.join(root, fn)
            try:
                if os.path.getsize(p) > _MAX_FILE_MB * 1024 * 1024:
                    continue
            except OSError:
                continue
            found.append(p)
            if len(found) >= _MAX_ALL_FILES:
                break
        if len(found) >= _MAX_ALL_FILES:
            break
    total = 0
    for p in found:
        try:
            total += rag.add_document(p)
        except Exception:
            pass
    return {"ok": True, "total_chunks": total, "found": len(found)}


@app.get("/api/documents")
def api_documents():
    llm, rag, _ = _get_shared()
    try:
        indexed = rag.list_documents()
        indexed_names = {d["doc"] for d in indexed}
        pending = []
        if os.path.isdir(DOCS_DIR):
            for f in sorted(os.listdir(DOCS_DIR)):
                if os.path.isfile(os.path.join(DOCS_DIR, f)) and f not in indexed_names:
                    pending.append(f)
        return {"indexed": indexed, "pending": pending,
                "docs_dir": DOCS_DIR}
    except Exception as e:
        return {"indexed": [], "pending": [], "docs_dir": DOCS_DIR, "error": str(e)}


@app.get("/api/documents/{doc}")
def api_doc_content(doc: str, limit: int = 6000):
    """返回文档原文内容（供前端点击引用后查看）。"""
    llm, rag, _ = _get_shared()
    safe = os.path.basename(doc)
    try:
        text = rag.get_document(safe, limit=limit)
        if not text:
            raise HTTPException(404, f"文档 {safe} 不在知识库中")
        return {"doc": safe, "content": text,
                "chars": len(text), "truncated": len(text) >= limit}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.delete("/api/documents/{doc}")
def api_remove_doc(doc: str):
    llm, rag, _ = _get_shared()
    safe = os.path.basename(doc)
    n = rag.remove_document(safe)
    # 同步删除源文件
    path = os.path.join(DOCS_DIR, safe)
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
    return {"ok": True, "removed_chunks": n}


@app.post("/api/ingest_dir")
def api_ingest_dir():
    llm, rag, _ = _get_shared()
    n = rag.index_dir(DOCS_DIR)
    return {"ok": True, "total_chunks": n}


@app.post("/api/ingest_path")
def api_ingest_path(payload: dict = Body(...)):
    """把指定路径下的文档导入知识库（支持目录或单个文件）。

    用途：让用户决定"检索哪些本地内容"——输入一个文件夹/文件路径，
    只把这些内容收进知识库，搜索范围严格限定在已导入的文档内。
    相对路径按 docs 目录解析（供"待导入"列表的单文件点击使用）。
    """
    llm, rag, _ = _get_shared()
    path = (payload.get("path") or "").strip().strip('"').strip("'")
    if not path:
        raise HTTPException(400, "路径不能为空")
    if not os.path.isabs(path):
        path = os.path.join(DOCS_DIR, path)
    if os.path.isdir(path):
        n = rag.index_dir(path)
    elif os.path.isfile(path):
        n = rag.add_document(path)
    else:
        raise HTTPException(400, f"路径不存在或不可读: {path}")
    return {"ok": True, "total_chunks": n, "path": path}


# ----------------------------------------------------------------- 会话
@app.post("/api/sessions")
def api_new_session():
    sid = str(int(time.time() * 1000))
    _get_agent(sid)
    return {"ok": True, "session_id": sid}


@app.get("/api/sessions")
def api_list_sessions():
    out = [{"id": sid, "title": s["title"], "created": s["created"]}
           for sid, s in SESSIONS.items()]
    out.sort(key=lambda x: -x["created"])
    return {"sessions": out}


@app.post("/api/sessions/{sid}/clear")
def api_clear_session(sid: str):
    if sid in SESSIONS:
        SESSIONS[sid]["agent"].memory.clear_short()
    return {"ok": True}


@app.delete("/api/sessions/{sid}")
def api_delete_session(sid: str):
    """真实删除会话：从内存移除，侧栏不再残留。"""
    SESSIONS.pop(sid, None)
    return {"ok": True}


@app.get("/api/sessions/{sid}/history")
def api_session_history(sid: str):
    """返回会话的短程对话历史（供切换会话时恢复界面）。"""
    if sid not in SESSIONS:
        raise HTTPException(404, "会话不存在")
    msgs = SESSIONS[sid]["agent"].memory.short_messages()
    return {"session_id": sid, "messages": msgs}


# ----------------------------------------------------------------- GPU
_GPU_CACHE = {"ts": 0, "data": None}


def _read_gpu_metrics() -> dict:
    """读取 AMD GPU 指标。优先级：pyamdgpuinfo → rocm-smi → 演示数据。"""
    global _GPU_CACHE
    now = time.time()
    if now - _GPU_CACHE["ts"] < 1.5:
        return _GPU_CACHE["data"]
    data = {"available": False, "source": "", "gpus": []}
    # 1) pyamdgpuinfo
    try:
        import pyamdgpuinfo
        n = pyamdgpuinfo.get_gpu_count()
        if n:
            gpus = []
            for i in range(n):
                g = pyamdgpuinfo.get_gpu(i)
                vr = g.memory_info
                gpus.append({
                    "id": i, "name": g.name,
                    "utilization": g.utilization,          # %
                    "vram_total_mb": round(vr["vram_total"] / (1024 ** 2), 0),
                    "vram_used_mb": round(vr["vram_used"] / (1024 ** 2), 0),
                    "temperature": g.temperature,
                    "power_w": g.average_power,
                    "core_clock": g.core_clock,
                })
            data = {"available": True, "source": "pyamdgpuinfo", "gpus": gpus}
    except Exception:
        pass
    # 2) rocm-smi
    if not data["available"]:
        try:
            import subprocess
            out = subprocess.run(["rocm-smi", "--json", "--showuse", "--showmemuse",
                                  "--showtemp", "--showpower", "--showclock"],
                                 capture_output=True, text=True, timeout=8)
            if out.returncode == 0 and out.stdout.strip():
                raw = json.loads(out.stdout)
                gpus = []
                for k, v in raw.items():
                    if k.startswith("card"):
                        u = v.get("GPU use (%)")
                        m = v.get("GPU memory use (%)")
                        t = v.get("Temperature (Sensor edge) (C)")
                        p = v.get("Current Socket Power (W)")
                        clk = v.get("GPU Clock (MHz)")
                        name = v.get("Card series", k)
                        vram_mb = v.get("VRAM Total Memory (B)")
                        if isinstance(vram_mb, str) and vram_mb.isdigit():
                            vram_mb = round(int(vram_mb) / (1024 ** 2), 0)
                        gpus.append({
                            "id": k, "name": name,
                            "utilization": float(u) if str(u).replace(".", "", 1).isdigit() else 0,
                            "vram_util_pct": float(m) if str(m).replace(".", "", 1).isdigit() else 0,
                            "temperature": float(t) if str(t).replace(".", "", 1).isdigit() else 0,
                            "power_w": float(p) if str(p).replace(".", "", 1).isdigit() else 0,
                            "core_clock": float(clk) if str(clk).replace(".", "", 1).isdigit() else 0,
                            "vram_total_mb": vram_mb or 0,
                        })
                if gpus:
                    data = {"available": True, "source": "rocm-smi", "gpus": gpus}
        except Exception:
            pass
    # 3) 演示数据（本地无 AMD GPU 时，让界面保持"活"的）
    if not data["available"] and DEMO_GPU:
        # 带随机游走的模拟数据，随 time 变化
        seed = int(now * 10)
        import random
        r = random.Random(seed)
        data = {
            "available": False, "source": "demo",
            "demo": True,
            "gpus": [{
                "id": 0, "name": "AMD Radeon RX 7900 XTX (演示)",
                "utilization": 40 + 40 * r.random(),
                "vram_total_mb": 24576,
                "vram_used_mb": 8192 + 6000 * r.random(),
                "temperature": 55 + 20 * r.random(),
                "power_w": 120 + 180 * r.random(),
                "core_clock": 1800 + 600 * r.random(),
                "vram_util_pct": (8192 + 6000 * r.random()) / 24576 * 100,
            }],
        }
    _GPU_CACHE = {"ts": now, "data": data}
    return data


@app.get("/api/gpu")
def api_gpu():
    return _read_gpu_metrics()


@app.get("/api/health")
def api_health():
    llm, rag, _ = _get_shared()
    try:
        chunk_n = rag.chunk_count()
        doc_n = rag.doc_count()
    except Exception:
        chunk_n = doc_n = 0
    gpu = _read_gpu_metrics()
    return {
        "ok": True,
        "model": {
            "backend": CFG["model"].get("backend"),
            "name": CFG["model"].get("name"),
            "base_url": CFG["model"].get("base_url"),
        },
        "embedding": CFG.get("embedding", {}).get("name"),
        "rag": {
            "hybrid": CFG.get("rag", {}).get("hybrid", True),
            "rerank": CFG.get("rag", {}).get("rerank", True),
            "docs": doc_n, "chunks": chunk_n,
            "docs_dir": DOCS_DIR,
        },
        "gpu": {"available": gpu["available"], "source": gpu["source"]},
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def launch(agent=None):
    """兼容入口：python main.py ui"""
    import uvicorn
    _get_shared()
    if agent is not None:
        # 允许外部注入 agent（当前自管实例，忽略注入）
        pass
    print(f"\n  Private RAG Agent UI: http://{HOST}:{PORT}\n")
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    launch()
