#pragma once
#include <string>

// Cross-platform Argos tools — platform-agnostic subset
// Windows-specific tools (screen_apps, ui_*, browser) are stubbed on non-Windows.

namespace argos_tools {

// Dispatch a tool by name. Returns result string (JSON or text).
std::string dispatch_tool(const std::string& tool_name, const std::string& args);

// Memory persistence (JSONL file in app data dir)
bool rag_memory_save_conversation(const std::string& role, const std::string& content);
std::string rag_memory_load_conversation(size_t max_messages);

} // namespace argos_tools
