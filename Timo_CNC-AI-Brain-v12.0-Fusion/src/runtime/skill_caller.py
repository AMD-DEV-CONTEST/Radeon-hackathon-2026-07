"""
Skill 执行注册表 — 将 YAML 中定义的 Skill 映射为真实 Python 可调用对象。
专家会议通过此注册表调用真实 Skill 获取硬数据。
"""
import json
from typing import Dict, Any, Callable, Optional
from pathlib import Path


class SkillCaller:
    """
    可调用 Skill 注册表。
    
    注册方式：
        caller = SkillCaller()
        caller.register("quote_calculate", quote_adapter.quote)
        caller.register("conflict_check", conflict_checker.check)
    
    调用方式：
        result = caller.call("quote_calculate", {"material": "6061", "quantity": 50})
    """

    def __init__(self):
        self._registry: Dict[str, Callable] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, fn: Callable, metadata: Optional[Dict] = None):
        """注册一个可调用的 Skill。"""
        self._registry[name] = fn
        self._metadata[name] = metadata or {}
        return self

    def call(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        调用已注册的 Skill。
        
        Args:
            name: Skill 名称（如 "quote_calculate"）
            params: 参数 dict
        
        Returns:
            {success: bool, result: dict, error: str|None, skill: str}
        """
        if name not in self._registry:
            return {"success": False, "error": f"Skill '{name}' 未注册", "skill": name}

        try:
            fn = self._registry[name]
            result = fn(params)
            return {
                "success": True,
                "result": result,
                "error": None,
                "skill": name,
                "metadata": self._metadata.get(name, {}),
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"{type(e).__name__}: {str(e)}",
                "skill": name,
            }

    def list_available(self) -> list:
        """列出所有已注册的 Skill 名称。"""
        return list(self._registry.keys())

    def get_info(self, name: str) -> Optional[Dict]:
        """获取 Skill 元信息。"""
        return self._metadata.get(name)
