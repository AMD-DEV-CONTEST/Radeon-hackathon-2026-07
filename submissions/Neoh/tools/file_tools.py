import logging
import os
from typing import Dict, Any
from .registry import ToolDefinition, registry

logger = logging.getLogger(__name__)


def read_file(file_path: str) -> Dict[str, Any]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        return {
            "success": True,
            "content": content,
            "file_size": len(content),
        }
    except FileNotFoundError:
        return {"success": False, "error": f"文件不存在: {file_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def write_file(file_path: str, content: str, append: bool = False) -> Dict[str, Any]:
    try:
        mode = "a" if append else "w"
        with open(file_path, mode, encoding="utf-8") as f:
            f.write(content)
        
        return {"success": True, "message": f"文件 {'追加' if append else '写入'}成功: {file_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_file(file_path: str) -> Dict[str, Any]:
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return {"success": True, "message": f"文件删除成功: {file_path}"}
        else:
            return {"success": False, "error": f"文件不存在: {file_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_directory(path: str = ".") -> Dict[str, Any]:
    try:
        items = []
        for entry in os.listdir(path):
            entry_path = os.path.join(path, entry)
            is_dir = os.path.isdir(entry_path)
            items.append({
                "name": entry,
                "type": "directory" if is_dir else "file",
                "path": entry_path,
            })
        
        return {"success": True, "items": items, "path": path}
    except Exception as e:
        return {"success": False, "error": str(e)}


def create_directory(path: str) -> Dict[str, Any]:
    try:
        os.makedirs(path, exist_ok=True)
        return {"success": True, "message": f"目录创建成功: {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


registry.register_tool(ToolDefinition(
    name="read_file",
    description="读取文件内容",
    parameters={
        "file_path": {"type": "string", "description": "文件路径"},
    },
    function=read_file,
    requires_approval=False,
))

registry.register_tool(ToolDefinition(
    name="write_file",
    description="写入文件内容",
    parameters={
        "file_path": {"type": "string", "description": "文件路径"},
        "content": {"type": "string", "description": "要写入的内容"},
        "append": {"type": "boolean", "description": "是否追加模式"},
    },
    function=write_file,
    requires_approval=True,
))

registry.register_tool(ToolDefinition(
    name="delete_file",
    description="删除文件",
    parameters={
        "file_path": {"type": "string", "description": "文件路径"},
    },
    function=delete_file,
    requires_approval=True,
))

registry.register_tool(ToolDefinition(
    name="list_directory",
    description="列出目录内容",
    parameters={
        "path": {"type": "string", "description": "目录路径"},
    },
    function=list_directory,
    requires_approval=False,
))

registry.register_tool(ToolDefinition(
    name="create_directory",
    description="创建目录",
    parameters={
        "path": {"type": "string", "description": "目录路径"},
    },
    function=create_directory,
    requires_approval=False,
))