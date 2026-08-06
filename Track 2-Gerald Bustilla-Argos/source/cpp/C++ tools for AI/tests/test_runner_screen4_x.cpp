// test_runner_screen4_x.cpp - X (Twitter) 100 tests
#include "test_screen4_common.h"

int main() {
    std::cout << "=== PLATFORM 1: X (Twitter) - 100 tests ===" << std::endl;

    // UIA Tree Structure (20 tests)
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains(out, "success"), "X: UIA-tree returns success"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Home / X"), "X: Root element is 'Home / X'"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "control_type", "window"), "X: Has window control type"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains(out, "total_elements"), "X: Has total_elements field"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains(out, "max_depth"), "X: Has max_depth field"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Navigation"), "X: Has Navigation pane"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Feed"), "X: Has Feed pane"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Trends sidebar"), "X: Has Trends sidebar"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Feed tabs"), "X: Has Feed tabs pane"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(count_depth(out, 0) == 1, "X: Has 1 root at depth 0"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(count_depth(out, 1) >= 3, "X: Has >=3 elements at depth 1"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(count_depth(out, 2) >= 10, "X: Has >=10 elements at depth 2"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(count_depth(out, 3) >= 10, "X: Has >=10 elements at depth 3"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(count_type(out, "button") >= 5, "X: Has >=5 button elements"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(count_type(out, "hyperlink") >= 5, "X: Has >=5 hyperlink elements"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(count_type(out, "text") >= 5, "X: Has >=5 text elements"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(count_type(out, "edit") >= 1, "X: Has >=1 edit element (compose)"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(count_type(out, "pane") >= 5, "X: Has >=5 pane elements"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains(out, "element_id") && json_contains(out, "parent_id"), "X: Elements have element_id and parent_id"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains(out, "bounds"), "X: Elements have bounds"); }

    // Platform-Specific Elements (20 tests)
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "For you"), "X: Has 'For you' feed tab"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Following"), "X: Has 'Following' feed tab"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Explore"), "X: Has Explore nav link"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Communities"), "X: Has Communities nav link"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Notifications"), "X: Has Notifications nav link"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Messages"), "X: Has Messages nav link"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Grok"), "X: Has Grok AI assistant nav link"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Bookmarks"), "X: Has Bookmarks nav link"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Profile"), "X: Has Profile nav link"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Search X"), "X: Has search edit in trends sidebar"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "What's happening"), "X: Has 'What's happening' trends header"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Who to follow"), "X: Has 'Who to follow' suggestions header"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Community Notes"), "X: Has Community Notes pane"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Verified"), "X: Has Verified badge text"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Views"), "X: Has Views count text"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Share"), "X: Has Share button"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Repost"), "X: Has Repost button"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Reply"), "X: Has Reply button"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "Like"), "X: Has Like button"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "name", "@devbuilder"), "X: Has @devbuilder author handle"); }

    // Interactive Elements (15 tests)
    { auto out = get_sim_output("interactive-elements sim_x"); check_pass(json_contains(out, "total_elements"), "X: Interactive-elements returns total_elements"); }
    { auto out = get_sim_output("interactive-elements sim_x"); check_pass(json_contains(out, "total_elements"), "X: Interactive-elements has total_elements"); }
    { auto out = get_sim_output("interactive-elements sim_x"); check_pass(json_contains_value(out, "name", "Post"), "X: Interactive-elements has Post button"); }
    { auto out = get_sim_output("interactive-elements sim_x"); check_pass(json_contains_value(out, "name", "Like"), "X: Interactive-elements has Like button"); }
    { auto out = get_sim_output("interactive-elements sim_x"); check_pass(json_contains_value(out, "name", "Repost"), "X: Interactive-elements has Repost button"); }
    { auto out = get_sim_output("interactive-elements sim_x"); check_pass(json_contains_value(out, "name", "Reply"), "X: Interactive-elements has Reply button"); }
    { auto out = get_sim_output("interactive-elements sim_x"); check_pass(json_contains_value(out, "name", "Share"), "X: Interactive-elements has Share button"); }
    { auto out = get_sim_output("interactive-elements sim_x"); check_pass(json_contains_value(out, "name", "Home"), "X: Interactive-elements has Home hyperlink"); }
    { auto out = get_sim_output("interactive-elements sim_x"); check_pass(json_contains_value(out, "name", "Explore"), "X: Interactive-elements has Explore hyperlink"); }
    { auto out = get_sim_output("interactive-elements sim_x"); check_pass(json_contains_value(out, "name", "Search X"), "X: Interactive-elements has Search edit"); }
    { auto out = get_sim_output("interactive-elements sim_x"); check_pass(json_contains_value(out, "action_type", "click"), "X: Interactive-elements has click action"); }
    { auto out = get_sim_output("interactive-elements sim_x"); check_pass(json_contains_value(out, "action_type", "type"), "X: Interactive-elements has type action for edit"); }
    { auto out = get_sim_output("interactive-elements sim_x"); check_pass(json_contains(out, "element_id"), "X: Interactive-elements has element_id"); }
    { auto out = get_sim_output("interactive-elements sim_x"); check_pass(json_contains(out, "control_type"), "X: Interactive-elements has control_type"); }
    { auto out = get_sim_output("interactive-elements sim_x"); check_pass(get_total(out, "total_elements") >= 15, "X: Has >=15 interactive elements"); }

    // Content & OCR (15 tests)
    { auto out = get_sim_output("get-content sim_x"); check_pass(json_contains(out, "total_blocks"), "X: Get-content returns total_blocks"); }
    { auto out = get_sim_output("get-content sim_x"); check_pass(json_contains_value(out, "source", "X"), "X: Get-content returns X source"); }
    { auto out = get_sim_output("get-content sim_x"); check_pass(json_contains(out, "blocks"), "X: Get-content has blocks array"); }
    { auto out = get_sim_output("get-content sim_x"); check_pass(json_contains_value(out, "type", "post"), "X: Get-content has post-type blocks"); }
    { auto out = get_sim_output("get-content sim_x"); check_pass(out.find("devbuilder") != std::string::npos, "X: Get-content contains devbuilder"); }
    { auto out = get_sim_output("ocr-window sim_x"); check_pass(json_contains(out, "success"), "X: OCR-window returns success"); }
    { auto out = get_sim_output("ocr-window sim_x"); check_pass(out.find("Real-time") != std::string::npos, "X: OCR-window contains Real-time text"); }
    { auto out = get_sim_output("ocr-window sim_x"); check_pass(out.find("AI won't replace") != std::string::npos, "X: OCR-window contains AI text"); }
    { auto out = get_sim_output("ocr-window sim_x"); check_pass(out.find("BuildInPublic") != std::string::npos || out.find("buildinpublic") != std::string::npos, "X: OCR-window contains #BuildInPublic hashtag"); }
    { auto out = get_sim_output("ocr-window sim_x"); check_pass(json_contains(out, "regions"), "X: OCR-window has regions array"); }
    { auto out = get_sim_output("search-content Real-time sim_x"); check_pass(json_contains(out, "total_results"), "X: Search-content 'Real-time' returns total_results"); }
    { auto out = get_sim_output("search-content Real-time sim_x"); check_pass(json_contains_value(out, "source", "X"), "X: Search-content returns X source"); }
    { auto out = get_sim_output("search-content collaboration sim_x"); check_pass(out.find("collaboration") != std::string::npos, "X: Search-content finds 'collaboration'"); }
    { auto out = get_sim_output("search-content nonexistent12345 sim_x"); check_pass(json_contains(out, "total_results"), "X: Search-content nonexistent returns total_results"); }
    { auto out = get_sim_output("search-content AI sim_x"); check_pass(json_contains(out, "total_results"), "X: Search-content 'AI' has total_results field"); }

    // Find Elements (15 tests)
    { auto out = get_sim_output("find-by-type button sim_x"); check_pass(json_contains(out, "total_found"), "X: Find-by-type button returns total_found"); }
    { auto out = get_sim_output("find-by-type button sim_x"); check_pass(json_contains(out, "total_found"), "X: Find-by-type button has total_found"); }
    { auto out = get_sim_output("find-by-type button sim_x"); check_pass(json_contains_value(out, "name", "Post"), "X: Find-by-type button finds Post"); }
    { auto out = get_sim_output("find-by-type button sim_x"); check_pass(json_contains_value(out, "name", "Like"), "X: Find-by-type button finds Like"); }
    { auto out = get_sim_output("find-by-type hyperlink sim_x"); check_pass(json_contains_value(out, "name", "Home"), "X: Find-by-type hyperlink finds Home"); }
    { auto out = get_sim_output("find-by-type hyperlink sim_x"); check_pass(json_contains_value(out, "name", "Explore"), "X: Find-by-type hyperlink finds Explore"); }
    { auto out = get_sim_output("find-by-type edit sim_x"); check_pass(json_contains_value(out, "name", "Post"), "X: Find-by-type edit finds compose box"); }
    { auto out = get_sim_output("find-by-type edit sim_x"); check_pass(json_contains_value(out, "name", "Search X"), "X: Find-by-type edit finds Search X"); }
    { auto out = get_sim_output("find-by-name Repost sim_x"); check_pass(json_contains(out, "total_found"), "X: Find-by-name Repost has total_found"); }
    { auto out = get_sim_output("find-by-name Repost sim_x"); check_pass(json_contains_value(out, "name", "Repost"), "X: Find-by-name Repost finds Repost"); }
    { auto out = get_sim_output("find-by-name Grok sim_x"); check_pass(json_contains_value(out, "name", "Grok"), "X: Find-by-name Grok finds Grok"); }
    { auto out = get_sim_output("find-by-name Bookmarks sim_x"); check_pass(json_contains_value(out, "name", "Bookmarks"), "X: Find-by-name Bookmarks finds Bookmarks"); }
    { auto out = get_sim_output("find-by-name Communities sim_x"); check_pass(json_contains_value(out, "name", "Communities"), "X: Find-by-name Communities finds Communities"); }
    { auto out = get_sim_output("find-by-type pane sim_x"); check_pass(json_contains(out, "total_found"), "X: Find-by-type pane has total_found"); }
    { auto out = get_sim_output("find-by-type image sim_x"); check_pass(json_contains(out, "total_found"), "X: Find-by-type image has total_found"); }

    // Element State & Patterns (15 tests)
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_bool(out, "is_enabled", true), "X: Elements have is_enabled true"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_bool(out, "is_visible", true), "X: Elements have is_visible true"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains(out, "has_invoke_pattern"), "X: Elements have has_invoke_pattern field"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains(out, "has_value_pattern"), "X: Elements have has_value_pattern field"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains(out, "is_keyboard_focusable"), "X: Elements have is_keyboard_focusable field"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains(out, "help_text"), "X: Elements have help_text field"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "help_text", "Side navigation rail"), "X: Nav pane has help_text"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "help_text", "Main feed column"), "X: Feed pane has help_text"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "help_text", "What's happening sidebar"), "X: Trends sidebar has help_text"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "help_text", "Algorithmic feed"), "X: For you tab has help_text"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "help_text", "Chronological feed from followed accounts"), "X: Following tab has help_text"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "help_text", "Grok AI assistant"), "X: Grok has help_text"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "help_text", "Community-contributed context"), "X: Community Notes has help_text"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "help_text", "Compose new post"), "X: Post button has help_text"); }
    { auto out = get_sim_output("uia-tree sim_x"); check_pass(json_contains_value(out, "help_text", "Tweet content"), "X: Tweet content has help_text"); }

    print_summary("X (TWITTER) TEST SUMMARY");
    return g_tests_failed > 0 ? 1 : 0;
}
