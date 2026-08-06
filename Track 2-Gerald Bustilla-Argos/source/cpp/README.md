# Argos — Faithful AI Companion

> A fully locally-deployed private AI agent with RAG, tool invocation, screen awareness, and a visual desktop companion — running on AMD Radeon GPU via ROCm.

![Argos](docs/argos_architecture.png)

## Overview

Argos is a desktop AI companion built in C++ for Windows. Named after the faithful dog of Odysseus, Argos lives on your desktop as a visual robot character with a golden Spartan helmet and red eyes. He watches your screen, proactively offers help, answers questions about your project files using RAG (Retrieval-Augmented Generation), and can execute 42+ tools to control your computer.

### Key Capabilities

| Capability | Implementation |
|---|---|
| **Local Knowledge Retrieval (RAG)** | TF-IDF vectorization + cosine similarity ranking over local project files. Automatic context injection before AI response. |
| **Tool Invocation** | 42+ tools: file operations, browser automation, screen reading, UI interaction, system control. Tool loop with up to 5 iterations. |
| **Multi-Turn Memory** | 20-message conversation history with full context preservation. Tool results fed back to AI for follow-up reasoning. |
| **Privacy/Permission Control** | Sensitive data redaction (passwords, tokens, credit cards) in screen context. Permission prompts for destructive tools. |
| **Proactive Screen Awareness** | Gathers active window titles, process names, and open applications. Generates contextual proactive messages every 10-20 seconds. |

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Argos Desktop Application                 │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │  Robot       │  │  Chatbox UI   │  │  Tray Icon         │ │
│  │  Renderer    │  │  (Rich Edit)  │  │  (System Tray)     │ │
│  │  (Direct2D)  │  │  Messenger-   │  │  Show/Hide/Quit    │ │
│  │  Spartan     │  │  style bubbles│  │                    │ │
│  │  helmet+eyes │  │  Auto-scroll  │  │                    │ │
│  └─────────────┘  └──────────────┘  └────────────────────┘ │
│         │                │                     │             │
│  ┌──────┴────────────────┴─────────────────────┴──────────┐ │
│  │              Main Controller (WndProc)                  │ │
│  │  • Message routing  • Timer management                  │ │
│  │  • Proactive system  • Chat lifecycle                   │ │
│  └──────────────────────┬──────────────────────────────────┘ │
│                         │                                    │
│  ┌──────────────────────┴──────────────────────────────────┐ │
│  │              Agent Client (agent_client.cpp)             │ │
│  │  • RAG context injection (automatic)                     │ │
│  │  • Tool loop (up to 5 iterations)                        │ │
│  │  • Multi-turn conversation history                       │ │
│  │  • WinHTTP with retry + timeout                          │ │
│  └──────────────────────┬──────────────────────────────────┘ │
│                         │                                    │
│  ┌──────────┬───────────┴──┬──────────────┬────────────────┐ │
│  │  RAG     │  Tool Engine │  Screen       │  Privacy       │ │
│  │  Engine  │  (42+ tools) │  Context      │  Filter        │ │
│  │  TF-IDF  │  • File ops  │  • Win32 API  │  • Redact      │ │
│  │  Cosine  │  • Browser   │  • Process    │    passwords   │ │
│  │  BM25    │  • UI loc    │  • Windows    │  • Redact      │ │
│  │  Index   │  • Search    │  • Privacy    │    tokens/cards│ │
│  └──────────┴──────────────┴──────────────┴────────────────┘ │
└─────────────────────────────┬───────────────────────────────┘
                              │
                    HTTPS (WinHTTP)
                              │
┌─────────────────────────────┴───────────────────────────────┐
│              AMD Radeon Cloud (ROCm)                        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  vLLM Inference Server                               │   │
│  │  Model: minicpm-v                                    │   │
│  │  OpenAI-compatible API                               │   │
│  │  Running on AMD Radeon GPU + ROCm software stack     │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Project Structure

