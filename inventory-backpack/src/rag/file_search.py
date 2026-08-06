"""
文件搜索工具 - 扫描桌面、文档等常见目录，按关键词查找文件。
支持中文路径（桌面、文档）和英文路径（Desktop、Documents）。
"""

import os
import time
from pathlib import Path
from typing import List, Dict, Optional
import fnmatch


# Windows 下常见的用户目录映射
def _get_user_dirs() -> Dict[str, Path]:
    """获取 Windows 用户常见目录的实际路径"""
    home = Path.home()
    dirs = {
        "home": home,
        "desktop_cn": home / "桌面",
        "desktop_en": home / "Desktop",
        "documents_cn": home / "文档",
        "documents_en": home / "Documents",
        "downloads_cn": home / "下载",
        "downloads_en": home / "Downloads",
    }
    # 只返回存在的目录
    return {k: v for k, v in dirs.items() if v.exists()}


def _get_search_paths() -> List[Path]:
    """获取所有需要扫描的目录路径"""
    dirs = _get_user_dirs()
    paths = set()

    # 优先使用存在的桌面路径
    for key in ["desktop_cn", "desktop_en", "documents_cn", "documents_en"]:
        if key in dirs:
            paths.add(dirs[key])

    # 如果桌面不存在，回退到 home 目录（限制深度）
    if not any("desktop" in k for k in dirs.keys()):
        paths.add(Path.home())

    return sorted(paths)


def search_files(
    keyword: str,
    search_paths: Optional[List[str]] = None,
    file_types: Optional[List[str]] = None,
    max_depth: int = 5,
    max_results: int = 50,
    time_budget_ms: int = 3000,
) -> Dict:
    """
    在指定目录中搜索包含关键词的文件。

    Args:
        keyword: 搜索关键词（支持文件名模糊匹配）
        search_paths: 要搜索的目录路径列表（None 则扫描默认目录）
        file_types: 要搜索的文件扩展名列表（如 ['.py', '.pdf']）
        max_depth: 最大递归深度
        max_results: 最大返回结果数
        time_budget_ms: 搜索时间预算（毫秒）

    Returns:
        {
            "success": bool,
            "results": [...],
            "errors": [...],
            "stats": {...}
        }
    """
    start_time = time.perf_counter()
    results = []
    errors = []
    scanned_dirs_count = 0
    denied_dirs_count = 0
    files_checked = 0

    # 确定搜索路径
    if search_paths:
        paths_to_search = [Path(p) for p in search_paths]
    else:
        paths_to_search = _get_search_paths()

    if not paths_to_search:
        return {
            "success": False,
            "results": [],
            "errors": [{"message": "No search directories found"}],
            "stats": {"scanned_dirs": 0, "files_found": 0},
        }

    for base_path in paths_to_search:
        if not base_path.exists():
            continue

        try:
            for root, dirs, files in os.walk(str(base_path)):
                # 时间预算检查
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                if elapsed_ms > time_budget_ms:
                    break

                # 深度限制
                root_path = Path(root)
                try:
                    rel_depth = len(root_path.relative_to(base_path).parts)
                except ValueError:
                    rel_depth = 0
                if rel_depth > max_depth:
                    dirs.clear()
                    continue

                # 跳过隐藏目录和系统目录
                dirs[:] = [
                    d for d in dirs
                    if not d.startswith('.') and d not in {
                        'node_modules', '__pycache__', '.git',
                        'Windows', 'System32', 'ProgramData',
                        'AppData', '$RECYCLE.BIN'
                    }
                ]

                scanned_dirs_count += 1

                # 搜索文件
                for filename in files:
                    files_checked += 1
                    if len(results) >= max_results:
                        break

                    # 检查文件扩展名过滤
                    if file_types:
                        ext = Path(filename).suffix.lower()
                        if ext not in [t.lower() for t in file_types]:
                            continue

                    # 关键词匹配（不区分大小写）
                    if keyword.lower() in filename.lower():
                        file_path = root_path / filename
                        try:
                            stat = file_path.stat()
                            results.append({
                                "name": filename,
                                "path": str(file_path),
                                "size": stat.st_size,
                                "modified": time.strftime("%Y-%m-%d %H:%M:%S",
                                                          time.localtime(stat.st_mtime)),
                                "extension": file_path.suffix.lower(),
                            })
                        except (OSError, PermissionError) as e:
                            denied_dirs_count += 1
                            errors.append({
                                "file": str(file_path),
                                "error": str(e),
                            })

                if len(results) >= max_results:
                    break

        except PermissionError as e:
            errors.append({
                "directory": str(base_path),
                "error": f"Permission denied: {e}",
            })
        except Exception as e:
            errors.append({
                "directory": str(base_path),
                "error": str(e),
            })

        if len(results) >= max_results:
            break

    # 按修改时间排序（最新的在前）
    results.sort(key=lambda x: x.get("modified", ""), reverse=True)

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    return {
        "success": len(results) > 0,
        "keyword": keyword,
        "results": results,
        "errors": errors[:10],  # 最多返回 10 个错误
        "stats": {
            "scanned_dirs": scanned_dirs_count,
            "files_checked": files_checked,
            "files_found": len(results),
            "denied_dirs": denied_dirs_count,
            "elapsed_ms": round(elapsed_ms, 1),
            "time_budget_exceeded": elapsed_ms > time_budget_ms,
        },
    }


def get_supported_extensions() -> List[str]:
    """获取常见的文档扩展名列表"""
    return [
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.txt', '.md', '.py', '.js', '.ts', '.java', '.cpp', '.c',
        '.html', '.css', '.json', '.xml', '.csv', '.zip', '.rar',
        '.7z', '.jpg', '.jpeg', '.png', '.gif', '.bmp',
    ]


def get_default_search_dirs() -> List[str]:
    """获取默认搜索目录"""
    paths = _get_search_paths()
    return [str(p) for p in paths]
