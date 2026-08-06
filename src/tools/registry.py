import logging
import inspect
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import jsonschema  # optional but expected in prod
    _JSONSCHEMA_AVAILABLE = True
except ImportError:  # pragma: no cover
    _JSONSCHEMA_AVAILABLE = False
    logger.warning("jsonschema not installed — parameter validation disabled.")


def _normalize_schema(raw_params: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the Bunker flat parameter dict into a JSON Schema object.

    Input (per-tool shorthand):
        {
            "path":    {"type": "string",  "description": "...", "required": True},
            "content": {"type": "string",  "description": "...", "required": False},
        }

    Output (valid JSON Schema):
        {
            "type": "object",
            "properties": {
                "path":    {"type": "string",  "description": "..."},
                "content": {"type": "string",  "description": "..."},
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    A property is considered required when its dict does **not** contain
    ``"required": False``; i.e., omitting ``"required"`` defaults to required.

    Args:
        raw_params: Flat parameter dict as registered by tool authors.

    Returns:
        Full JSON Schema object dict.
    """
    if not isinstance(raw_params, dict) or raw_params.get("type") == "object":
        # Already a JSON Schema or empty — return as-is.
        return raw_params or {}

    properties: Dict[str, Any] = {}
    required: List[str] = []

    for param_name, spec in raw_params.items():
        if not isinstance(spec, dict):
            # Tolerate degenerate schemas (e.g. False passed by mistake).
            continue
        prop_entry = {k: v for k, v in spec.items() if k != "required"}
        properties[param_name] = prop_entry

        # Treat absence of "required" key as required=True.
        if spec.get("required", True) is not False:
            required.append(param_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


class ToolRegistry:
    """MCP-style tool registry with permission gating and schema validation."""

    def __init__(self, permission_controller: Any = None):
        """Initialize the ToolRegistry.

        Args:
            permission_controller: Optional controller for requesting tool
                execution permissions.
        """
        self._tools: Dict[str, Dict[str, Any]] = {}
        self.permission_controller = permission_controller

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        func: Callable,
        description: str,
        parameters: Dict[str, Any],
        requires_permission: bool = False,
    ) -> None:
        """Register a tool.

        Args:
            name: The tool name.
            func: The callable function.
            description: A description of what the tool does.
            parameters: Flat Bunker parameter dict **or** a full JSON Schema.
                See _normalize_schema() for the expected input format.
            requires_permission: Whether the tool needs explicit approval
                before execution.
        """
        # Tolerate callers that accidentally pass a boolean for parameters.
        if not isinstance(parameters, dict):
            logger.warning(
                "register('%s'): parameters should be a dict, got %s. Using {}.",
                name,
                type(parameters).__name__,
            )
            parameters = {}

        self._tools[name] = {
            "name": name,
            "func": func,
            "description": description,
            "parameters": parameters,
            "_schema": _normalize_schema(parameters),
            "requires_permission": requires_permission,
        }

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all registered tools (metadata only, no callable).

        Returns:
            A list of dicts with name, description, parameters, requires_permission.
        """
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
                "requires_permission": t["requires_permission"],
            }
            for t in self._tools.values()
        ]

    def get_tool(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a tool by name.

        Args:
            name: The tool name.

        Returns:
            The tool definition dictionary or None if not found.
        """
        return self._tools.get(name)

    def get_descriptions_text(self) -> str:
        """Format all tools as text for an LLM system prompt.

        Returns:
            Formatted string of tool descriptions.
        """
        lines = []
        for name, tool in self._tools.items():
            params = tool.get("parameters", {})
            param_str = ", ".join(str(k) for k in params.keys())
            lines.append(f"{name}({param_str}): {tool['description']}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(
        self,
        tool_name: str,
        params: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a registered tool with validation and permission gating.

        Validation happens **before** the permission check so that a bad call
        never even touches the approval flow.

        Args:
            tool_name: The name of the tool to execute.
            params: Parameters to pass to the tool.
            session_id: Active session ID (used for permission context).

        Returns:
            ``{"success": True,  "result": <value>, "tool": tool_name}``  on success.
            ``{"success": False, "error": <message>, "tool": tool_name}`` on failure.
            ``{"success": False, "error": <message>}``                    for unknown tool.
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return {"success": False, "error": f"Tool '{tool_name}' not found."}

        # --- JSON Schema validation ---
        validation_error = self._validate_params(tool_name, tool["_schema"], params)
        if validation_error:
            logger.warning(
                "Parameter validation failed for tool '%s': %s", tool_name, validation_error
            )
            return {
                "success": False,
                "error": f"Invalid parameters for {tool_name}: {validation_error}",
                "tool": tool_name,
            }
        # --- End validation ---

        if tool["requires_permission"] and self.permission_controller:
            approved = self.permission_controller.request_approval(
                tool_name, params, reason=session_id or ""
            )
            if not approved:
                return {
                    "success": False,
                    "error": "Permission denied by user.",
                    "tool": tool_name,
                }

        try:
            func = tool["func"]
            # Filter to only params the function actually accepts.
            sig = inspect.signature(func)
            valid_params = {k: v for k, v in params.items() if k in sig.parameters}
            result = func(**valid_params)
            return {"success": True, "result": result, "tool": tool_name}
        except Exception as exc:
            logger.error("Error executing tool %s: %s", tool_name, exc)
            return {"success": False, "error": str(exc), "tool": tool_name}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_params(
        tool_name: str, schema: Dict[str, Any], params: Dict[str, Any]
    ) -> Optional[str]:
        """Validate params against the normalised JSON Schema.

        Returns:
            None if valid, or an error message string if invalid.
        """
        if not schema:
            return None

        if not _JSONSCHEMA_AVAILABLE:
            # No library — skip validation gracefully.
            return None

        try:
            jsonschema.validate(instance=params, schema=schema)
            return None
        except jsonschema.ValidationError as exc:
            return exc.message
        except Exception as exc:
            # Never crash execution due to a validator bug.
            logger.warning("Unexpected validation error for %s: %s", tool_name, exc)
            return None