```
amdagentic/
└── cpp/
    ├── build.bat                  # Build script (MSVC)
    ├── README.md                  # This file
    ├── docs/                      # Documentation
    │   ├── PROJECT_SPECIFICATION.md
    │   ├── ARCHITECTURE.md
    │   └── argos_architecture.png
    ├── demo/                      # Demo video and screenshots
    ├── testscripts/               # Test suite
    │   ├── README.md
    │   ├── run_all_tests.py
    │   ├── test_chatbox_sim.py    # 115 chatbox UI tests
    │   ├── test_rag_sim.py        # 55 RAG pipeline tests
    │   ├── test_api_new.py        # API connectivity test
    │   ├── test_api.py
    │   └── test_all_providers.py
    └── src/                       # Source code
        ├── main.cpp               # Main app, WndProc, chatbox, proactive system
        ├── agent_client.cpp       # HTTP client, RAG injection, tool loop
        ├── agent_client.h         # Agent client header
        ├── argos_tools.cpp        # Unified tool dispatch + RAG implementation
        ├── argos_tools.h          # Tool declarations
        ├── robot_renderer.cpp     # Direct2D robot rendering (Spartan helmet)
        ├── robot_renderer.h
        ├── window_manager.cpp     # Transparent overlay window
        ├── window_manager.h
        ├── tray_icon.cpp          # System tray icon
        ├── tray_icon.h
        ├── resource.h             # Resource IDs
        └── tools/                 # C++ AI tool libraries
            ├── search_engine.h    # TF-IDF search engine
            ├── vector_store.h     # Vector store with cosine similarity
            ├── content_indexer.h  # Directory indexing
            ├── file_mapper.h      # File system mapping
            ├── text_utils.h       # Tokenization, TF-IDF, stop words
            ├── image_hasher.h     # Image fingerprinting
            ├── json_writer.h      # JSON serialization
            ├── browser_tool.h     # Browser automation
            ├── screen_context.h   # Screen context reading
            ├── ui_locator.h       # UI element location
            └── *.cpp              # Implementations
```

## Environment Configuration

### Prerequisites

- **OS**: Windows 10/11 (x64)
- **Compiler**: Microsoft Visual C++ (MSVC) 19.x+
- **Framework**: Win32 API, Direct2D
- **API Server**: AMD Radeon Cloud with ROCm (vLLM serving `minicpm-v` model)

### Build Instructions

```bash
# From the cpp/ directory
build.bat
```

This compiles all source files and produces `build\Debug\argos.exe`.

### Running Argos

```bash
# Launch the application
build\Debug\argos.exe
```

Argos will appear as a small robot in the bottom-left corner of your screen. Click the robot to open the chatbox.

### API Configuration

The API endpoint is configured in `src/agent_client.h`:

```cpp
std::wstring m_serverUrl = L"https://developer.amd.com.cn/radeon/spaces/u-4408-1fb1befd/8000/v1";
std::wstring m_apiKey = L"rc-c042ad0acc56669f7b46e70f924189b5ac51664ce329f5b2";
std::wstring m_model = L"minicpm-v";
```

The API is OpenAI-compatible, served by **vLLM** on **AMD Radeon GPU** with the **ROCm** software stack.

## AMD Radeon GPU / ROCm Adaptation

### Inference Architecture

Argos uses AMD Radeon Cloud for AI inference:

1. **vLLM Server**: The `minicpm-v` model is served using vLLM, an open-source inference engine optimized for AMD Radeon GPUs.
2. **ROCm Software Stack**: The vLLM server runs on AMD ROCm, providing GPU-accelerated inference.
3. **OpenAI-Compatible API**: The server exposes a standard `/v1/chat/completions` endpoint, making it compatible with any OpenAI API client.
4. **WinHTTP Client**: Argos uses Windows WinHTTP API for HTTP communication with retry logic (3 attempts) and 30-second timeouts.

### Inference Optimization

- **vLLM**: Provides PagedAttention and continuous batching for efficient GPU memory usage
- **Model**: `minicpm-v` is a lightweight multimodal model optimized for fast inference
- **Retry Logic**: 3 retries with exponential backoff for network resilience
- **Timeout Management**: 30s connect/receive timeouts prevent hanging

### Local RAG (No GPU Required)

