from fastapi import FastAPI, WebSocket, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pathlib import Path
import uuid
import os
import json
import shutil

import re

app = FastAPI(title="Motus Agent API", version="0.1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_KB_DIR = Path(os.getenv("KNOWLEDGE_BASE_DIR", "data/knowledge_base"))
_META_FILE = _KB_DIR / "file_meta.json"


def _auto_upload_to_file_bar(file_path: str, folder_id: str = "") -> dict:
    """Auto-upload a local file to the file bar's last folder slot.
    
    Skips duplicate uploads of the same file path (deduplication).
    """
    src = Path(file_path)
    if not src.exists():
        return {"error": "file not found"}

    # Deduplication: check if this exact file path was already uploaded
    abs_path = str(src.resolve())
    meta = _load_meta()
    for fid, info in meta.items():
        existing = info.get("original_path", "")
        if existing == abs_path:
            # Already uploaded, return the existing file_id
            return {"file_id": fid, "name": info.get("name", src.name),
                    "folder_id": info.get("folder_id", folder_id),
                    "duplicate": True}

    file_id = str(uuid.uuid4())
    _KB_DIR.mkdir(parents=True, exist_ok=True)
    dest = _KB_DIR / f"{file_id}_{src.name}"
    shutil.copy2(str(src), str(dest))

    if not folder_id:
        folder_id = f"slot_{CFG_SLOT_COUNT - 1}"

    meta = _load_meta()
    meta[file_id] = {
        "name": src.name,
        "folder_id": folder_id,
        "original_path": abs_path,  # Store original path for dedup
    }
    _save_meta(meta)

    pipeline = getattr(app.state, "pipeline", None)
    if pipeline:
        pipeline.add_file(str(dest), file_id)

    return {"file_id": file_id, "name": src.name, "folder_id": folder_id}


def _detect_and_search(message: str) -> list:
    """Agent: detect if user is asking to find files, extract keywords, auto-search.

    Triggers on patterns like:
      - "帮我找桌面上的 Python 教程"
      - "搜索文档中的报告"
      - "找一下桌面上的 pdf"
      - "查找 Python 代码"

    Returns list of auto-uploaded file info dicts, or empty list.
    """
    print(f"[AUTO-SEARCH] Analyzing message: '{message[:100]}'")
    
    # Search intent patterns (Chinese + English)
    # NOTE: Longer alternatives must come FIRST to avoid partial matches!
    search_patterns = [
        r'(帮我|请|麻烦)?\s*(找一下|搜一下|查一下|搜索|查找|寻找|找)\s*(桌面上的|电脑里的|桌面|电脑|本机|本地|文件)?\s*(的)?\s*(.+)',
        r'(find|search|look\s+for)\s+(.+)\s+(on\s+desktop|in\s+documents|on\s+my\s+computer)',
    ]

    keyword = None
    matched = False
    for i, pattern in enumerate(search_patterns):
        m = re.search(pattern, message, re.IGNORECASE)
        if m:
            matched = True
            # The last capture group is the search subject
            keyword = m.groups()[-1].strip()
            print(f"[AUTO-SEARCH] Matched pattern_{i}, groups: {m.groups()}")
            # Cleanup: remove location/range prefixes and trailing suffixes
            cleaned = keyword
            # Remove "X中的Y" -> "Y" pattern (e.g., "文档中的报告" -> "报告")
            m2 = re.match(r'(?:文档|文件|资料|报告|代码|桌面|电脑|本机|本地|资料)中的(.+)', cleaned)
            if m2:
                cleaned = m2.group(1).strip()
            # Remove "X里的Y" -> "Y" pattern
            m3 = re.match(r'(?:桌面|电脑|本机|本地)里的(.+)', cleaned)
            if m3:
                cleaned = m3.group(1).strip()
            # Remove trailing suffixes
            cleaned = re.sub(r'(的文件|的资料|的文档|文件|资料|文档)$', '', cleaned).strip()
            # Remove leading "的" or "上"
            cleaned = re.sub(r'^(的|上)\s*', '', cleaned).strip()
            # If cleanup produced empty string, use the raw keyword
            if cleaned:
                keyword = cleaned
            break

    if not matched:
        print(f"[AUTO-SEARCH] No search intent detected")
        return []

    if not keyword or len(keyword) < 1:
        print(f"[AUTO-SEARCH] Search intent matched but keyword is empty/too short")
        return []

    print(f"[AUTO-SEARCH] Detected search intent, keyword: '{keyword}'")

    # Perform global file search
    try:
        from src.mcp.local_rag import global_file_search, get_search_roots
        roots = get_search_roots()
        print(f"[AUTO-SEARCH] Searching in roots: {roots}")
        search_results = global_file_search(keyword)
        print(f"[AUTO-SEARCH] Found {len(search_results)} files for '{keyword}'")
    except Exception as e:
        print(f"[AUTO-SEARCH] Search failed: {e}")
        import traceback
        traceback.print_exc()
        return []

    if not search_results:
        print(f"[AUTO-SEARCH] No files found for '{keyword}'")
        return []

    # Auto-upload top results to file bar (max 5)
    uploaded = []
    for match in search_results[:5]:
        path = match.path
        print(f"[AUTO-SEARCH] Processing result: {match.name} (score={match.score})")
        if os.path.exists(path):
            try:
                result = _auto_upload_to_file_bar(path)
                print(f"[AUTO-SEARCH] Upload result: {result}")
                if "file_id" in result and "error" not in result:
                    uploaded.append(result)
                    print(f"[AUTO-SEARCH] Successfully uploaded: {match.name} -> {result['file_id']}")
                else:
                    print(f"[AUTO-SEARCH] Skipped (error or no file_id): {result}")
            except Exception as e:
                print(f"[AUTO-SEARCH] Failed to upload {path}: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"[AUTO-SEARCH] File not found: {path}")

    print(f"[AUTO-SEARCH] Total uploaded: {len(uploaded)} files")
    return uploaded


CFG_SLOT_COUNT = 8


def _load_meta() -> dict:
    if _META_FILE.exists():
        return json.loads(_META_FILE.read_text(encoding="utf-8"))
    return {}


def _save_meta(meta: dict):
    _KB_DIR.mkdir(parents=True, exist_ok=True)
    _META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/health")
async def health_check():
    pipeline = getattr(app.state, "pipeline", None)
    kb_files = []
    if _META_FILE.exists():
        meta = _load_meta()
        for fid, info in meta.items():
            kb_files.append({
                "id": fid,
                "name": info.get("name", ""),
                "in_pipeline": fid in (pipeline._file_contents if pipeline else {}),
            })
    return {
        "status": "ok",
        "service": "motus-agent",
        "rag_pipeline_ready": pipeline is not None,
        "rag_file_count": len(kb_files),
        "rag_files_with_content": sum(1 for f in kb_files if f["in_pipeline"]),
        "rag_files_missing_content": [f["id"] for f in kb_files if not f["in_pipeline"]],
    }


@app.get("/api/test-search")
async def test_search(query: str = "Python"):
    """Quick test endpoint: verify auto-search is working."""
    from src.mcp.local_rag import global_file_search, get_search_roots
    import re as _re

    keyword = query.strip()
    if not keyword:
        return {"error": "query param required"}

    search_results = global_file_search(keyword)
    return {
        "keyword": keyword,
        "roots_scanned": get_search_roots(),
        "total_found": len(search_results),
        "results": [
            {"name": m.name, "path": m.path, "score": m.score}
            for m in search_results[:10]
        ],
    }


@app.get("/api/test-detect")
async def test_detect(message: str = "帮我找桌面上的Python教程"):
    """Quick test: verify search intent detection regex."""
    patterns = [
        r'(帮我|请|麻烦)?\s*(找一下|搜一下|查一下|搜索|查找|寻找|找)\s*(桌面上的|电脑里的|桌面|电脑|本机|本地|文件)?\s*(的)?\s*(.+)',
        r'(find|search|look\s+for)\s+(.+)\s+(on\s+desktop|in\s+documents|on\s+my\s+computer)',
    ]

    keyword = None
    matched_pattern = None
    for i, pattern in enumerate(patterns):
        m = re.search(pattern, message, re.IGNORECASE)
        if m:
            keyword = m.groups()[-1].strip()
            cleaned = re.sub(r'(的文件|的资料|的文档|文件|资料|文档)$', '', keyword).strip()
            cleaned = re.sub(r'^(的|上)\s*', '', cleaned).strip()
            if cleaned:
                keyword = cleaned
            matched_pattern = f"pattern_{i}"
            break

    return {
        "message": message,
        "detected": keyword is not None and len(keyword) >= 1,
        "keyword": keyword,
        "matched_pattern": matched_pattern,
        "length_ok": len(keyword) >= 1 if keyword else False,
    }


@app.get("/")
async def root():
    html_path = Path(__file__).resolve().parent.parent / "rag" / "rag_frontend.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    await ws.receive_text()


@app.post("/api/chat")
async def api_chat(payload: dict):
    message = payload.get("message", "")
    selected_files = payload.get("selected_files", [])
    enable_search = payload.get("enable_search", True)
    api_key = payload.get("api_key", "")
    model_url = payload.get("model_url", "")
    
    print(f"\n{'='*60}")
    print(f"[CHAT] Received request: message='{message[:80]}'")
    print(f"[CHAT] enable_search={enable_search}, selected_files={selected_files}")
    print(f"{'='*60}")

    if api_key:
        app.state.orchestrator.set_api_key(api_key)
    if model_url:
        app.state.orchestrator.set_model_url(model_url)

    # === Agent auto file search ===
    # Detect if the user is asking to find files, extract keywords and auto-search
    # Only auto-search when enabled (default: enabled)
    auto_search_results = []
    if enable_search:
        auto_search_results = _detect_and_search(message)
    else:
        print(f"[AUTO-SEARCH] Skipped (disabled by user)")
    if auto_search_results:
        print(f"[AUTO-SEARCH] Found {len(auto_search_results)} files, added to file bar")
        # Add newly found files to selected_files so they get used in RAG
        for f in auto_search_results:
            if f.get("file_id"):
                selected_files.append(f["file_id"])

    contexts = []
    pipeline = app.state.pipeline
    print(f"[DEBUG] pipeline exists: {pipeline is not None}")
    print(f"[DEBUG] selected_files: {selected_files}")
    
    if pipeline:
        # Auto-recovery: if _file_contents is empty but meta has files, reload
        if not pipeline._file_contents and _META_FILE.exists():
            meta = _load_meta()
            if meta:
                print(f"[DEBUG] _file_contents empty but {len(meta)} files in meta, auto-reloading...")
                pipeline._reload_from_disk()
                print(f"[DEBUG] after reload: {len(pipeline._file_contents)} files loaded")
        
        print(f"[DEBUG] _file_contents keys: {list(pipeline._file_contents.keys())}")
        for fid in pipeline._file_contents:
            content_len = len(pipeline._file_contents.get(fid, ""))
            print(f"[DEBUG]   file {fid}: {content_len} chars")
        
        if selected_files:
            # Check if any selected file is missing from _file_contents
            missing = [fid for fid in selected_files if fid not in pipeline._file_contents]
            if missing:
                print(f"[DEBUG] missing files in pipeline: {missing}")
                # Try to recover missing files from disk
                for fid in missing:
                    meta = _load_meta()
                    if fid in meta:
                        info = meta[fid]
                        file_path = _KB_DIR / f"{fid}_{info.get('name', '')}"
                        if file_path.exists():
                            result = pipeline.add_file(str(file_path), fid)
                            print(f"[DEBUG] recovered file {fid}: {result}")
            
            rag_result = pipeline.query(message, file_ids=selected_files)
        else:
            rag_result = {"contexts": [], "sources": []}
        contexts = rag_result.get("contexts", [])
        valid_contexts = [c for c in contexts if c and c.strip() and len(c.strip()) >= 5]
        print(f"[DEBUG] contexts total: {len(contexts)}, valid: {len(valid_contexts)}, "
              f"lengths: {[len(c) for c in valid_contexts]}")
        contexts = valid_contexts
    
    rag_instruction = ""
    if contexts:
        parts = []
        total_len = 0
        max_context = 8000
        for idx, c in enumerate(contexts):
            remaining = max_context - total_len
            if remaining <= 0:
                break
            truncated = c[:remaining]
            total_len += len(truncated)
            parts.append(f"[File {idx+1}] (file content, {len(truncated)} chars):\n{truncated}")
        rag_instruction = (
            "You are a helpful assistant. The user has uploaded files. "
            "IMPORTANT: Read and use the file contents below to answer the user's question. "
            "If the file contents are relevant, reference them in your answer. "
            "If the file contents do not help, say so.\n\n"
            "=== FILE CONTENTS ===\n" + "\n\n".join(parts) + "\n=== END FILE CONTENTS ==="
        )
    
    if rag_instruction:
        final_message = f"{rag_instruction}\n\nUser Question: {message}"
        context_messages = []
    else:
        final_message = message
        context_messages = []
    
    print(f"[DEBUG] final message length: {len(final_message)}, has rag: {bool(rag_instruction)}")
    
    result = {"result": "", "contexts": contexts}
    try:
        agent_result = await app.state.orchestrator.execute(final_message, context=context_messages or None)
        result["result"] = agent_result.get("result", "")
    except Exception as e:
        msg = str(e).lower()
        if "401" in msg or "unauthorized" in msg or "403" in msg:
            result["result"] = "API Key 无效或未授权，请在前端检查密钥设置。"
        elif "404" in msg or "not found" in msg:
            result["result"] = "模型不存在或不可用，请检查模型名称和端点地址。"
        elif "400" in msg or "bad request" in msg:
            result["result"] = "请求格式错误: " + str(e)[:200]
        elif "connection" in msg or "refused" in msg or "name or service not known" in msg:
            result["result"] = "无法连接到模型服务，请检查网络或模型端点配置。"
        elif contexts:
            result["result"] = f"已接收 {len(contexts)} 个文件内容，但模型服务暂不可用。"
        else:
            result["result"] = "模型服务暂不可用。"
    
    response_data = {"response": result["result"], "contexts": contexts}
    if auto_search_results:
        response_data["auto_search_files"] = [
            {"file_id": f.get("file_id"), "name": f.get("name"), "folder_id": f.get("folder_id")}
            for f in auto_search_results
        ]
        print(f"[AUTO-SEARCH] Returning {len(auto_search_results)} files to frontend: "
              f"{[f.get('name') for f in auto_search_results]}")
    else:
        print(f"[AUTO-SEARCH] No auto-search results to return")
    return response_data


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...), folder_id: str = Form(...)):
    file_id = str(uuid.uuid4())
    _KB_DIR.mkdir(parents=True, exist_ok=True)
    dest = _KB_DIR / f"{file_id}_{file.filename}"
    content = await file.read()
    dest.write_bytes(content)
    
    meta = _load_meta()
    meta[file_id] = {"name": file.filename, "folder_id": folder_id}
    _save_meta(meta)
    
    pipeline = app.state.pipeline
    parse_result = {"ok": True}
    if pipeline:
        parse_result = pipeline.add_file(str(dest), file_id)
    
    if not parse_result.get("ok", True):
        reason = parse_result.get("reason", "unknown")
        error_messages = {
            "no_extractable_text": "无法提取文本内容（可能是图片、音频、压缩包等二进制文件）",
            "insufficient_text": "文件文本内容过少，无法有效分析",
        }
        error_msg = error_messages.get(reason, "文件解析失败")
        meta = _load_meta()
        if file_id in meta:
            info = meta.pop(file_id)
            for f in _KB_DIR.iterdir():
                if f.name.startswith(file_id):
                    f.unlink()
                    break
            _save_meta(meta)
        return {
            "error": error_msg,
            "file_id": None,
            "name": file.filename,
            "folder_id": folder_id,
        }
    
    return {
        "file_id": file_id,
        "name": file.filename,
        "folder_id": folder_id,
        "chars": parse_result.get("chars", 0),
    }


