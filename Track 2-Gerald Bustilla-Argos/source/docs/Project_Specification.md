# Argos — Private AI Agent on AMD Radeon GPU
## Project Specification Document

**Track 2: Development & Local Deployment of Private AI Agents**
**Team: GERALD BUSTILLA**
**Application: Argos — Agentic AI Companion**

---

## 1. Application Scenarios

### Personal Intelligent Assistant
Argos is a persistent, always-on AI companion that lives on the user's desktop as a floating overlay robot. It provides:
- **Real-time chat** with SSE streaming responses (token-by-token)
- **Proactive engagement** — Argos periodically observes the screen and initiates helpful suggestions
- **Voice input** via Whisper local speech-to-text (push-to-talk with Caps Lock)
- **Screen awareness** — reads on-screen text, identifies active applications, interacts with browser content

### Office Automation Assistant
- **Browser automation** — opens URLs, reads search results, clicks elements by text, fills forms
- **File management** — lists, reads, and searches files across the filesystem
- **Command execution** — runs shell commands and reports results
- **Keyboard/mouse control** — types text, presses keys, sends hotkey combinations

### Local Knowledge Base Q&A Assistant (RAG)
- **Document indexing** — syncs Desktop, Documents, Downloads, Music, and Videos folders
- **Semantic search** — TF-IDF vector store with BM25 scoring and Reciprocal Rank Fusion (RRF)
- **Persistent memory** — conversation history saved to JSONL, loaded on startup for multi-turn context
- **Privacy-preserving** — all indexing and search runs locally, no data sent to external services

---

## 2. Agent Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Argos AI Agent System                           │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────────────┐   │
│  │  Robot Overlay│   │ Speech Bubble│   │  System Tray          │   │
│  │  (Direct2D)   │   │ (Chat UI)    │   │  (Hide/Show/Quit)     │   │
│  │  • Animations │   │ • Streaming  │   └───────────────────────┘   │
│  │  • Shield/Sword│  │ • Settings   │                               │
│  │  • Lightning   │   │ • RAG Sync   │                               │
│  └──────┬───────┘   └──────┬───────┘                               │
│         │                  │                                        │
│         └────────┬─────────┘                                        │
│                  ▼                                                   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    Agent Core (C++)                           │   │
│  │                                                               │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │   │
│  │  │ AgentClient │  │ Tool         │  │ RAG Engine         │  │   │
│  │  │ • SSE Stream│  │ Dispatcher   │  │ • TF-IDF Index     │  │   │
│  │  │ • Multi-turn│  │ • 38+ Tools  │  │ • BM25 Scoring     │  │   │
│  │  │ • Fallback  │  │ • Tool Loop  │  │ • RRF Fusion       │  │   │
│  │  │   Model     │  │  (8 iter)    │  │ • Persistent Index │  │   │
│  │  └──────┬──────┘  └──────┬───────┘  └────────┬───────────┘  │   │
│  │         │                │                    │              │   │
│  │  ┌──────┴────────────────┴────────────────────┴───────────┐  │   │
│  │  │              Memory Layer (JSONL)                       │  │   │
│  │  │  • Conversation persistence                             │  │   │
│  │  │  • Cross-session recall                                 │  │   │
│  │  └─────────────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│                              │ HTTPS (SSE Streaming)                 │
│                              ▼                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │           AMD Radeon Cloud API (OpenAI-compatible)           │   │
│  │                                                               │   │
│  │  • DeepSeek-V4-Flash (Primary — fast inference)              │   │
│  │  • MiniCPM5-1B (Fallback — lightweight)                      │   │
│  │  • Qwen3.6-35B-A3B (Vision — OCR/screen analysis)           │   │
│  │  • Whisper.cpp (Local — on-device speech-to-text)            │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  Local Components (100% on-device):                                 │
│  • Whisper speech-to-text (whisper.cpp + GGML)                      │
│  • RAG indexing & search (TF-IDF + BM25)                           │
│  • Conversation memory (JSONL persistence)                          │
│  • All tool execution (file, browser, screen, keyboard)            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Introduction to Core Capabilities

### 3.1 Tool Invocation (✅ Implemented)
Argos supports **38+ tools** invoked through a structured `[TOOL:name args]` syntax. The agent operates in an **agentic loop** (up to 8 iterations):
1. AI receives user message → generates response with tool tags
2. Tools execute locally → results fed back to AI
3. AI continues reasoning with tool results → may call more tools
4. Loop continues until AI produces a final answer without tool tags

