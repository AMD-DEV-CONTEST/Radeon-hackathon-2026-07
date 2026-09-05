// test_runner_ui4.cpp - Real-World UI Locator Tests
// Tests finding buttons and functions across 10 real-world app types
// Designed to find bugs in real-world usage scenarios

#include <string>
#include <iostream>
#include <cstdio>
#include <regex>
#include <functional>
#include <vector>

#ifdef _WIN32
#define popen _popen
#define pclose _pclose
#endif

static const std::string U = "uilocator.exe";

static int g_pass = 0, g_fail = 0, g_total = 0;

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

static bool json_contains(const std::string& json, const std::string& key) {
    return json.find(key) != std::string::npos;
}

static int json_get_int(const std::string& json, const std::string& key) {
    std::regex re("\"" + key + "\"\\s*:\\s*(-?\\d+)");
    std::smatch m;
    if (std::regex_search(json, m, re)) {
        return std::atoi(m[1].str().c_str());
    }
    return -1;
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
    g_total++;
    std::string output = exec_command(cmd);
    bool ok = checker(output);
    std::cout << "[" << (g_total < 10 ? " " : "") << g_total << "] "
              << (name.size() > 65 ? name.substr(0, 62) + "..." : name)
              << std::string(70 - std::min((size_t)70, name.size() + 4), ' ')
              << (ok ? "PASS" : "FAIL") << std::endl;
    if (!ok) {
        g_fail++;
        std::string trimmed = output.size() > 200 ? output.substr(0, 200) + "..." : output;
        std::cout << "       Output: " << trimmed << std::endl;
    } else {
        g_pass++;
    }
}

