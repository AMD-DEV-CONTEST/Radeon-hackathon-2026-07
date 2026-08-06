"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_backup(h):
    """POST /api/system/backup → 导出 XAI 数据目录为 tar.gz 流（P3-O3）。"""
    xai_home = os.environ.get("XAI_HOME", os.path.expanduser("~/.xai"))
    if not os.path.isdir(xai_home):
        h._json_response(500, {"error": f"数据目录不存在: {xai_home}"})
        return

    # 创建临时 tar.gz
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".tar.gz", prefix="xai-backup-")
    os.close(tmp_fd)
    try:
        with tarfile.open(tmp_path, "w:gz") as tar:
            tar.add(xai_home, arcname=os.path.basename(xai_home))
    except Exception as e:
        os.unlink(tmp_path)
        h._json_response(500, {"error": f"打包失败: {e}"})
        return

    file_size = os.path.getsize(tmp_path)
    iso_date = time.strftime("%Y-%m-%dT%H%M%S")
    filename = f"xai-backup-{iso_date}.tar.gz"

    h.send_response(200)
    h.send_header("Content-Type", "application/gzip")
    h.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    h.send_header("Content-Length", str(file_size))
    h.send_header("Access-Control-Allow-Origin", "*")
    h.end_headers()

    with open(tmp_path, "rb") as f:
        shutil.copyfileobj(f, h.wfile)
    os.unlink(tmp_path)

def _handle_restore(h):
    """POST /api/system/restore → multipart 上传 tar.gz 恢复数据目录（P3-O3）。"""
    content_type = h.headers.get("Content-Type", "")
    length = int(h.headers.get("Content-Length", "0"))
    if length == 0:
        h._json_response(400, {"error": "请求体为空，请上传 .tar.gz 备份文件"})
        return

    body = h.rfile.read(length)
    fname, data = h._parse_multipart(content_type, body)
    if data is None or len(data) == 0:
        h._json_response(400, {"error": "未找到 file 字段，请以 multipart/form-data 上传 .tar.gz 文件"})
        return

    # 校验 gzip 魔术字节
    if data[:2] != b'\x1f\x8b':
        h._json_response(400, {"error": "文件不是有效的 gzip 格式（期望 .tar.gz）"})
        return

    xai_home = os.environ.get("XAI_HOME", os.path.expanduser("~/.xai"))
    tmp_dir = tempfile.mkdtemp(prefix="xai-restore-")
    try:
        # 解压到临时目录
        tar_path = os.path.join(tmp_dir, fname)
        with open(tar_path, "wb") as f:
            f.write(data)
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(tmp_dir)
        os.unlink(tar_path)

        # 找到解压后的 .xai 目录
        extracted_root = tmp_dir
        for entry in os.listdir(tmp_dir):
            candidate = os.path.join(tmp_dir, entry)
            if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, "app.db")):
                extracted_root = candidate
                break

        # 校验
        if not os.path.exists(os.path.join(extracted_root, "app.db")):
            h._json_response(400, {"error": "备份文件无效：缺少 app.db 核心数据文件"})
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

        # 统计文件数
        file_count = sum(len(files) for _, _, files in os.walk(extracted_root))

        # 覆盖写入 XAI_HOME
        if os.path.exists(xai_home):
            shutil.rmtree(xai_home)
        shutil.copytree(extracted_root, xai_home)

        h._json_response(200, {
            "ok": True,
            "restored_files": file_count,
            "message": "恢复完成，请重启服务生效",
        })
    except Exception as e:
        h._json_response(500, {"error": f"恢复失败: {e}"})
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

def register(router) -> None:
    router.add("POST", "/api/system/backup", _handle_backup)
    router.add("POST", "/api/system/restore", _handle_restore)