**Tool Categories:**
| Category | Tools | Count |
|----------|-------|-------|
| File Operations | list_files, read, write, search_files, search_filename, index | 6 |
| Browser Automation | open_url, browser_screenshot, click_text, get_url | 4 |
| Screen Interaction | screen_text, screen_active, click, type_text, scroll, keyboard_key, keyboard_hotkey | 7 |
| System Commands | cmd, screenshot | 2 |
| RAG & Memory | rag_search, recall, forget, memory_load, memory_clear | 5 |
| UI Automation | find_element, focus_element, get_element_text | 3 |
| Computer Use | computer_use (unified screen interaction) | 1 |
| Misc | time, date, calculate | 3+ |

### 3.2 Local Knowledge Retrieval — RAG (✅ Implemented)
- **TF-IDF Vector Store**: Documents are chunked and indexed using Term Frequency-Inverse Document Frequency
- **BM25 Scoring**: Okapi BM25 ranking algorithm for relevance scoring
- **Reciprocal Rank Fusion (RRF)**: Merges TF-IDF and BM25 results for improved accuracy
- **Persistent Index**: Indices saved to disk for fast subsequent queries without re-indexing
- **Manual Folder Sync**: User selects which folders to index (Desktop, Documents, Downloads, Music, Videos)
- **Privacy-First**: All indexing and search executes locally — no external API calls

### 3.3 Local Multi-Turn Memory (✅ Implemented)
- **JSONL Persistence**: Every conversation (user + assistant) saved to `argos_memory.jsonl`
- **Cross-Session Recall**: On startup, Argos loads recent conversation history (last 5 messages) to maintain context
- **Memory Tools**: AI can explicitly `recall` past conversations or `forget` to clear memory
- **Context Window Management**: History limited to 20 messages to prevent context overflow

### 3.4 Multi-Step Task Planning (✅ Implemented)
- **Agentic Tool Loop**: AI decomposes complex tasks into multiple tool calls across iterations
- **Example**: "Search for cats on Google" → `open_url(google.com/search?q=cats)` → `screen_text()` → AI summarizes results
- **Conditional Execution**: AI decides which tools to call based on previous tool results
- **Error Handling**: Tool failures are fed back to AI for self-correction

### 3.5 Privacy Control & Permission Mechanism (✅ Implemented)
- **Local-First Architecture**: RAG, memory, and tool execution all run locally
- **No Telemetry**: No usage data, analytics, or crash reports sent anywhere
- **Configurable API Endpoint**: Users can point to any OpenAI-compatible server (including fully local deployments via vLLM/llama.cpp on AMD Radeon GPU)
- **User-Controlled RAG Sync**: Folders are only indexed when explicitly selected by the user
- **API Key Protection**: No hardcoded keys — users provide their own via config file, environment variable, or settings UI
- **Config File**: `argos_config.txt` (next to exe or `%APPDATA%/Argos/`)

### 3.6 Voice Input (✅ Implemented)
- **Whisper.cpp Integration**: Local speech-to-text using GGML-optimized Whisper model (tiny.en)
- **Push-to-Talk**: Hold Caps Lock to record, release to transcribe and auto-send
- **100% On-Device**: No audio sent to any server — all transcription happens locally

### 3.7 Visual Robot Companion (✅ Implemented)
- **Direct2D Rendering**: Custom 2.5D Spartan warrior robot with golden armor, shield, and sword
- **State-Driven Animations**: Idle, Walking, Greeting, Working, Celebrating, Sleeping, Dragging
- **Electric Lightning Effect**: Visual indicator when tools are executing — cyan bolts flicker around the robot
- **Proactive Behavior**: Robot walks across screen, periodically observes screen context

---

## 4. Model Introduction & Local Deployment Plan

### 4.1 Models Used

| Model | Role | Deployment | Optimization |
|-------|------|------------|--------------|
| **DeepSeek-V4-Flash** | Primary LLM | AMD Radeon Cloud API | Fast inference, streaming SSE |
| **MiniCPM5-1B** | Fallback LLM | AMD Radeon Cloud API | Lightweight, used when primary fails |
| **Qwen3.6-35B-A3B** | Vision/Multimodal | AMD Radeon Cloud API | OCR, screen analysis |
| **Whisper Tiny EN** | Speech-to-Text | 100% Local (whisper.cpp) | GGML quantized, CPU inference |

### 4.2 Local Deployment Plan

**Current Architecture:**
- Core inference runs on AMD Radeon Cloud API (OpenAI-compatible endpoint at `developer.amd.com.cn`)
- Speech-to-text runs 100% locally via whisper.cpp (GGML)
- RAG, memory, and all tool execution run locally