@app.get("/api/files")
async def api_files():
    meta = _load_meta()
    files = [
        {"id": fid, "name": info["name"], "folder_id": info.get("folder_id", "")}
        for fid, info in meta.items()
        if (_KB_DIR / f"{fid}_{info['name']}").exists()
    ]
    return {"files": files}


@app.post("/api/folders")
async def api_folders(payload: dict):
    return {"id": str(uuid.uuid4()), "name": payload.get("name", "")}


@app.delete("/api/files/{file_id}")
async def api_delete_file(file_id: str):
    meta = _load_meta()
    if file_id in meta:
        info = meta.pop(file_id)
        name = info.get("name", "")
        for f in _KB_DIR.iterdir():
            if f.name.startswith(file_id):
                f.unlink()
                break
        _save_meta(meta)
    pipeline = app.state.pipeline
    if pipeline and hasattr(pipeline, '_file_contents'):
        pipeline._file_contents.pop(file_id, None)
    return {"status": "deleted"}


@app.post("/api/mcp/search")
async def api_mcp_search(payload: dict):
    """MCP local RAG search: hybrid search file bar + global filesystem.
    
    Supports auto-uploading found files to the file bar for RAG use.
    """
    from src.mcp.local_rag import local_rag_search

    query = payload.get("query", "")
    auto_upload = payload.get("auto_upload", True)
    max_files = payload.get("max_files", 5)
    
    if not query:
        return {"error": "query is required"}

    pipeline = getattr(app.state, "pipeline", None)
    result = await local_rag_search(query, pipeline)

    auto_uploaded = []
    if auto_upload:
        # Auto-upload global matches to file bar (limit to max_files)
        uploaded_count = 0
        for match in result.get("global_matches", []):
            if uploaded_count >= max_files:
                break
            path = match.get("path", "")
            if path and os.path.exists(path):
                try:
                    uploaded = _auto_upload_to_file_bar(path)
                    if "file_id" in uploaded and "error" not in uploaded:
                        auto_uploaded.append(uploaded)
                        uploaded_count += 1
                except Exception as e:
                    print(f"[WARN] Failed to auto-upload {path}: {e}")

    return {
        "query": query,
        "file_bar_matches": result.get("file_bar_matches", []),
        "global_matches": result.get("global_matches", []),
        "auto_uploaded": auto_uploaded,
        "total": result.get("total", 0),
        "search_roots": result.get("search_roots", []),
    }


