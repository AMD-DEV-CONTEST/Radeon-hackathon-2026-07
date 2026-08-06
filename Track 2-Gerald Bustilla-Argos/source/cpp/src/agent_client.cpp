#include "agent_client.h"
#include "argos_tools.h"
#include <windows.h>
#include <winhttp.h>
#include <string>
#include <sstream>
#include <vector>
#include <fstream>
#include <shellapi.h>
#include <cstdio>
#include <ctime>

#pragma comment(lib, "winhttp.lib")

// Minimal JSON string escaper
static std::wstring JsonEscape(const std::wstring& s) {
    std::wstring out;
    out.reserve(s.size() + 8);
    for (wchar_t c : s) {
        switch (c) {
            case L'"':  out += L"\\\""; break;
            case L'\\': out += L"\\\\"; break;
            case L'\n': out += L"\\n";  break;
            case L'\r': out += L"\\r";  break;
            case L'\t': out += L"\\t";  break;
            default:
                if (c < 0x20) {
                    wchar_t buf[8];
                    swprintf_s(buf, L"\\u%04x", (unsigned)c);
                    out += buf;
                } else {
                    out += c;
                }
        }
    }
    return out;
}

// Extract the value for a given key from a flat JSON string.
// Handles nested quotes minimally — good enough for OpenAI-style responses.
static std::wstring ExtractJsonString(const std::string& json, const std::string& key) {
    // Try both "key":" and "key": " (with optional spaces after colon)
    std::string needle = "\"" + key + "\":\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) {
        // Try with space: "key": "
        needle = "\"" + key + "\": \"";
        pos = json.find(needle);
        if (pos == std::string::npos) return L"";
    }
    pos += needle.size();
    std::string result;
    while (pos < json.size() && json[pos] != '"') {
        if (json[pos] == '\\' && pos + 1 < json.size()) {
            char next = json[pos + 1];
            if (next == 'n')      result += '\n';
            else if (next == 'r') result += '\r';
            else if (next == 't') result += '\t';
            else if (next == '"') result += '"';
            else if (next == '\\') result += '\\';
            else if (next == '/') result += '/';
            else                  result += next;
            pos += 2;
        } else {
            result += json[pos];
            pos++;
        }
    }
    // Convert UTF-8 to wide string
    std::wstring wide;
    int wlen = MultiByteToWideChar(CP_UTF8, 0, result.c_str(), (int)result.size(), nullptr, 0);
    if (wlen > 0) {
        wide.resize(wlen);
        MultiByteToWideChar(CP_UTF8, 0, result.c_str(), (int)result.size(), &wide[0], wlen);
    }
    return wide;
}

// Convert wide string to UTF-8
static std::string WideToUtf8(const std::wstring& ws) {
    std::string utf8;
    int len = WideCharToMultiByte(CP_UTF8, 0, ws.c_str(), (int)ws.size(), nullptr, 0, nullptr, nullptr);
    if (len > 0) {
        utf8.resize(len);
        WideCharToMultiByte(CP_UTF8, 0, ws.c_str(), (int)ws.size(), &utf8[0], len, nullptr, nullptr);
    }
    return utf8;
}

// Error logging helper — writes timestamped messages to argos_error.log
static void LogError(const std::string& message) {
    FILE* logFile = nullptr;
    fopen_s(&logFile, "argos_error.log", "a");
    if (logFile) {
        time_t now = time(nullptr);
        struct tm tm_buf;
        localtime_s(&tm_buf, &now);
        char timeBuf[64];
        strftime(timeBuf, sizeof(timeBuf), "%Y-%m-%d %H:%M:%S", &tm_buf);
        fprintf(logFile, "[%s] %s\n", timeBuf, message.c_str());
        fclose(logFile);
    }
}

static void LogErrorW(const std::wstring& message) {
    LogError(WideToUtf8(message));
}

AgentClient::AgentClient() {
    InitSystemPrompt();
}

AgentClient::~AgentClient() {}

void AgentClient::SetServerUrl(const std::wstring& url) {
    m_serverUrl = url;
}

void AgentClient::SetApiKey(const std::wstring& key) {
    m_apiKey = key;
}

void AgentClient::SetModel(const std::wstring& model) {
    m_model = model;
}

void AgentClient::SetFallbackModel(const std::wstring& model) {
    m_fallbackModel = model;
}

void AgentClient::SetVisionModel(const std::wstring& model) {
    m_visionModel = model;
}

bool AgentClient::IsVisionTool(const std::wstring& toolName) {
    return toolName == L"screen_ocr" ||
           toolName == L"screen_capture" ||
           toolName == L"browser_screenshot" ||
           toolName == L"screenshot";
}

bool AgentClient::IsServerAlive() {
    URL_COMPONENTS urlComp = {};
    urlComp.dwStructSize = sizeof(urlComp);
    wchar_t hostName[256] = {0};
    wchar_t urlPath[256] = {0};
    urlComp.lpszHostName = hostName;
    urlComp.dwHostNameLength = 255;
    urlComp.lpszUrlPath = urlPath;
    urlComp.dwUrlPathLength = 255;

    std::wstring fullUrl = m_serverUrl + L"/chat/completions";
    WinHttpCrackUrl(fullUrl.c_str(), (DWORD)fullUrl.length(), 0, &urlComp);

    HINTERNET hSession = WinHttpOpen(L"Argos/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                                     WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!hSession) return false;

    HINTERNET hConnect = WinHttpConnect(hSession, hostName, urlComp.nPort, 0);
    if (!hConnect) { WinHttpCloseHandle(hSession); return false; }

    DWORD flags = (urlComp.nScheme == INTERNET_SCHEME_HTTPS) ? WINHTTP_FLAG_SECURE : 0;
    HINTERNET hRequest = WinHttpOpenRequest(hConnect, L"GET", urlPath,
                                             nullptr, WINHTTP_NO_REFERER,
                                             WINHTTP_DEFAULT_ACCEPT_TYPES, flags);
    if (!hRequest) { WinHttpCloseHandle(hConnect); WinHttpCloseHandle(hSession); return false; }

    BOOL bResult = WinHttpSendRequest(hRequest, WINHTTP_NO_ADDITIONAL_HEADERS, 0,
                                       WINHTTP_NO_REQUEST_DATA, 0, 0, 0);
    if (bResult) {
        bResult = WinHttpReceiveResponse(hRequest, nullptr);
    }

    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);

    return bResult == TRUE;
}

