// test_runner_screen.cpp - Test Suite for Screen Context Reader
// Tests: app enumeration, screen capture, text extraction, context assessment
#include <iostream>
#include <string>
#include <vector>
#include <sstream>
#include <cstdlib>
#include <functional>
#include <regex>

#ifdef _WIN32
#include <cstdio>
#define popen _popen
#define pclose _pclose
#endif

static int tests_passed = 0;
static int tests_failed = 0;
static int tests_total = 0;

static const std::string U = "screencontext.exe";

static std::string exec_command(const std::string& cmd) {
    std::string result;
    std::string full_cmd = cmd + " 2>&1";
    FILE* pipe = popen(full_cmd.c_str(), "r");
    if (!pipe) return "";
    char buffer[8192];
    while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
        result += buffer;
    }
    pclose(pipe);
    return result;
}

static bool json_contains(const std::string& json, const std::string& needle) {
    return json.find(needle) != std::string::npos;
}

static bool json_contains_ci(const std::string& json, const std::string& needle) {
    std::string lj, ln;
    for (char c : json) lj += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    for (char c : needle) ln += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return lj.find(ln) != std::string::npos;
}

static int json_get_int(const std::string& json, const std::string& key) {
    std::string search = "\"" + key + "\":";
    size_t pos = json.find(search);
    if (pos == std::string::npos) return -1;
    pos += search.size();
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) pos++;
    std::string num;
    while (pos < json.size() && (json[pos] >= '0' && json[pos] <= '9' || json[pos] == '-')) {
        num += json[pos++];
    }
    return num.empty() ? -1 : std::atoi(num.c_str());
}

static std::string json_get_str(const std::string& json, const std::string& key) {
    std::regex re("\"" + key + "\"\\s*:\\s*\"([^\"]*)\"");
    std::smatch m;
    if (std::regex_search(json, m, re)) {
        return m[1].str();
    }
    return "";
}

static void run_test(const std::string& name, const std::string& cmd,
                     std::function<bool(const std::string&)> checker) {
    tests_total++;
    std::string output = exec_command(cmd);
    bool ok = checker(output);
    std::cout << "[" << (tests_total < 10 ? " " : "") << tests_total << "] "
              << (name.size() > 65 ? name.substr(0, 62) + "..." : name)
              << std::string(70 - std::min((size_t)70, name.size() + 4), ' ')
              << (ok ? "PASS" : "FAIL") << std::endl;
    if (!ok) {
        tests_failed++;
        std::string trimmed = output.size() > 300 ? output.substr(0, 300) + "..." : output;
        std::cout << "       Output: " << trimmed << std::endl;
    } else {
        tests_passed++;
    }
}

