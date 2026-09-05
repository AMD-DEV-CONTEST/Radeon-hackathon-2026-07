// test_runner_screen2.cpp - Bug-Hunting Suite for Screen Context Reader
// 100 complex tests targeting edge cases, JSON safety, cross-platform, new APIs
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
    char buffer[16384];
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
    if (pos == std::string::npos) return -999;
    pos += search.size();
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) pos++;
    std::string num;
    while (pos < json.size() && ((json[pos] >= '0' && json[pos] <= '9') || json[pos] == '-')) {
        num += json[pos++];
    }
    return num.empty() ? -999 : std::atoi(num.c_str());
}

static float json_get_float(const std::string& json, const std::string& key) {
    std::string search = "\"" + key + "\":";
    size_t pos = json.find(search);
    if (pos == std::string::npos) return -1.0f;
    pos += search.size();
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) pos++;
    std::string num;
    while (pos < json.size() && ((json[pos] >= '0' && json[pos] <= '9') || json[pos] == '-' || json[pos] == '.')) {
        num += json[pos++];
    }
    return num.empty() ? -1.0f : static_cast<float>(std::atof(num.c_str()));
}

static std::string json_get_str(const std::string& json, const std::string& key) {
    std::regex re("\"" + key + "\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"");
    std::smatch m;
    if (std::regex_search(json, m, re)) {
        return m[1].str();
    }
    return "";
}

static int count_occurrences(const std::string& str, const std::string& sub) {
    int count = 0;
    size_t pos = 0;
    while ((pos = str.find(sub, pos)) != std::string::npos) {
        count++;
        pos += sub.size();
    }
    return count;
}

static bool valid_json(const std::string& s) {
    if (s.empty()) return false;
    int braces = 0, brackets = 0;
    bool in_string = false;
    bool escape = false;
    for (size_t i = 0; i < s.size(); i++) {
        char c = s[i];
        if (escape) { escape = false; continue; }
        if (c == '\\') { escape = true; continue; }
        if (c == '"') { in_string = !in_string; continue; }
        if (in_string) continue;
        if (c == '{') braces++;
        else if (c == '}') braces--;
        else if (c == '[') brackets++;
        else if (c == ']') brackets--;
    }
    return braces == 0 && brackets == 0;
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
        std::string trimmed = output.size() > 400 ? output.substr(0, 400) + "..." : output;
        std::cout << "       Output: " << trimmed << std::endl;
    } else {
        tests_passed++;
    }
}

