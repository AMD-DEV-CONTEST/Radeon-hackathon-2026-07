"""Tools package for the Bunker project."""

from .registry import ToolRegistry
from .file_tools import register_file_tools, file_read, file_write, file_list, file_search
from .email_tools import register_email_tools, email_draft, email_search
from .calendar_tools import register_calendar_tools, calendar_query, calendar_create_event
from .web_tools import register_web_tools, web_search

__all__ = [
    # Registry
    "ToolRegistry",
    # Registration helpers
    "register_file_tools",
    "register_email_tools",
    "register_calendar_tools",
    "register_web_tools",
    # Concrete tool functions (used by tests and the agent directly)
    "file_read",
    "file_write",
    "file_list",
    "file_search",
    "email_draft",
    "email_search",
    "calendar_query",
    "calendar_create_event",
    "web_search",
]
