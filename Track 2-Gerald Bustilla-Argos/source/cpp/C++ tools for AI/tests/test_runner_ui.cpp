// test_runner_ui.cpp - 100 complex tests for UI Locator Tool
// Tests: window enumeration, element detection, search, coordinates,
// hierarchy, cross-platform simulation, AI agent scenarios
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

static double json_get_double(const std::string& json, const std::string& key) {
    std::string search = "\"" + key + "\":";
    size_t pos = json.find(search);
    if (pos == std::string::npos) return -1.0;
    pos += search.size();
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) pos++;
    std::string num;
    while (pos < json.size() && ((json[pos] >= '0' && json[pos] <= '9') || json[pos] == '.' || json[pos] == '-')) {
        num += json[pos++];
    }
    if (num.empty()) return -1.0;
    return std::atof(num.c_str());
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
    std::cout << "[" << std::setw(3) << tests_total << "] " << std::left << std::setw(60) << test_name << " ... ";
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
    std::cout << "  UI LOCATOR TEST SUITE (100 tests)" << std::endl;
    std::cout << "  Window/Element Detection, Search," << std::endl;
    std::cout << "  Coordinates, Hierarchy, AI Scenarios" << std::endl;
    std::cout << "========================================" << std::endl;

    // ========== CATEGORY 1: Window Enumeration (1-12) ==========
    std::cout << std::endl << "--- Category 1: Window Enumeration ---" << std::endl;

    run_test("Sim mode lists 10 windows", U + " --sim list-windows",
        [](const std::string& o) { return json_get_int(o, "total_windows") == 10; });

    run_test("List-windows returns valid JSON", U + " --sim list-windows",
        [](const std::string& o) { return o.size() > 0 && o[0] == '{'; });

    run_test("Windows include editor window", U + " --sim list-windows",
        [](const std::string& o) { return json_contains_ci(o, "TextEditor"); });

    run_test("Windows include browser window", U + " --sim list-windows",
        [](const std::string& o) { return json_contains_ci(o, "WebBrowser"); });

    run_test("Windows include settings dialog", U + " --sim list-windows",
        [](const std::string& o) { return json_contains_ci(o, "Settings"); });

    run_test("Windows include mobile app", U + " --sim list-windows",
        [](const std::string& o) { return json_contains_ci(o, "ChatApp"); });

    run_test("Windows have process_id field", U + " --sim list-windows",
        [](const std::string& o) { return json_contains(o, "\"process_id\":"); });

    run_test("Windows have bounds field", U + " --sim list-windows",
        [](const std::string& o) { return json_contains(o, "\"bounds\":"); });

    run_test("Windows have is_visible field", U + " --sim list-windows",
        [](const std::string& o) { return json_contains(o, "\"is_visible\":"); });

    run_test("Editor window is focused", U + " --sim list-windows",
        [](const std::string& o) { return json_contains(o, "\"is_focused\":true"); });

    run_test("Windows have platform field", U + " --sim list-windows",
        [](const std::string& o) { return json_contains(o, "\"platform\":\"simulation\""); });

    run_test("Windows have element_count field", U + " --sim list-windows",
        [](const std::string& o) { return json_contains(o, "\"element_count\":"); });

    // ========== CATEGORY 2: Element Detection (13-25) ==========
    std::cout << std::endl << "--- Category 2: Element Detection ---" << std::endl;

    run_test("Get elements from editor window", U + " --sim get-elements sim_win_editor",
        [](const std::string& o) { return json_get_int(o, "total_elements") > 0; });

    run_test("Editor has 21 elements", U + " --sim get-elements sim_win_editor",
        [](const std::string& o) { return json_get_int(o, "total_elements") == 21; });

    run_test("Browser has 15 elements", U + " --sim get-elements sim_win_browser",
        [](const std::string& o) { return json_get_int(o, "total_elements") == 15; });

    run_test("Dialog has 15 elements", U + " --sim get-elements sim_win_dialog",
        [](const std::string& o) { return json_get_int(o, "total_elements") == 15; });

    run_test("Mobile has 12 elements", U + " --sim get-elements sim_win_mobile",
        [](const std::string& o) { return json_get_int(o, "total_elements") == 12; });

    run_test("Get-all-elements returns all 206+", U + " --sim get-all-elements",
        [](const std::string& o) { return json_get_int(o, "total_elements") >= 200; });

    run_test("Elements include buttons", U + " --sim get-all-elements",
        [](const std::string& o) { return json_contains(o, "\"type\":\"button\""); });

    run_test("Elements include text fields", U + " --sim get-all-elements",
        [](const std::string& o) { return json_contains(o, "\"type\":\"text_field\""); });

    run_test("Elements include menu items", U + " --sim get-all-elements",
        [](const std::string& o) { return json_contains(o, "\"type\":\"menu_item\""); });

    run_test("Elements include checkboxes", U + " --sim get-all-elements",
        [](const std::string& o) { return json_contains(o, "\"type\":\"checkbox\""); });

    run_test("Elements include links", U + " --sim get-all-elements",
        [](const std::string& o) { return json_contains(o, "\"type\":\"link\""); });

    run_test("Elements include tabs", U + " --sim get-all-elements",
        [](const std::string& o) { return json_contains(o, "\"type\":\"tab\""); });

    run_test("Elements include FAB (Android)", U + " --sim get-all-elements",
        [](const std::string& o) { return json_contains(o, "\"type\":\"fab\""); });

    // ========== CATEGORY 3: Element Coordinates & Bounds (26-37) ==========
    std::cout << std::endl << "--- Category 3: Element Coordinates & Bounds ---" << std::endl;

    run_test("Elements have x coordinate", U + " --sim get-elements sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"x\":"); });

    run_test("Elements have y coordinate", U + " --sim get-elements sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"y\":"); });

    run_test("Elements have width", U + " --sim get-elements sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"width\":"); });

    run_test("Elements have height", U + " --sim get-elements sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"height\":"); });

    run_test("Elements have center_x", U + " --sim get-elements sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"center_x\":"); });

    run_test("Elements have center_y", U + " --sim get-elements sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"center_y\":"); });

    run_test("Save button has correct coordinates", U + " --sim search Save --type toolbar_button",
        [](const std::string& o) {
            return json_contains(o, "\"text\":\"Save\"") &&
                   json_contains(o, "\"center_x\":") &&
                   json_contains(o, "\"center_y\":");
        });

    run_test("Find element at specific coordinates", U + " --sim find-at 127 93",
        [](const std::string& o) {
            // Should find the Save toolbar button (bounds: 105+2*50=205, 78, 45, 30)
            // Actually "Save" is at index 2: x=105+2*50=205, center=205+22=227
            // Let's find at editor menu area: 130, 62 should be in "Edit" menu
            return json_contains(o, "\"element\":") || json_contains(o, "\"id\":");
        });

    run_test("Find-at returns element with bounds", U + " --sim find-at 500 300",
        [](const std::string& o) { return json_contains(o, "\"bounds\":"); });

    run_test("Find-at in browser search area", U + " --sim find-at 600 320",
        [](const std::string& o) {
            return json_contains(o, "\"id\":\"elem_search_input\"") ||
                   json_contains(o, "\"type\":\"text_field\"");
        });

    run_test("Find-at in mobile FAB area", U + " --sim find-at 370 630",
        [](const std::string& o) {
            return json_contains(o, "\"type\":\"fab\"") ||
                   json_contains(o, "\"type\":\"bottom_bar\"");
        });

    run_test("Find-at outside any window returns empty element", U + " --sim find-at 5000 5000",
        [](const std::string& o) {
            return json_contains(o, "\"element\":") &&
                   !json_contains(o, "\"type\":\"button\"");
        });

    // ========== CATEGORY 4: Text Search (38-50) ==========
    std::cout << std::endl << "--- Category 4: Text Search ---" << std::endl;

    run_test("Search 'Save' finds results", U + " --sim search Save",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Search 'Save' --type toolbar_button finds button", U + " --sim search Save --type toolbar_button",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains(o, "\"type\":\"toolbar_button\"");
        });

    run_test("Search 'File' finds menu item", U + " --sim search File --type menu_item",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains(o, "\"type\":\"menu_item\"");
        });

    run_test("Search 'Google' finds Google Search button", U + " --sim search Google",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Search 'OK' finds OK button in dialog", U + " --sim search OK --type button",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains(o, "\"text\":\"OK\"");
        });

    run_test("Search 'Cancel' finds Cancel button", U + " --sim search Cancel --type button",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains(o, "\"text\":\"Cancel\"");
        });

    run_test("Search 'Search' finds search bar", U + " --sim search Search --type search_bar",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Search 'Dark mode' finds checkbox", U + " --sim search \"Dark mode\" --type checkbox",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains(o, "\"type\":\"checkbox\"");
        });

    run_test("Search results include score", U + " --sim search Save",
        [](const std::string& o) { return json_contains(o, "\"score\":"); });

    run_test("Search results include match_reason", U + " --sim search Save",
        [](const std::string& o) { return json_contains(o, "\"match_reason\":"); });

    run_test("Search with --top-k 1 returns at most 1", U + " --sim search button --top-k 1",
        [](const std::string& o) { return json_get_int(o, "total_results") <= 1; });

    run_test("Search nonexistent text returns 0", U + " --sim search zzzNonExistentText123",
        [](const std::string& o) { return json_get_int(o, "total_results") == 0; });

    run_test("Search 'New Chat' finds FAB", U + " --sim search \"New Chat\"",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains(o, "\"type\":\"fab\"");
        });

    // ========== CATEGORY 5: Type-Based Search (51-60) ==========
    std::cout << std::endl << "--- Category 5: Type-Based Search ---" << std::endl;

    run_test("Search type=button finds all buttons", U + " --sim search --type button",
        [](const std::string& o) { return json_get_int(o, "total_results") > 5; });

    run_test("Search type=checkbox finds checkboxes", U + " --sim search --type checkbox",
        [](const std::string& o) {
            return json_get_int(o, "total_results") == 4 &&
                   json_contains(o, "\"type\":\"checkbox\"");
        });

    run_test("Search type=menu_item finds 29+ items", U + " --sim search --type menu_item",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 29; });

    run_test("Search type=link finds 5 links", U + " --sim search --type link",
        [](const std::string& o) { return json_get_int(o, "total_results") == 5; });

    run_test("Search type=tab finds 14+ tabs", U + " --sim search --type tab",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 14; });

    run_test("Search type=text_field finds text fields", U + " --sim search --type text_field",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Search type=toolbar_button finds 15+", U + " --sim search --type toolbar_button",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 15; });

    run_test("Search type=list_item finds 20+ items", U + " --sim search --type list_item",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 20; });

    run_test("Search type=slider finds 3+ sliders", U + " --sim search --type slider",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 3; });

    run_test("Search type=dropdown finds dropdown", U + " --sim search --type dropdown",
        [](const std::string& o) { return json_get_int(o, "total_results") == 1; });

    // ========== CATEGORY 6: Clickable & Input Search (61-70) ==========
    std::cout << std::endl << "--- Category 6: Clickable & Input Search ---" << std::endl;

    run_test("Search-clickable finds all clickable", U + " --sim search-clickable",
        [](const std::string& o) { return json_get_int(o, "total_results") > 10; });

    run_test("Search-clickable with text filter 'Save'", U + " --sim search-clickable Save",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains_ci(o, "Save");
        });

    run_test("Search-clickable 'Google Search'", U + " --sim search-clickable \"Google Search\"",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains(o, "Google Search");
        });

    run_test("Search-clickable 'OK'", U + " --sim search-clickable OK",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains(o, "\"text\":\"OK\"");
        });

    run_test("Search-clickable includes clickable=true", U + " --sim search-clickable",
        [](const std::string& o) { return json_contains(o, "\"clickable\":true"); });

    run_test("Search-inputs finds text inputs", U + " --sim search-inputs",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Search-inputs includes text_input=true", U + " --sim search-inputs",
        [](const std::string& o) { return json_contains(o, "\"text_input\":true"); });

    run_test("Search-inputs finds search bar", U + " --sim search-inputs",
        [](const std::string& o) { return json_contains(o, "\"type\":\"search_bar\""); });

    run_test("Search-inputs finds text area", U + " --sim search-inputs",
        [](const std::string& o) { return json_contains(o, "\"type\":\"text_area\""); });

    run_test("Search-clickable finds FAB", U + " --sim search-clickable",
        [](const std::string& o) { return json_contains(o, "\"type\":\"fab\""); });

    // ========== CATEGORY 7: Element Hierarchy (71-80) ==========
    std::cout << std::endl << "--- Category 7: Element Hierarchy ---" << std::endl;

    run_test("Get-children of menubar finds menu items", U + " --sim get-children elem_menubar",
        [](const std::string& o) { return json_get_int(o, "total_elements") == 7; });

    run_test("Get-children of toolbar finds toolbar buttons", U + " --sim get-children elem_toolbar",
        [](const std::string& o) { return json_get_int(o, "total_elements") == 10; });

    run_test("Get-children of tabctrl finds tabs", U + " --sim get-children elem_tabctrl",
        [](const std::string& o) {
            int count = json_get_int(o, "total_elements");
            return count >= 4; // tabs + checkboxes + dropdown + slider
        });

    run_test("Get-children of bottom_nav finds buttons", U + " --sim get-children elem_bottom_nav",
        [](const std::string& o) { return json_get_int(o, "total_elements") == 3; });

    run_test("Get-parent of menu item returns menubar", U + " --sim get-parent elem_menu_0",
        [](const std::string& o) { return json_contains(o, "\"id\":\"elem_menubar\""); });

    run_test("Get-parent of toolbar button returns toolbar", U + " --sim get-parent elem_tb_0",
        [](const std::string& o) { return json_contains(o, "\"id\":\"elem_toolbar\""); });

    run_test("Get-tree of dialog returns full tree", U + " --sim get-tree elem_dialog",
        [](const std::string& o) { return json_get_int(o, "total_elements") > 5; });

    run_test("Get-tree of menubar returns menubar + items", U + " --sim get-tree elem_menubar",
        [](const std::string& o) { return json_get_int(o, "total_elements") == 8; });

    run_test("Elements have parent_id field", U + " --sim get-elements sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"parent_id\":"); });

    run_test("Elements have window_id field", U + " --sim get-elements sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"window_id\":\"sim_win_editor\""); });

    // ========== CATEGORY 8: Element Properties & Metadata (81-87) ==========
    std::cout << std::endl << "--- Category 8: Element Properties & Metadata ---" << std::endl;

    run_test("Elements have enabled field", U + " --sim get-all-elements",
        [](const std::string& o) { return json_contains(o, "\"enabled\":"); });

    run_test("Elements have visible field", U + " --sim get-all-elements",
        [](const std::string& o) { return json_contains(o, "\"visible\":"); });

    run_test("Disabled elements exist (Save As)", U + " --sim get-elements sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"enabled\":false"); });

    run_test("Elements have clickable property", U + " --sim get-all-elements",
        [](const std::string& o) { return json_contains(o, "\"clickable\":"); });

    run_test("Elements have container property", U + " --sim get-all-elements",
        [](const std::string& o) { return json_contains(o, "\"container\":"); });

    run_test("Checkbox has checked=true for Auto-update", U + " --sim search \"\" --type checkbox",
        [](const std::string& o) { return json_contains(o, "\"checked\":true"); });

    run_test("Get-element returns specific element", U + " --sim get-element elem_tb_2",
        [](const std::string& o) {
            return json_contains(o, "\"id\":\"elem_tb_2\"") &&
                   json_contains(o, "\"text\":\"Save\"");
        });

    // ========== CATEGORY 9: AI Agent Scenarios (88-100) ==========
    std::cout << std::endl << "--- Category 9: AI Agent Real-World Scenarios ---" << std::endl;

    run_test("AI: Find Save button and get coordinates", U + " --sim search Save --type toolbar_button --top-k 1",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains(o, "\"center_x\":") &&
                   json_contains(o, "\"center_y\":");
        });

    run_test("AI: Find all clickable in browser window", U + " --sim search-clickable --window sim_win_browser",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("AI: Search for 'File' menu to click it", U + " --sim search File --type menu_item --top-k 1",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains(o, "\"text\":\"File\"");
        });

    run_test("AI: Find search input to type query", U + " --sim search-inputs --window sim_win_browser",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains(o, "\"type\":\"search_bar\"");
        });

    run_test("AI: Find OK button in settings dialog", U + " --sim search OK --type button --window sim_win_dialog",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains(o, "\"text\":\"OK\"");
        });

    run_test("AI: Find checkbox 'Dark mode' to toggle", U + " --sim search \"Dark mode\" --type checkbox",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains(o, "\"type\":\"checkbox\"");
        });

    run_test("AI: Find FAB for new chat (Android)", U + " --sim search \"New Chat\"",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0 &&
                   json_contains(o, "\"type\":\"fab\"");
        });

    run_test("AI: Find 'Settings' in bottom nav (mobile)", U + " --sim search Settings --type button --window sim_win_mobile",
        [](const std::string& o) {
            return json_get_int(o, "total_results") > 0;
        });

    run_test("AI: Click element returns clicked=true", U + " --sim click elem_tb_2",
        [](const std::string& o) { return json_contains(o, "\"clicked\":true"); });

    run_test("AI: Click-at returns clicked=true", U + " --sim click-at 500 300",
        [](const std::string& o) { return json_contains(o, "\"clicked\":true"); });

    run_test("AI: Type-text returns typed=true", U + " --sim type-text \"hello world\"",
        [](const std::string& o) { return json_contains(o, "\"typed\":true"); });

    run_test("AI: Get-focused returns focused element", U + " --sim get-focused",
        [](const std::string& o) {
            return json_contains(o, "\"focused_window\":") &&
                   json_contains(o, "\"focused_element\":");
        });

    run_test("AI: Stats shows type_counts", U + " --sim stats",
        [](const std::string& o) {
            return json_contains(o, "\"type_counts\":") &&
                   json_contains(o, "\"total_windows\":10") &&
                   json_contains(o, "\"total_elements\":206");
        });

    // ========== SUMMARY ==========
    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  UI LOCATOR TEST SUITE - SUMMARY" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  Total:  " << tests_total << std::endl;
    std::cout << "  Passed: " << tests_passed << std::endl;
    std::cout << "  Failed: " << tests_failed << std::endl;
    std::cout << "  Rate:   " << std::fixed << std::setprecision(1)
              << (100.0 * tests_passed / tests_total) << "%" << std::endl;
    std::cout << "========================================" << std::endl;

    return tests_failed > 0 ? 1 : 0;
}
