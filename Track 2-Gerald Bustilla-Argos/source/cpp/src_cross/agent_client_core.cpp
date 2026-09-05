#include "agent_client_core.h"
#include "argos_tools_core.h"
#include "platform.h"
#include <sstream>
#include <cstring>
#include <thread>
#include <chrono>
#include <fstream>

// Find the closing quote of a JSON string value, skipping \" escaped quotes
static size_t findEndQuote(const std::string& s, size_t start) {
    size_t pos = start;
    while (pos < s.size()) {
        if (s[pos] == '\\') {
            pos += 2; // skip escaped char
            continue;
        }
        if (s[pos] == '"') return pos;
        pos++;
    }
    return std::string::npos;
}

// Extract "content" value from a JSON string, handling optional spaces and escaped quotes
// Also handles array format: "content":[{"type":"text","text":"..."}]
static std::string extractContent(const std::string& json) {
    // Try "content":"..." or "content": "..."
    size_t keyPos = json.find("\"content\"");
    while (keyPos != std::string::npos) {
        size_t colonPos = json.find(':', keyPos);
        if (colonPos == std::string::npos) break;
        
        // Skip whitespace after colon
        size_t valueStart = colonPos + 1;
        while (valueStart < json.size() && (json[valueStart] == ' ' || json[valueStart] == '\t')) {
            valueStart++;
        }
        
        if (valueStart >= json.size()) break;
        
        if (json[valueStart] == '"') {
            // String value: "content":"..."
            size_t contentStart = valueStart + 1;
            size_t endQuote = findEndQuote(json, contentStart);
            if (endQuote != std::string::npos) {
                std::string content = json.substr(contentStart, endQuote - contentStart);
                // Unescape
                std::string unescaped;
                for (size_t i = 0; i < content.size(); i++) {
                    if (content[i] == '\\' && i + 1 < content.size()) {
                        char next = content[i + 1];
                        if (next == 'n') unescaped += '\n';
                        else if (next == 'r') unescaped += '\r';
                        else if (next == 't') unescaped += '\t';
                        else if (next == '"') unescaped += '"';
                        else if (next == '\\') unescaped += '\\';
                        else if (next == '/') unescaped += '/';
                        else unescaped += content[i];
                        i++;
                    } else {
                        unescaped += content[i];
                    }
                }
                return unescaped;
            }
        } else if (json[valueStart] == '[') {
            // Array format: "content":[{"type":"text","text":"..."}]
            // Extract text from first object
            size_t textKey = json.find("\"text\"", valueStart);
            if (textKey != std::string::npos) {
                size_t textColon = json.find(':', textKey);
                if (textColon != std::string::npos) {
                    size_t textStart = textColon + 1;
                    while (textStart < json.size() && (json[textStart] == ' ' || json[textStart] == '\t')) {
                        textStart++;
                    }
                    if (textStart < json.size() && json[textStart] == '"') {
                        size_t contentStart = textStart + 1;
                        size_t endQuote = findEndQuote(json, contentStart);
                        if (endQuote != std::string::npos) {
                            std::string content = json.substr(contentStart, endQuote - contentStart);
                            // Unescape
                            std::string unescaped;
                            for (size_t i = 0; i < content.size(); i++) {
                                if (content[i] == '\\' && i + 1 < content.size()) {
                                    char next = content[i + 1];
                                    if (next == 'n') unescaped += '\n';
                                    else if (next == 'r') unescaped += '\r';
                                    else if (next == 't') unescaped += '\t';
                                    else if (next == '"') unescaped += '"';
                                    else if (next == '\\') unescaped += '\\';
                                    else if (next == '/') unescaped += '/';
                                    else unescaped += content[i];
                                    i++;
                                } else {
                                    unescaped += content[i];
                                }
                            }
                            return unescaped;
                        }
                    }
                }
            }
        }
        
        // Look for next occurrence of "content"
        keyPos = json.find("\"content\"", keyPos + 9);
    }
    return "";
}