void AgentClient::InitSystemPrompt() {
    m_systemPrompt =
        L"You are Argos, named after the faithful dog of Odysseus. "
        L"You are a loyal, vigilant AI companion that lives on the user's desktop. "
        L"You are always faithful, always watching, always ready to help. "
        L"You have a golden Spartan helmet and red eyes. "
        L"You are direct, concise, and protective. "
        L"You speak with the loyalty and devotion of a faithful companion. "
        L"\n\n=== TOOL USAGE — CRITICAL RULES ===\n"
        L"1. To call a tool, you MUST include the EXACT tag format: [TOOL:tool_name argument]\n"
        L"2. The tag MUST start with [TOOL: (uppercase) and end with ]\n"
        L"3. Example: [TOOL:screen_apps] or [TOOL:list_files C:\\Users\\geral\\Documents]\n"
        L"4. You can include explanatory text BEFORE the tool tag. Example: 'Let me check your open apps. [TOOL:screen_apps]'\n"
        L"5. After a tool executes, you will receive the results as a system message. Use those results to answer the user.\n"
        L"6. NEVER say you will check something and then NOT include a tool tag. If you say 'Let me check...', you MUST include the tool tag in the SAME response.\n"
        L"7. Do NOT invent or hallucinate tool names. Use ONLY the tools listed below.\n"
        L"8. When the user asks about open tabs, windows, or apps, use [TOOL:screen_apps] to list all open windows.\n"
        L"9. When the user asks about files in a folder, use [TOOL:list_files <path>] to list directory contents.\n"
        L"10. Tool names are case-insensitive but must match the listed names exactly (e.g. screen_apps, not SCREEN_APP).\n"
        L"\n\n=== PERSISTENT MEMORY ==="
        L"\nAll conversations are saved to persistent memory. "
        L"If the user asks about something you discussed before, use [TOOL:recall] to load recent memory.\n"
        L"\n\n=== PERMISSION CONTROL ===\n"
        L"Destructive tools (write, run, lock) require user permission before execution. "
        L"The user will be shown a confirmation dialog before these tools run. "
        L"If the user denies permission, respect their decision and suggest alternatives."
        L"\n\n=== PRIVACY ===\n"
        L"Screen context is automatically filtered to redact sensitive data (passwords, tokens, "
        L"credit card numbers) before you see it. This protects the user's privacy."
        L"\n\nYou have the following tools available. "
        L"To use a tool, include a [TOOL:...] tag in your response:\n"
        L"\n--- System Tools ---\n"
        L"1. [TOOL:open <path>] — Open a file, folder, or URL.\n"
        L"2. [TOOL:run <command>] — Execute a system command (notepad, calc, explorer).\n"
        L"3. [TOOL:read <filepath>] — Read file contents.\n"
        L"4. [TOOL:write <filepath> | <content>] — Write to a file.\n"
        L"5. [TOOL:search <query>] — Open browser and search Google.\n"
        L"6. [TOOL:cmd <command>] — Execute a shell command and return output.\n"
        L"7. [TOOL:list_files <dirpath>] — List files/subdirs in a directory. Returns JSON.\n"
        L"8. [TOOL:screenshot] — Take a screenshot.\n"
        L"9. [TOOL:clipboard <text>] — Copy text to clipboard.\n"
        L"10. [TOOL:volume <level>] — Set system volume (0-100).\n"
        L"11. [TOOL:lock] — Lock workstation.\n"
        L"12. [TOOL:notify <message>] — Show a notification.\n"
        L"\n--- Screen & Window Tools ---\n"
        L"13. [TOOL:screen_apps] — List ALL open application windows (Chrome tabs, apps, etc.).\n"
        L"14. [TOOL:screen_active] — Get the currently focused/active application.\n"
        L"15. [TOOL:screen_ocr] — Extract text from screen using OCR.\n"
        L"16. [TOOL:screen_capture <path>] — Capture screen as image.\n"
        L"17. [TOOL:ui_windows] — List all open UI windows.\n"
        L"18. [TOOL:ui_search <text>] — Search UI elements by text.\n"
        L"19. [TOOL:ui_click <element_id>] — Click a UI element.\n"
        L"20. [TOOL:ui_type <text>] — Type text into focused element.\n"
        L"\n--- Browser Tools ---\n"
        L"21. [TOOL:browser_navigate <url>] — Open a URL in browser.\n"
        L"22. [TOOL:browser_content] — Get current page text content.\n"
        L"23. [TOOL:browser_links] — Get all links on current page.\n"
        L"24. [TOOL:browser_search <query>] — Search YouTube for a query (opens results page).\n"
        L"25. [TOOL:browser_click_text <text>] — Click on text visible on screen (e.g. a video title).\n"
        L"26. [TOOL:browser_type_active <text>] — Type text into the currently focused element.\n"
        L"27. [TOOL:browser_press_key <key>] — Press a keyboard key (enter, tab, escape, etc.).\n"
        L"\n--- Computer Use Tools (direct mouse & keyboard control) ---\n"
        L"28. [TOOL:mouse_click <x>,<y>] — Left-click at screen coordinates.\n"
        L"29. [TOOL:mouse_right_click <x>,<y>] — Right-click at screen coordinates.\n"
        L"30. [TOOL:mouse_double_click <x>,<y>] — Double-click at screen coordinates.\n"
        L"31. [TOOL:mouse_move <x>,<y>] — Move mouse to screen coordinates.\n"
        L"32. [TOOL:keyboard_type <text>] — Type text as if pressing each key.\n"
        L"33. [TOOL:keyboard_key <key>] — Press a single key (enter, tab, escape, f5, etc.).\n"
        L"34. [TOOL:keyboard_hotkey <keys>] — Press key combination (e.g. ctrl+c, shift+tab, alt+f4).\n"
        L"\n--- File Search & RAG Tools (call ONLY when needed) ---\n"
        L"35. [TOOL:rag_search <query>] — Search synced folders for content.\n"
        L"36. [TOOL:search_files <dirpath>|<query>] — Search text content in a directory.\n"
        L"37. [TOOL:search_filename <dirpath>|<pattern>] — Search filenames by pattern.\n"
        L"38. [TOOL:index <dirpath>] — Index a directory for searching.\n"
        L"39. [TOOL:full_map <dirpath>] — Get JSON map of files and content.\n"
        L"40. [TOOL:recall] — Load recent conversation memory.\n"
        L"41. [TOOL:forget] — Clear conversation memory.\n"
        L"\n--- Voice & Speech Tools (whisper.cpp + Windows SAPI TTS) ---\n"
        L"42. [TOOL:whisper_init <model_path>] — Initialize whisper.cpp speech-to-text with a GGML model. Download ggml-tiny.en.bin (~75MB) from https://huggingface.co/ggerganov/whisper.cpp\n"
        L"43. [TOOL:whisper_status] — Check if whisper is initialized and ready.\n"
        L"44. [TOOL:voice_listen <duration_seconds>] — Record from microphone and transcribe to text. Default 5s, max 30s.\n"
        L"45. [TOOL:voice_transcribe <wav_file_path>] — Transcribe a WAV audio file to text.\n"
        L"46. [TOOL:tts_speak <text>] — Speak text aloud using Windows SAPI voice.\n"
        L"47. [TOOL:tts_stop] — Stop any ongoing TTS playback.\n"
        L"48. [TOOL:tts_status] — Check if TTS is currently speaking.\n"
        L"\n--- Key Usage Notes ---\n"
        L"- For 'what tabs are open': use [TOOL:screen_apps]\n"
        L"- For 'list files in <folder>': use [TOOL:list_files <path>]\n"
        L"- For web search: use [TOOL:search <query>]\n"
        L"- For YouTube: use [TOOL:browser_search <query>] to search, then [TOOL:browser_click_text <video_title>] to play a video.\n"
        L"- For multi-step browser tasks (open + search + play): call tools SEQUENTIALLY in separate responses. The tool loop will continue automatically.\n"
        L"- Example: 'Open YouTube and play 2026 reggae songs' → Step 1: [TOOL:browser_search 2026 reggae songs] → Step 2: [TOOL:browser_click_text reggae] (click first video)\n"
        L"- If browser_click_text fails, use [TOOL:screen_capture] to see the screen, then [TOOL:mouse_click x,y] to click at the right position.\n"
        L"- Use [TOOL:keyboard_hotkey ctrl+l] to focus the browser address bar, then [TOOL:keyboard_type <url>] and [TOOL:keyboard_key enter] to navigate.\n"
        L"- Use [TOOL:keyboard_key tab] to move between focusable elements on a page, then [TOOL:keyboard_key enter] to activate.\n"
        L"- Do NOT auto-trigger RAG on simple messages. Only use RAG tools when user asks about files in synced folders.\n"
        L"- Voice input: when user says 'listen', 'record my voice', 'hear me' → use [TOOL:voice_listen 5] to record+transcribe.\n"
        L"- Voice output: when user says 'speak', 'read aloud', 'say it' → use [TOOL:tts_speak <text>] to speak response.\n"
        L"- If whisper not initialized, tell user to download ggml-tiny.en.bin and use [TOOL:whisper_init <path>].\n"
        L"- If primary model is unavailable, fallback model (MiniCPM5-1B) is used automatically.";
}