int main() {
    std::cout << "========================================" << std::endl;
    std::cout << " SCREEN CONTEXT READER TEST SUITE" << std::endl;
    std::cout << " 100 Tests - App Detection, OCR, Context" << std::endl;
    std::cout << "========================================" << std::endl;

    // ========== CATEGORY 1: App Enumeration (1-12) ==========
    std::cout << std::endl << "--- Category 1: App Enumeration ---" << std::endl;

    run_test("Sim mode lists 13 apps", U + " --sim list-apps",
        [](const std::string& o) { return json_get_int(o, "total_apps") == 13; });

    run_test("List-apps returns valid JSON", U + " --sim list-apps",
        [](const std::string& o) { return o.size() > 0 && o[0] == '{'; });

    run_test("Apps include Facebook", U + " --sim list-apps",
        [](const std::string& o) { return json_contains_ci(o, "Facebook"); });

    run_test("Apps include Chrome", U + " --sim list-apps",
        [](const std::string& o) { return json_contains_ci(o, "Chrome"); });

    run_test("Apps include VS Code", U + " --sim list-apps",
        [](const std::string& o) { return json_contains_ci(o, "Visual Studio Code"); });

    run_test("Apps include Spotify", U + " --sim list-apps",
        [](const std::string& o) { return json_contains_ci(o, "Spotify"); });

    run_test("Apps include Outlook", U + " --sim list-apps",
        [](const std::string& o) { return json_contains_ci(o, "Outlook"); });

    run_test("Apps have process_id field", U + " --sim list-apps",
        [](const std::string& o) { return json_contains(o, "\"process_id\":"); });

    run_test("Apps have app_category field", U + " --sim list-apps",
        [](const std::string& o) { return json_contains(o, "\"app_category\":"); });

    run_test("Apps have bounds field", U + " --sim list-apps",
        [](const std::string& o) { return json_contains(o, "\"bounds\":"); });

    run_test("Facebook is focused", U + " --sim list-apps",
        [](const std::string& o) { return json_contains(o, "\"is_focused\":true"); });

    run_test("Apps have platform field", U + " --sim list-apps",
        [](const std::string& o) { return json_contains(o, "\"platform\":\"simulation\""); });

    // ========== CATEGORY 2: Active App Detection (13-22) ==========
    std::cout << std::endl << "--- Category 2: Active App Detection ---" << std::endl;

    run_test("Get-active-app returns Facebook", U + " --sim get-active-app",
        [](const std::string& o) { return json_contains_ci(o, "Facebook"); });

    run_test("Active app has social_media category", U + " --sim get-active-app",
        [](const std::string& o) { return json_contains(o, "\"app_category\":\"social_media\""); });

    run_test("Active app is focused", U + " --sim get-active-app",
        [](const std::string& o) { return json_contains(o, "\"is_focused\":true"); });

    run_test("Active app has process_name", U + " --sim get-active-app",
        [](const std::string& o) { return json_contains(o, "\"process_name\":\"facebook.exe\""); });

    run_test("Active app has window_id", U + " --sim get-active-app",
        [](const std::string& o) { return json_contains(o, "\"window_id\":\"sim_fb\""); });

    run_test("Active app has bounds", U + " --sim get-active-app",
        [](const std::string& o) { return json_contains(o, "\"bounds\":"); });

    run_test("Active app has platform simulation", U + " --sim get-active-app",
        [](const std::string& o) { return json_contains(o, "\"platform\":\"simulation\""); });

    run_test("Active app process_id > 0", U + " --sim get-active-app",
        [](const std::string& o) { return json_get_int(o, "process_id") > 0; });

    run_test("Active app is visible", U + " --sim get-active-app",
        [](const std::string& o) { return json_contains(o, "\"is_visible\":true"); });

    run_test("Active app not minimized", U + " --sim get-active-app",
        [](const std::string& o) { return json_contains(o, "\"is_minimized\":false"); });

    // ========== CATEGORY 3: App Classification (23-35) ==========
    std::cout << std::endl << "--- Category 3: App Classification ---" << std::endl;

    run_test("Facebook classified as social_media", U + " --sim list-apps",
        [](const std::string& o) { return json_contains(o, "\"app_category\":\"social_media\""); });

    run_test("Chrome classified as browser", U + " --sim list-apps",
        [](const std::string& o) { return json_contains(o, "\"app_category\":\"browser\""); });

    run_test("VS Code classified as ide", U + " --sim list-apps",
        [](const std::string& o) { return json_contains(o, "\"app_category\":\"ide\""); });

    run_test("Spotify classified as media_player", U + " --sim list-apps",
        [](const std::string& o) { return json_contains(o, "\"app_category\":\"media_player\""); });

    run_test("Outlook classified as email", U + " --sim list-apps",
        [](const std::string& o) { return json_contains(o, "\"app_category\":\"email\""); });

    run_test("Spotify is minimized", U + " --sim list-apps",
        [](const std::string& o) { return json_contains(o, "\"is_minimized\":true"); });

    run_test("Chrome is not focused", U + " --sim list-apps",
        [](const std::string& o) {
            // Chrome should have is_focused:false
            size_t chrome_pos = o.find("Chrome");
            if (chrome_pos == std::string::npos) return false;
            size_t focused_pos = o.find("\"is_focused\":false", chrome_pos);
            return focused_pos != std::string::npos;
        });

    run_test("All apps have unique window_ids", U + " --sim list-apps",
        [](const std::string& o) {
            return json_contains(o, "sim_fb") && json_contains(o, "sim_chrome") &&
                   json_contains(o, "sim_vscode") && json_contains(o, "sim_spotify") &&
                   json_contains(o, "sim_outlook");
        });

    run_test("All apps have process names", U + " --sim list-apps",
        [](const std::string& o) {
            return json_contains(o, "facebook.exe") && json_contains(o, "chrome.exe") &&
                   json_contains(o, "code.exe") && json_contains(o, "spotify.exe") &&
                   json_contains(o, "outlook.exe");
        });

    run_test("Facebook has correct process_id", U + " --sim list-apps",
        [](const std::string& o) { return json_contains(o, "\"process_id\":2001"); });

    run_test("Chrome has correct process_id", U + " --sim list-apps",
        [](const std::string& o) { return json_contains(o, "\"process_id\":2002"); });

    run_test("VS Code has correct process_id", U + " --sim list-apps",
        [](const std::string& o) { return json_contains(o, "\"process_id\":2003"); });

    // ========== CATEGORY 4: Screen Capture (36-45) ==========
    std::cout << std::endl << "--- Category 4: Screen Capture ---" << std::endl;

    run_test("Capture-screen in sim returns success", U + " --sim capture-screen",
        [](const std::string& o) { return json_contains(o, "\"success\":true"); });

    run_test("Capture-screen has file_path", U + " --sim capture-screen",
        [](const std::string& o) { return json_contains(o, "\"file_path\":\""); });

    run_test("Capture-screen has width 1920", U + " --sim capture-screen",
        [](const std::string& o) { return json_get_int(o, "width") == 1920; });

    run_test("Capture-screen has height 1080", U + " --sim capture-screen",
        [](const std::string& o) { return json_get_int(o, "height") == 1080; });

    run_test("Capture-screen has format bmp", U + " --sim capture-screen",
        [](const std::string& o) { return json_contains(o, "\"format\":\"bmp\""); });

    run_test("Capture-window sim_fb returns success", U + " --sim capture-window sim_fb",
        [](const std::string& o) { return json_contains(o, "\"success\":true"); });

    run_test("Capture-window has correct width", U + " --sim capture-window sim_fb",
        [](const std::string& o) { return json_get_int(o, "width") == 900; });

    run_test("Capture-window has correct height", U + " --sim capture-window sim_fb",
        [](const std::string& o) { return json_get_int(o, "height") == 700; });

    run_test("Capture-region returns success", U + " --sim capture-region 100 100 500 300",
        [](const std::string& o) { return json_contains(o, "\"success\":true"); });

    run_test("Capture-region has correct dimensions", U + " --sim capture-region 100 100 500 300",
        [](const std::string& o) { return json_get_int(o, "width") == 500 && json_get_int(o, "height") == 300; });

    // ========== CATEGORY 5: OCR / Text Extraction (46-55) ==========
    std::cout << std::endl << "--- Category 5: OCR / Text Extraction ---" << std::endl;

    run_test("OCR-screen returns success", U + " --sim ocr-screen",
        [](const std::string& o) { return json_contains(o, "\"success\":true"); });

    run_test("OCR-screen has full_text with content", U + " --sim ocr-screen",
        [](const std::string& o) { return json_contains(o, "\"full_text\":\"") && o.size() > 50; });

    run_test("OCR-screen has regions", U + " --sim ocr-screen",
        [](const std::string& o) { return json_contains(o, "\"regions\":"); });

    run_test("OCR-screen finds morning run text", U + " --sim ocr-screen",
        [](const std::string& o) { return json_contains_ci(o, "morning run"); });

    run_test("OCR-screen finds AI model text", U + " --sim ocr-screen",
        [](const std::string& o) { return json_contains_ci(o, "AI model"); });

    run_test("OCR-window sim_fb returns success", U + " --sim ocr-window sim_fb",
        [](const std::string& o) { return json_contains(o, "\"success\":true"); });

    run_test("OCR-window sim_fb has content", U + " --sim ocr-window sim_fb",
        [](const std::string& o) { return json_contains_ci(o, "morning run"); });

    run_test("OCR-region finds content in bounds", U + " --sim ocr-region 100 50 1000 200",
        [](const std::string& o) { return json_contains_ci(o, "morning run"); });

    run_test("OCR-region outside content returns empty", U + " --sim ocr-region 5000 5000 100 100",
        [](const std::string& o) { return json_get_int(o, "total_regions") == 0; });

    run_test("OCR-screen has confidence field", U + " --sim ocr-screen",
        [](const std::string& o) { return json_contains(o, "\"confidence\":"); });

    // ========== CATEGORY 6: Content Extraction (56-70) ==========
    std::cout << std::endl << "--- Category 6: Content Extraction ---" << std::endl;

    run_test("Get-content returns blocks", U + " --sim get-content",
        [](const std::string& o) { return json_get_int(o, "total_blocks") > 0; });

    run_test("Get-content has 24 blocks", U + " --sim get-content",
        [](const std::string& o) { return json_get_int(o, "total_blocks") == 24; });

    run_test("Get-content includes post type", U + " --sim get-content",
        [](const std::string& o) { return json_contains(o, "\"type\":\"post\""); });

    run_test("Get-content includes ad type", U + " --sim get-content",
        [](const std::string& o) { return json_contains(o, "\"type\":\"ad\""); });

    run_test("Get-content includes comment type", U + " --sim get-content",
        [](const std::string& o) { return json_contains(o, "\"type\":\"comment\""); });

    run_test("Get-content has author field", U + " --sim get-content",
        [](const std::string& o) { return json_contains(o, "\"author\":\"Sarah Johnson\""); });

    run_test("Get-content has relevance field", U + " --sim get-content",
        [](const std::string& o) { return json_contains(o, "\"relevance\":"); });

    run_test("Get-content has source field", U + " --sim get-content",
        [](const std::string& o) { return json_contains(o, "\"source\":\"Facebook\""); });

    run_test("Get-content has timestamp field", U + " --sim get-content",
        [](const std::string& o) { return json_contains(o, "\"timestamp\":\"2026-08-05"); });

    run_test("Get-content for sim_fb returns blocks", U + " --sim get-content sim_fb",
        [](const std::string& o) { return json_get_int(o, "total_blocks") > 0; });

    run_test("Get-content includes Sarah's post", U + " --sim get-content",
        [](const std::string& o) { return json_contains_ci(o, "Sarah Johnson"); });

    run_test("Get-content includes Tech News post", U + " --sim get-content",
        [](const std::string& o) { return json_contains_ci(o, "Tech News Daily"); });

    run_test("Get-content includes Mike's post", U + " --sim get-content",
        [](const std::string& o) { return json_contains_ci(o, "Mike Chen"); });

    run_test("Get-content includes John's comment", U + " --sim get-content",
        [](const std::string& o) { return json_contains_ci(o, "John Davis"); });

    run_test("Get-content includes sponsored ad", U + " --sim get-content",
        [](const std::string& o) { return json_contains_ci(o, "SportsMart") && json_contains_ci(o, "Sponsored"); });

    // ========== CATEGORY 7: Context Assessment (71-85) ==========
    std::cout << std::endl << "--- Category 7: Context Assessment ---" << std::endl;

    run_test("Get-context returns valid JSON", U + " --sim get-context",
        [](const std::string& o) { return o.size() > 0 && o[0] == '{'; });

    run_test("Get-context active_app is Facebook", U + " --sim get-context",
        [](const std::string& o) { return json_contains_ci(o, "Facebook"); });

    run_test("Get-context category is social_media", U + " --sim get-context",
        [](const std::string& o) { return json_contains(o, "\"active_app_category\":\"social_media\""); });

    run_test("Get-context activity is scrolling", U + " --sim get-context",
        [](const std::string& o) { return json_contains(o, "\"user_activity\":\"scrolling\""); });

    run_test("Get-context has assessment text", U + " --sim get-context",
        [](const std::string& o) { return json_contains(o, "\"assessment\":\""); });

    run_test("Get-context assessment mentions scrolling", U + " --sim get-context",
        [](const std::string& o) { return json_contains_ci(o, "scrolling"); });

    run_test("Get-context assessment mentions posts", U + " --sim get-context",
        [](const std::string& o) { return json_contains_ci(o, "posts"); });

    run_test("Get-context has suggested_actions", U + " --sim get-context",
        [](const std::string& o) { return json_contains(o, "\"suggested_actions\":"); });

    run_test("Get-context has 4 suggested actions", U + " --sim get-context",
        [](const std::string& o) {
            // Count occurrences of action entries
            size_t count = 0;
            std::string search = "suggested_actions\":[";
            size_t pos = o.find(search);
            if (pos == std::string::npos) return false;
            pos += search.size();
            while (pos < o.size()) {
                if (o[pos] == '"') { count++; while (pos < o.size() && o[pos] != ']') { if (o[pos] == '"') {pos++; break;} pos++; } }
                else if (o[pos] == ']') break;
                pos++;
            }
            return count >= 4;
        });

    run_test("Get-context suggests discussing posts", U + " --sim get-context",
        [](const std::string& o) { return json_contains_ci(o, "discuss"); });

    run_test("Get-context suggests email reminder", U + " --sim get-context",
        [](const std::string& o) { return json_contains_ci(o, "unread emails"); });

    run_test("Get-context suggests coding help", U + " --sim get-context",
        [](const std::string& o) { return json_contains_ci(o, "C++ code"); });

    run_test("Get-context has open_apps", U + " --sim get-context",
        [](const std::string& o) { return json_contains(o, "\"open_apps\":"); });

    run_test("Get-context has visible_content", U + " --sim get-context",
        [](const std::string& o) { return json_contains(o, "\"visible_content\":"); });

    // ========== CATEGORY 8: Edge Cases (86-95) ==========
    std::cout << std::endl << "--- Category 8: Edge Cases ---" << std::endl;

    run_test("Platform returns simulation in sim mode", U + " --sim platform",
        [](const std::string& o) { return json_contains(o, "\"platform\":\"simulation\""); });

    run_test("Capture-window non-existent returns error", U + " --sim capture-window nonexist",
        [](const std::string& o) { return json_contains(o, "\"success\":false"); });

    run_test("OCR-window non-existent returns error", U + " --sim ocr-window nonexist",
        [](const std::string& o) { return json_contains(o, "\"error\":\""); });

    run_test("Get-content for non-existent window returns 0 blocks", U + " --sim get-content nonexist",
        [](const std::string& o) { return json_get_int(o, "total_blocks") == 0; });

    run_test("Capture-screen with custom path", U + " --sim capture-screen custom.bmp",
        [](const std::string& o) { return json_contains(o, "custom.bmp"); });

    run_test("Capture-window with custom path", U + " --sim capture-window sim_fb custom_win.bmp",
        [](const std::string& o) { return json_contains(o, "custom_win.bmp"); });

    run_test("OCR-region with zero size", U + " --sim ocr-region 0 0 0 0",
        [](const std::string& o) { return json_get_int(o, "total_regions") == 0; });

    run_test("OCR-region with negative coords", U + " --sim ocr-region -10 -10 100 100",
        [](const std::string& o) { return json_get_int(o, "total_regions") == 0; });

    run_test("Assess command alias works", U + " --sim assess",
        [](const std::string& o) { return json_contains(o, "\"assessment\":"); });

    run_test("Get-context has timestamp", U + " --sim get-context",
        [](const std::string& o) { return json_contains(o, "\"timestamp\":\""); });

    // ========== CATEGORY 9: AI Agent Real-World Scenarios (96-100) ==========
    std::cout << std::endl << "--- Category 9: AI Agent Real-World Scenarios ---" << std::endl;

    run_test("AI: Full context workflow", U + " --sim get-context",
        [](const std::string& o) {
            return json_contains(o, "\"active_app\":") &&
                   json_contains(o, "\"user_activity\":") &&
                   json_contains(o, "\"assessment\":") &&
                   json_contains(o, "\"suggested_actions\":");
        });

    run_test("AI: Can see user is on Facebook", U + " --sim get-context",
        [](const std::string& o) {
            return json_contains_ci(o, "Facebook") &&
                   json_contains(o, "\"active_app_category\":\"social_media\"");
        });

    run_test("AI: Can read posts visible to user", U + " --sim get-content",
        [](const std::string& o) {
            return json_contains_ci(o, "Sarah Johnson") &&
                   json_contains_ci(o, "Tech News Daily") &&
                   json_contains_ci(o, "Mike Chen");
        });

    run_test("AI: Can identify ads vs posts", U + " --sim get-content",
        [](const std::string& o) {
            return json_contains(o, "\"type\":\"ad\"") &&
                   json_contains(o, "\"type\":\"post\"");
        });

    run_test("AI: Can suggest relevant actions", U + " --sim get-context",
        [](const std::string& o) {
            return json_contains_ci(o, "discuss") &&
                   json_contains_ci(o, "emails") &&
                   json_contains_ci(o, "code");
        });

    run_test("AI: Context includes all 5 open apps", U + " --sim get-context",
        [](const std::string& o) {
            return json_contains_ci(o, "Facebook") &&
                   json_contains_ci(o, "Chrome") &&
                   json_contains_ci(o, "Visual Studio Code") &&
                   json_contains_ci(o, "Spotify") &&
                   json_contains_ci(o, "Outlook");
        });

    run_test("AI: Assessment mentions pending tasks", U + " --sim get-context",
        [](const std::string& o) {
            return json_contains_ci(o, "coding") &&
                   json_contains_ci(o, "email");
        });

    // ========== SUMMARY ==========
    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << " SCREEN CONTEXT READER TEST SUMMARY" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  Total:  " << tests_total << std::endl;
    std::cout << "  Passed: " << tests_passed << std::endl;
    std::cout << "  Failed: " << tests_failed << std::endl;
    std::cout << "  Rate:   " << (100.0 * tests_passed / tests_total) << "%" << std::endl;
    std::cout << "========================================" << std::endl;

    return tests_failed > 0 ? 1 : 0;
}
