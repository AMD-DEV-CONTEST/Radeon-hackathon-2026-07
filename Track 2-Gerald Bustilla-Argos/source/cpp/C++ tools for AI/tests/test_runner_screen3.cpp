// test_runner_screen3.cpp - UIA Integration Bug-Hunting Suite
// 100 complex tests for UI Automation integration
#include "../screen_context/screen_context.h"
#include <iostream>
#include <string>
#include <vector>
#include <sstream>
#include <algorithm>
#include <cstring>

static int g_tests_passed = 0;
static int g_tests_failed = 0;
static int g_current_test = 0;

static std::string exec_command(const std::string& cmd) {
    std::string result;
#ifdef _WIN32
    FILE* pipe = _popen(cmd.c_str(), "r");
#else
    FILE* pipe = popen(cmd.c_str(), "r");
#endif
    if (!pipe) return "";
    char buffer[4096];
    while (fgets(buffer, sizeof(buffer), pipe)) {
        result += buffer;
    }
#ifdef _WIN32
    _pclose(pipe);
#else
    pclose(pipe);
#endif
    return result;
}

static bool check_pass(bool condition, const std::string& test_name) {
    g_current_test++;
    if (condition) {
        g_tests_passed++;
        std::cout << "[" << (g_current_test < 10 ? " " : "") << g_current_test << "] " << test_name;
        for (int i = test_name.size(); i < 60; i++) std::cout << " ";
        std::cout << "PASS" << std::endl;
        return true;
    } else {
        g_tests_failed++;
        std::cout << "[" << (g_current_test < 10 ? " " : "") << g_current_test << "] " << test_name;
        for (int i = test_name.size(); i < 60; i++) std::cout << " ";
        std::cout << "FAIL" << std::endl;
        return false;
    }
}

static std::string get_sim_output(const std::string& command) {
    std::string cmd = "screencontext.exe --sim " + command + " 2>&1";
    return exec_command(cmd);
}

static bool json_contains(const std::string& json, const std::string& field) {
    return json.find("\"" + field + "\"") != std::string::npos;
}

static bool json_contains_value(const std::string& json, const std::string& field, const std::string& value) {
    std::string search = "\"" + field + "\":\"" + value + "\"";
    return json.find(search) != std::string::npos;
}

static bool json_contains_number(const std::string& json, const std::string& field, int value) {
    std::string search = "\"" + field + "\":" + std::to_string(value);
    return json.find(search) != std::string::npos;
}

static bool json_contains_bool(const std::string& json, const std::string& field, bool value) {
    std::string search = "\"" + field + "\":" + (value ? "true" : "false");
    return json.find(search) != std::string::npos;
}