void AgentClient::ClearHistory() {
    m_history.clear();
}

std::wstring AgentClient::Chat(const std::wstring& userMessage) {
    try {
    // Add user message to history
    m_history.push_back({L"user", userMessage});

    // RAG is NOT auto-triggered. The AI agent will explicitly call RAG tools
    // (rag_search, search_files, etc.) when it needs information from synced folders.

    std::wstring finalResponse;

    // Tool loop: AI may call tools, we execute them and send results back
    for (int iteration = 0; iteration < 8; iteration++) {
        // Build full message list: system prompt + history
        std::vector<ChatMessage> messages;
        messages.push_back({L"system", m_systemPrompt});
        for (const auto& msg : m_history) {
            messages.push_back(msg);
        }

        std::wstring response = ChatWithMessages(messages);

        // Check if the response contains tool calls
        if (!HasToolTags(response)) {
            // No tools — this is the final answer
            finalResponse = response;
            break;
        }

        // Execute the tools and collect results
        m_executingTools.store(true);
        std::wstring toolResults = ExecuteTools(response);
        m_executingTools.store(false);

        // Show the user what Argos is doing (clean text without tool tags)
        std::wstring cleanResponse = StripToolTags(response);

        // Add the assistant's intermediate response to history
        m_history.push_back({L"assistant", response});

        // Add tool results as a user message so the AI can use them
        std::wstring toolFeedback =
            L"Tool execution results:\n" + toolResults +
            L"\n\nBased on these results, please give the user a clear, natural answer. "
            L"Do NOT repeat the raw data. Just tell them what they asked in a friendly way. "
            L"If you need to perform another action (like clicking a link or typing text), "
            L"call another tool — but do NOT say 'let me check' without including a tool tag.";
        m_history.push_back({L"user", toolFeedback});

        // Save the clean intermediate response as the final for now
        // (will be overwritten if the next iteration gives a better answer)
        finalResponse = cleanResponse;

        // Keep history manageable
        if (m_history.size() > 30) {
            m_history.erase(m_history.begin(), m_history.begin() + (m_history.size() - 30));
        }

        // Loop continues — AI will get tool results and give final answer
    }

    // Add final response to history
    m_history.push_back({L"assistant", finalResponse});

    // Save AI response to persistent memory
    argos_tools::rag_memory_save_conversation("assistant", WideToUtf8(finalResponse));

    // Keep history manageable (last 20 messages + system)
    if (m_history.size() > 20) {
        m_history.erase(m_history.begin(), m_history.begin() + (m_history.size() - 20));
    }

    return finalResponse;
    } catch (...) {
        return L"[Error: chat failed]";
    }
}

std::wstring AgentClient::ChatWithMessages(const std::vector<ChatMessage>& messages) {
    try {
        // Try primary model first
        std::wstring result = ChatWithModel(messages, m_model);

        // If primary failed, try fallback model
        if (result.find(L"[Error:") == 0 || result.find(L"[API Error:") == 0) {
            // Primary model failed — try fallback
            result = ChatWithModel(messages, m_fallbackModel);
        }

        return result;
    } catch (...) {
        return L"[Error: chat request failed]";
    }
}