// Extract "reasoning_content" value from a JSON string (DeepSeek reasoning model)
// Uses same logic as extractContent but searches for "reasoning_content" key
static std::string extractReasoningContent(const std::string& json) {
    size_t keyPos = json.find("\"reasoning_content\"");
    while (keyPos != std::string::npos) {
        size_t colonPos = json.find(':', keyPos);
        if (colonPos == std::string::npos) break;
        
        size_t valueStart = colonPos + 1;
        while (valueStart < json.size() && (json[valueStart] == ' ' || json[valueStart] == '\t')) {
            valueStart++;
        }
        
        if (valueStart >= json.size()) break;
        
        // Check for null: "reasoning_content":null
        if (json[valueStart] == 'n' && valueStart + 4 <= json.size() &&
            json.substr(valueStart, 4) == "null") {
            return "";
        }
        
        if (json[valueStart] == '"') {
            size_t contentStart = valueStart + 1;
            size_t endQuote = findEndQuote(json, contentStart);
            if (endQuote != std::string::npos) {
                std::string content = json.substr(contentStart, endQuote - contentStart);
                // Unescape
                std::string unescaped;
                for (size_t i = 0; i < content.size(); i++) {
                    if (content[i] == '\\' && i + 1 < content.size()) {
                        char next = content[i + 1];
                        if (next == 'n') unescaped += '\n';
                        else if (next == 'r') unescaped += '\r';
                        else if (next == 't') unescaped += '\t';
                        else if (next == '"') unescaped += '"';
                        else if (next == '\\') unescaped += '\\';
                        else if (next == '/') unescaped += '/';
                        else unescaped += content[i];
                        i++;
                    } else {
                        unescaped += content[i];
                    }
                }
                return unescaped;
            }
        }
        
        keyPos = json.find("\"reasoning_content\"", keyPos + 18);
    }
    return "";
}

// Minimal JSON string escaper
static std::string jsonEscape(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 8);
    for (char c : s) {
        switch (c) {
            case '"':  out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:   out += c;
        }
    }
    return out;
}

AgentClientCore::AgentClientCore() {
    initSystemPrompt();

    // Try loading config from file (overrides defaults)
    std::string configPath = argos::getAppDataDir() + "/argos_config.txt";
    std::ifstream configFile(configPath);
    if (configFile.is_open()) {
        std::string line;
        while (std::getline(configFile, line)) {
            size_t eq = line.find('=');
            if (eq == std::string::npos) continue;
            std::string key = line.substr(0, eq);
            std::string val = line.substr(eq + 1);
            if (key == "server_url") m_serverUrl = val;
            else if (key == "api_key") m_apiKey = val;
            else if (key == "model") m_model = val;
        }
        configFile.close();
        argos::log(("Loaded config from " + configPath).c_str());
    }
}

AgentClientCore::~AgentClientCore() {}

void AgentClientCore::setServerUrl(const std::string& url) { m_serverUrl = url; }
void AgentClientCore::setApiKey(const std::string& key) { m_apiKey = key; }
void AgentClientCore::setModel(const std::string& model) { m_model = model; }

void AgentClientCore::clearHistory() { m_history.clear(); }

