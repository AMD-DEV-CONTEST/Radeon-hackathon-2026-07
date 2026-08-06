"""请求模型"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ToolCall:
    """工具调用"""
    name: str
    parameters: Dict[str, Any]


@dataclass
class ExecuteRequest:
    """执行任务请求"""
    prompt: str
    tools: Optional[List[str]] = None
    stream: bool = False
    context_id: Optional[str] = None


@dataclass
class ChatRequest:
    """对话请求"""
    messages: List[Dict[str, str]]
    model: str = "motus-atom"
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    tools: Optional[List[str]] = None
    stream: bool = False