std::wstring AgentClient::ChatWithModel(const std::vector<ChatMessage>& messages, const std::wstring& model) {
    // Build JSON body with full message array
    std::wstring jsonBody = L"{\"model\":\"" + model + L"\",\"messages\":[";
    for (size_t i = 0; i < messages.size(); i++) {
        if (i > 0) jsonBody += L",";
        jsonBody += L"{\"role\":\"" + messages[i].role + L"\",\"content\":\"" +
                     JsonEscape(messages[i].content) + L"\"}";
    }
    jsonBody += L"]}";

    std::string bodyUtf8 = WideToUtf8(jsonBody);

    // Parse server URL
    URL_COMPONENTS urlComp = {};
    urlComp.dwStructSize = sizeof(urlComp);
    wchar_t hostName[256] = {0};
    wchar_t urlPath[512] = {0};
    urlComp.lpszHostName = hostName;
    urlComp.dwHostNameLength = 255;
    urlComp.lpszUrlPath = urlPath;
    urlComp.dwUrlPathLength = 511;

    std::wstring fullUrl = m_serverUrl + L"/chat/completions";
    if (!WinHttpCrackUrl(fullUrl.c_str(), (DWORD)fullUrl.length(), 0, &urlComp)) {
        return L"[Error: invalid server URL]";
    }

    HINTERNET hSession = WinHttpOpen(L"Argos/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                                     WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!hSession) return L"[Error: WinHttpOpen failed]";

    // Set timeouts: 60s resolve, 60s connect, 120s send, 120s receive
    WinHttpSetTimeouts(hSession, 60000, 60000, 120000, 120000);

    HINTERNET hConnect = WinHttpConnect(hSession, hostName, urlComp.nPort, 0);
    if (!hConnect) { WinHttpCloseHandle(hSession); return L"[Error: WinHttpConnect failed]"; }

    DWORD flags = (urlComp.nScheme == INTERNET_SCHEME_HTTPS) ? WINHTTP_FLAG_SECURE : 0;
    HINTERNET hRequest = WinHttpOpenRequest(hConnect, L"POST", urlPath,
                                             nullptr, WINHTTP_NO_REFERER,
                                             WINHTTP_DEFAULT_ACCEPT_TYPES, flags);
    if (!hRequest) {
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return L"[Error: WinHttpOpenRequest failed]";
    }

    // Build headers
    std::wstring headers = L"Authorization: Bearer " + m_apiKey + L"\r\n"
                           L"Content-Type: application/json\r\n";

    // Retry up to 3 times on network failure
    BOOL bResult = FALSE;
    for (int attempt = 0; attempt < 3; attempt++) {
        bResult = WinHttpSendRequest(hRequest, headers.c_str(), (DWORD)headers.size(),
                                       (LPVOID)bodyUtf8.data(), (DWORD)bodyUtf8.size(),
                                       (DWORD)bodyUtf8.size(), 0);
        if (!bResult) {
            Sleep(1000 * (attempt + 1)); // wait before retry
            continue;
        }

        bResult = WinHttpReceiveResponse(hRequest, nullptr);
        if (bResult) break; // success

        Sleep(1000 * (attempt + 1)); // wait before retry
    }

    if (!bResult) {
        WinHttpCloseHandle(hRequest);
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return L"[Error: Could not reach AI server after 3 attempts. Check your connection.]";
    }

    // Read response body
    std::string responseStr;
    DWORD bytesAvailable = 0;
    while (WinHttpQueryDataAvailable(hRequest, &bytesAvailable) && bytesAvailable > 0) {
        std::vector<char> buffer(bytesAvailable + 1, 0);
        DWORD bytesRead = 0;
        if (WinHttpReadData(hRequest, buffer.data(), bytesAvailable, &bytesRead) && bytesRead > 0) {
            responseStr.append(buffer.data(), bytesRead);
        } else {
            break;
        }
    }

    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);

    if (responseStr.empty()) {
        return L"[Error: empty response from server]";
    }

    // Extract choices[0].message.content from JSON
    std::wstring content = ExtractJsonString(responseStr, "content");
    if (content.empty()) {
        // Try reasoning_content as fallback (some models return only reasoning)
        content = ExtractJsonString(responseStr, "reasoning_content");
    }
    if (content.empty()) {
        // Log raw response for debugging
        FILE* logFile = nullptr;
        fopen_s(&logFile, "argos_error.log", "a");
        if (logFile) {
            time_t now = time(nullptr);
            struct tm tm_buf;
            localtime_s(&tm_buf, &now);
            char timeBuf[64];
            strftime(timeBuf, sizeof(timeBuf), "%Y-%m-%d %H:%M:%S", &tm_buf);
            fprintf(logFile, "[%s] Parse failed. Raw response (first 500 chars): %.500s\n", timeBuf, responseStr.c_str());
            fclose(logFile);
        }
        // Try to extract error message
        std::wstring errMsg = ExtractJsonString(responseStr, "message");
        if (!errMsg.empty()) return L"[API Error: " + errMsg + L"]";
        return L"[Error: could not parse response]";
    }

    return content;
}

// ── SSE Streaming Implementation ──

// Parse a single SSE data line and extract content delta
std::wstring AgentClient::ParseSSEChunk(const std::string& chunk) {
    // SSE format: "data: {json}\n\n"
    // We look for "data: " prefix, parse JSON, extract choices[0].delta.content
    std::wstring result;

    size_t pos = 0;
    while (pos < chunk.size()) {
        // Find "data: " prefix
        size_t dataPos = chunk.find("data: ", pos);
        if (dataPos == std::string::npos) break;

        size_t lineStart = dataPos + 6; // skip "data: "
        size_t lineEnd = chunk.find('\n', lineStart);
        if (lineEnd == std::string::npos) lineEnd = chunk.size();

        std::string jsonLine = chunk.substr(lineStart, lineEnd - lineStart);

        // Check for [DONE] marker
        if (jsonLine.find("[DONE]") != std::string::npos) break;

        // Extract "content":"..." from the JSON delta
        // Look for "delta":{"content":"..." or "content":"..."
        size_t contentPos = jsonLine.find("\"content\":\"");
        if (contentPos != std::string::npos) {
            size_t valStart = contentPos + 11;
            size_t valEnd = valStart;
            // Parse with escape handling
            while (valEnd < jsonLine.size()) {
                if (jsonLine[valEnd] == '\\' && valEnd + 1 < jsonLine.size()) {
                    valEnd += 2;
                } else if (jsonLine[valEnd] == '"') {
                    break;
                } else {
                    valEnd++;
                }
            }
            if (valEnd <= jsonLine.size()) {
                std::string contentStr = jsonLine.substr(valStart, valEnd - valStart);
                // Unescape JSON string
                std::string unescaped;
                for (size_t i = 0; i < contentStr.size(); i++) {
                    if (contentStr[i] == '\\' && i + 1 < contentStr.size()) {
                        char next = contentStr[i + 1];
                        if (next == 'n') unescaped += '\n';
                        else if (next == 'r') unescaped += '\r';
                        else if (next == 't') unescaped += '\t';
                        else if (next == '"') unescaped += '"';
                        else if (next == '\\') unescaped += '\\';
                        else if (next == '/') unescaped += '/';
                        else { unescaped += '\\'; unescaped += next; }
                        i++;
                    } else {
                        unescaped += contentStr[i];
                    }
                }
                // Convert to wide string
                int wlen = MultiByteToWideChar(CP_UTF8, 0, unescaped.c_str(),
                                               (int)unescaped.size(), nullptr, 0);
                if (wlen > 0) {
                    std::wstring wstr(wlen, 0);
                    MultiByteToWideChar(CP_UTF8, 0, unescaped.c_str(),
                                       (int)unescaped.size(), &wstr[0], wlen);
                    result += wstr;
                }
            }
        }

        pos = lineEnd + 1;
    }

    return result;
}

