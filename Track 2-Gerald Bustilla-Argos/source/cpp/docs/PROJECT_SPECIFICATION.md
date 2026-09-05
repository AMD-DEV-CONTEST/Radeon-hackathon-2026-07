# Project Specification — Argos: Faithful AI Companion

## Track 2: Development & Local Deployment of Private AI Agents

---

## 1. Application Scenarios

### Target Users
- **Software developers** who want an AI companion that understands their project files and can execute tasks on their computer
- **Power users** who need a desktop assistant with screen awareness, proactive help, and tool invocation
- **Privacy-conscious users** who want local RAG and sensitive data filtering without sending personal data to external services

### Application Scenarios

| Scenario | Description |
|---|---|
| **Project-aware Q&A** | User asks "What does RefreshConversation do?" — Argos uses RAG to search local project files and answers with code context |
| **Screen-aware proactive help** | Argos sees the user is debugging in VS Code and proactively offers: "I see you're debugging. Want me to search for similar error patterns?" |
| **Tool execution** | User says "Open notepad and search my project for error handling" — Argos executes both tools in sequence |
| **Browser automation** | User says "Navigate to GitHub and find my repo" — Argos uses browser tools |
| **Privacy-safe screen context** | When Argos reads window titles, passwords and tokens are automatically redacted before being sent to the AI |

---

## 2. Agent Architecture

### High-Level Architecture

```
User Input → RAG Engine (TF-IDF) → Context Injection → AI (Radeon GPU) → Tool Loop → Response
                                         ↑                                    ↓
                                   Privacy Filter ← Screen Context ← Win32 API
```

### Components

1. **Main Controller** (`main.cpp`)
   - Win32 WndProc: message routing, timer management
   - Chatbox UI: Rich Edit with Messenger-style bubbles
   - Proactive system: periodic screen context gathering + AI messages
   - Robot renderer: Direct2D animated Spartan helmet

2. **Agent Client** (`agent_client.cpp`)
   - WinHTTP client with retry logic (3 attempts, 30s timeout)
   - RAG context injection: automatically searches local files before AI call
   - Tool loop: up to 5 iterations (AI calls tools → execute → send results back)
   - Multi-turn conversation history (20-message window)

3. **RAG Engine** (`argos_tools.cpp` + `tools/`)
   - TF-IDF vectorization with inverted index
   - Cosine similarity ranking
   - Stop word removal and tokenization
   - Directory indexing with file content extraction
   - Returns clean text snippets (not JSON) for AI context

4. **Tool Engine** (`argos_tools.cpp`)
   - 42+ tools across 5 categories: system, search, browser, screen, UI
   - Unified dispatch function
   - Tool result truncation for long outputs
   - Permission control for destructive operations

5. **Privacy Filter** (`main.cpp`)
   - Sensitive keyword redaction (passwords, tokens, secrets, credentials)
   - Credit card number pattern detection
   - Applied to all screen context before AI processing

6. **Screen Context** (`main.cpp` + `tools/screen_context.cpp`)
   - Active window title and process name
   - Top 10 visible windows
   - Privacy-filtered before use

7. **Visual Companion** (`robot_renderer.cpp`)
   - Direct2D rendering: golden Spartan helmet, red eyes, cape
   - Animated thinking indicator (eye movement)
   - Transparent overlay window (always on top)

### Data Flow

```
1. User types message in chatbox
2. AgentClient::Chat() is called
3. RAG engine indexes current directory (TF-IDF)
4. RAG engine searches for relevant content (cosine similarity)
5. Top 5 results injected as system context message
6. Full message list (system prompt + RAG context + history) sent to API
7. AI response received
8. If response contains [TOOL:...] tags:
   a. ExecuteTools() runs each tool
   b. StripToolTags() removes tags from display
   c. Tool results sent back to AI as follow-up
   d. Repeat up to 5 times
9. Final response displayed in chatbox with formatting
10. Response added to conversation history
```

---

## 3. Core Capabilities

### Capability Matrix