void AgentClientCore::initSystemPrompt() {
    m_systemPrompt =
        "You are Argos, named after the faithful dog of Odysseus. "
        "You are a loyal, vigilant AI companion that lives on the user's device. "
        "You have a golden Spartan helmet and red eyes. "
        "You are direct, concise, and protective. "
        "You speak with the loyalty and devotion of a faithful companion.\n\n"
        "=== TOOL USAGE — CRITICAL RULES ===\n"
        "1. To call a tool, include: [TOOL:tool_name argument]\n"
        "2. The tag MUST start with [TOOL: and end with ]\n"
        "3. NEVER say you will check something and then NOT include a tool tag.\n"
        "4. Do NOT invent tool names.\n\n"
        "=== AVAILABLE TOOLS ===\n"
        "1. [TOOL:list_files <dirpath>] — List files in a directory.\n"
        "2. [TOOL:cmd <command>] — Execute a shell command.\n"
        "3. [TOOL:read <filepath>] — Read file contents.\n"
        "4. [TOOL:recall] — Load conversation memory.\n"
        "5. [TOOL:forget] — Clear conversation memory.\n"
        "6. [TOOL:open_url <url>] — Open a URL in the browser.\n"
        "7. [TOOL:screen_text] — Read all text currently visible on screen (any app, including browser).\n"
        "8. [TOOL:screen_active] — Get the currently focused app name, package, and recently used apps.\n"
        "9. [TOOL:click_text <text>] — Click on the first element containing the given text.\n"
        "10. [TOOL:type_text <text>] — Type text into the currently focused input field.\n"
        "11. [TOOL:scroll <up|down>] — Scroll the current screen up or down.\n"
        "12. [TOOL:ui_inspect] — Get the full UI element tree as JSON. Each element has id, text, desc, role, resId, clickable, editable, bounds. Use this to find specific buttons/fields.\n"
        "13. [TOOL:ui_click <id_or_text>] — Click an element by its numeric ID (from ui_inspect) or by text. Finds clickable parent automatically.\n"
        "14. [TOOL:ui_longpress <id_or_text>] — Long-press an element by ID or text.\n"
        "15. [TOOL:ui_type <elementId|text>] — Type text into a specific element by ID, or auto-find an input field. Use pipe separator: \"3|Hello world\"\n"
        "16. [TOOL:ui_action <elementId|action[|extra]>] — Perform any action: click, long_click, focus, set_text, scroll_forward, scroll_backward, select, expand, collapse. Example: \"5|set_text|Hello!\"\n"
        "17. [TOOL:ui_sequence <json_array>] — Execute multiple actions in sequence. Example: [{\"action\":\"click\",\"text\":\"Reply\"},{\"action\":\"type\",\"text\":\"Hello!\"},{\"action\":\"click\",\"text\":\"Send\"}]\n"
        "18. [TOOL:screenshot] — Take a text-based screenshot (saves screen content to file for analysis).\n"
        "19. [TOOL:notifications] — Open notification shade and read all notifications.\n"
        "20. [TOOL:notif_reply <index|message>] — Reply to a notification by index. Opens shade, finds Reply button, types message, clicks Send. Example: \"0|Hey, I'll get back to you!\"\n"
        "21. [TOOL:ui_tap_at <x,y>] — Tap ANY screen coordinate using gesture dispatch. Works even on apps with no accessibility nodes (canvas, games, image-only buttons). Example: \"540,960\"\n"
        "22. [TOOL:ui_longpress_at <x,y>] — Long press ANY screen coordinate using gesture dispatch. Example: \"540,960\"\n"
        "23. [TOOL:ui_smart_click <x,y>] — Smart click at coordinates: tries accessibility action first, falls back to gesture tap. Best of both worlds. Example: \"540,960\"\n"
        "24. [TOOL:ui_smart_longpress <x,y>] — Smart long press at coordinates: tries accessibility action first, falls back to gesture. Example: \"540,960\"\n"
        "25. [TOOL:ui_swipe <x1,y1,x2,y2[,duration]>] — Swipe gesture from one point to another. Used for custom scrolling, dragging, pull-to-refresh. Duration in ms (default 300). Example: \"540,1440,540,480,400\"\n"
        "26. [TOOL:ui_swipe_up] — Quick swipe up (scroll content down) at center of screen.\n"
        "27. [TOOL:ui_swipe_down] — Quick swipe down (scroll content up) at center of screen.\n"
        "28. [TOOL:ui_elements] — Get a quick list of ALL clickable/interactive elements with their text, bounds, and CENTER coordinates. Faster than ui_inspect for finding tappable buttons. Each element has \"center\":{\"x\":N,\"y\":N} for easy use with ui_tap_at.\n"
        "29. [TOOL:screen_size] — Get screen dimensions {\"width\":W,\"height\":H}. Use this to calculate tap coordinates.\n"
        "30. [TOOL:whisper_init <model_path>] — Initialize whisper.cpp speech-to-text engine with a GGML model file. Download ggml-tiny.en.bin (~75MB) from https://huggingface.co/ggerganov/whisper.cpp and place on device. Example: \"/sdcard/ggml-tiny.en.bin\"\n"
        "31. [TOOL:whisper_status] — Check if whisper is initialized and ready.\n"
        "32. [TOOL:voice_listen <duration_seconds>] — Record audio from microphone and transcribe to text using whisper.cpp. Default 5 seconds, max 30. Requires whisper_init first. Returns {\"text\":\"transcribed speech\"}.\n"
        "33. [TOOL:voice_transcribe <wav_file_path>] — Transcribe a WAV audio file to text using whisper.cpp.\n"
        "34. [TOOL:tts_speak <text>] — Speak text aloud using native Text-to-Speech (Android TextToSpeech engine). No GPL dependencies.\n"
        "35. [TOOL:tts_stop] — Stop any ongoing TTS playback.\n"
        "36. [TOOL:tts_status] — Check if TTS is currently speaking.\n\n"
        "=== BROWSER INTERACTION ===\n"
        "To search the web: use [TOOL:open_url https://www.google.com/search?q=your+query]\n"
        "Then use [TOOL:screen_text] to read the search results.\n"
        "Use [TOOL:click_text <link text>] to click on a search result.\n"
        "Use [TOOL:scroll down] to scroll down the page.\n"
        "Use [TOOL:screen_text] again to read more content.\n\n"
        "=== SOCIAL MEDIA & APP AUTOMATION ===\n"
        "To reply to messages on WhatsApp/Messenger/Instagram:\n"
        "1. Use [TOOL:notifications] to see incoming message notifications.\n"
        "2. Use [TOOL:notif_reply 0|Your reply here] to reply directly from notifications.\n"
        "Or to navigate within an app:\n"
        "1. Use [TOOL:ui_inspect] or [TOOL:ui_elements] to see all buttons and text fields.\n"
        "2. Use [TOOL:ui_click <text>] to tap on a chat or message.\n"
        "3. Use [TOOL:ui_type <text>] to type your reply in the input field.\n"
        "4. Use [TOOL:ui_click Send] to send the message.\n"
        "Or use [TOOL:ui_sequence] to do it all at once:\n"
        "[TOOL:ui_sequence [{\"action\":\"click\",\"text\":\"John Doe\"},{\"action\":\"type\",\"text\":\"Hey!\"},{\"action\":\"click\",\"text\":\"Send\"}]]\n\n"
        "=== ADVANCED UI AUTOMATION (Gesture-based) ===\n"
        "When accessibility actions don't work (image-only buttons, canvas apps, custom UI):\n"
        "1. Use [TOOL:ui_elements] to get all clickable elements with their CENTER coordinates.\n"
        "2. Use [TOOL:ui_smart_click <x,y>] to tap at those coordinates (tries accessibility first, then gesture).\n"
        "3. Use [TOOL:ui_swipe <x1,y1,x2,y2>] for custom scrolling, pull-to-refresh, or dragging.\n"
        "4. Use [TOOL:ui_swipe_up] or [TOOL:ui_swipe_down] for quick scrolling.\n"
        "5. Use [TOOL:ui_longpress_at <x,y>] to long-press on any element (e.g. to open context menu in WhatsApp/Telegram).\n"
        "6. Use [TOOL:screen_size] to get screen dimensions for calculating coordinates.\n"
        "TIP: ui_elements returns center:{x,y} for each button — use those with ui_smart_click for reliable tapping.\n"
        "TIP: For apps like Instagram/TikTok that use canvas or custom rendering, ui_swipe_up/ui_swipe_down work better than scroll.\n"
        "TIP: If ui_click fails, fall back to ui_smart_click with the element's center coordinates from ui_elements.\n\n"
        "=== VOICE INTERACTION (Speech-to-Text + Text-to-Speech) ===\n"
        "Voice input pipeline: whisper_init (load model) → voice_listen (record + transcribe) → use text as user input.\n"
        "Voice output: tts_speak <text> — speaks any text aloud using Android's native TTS engine.\n"
        "When the user says 'listen to me', 'record my voice', 'hear me', or 'voice input' — use [TOOL:voice_listen 5] to record 5 seconds of audio and transcribe it.\n"
        "When the user says 'speak', 'read aloud', 'say it', or 'tell me out loud' — use [TOOL:tts_speak <text>] to speak the response.\n"
        "If whisper is not initialized, tell the user to download a model file (ggml-tiny.en.bin ~75MB) from https://huggingface.co/ggerganov/whisper.cpp and use [TOOL:whisper_init <path>].\n\n"
        "Do NOT auto-trigger tools on simple messages. Only use tools when needed.\n"
        "User messages may include [Context: User is currently using <app>] — use this to give relevant answers.\n"
        "When the user asks 'what am I doing' or 'what app am I using', use [TOOL:screen_active] to get accurate info.\n"
        "When the user asks 'what do you see', 'what's on my screen', 'what's happening', 'read the screen', or similar — ALWAYS use [TOOL:screen_text] to read the screen, then summarize what you see.\n"
        "When the user asks 'who texted me' or 'check my messages' — use [TOOL:notifications] to read notifications.\n"
        "The screen_active tool returns 'name' (friendly app name), 'package', and 'recent_apps' (comma-separated app history).\n"
        "If primary model is unavailable, fallback model is used automatically.";
}

