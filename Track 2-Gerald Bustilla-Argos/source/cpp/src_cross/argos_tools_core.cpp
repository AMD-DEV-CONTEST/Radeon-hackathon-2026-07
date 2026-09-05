#include "argos_tools_core.h"
#include "platform.h"
#include "ui_inspector.h"
#include "whisper_wrapper.h"
#include <sstream>
#include <vector>
#include <fstream>
#include <dirent.h>
#include <sys/stat.h>
#include <cstdio>
#include <cstring>
#include <chrono>
#include <thread>

#ifdef __ANDROID__
#include <android/log.h>
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "Argos", __VA_ARGS__)
#else
#define LOGI(...)
#endif

namespace argos_tools {

static std::string getMemoryFilePath() {
    return argos::getAppDataDir() + "/conversation_memory.jsonl";
}

bool rag_memory_save_conversation(const std::string& role, const std::string& content) {
    std::string path = getMemoryFilePath();
    // Ensure directory exists
    mkdir(argos::getAppDataDir().c_str(), 0777);

    FILE* f = fopen(path.c_str(), "a");
    if (!f) return false;

    std::string escaped;
    for (char c : content) {
        if (c == '"') escaped += "\\\"";
        else if (c == '\\') escaped += "\\\\";
        else if (c == '\n') escaped += "\\n";
        else if (c == '\r') escaped += "\\r";
        else if (c == '\t') escaped += "\\t";
        else escaped += c;
    }

    fprintf(f, "{\"role\":\"%s\",\"content\":\"%s\"}\n", role.c_str(), escaped.c_str());
    fclose(f);
    return true;
}

std::string rag_memory_load_conversation(size_t max_messages) {
    std::string path = getMemoryFilePath();
    FILE* f = fopen(path.c_str(), "r");
    if (!f) return "[]";

    std::vector<std::string> lines;
    char buffer[8192];
    while (fgets(buffer, sizeof(buffer), f)) {
        lines.push_back(std::string(buffer));
    }
    fclose(f);

    size_t start = (lines.size() > max_messages) ? lines.size() - max_messages : 0;
    std::string result = "[\n";
    for (size_t i = start; i < lines.size(); i++) {
        result += "  " + lines[i];
        if (i < lines.size() - 1) result += ",";
        result += "\n";
    }
    result += "]";
    return result;
}

// Tool implementations
static std::string tool_list_files(const std::string& dirPath) {
    std::string path = dirPath;
    if (path.empty()) path = ".";
    std::ostringstream json;
    json << "{\"directory\":\"" << path << "\",\"files\":[";

    DIR* dir = opendir(path.c_str());
    if (!dir) {
        json << "],\"error\":\"Cannot open directory: " << path << "\"}";
        return json.str();
    }

    struct dirent* entry;
    bool first = true;
    while ((entry = readdir(dir)) != nullptr) {
        if (!first) json << ",";
        first = false;
        json << "{\"name\":\"" << entry->d_name << "\"";
        json << ",\"type\":\"" << (entry->d_type == DT_DIR ? "directory" : "file") << "\"";
        json << "}";
    }
    closedir(dir);
    json << "]}";
    return json.str();
}

static std::string tool_read_file(const std::string& filePath) {
    std::ifstream f(filePath, std::ios::binary);
    if (!f.is_open()) return "{\"error\":\"Cannot read file: " + filePath + "\"}";
    std::string content((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    if (content.size() > 5000) content = content.substr(0, 5000) + "...(truncated)";
    return content;
}

static std::string tool_cmd(const std::string& command) {
    FILE* pipe = popen(command.c_str(), "r");
    if (!pipe) return "{\"error\":\"Command failed\"}";
    std::string output;
    char buf[4096];
    while (fgets(buf, sizeof(buf), pipe)) {
        output += buf;
    }
    pclose(pipe);
    if (output.empty()) return "Command executed (no output).";
    if (output.size() > 3000) output = output.substr(0, 3000) + "...(truncated)";
    return output;
}

static std::string tool_recall() {
    return rag_memory_load_conversation(10);
}

static std::string tool_forget() {
    std::string path = getMemoryFilePath();
    if (remove(path.c_str()) == 0) return "{\"status\":\"Memory cleared\"}";
    return "{\"status\":\"No memory to clear\"}";
}

std::string dispatch_tool(const std::string& tool_name, const std::string& args) {
    std::string name = tool_name;
    // Lowercase
    for (auto& c : name) c = tolower(c);

    if (name == "list_files" || name == "dir" || name == "ls") {
        return tool_list_files(args);
    }
    if (name == "read") {
        return tool_read_file(args);
    }
    if (name == "cmd" || name == "command" || name == "shell") {
        return tool_cmd(args);
    }
    if (name == "recall") {
        return tool_recall();
    }
    if (name == "forget") {
        return tool_forget();
    }
    if (name == "search") {
        return "{\"error\":\"Web search not available on mobile platform. Use open_url to open a search page, then screen_text to read it.\"}";
    }
    if (name == "rag_search" || name == "search_files" || name == "search_filename") {
        return "{\"error\":\"RAG search not available on this platform\"}";
    }
    // ── Browser / Screen tools (Android Accessibility Service) ──
    if (name == "open_url" || name == "browser_open" || name == "navigate") {
        std::string result = argos::openUrl(args);
        // Wait for browser to load
        std::this_thread::sleep_for(std::chrono::seconds(2));
        return result;
    }
    if (name == "screen_text" || name == "read_screen" || name == "browser_content") {
        return argos::getScreenText();
    }
    if (name == "screen_active" || name == "active_app") {
        return argos::getActiveApp();
    }
    if (name == "click_text" || name == "browser_click") {
        std::string result = argos::clickText(args);
        // Wait for screen to update after click
        std::this_thread::sleep_for(std::chrono::seconds(1));
        return result;
    }
    if (name == "type_text" || name == "browser_type") {
        return argos::typeText(args);
    }
    if (name == "scroll") {
        int dir = 1; // default down
        if (args == "up" || args == "0") dir = 0;
        std::string result = argos::scrollScreen(dir);
        // Wait for scroll to settle
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        return result;
    }

    // ── UI Inspection & Automation tools ──

    if (name == "ui_inspect" || name == "inspect_ui" || name == "ui_tree") {
        // Optional depth argument: "ui_inspect" or "ui_inspect 15"
        int maxDepth = -1;
        if (!args.empty()) {
            maxDepth = std::atoi(args.c_str());
            if (maxDepth <= 0) maxDepth = -1;
        }
        return argos::getUITree(maxDepth);
    }

    if (name == "ui_click" || name == "ui_tap") {
        // Args can be: element ID number, or text to find
        if (args.empty()) return "{\"error\":\"ui_click needs element ID or text\"}";
        // Check if args is a number (element ID)
        bool isNumber = true;
        for (char c : args) { if (!isdigit(c) && c != '-') { isNumber = false; break; } }
        if (isNumber) {
            int id = std::atoi(args.c_str());
            std::string result = argos::performUIAction(id, "click", "");
            std::this_thread::sleep_for(std::chrono::milliseconds(800));
            return result;
        }
        // Otherwise treat as text to find and click
        return argos_ui::clickElementByText(args, false);
    }

    if (name == "ui_longpress" || name == "ui_long_click") {
        if (args.empty()) return "{\"error\":\"ui_longpress needs element ID or text\"}";
        bool isNumber = true;
        for (char c : args) { if (!isdigit(c) && c != '-') { isNumber = false; break; } }
        if (isNumber) {
            int id = std::atoi(args.c_str());
            std::string result = argos::performUIAction(id, "long_click", "");
            std::this_thread::sleep_for(std::chrono::milliseconds(800));
            return result;
        }
        return argos_ui::clickElementByText(args, true);
    }

    if (name == "ui_type" || name == "ui_input") {
        // Args format: "elementId|text" or just "text" (auto-find field)
        size_t pipe = args.find('|');
        if (pipe != std::string::npos) {
            int id = std::atoi(args.substr(0, pipe).c_str());
            std::string text = args.substr(pipe + 1);
            return argos::performUIAction(id, "set_text", text);
        }
        // No element ID — find an editable field and type into it
        return argos_ui::typeIntoFieldWithHint("", args);
    }

    if (name == "ui_action") {
        // Args format: "elementId|action" or "elementId|action|extra"
        // e.g. "5|click" or "3|set_text|Hello world"
        size_t p1 = args.find('|');
        if (p1 == std::string::npos) return "{\"error\":\"ui_action needs: elementId|action[|extra]\"}";
        int id = std::atoi(args.substr(0, p1).c_str());
        size_t p2 = args.find('|', p1 + 1);
        std::string action = (p2 != std::string::npos) ? args.substr(p1 + 1, p2 - p1 - 1) : args.substr(p1 + 1);
        std::string extra = (p2 != std::string::npos) ? args.substr(p2 + 1) : "";
        std::string result = argos::performUIAction(id, action, extra);
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        return result;
    }

    if (name == "ui_sequence" || name == "ui_macro") {
        // Args is a JSON array of action steps
        // e.g. [{"action":"click","text":"Reply"},{"action":"type","text":"Hello!"},{"action":"click","text":"Send"}]
        auto steps = argos_ui::parseActionSequence(args);
        if (steps.empty()) return "{\"error\":\"No valid action steps parsed from: " + args + "\"}";
        return argos_ui::executeActionSequence(steps);
    }

    if (name == "screenshot" || name == "screen_capture") {
        return argos::takeScreenshot(args);
    }

    if (name == "notifications" || name == "get_notifications") {
        return argos::getNotificationsList();
    }

    if (name == "notif_reply" || name == "notification_reply") {
        // Args format: "index|message"
        size_t pipe = args.find('|');
        if (pipe == std::string::npos) return "{\"error\":\"notif_reply needs: index|message\"}";
        int idx = std::atoi(args.substr(0, pipe).c_str());
        std::string msg = args.substr(pipe + 1);
        return argos::replyToNotificationByIdx(idx, msg);
    }

    // ── Gesture-based UI automation tools ──

    if (name == "ui_tap_at" || name == "ui_tap_point") {
        // Args format: "x,y"
        if (args.empty()) return "{\"error\":\"ui_tap_at needs: x,y\"}";
        size_t comma = args.find(',');
        if (comma == std::string::npos) return "{\"error\":\"ui_tap_at needs: x,y (comma separated)\"}";
        int x = std::atoi(args.substr(0, comma).c_str());
        int y = std::atoi(args.substr(comma + 1).c_str());
        std::string result = argos::clickAtPoint(x, y);
        std::this_thread::sleep_for(std::chrono::milliseconds(800));
        return result;
    }

    if (name == "ui_longpress_at" || name == "ui_long_press_point") {
        if (args.empty()) return "{\"error\":\"ui_longpress_at needs: x,y\"}";
        size_t comma = args.find(',');
        if (comma == std::string::npos) return "{\"error\":\"ui_longpress_at needs: x,y (comma separated)\"}";
        int x = std::atoi(args.substr(0, comma).c_str());
        int y = std::atoi(args.substr(comma + 1).c_str());
        std::string result = argos::longPressAtPoint(x, y);
        std::this_thread::sleep_for(std::chrono::milliseconds(800));
        return result;
    }

    if (name == "ui_smart_click" || name == "ui_smart_tap") {
        // Smart click: tries accessibility action first, falls back to gesture
        if (args.empty()) return "{\"error\":\"ui_smart_click needs: x,y\"}";
        size_t comma = args.find(',');
        if (comma == std::string::npos) return "{\"error\":\"ui_smart_click needs: x,y (comma separated)\"}";
        int x = std::atoi(args.substr(0, comma).c_str());
        int y = std::atoi(args.substr(comma + 1).c_str());
        std::string result = argos::smartClick(x, y);
        std::this_thread::sleep_for(std::chrono::milliseconds(800));
        return result;
    }

    if (name == "ui_smart_longpress") {
        if (args.empty()) return "{\"error\":\"ui_smart_longpress needs: x,y\"}";
        size_t comma = args.find(',');
        if (comma == std::string::npos) return "{\"error\":\"ui_smart_longpress needs: x,y (comma separated)\"}";
        int x = std::atoi(args.substr(0, comma).c_str());
        int y = std::atoi(args.substr(comma + 1).c_str());
        std::string result = argos::smartLongPress(x, y);
        std::this_thread::sleep_for(std::chrono::milliseconds(800));
        return result;
    }

    if (name == "ui_swipe" || name == "ui_gesture_swipe") {
        // Args format: "x1,y1,x2,y2" or "x1,y1,x2,y2,duration"
        if (args.empty()) return "{\"error\":\"ui_swipe needs: x1,y1,x2,y2[,duration]\"}";
        std::vector<int> nums;
        std::stringstream ss(args);
        std::string token;
        while (std::getline(ss, token, ',')) {
            nums.push_back(std::atoi(token.c_str()));
        }
        if (nums.size() < 4) return "{\"error\":\"ui_swipe needs at least 4 values: x1,y1,x2,y2\"}";
        int duration = nums.size() > 4 ? nums[4] : 300;
        std::string result = argos::swipeGesture(nums[0], nums[1], nums[2], nums[3], duration);
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        return result;
    }

    if (name == "ui_swipe_up" || name == "swipe_up") {
        std::string result = argos::swipeUp();
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        return result;
    }

    if (name == "ui_swipe_down" || name == "swipe_down") {
        std::string result = argos::swipeDown();
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        return result;
    }

    if (name == "ui_elements" || name == "ui_clickable") {
        // Quick list of all clickable/interactive elements with bounds and center points
        return argos::getClickableElements();
    }

    if (name == "screen_size" || name == "ui_screen_size") {
        return argos::getScreenSize();
    }

    // ── Voice / Speech tools (whisper.cpp + native TTS) ──

    if (name == "voice_listen" || name == "voice_record") {
        // Record audio from microphone and transcribe with whisper
        // Args: optional duration in seconds (default 5)
        int duration = 5;
        if (!args.empty()) {
            duration = std::atoi(args.c_str());
            if (duration < 1) duration = 5;
            if (duration > 30) duration = 30;
        }

        if (!argos::whisperIsReady()) {
            return "{\"error\":\"Whisper not initialized. Use whisper_init <model_path> first. Download ggml-tiny.en.bin (~75MB) or ggml-base.en.bin (~142MB) from https://huggingface.co/ggerganov/whisper.cpp\"}";
        }

        auto samples = argos::recordAudio(duration);
        if (samples.empty()) {
            return "{\"error\":\"No audio recorded. Check microphone permission.\"}";
        }

        std::string text = argos::whisperTranscribe(samples);
        if (text.empty()) {
            return "{\"status\":\"empty\",\"message\":\"No speech detected in recording\"}";
        }

        return "{\"status\":\"success\",\"text\":\"" + text + "\",\"duration\":" + std::to_string(duration) + "}";
    }

    if (name == "voice_transcribe" || name == "whisper_transcribe") {
        // Transcribe an audio file (WAV format) using whisper
        // Args: path to WAV file
        if (args.empty()) return "{\"error\":\"voice_transcribe needs: <wav_file_path>\"}";

        if (!argos::whisperIsReady()) {
            return "{\"error\":\"Whisper not initialized. Use whisper_init <model_path> first.\"}";
        }

        // Read WAV file and convert to float32 PCM
        std::ifstream wavFile(args, std::ios::binary);
        if (!wavFile.is_open()) {
            return "{\"error\":\"Cannot open file: " + args + "\"}";
        }

        // Skip WAV header (44 bytes standard) and read 16-bit PCM
        wavFile.seekg(0, std::ios::end);
        size_t fileSize = wavFile.tellg();
        if (fileSize < 44) {
            return "{\"error\":\"File too small to be a valid WAV\"}";
        }

        wavFile.seekg(44, std::ios::beg); // Skip standard WAV header
        size_t dataSize = fileSize - 44;
        size_t numSamples = dataSize / 2; // 16-bit samples

        std::vector<int16_t> pcm16(numSamples);
        wavFile.read((char*)pcm16.data(), dataSize);
        wavFile.close();

        std::vector<float> samples(numSamples);
        for (size_t i = 0; i < numSamples; i++) {
            samples[i] = (float)pcm16[i] / 32768.0f;
        }

        std::string text = argos::whisperTranscribe(samples);
        return "{\"status\":\"success\",\"text\":\"" + text + "\",\"samples\":" + std::to_string(numSamples) + "}";
    }

    if (name == "whisper_init" || name == "voice_init") {
        // Initialize whisper with a model file
        // Args: path to ggml model file (e.g. /sdcard/ggml-tiny.en.bin)
        if (args.empty()) {
            return "{\"error\":\"whisper_init needs: <model_path>. Download from https://huggingface.co/ggerganov/whisper.cpp\"}";
        }

        bool ok = argos::whisperInit(args);
        if (ok) {
            return "{\"status\":\"success\",\"model\":\"" + args + "\"}";
        }
        return "{\"error\":\"Failed to load whisper model: " + args + "\"}";
    }

    if (name == "whisper_status" || name == "voice_status") {
        if (argos::whisperIsReady()) {
            return "{\"status\":\"ready\",\"model\":\"" + argos::whisperGetModelPath() + "\"}";
        }
        return "{\"status\":\"not_initialized\",\"hint\":\"Use whisper_init <model_path> to initialize. Download ggml-tiny.en.bin from https://huggingface.co/ggerganov/whisper.cpp\"}";
    }

    if (name == "tts_speak" || name == "speak" || name == "voice_speak") {
        // Speak text using native TTS (Android TextToSpeech / Windows SAPI)
        if (args.empty()) return "{\"error\":\"tts_speak needs: <text>\"}";
        bool ok = argos::ttsSpeak(args);
        if (ok) {
            return "{\"status\":\"speaking\",\"text\":\"" + args + "\"}";
        }
        return "{\"error\":\"TTS not available or failed\"}";
    }

    if (name == "tts_stop" || name == "voice_stop") {
        argos::ttsStop();
        return "{\"status\":\"stopped\"}";
    }

    if (name == "tts_status") {
        if (argos::ttsIsSpeaking()) {
            return "{\"speaking\":true}";
        }
        return "{\"speaking\":false}";
    }

    return "{\"error\":\"Unknown tool: " + name + "\"}";
}

} // namespace argos_tools