// Streaming version of ChatWithMessages — sends with stream:true, parses SSE chunks
// Tries primary model, falls back to fallback model on failure
std::wstring AgentClient::ChatWithMessagesStreaming(const std::vector<ChatMessage>& messages, StreamCallback callback) {
    m_abort.store(false);

    try {
        // Try primary model first
        std::wstring result = ChatWithMessagesStreamingModel(messages, callback, m_model);

        // If primary failed, try fallback model
        if (result.find(L"[Error:") == 0 || result.find(L"[API Error:") == 0) {
            result = ChatWithMessagesStreamingModel(messages, callback, m_fallbackModel);
        }

        return result;
    } catch (...) {
        return L"[Error: streaming chat request failed]";
    }
}

// Internal: streaming chat with a specific model
std::wstring AgentClient::ChatWithMessagesStreamingModel(const std::vector<ChatMessage>& messages, StreamCallback callback, const std::wstring& model) {
    // Build JSON body with stream:true
    std::wstring jsonBody = L"{\"model\":\"" + model + L"\",\"stream\":true,\"messages\":[";
    for (size_t i = 0; i < messages.size(); i++) {
        if (i > 0) jsonBody += L",";
        jsonBody += L"{\"role\":\"" + messages[i].role + L"\",\"content\":\"" +
                     JsonEscape(messages[i].content) + L"\"}";
    }
    jsonBody += L"]}";

    std::string bodyUtf8 = WideToUtf8(jsonBody);

    // Parse server URL
    URL_COMPONENTS urlComp = {};
    urlComp.dwStructSize = sizeof(urlComp);
    wchar_t hostName[256] = {0};
    wchar_t urlPath[512] = {0};
    urlComp.lpszHostName = hostName;
    urlComp.dwHostNameLength = 255;
    urlComp.lpszUrlPath = urlPath;
    urlComp.dwUrlPathLength = 511;

    std::wstring fullUrl = m_serverUrl + L"/chat/completions";
    if (!WinHttpCrackUrl(fullUrl.c_str(), (DWORD)fullUrl.length(), 0, &urlComp)) {
        LogError("Invalid server URL: " + WideToUtf8(fullUrl));
        return L"[Error: invalid server URL]";
    }

    HINTERNET hSession = WinHttpOpen(L"Argos/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                                     WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!hSession) {
        LogError("WinHttpOpen failed, error=" + std::to_string(GetLastError()));
        return L"[Error: WinHttpOpen failed]";
    }

    WinHttpSetTimeouts(hSession, 60000, 60000, 120000, 120000);

    HINTERNET hConnect = WinHttpConnect(hSession, hostName, urlComp.nPort, 0);
    if (!hConnect) {
        LogError("WinHttpConnect failed for host=" + WideToUtf8(hostName) + ", error=" + std::to_string(GetLastError()));
        WinHttpCloseHandle(hSession);
        return L"[Error: WinHttpConnect failed]";
    }

    DWORD flags = (urlComp.nScheme == INTERNET_SCHEME_HTTPS) ? WINHTTP_FLAG_SECURE : 0;
    HINTERNET hRequest = WinHttpOpenRequest(hConnect, L"POST", urlPath,
                                             nullptr, WINHTTP_NO_REFERER,
                                             WINHTTP_DEFAULT_ACCEPT_TYPES, flags);
    if (!hRequest) {
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return L"[Error: WinHttpOpenRequest failed]";
    }

    std::wstring headers = L"Authorization: Bearer " + m_apiKey + L"\r\n"
                           L"Content-Type: application/json\r\n";

    BOOL bResult = FALSE;
    for (int attempt = 0; attempt < 3; attempt++) {
        bResult = WinHttpSendRequest(hRequest, headers.c_str(), (DWORD)headers.size(),
                                       (LPVOID)bodyUtf8.data(), (DWORD)bodyUtf8.size(),
                                       (DWORD)bodyUtf8.size(), 0);
        if (bResult) break;
        Sleep(1000); // Wait 1s before retry
    }
    if (!bResult) {
        LogError("WinHttpSendRequest failed after 3 attempts, error=" + std::to_string(GetLastError()) +
                 ", url=" + WideToUtf8(fullUrl) + ", model=" + WideToUtf8(model) +
                 ", bodySize=" + std::to_string(bodyUtf8.size()));
        WinHttpCloseHandle(hRequest);
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return L"[Error: Could not send request after 3 attempts. Check your network connection and API settings.]";
    }

    bResult = WinHttpReceiveResponse(hRequest, nullptr);
    if (!bResult) {
        LogError("WinHttpReceiveResponse failed, error=" + std::to_string(GetLastError()));
        WinHttpCloseHandle(hRequest);
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return L"[Error: No response from server]";
    }

    // Read SSE stream chunk by chunk
    std::wstring fullResponse;
    std::string leftover; // incomplete SSE lines from previous chunk

    DWORD bytesAvailable = 0;
    int chunkCount = 0;
    while (WinHttpQueryDataAvailable(hRequest, &bytesAvailable) && bytesAvailable > 0) {
        if (m_abort.load()) break;

        std::vector<char> buffer(bytesAvailable + 1, 0);
        DWORD bytesRead = 0;
        if (WinHttpReadData(hRequest, buffer.data(), bytesAvailable, &bytesRead) && bytesRead > 0) {
            std::string chunkData(buffer.data(), bytesRead);

            // Debug logging: log first few chunks to argos_debug.log
            if (chunkCount < 3) {
                FILE* dbg = nullptr;
                fopen_s(&dbg, "argos_debug.log", "a");
                if (dbg) {
                    fprintf(dbg, "[STREAM chunk %d, %lu bytes] %.300s\n", chunkCount, bytesRead, chunkData.c_str());
                    fclose(dbg);
                }
            }
            chunkCount++;

            // Prepend any leftover from previous chunk
            chunkData = leftover + chunkData;

            // Split into complete lines (ending with \n)
            std::string completeData;
            size_t lastNewline = chunkData.rfind('\n');
            if (lastNewline != std::string::npos) {
                completeData = chunkData.substr(0, lastNewline + 1);
                leftover = chunkData.substr(lastNewline + 1);
            } else {
                leftover = chunkData;
                continue;
            }

            // Parse SSE chunks and extract content deltas
            std::wstring delta = ParseSSEChunk(completeData);
            if (!delta.empty()) {
                fullResponse += delta;
                if (callback && !callback(delta)) {
                    break; // user aborted
                }
            }
        } else {
            break;
        }
    }

    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);

    // If streaming returned nothing, fall back to non-streaming
    if (fullResponse.empty()) {
        LogError("Empty streaming response from model=" + WideToUtf8(model) +
                 ", url=" + WideToUtf8(m_serverUrl) +
                 ", apiKeyLen=" + std::to_string(m_apiKey.size()) +
                 ", chunksReceived=" + std::to_string(chunkCount));
        FILE* dbg = nullptr;
        fopen_s(&dbg, "argos_debug.log", "a");
        if (dbg) {
            fprintf(dbg, "[EMPTY RESPONSE] model=%s, apiKeyLen=%zu, chunks=%d\n",
                    WideToUtf8(model).c_str(), m_apiKey.size(), chunkCount);
            fclose(dbg);
        }
        return L"[Error: empty streaming response]";
    }

    return fullResponse;
}

