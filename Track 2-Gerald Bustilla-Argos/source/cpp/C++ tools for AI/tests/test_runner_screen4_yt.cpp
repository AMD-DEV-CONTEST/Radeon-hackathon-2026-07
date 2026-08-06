// test_runner_screen4_yt.cpp - YouTube 100 tests
#include "test_screen4_common.h"

int main() {
    std::cout << "=== PLATFORM 4: YouTube - 100 tests ===" << std::endl;

    // UIA Tree Structure (20 tests)
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains(out, "success"), "YT: UIA-tree returns success"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "YouTube - How AI Works"), "YT: Root element is 'YouTube - How AI Works'"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains(out, "total_elements"), "YT: Has total_elements field"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Top bar"), "YT: Has Top bar pane"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Sidebar"), "YT: Has Sidebar pane"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Bottom navigation"), "YT: Has Bottom navigation pane"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Video actions"), "YT: Has Video actions pane"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(count_depth(out, 0) == 1, "YT: Has 1 root at depth 0"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(count_type(out, "button") >= 10, "YT: Has >=10 button elements"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(count_type(out, "hyperlink") >= 5, "YT: Has >=5 hyperlink elements"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(count_type(out, "image") >= 2, "YT: Has >=2 image elements (thumbnails)"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(count_type(out, "edit") >= 1, "YT: Has >=1 edit element (search)"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains(out, "element_id"), "YT: Elements have element_id"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains(out, "parent_id"), "YT: Elements have parent_id"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains(out, "bounds"), "YT: Elements have bounds"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains(out, "max_depth"), "YT: Has max_depth field"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains(out, "root_element_id"), "YT: Has root_element_id"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains(out, "error"), "YT: Has error field"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "control_type", "window"), "YT: Has window control type"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(count_type(out, "pane") >= 5, "YT: Has >=5 pane elements"); }

    // Platform-Specific Elements (20 tests)
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Shorts"), "YT: Has Shorts nav link"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Subscriptions"), "YT: Has Subscriptions nav link"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Trending"), "YT: Has Trending nav link"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Watch Later"), "YT: Has Watch Later nav link"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Liked Videos"), "YT: Has Liked Videos nav link"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Your Channel"), "YT: Has Your Channel nav link"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Subscribe"), "YT: Has Subscribe button"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Like"), "YT: Has Like button"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Dislike"), "YT: Has Dislike button"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Save"), "YT: Has Save button"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Share"), "YT: Has Share button"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Create"), "YT: Has Create nav button"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "3Blue1Brown"), "YT: Has 3Blue1Brown channel"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "TheCherno"), "YT: Has TheCherno channel"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "Sponsored: Skillshare"), "YT: Has sponsored content pane"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "name", "You"), "YT: Has 'You' profile nav button"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "help_text", "Shorts (vertical videos)"), "YT: Shorts has help_text"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "help_text", "Subscribe to channel"), "YT: Subscribe has help_text"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "help_text", "Like video"), "YT: Like has help_text"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "help_text", "Save to playlist"), "YT: Save has help_text"); }

    // Interactive Elements (15 tests)
    { auto out = get_sim_output("interactive-elements sim_youtube"); check_pass(json_contains(out, "total_elements"), "YT: Interactive-elements returns total_elements"); }
    { auto out = get_sim_output("interactive-elements sim_youtube"); check_pass(json_contains(out, "total_elements"), "YT: Interactive-elements has total_elements"); }
    { auto out = get_sim_output("interactive-elements sim_youtube"); check_pass(json_contains_value(out, "name", "Search"), "YT: Interactive-elements has Search"); }
    { auto out = get_sim_output("interactive-elements sim_youtube"); check_pass(json_contains_value(out, "name", "Subscribe"), "YT: Interactive-elements has Subscribe"); }
    { auto out = get_sim_output("interactive-elements sim_youtube"); check_pass(json_contains_value(out, "name", "Like"), "YT: Interactive-elements has Like"); }
    { auto out = get_sim_output("interactive-elements sim_youtube"); check_pass(json_contains_value(out, "name", "Dislike"), "YT: Interactive-elements has Dislike"); }
    { auto out = get_sim_output("interactive-elements sim_youtube"); check_pass(json_contains_value(out, "name", "Share"), "YT: Interactive-elements has Share"); }
    { auto out = get_sim_output("interactive-elements sim_youtube"); check_pass(json_contains_value(out, "name", "Save"), "YT: Interactive-elements has Save"); }
    { auto out = get_sim_output("interactive-elements sim_youtube"); check_pass(json_contains_value(out, "name", "Home"), "YT: Interactive-elements has Home"); }
    { auto out = get_sim_output("interactive-elements sim_youtube"); check_pass(json_contains_value(out, "name", "Shorts"), "YT: Interactive-elements has Shorts"); }
    { auto out = get_sim_output("interactive-elements sim_youtube"); check_pass(json_contains_value(out, "name", "Create"), "YT: Interactive-elements has Create"); }
    { auto out = get_sim_output("interactive-elements sim_youtube"); check_pass(json_contains_value(out, "action_type", "click"), "YT: Interactive-elements has click action"); }
    { auto out = get_sim_output("interactive-elements sim_youtube"); check_pass(json_contains_value(out, "action_type", "type"), "YT: Interactive-elements has type action"); }
    { auto out = get_sim_output("interactive-elements sim_youtube"); check_pass(json_contains(out, "element_id"), "YT: Interactive-elements has element_id"); }
    { auto out = get_sim_output("interactive-elements sim_youtube"); check_pass(get_total(out, "total_elements") >= 15, "YT: Has >=15 interactive elements"); }

    // Content & OCR (15 tests)
    { auto out = get_sim_output("get-content sim_youtube"); check_pass(json_contains(out, "total_blocks"), "YT: Get-content returns total_blocks"); }
    { auto out = get_sim_output("get-content sim_youtube"); check_pass(json_contains_value(out, "source", "YouTube"), "YT: Get-content returns YouTube source"); }
    { auto out = get_sim_output("get-content sim_youtube"); check_pass(json_contains(out, "blocks"), "YT: Get-content has blocks array"); }
    { auto out = get_sim_output("get-content sim_youtube"); check_pass(json_contains_value(out, "type", "video"), "YT: Get-content has video-type blocks"); }
    { auto out = get_sim_output("get-content sim_youtube"); check_pass(out.find("3Blue1Brown") != std::string::npos || out.find("Neural") != std::string::npos, "YT: Get-content contains video info"); }
    { auto out = get_sim_output("ocr-window sim_youtube"); check_pass(json_contains(out, "success"), "YT: OCR-window returns success"); }
    { auto out = get_sim_output("ocr-window sim_youtube"); check_pass(out.find("Neural Networks") != std::string::npos, "YT: OCR-window contains Neural Networks text"); }
    { auto out = get_sim_output("ocr-window sim_youtube"); check_pass(json_contains(out, "regions"), "YT: OCR-window has regions array"); }
    { auto out = get_sim_output("search-content Neural sim_youtube"); check_pass(json_contains(out, "total_results"), "YT: Search-content 'Neural' returns total_results"); }
    { auto out = get_sim_output("search-content Neural sim_youtube"); check_pass(json_contains_value(out, "source", "YouTube"), "YT: Search-content returns YouTube source"); }
    { auto out = get_sim_output("search-content Game Engine sim_youtube"); check_pass(json_contains(out, "total_results"), "YT: Search-content 'Game Engine' has total_results"); }
    { auto out = get_sim_output("search-content nonexistent12345 sim_youtube"); check_pass(json_contains(out, "total_results"), "YT: Search-content nonexistent returns total_results"); }
    { auto out = get_sim_output("get-content sim_youtube"); check_pass(json_contains(out, "total_blocks"), "YT: Get-content has total_blocks"); }
    { auto out = get_sim_output("search-content Sponsored sim_youtube"); check_pass(json_contains(out, "total_results"), "YT: Search-content 'Sponsored' has total_results"); }
    { auto out = get_sim_output("get-content sim_youtube"); check_pass(json_contains(out, "blocks"), "YT: Get-content has blocks field"); }

    // Find Elements (15 tests)
    { auto out = get_sim_output("find-by-type button sim_youtube"); check_pass(json_contains(out, "total_found"), "YT: Find-by-type button returns total_found"); }
    { auto out = get_sim_output("find-by-type button sim_youtube"); check_pass(json_contains_value(out, "name", "Subscribe"), "YT: Find-by-type button finds Subscribe"); }
    { auto out = get_sim_output("find-by-type button sim_youtube"); check_pass(json_contains_value(out, "name", "Like"), "YT: Find-by-type button finds Like"); }
    { auto out = get_sim_output("find-by-type button sim_youtube"); check_pass(json_contains_value(out, "name", "Dislike"), "YT: Find-by-type button finds Dislike"); }
    { auto out = get_sim_output("find-by-type hyperlink sim_youtube"); check_pass(json_contains_value(out, "name", "Shorts"), "YT: Find-by-type hyperlink finds Shorts"); }
    { auto out = get_sim_output("find-by-type hyperlink sim_youtube"); check_pass(json_contains_value(out, "name", "Watch Later"), "YT: Find-by-type hyperlink finds Watch Later"); }
    { auto out = get_sim_output("find-by-name Subscribe sim_youtube"); check_pass(json_contains_value(out, "name", "Subscribe"), "YT: Find-by-name Subscribe finds Subscribe"); }
    { auto out = get_sim_output("find-by-name Shorts sim_youtube"); check_pass(json_contains_value(out, "name", "Shorts"), "YT: Find-by-name Shorts finds Shorts"); }
    { auto out = get_sim_output("find-by-name Dislike sim_youtube"); check_pass(json_contains_value(out, "name", "Dislike"), "YT: Find-by-name Dislike finds Dislike"); }
    { auto out = get_sim_output("find-by-name Trending sim_youtube"); check_pass(json_contains_value(out, "name", "Trending"), "YT: Find-by-name Trending finds Trending"); }
    { auto out = get_sim_output("find-by-type edit sim_youtube"); check_pass(json_contains_value(out, "name", "Search"), "YT: Find-by-type edit finds Search"); }
    { auto out = get_sim_output("find-by-type image sim_youtube"); check_pass(json_contains_value(out, "name", "Thumbnail"), "YT: Find-by-type image finds Thumbnail"); }
    { auto out = get_sim_output("find-by-type pane sim_youtube"); check_pass(json_contains(out, "total_found"), "YT: Find-by-type pane has total_found"); }
    { auto out = get_sim_output("find-by-name Create sim_youtube"); check_pass(json_contains_value(out, "name", "Create"), "YT: Find-by-name Create finds Create"); }
    { auto out = get_sim_output("find-by-name Liked sim_youtube"); check_pass(json_contains_value(out, "name", "Liked Videos"), "YT: Find-by-name Liked finds Liked Videos"); }

    // Element State & Patterns (15 tests)
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_bool(out, "is_enabled", true), "YT: Elements have is_enabled true"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_bool(out, "is_visible", true), "YT: Elements have is_visible true"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains(out, "has_invoke_pattern"), "YT: Elements have has_invoke_pattern"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains(out, "has_value_pattern"), "YT: Elements have has_value_pattern"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains(out, "is_keyboard_focusable"), "YT: Elements have is_keyboard_focusable"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains(out, "help_text"), "YT: Elements have help_text"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "help_text", "Top navigation bar"), "YT: Top bar has help_text"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "help_text", "Navigation sidebar"), "YT: Sidebar has help_text"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "help_text", "Saved videos to watch later"), "YT: Watch Later has help_text"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "help_text", "Videos you liked"), "YT: Liked Videos has help_text"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "help_text", "Dislike video"), "YT: Dislike has help_text"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "help_text", "Share video"), "YT: Share has help_text"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "help_text", "Create/upload video"), "YT: Create has help_text"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "help_text", "Your profile/library"), "YT: You has help_text"); }
    { auto out = get_sim_output("uia-tree sim_youtube"); check_pass(json_contains_value(out, "help_text", "Bottom nav bar"), "YT: Bottom nav has help_text"); }

    print_summary("YOUTUBE TEST SUMMARY");
    return g_tests_failed > 0 ? 1 : 0;
}
