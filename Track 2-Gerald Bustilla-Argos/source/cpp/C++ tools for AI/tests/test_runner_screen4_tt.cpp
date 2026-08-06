// test_runner_screen4_tt.cpp - TikTok 100 tests
#include "test_screen4_common.h"

int main() {
    std::cout << "=== PLATFORM 5: TikTok - 100 tests ===" << std::endl;

    // UIA Tree Structure (20 tests)
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains(out, "success"), "TT: UIA-tree returns success"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "TikTok"), "TT: Root element is 'TikTok'"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains(out, "total_elements"), "TT: Has total_elements field"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Feed tabs"), "TT: Has Feed tabs pane"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Bottom navigation"), "TT: Has Bottom navigation pane"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(count_depth(out, 0) == 1, "TT: Has 1 root at depth 0"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(count_type(out, "button") >= 10, "TT: Has >=10 button elements"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(count_type(out, "hyperlink") >= 2, "TT: Has >=2 hyperlink elements"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(count_type(out, "image") >= 1, "TT: Has >=1 image element (video)"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(count_type(out, "text") >= 3, "TT: Has >=3 text elements"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains(out, "element_id"), "TT: Elements have element_id"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains(out, "parent_id"), "TT: Elements have parent_id"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains(out, "bounds"), "TT: Elements have bounds"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains(out, "max_depth"), "TT: Has max_depth field"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains(out, "root_element_id"), "TT: Has root_element_id"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains(out, "error"), "TT: Has error field"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "control_type", "window"), "TT: Has window control type"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(count_type(out, "pane") >= 3, "TT: Has >=3 pane elements"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains(out, "depth"), "TT: Elements have depth field"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(count_depth(out, 1) >= 2, "TT: Has >=2 elements at depth 1"); }

    // Platform-Specific Elements (20 tests)
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "For You"), "TT: Has 'For You' feed tab"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Following"), "TT: Has 'Following' feed tab"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Bookmark"), "TT: Has Bookmark button"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Follow"), "TT: Has Follow button"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Like"), "TT: Has Like button"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Comment"), "TT: Has Comment button"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Share"), "TT: Has Share button"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Create"), "TT: Has Create (+) button"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Shop"), "TT: Has Shop nav button"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Inbox"), "TT: Has Inbox nav button"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Discover"), "TT: Has Discover nav button"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Profile"), "TT: Has Profile nav button"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "@codejokes"), "TT: Has @codejokes author"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Original sound - @codejokes"), "TT: Has sound info text"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Home"), "TT: Has Home nav button"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "name", "Search"), "TT: Has Search button"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "help_text", "Algorithmic feed (default)"), "TT: For You has help_text"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "help_text", "Save/bookmark video"), "TT: Bookmark has help_text"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "help_text", "Follow creator"), "TT: Follow has help_text"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "help_text", "Create video (+)"), "TT: Create has help_text"); }

    // Interactive Elements (15 tests)
    { auto out = get_sim_output("interactive-elements sim_tiktok"); check_pass(json_contains(out, "total_elements"), "TT: Interactive-elements returns total_elements"); }
    { auto out = get_sim_output("interactive-elements sim_tiktok"); check_pass(json_contains(out, "total_elements"), "TT: Interactive-elements has total_elements"); }
    { auto out = get_sim_output("interactive-elements sim_tiktok"); check_pass(json_contains_value(out, "name", "Like"), "TT: Interactive-elements has Like"); }
    { auto out = get_sim_output("interactive-elements sim_tiktok"); check_pass(json_contains_value(out, "name", "Comment"), "TT: Interactive-elements has Comment"); }
    { auto out = get_sim_output("interactive-elements sim_tiktok"); check_pass(json_contains_value(out, "name", "Bookmark"), "TT: Interactive-elements has Bookmark"); }
    { auto out = get_sim_output("interactive-elements sim_tiktok"); check_pass(json_contains_value(out, "name", "Share"), "TT: Interactive-elements has Share"); }
    { auto out = get_sim_output("interactive-elements sim_tiktok"); check_pass(json_contains_value(out, "name", "Follow"), "TT: Interactive-elements has Follow"); }
    { auto out = get_sim_output("interactive-elements sim_tiktok"); check_pass(json_contains_value(out, "name", "Create"), "TT: Interactive-elements has Create"); }
    { auto out = get_sim_output("interactive-elements sim_tiktok"); check_pass(json_contains_value(out, "name", "Shop"), "TT: Interactive-elements has Shop"); }
    { auto out = get_sim_output("interactive-elements sim_tiktok"); check_pass(json_contains_value(out, "name", "Home"), "TT: Interactive-elements has Home"); }
    { auto out = get_sim_output("interactive-elements sim_tiktok"); check_pass(json_contains_value(out, "name", "Discover"), "TT: Interactive-elements has Discover"); }
    { auto out = get_sim_output("interactive-elements sim_tiktok"); check_pass(json_contains_value(out, "name", "Inbox"), "TT: Interactive-elements has Inbox"); }
    { auto out = get_sim_output("interactive-elements sim_tiktok"); check_pass(json_contains_value(out, "name", "Profile"), "TT: Interactive-elements has Profile"); }
    { auto out = get_sim_output("interactive-elements sim_tiktok"); check_pass(json_contains_value(out, "action_type", "click"), "TT: Interactive-elements has click action"); }
    { auto out = get_sim_output("interactive-elements sim_tiktok"); check_pass(get_total(out, "total_elements") >= 12, "TT: Has >=12 interactive elements"); }

    // Content & OCR (15 tests)
    { auto out = get_sim_output("get-content sim_tiktok"); check_pass(json_contains(out, "total_blocks"), "TT: Get-content returns total_blocks"); }
    { auto out = get_sim_output("get-content sim_tiktok"); check_pass(json_contains_value(out, "source", "TikTok"), "TT: Get-content returns TikTok source"); }
    { auto out = get_sim_output("get-content sim_tiktok"); check_pass(json_contains(out, "blocks"), "TT: Get-content has blocks array"); }
    { auto out = get_sim_output("get-content sim_tiktok"); check_pass(json_contains_value(out, "type", "video"), "TT: Get-content has video-type blocks"); }
    { auto out = get_sim_output("get-content sim_tiktok"); check_pass(out.find("codejokes") != std::string::npos, "TT: Get-content contains codejokes"); }
    { auto out = get_sim_output("ocr-window sim_tiktok"); check_pass(json_contains(out, "success"), "TT: OCR-window returns success"); }
    { auto out = get_sim_output("ocr-window sim_tiktok"); check_pass(out.find("compiles") != std::string::npos, "TT: OCR-window contains compiles text"); }
    { auto out = get_sim_output("ocr-window sim_tiktok"); check_pass(out.find("programming") != std::string::npos, "TT: OCR-window contains programming hashtag"); }
    { auto out = get_sim_output("ocr-window sim_tiktok"); check_pass(json_contains(out, "regions"), "TT: OCR-window has regions array"); }
    { auto out = get_sim_output("search-content programming sim_tiktok"); check_pass(json_contains(out, "total_results"), "TT: Search-content 'programming' returns total_results"); }
    { auto out = get_sim_output("search-content programming sim_tiktok"); check_pass(json_contains_value(out, "source", "TikTok"), "TT: Search-content returns TikTok source"); }
    { auto out = get_sim_output("search-content codejokes sim_tiktok"); check_pass(json_contains(out, "total_results"), "TT: Search-content 'codejokes' has total_results"); }
    { auto out = get_sim_output("search-content nonexistent12345 sim_tiktok"); check_pass(json_contains(out, "total_results"), "TT: Search-content nonexistent returns total_results"); }
    { auto out = get_sim_output("get-content sim_tiktok"); check_pass(json_contains(out, "total_blocks"), "TT: Get-content has total_blocks"); }
    { auto out = get_sim_output("search-content compiles sim_tiktok"); check_pass(json_contains(out, "total_results"), "TT: Search-content 'compiles' has total_results"); }

    // Find Elements (15 tests)
    { auto out = get_sim_output("find-by-type button sim_tiktok"); check_pass(json_contains(out, "total_found"), "TT: Find-by-type button returns total_found"); }
    { auto out = get_sim_output("find-by-type button sim_tiktok"); check_pass(json_contains_value(out, "name", "Like"), "TT: Find-by-type button finds Like"); }
    { auto out = get_sim_output("find-by-type button sim_tiktok"); check_pass(json_contains_value(out, "name", "Bookmark"), "TT: Find-by-type button finds Bookmark"); }
    { auto out = get_sim_output("find-by-type button sim_tiktok"); check_pass(json_contains_value(out, "name", "Follow"), "TT: Find-by-type button finds Follow"); }
    { auto out = get_sim_output("find-by-type button sim_tiktok"); check_pass(json_contains_value(out, "name", "Create"), "TT: Find-by-type button finds Create"); }
    { auto out = get_sim_output("find-by-type hyperlink sim_tiktok"); check_pass(json_contains_value(out, "name", "For You"), "TT: Find-by-type hyperlink finds For You"); }
    { auto out = get_sim_output("find-by-type hyperlink sim_tiktok"); check_pass(json_contains_value(out, "name", "Following"), "TT: Find-by-type hyperlink finds Following"); }
    { auto out = get_sim_output("find-by-name Bookmark sim_tiktok"); check_pass(json_contains_value(out, "name", "Bookmark"), "TT: Find-by-name Bookmark finds Bookmark"); }
    { auto out = get_sim_output("find-by-name Follow sim_tiktok"); check_pass(json_contains_value(out, "name", "Follow"), "TT: Find-by-name Follow finds Follow"); }
    { auto out = get_sim_output("find-by-name Shop sim_tiktok"); check_pass(json_contains_value(out, "name", "Shop"), "TT: Find-by-name Shop finds Shop"); }
    { auto out = get_sim_output("find-by-name Discover sim_tiktok"); check_pass(json_contains_value(out, "name", "Discover"), "TT: Find-by-name Discover finds Discover"); }
    { auto out = get_sim_output("find-by-name Inbox sim_tiktok"); check_pass(json_contains_value(out, "name", "Inbox"), "TT: Find-by-name Inbox finds Inbox"); }
    { auto out = get_sim_output("find-by-type image sim_tiktok"); check_pass(json_contains_value(out, "name", "Video content"), "TT: Find-by-type image finds video"); }
    { auto out = get_sim_output("find-by-type text sim_tiktok"); check_pass(json_contains(out, "total_found"), "TT: Find-by-type text has total_found"); }
    { auto out = get_sim_output("find-by-name codejokes sim_tiktok"); check_pass(json_contains_value(out, "name", "@codejokes"), "TT: Find-by-name codejokes finds @codejokes"); }

    // Element State & Patterns (15 tests)
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_bool(out, "is_enabled", true), "TT: Elements have is_enabled true"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_bool(out, "is_visible", true), "TT: Elements have is_visible true"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains(out, "has_invoke_pattern"), "TT: Elements have has_invoke_pattern"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains(out, "has_value_pattern"), "TT: Elements have has_value_pattern"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains(out, "is_keyboard_focusable"), "TT: Elements have is_keyboard_focusable"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains(out, "help_text"), "TT: Elements have help_text"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "help_text", "For You / Following tabs"), "TT: Feed tabs has help_text"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "help_text", "Following feed"), "TT: Following has help_text"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "help_text", "Like video (heart)"), "TT: Like has help_text"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "help_text", "Comment on video"), "TT: Comment has help_text"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "help_text", "Share video"), "TT: Share has help_text"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "help_text", "Sound name"), "TT: Sound info has help_text"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "help_text", "Video caption"), "TT: Caption has help_text"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "help_text", "Bottom nav bar"), "TT: Bottom nav has help_text"); }
    { auto out = get_sim_output("uia-tree sim_tiktok"); check_pass(json_contains_value(out, "help_text", "Shop products"), "TT: Shop has help_text"); }

    print_summary("TIKTOK TEST SUMMARY");
    return g_tests_failed > 0 ? 1 : 0;
}
