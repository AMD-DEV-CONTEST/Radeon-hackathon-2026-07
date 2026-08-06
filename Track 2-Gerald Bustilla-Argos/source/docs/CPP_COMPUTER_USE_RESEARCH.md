# C++ Computer Use Libraries — Research Report

This document catalogs existing C++ libraries and frameworks for computer use
(mouse, keyboard, screen capture, UI automation, clipboard) that could be
integrated into Aria to make the computer-use layer cross-platform and more
capable.

## Current State in Aria

Aria already has:
- `InputSimulator` (Win32 `SendInput` only) — mouse + keyboard
- `UIScanner` (Windows UIA only) — accessibility tree scanning
- `ComputerUse` — orchestrator (scan → AI → act → repeat)
- `BridgeServer` — HTTP bridge for Python tool integration

**Gap:** Everything is Windows-only. To support "any kind of C++" we need
cross-platform abstractions for input injection, screen capture, UI
accessibility, and clipboard.

---

## 1. Input Injection (Mouse + Keyboard)

### 1a. robot-cpp  ⭐ RECOMMENDED
- **Repo:** https://github.com/developer239/robot-cpp
- **Stars:** 26 | **License:** MIT | **Language:** C++23
- **Platforms:** macOS (Quartz), Windows (SendInput + GDI), Linux (XTest + XRandR)
- **Features:**
  - Mouse: move (absolute/smooth), click, double-click, drag, scroll (line/pixel)
  - Keyboard: press/release physical keys, modifier chords, type Unicode (layout-independent)
  - Screen capture at native resolution, PNG encoding
  - Window enumeration, bounds, z-order, activate
  - Record + replay global input with original timing
  - Capability reporting + typed errors (no silent failures)
  - DPI/HiDPI aware (logical vs physical coordinates)
  - Single `Session` object, no global state
- **Why it's the best fit:** Most complete, modern C++ design, correct
  handling of keyboard layouts and HiDPI, and includes screen capture +
  window management. Directly replaces our `InputSimulator` + adds
  screenshot capability.
- **Integration:** CMake FetchContent. Requires C++23 toolchain (Clang 18+,
  GCC 14+, MSVC 2022 17.10+). **Caveat:** C++23 requirement may need a
  compiler upgrade.

### 1b. hidtool
- **Repo:** https://github.com/JaderoChan/hidtool
- **License:** MIT | **Language:** C++11
- **Platforms:** Windows, macOS, Linux
- **Features:**
  - Keyboard: global event listening + input simulation
  - Mouse: move, click, wheel, drag + event listening
  - Singleton pattern, thread-safe
  - C/Python bindings available
- **Pros:** C++11 compatible (easy to integrate), clean API, both hook +
  simulate
- **Cons:** No screen capture, no window management, smaller community

### 1c. input_lite
- **Repo:** https://github.com/smasherprog/input_lite
- **License:** MIT | **Language:** C++
- **Platforms:** Windows, macOS, Linux
- **Features:** Keyboard + mouse event simulation, header-only style
- **Pros:** Same author as screen_capture_lite (they pair well)
- **Cons:** Basic API, no screen capture or window management

### 1d. inpctrl
- **Repo:** https://github.com/3443eee/inpctrl
- **License:** MIT | **Language:** C++ (header-only)
- **Platforms:** Windows, Linux (no macOS)
- **Features:** Press/hold/release keys, relative mouse move, key state
  tracking
- **Pros:** Header-only, very simple
- **Cons:** No macOS, no absolute mouse positioning, no scroll, no click

### 1e. FakeInput
- **Repo:** https://github.com/uiii/FakeInput
- **License:** MIT | **Language:** C++
- **Platforms:** Unix + Windows
- **Features:** Key press, mouse move, can execute external programs
- **Cons:** Old, minimal, no macOS

### 1f. IbInputSimulator (Windows-only, driver-level)
- **Repo:** https://github.com/Chaoses-Ib/IbInputSimulator
- **License:** MIT | **Language:** C/C++
- **Platforms:** Windows only
- **Features:** Driver-level input simulation (Logitech, Razer, MouClassInputInjection)
- **Use case:** Bypassing anti-cheat / games that block SendInput
- **Not relevant** for cross-platform, but useful for Windows gaming scenarios

