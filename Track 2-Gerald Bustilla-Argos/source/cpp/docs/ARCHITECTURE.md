# Architecture Document — Argos AI Companion

## 1. System Overview

Argos is a Windows desktop application built in C++ using the Win32 API and Direct2D. It provides a visual AI companion with a chatbox interface, powered by an AMD Radeon GPU cloud API (vLLM + ROCm) and a local RAG engine.

## 2. Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Argos Application                            │
│                                                                     │
│  ┌──────────────┐   ┌───────────────────┐   ┌────────────────────┐ │
│  │  Robot        │   │  Chatbox          │   │  Tray Icon         │ │
│  │  Renderer     │   │  (Rich Edit)      │   │  (Shell_NotifyIcon)│ │
│  │               │   │                   │   │                    │ │
│  │  Direct2D     │   │  • User bubbles   │   │  • Show/Hide       │ │
│  │  • Helmet     │   │  • AI bubbles     │   │  • Quit            │ │
│  │  • Eyes       │   │  • Thinking dots  │   │  • Settings        │ │
│  │  • Cape       │   │  • Auto-scroll    │   │                    │ │
│  │  • Animation  │   │  • Scroll preserve│   │                    │ │
│  └──────┬───────┘   └────────┬──────────┘   └─────────┬──────────┘ │
│         │                    │                         │             │
│  ┌──────┴────────────────────┴─────────────────────────┴──────────┐ │
│  │                    WndProc (main.cpp)                          │ │
│  │                                                                │ │
│  │  • WM_CREATE: Initialize renderer, agent, tray, timers         │ │
│  │  • WM_TIMER (IDT_LOADING): UpdateThinkingDots()                │ │
│  │  • WM_TIMER (IDT_PROACTIVE): GatherScreenContext + AI message  │ │
│  │  • WM_CHAT_RESPONSE: Display AI response, stop loading         │ │
│  │  • WM_CHAT_ERROR: Display error, stop loading                  │ │
│  │  • WM_COMMAND: Button clicks (send, voice, settings, clear)    │ │
│  │  • WM_LBUTTONUP: Toggle chatbox visibility                     │ │
│  └────────────────────────┬───────────────────────────────────────┘ │
│                           │                                         │
│  ┌────────────────────────┴───────────────────────────────────────┐ │
│  │              AgentClient (agent_client.cpp)                    │ │
│  │                                                                │ │
│  │  Chat(userMessage):                                            │ │
│  │    1. Add user message to history                              │ │
│  │    2. Run RAG search on user query                             │ │
│  │    3. Inject RAG context as system message                     │ │
│  │    4. For up to 5 iterations:                                  │ │
│  │       a. Build message list (system + history)                 │ │
│  │       b. Call ChatWithMessages() → API                         │ │
│  │       c. If HasToolTags(response):                             │ │
│  │          - ExecuteTools(response)                              │ │
│  │          - StripToolTags(response)                             │ │
│  │          - Add tool results to history                         │ │
│  │          - Continue loop                                       │ │
│  │       d. Else: break (final answer)                            │ │
│  │    5. Add final response to history                            │ │
│  │    6. Trim history to 20 messages                              │ │
│  │                                                                │ │
│  │  ChatWithMessages():                                           │ │
│  │    • WinHTTP POST to /v1/chat/completions                      │ │
│  │    • 3 retries with backoff                                    │ │
│  │    • 30s timeout                                               │ │
│  │    • JSON request/response parsing                             │ │
│  └────────────────────────┬───────────────────────────────────────┘ │
│                           │                                         │
│  ┌──────────┬─────────────┴──┬──────────────┬──────────────────────┐│
│  │  RAG     │  Tool Engine   │  Screen       │  Privacy Filter     ││
│  │  Engine  │  (argos_tools) │  Context      │  (main.cpp)         ││
│  │          │                │  (main.cpp)   │                     ││
│  │  TF-IDF  │  dispatch_tool │  GatherScreen │  filterSensitive()  ││
│  │  Cosine  │  • System (10) │  Context()    │  • Passwords        ││
│  │  BM25    │  • Search (6)  │  • GetFGWindow│  • API keys         ││
│  │  Index   │  • Browser(10) │  • Process ID │  • Tokens           ││
│  │  Search  │  • Screen (7)  │  • EnumWindows│  • Credit cards     ││
│  │  Inject  │  • UI (10)     │  • Filter     │  • SSNs             ││
│  └──────────┴────────────────┴──────────────┴──────────────────────┘│
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                         HTTPS (WinHTTP)
                                   │
┌──────────────────────────────────┴──────────────────────────────────┐
│                   AMD Radeon Cloud (ROCm)                          │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  vLLM Inference Server                                       │  │
│  │  • Model: minicpm-v                                          │  │
│  │  • PagedAttention                                            │  │
│  │  • Continuous batching                                       │  │
│  │  • OpenAI-compatible API                                     │  │
│  │  • Running on AMD Radeon GPU + ROCm                          │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

