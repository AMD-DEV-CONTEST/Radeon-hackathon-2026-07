# AgentFlow AI API Documentation

Base URL: `http://127.0.0.1:8000`

Interactive docs:
- Swagger UI: `/docs`
- ReDoc: `/redoc`

## Endpoints

### `GET /`
Basic service metadata.

### `GET /api/system/health`
Returns backend health, Ollama status, and detected models.

**Response fields**
- `ok`
- `ollama_running`
- `selected_model`
- `available_models`
- `database_ready`
- `chroma_ready`
- `message`

### `GET /api/system/info`
Returns CPU, memory, GPU, platform, and Ollama runtime details.

### `GET /api/system/benchmarks`
Returns benchmark totals plus recent workflow runs.

### `GET /api/conversations`
Returns conversation history cards for the sidebar.

### `GET /api/conversations/{conversation_id}`
Returns the full conversation including:
- raw messages
- plan
- timeline
- citations
- tools
- benchmark metadata

### `GET /api/documents`
Returns uploaded documents tracked in SQLite.

### `POST /api/documents/upload`
Uploads a local file and indexes it into ChromaDB.

**Supported formats**
- PDF
- TXT
- MD

**Form field**
- `file`

### `POST /api/chat`
Runs the full multi-agent workflow.

**Request body**
```json
{
  "conversation_id": "optional-existing-conversation-id",
  "message": "Plan a launch checklist using the uploaded PDF.",
  "document_ids": ["optional-document-id"],
  "model": "optional-installed-ollama-model"
}
```

**Response body includes**
- `conversation_id`
- `message_id`
- `model`
- `response`
- `planner`
- `citations`
- `tools`
- `timeline`
- `benchmark`
- `system_alert`
- `agent_status`

## Multi-Agent Response Contract

AgentFlow AI returns transparent orchestration metadata for every assistant reply:
- **planner**: generated goal, tasks, tools, risks, and success criteria
- **citations**: local RAG evidence from uploaded files
- **tools**: safe local tool runs and outputs
- **timeline**: Planner → Research → Memory → Tool → Reviewer execution trail
- **benchmark**: latency and workload summary
