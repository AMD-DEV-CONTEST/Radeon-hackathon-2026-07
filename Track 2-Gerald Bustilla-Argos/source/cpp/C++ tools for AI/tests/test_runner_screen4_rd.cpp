// test_runner_screen4_rd.cpp - Reddit 100 tests
#include "test_screen4_common.h"

int main() {
    std::cout << "=== PLATFORM 6: Reddit - 100 tests ===" << std::endl;

    // UIA Tree Structure (20 tests)
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains(out, "success"), "RD: UIA-tree returns success"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "r/cpp - Reddit"), "RD: Root element is 'r/cpp - Reddit'"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains(out, "total_elements"), "RD: Has total_elements field"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "Top bar"), "RD: Has Top bar pane"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "Subreddits"), "RD: Has Subreddits left rail pane"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "Sidebar"), "RD: Has Sidebar pane"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(count_depth(out, 0) == 1, "RD: Has 1 root at depth 0"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(count_type(out, "button") >= 8, "RD: Has >=8 button elements"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(count_type(out, "hyperlink") >= 8, "RD: Has >=8 hyperlink elements"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(count_type(out, "edit") >= 1, "RD: Has >=1 edit element (search)"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(count_type(out, "text") >= 5, "RD: Has >=5 text elements"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains(out, "element_id"), "RD: Elements have element_id"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains(out, "parent_id"), "RD: Elements have parent_id"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains(out, "bounds"), "RD: Elements have bounds"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains(out, "max_depth"), "RD: Has max_depth field"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains(out, "root_element_id"), "RD: Has root_element_id"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains(out, "error"), "RD: Has error field"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "control_type", "window"), "RD: Has window control type"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(count_type(out, "pane") >= 5, "RD: Has >=5 pane elements"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(count_depth(out, 1) >= 3, "RD: Has >=3 elements at depth 1"); }

    // Platform-Specific Elements (20 tests)
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "Sort: Hot"), "RD: Has Sort: Hot dropdown button"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "r/cpp"), "RD: Has r/cpp subreddit link"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "r/programming"), "RD: Has r/programming subreddit link"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "r/learnprogramming"), "RD: Has r/learnprogramming subreddit link"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "Popular"), "RD: Has Popular feed link"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "Join"), "RD: Has Join subreddit button"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "Upvote"), "RD: Has Upvote button"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "Downvote"), "RD: Has Downvote button"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "Save"), "RD: Has Save button"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "Share"), "RD: Has Share button"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "Comments"), "RD: Has Comments button"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "About r/cpp"), "RD: Has About r/cpp link"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "Rules"), "RD: Has Rules link"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "Wiki"), "RD: Has Wiki link"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "125K members"), "RD: Has member count text"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "u/cpp_enthusiast"), "RD: Has u/cpp_enthusiast author"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "name", "u/learning_cpp"), "RD: Has u/learning_cpp author"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "help_text", "Sort posts (Hot/New/Top/Rising)"), "RD: Sort has help_text"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "help_text", "Join subreddit"), "RD: Join has help_text"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "help_text", "Save post"), "RD: Save has help_text"); }

    // Interactive Elements (15 tests)
    { auto out = get_sim_output("interactive-elements sim_reddit"); check_pass(json_contains(out, "total_elements"), "RD: Interactive-elements returns total_elements"); }
    { auto out = get_sim_output("interactive-elements sim_reddit"); check_pass(json_contains(out, "total_elements"), "RD: Interactive-elements has total_elements"); }
    { auto out = get_sim_output("interactive-elements sim_reddit"); check_pass(json_contains_value(out, "name", "Upvote"), "RD: Interactive-elements has Upvote"); }
    { auto out = get_sim_output("interactive-elements sim_reddit"); check_pass(json_contains_value(out, "name", "Downvote"), "RD: Interactive-elements has Downvote"); }
    { auto out = get_sim_output("interactive-elements sim_reddit"); check_pass(json_contains_value(out, "name", "Save"), "RD: Interactive-elements has Save"); }
    { auto out = get_sim_output("interactive-elements sim_reddit"); check_pass(json_contains_value(out, "name", "Share"), "RD: Interactive-elements has Share"); }
    { auto out = get_sim_output("interactive-elements sim_reddit"); check_pass(json_contains_value(out, "name", "Join"), "RD: Interactive-elements has Join"); }
    { auto out = get_sim_output("interactive-elements sim_reddit"); check_pass(json_contains_value(out, "name", "Comments"), "RD: Interactive-elements has Comments"); }
    { auto out = get_sim_output("interactive-elements sim_reddit"); check_pass(json_contains_value(out, "name", "Search"), "RD: Interactive-elements has Search"); }
    { auto out = get_sim_output("interactive-elements sim_reddit"); check_pass(json_contains_value(out, "name", "Sort: Hot"), "RD: Interactive-elements has Sort"); }
    { auto out = get_sim_output("interactive-elements sim_reddit"); check_pass(json_contains_value(out, "name", "r/cpp"), "RD: Interactive-elements has r/cpp link"); }
    { auto out = get_sim_output("interactive-elements sim_reddit"); check_pass(json_contains_value(out, "action_type", "click"), "RD: Interactive-elements has click action"); }
    { auto out = get_sim_output("interactive-elements sim_reddit"); check_pass(json_contains(out, "element_id"), "RD: Interactive-elements has element_id"); }
    { auto out = get_sim_output("interactive-elements sim_reddit"); check_pass(json_contains(out, "control_type"), "RD: Interactive-elements has control_type"); }
    { auto out = get_sim_output("interactive-elements sim_reddit"); check_pass(get_total(out, "total_elements") >= 12, "RD: Has >=12 interactive elements"); }

    // Content & OCR (15 tests)
    { auto out = get_sim_output("get-content sim_reddit"); check_pass(json_contains(out, "total_blocks"), "RD: Get-content returns total_blocks"); }
    { auto out = get_sim_output("get-content sim_reddit"); check_pass(json_contains_value(out, "source", "Reddit"), "RD: Get-content returns Reddit source"); }
    { auto out = get_sim_output("get-content sim_reddit"); check_pass(json_contains(out, "blocks"), "RD: Get-content has blocks array"); }
    { auto out = get_sim_output("get-content sim_reddit"); check_pass(json_contains_value(out, "type", "post"), "RD: Get-content has post-type blocks"); }
    { auto out = get_sim_output("get-content sim_reddit"); check_pass(out.find("cpp_enthusiast") != std::string::npos, "RD: Get-content contains cpp_enthusiast"); }
    { auto out = get_sim_output("ocr-window sim_reddit"); check_pass(json_contains(out, "success"), "RD: OCR-window returns success"); }
    { auto out = get_sim_output("ocr-window sim_reddit"); check_pass(out.find("C++20") != std::string::npos, "RD: OCR-window contains C++20 text"); }
    { auto out = get_sim_output("ocr-window sim_reddit"); check_pass(json_contains(out, "regions"), "RD: OCR-window has regions array"); }
    { auto out = get_sim_output("search-content C++ sim_reddit"); check_pass(json_contains(out, "total_results"), "RD: Search-content 'C++' returns total_results"); }
    { auto out = get_sim_output("search-content C++ sim_reddit"); check_pass(json_contains_value(out, "source", "Reddit"), "RD: Search-content returns Reddit source"); }
    { auto out = get_sim_output("search-content vector sim_reddit"); check_pass(json_contains(out, "total_results"), "RD: Search-content 'vector' has total_results"); }
    { auto out = get_sim_output("search-content nonexistent12345 sim_reddit"); check_pass(json_contains_number(out, "total_results", 0), "RD: Search-content nonexistent returns 0"); }
    { auto out = get_sim_output("get-content sim_reddit"); check_pass(json_contains(out, "total_blocks"), "RD: Get-content has total_blocks"); }
    { auto out = get_sim_output("search-content reserve sim_reddit"); check_pass(json_contains(out, "total_results"), "RD: Search-content 'reserve' has total_results"); }
    { auto out = get_sim_output("get-content sim_reddit"); check_pass(json_contains(out, "blocks"), "RD: Get-content has blocks field"); }

    // Find Elements (15 tests)
    { auto out = get_sim_output("find-by-type button sim_reddit"); check_pass(json_contains(out, "total_found"), "RD: Find-by-type button returns total_found"); }
    { auto out = get_sim_output("find-by-type button sim_reddit"); check_pass(json_contains_value(out, "name", "Upvote"), "RD: Find-by-type button finds Upvote"); }
    { auto out = get_sim_output("find-by-type button sim_reddit"); check_pass(json_contains_value(out, "name", "Downvote"), "RD: Find-by-type button finds Downvote"); }
    { auto out = get_sim_output("find-by-type button sim_reddit"); check_pass(json_contains_value(out, "name", "Save"), "RD: Find-by-type button finds Save"); }
    { auto out = get_sim_output("find-by-type button sim_reddit"); check_pass(json_contains_value(out, "name", "Join"), "RD: Find-by-type button finds Join"); }
    { auto out = get_sim_output("find-by-type hyperlink sim_reddit"); check_pass(json_contains_value(out, "name", "r/cpp"), "RD: Find-by-type hyperlink finds r/cpp"); }
    { auto out = get_sim_output("find-by-type hyperlink sim_reddit"); check_pass(json_contains_value(out, "name", "Popular"), "RD: Find-by-type hyperlink finds Popular"); }
    { auto out = get_sim_output("find-by-name Upvote sim_reddit"); check_pass(json_contains_value(out, "name", "Upvote"), "RD: Find-by-name Upvote finds Upvote"); }
    { auto out = get_sim_output("find-by-name Join sim_reddit"); check_pass(json_contains_value(out, "name", "Join"), "RD: Find-by-name Join finds Join"); }
    { auto out = get_sim_output("find-by-name Rules sim_reddit"); check_pass(json_contains_value(out, "name", "Rules"), "RD: Find-by-name Rules finds Rules"); }
    { auto out = get_sim_output("find-by-name Wiki sim_reddit"); check_pass(json_contains_value(out, "name", "Wiki"), "RD: Find-by-name Wiki finds Wiki"); }
    { auto out = get_sim_output("find-by-name Sort sim_reddit"); check_pass(json_contains_value(out, "name", "Sort: Hot"), "RD: Find-by-name Sort finds Sort: Hot"); }
    { auto out = get_sim_output("find-by-type edit sim_reddit"); check_pass(json_contains_value(out, "name", "Search Reddit"), "RD: Find-by-type edit finds Search"); }
    { auto out = get_sim_output("find-by-type pane sim_reddit"); check_pass(json_contains(out, "total_found"), "RD: Find-by-type pane has total_found"); }
    { auto out = get_sim_output("find-by-name Comments sim_reddit"); check_pass(json_contains_value(out, "name", "Comments"), "RD: Find-by-name Comments finds Comments"); }

    // Element State & Patterns (15 tests)
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_bool(out, "is_enabled", true), "RD: Elements have is_enabled true"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_bool(out, "is_visible", true), "RD: Elements have is_visible true"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains(out, "has_invoke_pattern"), "RD: Elements have has_invoke_pattern"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains(out, "has_value_pattern"), "RD: Elements have has_value_pattern"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains(out, "is_keyboard_focusable"), "RD: Elements have is_keyboard_focusable"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains(out, "help_text"), "RD: Elements have help_text"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "help_text", "Subscribed communities"), "RD: Subreddits pane has help_text"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "help_text", "Top navigation bar"), "RD: Top bar has help_text"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "help_text", "Subreddit sidebar"), "RD: Sidebar has help_text"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "help_text", "Community rules"), "RD: Rules has help_text"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "help_text", "Community wiki"), "RD: Wiki has help_text"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "help_text", "Upvote"), "RD: Upvote has help_text"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "help_text", "Downvote"), "RD: Downvote has help_text"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "help_text", "Share post"), "RD: Share has help_text"); }
    { auto out = get_sim_output("uia-tree sim_reddit"); check_pass(json_contains_value(out, "help_text", "Reddit home feed"), "RD: Home link has help_text"); }

    print_summary("REDDIT TEST SUMMARY");
    return g_tests_failed > 0 ? 1 : 0;
}
