// test_runner_ui2.cpp - 100 complex situational tests for UI Locator Tool
// Tests: multi-monitor, element state, advanced actions, wait/poll, element path,
// window management, nearest element, export/import, shortcuts, regions,
// change detection, highlight, and complex AI agent real-world scenarios
#include <iostream>
#include <string>
#include <vector>
#include <sstream>
#include <iomanip>
#include <cstdlib>
#include <functional>

#ifdef _WIN32
#include <cstdio>
#define popen _popen
#define pclose _pclose
#endif

static int tests_passed = 0;
static int tests_failed = 0;
static int tests_total = 0;

static std::string exec_command(const std::string& cmd) {
    std::string result;
    FILE* pipe = popen(cmd.c_str(), "r");
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
    while (pos < json.size() && (json[pos] >= '0' && json[pos] <= '9')) {
        num += json[pos++];
    }
    if (num.empty()) return -1;
    return std::atoi(num.c_str());
}

static int count_occurrences(const std::string& json, const std::string& needle) {
    int count = 0;
    size_t pos = 0;
    while ((pos = json.find(needle, pos)) != std::string::npos) {
        count++;
        pos += needle.size();
    }
    return count;
}

static void run_test(const std::string& test_name, const std::string& cmd,
                     std::function<bool(const std::string&)> validator) {
    tests_total++;
    std::cout << "[" << std::setw(3) << tests_total << "] " << std::left << std::setw(65) << test_name << " ... ";
    std::cout.flush();

    std::string output = exec_command(cmd);

    bool passed = false;
    try {
        passed = validator(output);
    } catch (...) {
        passed = false;
    }

    if (passed) {
        tests_passed++;
        std::cout << "PASS" << std::endl;
    } else {
        tests_failed++;
        std::cout << "FAIL" << std::endl;
        if (output.size() > 300) output = output.substr(0, 300) + "...";
        std::cout << "       Output: " << output << std::endl;
    }
}

static std::string U = ".\\uilocator.exe";

