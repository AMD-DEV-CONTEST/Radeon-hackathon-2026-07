# Agent Module Guidelines

**Module purpose**: This module contains the core decision-making logic of the Bunker agent, including task planning, permission gating, and the ReAct reasoning loop.

## Class/Method Table
| Class | Key Methods | Description |
|---|---|---|
| `ReActAgent` | `run()`, `stream_run()` | Core reasoning loop (Thought -> Action -> Observation -> Final Answer). |
| `TaskPlanner` | `plan()` | Decomposes requests into subtasks. |
| `PermissionController`| `request_approval()`, `requires_approval()` | Gates tool execution based on privacy configs. |

## ReAct Loop Flow
1. **Initialize Context**: Build system prompt with tool registry and add user context (`react_loop.py:run`).
2. **Generate Thought/Action**: Model proposes an action.
3. **Parse Output**: Extract tool name and JSON input (`react_loop.py:_parse_react_output`).
4. **Permission Check**: Ask `PermissionController` if the action is allowed.
5. **Execute Action**: If approved, run the tool.
6. **Audit Log**: Log the execution result.
7. **Append Observation**: Feed tool output back to the model.
8. **Repeat/Finalize**: Loop until `Final Answer` is generated.

## Critical Invariants
- `MAX_ITERATIONS` is strictly set to **10** to prevent infinite loops.
- **EVERY** tool call MUST be gated by `permission_controller.request_approval()`.
- **EVERY** executed tool call MUST be logged via `audit_logger.log()`.
- The `stream_run()` method MUST yield intermediate states (`reasoning`, `observed`, `done`) for real-time Gradio UI updates.

## How to add a new reasoning strategy
1. Create a new class (e.g., `PlanAndSolveAgent`) adhering to the same interface as `ReActAgent`.
2. Implement the `run()` and `stream_run()` methods, ensuring permission checks and audit logging are included.
3. Register the new strategy in `src/agent/__init__.py`.

## Permission Level Table
| Tool Type | Auto-Approved? | Notes |
|---|---|---|
| `file_read`, `file_search`, `file_list` | **Yes** | Read-only operations. |
| `file_write`, `email_draft` | **No** | Modifies state, requires user approval. |
| `email_search`, `web_search` | **No** | Potentially leaks context/data, requires user approval. |