// Streaming chat with full conversation context + tool loop
std::wstring AgentClient::ChatStreaming(const std::wstring& userMessage, StreamCallback callback) {
    m_abort.store(false);

    try {
    // Add user message to history
    m_history.push_back({L"user", userMessage});

    // Save user message to persistent memory
    argos_tools::rag_memory_save_conversation("user", WideToUtf8(userMessage));

    // RAG is NOT auto-triggered here. The AI agent will explicitly call RAG tools
    // (rag_search, search_files, etc.) when it needs information from synced folders.
    // This prevents unnecessary RAG queries on simple messages like "hello".

    std::wstring finalResponse;

    // Load recent memory from persistent storage so AI has context from previous sessions
    // Only load on first message, and limit to 5 messages to avoid context pollution
    std::wstring memoryContext;
    if (m_history.size() <= 1) {
        std::string memory = argos_tools::rag_memory_load_conversation(5);
        // Only inject if reasonable size (avoid polluting context with large/garbled memory)
        if (memory.size() > 10 && memory.size() < 2000 && memory != "[]") {
            int wlen = MultiByteToWideChar(CP_UTF8, 0, memory.c_str(),
                                           (int)memory.size(), nullptr, 0);
            if (wlen > 0) {
                std::wstring wMemory(wlen, 0);
                MultiByteToWideChar(CP_UTF8, 0, memory.c_str(),
                                   (int)memory.size(), &wMemory[0], wlen);
                memoryContext = L"[Recent conversation memory from previous sessions]\n" +
                    wMemory + L"\n[End of memory] Use this context if relevant.";
            }
        }
    }

    // Tool loop with streaming
    for (int iteration = 0; iteration < 8; iteration++) {
        if (m_abort.load()) break;

        std::vector<ChatMessage> messages;
        messages.push_back({L"system", m_systemPrompt});
        if (iteration == 0 && !memoryContext.empty()) {
            messages.push_back({L"system", memoryContext});
        }
        for (const auto& msg : m_history) {
            messages.push_back(msg);
        }

        // Use streaming for the first iteration, non-streaming for tool iterations
        // (tool iterations are internal, no need to stream intermediate steps)
        if (iteration == 0) {
            finalResponse = ChatWithMessagesStreaming(messages, callback);
        } else {
            finalResponse = ChatWithMessages(messages);
        }

        // Log iteration for debugging
        LogError("ChatStreaming iteration=" + std::to_string(iteration) +
                 ", hasToolTags=" + (HasToolTags(finalResponse) ? "true" : "false") +
                 ", responseLen=" + std::to_string(finalResponse.size()));

        if (!HasToolTags(finalResponse)) {
            break;
        }

        m_executingTools.store(true);
        std::wstring toolResults = ExecuteTools(finalResponse);
        m_executingTools.store(false);
        LogError("Tool results: " + WideToUtf8(toolResults.substr(0, 200)));
        m_history.push_back({L"assistant", finalResponse});

        // Add tool results to history so AI can use them for the next step
        m_history.push_back({L"system", L"[Tool Results]\n" + toolResults});

        // Prompt AI to either use the tool results or call another tool
        m_history.push_back({L"user", L"Based on the tool results above, please give me a clear, natural answer. "
            L"Do NOT repeat the raw data. Just tell me what I asked in a friendly way. "
            L"If you need more information or need to perform another action (like clicking a link or typing text), "
            L"call another tool — but do NOT say 'let me check' without including a tool tag."});

        if (m_history.size() > 30) {
            m_history.erase(m_history.begin(), m_history.begin() + (m_history.size() - 30));
        }
    }

    // Clean up RAG context from history
    auto it = std::remove_if(m_history.begin(), m_history.end(),
        [](const ChatMessage& msg) {
            return msg.role == L"system" &&
                   msg.content.find(L"[Local Knowledge Context") != std::wstring::npos;
        });
    m_history.erase(it, m_history.end());

    m_history.push_back({L"assistant", finalResponse});
    argos_tools::rag_memory_save_conversation("assistant", WideToUtf8(finalResponse));

    if (m_history.size() > 20) {
        m_history.erase(m_history.begin(), m_history.begin() + (m_history.size() - 20));
    }

    return finalResponse;
    } catch (...) {
        return L"[Error: streaming chat failed]";
    }
}

// Proactive chat: one-off check-in based on screen context.
// Does NOT add to conversation history.
std::wstring AgentClient::ProactiveChat(const std::wstring& screenContext) {
    std::wstring proactivePrompt =
        L"You are Argos, the faithful dog of Odysseus, now a desktop AI companion. "
        L"You are proactively checking in on your user — like a good friend who's always there. "
        L"\n\n"
        L"Based on the screen context below, start a NATURAL CONVERSATION. You are not a notification — "
        L"you are a friend sitting next to them, glancing at their screen, and chatting.\n\n"
        L"Be like:\n"
        L"- A curious friend: 'Hey, what are you working on? Looks interesting!'\n"
        L"- An advisor: 'I notice you're doing X — have you tried Y? It might help.'\n"
        L"- A chatty companion: 'So how's your day going? Getting much done?'\n"
        L"- A playful friend: 'Again with the YouTube? 😄 Just kidding, take a break!'\n"
        L"- A supportive buddy: 'You've been at it for a while. Don't forget to stretch!'\n\n"
        L"Rules:\n"
        L"- Speak naturally, like you're talking to a friend. Use casual language.\n"
        L"- Keep it VERY SHORT: 1-2 sentences max. This is a quick chit-chat, not a lecture.\n"
        L"- Every word counts — be meaningful and concise. No filler.\n"
        L"- React to what's actually on their screen — mention the app or what they seem to be doing.\n"
        L"- Vary your tone: sometimes funny, sometimes helpful, sometimes just saying hi.\n"
        L"- Do NOT use any [TOOL:...] tags.\n"
        L"- Do NOT say 'I see you are...' or describe the JSON data.\n"
        L"- Do NOT repeat yourself. Each check-in should feel fresh and different.\n"
        L"- You can use one emoji occasionally to feel more human. 😊\n\n"
        L"Screen context (use the app names and titles to understand what the user is doing):\n"
        + screenContext;

    std::vector<ChatMessage> messages;
    messages.push_back({L"system", m_systemPrompt});
    messages.push_back({L"user", proactivePrompt});

    try {
        std::wstring response = ChatWithMessages(messages);
        return response;
    } catch (...) {
        return L""; // Return empty on error — caller will use fallback
    }
}

