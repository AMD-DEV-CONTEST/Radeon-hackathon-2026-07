import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    """Estimate token count for a string.

    Tries tiktoken (cl100k_base) first; falls back to len(text) // 4.

    Args:
        text: The text to estimate.

    Returns:
        Estimated token count (minimum 1 for non-empty text).
    """
    if not text:
        return 0
    try:
        import tiktoken  # optional dependency
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


class _AutoApproveAllController:
    """Minimal stand-in used when no permission_controller is supplied."""

    def request_approval(self, tool_name: str, params: dict, reason: str = "") -> bool:  # noqa: D401
        return True


class ReActAgent:
    """ReAct agent: Thought → Action → Observation → Final Answer.

    Result shape returned by run():
    {
        "status":     "success" | "failed",
        "response":   str,
        "thoughts":   list[str],
        "actions":    list[dict],
        "iterations": int,
        "tokens_used": int,
        "reason":     Optional[str],   # present only on "failed"
    }

    Parsed output shape from _parse_react_output():
    {
        "type":         "final_answer" | "action" | "unknown",
        "content":      str,           # for final_answer
        "thought":      str,           # for action
        "action":       str,           # for action
        "action_input": dict,          # for action
    }
    """

    # Class-level default; each instance gets its own instance attribute.
    _DEFAULT_MAX_ITERATIONS: int = 10
    _DEFAULT_MAX_TOKENS_PER_TURN: int = 4096
    _DEFAULT_MAX_TOTAL_TOKENS: int = 12000

    SYSTEM_PROMPT = (
        "You are Bunker, a private AI assistant running entirely on the user's local AMD Radeon GPU.\n"
        "All your inference, document processing, and memory stays on this machine — nothing leaves.\n"
        "\n"
        "You have access to these tools:\n"
        "{tool_descriptions}\n"
        "\n"
        "Use the ReAct format:\n"
        "Thought: [your reasoning]\n"
        "Action: [tool_name]\n"
        "Action Input: [JSON parameters]\n"
        "Observation: [tool result — filled in by system]\n"
        "...\n"
        "Final Answer: [your response to the user]\n"
        "\n"
        "Rules:\n"
        "- Always reason before acting\n"
        "- Never call a tool more than 3 times in one session\n"
        "- If a tool fails, try an alternative approach\n"
        "- Always end with Final Answer"
    )

    def __init__(
        self,
        model_manager: Any,
        tool_registry: Any,
        permission_controller: Any = None,
        audit_logger: Any = None,
        memory_manager: Any = None,
        max_iterations: Optional[int] = None,
        max_tokens_per_turn: Optional[int] = None,
        max_total_tokens: Optional[int] = None,
    ):
        """Initializes the ReActAgent.

        Args:
            model_manager: Evaluates prompts (must have a .generate(messages) method).
            tool_registry: Manages available tools.
            permission_controller: Handles permission checks. Defaults to an
                auto-approving stub when not provided.
            audit_logger: Logs tool executions (optional, duck-typed).
            memory_manager: Optional memory for context across sessions.
            max_iterations: Override the maximum number of ReAct loop iterations.
            max_tokens_per_turn: Max tokens allowed for a single LLM response.
            max_total_tokens: Max cumulative tokens per run() call.
        """
        self.model_manager = model_manager
        self.tool_registry = tool_registry
        self.permission_controller = permission_controller or _AutoApproveAllController()
        self.audit_logger = audit_logger
        self.memory_manager = memory_manager

        # Instance-level limits (allow test-time override via attribute assignment).
        self.max_iterations: int = (
            max_iterations
            if max_iterations is not None
            else self._DEFAULT_MAX_ITERATIONS
        )
        self.max_tokens_per_turn: int = (
            max_tokens_per_turn
            if max_tokens_per_turn is not None
            else self._DEFAULT_MAX_TOKENS_PER_TURN
        )
        self.max_total_tokens: int = (
            max_total_tokens
            if max_total_tokens is not None
            else self._DEFAULT_MAX_TOTAL_TOKENS
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(
        self,
        user_message: str,
        session_id: str = "",
        context: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """Execute the full ReAct loop for a single user turn.

        Args:
            user_message: The user's input.
            session_id: The current session ID (optional, used for audit logging).
            context: Previous conversation context as a list of {role, content} dicts.

        Returns:
            A result dict with keys: status, response, thoughts, actions,
            iterations, tokens_used, and optionally reason.
        """
        context = context or []
        system_prompt = self.SYSTEM_PROMPT.format(
            tool_descriptions=self._build_tool_descriptions()
        )

        messages: List[Dict] = (
            [{"role": "system", "content": system_prompt}]
            + context
            + [{"role": "user", "content": user_message}]
        )

        thoughts: List[str] = []
        actions: List[Dict] = []
        iterations = 0
        total_tokens = 0

        while iterations < self.max_iterations:
            iterations += 1
            logger.info("ReAct loop iteration %d", iterations)

            try:
                response_text = self.model_manager.generate(messages)

                # --- Token budget checks ---
                turn_tokens = _estimate_tokens(response_text)
                if turn_tokens > self.max_tokens_per_turn:
                    return {
                        "status": "failed",
                        "response": "Token budget exceeded for a single response.",
                        "thoughts": thoughts,
                        "actions": actions,
                        "iterations": iterations,
                        "tokens_used": total_tokens + turn_tokens,
                        "reason": (
                            f"Token budget: single response used {turn_tokens} tokens "
                            f"(limit {self.max_tokens_per_turn})."
                        ),
                    }
                total_tokens += turn_tokens
                if total_tokens > self.max_total_tokens:
                    return {
                        "status": "failed",
                        "response": "Total token budget for this turn exceeded.",
                        "thoughts": thoughts,
                        "actions": actions,
                        "iterations": iterations,
                        "tokens_used": total_tokens,
                        "reason": (
                            f"Token budget: cumulative usage {total_tokens} tokens "
                            f"exceeds limit {self.max_total_tokens}."
                        ),
                    }
                # --- End token budget checks ---

                parsed = self._parse_react_output(response_text)
                messages.append({"role": "assistant", "content": response_text})

                if parsed["type"] == "final_answer":
                    return {
                        "status": "success",
                        "response": parsed["content"],
                        "thoughts": thoughts,
                        "actions": actions,
                        "iterations": iterations,
                        "tokens_used": total_tokens,
                    }

                elif parsed["type"] == "action":
                    thoughts.append(parsed.get("thought", ""))
                    tool_name = parsed["action"]
                    action_input = parsed.get("action_input", {})
                    actions.append({"tool": tool_name, "input": action_input})

                    approved = self.permission_controller.request_approval(
                        tool_name, action_input, reason=parsed.get("thought", "")
                    )
                    if not approved:
                        observation = f"Error: Permission denied for tool {tool_name}."
                    else:
                        try:
                            observation = self.tool_registry.execute(
                                tool_name, action_input
                            )
                            self._audit(session_id, tool_name, action_input, "SUCCESS")
                        except Exception as exc:
                            observation = f"Error executing tool: {exc}"
                            self._audit(session_id, tool_name, action_input, f"FAILED: {exc}")

                    messages.append(
                        {"role": "user", "content": f"Observation: {observation}"}
                    )

                else:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Format Error: Please use Thought/Action/Action Input "
                                "or Final Answer format."
                            ),
                        }
                    )

            except Exception as exc:
                logger.error("Error in ReAct loop: %s", exc)
                return {
                    "status": "failed",
                    "response": f"I encountered an error during my reasoning process: {exc}",
                    "thoughts": thoughts,
                    "actions": actions,
                    "iterations": iterations,
                    "tokens_used": total_tokens,
                    "reason": str(exc),
                }

        # Reached max iterations without a final answer.
        return {
            "status": "failed",
            "response": "Max iterations reached without a final answer.",
            "thoughts": thoughts,
            "actions": actions,
            "iterations": iterations,
            "tokens_used": total_tokens,
            "reason": f"Max iterations reached ({self.max_iterations}).",
        }

    def stream_run(
        self,
        user_message: str,
        session_id: str = "",
        context: Optional[List[Dict]] = None,
    ):
        """Generator yielding intermediate ReAct steps for real-time UI updates.

        Args:
            user_message: The user's input.
            session_id: The current session ID.
            context: Previous conversation context.

        Yields:
            Dicts with keys: status ("reasoning", "observed", "done", "error").
        """
        context = context or []
        system_prompt = self.SYSTEM_PROMPT.format(
            tool_descriptions=self._build_tool_descriptions()
        )
        messages: List[Dict] = (
            [{"role": "system", "content": system_prompt}]
            + context
            + [{"role": "user", "content": user_message}]
        )

        iterations = 0

        while iterations < self.max_iterations:
            iterations += 1

            try:
                response_text = self.model_manager.generate(messages)
                parsed = self._parse_react_output(response_text)
                messages.append({"role": "assistant", "content": response_text})

                if parsed["type"] == "final_answer":
                    yield {"status": "done", "response": parsed["content"]}
                    return

                elif parsed["type"] == "action":
                    yield {
                        "status": "reasoning",
                        "thought": parsed.get("thought", ""),
                        "action": parsed["action"],
                    }

                    tool_name = parsed["action"]
                    action_input = parsed.get("action_input", {})

                    approved = self.permission_controller.request_approval(
                        tool_name, action_input, reason=parsed.get("thought", "")
                    )
                    if not approved:
                        observation = f"Error: Permission denied for tool {tool_name}."
                    else:
                        try:
                            observation = self.tool_registry.execute(
                                tool_name, action_input
                            )
                            self._audit(session_id, tool_name, action_input, "SUCCESS")
                        except Exception as exc:
                            observation = f"Error executing tool: {exc}"
                            self._audit(session_id, tool_name, action_input, f"FAILED: {exc}")

                    messages.append(
                        {"role": "user", "content": f"Observation: {observation}"}
                    )
                    yield {"status": "observed", "observation": observation}

                else:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Format Error: Please use Thought/Action/Action Input "
                                "or Final Answer format."
                            ),
                        }
                    )

            except Exception as exc:
                yield {"status": "error", "error": str(exc)}
                return

        yield {"status": "done", "response": "Max iterations reached."}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_react_output(self, text: str) -> Dict[str, Any]:
        """Parse model text into a structured ReAct component dict.

        Returns a dict with key ``type`` set to one of:
        - ``"final_answer"`` — contains ``"content"``
        - ``"action"``       — contains ``"thought"``, ``"action"``, ``"action_input"``
        - ``"unknown"``      — no recognized structure

        Args:
            text: Raw model output.

        Returns:
            Parsed component dictionary.
        """
        # Final Answer takes priority.
        final_match = re.search(r"Final Answer:\s*(.*)", text, re.DOTALL)
        if final_match:
            return {
                "type": "final_answer",
                "content": final_match.group(1).strip(),
            }

        thought_match = re.search(r"Thought:\s*(.*?)(?=Action:|$)", text, re.DOTALL)
        action_match = re.search(r"Action:\s*(.*?)(?=Action Input:|$)", text, re.DOTALL)
        input_match = re.search(r"Action Input:\s*(.*)", text, re.DOTALL)

        if action_match and input_match:
            thought = thought_match.group(1).strip() if thought_match else ""
            action = action_match.group(1).strip()
            raw_input = input_match.group(1).strip()

            try:
                json_match = re.search(r"\{.*\}", raw_input, re.DOTALL)
                action_input = (
                    json.loads(json_match.group(0))
                    if json_match
                    else json.loads(raw_input)
                )
            except json.JSONDecodeError:
                action_input = {"raw_input": raw_input}

            return {
                "type": "action",
                "thought": thought,
                "action": action,
                "action_input": action_input,
            }

        return {"type": "unknown"}

    def _build_tool_descriptions(self) -> str:
        """Format available tools as text for the LLM system prompt.

        Returns:
            Newline-separated tool descriptions.
        """
        try:
            tools = self.tool_registry.list_tools()
        except AttributeError:
            # Fallback for mocks that implement get_tools() instead.
            tools = self.tool_registry.get_tools()

        descriptions = []
        for tool in tools:
            descriptions.append(
                f"- {tool['name']}: {tool['description']}\n"
                f"  Parameters: {json.dumps(tool.get('parameters', {}))}"
            )
        return "\n".join(descriptions)

    def _audit(
        self, session_id: str, tool_name: str, params: dict, status: str
    ) -> None:
        """Fire-and-forget audit log entry. Tolerates missing/duck-typed loggers.

        Args:
            session_id: Active session ID.
            tool_name: Tool that was called.
            params: Parameters passed to the tool.
            status: "SUCCESS" or "FAILED: <reason>".
        """
        if self.audit_logger is None:
            return
        try:
            self.audit_logger.log_tool_call(
                tool_name=tool_name,
                params=params,
                result_summary=status,
                approved=True,
                session_id=session_id,
            )
        except Exception:
            # Fallback for mocks / alternative logger signatures.
            try:
                self.audit_logger.log(session_id, tool_name, params, status)
            except Exception:
                pass