---

## 2. Screen Capture

### 2a. screen_capture_lite  ⭐ RECOMMENDED
- **Repo:** https://github.com/smasherprog/screen_capture_lite
- **Stars:** 700+ | **License:** MIT | **Language:** C++
- **Platforms:** Windows 7+, macOS, Linux
- **Features:**
  - Capture all monitors or specific windows
  - Frame-changed callbacks (efficient for video)
  - Mouse cursor capture
  - Raw BGRA 32bpp output
  - No external dependencies (except X11 libs on Linux)
- **Integration:** CMake, pairs with input_lite (same author)
- **Why:** Best standalone screen capture for C++. Would let Aria take
  screenshots for vision-based AI agents.

### 2b. gpuview (Windows-only, GPU-native)
- **Repo:** https://github.com/OnlyTerp/gpuview
- **License:** MIT | **Language:** C# (not C++, but worth noting)
- **Features:** DXGI Desktop Duplication + dirty-rect change feed
- **Why notable:** 96% less image data than full-frame screenshots by
  only sending changed regions. Could inspire a similar C++ implementation
  for efficient agent vision.

---

## 3. UI Accessibility (Cross-Platform)

### 3a. Acacia  ⭐ RECOMMENDED
- **Repo:** https://igalia.github.io/acacia/
- **License:** BSD | **Language:** C++
- **Platforms:** Linux (AT-SPI), macOS (NSAccessibility), Windows (MSAA/UIA)
- **Features:**
  - Thin C++ wrapper around each platform's accessibility API
  - Cross-platform Accessibility Tree (CAT) API (experimental)
  - Python + Node.js bindings available
  - Used by WebKit/GTK accessibility testing
- **Why it's the best fit:** This is the only truly cross-platform
  accessibility library in C++. It would let us replace our Windows-only
  `UIScanner` with a cross-platform version.
- **Caveat:** CAT (cross-platform API) is experimental and OFF by default

### 3b. Microsoft UIAutomation (Windows-only)
- **Repo:** https://github.com/microsoft/microsoft-ui-uiautomation
- **License:** MIT | **Language:** C++/WinRT
- **Platforms:** Windows only
- **Features:** Remote Operations API, reduces cross-process call overhead
- **Status:** We already use UIA via our `UIScanner`. This library would
  improve performance but not add cross-platform support.

---

## 4. Full Computer-Use Frameworks

### 4a. computer.cpp  ⭐⭐ TOP RECOMMENDATION
- **Repo:** https://github.com/gobii-ai/computer.cpp
- **Stars:** 7 | **License:** MIT | **Language:** C++20
- **Platforms:** macOS (full), Linux + Windows (in progress)
- **Features:**
  - **Everything in one:** accessibility snapshots, screenshots, input
    injection, window management, clipboard, image utilities, LLM calls
  - Lua app definitions: wrap any desktop app as a semantic API
  - CLI + local HTTP API + MCP server (all from one definition)
  - Micro-agents: bounded keyboard/mouse/screenshot tools
  - Operations: sync/async, progress, cancellation, trace logs
  - Screenshot + artifact management
- **Why it's the top pick:** This is literally a C++ computer-use framework
  designed for AI agents. It does exactly what Aria's `ComputerUse` class
  does, but cross-platform and with MCP support.
- **Integration:** CMake 3.24+, C++20, vcpkg dependencies
- **Caveat:** macOS backend is most mature; Linux/Windows backends are
  still being developed. Only 7 stars (early project).

### 4b. os-ai-computer-use
- **Repo:** https://github.com/777genius/os-ai-computer-use
- **Stars:** 171 | **License:** Apache 2.0
- **Languages:** Python (58%), Dart (34%), C++ (3%)
- **Features:** 75% on OSWorld benchmark, OpenAI + Anthropic support
- **Not directly useful** as a C++ library (mostly Python/Dart), but
  valuable as a reference architecture.