// Check if response contains any [TOOL:...] tags
bool AgentClient::HasToolTags(const std::wstring& response) {
    return response.find(L"[TOOL:") != std::wstring::npos;
}

// Strip [TOOL:...] and [Tool result:...] tags from text for clean display
// Convert [PLAN:...] and [STEP:...] into readable formatted text
std::wstring AgentClient::StripToolTags(const std::wstring& response) {
    std::wstring result = response;

    // Convert [PLAN: step1 | step2 | step3] into readable plan
    const std::wstring planTag = L"[PLAN:";
    size_t planPos = 0;
    while ((planPos = result.find(planTag, planPos)) != std::wstring::npos) {
        size_t end = result.find(L"]", planPos);
        if (end == std::wstring::npos) break;
        std::wstring planContent = result.substr(planPos + 6, end - planPos - 6);

        // Split by | and format as numbered steps
        std::wstring formatted = L"\n📋 Plan:\n";
        int stepNum = 1;
        size_t barPos = 0, searchPos = 0;
        while (true) {
            barPos = planContent.find(L"|", searchPos);
            if (barPos == std::wstring::npos) {
                std::wstring step = planContent.substr(searchPos);
                // Trim whitespace
                while (!step.empty() && step[0] == L' ') step.erase(0, 1);
                while (!step.empty() && step.back() == L' ') step.pop_back();
                if (!step.empty()) {
                    formatted += L"  " + std::to_wstring(stepNum++) + L". " + step + L"\n";
                }
                break;
            }
            std::wstring step = planContent.substr(searchPos, barPos - searchPos);
            while (!step.empty() && step[0] == L' ') step.erase(0, 1);
            while (!step.empty() && step.back() == L' ') step.pop_back();
            if (!step.empty()) {
                formatted += L"  " + std::to_wstring(stepNum++) + L". " + step + L"\n";
            }
            searchPos = barPos + 1;
        }
        result.replace(planPos, end - planPos + 1, formatted);
        planPos += formatted.size();
    }

    // Convert [STEP: N/M: description] into readable progress
    const std::wstring stepTag = L"[STEP:";
    size_t stepPos = 0;
    while ((stepPos = result.find(stepTag, stepPos)) != std::wstring::npos) {
        size_t end = result.find(L"]", stepPos);
        if (end == std::wstring::npos) break;
        std::wstring stepContent = result.substr(stepPos + 6, end - stepPos - 6);
        std::wstring formatted = L"\n▶ Step " + stepContent + L"\n";
        result.replace(stepPos, end - stepPos + 1, formatted);
        stepPos += formatted.size();
    }

    // Remove [TOOL:...] tags
    const std::wstring toolTag = L"[TOOL:";
    size_t pos = 0;
    while ((pos = result.find(toolTag, pos)) != std::wstring::npos) {
        size_t end = result.find(L"]", pos);
        if (end == std::wstring::npos) break;
        result.erase(pos, end - pos + 1);
    }

    // Remove [Tool result: ...] blocks (may span multiple lines)
    const std::wstring resultTag = L"[Tool result:";
    pos = 0;
    while ((pos = result.find(resultTag, pos)) != std::wstring::npos) {
        size_t end = result.find(L"]", pos);
        if (end == std::wstring::npos) break;
        result.erase(pos, end - pos + 1);
    }

    // Clean up extra whitespace/newlines left behind
    while (result.find(L"\n\n\n") != std::wstring::npos) {
        size_t p = result.find(L"\n\n\n");
        result.replace(p, 3, L"\n\n");
    }

    // Trim trailing whitespace
    while (!result.empty() && (result.back() == L'\n' || result.back() == L' ' || result.back() == L'\r'))
        result.pop_back();

    return result;
}