@app.post("/api/search")
async def api_search_files(payload: dict):
    """Quick file search endpoint with auto-upload to file bar.
    
    Usage: POST /api/search {"keyword": "Python教程"}
    Returns matching files and auto-uploads them to the file bar.
    """
    from src.mcp.local_rag import global_file_search, get_search_roots

    keyword = payload.get("keyword", "")
    max_files = payload.get("max_files", 5)
    auto_upload = payload.get("auto_upload", True)

    if not keyword:
        return {"error": "keyword is required"}

    # Perform global file search
    search_results = global_file_search(keyword)

    # Convert to dicts
    matches = [
        {
            "path": m.path,
            "name": m.name,
            "score": m.score,
            "snippet": m.snippet,
        }
        for m in search_results
    ]

    # Auto-upload to file bar
    auto_uploaded = []
    if auto_upload:
        uploaded_count = 0
        for match in matches:
            if uploaded_count >= max_files:
                break
            path = match.get("path", "")
            if path and os.path.exists(path):
                try:
                    uploaded = _auto_upload_to_file_bar(path)
                    if "file_id" in uploaded and "error" not in uploaded:
                        auto_uploaded.append(uploaded)
                        uploaded_count += 1
                except Exception as e:
                    print(f"[WARN] Failed to upload {path}: {e}")

    return {
        "keyword": keyword,
        "matches": matches[:20],  # Return top 20 matches
        "auto_uploaded": auto_uploaded,
        "total_found": len(matches),
        "search_roots": get_search_roots(),
        "message": f"Found {len(matches)} files, auto-uploaded {len(auto_uploaded)} to file bar" if auto_upload else f"Found {len(matches)} files",
    }


@app.post("/api/reset")
async def api_reset():
    """Force reset RAG pipeline - clears all cached file contents and reloads from disk"""
    from src.rag.pipeline import get_rag_pipeline
    config = getattr(app.state, "config", None)
    original_env = getattr(app.state, "original_env", None)
    app.state.pipeline = get_rag_pipeline(config, original_env, force_reset=True)
    meta = _load_meta()
    valid_count = len([fid for fid in meta if fid in app.state.pipeline._file_contents])
    total_count = len(meta)
    return {
        "status": "ok",
        "valid_files": valid_count,
        "total_files": total_count,
    }