| # | Capability | Implementation | Status |
|---|---|---|---|
| 1 | **Local knowledge retrieval (RAG)** | TF-IDF + cosine similarity, auto-injection | ✅ Complete |
| 2 | **Tool invocation** | 42+ tools, unified dispatch, tool loop | ✅ Complete |
| 3 | **Multi-step task planning** | Tool loop (up to 5 iterations) | ✅ Complete |
| 4 | **Local multi-turn memory** | 20-message conversation history | ✅ Complete |
| 5 | **Permission control & privacy** | Sensitive data redaction + tool confirmation | ✅ Complete |

### RAG Implementation Details

- **Algorithm**: TF-IDF (Term Frequency-Inverse Document Frequency) with cosine similarity
- **Indexing**: Scans directory, extracts text from files, builds inverted index
- **Tokenization**: Lowercase, alphanumeric split, stop word removal (100+ stop words)
- **Ranking**: Cosine similarity between query vector and document vectors
- **Output**: Top 5 text passages with file path, line number, snippet, and relevance score
- **Injection**: RAG results inserted as system context message before user's question
- **Fallback**: If no relevant files found, AI responds without RAG context

### Tool Categories

**System Tools (10)**: open, run, read, write, search, volume, screenshot, lock, notify, clipboard

**AI Search / RAG Tools (6)**: index, search_files, search_filename, full_map, stats, rag_search

**Browser Automation (10)**: navigate, content, title, url, find, click, type, screenshot, links, summarize

**Screen Context (7)**: apps, active, capture, ocr, context, search, summary

**UI Locator (10)**: windows, elements, search, clickable, click_at, click, type, focus, close, map

---

## 4. Model Introduction & Local Deployment Plan

### Model
- **Model**: `minicpm-v` (MiniCPM-V)
- **Server**: vLLM (open-source inference engine)
- **Hardware**: AMD Radeon GPU
- **Software Stack**: ROCm
- **API**: OpenAI-compatible (`/v1/chat/completions`)

### Deployment Architecture

```
AMD Radeon Cloud Instance
├── ROCm Software Stack
│   ├── HIP runtime
│   ├── ROCm libraries (MIOpen, rocBLAS, etc.)
│   └── GPU drivers
├── vLLM Inference Server
│   ├── Model: minicpm-v
│   ├── PagedAttention for memory efficiency
│   └── Continuous batching
└── OpenAI-compatible API endpoint
    └── https://developer.amd.com.cn/radeon/spaces/.../v1
```

### Client-Side (Local)
- C++ Win32 application running on user's Windows desktop
- WinHTTP for API communication
- Local RAG engine (CPU-based, no GPU required)
- All tool execution is local

---

## 5. Optimization for Inference Speed on AMD Radeon GPU

### Server-Side Optimizations
- **vLLM**: PagedAttention reduces GPU memory waste, enables larger batch sizes
- **Continuous Batching**: Dynamic batching of requests for better GPU utilization
- **Model Choice**: `minicpm-v` is a lightweight model (4B parameters) optimized for fast inference
- **ROCm Optimization**: vLLM is compiled with ROCm support for AMD Radeon GPU acceleration

### Client-Side Optimizations
- **Retry Logic**: 3 retries with exponential backoff for network resilience
- **Timeout Management**: 30-second connect/receive timeouts prevent hanging
- **RAG Pre-filtering**: Only top 5 results injected (reduces prompt token count)
- **History Management**: 20-message window prevents unbounded prompt growth
- **Tool Result Truncation**: Long tool outputs truncated to prevent token overflow

### Performance Characteristics
- **RAG Search**: < 100ms for 100 files (local CPU, TF-IDF)
- **API Latency**: Depends on model server load (typically 1-5 seconds)
- **Tool Execution**: < 1s for most tools (file ops, system commands)
- **Proactive Timer**: 10-20 second intervals (configurable)

---

## 6. Privacy & Security

### Data Redaction
- Passwords, API keys, tokens, secrets → `[REDACTED]`
- Credit card numbers (12+ digit patterns) → `[REDACTED-CARD]`
- SSNs, bank accounts, routing numbers → `[REDACTED]`

### Permission Control
- Destructive tools (`write`, `run`, `lock`) require user confirmation dialog
- User can approve or deny each tool execution
- No tool executes without explicit user consent for destructive operations

### Data Flow Privacy
- Screen context is filtered locally before sending to AI
- RAG search is entirely local (no external API calls)
- Conversation history stored in memory only (not persisted to disk)
- No telemetry or usage tracking
