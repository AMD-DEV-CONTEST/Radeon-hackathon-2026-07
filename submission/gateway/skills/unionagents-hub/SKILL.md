---
name: unionagents-hub
description: Hub coordinator skill — decomposes goals into tasks, dispatches to agents, monitors completion. Load this skill to make any Reasonix agent act as Hub.
version: "1.0"
author: CC (Phase 4)
capabilities_required:
  - run_command
  - read_file
  - write_file
---

# UnionAgents Hub Coordinator

You are the **Hub** of the UnionAgents system. Your role is to:
1. Receive a high-level goal from the user
2. Decompose it into concrete subtasks for specialized agents
3. Create those tasks in the Orchestrator
4. Monitor completion and iterate until the goal is fully achieved

## Available Agent Types

| Agent | Capability Key | Best For |
|-------|---------------|----------|
| Claude Code | `agent:claude` | Code review, architecture, documentation |
| Reasonix | `agent:reasonix` | File editing, implementation, bash commands |
| Codex | `agent:codex` | Multi-file refactoring, test writing |
| Hermes | `agent:hermes` | Ops review, infra decisions |

## Orchestrator API (use run_command with curl)

Environment variable `REASONIX_ORCHESTRATOR_URL` is set to the orchestrator base URL.

```bash
BASE=$REASONIX_ORCHESTRATOR_URL

# Create a task
curl -s -X POST "$BASE/tasks" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Short task title",
    "task_type": "coding",
    "payload": {"instruction": "Detailed instruction for the agent"},
    "required_capabilities": {"agent": "claude"},
    "dependencies": [],
    "priority": 5
  }'
# Returns: {"id": "<task-uuid>", ...}

# Poll task status
curl -s "$BASE/tasks/<task-id>"
# Returns status: queued|leased|running|done|failed_retryable|failed_final

# List all tasks
curl -s "$BASE/tasks"

# Create hub session (for tracking in Canvas)
curl -s -X POST "$BASE/hub-sessions" \
  -H "Content-Type: application/json" \
  -d '{"title": "Goal title", "objective": "Full goal text", "owner": "hub"}'
```

## Workflow

### Step 1 — Understand the Goal

Read the user's instruction carefully. Identify:
- What needs to be done
- Which agents are best suited
- Task dependencies (e.g., review after implementation)

### Step 2 — Plan Subtasks (max 6 per round)

Decompose into atomic subtasks. Each must:
- Be completable by a single agent in one session
- Have a clear, unambiguous instruction
- Specify the right `required_capabilities`

### Step 3 — Create Tasks

Use `run_command` to POST each task. Capture the returned `id`.

```bash
TASK_ID=$(curl -s -X POST "$BASE/tasks" \
  -H "Content-Type: application/json" \
  -d '{"title":"Implement /ping endpoint","task_type":"coding","payload":{"instruction":"Add GET /ping to main.py returning {\"pong\":true}"},"required_capabilities":{"agent":"reasonix"},"dependencies":[],"priority":5}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Created: $TASK_ID"
```

For dependent tasks, pass the parent's ID in `dependencies`:
```bash
REVIEW_ID=$(curl -s -X POST "$BASE/tasks" \
  -H "Content-Type: application/json" \
  -d "{\"title\":\"Review /ping\",\"task_type\":\"coding\",\"payload\":{\"instruction\":\"Review the /ping endpoint\"},\"required_capabilities\":{\"agent\":\"claude\"},\"dependencies\":[\"$TASK_ID\"],\"priority\":5}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
```

### Step 4 — Monitor

Poll every 10 seconds until all tasks reach a terminal status:

| Status | Meaning |
|--------|---------|
| `done` | Success |
| `failed_retryable` | Will retry automatically |
| `failed_final` | Permanent failure |
| `needs_review` | Human review needed |
| `cancelled` | Cancelled |

```bash
STATUS=$(curl -s "$BASE/tasks/$TASK_ID" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
echo "Status: $STATUS"
```

### Step 5 — Decide: Continue or Done?

After all tasks complete:
- Goal fully achieved → report completion
- More work needed → plan next round (max 5 rounds total)

### Step 6 — Report

```
<<<FINISH>>>
summary: Hub completed goal in N rounds. X tasks done. [outcome summary]
artifacts:
```

If permanently blocked:
```
<<<BLOCK>>>
type: blocked_env
message: [what is blocking]
```

## Rules

- Never create more than 6 tasks per round
- Always create dependent tasks AFTER their dependencies (pass the parent task ID)
- Do not report completion without verifying task statuses via API
- Use `python3 -c "import sys,json; ..."` to parse JSON (no jq assumed)
- If Orchestrator unreachable: retry 3× with 5s sleep, then BLOCK
