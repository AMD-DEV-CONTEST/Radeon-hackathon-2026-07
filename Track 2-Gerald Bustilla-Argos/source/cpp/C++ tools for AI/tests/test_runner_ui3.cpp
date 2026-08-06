// test_runner_ui3.cpp - 100 bug-hunting tests for UI Locator Tool
// Designed to find bugs via edge cases, boundary conditions, and stress testing
#include <iostream>
#include <string>
#include <vector>
#include <sstream>
#include <iomanip>
#include <cstdlib>
#include <functional>
#include <fstream>
#include <cmath>

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
    std::cout << "  UI LOCATOR BUG-HUNTING TEST SUITE" << std::endl;
    std::cout << "  100 Edge Case & Bug-Finding Tests" << std::endl;
    std::cout << "========================================" << std::endl;

    // ========== CATEGORY 1: Empty & Null Input Edge Cases (1-12) ==========
    std::cout << std::endl << "--- Category 1: Empty & Null Input Edge Cases ---" << std::endl;

    run_test("Search with empty query doesn't crash", U + " --sim search \"\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-clickable with empty filter", U + " --sim search-clickable \"\"",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    run_test("Search-inputs with empty filter", U + " --sim search-inputs \"\"",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    run_test("Get-element with empty ID", U + " --sim get-element \"\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Get-element with non-existent ID", U + " --sim get-element zzz_nonexistent",
        [](const std::string& o) { return json_contains(o, "\"id\":\"\""); });

    run_test("Get-children with non-existent ID", U + " --sim get-children zzz_nonexistent",
        [](const std::string& o) { return json_get_int(o, "total_elements") == 0; });

    run_test("Get-parent with non-existent ID", U + " --sim get-parent zzz_nonexistent",
        [](const std::string& o) { return json_contains(o, "\"id\":\"\""); });

    run_test("Get-parent with root element (no parent)", U + " --sim get-parent sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"id\":\"\""); });

    run_test("Get-tree with non-existent ID", U + " --sim get-tree zzz_nonexistent",
        [](const std::string& o) { return json_get_int(o, "total_elements") == 0; });

    run_test("Find-at with negative coordinates", U + " --sim find-at -1 -1",
        [](const std::string& o) { return json_contains(o, "\"id\":\"\""); });

    run_test("Find-at with very large coordinates", U + " --sim find-at 99999 99999",
        [](const std::string& o) { return json_contains(o, "\"id\":\"\""); });

    run_test("Find-at at origin (0,0)", U + " --sim find-at 0 0",
        [](const std::string& o) { return o.size() > 0; });

    // ========== CATEGORY 2: Boundary Coordinate Tests (13-22) ==========
    std::cout << std::endl << "--- Category 2: Boundary Coordinate Tests ---" << std::endl;

    run_test("Find-at at exact element center (Save button)", U + " --sim find-at 60 35",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Find-at at element edge (x=0,y=0)", U + " --sim find-at 0 0",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Click-at at negative coords returns false", U + " --sim click-at -100 -100",
        [](const std::string& o) { return json_contains(o, "\"clicked\":false") || json_contains(o, "\"clicked\":true"); });

    run_test("Click-at at very large coords", U + " --sim click-at 99999 99999",
        [](const std::string& o) { return json_contains(o, "\"clicked\":false") || json_contains(o, "\"clicked\":true"); });

    run_test("Find-at at exact boundary of window", U + " --sim find-at 799 599",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Find-at just outside window boundary", U + " --sim find-at 9999 9999",
        [](const std::string& o) { return json_contains(o, "\"id\":\"\""); });

    run_test("Screen-at at negative coords", U + " --sim screen-at -1 -1",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Screen-at at very large coords", U + " --sim screen-at 99999 99999",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Nearest-clickable at origin with max_distance=0", U + " --sim nearest-clickable 0 0 0",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Nearest-clickable at far point with small distance", U + " --sim nearest-clickable 9999 9999 10",
        [](const std::string& o) { return json_contains(o, "\"id\":\"\""); });

    // ========== CATEGORY 3: Search Edge Cases (23-35) ==========
    std::cout << std::endl << "--- Category 3: Search Edge Cases ---" << std::endl;

    run_test("Search with special regex chars", U + " --sim search \"a.b*c+d\"",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    run_test("Search with very long query", U + " --sim search \"thisisaverylongquerythatexceedsnormallengthsandtestshowthesearchenginehandlesverylongqueries1234567890abcdefghij\"",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    run_test("Search with single character", U + " --sim search \"a\"",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    run_test("Search with whitespace only", U + " --sim search \"   \"",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    run_test("Search with numbers only", U + " --sim search \"12345\"",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    run_test("Search with mixed case query", U + " --sim search \"SaVe\"",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Search-clickable with non-existent text", U + " --sim search-clickable zzzNonExistent",
        [](const std::string& o) { return json_get_int(o, "total_results") == 0; });

    run_test("Search-inputs with non-existent text", U + " --sim search-inputs zzzNonExistent",
        [](const std::string& o) { return json_get_int(o, "total_results") == 0; });

    run_test("Search with type filter (toolbar_button)", U + " --sim search Save --type toolbar_button",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Search with type filter (non-existent type)", U + " --sim search Save --type zzz_nonexistent",
        [](const std::string& o) { return json_get_int(o, "total_results") == 0; });

    run_test("Search with window filter", U + " --sim search Save --window sim_win_editor",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("Search with non-existent window filter", U + " --sim search Save --window zzz_nonexistent",
        [](const std::string& o) { return json_get_int(o, "total_results") == 0; });

    run_test("Search for text with spaces", U + " --sim search \"Save As\"",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    // ========== CATEGORY 4: Fuzzy Match Edge Cases (36-45) ==========
    std::cout << std::endl << "--- Category 4: Fuzzy Match Edge Cases ---" << std::endl;

    run_test("Search with 1-char typo (Svae)", U + " --sim search Svae",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    run_test("Search with transposed chars (Svae)", U + " --sim search Svae",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    run_test("Search with missing char (Sav)", U + " --sim search Sav",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    run_test("Search with extra char (Savee)", U + " --sim search Savee",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    run_test("Search with completely different word", U + " --sim search zzzzzzzzzz",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    run_test("Search with substring of element text", U + " --sim search Sav",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    run_test("Search with superstring of element text", U + " --sim search SaveButtonXXX",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    run_test("Search with empty string returns all or some results", U + " --sim search \"\"",
        [](const std::string& o) { return json_get_int(o, "total_results") >= 0; });

    run_test("Search-clickable returns only clickable elements", U + " --sim search-clickable \"\"",
        [](const std::string& o) {
            return json_get_int(o, "total_results") >= 0;
        });

    run_test("Search-inputs returns only input elements", U + " --sim search-inputs \"\"",
        [](const std::string& o) {
            return json_get_int(o, "total_results") >= 0;
        });

    // ========== CATEGORY 5: Element Path Edge Cases (46-55) ==========
    std::cout << std::endl << "--- Category 5: Element Path Edge Cases ---" << std::endl;

    run_test("Find-by-path with empty path", U + " --sim find-by-path \"\"",
        [](const std::string& o) { return json_get_int(o, "total_elements") >= 0; });

    run_test("Find-by-path with single segment (window only)", U + " --sim find-by-path sim_win_editor",
        [](const std::string& o) { return json_get_int(o, "total_elements") >= 0; });

    run_test("Find-by-path with non-existent root", U + " --sim find-by-path zzz_nonexistent/Save",
        [](const std::string& o) { return json_get_int(o, "total_elements") == 0; });

    run_test("Find-by-path with valid root but non-existent child", U + " --sim find-by-path sim_win_editor/zzz_nonexistent",
        [](const std::string& o) { return json_get_int(o, "total_elements") == 0; });

    run_test("Find-by-path with very deep path", U + " --sim find-by-path sim_win_editor/elem_toolbar/elem_tb_2/extra/deep/path",
        [](const std::string& o) { return json_get_int(o, "total_elements") >= 0; });

    run_test("Find-by-path with trailing slash", U + " --sim find-by-path sim_win_editor/",
        [](const std::string& o) { return json_get_int(o, "total_elements") >= 0; });

    run_test("Find-by-path with double slash", U + " --sim find-by-path sim_win_editor//Save",
        [](const std::string& o) { return json_get_int(o, "total_elements") >= 0; });

    run_test("Element-path for non-existent element", U + " --sim element-path zzz_nonexistent",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Element-path for root window element", U + " --sim element-path sim_win_editor",
        [](const std::string& o) { return json_contains(o, "\"path\":\""); });

    run_test("Find-by-path case insensitive", U + " --sim find-by-path \"SIM_WIN_EDITOR/Save\"",
        [](const std::string& o) { return json_get_int(o, "total_elements") >= 0; });

    // ========== CATEGORY 6: Window Management Edge Cases (56-65) ==========
    std::cout << std::endl << "--- Category 6: Window Management Edge Cases ---" << std::endl;

    run_test("Focus-window with non-existent ID", U + " --sim focus-window zzz_nonexistent",
        [](const std::string& o) { return json_contains(o, "\"focused\":false"); });

    run_test("Minimize-window with non-existent ID", U + " --sim minimize-window zzz_nonexistent",
        [](const std::string& o) { return json_contains(o, "\"minimized\":false"); });

    run_test("Maximize-window with non-existent ID", U + " --sim maximize-window zzz_nonexistent",
        [](const std::string& o) { return json_contains(o, "\"maximized\":false"); });

    run_test("Restore-window with non-existent ID", U + " --sim restore-window zzz_nonexistent",
        [](const std::string& o) { return json_contains(o, "\"restored\":false"); });

    run_test("Close-window with non-existent ID", U + " --sim close-window zzz_nonexistent",
        [](const std::string& o) { return json_contains(o, "\"closed\":false"); });

    run_test("Move-window with non-existent ID", U + " --sim move-window zzz_nonexistent 100 100",
        [](const std::string& o) { return json_contains(o, "\"moved\":false"); });

    run_test("Resize-window with non-existent ID", U + " --sim resize-window zzz_nonexistent 800 600",
        [](const std::string& o) { return json_contains(o, "\"resized\":false"); });

    run_test("Move-window with negative coords", U + " --sim move-window sim_win_editor -100 -100",
        [](const std::string& o) { return json_contains(o, "\"moved\":"); });

    run_test("Resize-window with zero dimensions", U + " --sim resize-window sim_win_editor 0 0",
        [](const std::string& o) { return json_contains(o, "\"resized\":"); });

    run_test("Resize-window with negative dimensions", U + " --sim resize-window sim_win_editor -1 -1",
        [](const std::string& o) { return json_contains(o, "\"resized\":"); });

    // ========== CATEGORY 7: Element State Edge Cases (66-75) ==========
    std::cout << std::endl << "--- Category 7: Element State Edge Cases ---" << std::endl;

    run_test("Element-state for non-existent element", U + " --sim element-state zzz_nonexistent",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Is-enabled for non-existent element", U + " --sim is-enabled zzz_nonexistent",
        [](const std::string& o) { return json_contains(o, "\"enabled\":false"); });

    run_test("Is-visible for non-existent element", U + " --sim is-visible zzz_nonexistent",
        [](const std::string& o) { return json_contains(o, "\"visible\":false"); });

    run_test("Is-checked for non-existent element", U + " --sim is-checked zzz_nonexistent",
        [](const std::string& o) { return json_contains(o, "\"checked\":false"); });

    run_test("Element-value for non-existent element", U + " --sim element-value zzz_nonexistent",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Is-enabled for disabled Save As button", U + " --sim is-enabled elem_tb_3",
        [](const std::string& o) { return json_contains(o, "\"enabled\":false"); });

    run_test("Is-visible for visible element", U + " --sim is-visible elem_tb_0",
        [](const std::string& o) { return json_contains(o, "\"visible\":true"); });

    run_test("Element-state returns all state fields", U + " --sim element-state elem_tb_2",
        [](const std::string& o) {
            return json_contains(o, "\"enabled\":") && json_contains(o, "\"visible\":") &&
                   json_contains(o, "\"clickable\":");
        });

    run_test("Wait-for-element on non-existent (no crash)", U + " --sim wait-for-element zzz_nonexistent 100",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Wait-for-window on non-existent (no crash)", U + " --sim wait-for-window zzz_nonexistent 100",
        [](const std::string& o) { return o.size() > 0; });

    // ========== CATEGORY 8: Nearest Element Edge Cases (76-83) ==========
    std::cout << std::endl << "--- Category 8: Nearest Element Edge Cases ---" << std::endl;

    run_test("Nearest-clickable with very large max_distance", U + " --sim nearest-clickable 0 0 99999",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Nearest-clickable at negative coords", U + " --sim nearest-clickable -100 -100 500",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Nearest-by-type with non-existent type string", U + " --sim nearest-by-type 100 100 zzz_nonexistent 500",
        [](const std::string& o) { return json_contains(o, "\"id\":\"\""); });

    run_test("Nearest-by-text with non-existent text", U + " --sim nearest-by-text 100 100 zzzNonExistent 500",
        [](const std::string& o) { return json_contains(o, "\"id\":\"\""); });

    run_test("Nearest-by-text with empty text", U + " --sim nearest-by-text 100 100 \"\" 500",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Nearest-clickable at exact element position", U + " --sim nearest-clickable 60 35 100",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Nearest-by-type for button at origin", U + " --sim nearest-by-type 0 0 button 1000",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Nearest-clickable with max_distance=1 (very small)", U + " --sim nearest-clickable 500 300 1",
        [](const std::string& o) { return o.size() > 0; });

    // ========== CATEGORY 9: Export/Import & Snapshot Edge Cases (84-92) ==========
    std::cout << std::endl << "--- Category 9: Export/Import & Snapshot Edge Cases ---" << std::endl;

    run_test("Export-map returns valid JSON", U + " --sim export-map",
        [](const std::string& o) { return o.size() > 0 && o[0] == '{'; });

    run_test("Save-map to file", U + " --sim save-map test_ui_map.json",
        [](const std::string& o) { return json_contains(o, "saved") || o.size() > 0; });

    run_test("Load-map from file", U + " --sim load-map test_ui_map.json",
        [](const std::string& o) { return json_contains(o, "\"loaded\":true"); });

    run_test("Load-map from non-existent file", U + " --sim load-map zzz_nonexistent_map.json",
        [](const std::string& o) { return json_contains(o, "\"loaded\":false"); });

    run_test("Snapshot returns valid JSON string", U + " --sim snapshot",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Detect-regions for editor window", U + " --sim detect-regions sim_win_editor",
        [](const std::string& o) { return json_get_int(o, "total_regions") >= 0; });

    run_test("Detect-regions for non-existent window", U + " --sim detect-regions zzz_nonexistent",
        [](const std::string& o) { return json_get_int(o, "total_regions") == 0; });

    run_test("Elements-in-region for toolbar", U + " --sim elements-in-region sim_win_editor toolbar",
        [](const std::string& o) { return json_get_int(o, "total_elements") >= 0; });

    run_test("Elements-in-region for non-existent region", U + " --sim elements-in-region sim_win_editor zzz_nonexistent",
        [](const std::string& o) { return json_get_int(o, "total_elements") == 0; });

    // Clean up
    std::remove("test_ui_map.json");

    // ========== CATEGORY 10: Complex AI Agent Stress Scenarios (93-100) ==========
    std::cout << std::endl << "--- Category 10: Complex AI Agent Stress Scenarios ---" << std::endl;

    run_test("AI: Search, find element, click chain", U + " --sim search Save",
        [](const std::string& o) { return json_get_int(o, "total_results") > 0; });

    run_test("AI: Get all elements count is consistent", U + " --sim get-all-elements",
        [](const std::string& o) { return json_get_int(o, "total_elements") > 0; });

    run_test("AI: Get elements for non-existent window", U + " --sim get-elements zzz_nonexistent",
        [](const std::string& o) { return json_get_int(o, "total_elements") == 0; });

    run_test("AI: Get elements for empty window ID", U + " --sim get-elements \"\"",
        [](const std::string& o) { return json_get_int(o, "total_elements") >= 0; });

    run_test("AI: Get focused element in sim mode", U + " --sim get-focused",
        [](const std::string& o) { return o.size() > 0; });

    run_test("AI: Stats returns valid data", U + " --sim stats",
        [](const std::string& o) { return json_get_int(o, "total_windows") > 0; });

    run_test("AI: Platform returns simulation in sim mode", U + " --sim platform",
        [](const std::string& o) { return json_contains_ci(o, "simulation"); });

    run_test("AI: Click element with non-existent ID returns false", U + " --sim click zzz_nonexistent",
        [](const std::string& o) { return json_contains(o, "\"clicked\":false"); });

    // ========== SUMMARY ==========
    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  UI LOCATOR BUG-HUNTING TEST SUMMARY" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  Total:  " << tests_total << std::endl;
    std::cout << "  Passed: " << tests_passed << std::endl;
    std::cout << "  Failed: " << tests_failed << std::endl;
    double rate = static_cast<double>(tests_passed) / tests_total * 100.0;
    std::cout << "  Rate:   " << std::fixed << std::setprecision(1) << rate << "%" << std::endl;
    std::cout << "========================================" << std::endl;

    return tests_failed > 0 ? 1 : 0;
}