The RAG (Retrieval-Augmented Generation) system runs **entirely locally** on the CPU:
- TF-IDF vectorization with inverted index
- Cosine similarity ranking
- No external API calls for document search
- Zero latency for local knowledge retrieval

## Core Capabilities

### 1. RAG (Retrieval-Augmented Generation)

When the user sends a message, Argos automatically:
1. Indexes the current working directory (file scanning + text extraction)
2. Tokenizes the user's query (with stop word removal)
3. Builds a TF-IDF query vector
4. Calculates cosine similarity with all indexed documents
5. Injects the top 5 relevant text passages as system context before the AI response

The AI sees both the user's question and relevant code/docs from the project, enabling project-aware answers.

### 2. Tool Invocation (42+ Tools)

**System Tools**: `open`, `run`, `read`, `write`, `search`, `volume`, `screenshot`, `lock`, `notify`, `clipboard`

**AI Search Tools (RAG)**: `index`, `search_files`, `search_filename`, `full_map`, `stats`, `rag_search`

**Browser Automation**: `browser_navigate`, `browser_content`, `browser_title`, `browser_url`, `browser_find`, `browser_click`, `browser_type`, `browser_screenshot`, `browser_links`, `browser_summarize`

**Screen Context**: `screen_apps`, `screen_active`, `screen_capture`, `screen_ocr`, `screen_context`, `screen_search`, `screen_summary`

**UI Locator**: `ui_windows`, `ui_elements`, `ui_search`, `ui_clickable`, `ui_click_at`, `ui_click`, `ui_type`, `ui_focus`, `ui_close`, `ui_map`

### 3. Tool Loop

When the AI calls a tool, Argos:
1. Executes the tool and collects results
2. Strips tool tags from the display text
3. Sends tool results back to the AI as a follow-up message
4. The AI processes the results and either calls another tool or gives a final answer
5. Up to 5 iterations (prevents infinite loops)

### 4. Multi-Turn Memory

- 20-message conversation history window
- Full context preservation across turns
- Tool results stored in history for follow-up questions

### 5. Privacy & Permission Control

**Privacy Filter**: Screen context is filtered before sending to AI:
- Passwords, API keys, tokens, secrets, credentials → `[REDACTED]`
- Credit card numbers (12+ digits with dashes) → `[REDACTED-CARD]`
- SSNs, bank accounts, routing numbers → `[REDACTED]`

**Permission Control**: Destructive tools (`write`, `run`, `lock`) require user confirmation via dialog before execution.

### 6. Proactive Screen Awareness

- Gathers active window title, process name, and open windows every 10-20 seconds
- Generates contextual proactive messages ("I see you're coding in VS Code...")
- Stops when chatbox is open, resumes when closed
- Privacy-filtered before sending to AI

### 7. Modern Messenger-Style Chatbox

- User messages: blue background, white text, right-aligned
- Argos messages: light gray background, black text, left-aligned
- Animated thinking indicator with cycling dots
- Auto-scroll when at bottom, scroll position preserved when reading history
- Rich Edit control with paragraph formatting and character styling

## Testing

See `testscripts/README.md` for detailed test documentation.

```bash
# Run all tests
python testscripts\run_all_tests.py

# Run individual test suites
python testscripts\test_chatbox_sim.py    # 115 tests
python testscripts\test_rag_sim.py        # 55 tests
python testscripts\test_api_new.py        # API connectivity
```

**Test Results**: 170+ tests, all passing (API tests skip gracefully when instance is unavailable).

## Dependencies

- **Win32 API**: Window management, timers, system tray
- **Direct2D (d2d1.lib)**: Robot rendering with gradients and shapes
- **WinHTTP (winhttp.lib)**: HTTP client for API communication
- **Rich Edit (msftedit.dll)**: Chatbox conversation display
- **Shell API (shell32.lib)**: File execution, notifications
- **DWM (dwmapi.lib)**: Desktop Window Manager for transparency

No external libraries required. All C++ tool libraries (AI search, browser, screen context, UI locator) are included in `src/tools/`.

## License

This project is submitted for the AMD AI DevMaster Hackathon 2026.