**Full Local Deployment Path (for AMD Radeon GPU + ROCm):**
1. **LLM Server**: Deploy vLLM or llama.cpp (ROCm build) on AMD Radeon GPU
   - Load DeepSeek-V4-Flash or equivalent model
   - Expose OpenAI-compatible API endpoint
   - Point Argos to local endpoint via `argos_config.txt`
2. **Speech-to-Text**: Already local via whisper.cpp
3. **RAG**: Already local (TF-IDF + BM25)
4. **Memory**: Already local (JSONL)
5. **Tools**: Already local (Win32 APIs)

**Configuration for Full Local Deployment:**
```ini
# argos_config.txt
server_url=http://localhost:8000/v1
api_key=local-no-key-needed
model=DeepSeek-V4-Flash
```

---

## 5. Optimization Description for Inference Speed on AMD Radeon GPU

### 5.1 SSE Streaming
- Responses stream token-by-token via Server-Sent Events
- User sees partial responses immediately — perceived latency is near-zero
- Eliminates waiting for full response generation before display

### 5.2 Model Fallback Chain
- Primary model (DeepSeek-V4-Flash) optimized for speed
- Automatic fallback to MiniCPM5-1B if primary is unavailable
- Prevents total failure — always returns a response

### 5.3 Agentic Loop Optimization
- Maximum 8 tool iterations per request — prevents infinite loops
- Tool results are concise (truncated to prevent context bloat)
- History limited to 20 messages to keep prompt size manageable

### 5.4 Local Component Optimization
- **Whisper Tiny EN model**: ~75MB, sub-second transcription on CPU
- **RAG persistent index**: Saved to disk — no re-indexing on startup
- **BM25 + RRF**: O(n) retrieval with lightweight scoring — no GPU needed for RAG
- **JSONL memory**: Append-only writes, O(1) for save, O(n) for load (limited to 5 messages)

### 5.5 AMD Radeon GPU Optimization Path
For full local deployment on AMD Radeon GPU with ROCm:
- **vLLM with ROCm**: PagedAttention for efficient KV cache management
- **Quantization**: INT8/INT4 quantization via GGUF for llama.cpp
- **Batched inference**: Multiple tool results processed in single forward pass
- **Flash Attention**: ROCm-supported flash attention for reduced memory bandwidth

---

## 6. Capabilities Summary (vs. Competition Requirements)

| Required Capability (min 2 of 5) | Status | Implementation |
|----------------------------------|--------|----------------|
| Local knowledge retrieval (RAG) | ✅ | TF-IDF + BM25 + RRF, persistent index |
| Tool invocation | ✅ | 38+ tools, agentic loop (8 iterations) |
| Multi-step task planning | ✅ | AI decomposes tasks via tool loop |
| Local multi-turn memory | ✅ | JSONL persistence, cross-session recall |
| Permission control & privacy | ✅ | Config file, env vars, no telemetry, local-first |

**All 5 capabilities implemented** (minimum was 2).

---

## 7. Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | C++17 |
| UI Framework | Win32 API + Direct2D |
| AI Inference | AMD Radeon Cloud API (OpenAI-compatible) |
| Speech-to-Text | whisper.cpp (GGML, local) |
| RAG Engine | Custom TF-IDF + BM25 + RRF |
| Memory | JSONL persistent storage |
| Browser Automation | Windows UI Automation API |
| Build System | MSBuild (Visual Studio 2022) |
| Platform | Windows 10/11 x64 |

---

## 8. File Structure

```
amdagentic/
├── cpp/
│   ├── src/
│   │   ├── main.cpp                 # Win32 entry, overlay window, chat UI
│   │   ├── robot_renderer.cpp/.h    # Direct2D robot (Spartan warrior)
│   │   ├── agent_client.cpp/.h      # AI chat, SSE, tool loop
│   │   ├── argos_tools.cpp/.h       # 38+ tools, RAG, memory
│   │   ├── window_manager.cpp/.h    # Transparent overlay window
│   │   ├── tray_icon.cpp/.h         # System tray
│   │   └── tools/                   # Browser, screen, UI automation
│   ├── src_cross/                   # Cross-platform core (shared logic)
│   │   ├── agent_client_core.*      # Shared agent logic
│   │   ├── argos_tools_core.*       # Shared tool implementations
│   │   └── whisper_wrapper.*        # Whisper speech-to-text
│   ├── third_party/
│   │   └── whisper.cpp/             # GGML whisper.cpp library
│   └── build.bat                    # Windows build script
├── docs/                            # Documentation
└── README.md                        # Project README
```
