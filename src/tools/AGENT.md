# Tools Module

**Module purpose**: Provides an MCP-style tool registry with permission gating for local file operations, email, calendar, and web search capabilities.

**Permission levels**:
| Tool | Requires Permission? |
|------|----------------------|
| `file_read` | False (Auto-approved) |
| `file_search` | False (Auto-approved) |
| `file_list` | False (Auto-approved) |
| `calendar_query` | False (Auto-approved) |
| `file_write` | True |
| `email_draft` | True |
| `email_search` | True |
| `calendar_create_event` | True |
| `web_search` | True |

**Registry API**:
- `register()`: Adds a tool to the internal map.
- `list_tools()`: Returns metadata schemas for all tools.
- `execute()`: Runs the tool (if permission granted via the controller) and catches exceptions.

**How to add a new tool** (4-step recipe):
1. Create function in appropriate `_tools.py` file.
2. Add `register_*` call with `requires_permission=True/False` and a JSON-Schema for parameters.
3. Add test in `tests/test_tools.py`.
4. Update `react_loop.py` SYSTEM_PROMPT if tool name changed or its exact name needs to be highlighted.

**Security note**: 
File path sandboxing is enforced via `os.path.realpath` checking against a fixed `base_dir` before reading/writing files.

**Where this wires into**:
`ToolRegistry` -> initialized in `main.py` -> bound to `react_loop`.
