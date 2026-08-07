import logging
from typing import Dict, Any, Callable, List
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ToolDefinition(BaseModel):
    name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    parameters: Dict[str, Any] = Field(..., description="参数定义")
    function: Callable = Field(..., description="工具函数")
    requires_approval: bool = Field(False, description="是否需要用户批准")


class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}

    def register_tool(self, tool_def: ToolDefinition):
        self.tools[tool_def.name] = tool_def
        logger.info(f"Registered tool: {tool_def.name}")

    def get_tool(self, name: str) -> ToolDefinition:
        if name not in self.tools:
            raise ValueError(f"Tool not found: {name}")
        return self.tools[name]

    def list_tools(self) -> List[Dict[str, Any]]:
        tool_list = []
        for name, tool in self.tools.items():
            tool_list.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "requires_approval": tool.requires_approval,
            })
        return tool_list

    def get_tool_descriptions(self) -> str:
        descriptions = []
        for name, tool in self.tools.items():
            param_str = ", ".join([f"{k}: {v['type']}" for k, v in tool.parameters.items()])
            descriptions.append(f"- {name}: {tool.description} (参数: {param_str})")
        return "\n".join(descriptions)

    def call_tool(self, name: str, **kwargs) -> Any:
        tool = self.get_tool(name)
        logger.info(f"Calling tool: {name} with args: {kwargs}")
        
        try:
            result = tool.function(**kwargs)
            logger.info(f"Tool {name} returned: {result}")
            return result
        except Exception as e:
            logger.error(f"Tool {name} failed: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_approved_tools(self) -> List[str]:
        return [name for name, tool in self.tools.items() if not tool.requires_approval]


registry = ToolRegistry()