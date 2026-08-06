"""Bunker's existing tools wrapped as :class:`dspy.Tool`.

Each tool wraps the same function that the MCP-style :class:`ToolRegistry`
registers, but the permission gate lives *inside* the tool body: when the
``dspy.ReAct`` agent calls a tool it invokes it directly (no registry in the
path), so the consent check must be part of the callable itself.

dspy.Tool reads the function's name, type hints, and docstring to instruct
the LM: https://dspy.ai/getting-started/react-and-tools/
"""

import functools
import json
import logging
from typing import Any, Dict, List

import dspy

from ..agent.permission_controller import PermissionController
from . import calendar_tools, email_tools, file_tools, web_tools

logger = logging.getLogger(__name__)


def _make_tool(
    func: Any,
    permission_controller: PermissionController,
    requires_permission: bool,
    name: str,
    desc: str,
    args: Dict[str, Dict[str, Any]],
    data_flow_monitor: Any = None,
    audit_logger: Any = None,
    **bound_kwargs: Any,
) -> dspy.Tool:
    """Wrap a tool function into a permission-gated :class:`dspy.Tool`.

    Args:
        func: The underlying tool function.
        permission_controller: The consent gate to call before dangerous tools.
        requires_permission: Whether the tool needs explicit consent.
        name: The tool name shown to the LM.
        desc: The tool description shown to the LM.
        args: JSON schema of the parameters the LM may pass.
        data_flow_monitor: Optional DataFlowMonitor; every tool execution
            records a local-only event (is_local=True) so the privacy dashboard
            stays at 100% localhost.
        audit_logger: Optional AuditLogger; every tool execution is written to
            the JSONL audit log.
        bound_kwargs: Keyword arguments baked in at build time (e.g. base_dir)
            that the LM must never control.
    """

    def _record_tool_event(
        params: Dict[str, Any], approved: bool, result_str: str
    ) -> None:
        if data_flow_monitor is not None:
            try:
                data_flow_monitor.record_event(
                    event_type="tool_call",
                    source="dspy_agent",
                    destination=f"local_tool:{name}",
                    bytes_count=len(result_str.encode("utf-8", errors="ignore")),
                    is_local=True,
                    metadata={"tool": name, "approved": approved},
                )
            except Exception as exc:
                logger.warning("Failed to record data flow event for %s: %s", name, exc)
        if audit_logger is not None:
            try:
                audit_logger.log_tool_call(
                    tool_name=name,
                    params=params,
                    result_summary=result_str[:200],
                    approved=approved,
                )
            except Exception as exc:
                logger.warning("Failed to audit tool call %s: %s", name, exc)

    @functools.wraps(func)
    def _gated(**kwargs: Any) -> str:
        params = {**bound_kwargs, **kwargs}
        approved = not requires_permission
        if requires_permission:
            approved = permission_controller.gate(action=name, params=params, reason="DSPy agent tool call")
            if not approved:
                result_str = json.dumps({"error": f"Permission denied by user for tool {name}."})
                _record_tool_event(params, approved, result_str)
                return result_str
        result = func(**params)
        if isinstance(result, str):
            result_str = result
        else:
            result_str = json.dumps(result, default=str)
        _record_tool_event(params, approved, result_str)
        return result_str

    return dspy.Tool(func=_gated, name=name, desc=desc, args=args)


def build_bunker_tools(
    permission_controller: PermissionController,
    base_dir: str = "./data/documents",
    data_flow_monitor: Any = None,
    audit_logger: Any = None,
) -> List[dspy.Tool]:
    """Build Bunker's tools as a list of :class:`dspy.Tool`.

    Safe tools (``file_read``, ``file_search``, ``file_list``,
    ``calendar_query``) run un-gated. Dangerous tools always call
    ``permission_controller.gate()`` before executing.

    Args:
        permission_controller: The controller gating dangerous tool calls.
        base_dir: The allowed base directory for file operations.
        data_flow_monitor: Optional DataFlowMonitor; every execution records a
            local-only event for the privacy dashboard.
        audit_logger: Optional AuditLogger; every execution is audit-logged.

    Returns:
        The ordered list of tools ready for ``dspy.ReAct``.
    """
    specs = [
        {
            "func": file_tools.file_read,
            "name": "file_read",
            "desc": "Read the contents of a file from the user's documents directory.",
            "args": {"path": {"type": "string", "description": "The relative path to the file"}},
            "requires_permission": False,
            "bound": {"base_dir": base_dir},
        },
        {
            "func": file_tools.file_write,
            "name": "file_write",
            "desc": "Write content to a file. Requires explicit user consent.",
            "args": {
                "path": {"type": "string", "description": "The relative path to the file"},
                "content": {"type": "string", "description": "The content to write"},
            },
            "requires_permission": True,
            "bound": {"base_dir": base_dir},
        },
        {
            "func": file_tools.file_search,
            "name": "file_search",
            "desc": "Search files by filename or content substring.",
            "args": {
                "query": {"type": "string", "description": "The search query"},
                "recursive": {"type": "boolean", "description": "Whether to search subdirectories"},
            },
            "requires_permission": False,
            "bound": {"base_dir": base_dir},
        },
        {
            "func": file_tools.file_list,
            "name": "file_list",
            "desc": "List files in a directory.",
            "args": {"directory": {"type": "string", "description": "The relative directory path to list"}},
            "requires_permission": False,
            "bound": {"base_dir": base_dir},
        },
        {
            "func": email_tools.email_draft,
            "name": "email_draft",
            "desc": "Create a draft email saved locally. Requires explicit user consent.",
            "args": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body content"},
                "cc": {"type": "string", "description": "CC recipients"},
            },
            "requires_permission": True,
            "bound": {},
        },
        {
            "func": email_tools.email_search,
            "name": "email_search",
            "desc": "Search the local mailbox for emails. Requires explicit user consent.",
            "args": {
                "query": {"type": "string", "description": "Search query"},
                "folder": {"type": "string", "description": "Folder to search in"},
            },
            "requires_permission": True,
            "bound": {},
        },
        {
            "func": calendar_tools.calendar_query,
            "name": "calendar_query",
            "desc": "Query the local calendar for events.",
            "args": {
                "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                "query": {"type": "string", "description": "Search query text"},
            },
            "requires_permission": False,
            "bound": {},
        },
        {
            "func": calendar_tools.calendar_create_event,
            "name": "calendar_create_event",
            "desc": "Add a new calendar event. Requires explicit user consent.",
            "args": {
                "title": {"type": "string", "description": "Event title"},
                "start": {"type": "string", "description": "Start datetime (ISO)"},
                "end": {"type": "string", "description": "End datetime (ISO)"},
                "description": {"type": "string", "description": "Event description"},
                "attendees": {"type": "array", "description": "List of attendee emails"},
            },
            "requires_permission": True,
            "bound": {},
        },
        {
            "func": web_tools.web_search,
            "name": "web_search",
            "desc": "Search the web. Requires explicit user consent.",
            "args": {
                "query": {"type": "string", "description": "The search query"},
                "num_results": {"type": "integer", "description": "Number of results to return"},
            },
            "requires_permission": True,
            "bound": {},
        },
    ]

    tools = []
    for spec in specs:
        tools.append(
            _make_tool(
                func=spec["func"],
                permission_controller=permission_controller,
                requires_permission=spec["requires_permission"],
                name=spec["name"],
                desc=spec["desc"],
                args=spec["args"],
                data_flow_monitor=data_flow_monitor,
                audit_logger=audit_logger,
                **spec["bound"],
            )
        )
    return tools
