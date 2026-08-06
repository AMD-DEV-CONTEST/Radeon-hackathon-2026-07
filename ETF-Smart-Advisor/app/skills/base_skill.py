# app/skills/base_skill.py
"""
基础技能类
"""

from typing import Dict, Any, Optional
from abc import ABC, abstractmethod


class BaseSkill(ABC):
    """技能基类"""
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.context = {}
    
    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        """执行技能"""
        pass
    
    def get_prompt(self) -> str:
        """获取技能提示词"""
        return self.description
    
    def set_context(self, key: str, value: Any):
        """设置上下文"""
        self.context[key] = value
    
    def get_context(self, key: str, default: Any = None) -> Any:
        """获取上下文"""
        return self.context.get(key, default)