### 4c. Forgeant (C++ agent framework, not computer-use)
- **Repo:** https://github.com/Jimdrews/forgeant
- **License:** MIT | **Language:** C++23
- **Features:** LLM agent framework with tool use, structured output,
  multi-provider (Anthropic, OpenAI, Ollama)
- **Relevance:** Could replace our `AgentClient` with a more capable
  C++-native agent loop. Not computer-use itself, but the agent
  orchestration layer.

---

## 5. Clipboard

### 5a. clip  ⭐ RECOMMENDED
- **Repo:** https://github.com/dacap/clip
- **Stars:** 700 | **License:** MIT | **Language:** C++
- **Platforms:** Windows, macOS, Linux (X11)
- **Features:** Copy/paste UTF-8 text, images, custom data formats
- **Why:** Most mature, well-maintained, used by Aseprite and other projects

### 5b. clipboard_lite
- **Repo:** https://github.com/smasherprog/clipboard_lite
- **License:** MIT | **Language:** C++
- **Platforms:** Windows, macOS, Linux
- **Features:** Text + image clipboard, callback-based, no dependencies
- **Pairs with:** screen_capture_lite + input_lite (same author)

---

## 6. Recommendation Summary

### For maximum capability with minimal effort (Windows stays primary):

| Layer | Keep | Add |
|-------|------|-----|
| Input injection | Our `InputSimulator` (Win32) | — |
| UI scanning | Our `UIScanner` (UIA) | — |
| Screen capture | — | `screen_capture_lite` (FetchContent) |
| Clipboard | — | `clip` (FetchContent) |
| Agent loop | Our `ComputerUse` | — |

This adds screenshot + clipboard capabilities without changing existing code.

### For full cross-platform support:

| Layer | Replace with | Library |
|-------|-------------|---------|
| Input injection | Cross-platform | `robot-cpp` (C++23) or `hidtool` (C++11) |
| Screen capture | Cross-platform | `screen_capture_lite` or `robot-cpp` built-in |
| UI scanning | Cross-platform | `Acacia` (CAT API) |
| Clipboard | Cross-platform | `clip` |
| Agent loop | Optional upgrade | `computer.cpp` concepts or `Forgeant` |

### For the most complete solution (ambitious):

Adopt **computer.cpp** as the entire computer-use layer. It already
implements: accessibility, screenshots, input, window management,
clipboard, MCP server, and micro-agents — all in C++20. We'd wrap our
Aria robot UI around it and use its HTTP/MCP interfaces for the Python
tool integration.

---

## 7. Integration Path (Pragmatic)

### Phase 1: Add screen capture (immediate value)
```cmake
# CMakeLists.txt
FetchContent_Declare(screen_capture_lite
    GIT_REPOSITORY https://github.com/smasherprog/screen_capture_lite.git
    GIT_TAG master)
FetchContent_MakeAvailable(screen_capture_lite)
target_link_libraries(aria_desktop PRIVATE ScreenCaptureLite)
```
Add `Screenshot()` to `InputSimulator` or a new `ScreenCapture` class.
Expose via the bridge server: `{"action":"screenshot","path":"..."}`.

### Phase 2: Add clipboard
```cmake
FetchContent_Declare(clip
    GIT_REPOSITORY https://github.com/dacap/clip.git
    GIT_TAG main)
FetchContent_MakeAvailable(clip)
target_link_libraries(aria_desktop PRIVATE clip)
```
Add `GetClipboard()` / `SetClipboard()` to the bridge.

### Phase 3: Cross-platform input (when macOS/Linux needed)
Replace `InputSimulator` internals with `robot-cpp` or `hidtool` behind
the same API. Our `InputSimulator` header stays the same; only the `.cpp`
changes per-platform.

### Phase 4: Cross-platform UI scanning (when needed)
Wrap `Acacia` behind our `UIScanner` interface. On Windows it uses UIA
(our existing code), on macOS it uses NSAccessibility, on Linux AT-SPI.

### Phase 5: Full computer.cpp integration (optional, ambitious)
If computer.cpp matures on Windows/Linux, adopt it as the entire
computer-use backend and reduce our custom code to the Aria robot UI +
voice layer.