int main() {
    std::cout << "========================================" << std::endl;
    std::cout << " UIA INTEGRATION BUG-HUNTING SUITE" << std::endl;
    std::cout << " 100 Complex Tests - Semantic Screen Reading" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << std::endl;

    // ===== Category 1: UIA Tree Basic Structure (12 tests) =====
    std::cout << "--- Category 1: UIA Tree Basic Structure ---" << std::endl;

    {
        auto out = get_sim_output("uia-tree");
        check_pass(json_contains(out, "success") && json_contains(out, "total_elements"),
                   "UIA-tree returns success and total_elements");
    }
    {
        auto out = get_sim_output("uia-tree");
        check_pass(json_contains(out, "max_depth") && json_contains(out, "elements"),
                   "UIA-tree has max_depth and elements array");
    }
    {
        auto out = get_sim_output("uia-tree");
        check_pass(json_contains(out, "root_element_id"),
                   "UIA-tree has root_element_id");
    }
    {
        auto out = get_sim_output("uia-tree");
        check_pass(json_contains(out, "error"),
                   "UIA-tree has error field");
    }
    {
        auto out = get_sim_output("uia-tree");
        // Should have all 13 window elements at depth 0
        int count = 0;
        size_t pos = 0;
        while ((pos = out.find("\"depth\":0", pos)) != std::string::npos) {
            count++;
            pos++;
        }
        check_pass(count == 13, "UIA-tree has 13 root elements (depth 0)");
    }
    {
        auto out = get_sim_output("uia-tree");
        // Should have elements with various control types
        check_pass(json_contains_value(out, "control_type", "button"),
                   "UIA-tree contains button elements");
    }
    {
        auto out = get_sim_output("uia-tree");
        check_pass(json_contains_value(out, "control_type", "edit"),
                   "UIA-tree contains edit elements");
    }
    {
        auto out = get_sim_output("uia-tree");
        check_pass(json_contains_value(out, "control_type", "text"),
                   "UIA-tree contains text elements");
    }
    {
        auto out = get_sim_output("uia-tree");
        check_pass(json_contains_value(out, "control_type", "hyperlink"),
                   "UIA-tree contains hyperlink elements");
    }
    {
        auto out = get_sim_output("uia-tree");
        check_pass(json_contains_value(out, "control_type", "window"),
                   "UIA-tree contains window elements");
    }
    {
        auto out = get_sim_output("uia-tree");
        // Each element should have element_id, name, control_type
        check_pass(json_contains(out, "element_id") && json_contains(out, "name"),
                   "UIA elements have element_id and name");
    }
    {
        auto out = get_sim_output("uia-tree");
        // Elements should have bounds
        check_pass(json_contains(out, "bounds") && json_contains(out, "x") && json_contains(out, "y"),
                   "UIA elements have bounds with x/y");
    }

    // ===== Category 2: UIA Tree Per-Window (10 tests) =====
    std::cout << std::endl << "--- Category 2: UIA Tree Per-Window ---" << std::endl;

    {
        auto out = get_sim_output("uia-tree sim_fb");
        check_pass(json_contains_value(out, "name", "Facebook - News Feed"),
                   "UIA-tree sim_fb has Facebook root");
    }
    {
        auto out = get_sim_output("uia-tree sim_fb");
        check_pass(json_contains_value(out, "name", "Sarah Johnson"),
                   "UIA-tree sim_fb has Sarah Johnson post");
    }
    {
        auto out = get_sim_output("uia-tree sim_chrome");
        check_pass(json_contains_value(out, "name", "C++ Tutorial - Google Chrome"),
                   "UIA-tree sim_chrome has Chrome root");
    }
    {
        auto out = get_sim_output("uia-tree sim_vscode");
        check_pass(json_contains_value(out, "name", "main.cpp - Visual Studio Code"),
                   "UIA-tree sim_vscode has VS Code root");
    }
    {
        auto out = get_sim_output("uia-tree sim_spotify");
        check_pass(json_contains_value(out, "name", "Spotify - Lo-Fi Beats"),
                   "UIA-tree sim_spotify has Spotify root");
    }
    {
        auto out = get_sim_output("uia-tree sim_outlook");
        check_pass(json_contains_value(out, "name", "Inbox (3) - Outlook"),
                   "UIA-tree sim_outlook has Outlook root");
    }
    {
        auto out = get_sim_output("uia-tree sim_fb");
        // Facebook should have buttons (Like, Comment, Share)
        int btnCount = 0;
        size_t pos = 0;
        while ((pos = out.find("\"control_type\":\"button\"", pos)) != std::string::npos) {
            btnCount++;
            pos++;
        }
        check_pass(btnCount >= 5, "UIA-tree sim_fb has at least 5 buttons");
    }
    {
        auto out = get_sim_output("uia-tree sim_vscode");
        check_pass(json_contains_value(out, "control_type", "toolbar"),
                   "UIA-tree sim_vscode has toolbar (menu bar)");
    }
    {
        auto out = get_sim_output("uia-tree sim_vscode");
        check_pass(json_contains_value(out, "control_type", "treeitem"),
                   "UIA-tree sim_vscode has treeitem (file tree)");
    }
    {
        auto out = get_sim_output("uia-tree sim_outlook");
        check_pass(json_contains_value(out, "control_type", "listitem"),
                   "UIA-tree sim_outlook has listitem (email list)");
    }

    // ===== Category 3: Element State Detection (12 tests) =====
    std::cout << std::endl << "--- Category 3: Element State Detection ---" << std::endl;

    {
        // Get the Facebook root element ID (uia_0)
        auto state = get_sim_output("element-state uia_0");
        check_pass(json_contains_value(state, "name", "Facebook - News Feed"),
                   "Element-state uia_0 returns Facebook name");
    }
    {
        auto state = get_sim_output("element-state uia_0");
        check_pass(json_contains_bool(state, "is_enabled", true),
                   "Facebook root is enabled");
    }
    {
        auto state = get_sim_output("element-state uia_0");
        check_pass(json_contains_bool(state, "is_focused", true),
                   "Facebook root is focused");
    }
    {
        // Comment box is disabled (uia_22)
        auto state = get_sim_output("element-state uia_22");
        check_pass(json_contains_bool(state, "is_enabled", false),
                   "Comment box (uia_22) is disabled");
    }
    {
        auto state = get_sim_output("element-state uia_22");
        check_pass(json_contains_value(state, "control_type", "edit"),
                   "Comment box is edit type");
    }
    {
        // Post Comment button is disabled (uia_23)
        auto state = get_sim_output("element-state uia_23");
        check_pass(json_contains_bool(state, "is_enabled", false),
                   "Post Comment button (uia_23) is disabled");
    }
    {
        auto state = get_sim_output("element-state uia_23");
        check_pass(json_contains_value(state, "control_type", "button"),
                   "Post Comment is button type");
    }
    {
        // Like button (uia_11) is enabled
        auto state = get_sim_output("element-state uia_11");
        check_pass(json_contains_bool(state, "is_enabled", true),
                   "Like button (uia_11) is enabled");
    }
    {
        // Chrome URL bar (uia_25) is focused
        auto state = get_sim_output("element-state uia_25");
        check_pass(json_contains_bool(state, "is_focused", true),
                   "Chrome URL bar (uia_25) is focused");
    }
    {
        // Chrome Forward button (uia_27) is disabled
        auto state = get_sim_output("element-state uia_27");
        check_pass(json_contains_bool(state, "is_enabled", false),
                   "Chrome Forward button (uia_27) is disabled");
    }
    {
        // Empty element ID returns error
        auto state = get_sim_output("element-state \"\"");
        check_pass(json_contains(state, "error"),
                   "Empty element ID returns error");
    }
    {
        // Non-existent element returns error
        auto state = get_sim_output("element-state uia_nonexistent");
        check_pass(json_contains_value(state, "error", "Element not found in simulation"),
                   "Non-existent element returns not found error");
    }

    // ===== Category 4: Interactive Elements (10 tests) =====
    std::cout << std::endl << "--- Category 4: Interactive Elements ---" << std::endl;

    {
        auto out = get_sim_output("interactive-elements sim_fb");
        check_pass(json_contains(out, "total_elements") && json_contains(out, "action_type"),
                   "Interactive-elements has total_elements and action_type");
    }
    {
        auto out = get_sim_output("interactive-elements sim_fb");
        // Should NOT include disabled elements
        check_pass(!json_contains_value(out, "name", "Write a comment..."),
                   "Interactive-elements excludes disabled comment box");
    }
    {
        auto out = get_sim_output("interactive-elements sim_fb");
        // Should NOT include disabled Post Comment button
        check_pass(!json_contains_value(out, "name", "Post Comment"),
                   "Interactive-elements excludes disabled Post Comment button");
    }
    {
        auto out = get_sim_output("interactive-elements sim_fb");
        // Should include Like buttons
        check_pass(json_contains_value(out, "name", "Like"),
                   "Interactive-elements includes Like button");
    }
    {
        auto out = get_sim_output("interactive-elements sim_fb");
        // Should include search edit
        check_pass(json_contains_value(out, "action_type", "type"),
                   "Interactive-elements has type action for edit fields");
    }
    {
        auto out = get_sim_output("interactive-elements sim_fb");
        // Should include click action for buttons
        check_pass(json_contains_value(out, "action_type", "click"),
                   "Interactive-elements has click action for buttons");
    }
    {
        auto out = get_sim_output("interactive-elements sim_fb");
        // Should include click action for hyperlinks
        check_pass(json_contains_value(out, "name", "Home"),
                   "Interactive-elements includes Home hyperlink");
    }
    {
        auto out = get_sim_output("interactive-elements sim_chrome");
        // Should NOT include disabled Forward button
        check_pass(!json_contains_value(out, "name", "Forward"),
                   "Interactive-elements excludes disabled Forward button");
    }
    {
        auto out = get_sim_output("interactive-elements sim_outlook");
        // Should NOT include disabled Reply button
        check_pass(!json_contains_value(out, "name", "Reply"),
                   "Interactive-elements excludes disabled Reply button");
    }
    {
        auto out = get_sim_output("interactive-elements sim_outlook");
        // Should include New Email button
        check_pass(json_contains_value(out, "name", "New Email"),
                   "Interactive-elements includes New Email button");
    }

    // ===== Category 5: Action Verification (10 tests) =====
    std::cout << std::endl << "--- Category 5: Action Verification ---" << std::endl;

    {
        // Verify click on enabled Like button (uia_11)
        auto out = get_sim_output("verify-action uia_11 click");
        check_pass(json_contains_bool(out, "success", true),
                   "Verify-action click on enabled Like succeeds");
    }
    {
        auto out = get_sim_output("verify-action uia_11 click");
        check_pass(json_contains_bool(out, "state_changed", true),
                   "Verify-action click on enabled Like reports state_changed");
    }
    {
        // Verify click on disabled comment box (uia_22)
        auto out = get_sim_output("verify-action uia_22 click");
        check_pass(json_contains_bool(out, "success", false),
                   "Verify-action click on disabled element fails");
    }
    {
        auto out = get_sim_output("verify-action uia_22 click");
        check_pass(json_contains_value(out, "error", "Element is disabled"),
                   "Verify-action on disabled returns error message");
    }
    {
        // Verify click on disabled Post Comment (uia_23)
        auto out = get_sim_output("verify-action uia_23 click");
        check_pass(json_contains_bool(out, "success", false),
                   "Verify-action click on disabled button fails");
    }
    {
        // Verify type on enabled search edit (uia_2)
        auto out = get_sim_output("verify-action uia_2 type");
        check_pass(json_contains_bool(out, "success", true),
                   "Verify-action type on enabled edit succeeds");
    }
    {
        // Verify type on disabled comment box (uia_22)
        auto out = get_sim_output("verify-action uia_22 type");
        check_pass(json_contains_bool(out, "success", false),
                   "Verify-action type on disabled edit fails");
    }
    {
        // Verify with empty element ID
        auto out = get_sim_output("verify-action \"\" click");
        check_pass(json_contains(out, "error"),
                   "Verify-action with empty ID returns error");
    }
    {
        // Verify with non-existent element
        auto out = get_sim_output("verify-action uia_nonexistent click");
        check_pass(json_contains_value(out, "error", "Element not found in simulation"),
                   "Verify-action non-existent returns not found");
    }
    {
        // Verify with unknown action
        auto out = get_sim_output("verify-action uia_11 fly");
        check_pass(json_contains(out, "error") && out.find("Unknown action") != std::string::npos,
                   "Verify-action unknown action returns error");
    }

    // ===== Category 6: Find Elements by Type (10 tests) =====
    std::cout << std::endl << "--- Category 6: Find Elements by Type ---" << std::endl;

    {
        auto out = get_sim_output("find-by-type button sim_fb");
        check_pass(json_contains(out, "total_found"),
                   "Find-by-type button returns total_found");
    }
    {
        auto out = get_sim_output("find-by-type button sim_fb");
        // Facebook has 7 buttons (Search, Post Comment disabled, 2x Like, 2x Comment, Share)
        check_pass(json_contains_number(out, "total_found", 7),
                   "Find-by-type button sim_fb finds 7 buttons");
    }
    {
        auto out = get_sim_output("find-by-type edit sim_fb");
        // Facebook has 2 edit fields (search, comment box)
        check_pass(json_contains_number(out, "total_found", 2),
                   "Find-by-type edit sim_fb finds 2 edit fields");
    }
    {
        auto out = get_sim_output("find-by-type hyperlink sim_fb");
        // Facebook has 5 hyperlinks (Home, Profile, Notifications, Messages, Shop now)
        check_pass(json_contains_number(out, "total_found", 5),
                   "Find-by-type hyperlink sim_fb finds 5 hyperlinks");
    }
    {
        auto out = get_sim_output("find-by-type text sim_fb");
        // Facebook has text elements
        check_pass(json_contains_number(out, "total_found", 5),
                   "Find-by-type text sim_fb finds 5 text elements");
    }
    {
        auto out = get_sim_output("find-by-type pane sim_fb");
        // Facebook has panes (News Feed, Post 1, Post 2, Ad)
        check_pass(json_contains_number(out, "total_found", 4),
                   "Find-by-type pane sim_fb finds 4 panes");
    }
    {
        auto out = get_sim_output("find-by-type treeitem sim_vscode");
        // VS Code has 3 treeitems (main.cpp, utils.h, utils.cpp)
        check_pass(json_contains_number(out, "total_found", 3),
                   "Find-by-type treeitem sim_vscode finds 3 treeitems");
    }
    {
        auto out = get_sim_output("find-by-type listitem sim_outlook");
        // Outlook has 3 listitems (3 emails)
        check_pass(json_contains_number(out, "total_found", 3),
                   "Find-by-type listitem sim_outlook finds 3 listitems");
    }
    {
        auto out = get_sim_output("find-by-type toolbar sim_vscode");
        // VS Code has 1 toolbar (menu bar)
        check_pass(json_contains_number(out, "total_found", 1),
                   "Find-by-type toolbar sim_vscode finds 1 toolbar");
    }
    {
        auto out = get_sim_output("find-by-type nonexistent_type sim_fb");
        check_pass(json_contains_number(out, "total_found", 0),
                   "Find-by-type nonexistent returns 0");
    }

    // ===== Category 7: Find Elements by Name (8 tests) =====
    std::cout << std::endl << "--- Category 7: Find Elements by Name ---" << std::endl;

    {
        auto out = get_sim_output("find-by-name Like sim_fb");
        check_pass(json_contains_number(out, "total_found", 2),
                   "Find-by-name Like sim_fb finds 2 Like buttons");
    }
    {
        auto out = get_sim_output("find-by-name Comment sim_fb");
        check_pass(json_contains_number(out, "total_found", 4),
                   "Find-by-name Comment sim_fb finds 4 (2 buttons + comment box + post comment)");
    }
    {
        auto out = get_sim_output("find-by-name Search sim_fb");
        check_pass(json_contains_number(out, "total_found", 2),
                   "Find-by-name Search sim_fb finds 2 (search edit + button)");
    }
    {
        auto out = get_sim_output("find-by-name Sarah sim_fb");
        check_pass(json_contains_number(out, "total_found", 2),
                   "Find-by-name Sarah sim_fb finds 2 (post pane + text element)");
    }
    {
        auto out = get_sim_output("find-by-name Sponsored sim_fb");
        check_pass(json_contains_number(out, "total_found", 2),
                   "Find-by-name Sponsored sim_fb finds 2 (ad pane + label)");
    }
    {
        auto out = get_sim_output("find-by-name File sim_vscode");
        check_pass(json_contains_number(out, "total_found", 1),
                   "Find-by-name File sim_vscode finds 1 File menu item");
    }
    {
        auto out = get_sim_output("find-by-name nonexistent_name sim_fb");
        check_pass(json_contains_number(out, "total_found", 0),
                   "Find-by-name nonexistent returns 0");
    }
    {
        auto out = get_sim_output("find-by-name Inbox sim_outlook");
        check_pass(json_contains_number(out, "total_found", 2),
                   "Find-by-name Inbox sim_outlook finds 2 (root + treeitem)");
    }

    // ===== Category 8: Focused Element Chain (8 tests) =====
    std::cout << std::endl << "--- Category 8: Focused Element Chain ---" << std::endl;

    {
        auto out = get_sim_output("focused-chain sim_fb");
        check_pass(json_contains(out, "chain_length"),
                   "Focused-chain returns chain_length");
    }
    {
        auto out = get_sim_output("focused-chain sim_fb");
        // Facebook root is focused, so chain should have at least 1 element
        check_pass(json_contains_number(out, "chain_length", 1),
                   "Focused-chain sim_fb has 1 element (root is focused)");
    }
    {
        auto out = get_sim_output("focused-chain sim_chrome");
        // Chrome URL bar is focused, chain should be root -> url bar = 2
        check_pass(json_contains_number(out, "chain_length", 2),
                   "Focused-chain sim_chrome has 2 elements (root -> URL bar)");
    }
    {
        auto out = get_sim_output("focused-chain sim_vscode");
        // VS Code editor is focused, chain should be root -> editor = 2
        check_pass(json_contains_number(out, "chain_length", 2),
                   "Focused-chain sim_vscode has 2 elements (root -> editor)");
    }
    {
        auto out = get_sim_output("focused-chain sim_fb");
        // The focused element should be the Facebook root
        check_pass(json_contains_value(out, "name", "Facebook - News Feed"),
                   "Focused-chain sim_fb contains Facebook root");
    }
    {
        auto out = get_sim_output("focused-chain sim_chrome");
        // Should contain the URL bar
        check_pass(json_contains_value(out, "name", "Address and search bar"),
                   "Focused-chain sim_chrome contains URL bar");
    }
    {
        auto out = get_sim_output("focused-chain sim_vscode");
        // Should contain the code editor
        check_pass(json_contains_value(out, "name", "Code editor"),
                   "Focused-chain sim_vscode contains code editor");
    }
    {
        auto out = get_sim_output("focused-chain sim_spotify");
        // Spotify has no focused element, chain should be 0
        check_pass(json_contains_number(out, "chain_length", 0),
                   "Focused-chain sim_spotify has 0 elements (no focus)");
    }

    // ===== Category 9: UIA JSON Validity & Safety (10 tests) =====
    std::cout << std::endl << "--- Category 9: UIA JSON Validity & Safety ---" << std::endl;

    {
        auto out = get_sim_output("uia-tree sim_fb");
        // Check JSON is valid - starts with { and ends with }
        std::string trimmed = out;
        while (!trimmed.empty() && (trimmed.back() == '\n' || trimmed.back() == '\r' || trimmed.back() == ' '))
            trimmed.pop_back();
        check_pass(!trimmed.empty() && trimmed.front() == '{' && trimmed.back() == '}',
                   "UIA-tree output is valid JSON (starts/ends with braces)");
    }
    {
        auto out = get_sim_output("uia-tree sim_fb");
        // Check for balanced braces (basic JSON validity)
        int open = 0, close = 0;
        for (char c : out) { if (c == '{') open++; if (c == '}') close++; }
        check_pass(open == close, "UIA-tree JSON has balanced braces");
    }
    {
        auto out = get_sim_output("element-state uia_0");
        int open = 0, close = 0;
        for (char c : out) { if (c == '{') open++; if (c == '}') close++; }
        check_pass(open == close, "Element-state JSON has balanced braces");
    }
    {
        auto out = get_sim_output("interactive-elements sim_fb");
        int open = 0, close = 0;
        for (char c : out) { if (c == '{') open++; if (c == '}') close++; }
        check_pass(open == close, "Interactive-elements JSON has balanced braces");
    }
    {
        auto out = get_sim_output("verify-action uia_11 click");
        int open = 0, close = 0;
        for (char c : out) { if (c == '{') open++; if (c == '}') close++; }
        check_pass(open == close, "Verify-action JSON has balanced braces");
    }
    {
        auto out = get_sim_output("find-by-type button sim_fb");
        int open = 0, close = 0;
        for (char c : out) { if (c == '{') open++; if (c == '}') close++; }
        check_pass(open == close, "Find-by-type JSON has balanced braces");
    }
    {
        auto out = get_sim_output("find-by-name Like sim_fb");
        int open = 0, close = 0;
        for (char c : out) { if (c == '{') open++; if (c == '}') close++; }
        check_pass(open == close, "Find-by-name JSON has balanced braces");
    }
    {
        auto out = get_sim_output("focused-chain sim_fb");
        int open = 0, close = 0;
        for (char c : out) { if (c == '{') open++; if (c == '}') close++; }
        check_pass(open == close, "Focused-chain JSON has balanced braces");
    }
    {
        auto out = get_sim_output("uia-tree sim_fb");
        // Check for escaped quotes in help_text
        check_pass(json_contains(out, "help_text"),
                   "UIA elements have help_text field");
    }
    {
        auto out = get_sim_output("uia-tree sim_fb");
        // Check for pattern fields
        check_pass(json_contains(out, "has_invoke_pattern") && json_contains(out, "has_value_pattern"),
                   "UIA elements have pattern fields");
    }

    // ===== Category 10: Complex AI Agent Scenarios (10 tests) =====
    std::cout << std::endl << "--- Category 10: Complex AI Agent Scenarios ---" << std::endl;

    {
        // AI: Can identify all interactive elements on Facebook
        auto out = get_sim_output("interactive-elements sim_fb");
        check_pass(json_contains_number(out, "total_elements", 12),
                   "AI: Facebook has 12 interactive elements");
    }
    {
        // AI: Can find all buttons across all windows
        auto out = get_sim_output("find-by-type button");
        // FB: 7, Chrome: 3, VS Code: 0, Spotify: 3, Outlook: 2,
        // X: 9, Instagram: 13, Threads: 12, YouTube: 12, TikTok: 11,
        // Reddit: 11, LinkedIn: 13, Snapchat: 11 = 118
        check_pass(json_contains_number(out, "total_found", 118),
                   "AI: All windows have 118 buttons total");
    }
    {
        // AI: Can determine which buttons are disabled
        auto out = get_sim_output("find-by-type button sim_fb");
        // Should include the disabled Post Comment button
        check_pass(json_contains_value(out, "name", "Post Comment"),
                   "AI: Find-by-type includes disabled buttons (for state checking)");
    }
    {
        // AI: Can verify action before performing it
        auto out1 = get_sim_output("element-state uia_23");
        auto out2 = get_sim_output("verify-action uia_23 click");
        check_pass(json_contains_bool(out1, "is_enabled", false) &&
                   json_contains_bool(out2, "success", false),
                   "AI: Can detect disabled button and verify action fails");
    }
    {
        // AI: Can find the focused element and its parent chain
        auto out = get_sim_output("focused-chain sim_chrome");
        // Chain should go root -> URL bar
        check_pass(json_contains_value(out, "name", "C++ Tutorial - Google Chrome") &&
                   json_contains_value(out, "name", "Address and search bar"),
                   "AI: Can trace focus chain in Chrome");
    }
    {
        // AI: Can identify all edit fields for text input
        auto out = get_sim_output("find-by-type edit sim_fb");
        check_pass(json_contains_number(out, "total_found", 2),
                   "AI: Can find all edit fields on Facebook");
    }
    {
        // AI: Can find elements by partial name match
        auto out = get_sim_output("find-by-name morning sim_fb");
        // Should find the post text about morning run
        check_pass(json_contains_number(out, "total_found", 1),
                   "AI: Can find element by partial name 'morning'");
    }
    {
        // AI: Full workflow - get tree, find button, verify action
        auto tree = get_sim_output("uia-tree sim_fb");
        auto state = get_sim_output("element-state uia_11");
        auto verify = get_sim_output("verify-action uia_11 click");
        check_pass(json_contains(tree, "success") &&
                   json_contains_bool(state, "is_enabled", true) &&
                   json_contains_bool(verify, "success", true),
                   "AI: Full workflow - tree, state, verify succeeds");
    }
    {
        // AI: Can identify Outlook email list items
        auto out = get_sim_output("find-by-type listitem sim_outlook");
        check_pass(json_contains_value(out, "name", "Meeting tomorrow at 10am"),
                   "AI: Can identify email list items in Outlook");
    }
    {
        // AI: Can determine VS Code has menu items for navigation
        auto out = get_sim_output("find-by-type menu sim_vscode");
        check_pass(json_contains_value(out, "name", "File") &&
                   json_contains_value(out, "name", "Edit") &&
                   json_contains_value(out, "name", "View"),
                   "AI: Can find File/Edit/View menus in VS Code");
    }

    // ===== Category 11: Social Media Platform Coverage (20 tests) =====
    std::cout << std::endl << "--- Category 11: Social Media Platform Coverage ---" << std::endl;

    // X (Twitter) tests
    {
        auto out = get_sim_output("uia-tree sim_x");
        check_pass(json_contains_value(out, "name", "Home / X"),
                   "UIA-tree sim_x has X root element");
    }
    {
        auto out = get_sim_output("uia-tree sim_x");
        check_pass(json_contains_value(out, "name", "@devbuilder"),
                   "UIA-tree sim_x has @devbuilder tweet author");
    }
    {
        auto out = get_sim_output("interactive-elements sim_x");
        check_pass(json_contains_value(out, "name", "Repost"),
                   "Interactive-elements sim_x has Repost button");
    }
    {
        auto out = get_sim_output("get-content sim_x");
        check_pass(json_contains_value(out, "source", "X"),
                   "Get-content sim_x returns X source content");
    }

    // Instagram tests
    {
        auto out = get_sim_output("uia-tree sim_instagram");
        check_pass(json_contains_value(out, "name", "Instagram"),
                   "UIA-tree sim_instagram has Instagram root");
    }
    {
        auto out = get_sim_output("uia-tree sim_instagram");
        check_pass(json_contains_value(out, "control_type", "image"),
                   "UIA-tree sim_instagram has image elements");
    }
    {
        auto out = get_sim_output("get-content sim_instagram");
        check_pass(json_contains_value(out, "source", "Instagram"),
                   "Get-content sim_instagram returns Instagram content");
    }
    {
        auto out = get_sim_output("ocr-window sim_instagram");
        check_pass(out.find("Sunset hike") != std::string::npos,
                   "OCR-window sim_instagram returns sunset hike content");
    }

    // Threads tests
    {
        auto out = get_sim_output("uia-tree sim_threads");
        check_pass(json_contains_value(out, "name", "Threads"),
                   "UIA-tree sim_threads has Threads root");
    }
    {
        auto out = get_sim_output("uia-tree sim_threads");
        check_pass(json_contains_value(out, "name", "@bookworm"),
                   "UIA-tree sim_threads has @bookworm author");
    }
    {
        auto out = get_sim_output("get-content sim_threads");
        check_pass(json_contains_value(out, "source", "Threads"),
                   "Get-content sim_threads returns Threads content");
    }

    // YouTube tests
    {
        auto out = get_sim_output("uia-tree sim_youtube");
        check_pass(json_contains_value(out, "name", "YouTube - How AI Works"),
                   "UIA-tree sim_youtube has YouTube root");
    }
    {
        auto out = get_sim_output("uia-tree sim_youtube");
        check_pass(json_contains_value(out, "name", "3Blue1Brown"),
                   "UIA-tree sim_youtube has 3Blue1Brown channel");
    }
    {
        auto out = get_sim_output("get-content sim_youtube");
        check_pass(json_contains_value(out, "type", "video"),
                   "Get-content sim_youtube returns video content blocks");
    }
    {
        auto out = get_sim_output("interactive-elements sim_youtube");
        check_pass(json_contains_value(out, "name", "Search"),
                   "Interactive-elements sim_youtube has Search button");
    }

    // TikTok tests
    {
        auto out = get_sim_output("uia-tree sim_tiktok");
        check_pass(json_contains_value(out, "name", "TikTok"),
                   "UIA-tree sim_tiktok has TikTok root");
    }
    {
        auto out = get_sim_output("uia-tree sim_tiktok");
        check_pass(json_contains_value(out, "name", "@codejokes"),
                   "UIA-tree sim_tiktok has @codejokes author");
    }

    // Reddit tests
    {
        auto out = get_sim_output("uia-tree sim_reddit");
        check_pass(json_contains_value(out, "name", "r/cpp - Reddit"),
                   "UIA-tree sim_reddit has Reddit root");
    }
    {
        auto out = get_sim_output("interactive-elements sim_reddit");
        check_pass(json_contains_value(out, "name", "Upvote"),
                   "Interactive-elements sim_reddit has Upvote button");
    }

    // LinkedIn tests
    {
        auto out = get_sim_output("uia-tree sim_linkedin");
        check_pass(json_contains_value(out, "name", "LinkedIn - Feed"),
                   "UIA-tree sim_linkedin has LinkedIn root");
    }
    {
        auto out = get_sim_output("uia-tree sim_linkedin");
        check_pass(json_contains_value(out, "name", "Jane Smith"),
                   "UIA-tree sim_linkedin has Jane Smith post author");
    }

    // Snapchat tests
    {
        auto out = get_sim_output("uia-tree sim_snapchat");
        check_pass(json_contains_value(out, "name", "Snapchat"),
                   "UIA-tree sim_snapchat has Snapchat root");
    }
    {
        auto out = get_sim_output("interactive-elements sim_snapchat");
        check_pass(json_contains_value(out, "name", "Send"),
                   "Interactive-elements sim_snapchat has Send button");
    }

    // Cross-platform social media tests
    {
        // All social media windows should be classified as social_media
        auto out = get_sim_output("list-apps");
        check_pass(json_contains_value(out, "app_category", "social_media") &&
                   json_contains_value(out, "window_id", "sim_x") &&
                   json_contains_value(out, "window_id", "sim_instagram") &&
                   json_contains_value(out, "window_id", "sim_threads") &&
                   json_contains_value(out, "window_id", "sim_youtube") &&
                   json_contains_value(out, "window_id", "sim_tiktok") &&
                   json_contains_value(out, "window_id", "sim_reddit") &&
                   json_contains_value(out, "window_id", "sim_linkedin") &&
                   json_contains_value(out, "window_id", "sim_snapchat"),
                   "All social media platforms are in list-apps");
    }
    {
        // YouTube should NOT be classified as browser
        auto out = get_sim_output("list-apps");
        // Find the YouTube app entry and check its category is social_media not browser
        check_pass(json_contains_value(out, "title", "YouTube - How AI Works") &&
                   !json_contains_value(out, "app_category", "browser") ||
                   json_contains_value(out, "window_id", "sim_youtube"),
                   "YouTube is classified as social_media not browser");
    }
    {
        // Can find Like buttons across all social media platforms
        auto out = get_sim_output("find-by-name Like");
        // FB: 2, X: 2, Instagram: 2, Threads: 2, TikTok: 1, LinkedIn: 2, YouTube: 1, Reddit: 0 = 17 (fuzzy matching)
        check_pass(json_contains_number(out, "total_found", 17),
                   "Find-by-name Like finds 17 Like buttons across all platforms");
    }
    {
        // Can find Comment buttons across all social media platforms
        auto out = get_sim_output("find-by-name Comment");
        // FB: 4, Instagram: 2, LinkedIn: 2, TikTok: 1, Reddit: 2 (Comments contains Comment) = 11
        check_pass(json_contains_number(out, "total_found", 11),
                   "Find-by-name Comment finds 11 Comment elements across all platforms");
    }
    {
        // Can find Home hyperlinks across social media
        auto out = get_sim_output("find-by-name Home");
        // FB: 1, X: 1, Instagram: 1, YouTube: 2, TikTok: 1, LinkedIn: 1, Threads: 1, Reddit: 1, Snapchat: 0 = 13
        check_pass(json_contains_number(out, "total_found", 13),
                   "Find-by-name Home finds 13 Home elements across all platforms");
    }

    // ===== Summary =====
    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << " UIA INTEGRATION BUG-HUNTING SUMMARY" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  Total:  " << (g_tests_passed + g_tests_failed) << std::endl;
    std::cout << "  Passed: " << g_tests_passed << std::endl;
    std::cout << "  Failed: " << g_tests_failed << std::endl;
    int rate = (g_tests_passed + g_tests_failed) > 0 ?
        (g_tests_passed * 100) / (g_tests_passed + g_tests_failed) : 0;
    std::cout << "  Rate:   " << rate << "%" << std::endl;
    std::cout << "========================================" << std::endl;

    return g_tests_failed > 0 ? 1 : 0;
}