std::string AgentClientCore::buildJsonBody(const std::vector<ChatMessageCore>& messages, bool stream) {
    std::string body = "{\"model\":\"" + m_model + "\",\"stream\":" + (stream ? "true" : "false") + ",\"messages\":[";
    for (size_t i = 0; i < messages.size(); i++) {
        if (i > 0) body += ",";
        body += "{\"role\":\"" + jsonEscape(messages[i].role) + "\",\"content\":\"" + jsonEscape(messages[i].content) + "\"}";
    }
    body += "]}";
    return body;
}

std::string AgentClientCore::parseSSEChunk(const std::string& chunk, std::string* thoughts) {
    std::string result;
    std::string thoughtsAccum;
    size_t pos = 0;
    while (pos < chunk.size()) {
        size_t lineEnd = chunk.find('\n', pos);
        if (lineEnd == std::string::npos) lineEnd = chunk.size();
        std::string line = chunk.substr(pos, lineEnd - pos);
        // Trim \r for \r\n line endings
        if (!line.empty() && line.back() == '\r') line.pop_back();
        pos = lineEnd + 1;

        // Handle "data:" or "data: " (with optional space)
        if (line.substr(0, 5) == "data:") {
            size_t dataStart = 5;
            if (dataStart < line.size() && line[dataStart] == ' ') dataStart++;
            std::string data = line.substr(dataStart);
            
            if (data == "[DONE]") break;
            if (data.empty()) continue;
            
            // Extract reasoning content (thoughts) if requested
            if (thoughts) {
                std::string reasoning = extractReasoningContent(data);
                if (!reasoning.empty()) {
                    thoughtsAccum += reasoning;
                }
            }
            
            std::string content = extractContent(data);
            if (!content.empty()) {
                result += content;
            }
        }
    }
    if (thoughts) *thoughts = thoughtsAccum;
    return result;
}