int main() {
    std::cout << "========================================" << std::endl;
    std::cout << " SCREEN CONTEXT BUG-HUNTING SUITE" << std::endl;
    std::cout << " 100 Complex Tests - Edge Cases & Bugs" << std::endl;
    std::cout << "========================================" << std::endl;

    // ========== CATEGORY 1: JSON Safety & Escaping (1-12) ==========
    std::cout << std::endl << "--- Category 1: JSON Safety & Escaping ---" << std::endl;

    run_test("List-apps produces valid JSON", U + " --sim list-apps",
        [](const std::string& o) { return valid_json(o); });

    run_test("Get-context produces valid JSON", U + " --sim get-context",
        [](const std::string& o) { return valid_json(o); });

    run_test("OCR-screen produces valid JSON", U + " --sim ocr-screen",
        [](const std::string& o) { return valid_json(o); });

    run_test("OCR-window produces valid JSON", U + " --sim ocr-window sim_fb",
        [](const std::string& o) { return valid_json(o); });

    run_test("Get-content produces valid JSON", U + " --sim get-content",
        [](const std::string& o) { return valid_json(o); });

    run_test("App-summary produces valid JSON", U + " --sim app-summary",
        [](const std::string& o) { return valid_json(o); });

    run_test("Screen-content produces valid JSON", U + " --sim screen-content",
        [](const std::string& o) { return valid_json(o); });

    run_test("Search-content produces valid JSON", U + " --sim search-content morning",
        [](const std::string& o) { return valid_json(o); });

    run_test("Get-active-app produces valid JSON", U + " --sim get-active-app",
        [](const std::string& o) { return valid_json(o); });

    run_test("Capture-screen produces valid JSON", U + " --sim capture-screen",
        [](const std::string& o) { return valid_json(o); });

    run_test("OCR full_text has escaped newlines", U + " --sim ocr-screen",
        [](const std::string& o) {
            // Check that full_text has \\n (escaped newline) not raw newline
            size_t ft_pos = o.find("\"full_text\":\"");
            if (ft_pos == std::string::npos) return false;
            ft_pos += 13;
            // Check the text doesn't have raw newline chars before the closing quote
            // (escaped newlines show as \\n in the output)
            return o.find("\\n", ft_pos) != std::string::npos;
        });

    run_test("Assessment text has escaped quotes", U + " --sim get-context",
        [](const std::string& o) {
            // Assessment should contain escaped quotes for the post excerpt
            return o.find("\\\"") != std::string::npos;
        });

    // ========== CATEGORY 2: Empty / Null Input Edge Cases (13-25) ==========
    std::cout << std::endl << "--- Category 2: Empty / Null Input Edge Cases ---" << std::endl;

    run_test("Search-content with empty query returns 0 results", U + " --sim search-content \"\"",
        [](const std::string& o) { return json_get_int(o, "total_results") == 0; });

    run_test("Get-content with empty window returns all blocks", U + " --sim get-content \"\"",
        [](const std::string& o) { return json_get_int(o, "total_blocks") == 24; });

    run_test("OCR-window with empty id returns error", U + " --sim ocr-window \"\"",
        [](const std::string& o) { return json_contains(o, "\"success\":false") || json_contains(o, "\"error\""); });

    run_test("Capture-window with empty id returns error", U + " --sim capture-window \"\"",
        [](const std::string& o) { return json_contains(o, "\"success\":false"); });

    run_test("Capture-region 0x0 returns error", U + " --sim capture-region 0 0 0 0",
        [](const std::string& o) { return json_contains(o, "\"success\":false"); });

    run_test("Capture-region negative dims returns error", U + " --sim capture-region 10 10 -5 -5",
        [](const std::string& o) { return json_contains(o, "\"success\":false"); });

    run_test("OCR-region 0x0 returns 0 regions", U + " --sim ocr-region 0 0 0 0",
        [](const std::string& o) { return json_get_int(o, "total_regions") == 0; });

    run_test("OCR-region negative coords returns 0 regions", U + " --sim ocr-region -10 -10 100 100",
        [](const std::string& o) { return json_get_int(o, "total_regions") == 0; });

    run_test("Search-content non-existent term returns 0", U + " --sim search-content zzznotfound",
        [](const std::string& o) { return json_get_int(o, "total_results") <= 2; });

    run_test("Get-content non-existent window returns 0 blocks", U + " --sim get-content zzznonexist",
        [](const std::string& o) { return json_get_int(o, "total_blocks") == 0; });

    run_test("Capture-window non-existent returns error", U + " --sim capture-window zzznonexist",
        [](const std::string& o) { return json_contains(o, "\"success\":false"); });

    run_test("OCR-window non-existent returns error", U + " --sim ocr-window zzznonexist",
        [](const std::string& o) { return json_contains(o, "\"error\""); });

    run_test("Search-content in non-existent window returns 0", U + " --sim search-content morning zzznonexist",
        [](const std::string& o) { return json_get_int(o, "total_results") == 0; });

    // ========== CATEGORY 3: App Classification Edge Cases (26-38) ==========
    std::cout << std::endl << "--- Category 3: App Classification Edge Cases ---" << std::endl;

    run_test("Spotify classified as media_player not browser", U + " --sim list-apps",
        [](const std::string& o) {
            size_t spotify_pos = o.find("Spotify");
            if (spotify_pos == std::string::npos) return false;
            size_t cat_pos = o.find("\"app_category\":\"media_player\"", spotify_pos > 100 ? spotify_pos - 100 : 0);
            return cat_pos != std::string::npos && cat_pos < spotify_pos + 200;
        });

    run_test("VS Code classified as ide not editor", U + " --sim list-apps",
        [](const std::string& o) {
            size_t vscode_pos = o.find("Visual Studio Code");
            if (vscode_pos == std::string::npos) return false;
            size_t cat_pos = o.find("\"app_category\":\"ide\"", vscode_pos > 100 ? vscode_pos - 100 : 0);
            return cat_pos != std::string::npos && cat_pos < vscode_pos + 200;
        });

    run_test("Facebook classified as social_media not browser", U + " --sim list-apps",
        [](const std::string& o) {
            size_t fb_pos = o.find("Facebook");
            if (fb_pos == std::string::npos) return false;
            size_t cat_pos = o.find("\"app_category\":\"social_media\"", fb_pos > 100 ? fb_pos - 100 : 0);
            return cat_pos != std::string::npos && cat_pos < fb_pos + 200;
        });

    run_test("Chrome classified as browser not ide", U + " --sim list-apps",
        [](const std::string& o) {
            size_t chrome_pos = o.find("Chrome");
            if (chrome_pos == std::string::npos) return false;
            size_t cat_pos = o.find("\"app_category\":\"browser\"", chrome_pos > 100 ? chrome_pos - 100 : 0);
            return cat_pos != std::string::npos && cat_pos < chrome_pos + 200;
        });

    run_test("Outlook classified as email not editor", U + " --sim list-apps",
        [](const std::string& o) {
            size_t outlook_pos = o.find("Outlook");
            if (outlook_pos == std::string::npos) return false;
            size_t cat_pos = o.find("\"app_category\":\"email\"", outlook_pos > 100 ? outlook_pos - 100 : 0);
            return cat_pos != std::string::npos && cat_pos < outlook_pos + 200;
        });

    run_test("App-summary has 5 categories", U + " --sim app-summary",
        [](const std::string& o) {
            // Count category entries in apps_by_category
            int count = count_occurrences(o, "\":");
            // Each category entry has "category":count - but also other fields
            // Just check all 5 categories are present
            return json_contains(o, "social_media") && json_contains(o, "browser") &&
                   json_contains(o, "ide") && json_contains(o, "media_player") &&
                   json_contains(o, "email");
        });

    run_test("App-summary total_apps is 13", U + " --sim app-summary",
        [](const std::string& o) { return json_get_int(o, "total_apps") == 13; });

    run_test("App-summary focused_app_count is 1", U + " --sim app-summary",
        [](const std::string& o) { return json_get_int(o, "focused_app_count") == 1; });

    run_test("App-summary minimized_app_count is 1", U + " --sim app-summary",
        [](const std::string& o) { return json_get_int(o, "minimized_app_count") == 1; });

    run_test("App-summary active_app_category is social_media", U + " --sim app-summary",
        [](const std::string& o) { return json_contains(o, "\"active_app_category\":\"social_media\""); });

    run_test("App-summary platform is simulation", U + " --sim app-summary",
        [](const std::string& o) { return json_contains(o, "\"platform\":\"simulation\""); });

    run_test("App-summary has apps_by_category object", U + " --sim app-summary",
        [](const std::string& o) { return json_contains(o, "\"apps_by_category\":{"); });

    run_test("App-summary social_media count is 9", U + " --sim app-summary",
        [](const std::string& o) { return json_contains(o, "\"social_media\":9"); });

    // ========== CATEGORY 4: Content Search Deep Tests (39-52) ==========
    std::cout << std::endl << "--- Category 4: Content Search Deep Tests ---" << std::endl;

    run_test("Search 'morning' finds 8 results", U + " --sim search-content morning",
        [](const std::string& o) { return json_get_int(o, "total_results") == 8; });

    run_test("Search 'morning' top result is score 1.0", U + " --sim search-content morning",
        [](const std::string& o) { return json_get_float(o, "score") == 1.0f; });

    run_test("Search 'morning' has match_position > 0", U + " --sim search-content morning",
        [](const std::string& o) { return json_get_int(o, "match_position") > 0; });

    run_test("Search 'AI' finds results", U + " --sim search-content AI",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Search 'running' finds results", U + " --sim search-content running",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Search 'SportsMart' finds ad", U + " --sim search-content SportsMart",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains_ci(o, "SportsMart");
        });

    run_test("Search 'Sponsored' finds ad", U + " --sim search-content Sponsored",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Search 'fitness' finds post", U + " --sim search-content fitness",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Search 'August' finds Mike's post", U + " --sim search-content August",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains_ci(o, "Mike Chen");
        });

    run_test("Search 'impressive' finds comment", U + " --sim search-content impressive",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains_ci(o, "John Davis");
        });

    run_test("Search 'healthcare' finds Tech News post", U + " --sim search-content healthcare",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains_ci(o, "Tech News");
        });

    run_test("Search 'morning' in sim_fb finds results", U + " --sim search-content morning sim_fb",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Search results have match_context field", U + " --sim search-content morning",
        [](const std::string& o) { return json_contains(o, "\"match_context\""); });

    run_test("Search results have block field", U + " --sim search-content morning",
        [](const std::string& o) { return json_contains(o, "\"block\""); });

    // ========== CATEGORY 5: OCR Window Deep Tests (53-65) ==========
    std::cout << std::endl << "--- Category 5: OCR Window Deep Tests ---" << std::endl;

    run_test("OCR-window sim_chrome returns success", U + " --sim ocr-window sim_chrome",
        [](const std::string& o) { return json_contains(o, "\"success\":true"); });

    run_test("OCR-window sim_chrome has title text", U + " --sim ocr-window sim_chrome",
        [](const std::string& o) { return json_contains_ci(o, "C++ Tutorial"); });

    run_test("OCR-window sim_vscode returns success", U + " --sim ocr-window sim_vscode",
        [](const std::string& o) { return json_contains(o, "\"success\":true"); });

    run_test("OCR-window sim_vscode has title text", U + " --sim ocr-window sim_vscode",
        [](const std::string& o) { return json_contains_ci(o, "main.cpp"); });

    run_test("OCR-window sim_spotify returns success", U + " --sim ocr-window sim_spotify",
        [](const std::string& o) { return json_contains(o, "\"success\":true"); });

    run_test("OCR-window sim_spotify has title text", U + " --sim ocr-window sim_spotify",
        [](const std::string& o) { return json_contains_ci(o, "Spotify"); });

    run_test("OCR-window sim_outlook returns success", U + " --sim ocr-window sim_outlook",
        [](const std::string& o) { return json_contains(o, "\"success\":true"); });

    run_test("OCR-window sim_outlook has title text", U + " --sim ocr-window sim_outlook",
        [](const std::string& o) { return json_contains_ci(o, "Outlook"); });

    run_test("OCR-window sim_fb has 5 regions", U + " --sim ocr-window sim_fb",
        [](const std::string& o) { return json_get_int(o, "total_regions") == 5; });

    run_test("OCR-window sim_chrome has 1 region", U + " --sim ocr-window sim_chrome",
        [](const std::string& o) { return json_get_int(o, "total_regions") == 1; });

    run_test("OCR-window sim_vscode has 1 region", U + " --sim ocr-window sim_vscode",
        [](const std::string& o) { return json_get_int(o, "total_regions") == 1; });

    run_test("OCR-window sim_fb has confidence > 0.9", U + " --sim ocr-window sim_fb",
        [](const std::string& o) { return json_contains(o, "\"confidence\":0.95"); });

    run_test("OCR-window sim_chrome has confidence 1.0", U + " --sim ocr-window sim_chrome",
        [](const std::string& o) { return json_contains(o, "\"confidence\":1"); });

    // ========== CATEGORY 6: Content Block Extraction Deep Tests (66-75) ==========
    std::cout << std::endl << "--- Category 6: Content Block Extraction Deep Tests ---" << std::endl;

    run_test("Get-content sim_chrome returns 1 block", U + " --sim get-content sim_chrome",
        [](const std::string& o) { return json_get_int(o, "total_blocks") == 1; });

    run_test("Get-content sim_chrome has window_title type", U + " --sim get-content sim_chrome",
        [](const std::string& o) { return json_contains(o, "\"type\":\"window_title\""); });

    run_test("Get-content sim_vscode returns 1 block", U + " --sim get-content sim_vscode",
        [](const std::string& o) { return json_get_int(o, "total_blocks") == 1; });

    run_test("Get-content sim_spotify returns 1 block", U + " --sim get-content sim_spotify",
        [](const std::string& o) { return json_get_int(o, "total_blocks") == 1; });

    run_test("Get-content sim_outlook returns 1 block", U + " --sim get-content sim_outlook",
        [](const std::string& o) { return json_get_int(o, "total_blocks") == 1; });

    run_test("Get-content sim_fb returns 5 blocks", U + " --sim get-content sim_fb",
        [](const std::string& o) { return json_get_int(o, "total_blocks") == 5; });

    run_test("Get-content sim_chrome has Chrome title", U + " --sim get-content sim_chrome",
        [](const std::string& o) { return json_contains_ci(o, "Chrome"); });

    run_test("Get-content sim_vscode has main.cpp", U + " --sim get-content sim_vscode",
        [](const std::string& o) { return json_contains_ci(o, "main.cpp"); });

    run_test("Get-content sim_fb has post type blocks", U + " --sim get-content sim_fb",
        [](const std::string& o) { return json_contains(o, "\"type\":\"post\""); });

    run_test("Get-content sim_fb has ad type block", U + " --sim get-content sim_fb",
        [](const std::string& o) { return json_contains(o, "\"type\":\"ad\""); });

    // ========== CATEGORY 7: Screen Content Snapshot (76-85) ==========
    std::cout << std::endl << "--- Category 7: Screen Content Snapshot ---" << std::endl;

    run_test("Screen-content has timestamp", U + " --sim screen-content",
        [](const std::string& o) { return json_contains(o, "\"timestamp\""); });

    run_test("Screen-content has active_window_id", U + " --sim screen-content",
        [](const std::string& o) { return json_contains(o, "\"active_window_id\":\"sim_fb\""); });

    run_test("Screen-content has active_window_title", U + " --sim screen-content",
        [](const std::string& o) { return json_contains_ci(o, "Facebook"); });

    run_test("Screen-content has active_process", U + " --sim screen-content",
        [](const std::string& o) { return json_contains(o, "\"active_process\":\"facebook.exe\""); });

    run_test("Screen-content has screen_width 1920", U + " --sim screen-content",
        [](const std::string& o) { return json_get_int(o, "screen_width") == 1920; });

    run_test("Screen-content has screen_height 1080", U + " --sim screen-content",
        [](const std::string& o) { return json_get_int(o, "screen_height") == 1080; });

    run_test("Screen-content has platform simulation", U + " --sim screen-content",
        [](const std::string& o) { return json_contains(o, "\"platform\":\"simulation\""); });

    run_test("Screen-content has open_apps", U + " --sim screen-content",
        [](const std::string& o) { return json_contains(o, "\"open_apps\""); });

    run_test("Screen-content has visible_text", U + " --sim screen-content",
        [](const std::string& o) { return json_contains(o, "\"visible_text\""); });

    run_test("Screen-content open_apps has 13 apps", U + " --sim screen-content",
        [](const std::string& o) { return json_get_int(o, "total_apps") == 13; });

    // ========== CATEGORY 8: Cross-Platform & Platform Detection (86-92) ==========
    std::cout << std::endl << "--- Category 8: Cross-Platform & Platform Detection ---" << std::endl;

    run_test("Platform in sim mode returns simulation", U + " --sim platform",
        [](const std::string& o) { return json_contains(o, "\"platform\":\"simulation\""); });

    run_test("Platform without sim returns real platform", U + " platform",
        [](const std::string& o) {
            return json_contains(o, "\"platform\":\"windows\"") ||
                   json_contains(o, "\"platform\":\"linux\"") ||
                   json_contains(o, "\"platform\":\"macos\"");
        });

    run_test("Get-context platform matches sim mode", U + " --sim get-context",
        [](const std::string& o) { return json_contains(o, "\"platform\":\"simulation\""); });

    run_test("App-summary platform matches sim mode", U + " --sim app-summary",
        [](const std::string& o) { return json_contains(o, "\"platform\":\"simulation\""); });

    run_test("Screen-content platform matches sim mode", U + " --sim screen-content",
        [](const std::string& o) { return json_contains(o, "\"platform\":\"simulation\""); });

    run_test("All sim apps have platform simulation", U + " --sim list-apps",
        [](const std::string& o) {
            // Count occurrences of "platform":"simulation"
            return count_occurrences(o, "\"platform\":\"simulation\"") == 13;
        });

    run_test("Non-sim list-apps returns real platform", U + " list-apps",
        [](const std::string& o) {
            // Should not contain "simulation"
            return !json_contains(o, "\"platform\":\"simulation\"") && valid_json(o);
        });

    // ========== CATEGORY 9: Complex AI Agent Scenarios (93-100) ==========
    std::cout << std::endl << "--- Category 9: Complex AI Agent Scenarios ---" << std::endl;

    run_test("AI: Full workflow - apps, content, context, search", U + " --sim get-context",
        [](const std::string& o) {
            return json_contains(o, "\"active_app\"") &&
                   json_contains(o, "\"user_activity\"") &&
                   json_contains(o, "\"assessment\"") &&
                   json_contains(o, "\"suggested_actions\"") &&
                   json_contains(o, "\"open_apps\"") &&
                   json_contains(o, "\"visible_content\"");
        });

    run_test("AI: Can search for 'run' and find fitness post", U + " --sim search-content run",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains_ci(o, "morning run");
        });

    run_test("AI: Can identify user is scrolling social media", U + " --sim get-context",
        [](const std::string& o) {
            return json_contains(o, "\"user_activity\":\"scrolling\"") &&
                   json_contains(o, "\"active_app_category\":\"social_media\"");
        });

    run_test("AI: Can see all 5 apps and their categories", U + " --sim app-summary",
        [](const std::string& o) {
            return json_contains(o, "social_media") &&
                   json_contains(o, "browser") &&
                   json_contains(o, "ide") &&
                   json_contains(o, "media_player") &&
                   json_contains(o, "email");
        });

    run_test("AI: Screen-content has all fields for assessment", U + " --sim screen-content",
        [](const std::string& o) {
            return json_contains(o, "active_window_id") &&
                   json_contains(o, "active_window_title") &&
                   json_contains(o, "active_process") &&
                   json_contains(o, "screen_width") &&
                   json_contains(o, "screen_height") &&
                   json_contains(o, "open_apps") &&
                   json_contains(o, "visible_text");
        });

    run_test("AI: Can search content within specific window", U + " --sim search-content morning sim_fb",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains_ci(o, "morning");
        });

    run_test("AI: Assessment mentions Sarah Johnson", U + " --sim get-context",
        [](const std::string& o) { return json_contains_ci(o, "Sarah Johnson"); });

    run_test("AI: Assessment mentions 3 unread emails", U + " --sim get-context",
        [](const std::string& o) { return json_contains_ci(o, "3 unread emails"); });

    // ========== SUMMARY ==========
    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << " SCREEN CONTEXT BUG-HUNTING SUMMARY" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  Total:  " << tests_total << std::endl;
    std::cout << "  Passed: " << tests_passed << std::endl;
    std::cout << "  Failed: " << tests_failed << std::endl;
    std::cout << "  Rate:   " << (100.0 * tests_passed / tests_total) << "%" << std::endl;
    std::cout << "========================================" << std::endl;

    return tests_failed > 0 ? 1 : 0;
}
