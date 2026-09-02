"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES
import base64

# 上传文件存储目录
_UPLOAD_DIR = os.path.expanduser("~/.xai/uploads")

def _handle_file_ingest(h):
    """POST /api/file/ingest → 将文本文件内容存入临时目录，返回 @file: 引用。"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {name, content}"})
        return
    name = (data.get("name") or "uploaded_file").strip()
    content = data.get("content", "")
    if not content:
        h._json_response(400, {"error": "content 不能为空"})
        return
    try:
        # 安全文件名
        safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
        if not safe_name or safe_name.startswith("."):
            safe_name = "uploaded_file"
        stamp = time.strftime("%Y%m%d%H%M%S") + f"{int((time.time() % 1) * 1000):03d}"
        stored = f"{stamp}_{safe_name}"
        # 存入临时目录
        temp_dir = os.path.join(os.path.dirname(__file__), ".ingest_tmp")
        os.makedirs(temp_dir, exist_ok=True)
        abs_path = os.path.join(temp_dir, stored)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        ref = f"@file:{abs_path}"
        h._json_response(200, {"ok": True, "path": abs_path, "ref": ref, "name": name})
    except Exception as e:
        h._json_response(500, {"error": f"摄入失败: {e}"})

def _handle_file_read(h):
    """GET /api/file/read?path=... → 读取文件内容，限制路径在 ~/Desktop/mask 内。"""
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query)
    fp = (qs.get("path") or [None])[0]
    if not fp:
        h._json_response(400, {"error": "缺少 path 参数"})
        return
    # 安全限制：路径必须在 ~/Desktop/mask 目录下
    try:
        mask_root = Path(os.path.expanduser("~/Desktop/mask")).resolve()
        abs_path = Path(fp).resolve()
        if mask_root not in abs_path.parents and abs_path != mask_root:
            h._json_response(403, {"error": "路径越界：仅允许 ~/Desktop/mask 内的文件"})
            return
        if not abs_path.exists():
            h._json_response(404, {"error": "文件不存在"})
            return
        if not abs_path.is_file():
            h._json_response(400, {"error": "不是文件"})
            return
        # 限制文件大小：最大 2MB
        if abs_path.stat().st_size > 2 * 1024 * 1024:
            h._json_response(413, {"error": "文件过大（最大 2MB）"})
            return
        content = abs_path.read_text(encoding="utf-8", errors="replace")
        h._json_response(200, {"content": content, "path": str(abs_path)})
    except Exception as e:
        h._json_response(500, {"error": f"读取失败: {e}"})

def _handle_open(h):
    """在本机用默认应用打开文件（macOS open / Linux xdg-open / Windows start）。"""
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query)
    name = (qs.get("name") or [None])[0]
    p = h._resolve_workspace_file(name)
    if not p or not os.path.exists(p):
        h._json_response(404, {"ok": False, "error": "文件不存在或越界"})
        return
    try:
        sys_name = platform.system()
        if sys_name == "Darwin":
            subprocess.Popen(["open", p])
        elif sys_name == "Windows":
            subprocess.Popen(["cmd", "/c", "start", "", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception as e:
        h._json_response(500, {"ok": False, "error": f"打开失败: {e}"})
        return
    h._json_response(200, {"ok": True, "path": p})

def _handle_file_upload(h):
    """POST /api/file/upload → 接收 base64 编码文件，存到 ~/.xai/uploads/，返回 @file: 引用。
    支持内容：图片/音频/文本/任意二进制。
    请求格式：JSON { name, content_base64, mime_type, size }
    """
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {name, content_base64, mime_type}"})
        return
    name = (data.get("name") or "uploaded_file").strip()
    content_b64 = data.get("content_base64", "")
    mime_type = (data.get("mime_type") or "application/octet-stream").strip()
    size_hint = data.get("size", 0)
    if not content_b64:
        h._json_response(400, {"error": "content_base64 不能为空"})
        return
    # 大小限制：最大 50MB
    if size_hint > 50 * 1024 * 1024:
        h._json_response(413, {"error": "文件过大（最大 50MB）"})
        return
    try:
        raw = base64.b64decode(content_b64)
    except Exception:
        h._json_response(400, {"error": "base64 解码失��"})
        return
    if len(raw) > 50 * 1024 * 1024:
        h._json_response(413, {"error": "解码后文件过大（最大 50MB）"})
        return
    try:
        # 安全文件名（保留扩展名）
        safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in name).strip()
        if not safe_name or safe_name.startswith("."):
            safe_name = "uploaded_file"
        stamp = time.strftime("%Y%m%d%H%M%S") + f"{int((time.time() % 1) * 1000):03d}"
        stored = f"{stamp}_{safe_name}"
        os.makedirs(_UPLOAD_DIR, exist_ok=True)
        abs_path = os.path.join(_UPLOAD_DIR, stored)
        with open(abs_path, "wb") as f:
            f.write(raw)
        ref = f"@file:{abs_path}"
        # 如果是图片，生成带 mime 标记便于前端预览
        is_image = mime_type.startswith("image/")
        h._json_response(200, {
            "ok": True,
            "path": abs_path,
            "ref": ref,
            "name": name,
            "mime_type": mime_type,
            "size": len(raw),
            "is_image": is_image,
            "preview_url": f"/api/file/preview/{stored}" if is_image else None,
        })
    except Exception as e:
        h._json_response(500, {"error": f"上传失败: {e}"})


def _handle_file_preview(h):
    """GET /api/file/preview/<stored_filename> → 返回文件二进制内容（图片直接展示）。"""
    # 提取文件名（路径 /api/file/preview/<name>）
    prefix = "/api/file/preview/"
    if not h.path.startswith(prefix):
        h._json_response(400, {"error": "无效路径"})
        return
    fname = h.path[len(prefix):]
    # 安全：只允许 _UPLOAD_DIR 内的文件
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in fname)
    abs_path = os.path.join(_UPLOAD_DIR, safe_name)
    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        h._json_response(404, {"error": "文件不存在"})
        return
    if not abs_path.startswith(_UPLOAD_DIR):
        h._json_response(403, {"error": "路径越界"})
        return
    try:
        # 根据扩展名推断 MIME
        ext = os.path.splitext(abs_path)[1].lower()
        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
            ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
            ".mp4": "video/mp4", ".pdf": "application/pdf",
        }
        content_type = mime_map.get(ext, "application/octet-stream")
        with open(abs_path, "rb") as f:
            raw = f.read()
        h.send_response(200)
        h.send_header("Content-Type", content_type)
        h.send_header("Content-Length", str(len(raw)))
        h.send_header("Cache-Control", "public, max-age=31536000, immutable")
        h.end_headers()
        h.wfile.write(raw)
    except Exception as e:
        h._json_response(500, {"error": f"预览失败: {e}"})


def register(router) -> None:
    router.add("GET", "/api/open", _handle_open)
    router.add_prefix("GET", "/api/file/read", _handle_file_read)
    router.add("POST", "/api/file/ingest", _handle_file_ingest)
    router.add("POST", "/api/file/upload", _handle_file_upload)
    router.add_prefix("GET", "/api/file/preview", _handle_file_preview)
