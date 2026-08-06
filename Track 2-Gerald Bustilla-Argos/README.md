# Argos — Agentic AI Companion (Windows Desktop)

> Named after the faithful dog of Odysseus — Argos waits, watches, and acts.
>
> **Track 2: Development & Local Deployment of Private AI Agents**
> **Team: GERALD BUSTILLA**

An AI companion robot that lives on your Windows desktop as a floating overlay. Click the robot to chat, ask questions, or instruct it to browse the web, read screen content, execute commands, search local files (RAG), and more. Features a Spartan warrior robot with shield and sword, electric lightning effects during tool execution, and push-to-talk voice input via local Whisper.

Powered by **AMD Radeon Cloud API** (OpenAI-compatible) with SSE streaming, 38+ tool calling, RAG-based knowledge retrieval, and persistent multi-turn memory.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Environment Requirements](#environment-requirements)
- [Build Guide](#build-guide)
- [Dependency List](#dependency-list)
- [Features](#features)
- [Architecture](#architecture)
- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Local Deployment on AMD Radeon GPU](#local-deployment-on-amd-radeon-gpu)
- [License](#license)

---

## Quick Start

### Option A: Pre-built Binary
1. Download `argos.exe` from the [Releases](../../releases) page
2. Create `argos_config.txt` in the same folder with your API key:
   ```ini
   server_url=https://developer.amd.com.cn/radeon/api/v1
   api_key=YOUR_API_KEY_HERE
   model=DeepSeek-V4-Flash
   ```
3. Run `argos.exe`
4. Click the robot → speech bubble opens → start chatting

### Option B: Build from Source
```bash
git clone https://github.com/Zrald1/amdagentic.git
cd amdagentic\cpp
build.bat
```
Output: `cpp\build\Debug\argos.exe`

---

## Configuration

Argos supports **three methods** for configuring the API key and server URL (in priority order):

### 1. Environment Variables (Highest Priority)
```bash
set ARGOS_API_KEY=your-api-key-here
set ARGOS_SERVER_URL=https://developer.amd.com.cn/radeon/api/v1
set ARGOS_MODEL=DeepSeek-V4-Flash
argos.exe
```

### 2. Config File
Create `argos_config.txt` in one of these locations:
- **Next to `argos.exe`** (recommended for portable deployments)
- **`%APPDATA%\Argos\argos_config.txt`** (for installed deployments)

```ini
server_url=https://developer.amd.com.cn/radeon/api/v1
api_key=your-api-key-here
model=DeepSeek-V4-Flash
fallback_model=MiniCPM5-1B
vision_model=Qwen3.6-35B-A3B
```

### 3. Settings UI (In-App)
1. Click the robot → speech bubble opens
2. Click the **Settings** button
3. Enter Base URL, API Key, and Model name
4. Settings are automatically saved to `argos_config.txt` when you send a message

> **Note:** No API key is hardcoded in the source code. Users must provide their own key.

### Getting an AMD Radeon Cloud API Key
The AMD Radeon Developer Cloud provides free access to AI models via an OpenAI-compatible API. Visit the [AMD Radeon Cloud portal](https://developer.amd.com.cn) to obtain an API key.

---

## Environment Requirements

### Build Requirements
| Requirement | Version |
|-------------|---------|
| OS | Windows 10 or 11 (x64) |
| Compiler | Visual Studio 2022 (C++ Build Tools) |
| Windows SDK | 10.0 (latest) |
| C++ Standard | C++17 |

### Runtime Requirements
| Requirement | Notes |
|-------------|-------|
| OS | Windows 10/11 x64 |
| RAM | 512MB free (1GB with Whisper model) |
| Disk | 100MB (app) + 75MB (Whisper model) |
| Network | Internet access to AMD Radeon Cloud API |
| GPU | Any GPU (Direct2D rendering); AMD Radeon recommended for local deployment |

### Whisper Voice Input (Optional)
For push-to-talk voice input, download the Whisper model:
1. Download `ggml-tiny.en.bin` (~75MB) from [Hugging Face](https://huggingface.co/ggerganov/whisper.cpp)
2. Place it in one of these locations:
   - Next to `argos.exe`
   - `%USERPROFILE%\ggml-tiny.en.bin`
   - `C:\models\ggml-tiny.en.bin`
3. Hold **Caps Lock** to record → release to transcribe → auto-sends to Argos

---

## Build Guide

### Step-by-Step Build

1. **Install Visual Studio 2022 Build Tools**
   - Download from: https://visualstudio.microsoft.com/downloads/
   - Select "Build Tools for Visual Studio 2022"
   - Check "Desktop development with C++" workload

2. **Clone and Build**
   ```bash
   git clone https://github.com/Zrald1/amdagentic.git
   cd amdagentic\cpp
   build.bat
   ```

3. **Output**
   ```
   cpp\build\Debug\argos.exe
   ```

### Build Configuration
The build script (`build.bat`) compiles all source files with MSVC and links against:
- `d2d1.lib` (Direct2D)
- `dwmapi.lib` (Desktop Window Manager)
- `winhttp.lib` (HTTP client)
- `user32.lib`, `gdi32.lib`, `shell32.lib` (Windows APIs)
- `ole32.lib`, `oleaut32.lib` (COM/UI Automation)
- `uiautomationcore.lib` (UI Automation)
- `winmm.lib` (Audio recording)
- `advapi32.lib` (Security/registry)

### Whisper.cpp (Bundled)
The `third_party/whisper.cpp` library is included in the repository. It's compiled as part of the build — no separate installation needed.

---

## Dependency List

### Build Dependencies (all included in repo or Windows SDK)
| Dependency | Source | Purpose |
|-----------|--------|---------|
| Direct2D | Windows SDK | 2D graphics rendering |
| Win32 API | Windows SDK | Window management, UI |
| WinHTTP | Windows SDK | HTTP/SSE streaming |
| UI Automation | Windows SDK | Browser/screen interaction |
| whisper.cpp | `third_party/whisper.cpp` | Local speech-to-text |
| GGML | `third_party/whisper.cpp` (bundled) | Tensor math for Whisper |

### No External Package Managers Required
The project has **zero external dependencies** that need to be installed via vcpkg, NuGet, or any other package manager. Everything is either in the Windows SDK or bundled in `third_party/`.

---

## Features

### AI Chat
- **SSE streaming** — Responses stream in real-time, token by token
- **Reasoning/thoughts display** — AI's internal reasoning shown as italic thoughts
- **Conversation memory** — Persists across sessions in JSONL files
- **Fallback model** — Automatically falls back to MiniCPM5-1B if primary fails

### AI Tools (38+ Tools)
The AI can call tools using `[TOOL:tool_name args]` syntax. Tools execute in a loop (up to 8 iterations).

| Tool | Description |
|------|-------------|
| `list_files` | List files in a directory |
| `read` | Read file contents |
| `write` | Write to a file |
| `cmd` | Execute shell commands |
| `open_url` | Open a URL in the browser |
| `screen_text` | Read all text visible on screen |
| `screen_active` | Get the currently focused app |
| `click_text` | Click an element by its text |
| `type_text` | Type text into the focused input |
| `scroll` | Scroll the screen up/down |
| `keyboard_key` | Press a single key |
| `keyboard_hotkey` | Press key combinations (ctrl+c, etc.) |
| `rag_search` | RAG-based file content search |
| `recall` | Load conversation memory |
| `forget` | Clear conversation memory |
| `browser_screenshot` | Take browser screenshots |
| `search_files` | Search text content in a directory |
| `search_filename` | Search filenames by pattern |
| `index` | Index a directory for searching |
| `screenshot` | Capture the screen |
| `computer_use` | Unified screen interaction tool |
| ...and more | |

### RAG (Local Knowledge Retrieval)
- **TF-IDF + BM25** vector indexing with Reciprocal Rank Fusion
- **Manual folder sync** — user selects which folders to index
- **Persistent index** — saved to disk for fast subsequent queries
- **100% local** — no external API calls for search

### Voice Input (Push-to-Talk)
- **Whisper.cpp** local speech-to-text (GGML-optimized)
- Hold **Caps Lock** to record → release to transcribe → auto-send
- No audio sent to any server

### Visual Robot Companion
- **Direct2D Spartan warrior** with golden armor, shield (left arm), sword (right arm)
- **Electric lightning effect** — cyan bolts flicker around robot when executing tools
- **State-driven animations** — idle, walk, greet, work, celebrate, sleep
- **Proactive behavior** — robot walks, observes screen, initiates suggestions
- **System tray** — hide/show/quit from tray

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Windows Desktop (C++ / Win32 / Direct2D)           │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  Robot   │  │ Speech Bubble│  │  System Tray  │  │
│  │ (D2D)    │  │ (Chat UI)    │  │               │  │
│  └────┬─────┘  └──────┬───────┘  └───────────────┘  │
│       │               │                              │
│       └───────┬───────┘                              │
│               ▼                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │  Agent Core (C++)                             │   │
│  │  • AgentClient (SSE stream, tool loop)        │   │
│  │  • Tool Dispatcher (38+ tools)                │   │
│  │  • RAG Engine (TF-IDF + BM25 + RRF)          │   │
│  │  • Memory Persistence (JSONL)                 │   │
│  │  • Whisper STT (local, GGML)                  │   │
│  └──────────────────┬───────────────────────────┘   │
└─────────────────────┼───────────────────────────────┘
                      │ HTTPS (SSE streaming)
                      ▼
           ┌─────────────────────┐
           │  AMD Radeon Cloud   │
           │  API (OpenAI-compat)│
           │  • DeepSeek-V4-Flash│
           │  • MiniCPM5-1B      │
           │  • Qwen3.6-35B-A3B  │
           └─────────────────────┘
```

**Local components (100% on-device):**
- Whisper speech-to-text (whisper.cpp + GGML)
- RAG indexing & search (TF-IDF + BM25)
- Conversation memory (JSONL persistence)
- All tool execution (file, browser, screen, keyboard)

---

## How It Works

1. **Click the robot's head** → speech bubble opens
2. **Type a message** (or hold Caps Lock for voice) → AI streams thoughts then response
3. **AI decides to use a tool** → tool executes locally → result feeds back to AI → AI continues
4. **Example: "Search for cats on Google"**
   - AI calls `[TOOL:open_url https://www.google.com/search?q=cats]`
   - Browser opens, 2-second delay for page load
   - AI calls `[TOOL:screen_text]` → reads search results
   - AI summarizes the results for you
5. **Electric lightning** flickers around the robot while tools execute

---

## Project Structure

```
amdagentic/
├── cpp/
│   ├── src/
│   │   ├── main.cpp                 # Win32 entry, overlay window, chat UI
│   │   ├── robot_renderer.cpp/.h    # Direct2D Spartan warrior robot
│   │   ├── agent_client.cpp/.h      # AI chat, SSE, tool loop
│   │   ├── argos_tools.cpp/.h       # 38+ tools, RAG, memory
│   │   ├── window_manager.cpp/.h    # Transparent overlay window
│   │   ├── tray_icon.cpp/.h         # System tray
│   │   └── tools/                   # Browser, screen, UI automation
│   │       ├── browser_tool.cpp
│   │       ├── screen_context.cpp
│   │       ├── ui_locator.cpp
│   │       └── computer_use_tool.cpp
│   ├── src_cross/                   # Cross-platform core (Android + Windows)
│   │   ├── agent_client_core.*      # Shared agent logic
│   │   ├── argos_tools_core.*       # Shared tool implementations
│   │   ├── whisper_wrapper.*        # Whisper speech-to-text
│   │   └── platform.h               # Platform abstraction
│   ├── third_party/
│   │   └── whisper.cpp/             # GGML whisper.cpp library (bundled)
│   ├── build.bat                    # Windows build script
│   └── argos_config.txt             # User config (created on first save)
├── android/                         # Android app (Java + JNI)
├── docs/
│   └── Project_Specification.md     # Project specification document
└── README.md                        # This file
```

---

## Local Deployment on AMD Radeon GPU

### Full Local Deployment (with vLLM on ROCm)

To run everything locally on an AMD Radeon GPU with ROCm:

1. **Set up vLLM with ROCm** on your AMD Radeon GPU machine:
   ```bash
   # Install ROCm (see AMD documentation)
   pip install vllm[rocm]
   vllm serve --model deepseek-ai/deepseek-v4-flash --port 8000
   ```

2. **Configure Argos to use local endpoint:**
   ```ini
   # argos_config.txt
   server_url=http://localhost:8000/v1
   api_key=local
   model=deepseek-ai/deepseek-v4-flash
   ```

3. **Run Argos:**
   ```bash
   argos.exe
   ```

### Alternative: llama.cpp with ROCm

```bash
# Build llama.cpp with ROCm
cmake -B build -DGGML_HIPBLAS=ON
cmake --build build

# Serve with OpenAI-compatible API
./build/bin/llama-server -m model.gguf --port 8000
```

Then configure `argos_config.txt` to point to `http://localhost:8000/v1`.

---

## License

MIT
