import logging
from typing import Dict, Any
from .registry import ToolDefinition, registry

logger = logging.getLogger(__name__)


def code_interpreter(code: str) -> Dict[str, Any]:
    try:
        local_vars = {}
        exec(code, globals(), local_vars)
        
        result = {}
        for key, value in local_vars.items():
            if not key.startswith("_"):
                result[key] = str(value)
        
        if result:
            return {"success": True, "output": result}
        else:
            return {"success": True, "output": "代码执行完成，无返回值"}
    except SyntaxError as e:
        return {"success": False, "error": f"语法错误: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def format_code(code: str, language: str = "python") -> Dict[str, Any]:
    """格式化代码。当前仅支持 Python（black），其他语言返回明确提示。"""
    if language and language.lower() not in ("python", "py", ""):
        return {
            "success": False,
            "error": f"暂不支持 {language} 格式化，当前仅支持 Python（black）",
        }
    try:
        import black
        formatted_code = black.format_str(code, mode=black.Mode())
        return {"success": True, "formatted_code": formatted_code}
    except ImportError:
        return {"success": False, "error": "black 格式化工具未安装"}
    except Exception as e:
        return {"success": False, "error": str(e)}


registry.register_tool(ToolDefinition(
    name="code_interpreter",
    description="解释执行 Python 代码",
    parameters={
        "code": {"type": "string", "description": "要执行的 Python 代码"},
    },
    function=code_interpreter,
    requires_approval=True,
))

registry.register_tool(ToolDefinition(
    name="format_code",
    description="格式化代码",
    parameters={
        "code": {"type": "string", "description": "要格式化的代码"},
        "language": {"type": "string", "description": "代码语言"},
    },
    function=format_code,
    requires_approval=False,
))