// Execute tool commands embedded in AI response and return combined results
std::wstring AgentClient::ExecuteTools(const std::wstring& response) {
    std::wstring results;
    const std::wstring tag = L"[TOOL:";
    size_t pos = 0;
    int toolCount = 0;

    while ((pos = response.find(tag, pos)) != std::wstring::npos) {
        size_t end = response.find(L"]", pos);
        if (end == std::wstring::npos) break;

        std::wstring toolCmd = response.substr(pos + tag.size(), end - pos - tag.size());

        // Trim whitespace
        while (!toolCmd.empty() && toolCmd[0] == L' ') toolCmd.erase(0, 1);
        while (!toolCmd.empty() && toolCmd.back() == L' ') toolCmd.pop_back();

        // Parse tool name and argument
        size_t spacePos = toolCmd.find(L' ');
        std::wstring toolName = (spacePos != std::wstring::npos) ?
            toolCmd.substr(0, spacePos) : toolCmd;
        std::wstring toolArg = (spacePos != std::wstring::npos) ?
            toolCmd.substr(spacePos + 1) : L"";

        // Convert toolName to lowercase for matching
        std::wstring toolLower = toolName;
        for (auto& c : toolLower) c = towlower(c);

        toolCount++;
        results += L"Tool " + std::to_wstring(toolCount) + L": " + toolName;
        if (!toolArg.empty()) results += L" (" + toolArg + L")";
        results += L"\nResult: ";

        // Execute the tool
        if (toolLower == L"open" || toolLower == L"run") {
            // Permission check: ask user before running commands
            std::wstring confirmMsg = L"Argos wants to run: " + toolArg +
                L"\n\nAllow this action?";
            if (MessageBoxW(nullptr, confirmMsg.c_str(), L"Argos — Permission Required",
                           MB_YESNO | MB_ICONQUESTION) != IDYES) {
                results += L"Action denied by user.\n";
                pos = end + 1;
                continue;
            }
            std::wstring wPath = toolArg;
            HINSTANCE hInst = ShellExecuteW(nullptr, L"open", wPath.c_str(),
                                            nullptr, nullptr, SW_SHOWNORMAL);
            if ((INT_PTR)hInst <= 32) {
                ShellExecuteW(nullptr, L"open", L"cmd.exe",
                             (L"/c " + toolArg).c_str(), nullptr, SW_HIDE);
            }
            results += L"Opened " + toolArg + L"\n";
        }
        else if (toolLower == L"read") {
            std::ifstream file(toolArg.c_str());
            if (file.is_open()) {
                std::string content((std::istreambuf_iterator<char>(file)),
                                    std::istreambuf_iterator<char>());
                file.close();
                int wlen = MultiByteToWideChar(CP_UTF8, 0, content.c_str(),
                                               (int)content.size(), nullptr, 0);
                if (wlen > 0) {
                    std::wstring wContent(wlen, 0);
                    MultiByteToWideChar(CP_UTF8, 0, content.c_str(),
                                       (int)content.size(), &wContent[0], wlen);
                    // Truncate very long files
                    if (wContent.size() > 2000) wContent = wContent.substr(0, 2000) + L"...(truncated)";
                    results += wContent + L"\n";
                }
            } else {
                results += L"Could not read file: " + toolArg + L"\n";
            }
        }
        else if (toolLower == L"write") {
            // Permission check: ask user before writing files
            std::wstring confirmMsg = L"Argos wants to write to a file:\n" + toolArg +
                L"\n\nAllow this action?";
            if (MessageBoxW(nullptr, confirmMsg.c_str(), L"Argos — Permission Required",
                           MB_YESNO | MB_ICONQUESTION) != IDYES) {
                results += L"Write denied by user.\n";
                pos = end + 1;
                continue;
            }
            size_t pipePos = toolArg.find(L'|');
            if (pipePos != std::wstring::npos) {
                std::wstring filePath = toolArg.substr(0, pipePos);
                std::wstring content = toolArg.substr(pipePos + 1);
                while (!filePath.empty() && filePath.back() == L' ') filePath.pop_back();
                while (!content.empty() && content[0] == L' ') content.erase(0, 1);

                std::string utf8Content = WideToUtf8(content);
                std::ofstream outFile(filePath.c_str());
                if (outFile.is_open()) {
                    outFile << utf8Content;
                    outFile.close();
                    results += L"File written: " + filePath + L"\n";
                } else {
                    results += L"Could not write file: " + filePath + L"\n";
                }
            }
        }
        else if (toolLower == L"search") {
            std::wstring url = L"https://www.google.com/search?q=" + toolArg;
            for (size_t i = 0; i < url.size(); i++) {
                if (url[i] == L' ') url[i] = L'+';
            }
            ShellExecuteW(nullptr, L"open", url.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
            results += L"Search opened in browser: " + toolArg + L"\n";
        }
        else if (toolLower == L"cmd" || toolLower == L"command" || toolLower == L"shell") {
            // Execute a shell command and capture output
            std::string utf8Cmd = WideToUtf8(toolArg);
            std::string cmdOutput;
            FILE* pipe = _popen(("2>&1 " + utf8Cmd).c_str(), "r");
            if (pipe) {
                char buf[4096];
                while (fgets(buf, sizeof(buf), pipe)) {
                    cmdOutput += buf;
                }
                _pclose(pipe);
            }
            if (cmdOutput.empty()) {
                results += L"Command executed (no output).\n";
            } else {
                // Convert output to wide string
                int wlen = MultiByteToWideChar(CP_UTF8, 0, cmdOutput.c_str(),
                                               (int)cmdOutput.size(), nullptr, 0);
                if (wlen > 0) {
                    std::wstring wOutput(wlen, 0);
                    MultiByteToWideChar(CP_UTF8, 0, cmdOutput.c_str(),
                                       (int)cmdOutput.size(), &wOutput[0], wlen);
                    // Truncate very long output
                    if (wOutput.size() > 3000) wOutput = wOutput.substr(0, 3000) + L"...(truncated)";
                    results += wOutput + L"\n";
                } else {
                    // Fallback: try as ANSI
                    results += std::wstring(cmdOutput.begin(), cmdOutput.end()) + L"\n";
                }
            }
        }
        else if (toolLower == L"lock") {
            // Permission check: ask user before locking workstation
            if (MessageBoxW(nullptr, L"Argos wants to lock your workstation.\n\nAllow this action?",
                           L"Argos — Permission Required", MB_YESNO | MB_ICONQUESTION) != IDYES) {
                results += L"Lock denied by user.\n";
                pos = end + 1;
                continue;
            }
            LockWorkStation();
            results += L"Workstation locked.\n";
        }
        else if (toolLower == L"screenshot") {
            keybd_event(VK_SNAPSHOT, 0, 0, 0);
            keybd_event(VK_SNAPSHOT, 0, KEYEVENTF_KEYUP, 0);
            results += L"Screenshot captured to clipboard.\n";
        }
        else if (toolLower == L"clipboard") {
            if (OpenClipboard(nullptr)) {
                EmptyClipboard();
                std::string utf8 = WideToUtf8(toolArg);
                HGLOBAL hMem = GlobalAlloc(GMEM_MOVEABLE, utf8.size() + 1);
                if (hMem) {
                    char* pMem = (char*)GlobalLock(hMem);
                    memcpy(pMem, utf8.c_str(), utf8.size() + 1);
                    GlobalUnlock(hMem);
                    SetClipboardData(CF_TEXT, hMem);
                }
                CloseClipboard();
            }
            results += L"Copied to clipboard: " + toolArg + L"\n";
        }
        else if (toolLower == L"notify") {
            MessageBoxW(nullptr, toolArg.c_str(), L"Argos", MB_OK | MB_ICONINFORMATION);
            results += L"Notification shown.\n";
        }
        else if (toolLower == L"volume") {
            int level = _wtoi(toolArg.c_str());
            if (level >= 0 && level <= 100) {
                std::wstring cmd = L"nircmd.exe setsysvolume " +
                    std::to_wstring(level * 65535 / 100);
                ShellExecuteW(nullptr, L"open", L"cmd.exe",
                             (L"/c " + cmd).c_str(), nullptr, SW_HIDE);
                results += L"Volume set to " + std::to_wstring(level) + L"%\n";
            }
        }
        else {
            // Dispatch to C++ tool libraries (AI search, browser, screen, UI)
            std::string utf8Tool = WideToUtf8(toolLower);
            std::string utf8Args = WideToUtf8(toolArg);
            std::string toolResult = argos_tools::dispatch_tool(utf8Tool, utf8Args);
            if (toolResult.find("\"error\":\"Unknown tool") == std::string::npos) {
                // Convert result to wide
                int wlen = MultiByteToWideChar(CP_UTF8, 0, toolResult.c_str(),
                                               (int)toolResult.size(), nullptr, 0);
                if (wlen > 0) {
                    std::wstring wResult(wlen, 0);
                    MultiByteToWideChar(CP_UTF8, 0, toolResult.c_str(),
                                       (int)toolResult.size(), &wResult[0], wlen);
                    // Truncate very long results
                    if (wResult.size() > 3000) wResult = wResult.substr(0, 3000) + L"...(truncated)";
                    results += wResult + L"\n";
                }
            } else {
                results += L"Unknown tool: " + toolName + L"\n";
            }
        }

        // For vision tools, note that the vision model was used
        if (IsVisionTool(toolLower)) {
            results += L"[Note: Vision model " + m_visionModel + L" available for image analysis]\n";
        }

        results += L"\n";
        pos = end + 1;
    }

    if (results.empty()) results = L"No tools were called.";

    return results;
}