## 3. Threading Model

```
Main Thread (UI)
├── WndProc message handling
├── Robot rendering (Direct2D)
├── Chatbox updates (Rich Edit)
├── Timer callbacks
│   ├── IDT_LOADING (300ms): UpdateThinkingDots()
│   └── IDT_PROACTIVE (10-20s): Proactive message
│
Worker Threads (std::thread)
├── Chat thread: AgentClient::Chat() → API call
│   ├── RAG search (synchronous, local)
│   ├── API request (WinHTTP, blocking)
│   ├── Tool execution (synchronous)
│   └── PostMessage(WM_CHAT_RESPONSE) back to UI
│
└── Proactive thread: GatherScreenContext() + API call
    ├── Screen context gathering (Win32 API)
    ├── Privacy filtering (local)
    ├── API request (WinHTTP, blocking)
    └── PostMessage(WM_PROACTIVE_RESPONSE) back to UI
```

## 4. RAG Data Flow

```
User sends: "What does RefreshConversation do?"
                    │
                    ▼
┌─────────────────────────────────────┐
│  Step 1: Tokenize query             │
│  "what does refreshconversation do" │
│  → [refreshconversation]            │
│  (stop words removed)               │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│  Step 2: Index current directory    │
│  • Scan all text files              │
│  • Extract content per file         │
│  • Build TF-IDF vectors             │
│  • Build inverted index             │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│  Step 3: Cosine similarity search   │
│  • Query vector vs all doc vectors  │
│  • Rank by similarity score         │
│  • Select top 5 results             │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│  Step 4: Build context string       │
│  "RAG found 3 relevant passages:"   │
│  "--- Result 1 ---"                 │
│  "File: src/main.cpp"               │
│  "Line: 42"                         │
│  "Content: ...RefreshConversation..."│
│  "Score: 0.847"                     │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│  Step 5: Inject as system message   │
│  history.insert(system, ragContext) │
│  Before user's question             │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│  Step 6: Send to AI API             │
│  System prompt + RAG context +      │
│  conversation history + user query  │
│  → AMD Radeon GPU (vLLM + ROCm)    │
└─────────────────────────────────────┘
```

## 5. Tool Loop Sequence

```
User: "Search my project for error handling and open the results"
         │
         ▼
    AI Iteration 1:
    Response: "Searching your project. [TOOL:search_files C:\projects|error handling]"
         │
         ▼
    ExecuteTools(): Run search_files → returns JSON results
    StripToolTags(): Remove [TOOL:...] from display
    Add tool results to history
         │
         ▼
    AI Iteration 2:
    Response: "Found 3 files with error handling. Opening the first one. [TOOL:open C:\projects\main.cpp]"
         │
         ▼
    ExecuteTools(): Run open → opens file in default editor
    StripToolTags(): Remove [TOOL:...] from display
    Add tool results to history
         │
         ▼
    AI Iteration 3:
    Response: "I've opened main.cpp for you. The error handling is in the try-catch block on line 42."
    No tool tags → Final answer
         │
         ▼
    Display to user
```

## 6. File Descriptions

| File | Lines | Description |
|---|---|---|
| `main.cpp` | ~1466 | Main application: WndProc, chatbox, proactive system, privacy filter, screen context |
| `agent_client.cpp` | ~628 | HTTP client, RAG injection, tool loop, system prompt |
| `agent_client.h` | ~67 | Agent client class declaration |
| `argos_tools.cpp` | ~389 | RAG implementation + unified tool dispatch (42+ tools) |
| `argos_tools.h` | ~132 | Tool function declarations |
| `robot_renderer.cpp` | ~700+ | Direct2D rendering: Spartan helmet, eyes, cape, animations |
| `window_manager.cpp` | ~100 | Transparent overlay window creation |
| `tray_icon.cpp` | ~80 | System tray icon with context menu |
| `tools/search_engine.cpp` | ~200 | TF-IDF search engine implementation |
| `tools/vector_store.cpp` | ~300 | Vector store with cosine similarity + BM25 |
| `tools/content_indexer.cpp` | ~200 | Directory indexing and content extraction |
| `tools/text_utils.cpp` | ~150 | Tokenization, stop words, TF-IDF computation |
| `tools/file_mapper.cpp` | ~100 | File system mapping |
| `tools/image_hasher.cpp` | ~150 | Image fingerprinting (perceptual hash) |
| `tools/json_writer.cpp` | ~200 | JSON serialization for search results |
| `tools/browser_tool.cpp` | ~300 | Browser automation (Chrome DevTools Protocol) |
| `tools/screen_context.cpp` | ~200 | Screen context reading (active app, OCR) |
| `tools/ui_locator.cpp` | ~300 | UI element location (UI Automation API) |

## 7. Build & Run

### Build
```bash
cd cpp
build.bat
```

### Run
```bash
build\Debug\argos.exe
```

### Test
```bash
python testscripts\run_all_tests.py
```