int main() {
    std::cout << "========================================" << std::endl;
    std::cout << " UI LOCATOR REAL-WORLD TEST SUITE" << std::endl;
    std::cout << " 10 App Types - 100 Tests" << std::endl;
    std::cout << "========================================" << std::endl;

    // ========== CATEGORY 1: IDE - Finding Code Actions (1-10) ==========
    std::cout << std::endl << "--- Category 1: IDE (VS Code-like) ---" << std::endl;

    run_test("IDE: Find Run menu item", U + " --sim search Run --window sim_win_ide",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("IDE: Find Terminal menu item", U + " --sim search Terminal --window sim_win_ide",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("IDE: Find Explorer in activity bar", U + " --sim search Explorer --window sim_win_ide",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("IDE: Find Source Control button", U + " --sim search \"Source Control\" --window sim_win_ide",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("IDE: Find Extensions button", U + " --sim search Extensions --window sim_win_ide",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("IDE: Find Command Palette", U + " --sim search \"Command Palette\" --window sim_win_ide",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("IDE: Find file main.cpp in tree", U + " --sim search main.cpp --window sim_win_ide",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("IDE: Find Debug activity (fuzzy: Debg)", U + " --sim search Debg --window sim_win_ide",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("IDE: Get all elements count > 25", U + " --sim get-elements sim_win_ide",
        [](const std::string& o) { return json_get_int(o, "total_elements") > 25; });

    run_test("IDE: Find-by-path Explorer/main.cpp", U + " --sim find-by-path sim_win_ide/main.cpp",
        [](const std::string& o) { return json_get_int(o, "total_elements") > 0; });

    // ========== CATEGORY 2: Spreadsheet - Finding Data Actions (11-20) ==========
    std::cout << std::endl << "--- Category 2: Spreadsheet (Excel-like) ---" << std::endl;

    run_test("SS: Find AutoSum button", U + " --sim search AutoSum --window sim_win_spreadsheet",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("SS: Find Sort Ascending button", U + " --sim search \"Sort Ascending\" --window sim_win_spreadsheet",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("SS: Find Format Cells button", U + " --sim search \"Format Cells\" --window sim_win_spreadsheet",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("SS: Find Formulas tab", U + " --sim search Formulas --window sim_win_spreadsheet",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("SS: Find formula bar (text_field)", U + " --sim search formula --window sim_win_spreadsheet --type text_field",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("SS: Find Bold button", U + " --sim search Bold --window sim_win_spreadsheet",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("SS: Find cell A1", U + " --sim search A1 --window sim_win_spreadsheet",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("SS: Find all table cells", U + " --sim search --type table_cell --window sim_win_spreadsheet",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("SS: Find Data tab", U + " --sim search Data --window sim_win_spreadsheet",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("SS: Get element at formula bar center", U + " --sim find-at 650 185",
        [](const std::string& o) { return o.size() > 0 && json_contains(o, "\"id\":\""); });

    // ========== CATEGORY 3: Media Player - Finding Playback Controls (21-30) ==========
    std::cout << std::endl << "--- Category 3: Media Player (VLC-like) ---" << std::endl;

    run_test("Media: Find Play button", U + " --sim search Play --window sim_win_media",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Media: Find Pause button (disabled)", U + " --sim search Pause --window sim_win_media",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Media: Find Fullscreen button", U + " --sim search Fullscreen --window sim_win_media",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Media: Find Mute button", U + " --sim search Mute --window sim_win_media",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Media: Find Volume slider", U + " --sim search Volume --window sim_win_media --type slider",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Media: Find Subtitle menu", U + " --sim search Subtitle --window sim_win_media",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Media: Find Previous button", U + " --sim search Previous --window sim_win_media",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Media: Find Next button", U + " --sim search Next --window sim_win_media",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Media: Is Pause disabled?", U + " --sim is-enabled mp_ctrl_1",
        [](const std::string& o) { return json_contains(o, "\"enabled\":false"); });

    run_test("Media: Find seek bar (slider)", U + " --sim search Seek --window sim_win_media --type slider",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    // ========== CATEGORY 4: File Manager - Finding Navigation (31-40) ==========
    std::cout << std::endl << "--- Category 4: File Manager (Explorer-like) ---" << std::endl;

    run_test("FM: Find Back button", U + " --sim search Back --window sim_win_filemgr",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("FM: Find Forward button (disabled)", U + " --sim search Forward --window sim_win_filemgr",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("FM: Find Refresh button", U + " --sim search Refresh --window sim_win_filemgr",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("FM: Find Downloads in sidebar", U + " --sim search Downloads --window sim_win_filemgr",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("FM: Find Documents in sidebar", U + " --sim search Documents --window sim_win_filemgr",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("FM: Find search bar", U + " --sim search \"Search files\" --window sim_win_filemgr",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("FM: Find file resume.pdf", U + " --sim search resume.pdf --window sim_win_filemgr",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("FM: Find all list items", U + " --sim search --type list_item --window sim_win_filemgr",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 10; });

    // Note: search --type with empty query was a bug - now fixed

    run_test("FM: Is Forward disabled?", U + " --sim is-enabled fm_nav_btn_1",
        [](const std::string& o) { return json_contains(o, "\"enabled\":false"); });

    run_test("FM: Find-by-path Quick Access/Downloads", U + " --sim find-by-path sim_win_filemgr/Downloads",
        [](const std::string& o) { return json_get_int(o, "total_elements") > 0; });

    // ========== CATEGORY 5: Email Client - Finding Mail Actions (41-50) ==========
    std::cout << std::endl << "--- Category 5: Email Client (Outlook-like) ---" << std::endl;

    run_test("Email: Find New Email button", U + " --sim search \"New Email\" --window sim_win_email",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Email: Find Reply button (disabled)", U + " --sim search Reply --window sim_win_email",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Email: Find Delete button", U + " --sim search Delete --window sim_win_email",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Email: Find Archive button", U + " --sim search Archive --window sim_win_email",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Email: Find Send/Receive button", U + " --sim search Send --window sim_win_email",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Email: Find Inbox folder", U + " --sim search Inbox --window sim_win_email",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Email: Find email subject Meeting", U + " --sim search Meeting --window sim_win_email",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Email: Is Reply disabled?", U + " --sim is-enabled em_btn_1",
        [](const std::string& o) { return json_contains(o, "\"enabled\":false"); });

    run_test("Email: Find all buttons", U + " --sim search --type button --window sim_win_email",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 10; });

    run_test("Email: Find search bar", U + " --sim search \"Search Mail\" --window sim_win_email",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    // ========== CATEGORY 6: Terminal - Finding Console Actions (51-60) ==========
    std::cout << std::endl << "--- Category 6: Terminal / Console ---" << std::endl;

    run_test("Terminal: Find New Tab button", U + " --sim search \"New Tab\" --window sim_win_terminal",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Terminal: Find Split Pane button", U + " --sim search \"Split Pane\" --window sim_win_terminal",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Terminal: Find Search menu", U + " --sim search Search --window sim_win_terminal",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Terminal: Find Terminal menu", U + " --sim search Terminal --window sim_win_terminal",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Terminal: Find text area (focused)", U + " --sim search --type text_area --window sim_win_terminal",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Terminal: Find scrollbar", U + " --sim search --type scrollbar --window sim_win_terminal",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Terminal: Get focused element", U + " --sim get-focused",
        [](const std::string& o) { return json_contains(o, "\"focused\":true"); });

    run_test("Terminal: Find File menu", U + " --sim search File --window sim_win_terminal",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Terminal: Element count > 8", U + " --sim get-elements sim_win_terminal",
        [](const std::string& o) { return json_get_int(o, "total_elements") > 8; });

    run_test("Terminal: Find-by-path terminal/New Tab", U + " --sim find-by-path sim_win_terminal/\"New Tab\"",
        [](const std::string& o) { return json_get_int(o, "total_elements") > 0; });

    // ========== CATEGORY 7: Cross-App AI Agent Scenarios (61-75) ==========
    std::cout << std::endl << "--- Category 7: Cross-App AI Agent Scenarios ---" << std::endl;

    run_test("AI: Find 'Save' across all apps", U + " --sim search Save",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("AI: Find 'File' menu across all apps", U + " --sim search File",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 3; });

    run_test("AI: Find 'Help' menu across all apps", U + " --sim search Help",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 3; });

    run_test("AI: Find 'View' menu across all apps", U + " --sim search View",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 3; });

    run_test("AI: Find all buttons across all apps", U + " --sim search --type button",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 30; });

    run_test("AI: Find all text_fields across all apps", U + " --sim search --type text_field",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 3; });

    run_test("AI: Find all tabs across all apps", U + " --sim search --type tab",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 5; });

    run_test("AI: Find all menu_items across all apps", U + " --sim search --type menu_item",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 20; });

    run_test("AI: Find all sliders across all apps", U + " --sim search --type slider",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 3; });

    run_test("AI: Find all labels across all apps", U + " --sim search --type label",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("AI: Total element count > 150", U + " --sim get-all-elements",
        [](const std::string& o) { return json_get_int(o, "total_elements") > 150; });

    run_test("AI: Total window count = 10", U + " --sim list-windows",
        [](const std::string& o) { return json_get_int(o, "total_windows") == 10; });

    run_test("AI: Search-clickable finds clickable elements", U + " --sim search-clickable",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("AI: Search-clickable with filter 'Play'", U + " --sim search-clickable Play",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("AI: Search-inputs finds text inputs", U + " --sim search-inputs",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 3; });

    // ========== CATEGORY 8: Fuzzy Search Real-World Typos (76-85) ==========
    std::cout << std::endl << "--- Category 8: Fuzzy Search Real-World Typos ---" << std::endl;

    run_test("Fuzzy: 'Extensons' finds Extensions", U + " --sim search Extensons --window sim_win_ide",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Fuzzy: 'Refesh' finds Refresh", U + " --sim search Refesh --window sim_win_filemgr",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Fuzzy: 'Fullscreen' typo 'Fullscren'", U + " --sim search Fullscren --window sim_win_media",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Fuzzy: 'Achive' finds Archive", U + " --sim search Achive --window sim_win_email",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Fuzzy: 'Delte' finds Delete", U + " --sim search Delte --window sim_win_email",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Fuzzy: 'Autosum' finds AutoSum", U + " --sim search Autosum --window sim_win_spreadsheet",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Fuzzy: 'Fullsreen' finds Fullscreen", U + " --sim search Fullsreen --window sim_win_media",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Fuzzy: 'Command Palet' finds Command Palette", U + " --sim search \"Command Palet\" --window sim_win_ide",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Fuzzy: 'Split Pan' finds Split Pane", U + " --sim search \"Split Pan\" --window sim_win_terminal",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Fuzzy: 'Sorce Control' finds Source Control", U + " --sim search \"Sorce Control\" --window sim_win_ide",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    // ========== CATEGORY 9: Coordinate-Based Finding Across Apps (86-95) ==========
    std::cout << std::endl << "--- Category 9: Coordinate-Based Finding Across Apps ---" << std::endl;

    run_test("Coord: Find-at IDE Run menu center (325,15)", U + " --sim find-at 325 15",
        [](const std::string& o) { return json_contains(o, "Run"); });

    run_test("Coord: Find-at SS Bold button center (92,97)", U + " --sim find-at 92 97",
        [](const std::string& o) { return json_contains(o, "ss_btn_"); });

    run_test("Coord: Find-at Media Play button center (232,572)", U + " --sim find-at 232 572",
        [](const std::string& o) { return json_contains(o, "Play"); });

    run_test("Coord: Find-at FM Back button center (172,99)", U + " --sim find-at 172 99",
        [](const std::string& o) { return json_contains(o, "Back"); });

    run_test("Coord: Find-at Email New Email button center (52,25)", U + " --sim find-at 52 25",
        [](const std::string& o) { return o.size() > 0 && json_contains(o, "\"id\":\""); });

    run_test("Coord: Nearest-clickable to IDE Run menu", U + " --sim nearest-clickable 325 15 50",
        [](const std::string& o) { return json_contains(o, "\"id\":\""); });

    run_test("Coord: Nearest-by-type button near SS area", U + " --sim nearest-by-type 100 90 button 200",
        [](const std::string& o) { return json_contains(o, "\"id\":\""); });

    run_test("Coord: Nearest-by-text 'Play' near media area", U + " --sim nearest-by-text 232 572 Play 100",
        [](const std::string& o) { return json_contains(o, "Play"); });

    run_test("Coord: Find-at at IDE editor center (900,500)", U + " --sim find-at 900 500",
        [](const std::string& o) { return o.size() > 0 && json_contains(o, "\"id\":\""); });

    run_test("Coord: Find-at at Terminal text center (850,500)", U + " --sim find-at 850 500",
        [](const std::string& o) { return o.size() > 0 && json_contains(o, "\"id\":\""); });

    // ========== CATEGORY 10: Element Hierarchy & State Across Apps (96-100) ==========
    std::cout << std::endl << "--- Category 10: Element Hierarchy & State Across Apps ---" << std::endl;

    run_test("Tree: Get IDE activity bar children", U + " --sim get-children ide_activitybar",
        [](const std::string& o) { return json_get_int(o, "total_elements") >= 5; });

    run_test("Tree: Get SS ribbon children", U + " --sim get-children ss_ribbon",
        [](const std::string& o) { return json_get_int(o, "total_elements") >= 10; });

    run_test("Tree: Get Email folders children", U + " --sim get-children em_folders",
        [](const std::string& o) { return json_get_int(o, "total_elements") >= 7; });

    run_test("State: IDE editor is focused", U + " --sim element-state ide_editor",
        [](const std::string& o) { return json_contains(o, "\"focused\":true"); });

    run_test("State: SS cell A1 is selected", U + " --sim element-state ss_cell_0",
        [](const std::string& o) { return json_contains(o, "\"selected\":true"); });

    // ========== SUMMARY ==========
    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << " UI LOCATOR REAL-WORLD TEST SUMMARY" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  Total:  " << g_total << std::endl;
    std::cout << "  Passed: " << g_pass << std::endl;
    std::cout << "  Failed: " << g_fail << std::endl;
    std::cout << "  Rate:   " << (g_pass * 100 / g_total) << "." << ((g_pass * 1000 / g_total) % 10) << "%" << std::endl;
    std::cout << "========================================" << std::endl;

    return g_fail > 0 ? 1 : 0;
}
