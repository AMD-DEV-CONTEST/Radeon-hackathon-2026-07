"""响应模型"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolResult:
    """工具执行结果"""
    name: str
    success: bool
    result: Any = None
    error: Optional[str] = None


@dataclass
class AgentResponse:
    """Agent 响应"""
    content: str
    tool_calls: List[ToolResult] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamChunk:
    """流式响应块"""
    content: str
    is_finished: bool = False
    tool_call: Optional[ToolResult] = None