bool AgentClientCore::hasToolTags(const std::string& response) {
    return response.find("[TOOL:") != std::string::npos;
}

std::string AgentClientCore::stripToolTags(const std::string& response) {
    std::string result = response;
    size_t pos = 0;
    while ((pos = result.find("[TOOL:", pos)) != std::string::npos) {
        size_t end = result.find(']', pos);
        if (end == std::string::npos) break;
        result.erase(pos, end - pos + 1);
    }
    // Also strip [Tool result:...] and [Tool Results]...
    pos = 0;
    while ((pos = result.find("[Tool ", pos)) != std::string::npos) {
        size_t end = result.find(']', pos);
        if (end == std::string::npos) break;
        result.erase(pos, end - pos + 1);
    }
    return result;
}

std::string AgentClientCore::executeTools(const std::string& response, ToolStatusCallbackCore toolStatusCallback) {
    std::string results;
    size_t pos = 0;
    while ((pos = response.find("[TOOL:", pos)) != std::string::npos) {
        size_t end = response.find(']', pos);
        if (end == std::string::npos) break;
        std::string tag = response.substr(pos + 6, end - pos - 6);
        // Parse tool name and args
        size_t spacePos = tag.find(' ');
        std::string toolName = (spacePos != std::string::npos) ? tag.substr(0, spacePos) : tag;
        std::string toolArg = (spacePos != std::string::npos) ? tag.substr(spacePos + 1) : "";

        // Notify status callback
        if (toolStatusCallback) {
            std::string status = "🔧 " + toolName;
            if (!toolArg.empty() && toolArg.size() < 80) status += ": " + toolArg;
            toolStatusCallback(status);
        }

        // Dispatch to tools core
        std::string result = argos_tools::dispatch_tool(toolName, toolArg);
        results += "[Tool result: " + toolName + "]\n" + result + "\n";

        // Notify completion
        if (toolStatusCallback) {
            std::string doneStatus = "✅ " + toolName + " done";
            toolStatusCallback(doneStatus);
        }

        pos = end + 1;
    }
    return results;
}

