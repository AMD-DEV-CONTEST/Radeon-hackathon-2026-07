from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import inspect

import kubernetes_tools


app = FastAPI(
    title="DevDas Kubernetes Tool Server",
    version="1.0"
)


class ToolRequest(BaseModel):
    tool: str
    arguments: dict = {}


@app.get("/")
def health():
    return {
        "status": "running",
        "service": "DevDas Tool Server"
    }


@app.get("/tools")
def list_tools():
    """
    Returns all callable tool names automatically.
    """
    tools = []

    for name, obj in inspect.getmembers(kubernetes_tools):
        if inspect.isfunction(obj) and not name.startswith("_"):
            tools.append(name)

    return {
        "tools": sorted(tools)
    }


@app.post("/execute_tool")
def execute_tool(request: ToolRequest):

    tool_name = request.tool
    arguments = request.arguments

    # Tool exists?
    if not hasattr(kubernetes_tools, tool_name):
        raise HTTPException(
            status_code=404,
            detail=f"Tool '{tool_name}' not found."
        )

    func = getattr(kubernetes_tools, tool_name)

    if not callable(func):
        raise HTTPException(
            status_code=400,
            detail=f"'{tool_name}' is not callable."
        )

    try:
        result = func(**arguments)

        return {
            "success": True,
            "tool": tool_name,
            "result": result
        }

    except Exception as e:

        return {
            "success": False,
            "tool": tool_name,
            "error": str(e)
        }