int main() {
    std::cout << "========================================" << std::endl;
    std::cout << "  UI LOCATOR TEST SUITE 2 (100 tests)" << std::endl;
    std::cout << "  Advanced Features & Situational Tests" << std::endl;
    std::cout << "========================================" << std::endl;

    // ========== CATEGORY 1: Multi-Monitor Support (1-10) ==========
    std::cout << std::endl << "--- Category 1: Multi-Monitor Support ---" << std::endl;

    run_test("Sim mode returns 2 screens", U + " --sim screens",
        [](const std::string& o) { return json_get_int(o, "total_screens") == 2; });

    run_test("Screens have primary flag", U + " --sim screens",
        [](const std::string& o) { return json_contains(o, "\"is_primary\":true"); });

    run_test("Primary screen has 1920x1080", U + " --sim primary-screen",
        [](const std::string& o) {
            return json_contains(o, "\"width\":1920") && json_contains(o, "\"height\":1080");
        });

    run_test("Screen-at returns correct screen", U + " --sim screen-at 100 100",
        [](const std::string& o) { return json_contains(o, "\"id\":0"); });

    run_test("Screen-at on secondary monitor", U + " --sim screen-at 2000 500",
        [](const std::string& o) { return json_contains(o, "\"id\":1"); });

    run_test("Screens have work_area field", U + " --sim screens",
        [](const std::string& o) { return json_contains(o, "\"work_area\":"); });

    run_test("Screens have dpi_scale field", U + " --sim screens",
        [](const std::string& o) { return json_contains(o, "\"dpi_scale\":"); });

    run_test("Screens have color_depth field", U + " --sim screens",
        [](const std::string& o) { return json_contains(o, "\"color_depth\":"); });

    run_test("Screens have name field", U + " --sim screens",
        [](const std::string& o) { return json_contains(o, "\"name\":"); });

    run_test("Secondary screen at x=1920", U + " --sim screens",
        [](const std::string& o) { return json_contains(o, "\"x\":1920"); });

    // ========== CATEGORY 2: Element State Queries (11-20) ==========
    std::cout << std::endl << "--- Category 2: Element State Queries ---" << std::endl;

    run_test("Element-state returns enabled=true for Save", U + " --sim element-state elem_tb_2",
        [](const std::string& o) { return json_contains(o, "\"enabled\":true"); });

    run_test("Element-state returns enabled=false for Save As", U + " --sim element-state elem_tb_3",
        [](const std::string& o) { return json_contains(o, "\"enabled\":false"); });

    run_test("Element-state returns clickable=true for button", U + " --sim element-state elem_tb_2",
        [](const std::string& o) { return json_contains(o, "\"clickable\":true"); });

    run_test("Element-state returns is_container for menubar", U + " --sim element-state elem_menubar",
        [](const std::string& o) { return json_contains(o, "\"is_container\":true"); });

    run_test("Element-state returns is_text_input for textarea", U + " --sim element-state elem_textarea",
        [](const std::string& o) { return json_contains(o, "\"is_text_input\":true"); });

    run_test("Is-enabled returns true for enabled element", U + " --sim is-enabled elem_tb_0",
        [](const std::string& o) { return json_contains(o, "\"enabled\":true"); });

    run_test("Is-enabled returns false for disabled element", U + " --sim is-enabled elem_tb_3",
        [](const std::string& o) { return json_contains(o, "\"enabled\":false"); });

    run_test("Is-checked returns true for Auto-update", U + " --sim is-checked elem_checkbox_1",
        [](const std::string& o) { return json_contains(o, "\"checked\":true"); });

    run_test("Is-checked returns false for notifications", U + " --sim is-checked elem_checkbox_0",
        [](const std::string& o) { return json_contains(o, "\"checked\":false"); });

    run_test("Element-value returns text content", U + " --sim element-value elem_textarea",
        [](const std::string& o) { return json_contains(o, "Hello World"); });

    // ========== CATEGORY 3: Advanced Actions (21-30) ==========
    std::cout << std::endl << "--- Category 3: Advanced Actions ---" << std::endl;

    run_test("Scroll returns scrolled=true in sim", U + " --sim scroll 500 300 0 -3",
        [](const std::string& o) { return json_contains(o, "\"scrolled\":true"); });

    run_test("Hover returns hovered=true in sim", U + " --sim hover 500 300",
        [](const std::string& o) { return json_contains(o, "\"hovered\":true"); });

    run_test("Hover-element returns hovered=true", U + " --sim hover-element elem_tb_2",
        [](const std::string& o) { return json_contains(o, "\"hovered\":true"); });

    run_test("Drag returns dragged=true in sim", U + " --sim drag 100 100 200 200",
        [](const std::string& o) { return json_contains(o, "\"dragged\":true"); });

    run_test("Send-shortcut copy returns sent=true", U + " --sim send-shortcut copy",
        [](const std::string& o) { return json_contains(o, "\"sent\":true"); });

    run_test("Send-shortcut paste returns sent=true", U + " --sim send-shortcut paste",
        [](const std::string& o) { return json_contains(o, "\"sent\":true"); });

    run_test("Send-shortcut save returns sent=true", U + " --sim send-shortcut save",
        [](const std::string& o) { return json_contains(o, "\"sent\":true"); });

    run_test("Send-shortcut undo returns sent=true", U + " --sim send-shortcut undo",
        [](const std::string& o) { return json_contains(o, "\"sent\":true"); });

    run_test("Send-shortcut find returns sent=true", U + " --sim send-shortcut find",
        [](const std::string& o) { return json_contains(o, "\"sent\":true"); });

    run_test("Send-shortcut nonexistent returns sent=false", U + " --sim send-shortcut zzzNonExistent",
        [](const std::string& o) { return json_contains(o, "\"sent\":false"); });

    // ========== CATEGORY 4: Wait/Poll API (31-38) ==========
    std::cout << std::endl << "--- Category 4: Wait/Poll API ---" << std::endl;

    run_test("Wait-for-element finds Save button", U + " --sim wait-for-element Save 1000",
        [](const std::string& o) { return json_contains(o, "\"id\":\"elem_tb_2\""); });

    run_test("Wait-for-element finds OK button", U + " --sim wait-for-element OK 1000",
        [](const std::string& o) { return json_contains(o, "\"text\":\"OK\""); });

    run_test("Wait-for-element with type filter", U + " --sim wait-for-element File 1000 --type menu_item",
        [](const std::string& o) { return json_contains(o, "\"type\":\"menu_item\""); });

    run_test("Wait-for-element nonexistent returns empty", U + " --sim wait-for-element zzzNonExistent 100",
        [](const std::string& o) { return json_contains(o, "\"id\":\"\""); });

    run_test("Wait-for-window finds TextEditor", U + " --sim wait-for-window TextEditor 1000",
        [](const std::string& o) { return json_contains(o, "TextEditor"); });

    run_test("Wait-for-window finds Settings", U + " --sim wait-for-window Settings 1000",
        [](const std::string& o) { return json_contains_ci(o, "Settings"); });

    run_test("Wait-for-window nonexistent returns empty", U + " --sim wait-for-window zzzNonExistent 100",
        [](const std::string& o) { return json_contains(o, "\"id\":\"\""); });

    run_test("Wait-for-element finds checkbox by text", U + " --sim wait-for-element \"Dark mode\" 1000",
        [](const std::string& o) { return json_contains(o, "\"type\":\"checkbox\""); });

    // ========== CATEGORY 5: Element Path / Selector (39-48) ==========
    std::cout << std::endl << "--- Category 5: Element Path / Selector ---" << std::endl;

    run_test("Find-by-path locates Save via toolbar", U + " --sim find-by-path \"sim_win_editor/elem_toolbar/Save\"",
        [](const std::string& o) {
            return json_get_int(o, "total_elements") > 0 &&
                   json_contains(o, "\"text\":\"Save\"");
        });

    run_test("Find-by-path locates File menu", U + " --sim find-by-path \"sim_win_editor/elem_menubar/File\"",
        [](const std::string& o) {
            return json_get_int(o, "total_elements") > 0 &&
                   json_contains(o, "\"text\":\"File\"");
        });

    run_test("Find-by-path locates OK in dialog", U + " --sim find-by-path \"sim_win_dialog/OK\"",
        [](const std::string& o) {
            return json_get_int(o, "total_elements") > 0 &&
                   json_contains(o, "\"text\":\"OK\"");
        });

    run_test("Find-by-path locates FAB in mobile", U + " --sim find-by-path \"sim_win_mobile/New Chat\"",
        [](const std::string& o) {
            return json_get_int(o, "total_elements") > 0 &&
                   json_contains(o, "\"type\":\"fab\"");
        });

    run_test("Find-by-path with invalid path returns 0", U + " --sim find-by-path \"zzz/yyy/xxx\"",
        [](const std::string& o) { return json_get_int(o, "total_elements") == 0; });

    run_test("Element-path returns path for Save button", U + " --sim element-path elem_tb_2",
        [](const std::string& o) { return json_contains(o, "\"path\":\""); });

    run_test("Element-path includes Save in path", U + " --sim element-path elem_tb_2",
        [](const std::string& o) { return json_contains_ci(o, "Save"); });

    run_test("Element-path for menu item includes File", U + " --sim element-path elem_menu_0",
        [](const std::string& o) { return json_contains_ci(o, "File"); });

    run_test("Element-path for checkbox includes Dark mode", U + " --sim element-path elem_checkbox_3",
        [](const std::string& o) { return json_contains_ci(o, "Dark mode"); });

    run_test("Find-by-path locates Cancel in dialog", U + " --sim find-by-path \"sim_win_dialog/Cancel\"",
        [](const std::string& o) {
            return json_get_int(o, "total_elements") > 0 &&
                   json_contains(o, "\"text\":\"Cancel\"");
        });

    // ========== CATEGORY 6: Window Management (49-58) ==========
    std::cout << std::endl << "--- Category 6: Window Management ---" << std::endl;

    run_test("Focus-window returns focused=true in sim", U + " --sim focus-window sim_win_browser",
        [](const std::string& o) { return json_contains(o, "\"focused\":true"); });

    run_test("Minimize-window returns minimized=true", U + " --sim minimize-window sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"minimized\":true"); });

    run_test("Maximize-window returns maximized=true", U + " --sim maximize-window sim_win_browser",
        [](const std::string& o) { return json_contains(o, "\"maximized\":true"); });

    run_test("Restore-window returns restored=true", U + " --sim restore-window sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"restored\":true"); });

    run_test("Close-window returns closed=true", U + " --sim close-window sim_win_dialog",
        [](const std::string& o) { return json_contains(o, "\"closed\":true"); });

    run_test("Move-window returns moved=true", U + " --sim move-window sim_win_editor 200 200",
        [](const std::string& o) { return json_contains(o, "\"moved\":true"); });

    run_test("Resize-window returns resized=true", U + " --sim resize-window sim_win_editor 1024 768",
        [](const std::string& o) { return json_contains(o, "\"resized\":true"); });

    run_test("Focus-window on mobile app", U + " --sim focus-window sim_win_mobile",
        [](const std::string& o) { return json_contains(o, "\"focused\":true"); });

    run_test("Minimize settings dialog", U + " --sim minimize-window sim_win_dialog",
        [](const std::string& o) { return json_contains(o, "\"minimized\":true"); });

    run_test("Close browser window", U + " --sim close-window sim_win_browser",
        [](const std::string& o) { return json_contains(o, "\"closed\":true"); });

    // ========== CATEGORY 7: Nearest Element Search (59-68) ==========
    std::cout << std::endl << "--- Category 7: Nearest Element Search ---" << std::endl;

    run_test("Nearest-clickable finds element near point", U + " --sim nearest-clickable 500 300 500",
        [](const std::string& o) { return json_contains(o, "\"id\":\""); });

    run_test("Nearest-clickable finds button near toolbar", U + " --sim nearest-clickable 300 93 100",
        [](const std::string& o) {
            return json_contains(o, "\"type\":\"toolbar_button\"") ||
                   json_contains(o, "\"type\":\"menu_item\"") ||
                   json_contains(o, "\"type\":\"button\"");
        });

    run_test("Nearest-clickable with small radius may be empty", U + " --sim nearest-clickable 5000 5000 10",
        [](const std::string& o) { return json_contains(o, "\"element\":"); });

    run_test("Nearest-by-type finds button near point", U + " --sim nearest-by-type 550 575 button 200",
        [](const std::string& o) { return json_contains(o, "\"type\":\"button\""); });

    run_test("Nearest-by-type finds checkbox near dialog", U + " --sim nearest-by-type 400 400 checkbox 300",
        [](const std::string& o) { return json_contains(o, "\"type\":\"checkbox\""); });

    run_test("Nearest-by-type finds link in browser", U + " --sim nearest-by-type 620 200 link 300",
        [](const std::string& o) { return json_contains(o, "\"type\":\"link\""); });

    run_test("Nearest-by-text finds Save near toolbar", U + " --sim nearest-by-text 300 93 Save 200",
        [](const std::string& o) { return json_contains_ci(o, "Save"); });

    run_test("Nearest-by-text finds OK in dialog", U + " --sim nearest-by-text 550 575 OK 200",
        [](const std::string& o) { return json_contains(o, "\"text\":\"OK\""); });

    run_test("Nearest-by-text finds File in menu", U + " --sim nearest-by-text 130 62 File 100",
        [](const std::string& o) { return json_contains(o, "\"text\":\"File\""); });

    run_test("Nearest-clickable finds FAB in mobile area", U + " --sim nearest-clickable 370 630 100",
        [](const std::string& o) {
            return json_contains(o, "\"type\":\"fab\"") ||
                   json_contains(o, "\"type\":\"button\"");
        });

    // ========== CATEGORY 8: Export/Import (69-76) ==========
    std::cout << std::endl << "--- Category 8: Export/Import ---" << std::endl;

    run_test("Export-map returns valid JSON with version", U + " --sim export-map",
        [](const std::string& o) {
            return json_contains(o, "\"version\":\"1.0\"") &&
                   json_contains(o, "\"platform\":");
        });

    run_test("Export-map includes screens data", U + " --sim export-map",
        [](const std::string& o) { return json_contains(o, "\"screens\":"); });

    run_test("Export-map includes windows data", U + " --sim export-map",
        [](const std::string& o) { return json_contains(o, "\"windows\":"); });

    run_test("Export-map includes elements data", U + " --sim export-map",
        [](const std::string& o) { return json_contains(o, "\"elements\":"); });

    run_test("Export-map has 206+ elements", U + " --sim export-map",
        [](const std::string& o) { return json_get_int(o, "total_elements") >= 200; });

    run_test("Save-map writes file successfully", U + " --sim save-map test_map_export.json",
        [](const std::string& o) { return json_contains(o, "\"saved\":true"); });

    run_test("Load-map reads file successfully", U + " --sim load-map test_map_export.json",
        [](const std::string& o) { return json_contains(o, "\"loaded\":true"); });

    run_test("Export-map contains all 10 windows", U + " --sim export-map",
        [](const std::string& o) { return json_contains(o, "\"total_windows\":10"); });

    // ========== CATEGORY 9: Keyboard Shortcuts (77-84) ==========
    std::cout << std::endl << "--- Category 9: Keyboard Shortcuts ---" << std::endl;

    run_test("Shortcuts returns list with 30+ shortcuts", U + " --sim shortcuts",
        [](const std::string& o) { return json_get_int(o, "total_shortcuts") >= 30; });

    run_test("Shortcuts includes copy", U + " --sim shortcuts",
        [](const std::string& o) { return json_contains(o, "\"name\":\"copy\""); });

    run_test("Shortcuts includes paste", U + " --sim shortcuts",
        [](const std::string& o) { return json_contains(o, "\"name\":\"paste\""); });

    run_test("Shortcuts includes save", U + " --sim shortcuts",
        [](const std::string& o) { return json_contains(o, "\"name\":\"save\""); });

    run_test("Get-shortcut copy returns valid shortcut", U + " --sim get-shortcut copy",
        [](const std::string& o) {
            return json_contains(o, "\"name\":\"copy\"") &&
                   json_contains(o, "\"key_name\":\"C\"");
        });

    run_test("Get-shortcut save has key S", U + " --sim get-shortcut save",
        [](const std::string& o) { return json_contains(o, "\"key_name\":\"S\""); });

    run_test("Shortcuts include fullscreen F11", U + " --sim shortcuts",
        [](const std::string& o) { return json_contains(o, "\"name\":\"fullscreen\""); });

    run_test("Shortcuts include select_all", U + " --sim shortcuts",
        [](const std::string& o) { return json_contains(o, "\"name\":\"select_all\""); });

    // ========== CATEGORY 10: Element Regions (85-90) ==========
    std::cout << std::endl << "--- Category 10: Element Regions ---" << std::endl;

    run_test("Detect-regions returns 4 regions for editor", U + " --sim detect-regions sim_win_editor",
        [](const std::string& o) { return json_get_int(o, "total_regions") >= 4; });

    run_test("Detect-regions includes header", U + " --sim detect-regions sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"region_type\":\"header\""); });

    run_test("Detect-regions includes footer", U + " --sim detect-regions sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"region_type\":\"footer\""); });

    run_test("Detect-regions includes content", U + " --sim detect-regions sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"region_type\":\"content\""); });

    run_test("Header region contains menubar elements", U + " --sim detect-regions sim_win_editor",
        [](const std::string& o) { return json_contains(o, "elem_menubar"); });

    run_test("Elements-in-region header returns elements", U + " --sim elements-in-region sim_win_editor header",
        [](const std::string& o) { return json_get_int(o, "total_elements") > 0; });

    // ========== CATEGORY 11: Change Detection (91-94) ==========
    std::cout << std::endl << "--- Category 11: Change Detection ---" << std::endl;

    run_test("Snapshot returns element_count=206+", U + " --sim snapshot",
        [](const std::string& o) { return json_get_int(o, "element_count") >= 200; });

    run_test("Snapshot includes element IDs", U + " --sim snapshot",
        [](const std::string& o) { return json_contains(o, "\"id\":\"elem_tb_2\""); });

    run_test("Snapshot includes enabled state", U + " --sim snapshot",
        [](const std::string& o) { return json_contains(o, "\"enabled\":"); });

    run_test("Snapshot includes checked state", U + " --sim snapshot",
        [](const std::string& o) { return json_contains(o, "\"checked\":"); });

    // ========== CATEGORY 12: Highlight API (95-97) ==========
    std::cout << std::endl << "--- Category 12: Highlight API ---" << std::endl;

    run_test("Highlight element returns highlighted=true", U + " --sim highlight elem_tb_2",
        [](const std::string& o) { return json_contains(o, "\"highlighted\":true"); });

    run_test("Highlight-region returns highlighted=true", U + " --sim highlight-region 100 100 200 50",
        [](const std::string& o) { return json_contains(o, "\"highlighted\":true"); });

    run_test("Clear-highlights returns cleared=true", U + " --sim clear-highlights",
        [](const std::string& o) { return json_contains(o, "\"cleared\":true"); });

    // ========== CATEGORY 13: Complex AI Agent Scenarios (98-100) ==========
    std::cout << std::endl << "--- Category 13: Complex AI Agent Scenarios ---" << std::endl;

    run_test("AI: Full workflow - find, check state, get coords, click",
        U + " --sim search Save --type toolbar_button --top-k 1",
        [](const std::string& o) {
            // Step 1: Search finds the Save button
            return json_get_int(o, "total_results") > 0 &&
                   json_contains(o, "\"text\":\"Save\"") &&
                   json_contains(o, "\"center_x\":") &&
                   json_contains(o, "\"center_y\":") &&
                   json_contains(o, "\"clickable\":true");
        });

    run_test("AI: Multi-step - detect region, find elements in header",
        U + " --sim elements-in-region sim_win_editor header",
        [](const std::string& o) {
            // Header region should contain menu items and toolbar buttons
            return json_get_int(o, "total_elements") > 5 &&
                   json_contains(o, "elem_menubar") &&
                   json_contains(o, "elem_toolbar");
        });

    run_test("AI: Full workflow - export map, verify screens+windows+elements",
        U + " --sim export-map",
        [](const std::string& o) {
            return json_contains(o, "\"version\":\"1.0\"") &&
                   json_contains(o, "\"total_screens\":2") &&
                   json_contains(o, "\"total_windows\":10") &&
                   json_get_int(o, "total_elements") >= 200 &&
                   json_contains(o, "TextEditor") &&
                   json_contains(o, "WebBrowser") &&
                   json_contains(o, "ChatApp");
        });

    // ========== SUMMARY ==========
    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  UI LOCATOR TEST SUITE 2 - SUMMARY" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  Total:  " << tests_total << std::endl;
    std::cout << "  Passed: " << tests_passed << std::endl;
    std::cout << "  Failed: " << tests_failed << std::endl;
    std::cout << "  Rate:   " << std::fixed << std::setprecision(1)
              << (100.0 * tests_passed / tests_total) << "%" << std::endl;
    std::cout << "========================================" << std::endl;

    return tests_failed > 0 ? 1 : 0;
}