std::string AgentClientCore::chatWithMessages(const std::vector<ChatMessageCore>& messages) {
    std::string body = buildJsonBody(messages, false);
    std::string headers = "Authorization: Bearer " + m_apiKey + "\r\n";
    std::string url = m_serverUrl + "/chat/completions";
    argos::log(("POST " + url + " body_len=" + std::to_string(body.size())).c_str());
    std::string response = argos::httpPost(url, headers, body);
    argos::log(("HTTP response len=" + std::to_string(response.size())).c_str());
    if (response.size() > 0) {
        std::string preview = response.substr(0, response.size() > 500 ? 500 : response.size());
        argos::log(("Response: " + preview).c_str());
    }

    std::string content = extractContent(response);
    if (!content.empty()) {
        return content;
    }
    
    argos::log(("Failed to parse response, full response: " + response.substr(0, response.size() > 1000 ? 1000 : response.size())).c_str());
    return "[Error: Failed to parse response]";
}

std::string AgentClientCore::chatWithMessagesStreaming(const std::vector<ChatMessageCore>& messages,
                                                        StreamCallbackCore callback,
                                                        ThoughtsCallbackCore thoughtsCallback,
                                                        ToolStatusCallbackCore toolStatusCallback) {
    std::string body = buildJsonBody(messages, true);
    std::string headers = "Authorization: Bearer " + m_apiKey + "\r\n";
    std::string url = m_serverUrl + "/chat/completions";
    argos::log(("POST streaming " + url).c_str());

    std::string fullResponse;
    std::string fullThoughts;
    std::string leftover;

    std::string rawResponse = argos::httpPostStream(url, headers, body,
        [&](const std::string& chunk) -> bool {
            if (m_abort.load()) return false;
            std::string data = leftover + chunk;
            std::string thoughts;
            std::string delta = parseSSEChunk(data, &thoughts);
            if (!thoughts.empty()) {
                fullThoughts += thoughts;
                if (thoughtsCallback) thoughtsCallback(fullThoughts);
            }
            if (!delta.empty()) {
                fullResponse += delta;
                if (callback && !callback(delta)) return false;
            }
            // Keep incomplete lines
            size_t lastNewline = data.rfind('\n');
            if (lastNewline != std::string::npos) {
                leftover = data.substr(lastNewline + 1);
            } else {
                leftover = data;
            }
            return true;
        });

    if (!rawResponse.empty() && rawResponse.find("[Error:") == 0) {
        argos::log(("HTTP error in streaming: " + rawResponse.substr(0, 200)).c_str());
        return rawResponse;
    }

    if (fullResponse.empty()) {
        argos::log("Streaming response empty, falling back to non-streaming");
        return chatWithMessages(messages);
    }
    argos::log(("Streaming done, response len=" + std::to_string(fullResponse.size()) +
                " thoughts len=" + std::to_string(fullThoughts.size())).c_str());
    return fullResponse;
}

