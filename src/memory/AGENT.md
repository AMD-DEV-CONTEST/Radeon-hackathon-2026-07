# Memory Module

**Module purpose**: Manages conversation history, token-aware context window building, and optional knowledge extraction using SQLite backends. 

**SQLite schema**:
- `sessions`: `id` (TEXT PK), `created_at` (REAL), `updated_at` (REAL), `title` (TEXT), `metadata` (TEXT JSON).
- `messages`: `id` (TEXT PK), `session_id` (TEXT FK), `role` (TEXT), `content` (TEXT), `timestamp` (REAL), `metadata` (TEXT JSON).
- `entities`: `id` (TEXT PK), `name` (TEXT UNIQUE), `type` (TEXT), `description` (TEXT).
- `relationships`: `id` (TEXT PK), `entity1_id` (TEXT FK), `entity2_id` (TEXT FK), `relation_type` (TEXT).

**Token counting heuristic**: Uses `chars_per_token=4.0` to estimate context size without a full tokenizer.

**Critical invariants**:
- Always update `updated_at` on the parent session when adding a new message.
- Use `uuid.uuid4().hex` for generating all IDs (sessions, messages, entities, relationships).

**How to add a new message type**:
Pass the new role string (e.g., `user`, `assistant`, `system`, `tool`) to `add_message(..., role=...)`. The system is agnostic to the role string, but consumers should expect these standard roles.

**Where this wires into**:
- `SessionStore` -> `ContextManager` -> `react_loop` -> `main.py`. The loop fetches history, builds bounded context, and stores new messages.