std::string AgentClientCore::chat(const std::string& userMessage) {
    m_abort.store(false);
    m_history.push_back({"user", userMessage});

    // Save to memory
    argos_tools::rag_memory_save_conversation("user", userMessage);

    std::string finalResponse;

    for (int iteration = 0; iteration < 8; iteration++) {
        if (m_abort.load()) break;

        std::vector<ChatMessageCore> messages;
        messages.push_back({"system", m_systemPrompt});
        for (const auto& msg : m_history) {
            messages.push_back(msg);
        }

        std::string response = chatWithMessages(messages);

        if (!hasToolTags(response)) {
            finalResponse = response;
            break;
        }

        std::string toolResults = executeTools(response);
        m_history.push_back({"assistant", response});
        m_history.push_back({"system", "[Tool Results]\n" + toolResults});
        m_history.push_back({"user", "Based on the tool results above, give me a clear answer."});
        finalResponse = stripToolTags(response);

        if (m_history.size() > 30) {
            m_history.erase(m_history.begin(), m_history.begin() + (m_history.size() - 30));
        }
    }

    m_history.push_back({"assistant", finalResponse});
    argos_tools::rag_memory_save_conversation("assistant", finalResponse);

    if (m_history.size() > 20) {
        m_history.erase(m_history.begin(), m_history.begin() + (m_history.size() - 20));
    }

    return finalResponse;
}

std::string AgentClientCore::chatStreaming(const std::string& userMessage, StreamCallbackCore callback,
                              ThoughtsCallbackCore thoughtsCallback,
                              ToolStatusCallbackCore toolStatusCallback) {
    m_abort.store(false);
    m_history.push_back({"user", userMessage});
    argos_tools::rag_memory_save_conversation("user", userMessage);

    std::string finalResponse;

    // Load memory on first message
    std::string memoryContext;
    if (m_history.size() <= 1) {
        std::string memory = argos_tools::rag_memory_load_conversation(5);
        if (memory.size() > 10 && memory.size() < 2000 && memory != "[]") {
            memoryContext = "[Recent conversation memory]\n" + memory + "\n[End of memory]";
        }
    }

    for (int iteration = 0; iteration < 8; iteration++) {
        if (m_abort.load()) break;

        std::vector<ChatMessageCore> messages;
        messages.push_back({"system", m_systemPrompt});
        if (iteration == 0 && !memoryContext.empty()) {
            messages.push_back({"system", memoryContext});
        }
        for (const auto& msg : m_history) {
            messages.push_back(msg);
        }

        // Always use streaming so the user sees follow-up responses after tool execution
        if (iteration > 0 && callback) {
            // Signal reset so accumulated text is cleared for the follow-up response
            callback("\x01RESET\x01");
        }
        finalResponse = chatWithMessagesStreaming(messages, callback, thoughtsCallback);

        if (!hasToolTags(finalResponse)) break;

        std::string toolResults = executeTools(finalResponse, toolStatusCallback);
        m_history.push_back({"assistant", finalResponse});
        m_history.push_back({"system", "[Tool Results]\n" + toolResults});
        m_history.push_back({"user", "Based on the tool results above, give me a clear answer."});

        if (m_history.size() > 30) {
            m_history.erase(m_history.begin(), m_history.begin() + (m_history.size() - 30));
        }
    }

    m_history.push_back({"assistant", finalResponse});
    argos_tools::rag_memory_save_conversation("assistant", finalResponse);

    if (m_history.size() > 20) {
        m_history.erase(m_history.begin(), m_history.begin() + (m_history.size() - 20));
    }

    return finalResponse;
}
