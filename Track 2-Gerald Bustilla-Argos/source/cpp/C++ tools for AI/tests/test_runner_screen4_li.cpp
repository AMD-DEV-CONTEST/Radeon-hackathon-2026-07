// test_runner_screen4_li.cpp - LinkedIn 100 tests
#include "test_screen4_common.h"

int main() {
    std::cout << "=== PLATFORM 7: LinkedIn - 100 tests ===" << std::endl;

    // UIA Tree Structure (20 tests)
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains(out, "success"), "LI: UIA-tree returns success"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "LinkedIn - Feed"), "LI: Root element is 'LinkedIn - Feed'"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains(out, "total_elements"), "LI: Has total_elements field"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Top bar"), "LI: Has Top bar pane"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Bottom navigation"), "LI: Has Bottom navigation pane"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(count_depth(out, 0) == 1, "LI: Has 1 root at depth 0"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(count_type(out, "button") >= 10, "LI: Has >=10 button elements"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(count_type(out, "edit") >= 1, "LI: Has >=1 edit element (search)"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(count_type(out, "text") >= 5, "LI: Has >=5 text elements"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains(out, "element_id"), "LI: Elements have element_id"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains(out, "parent_id"), "LI: Elements have parent_id"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains(out, "bounds"), "LI: Elements have bounds"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains(out, "max_depth"), "LI: Has max_depth field"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains(out, "root_element_id"), "LI: Has root_element_id"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains(out, "error"), "LI: Has error field"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "control_type", "window"), "LI: Has window control type"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(count_type(out, "pane") >= 3, "LI: Has >=3 pane elements"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains(out, "depth"), "LI: Elements have depth field"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(count_depth(out, 1) >= 2, "LI: Has >=2 elements at depth 1"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(count_depth(out, 2) >= 10, "LI: Has >=10 elements at depth 2"); }

    // Platform-Specific Elements (20 tests)
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Profile avatar"), "LI: Has Profile avatar button"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Create post"), "LI: Has Create post button"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Messaging"), "LI: Has Messaging button"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Notifications"), "LI: Has Notifications button"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Search"), "LI: Has Search edit"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Jane Smith"), "LI: Has Jane Smith post author"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "John Doe"), "LI: Has John Doe post author"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Senior Software Engineer at Google"), "LI: Has author headline"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Tech Lead at Microsoft | AI Research"), "LI: Has second author headline"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Like"), "LI: Has Like button"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Comment"), "LI: Has Comment button"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Repost"), "LI: Has Repost button"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Send"), "LI: Has Send button"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Home"), "LI: Has Home nav button"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Video"), "LI: Has Video nav button"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "My Network"), "LI: Has My Network nav button"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "name", "Jobs"), "LI: Has Jobs nav button"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "help_text", "Open profile sidebar drawer"), "LI: Profile avatar has help_text"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "help_text", "Compose new post"), "LI: Create post has help_text"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "help_text", "Repost to your network"), "LI: Repost has help_text"); }

    // Interactive Elements (15 tests)
    { auto out = get_sim_output("interactive-elements sim_linkedin"); check_pass(json_contains(out, "total_elements"), "LI: Interactive-elements returns total_elements"); }
    { auto out = get_sim_output("interactive-elements sim_linkedin"); check_pass(json_contains(out, "total_elements"), "LI: Interactive-elements has total_elements"); }
    { auto out = get_sim_output("interactive-elements sim_linkedin"); check_pass(json_contains_value(out, "name", "Like"), "LI: Interactive-elements has Like"); }
    { auto out = get_sim_output("interactive-elements sim_linkedin"); check_pass(json_contains_value(out, "name", "Comment"), "LI: Interactive-elements has Comment"); }
    { auto out = get_sim_output("interactive-elements sim_linkedin"); check_pass(json_contains_value(out, "name", "Repost"), "LI: Interactive-elements has Repost"); }
    { auto out = get_sim_output("interactive-elements sim_linkedin"); check_pass(json_contains_value(out, "name", "Send"), "LI: Interactive-elements has Send"); }
    { auto out = get_sim_output("interactive-elements sim_linkedin"); check_pass(json_contains_value(out, "name", "Create post"), "LI: Interactive-elements has Create post"); }
    { auto out = get_sim_output("interactive-elements sim_linkedin"); check_pass(json_contains_value(out, "name", "Messaging"), "LI: Interactive-elements has Messaging"); }
    { auto out = get_sim_output("interactive-elements sim_linkedin"); check_pass(json_contains_value(out, "name", "Home"), "LI: Interactive-elements has Home"); }
    { auto out = get_sim_output("interactive-elements sim_linkedin"); check_pass(json_contains_value(out, "name", "Jobs"), "LI: Interactive-elements has Jobs"); }
    { auto out = get_sim_output("interactive-elements sim_linkedin"); check_pass(json_contains_value(out, "name", "My Network"), "LI: Interactive-elements has My Network"); }
    { auto out = get_sim_output("interactive-elements sim_linkedin"); check_pass(json_contains_value(out, "name", "Profile avatar"), "LI: Interactive-elements has Profile avatar"); }
    { auto out = get_sim_output("interactive-elements sim_linkedin"); check_pass(json_contains_value(out, "action_type", "click"), "LI: Interactive-elements has click action"); }
    { auto out = get_sim_output("interactive-elements sim_linkedin"); check_pass(json_contains(out, "element_id"), "LI: Interactive-elements has element_id"); }
    { auto out = get_sim_output("interactive-elements sim_linkedin"); check_pass(get_total(out, "total_elements") >= 15, "LI: Has >=15 interactive elements"); }

    // Content & OCR (15 tests)
    { auto out = get_sim_output("get-content sim_linkedin"); check_pass(json_contains(out, "total_blocks"), "LI: Get-content returns total_blocks"); }
    { auto out = get_sim_output("get-content sim_linkedin"); check_pass(json_contains_value(out, "source", "LinkedIn"), "LI: Get-content returns LinkedIn source"); }
    { auto out = get_sim_output("get-content sim_linkedin"); check_pass(json_contains(out, "blocks"), "LI: Get-content has blocks array"); }
    { auto out = get_sim_output("get-content sim_linkedin"); check_pass(json_contains_value(out, "type", "post"), "LI: Get-content has post-type blocks"); }
    { auto out = get_sim_output("get-content sim_linkedin"); check_pass(out.find("Jane Smith") != std::string::npos, "LI: Get-content contains Jane Smith"); }
    { auto out = get_sim_output("ocr-window sim_linkedin"); check_pass(json_contains(out, "success"), "LI: OCR-window returns success"); }
    { auto out = get_sim_output("ocr-window sim_linkedin"); check_pass(out.find("Excited to announce") != std::string::npos, "LI: OCR-window contains announcement text"); }
    { auto out = get_sim_output("ocr-window sim_linkedin"); check_pass(out.find("published") != std::string::npos, "LI: OCR-window contains published text"); }
    { auto out = get_sim_output("ocr-window sim_linkedin"); check_pass(json_contains(out, "regions"), "LI: OCR-window has regions array"); }
    { auto out = get_sim_output("search-content Google sim_linkedin"); check_pass(json_contains(out, "total_results"), "LI: Search-content 'Google' returns total_results"); }
    { auto out = get_sim_output("search-content Google sim_linkedin"); check_pass(json_contains_value(out, "source", "LinkedIn"), "LI: Search-content returns LinkedIn source"); }
    { auto out = get_sim_output("search-content Microsoft sim_linkedin"); check_pass(json_contains(out, "total_results"), "LI: Search-content 'Microsoft' has total_results"); }
    { auto out = get_sim_output("search-content nonexistent12345 sim_linkedin"); check_pass(json_contains(out, "total_results"), "LI: Search-content nonexistent returns total_results"); }
    { auto out = get_sim_output("get-content sim_linkedin"); check_pass(json_contains(out, "total_blocks"), "LI: Get-content has total_blocks"); }
    { auto out = get_sim_output("search-content Software Engineer sim_linkedin"); check_pass(json_contains(out, "total_results"), "LI: Search-content 'Software Engineer' has total_results"); }

    // Find Elements (15 tests)
    { auto out = get_sim_output("find-by-type button sim_linkedin"); check_pass(json_contains(out, "total_found"), "LI: Find-by-type button returns total_found"); }
    { auto out = get_sim_output("find-by-type button sim_linkedin"); check_pass(json_contains_value(out, "name", "Like"), "LI: Find-by-type button finds Like"); }
    { auto out = get_sim_output("find-by-type button sim_linkedin"); check_pass(json_contains_value(out, "name", "Repost"), "LI: Find-by-type button finds Repost"); }
    { auto out = get_sim_output("find-by-type button sim_linkedin"); check_pass(json_contains_value(out, "name", "Jobs"), "LI: Find-by-type button finds Jobs"); }
    { auto out = get_sim_output("find-by-type button sim_linkedin"); check_pass(json_contains_value(out, "name", "Create post"), "LI: Find-by-type button finds Create post"); }
    { auto out = get_sim_output("find-by-type edit sim_linkedin"); check_pass(json_contains_value(out, "name", "Search"), "LI: Find-by-type edit finds Search"); }
    { auto out = get_sim_output("find-by-name Repost sim_linkedin"); check_pass(json_contains_value(out, "name", "Repost"), "LI: Find-by-name Repost finds Repost"); }
    { auto out = get_sim_output("find-by-name Jobs sim_linkedin"); check_pass(json_contains_value(out, "name", "Jobs"), "LI: Find-by-name Jobs finds Jobs"); }
    { auto out = get_sim_output("find-by-name Network sim_linkedin"); check_pass(json_contains_value(out, "name", "My Network"), "LI: Find-by-name Network finds My Network"); }
    { auto out = get_sim_output("find-by-name Jane sim_linkedin"); check_pass(json_contains_value(out, "name", "Jane Smith"), "LI: Find-by-name Jane finds Jane Smith"); }
    { auto out = get_sim_output("find-by-name John sim_linkedin"); check_pass(json_contains_value(out, "name", "John Doe"), "LI: Find-by-name John finds John Doe"); }
    { auto out = get_sim_output("find-by-name Video sim_linkedin"); check_pass(json_contains_value(out, "name", "Video"), "LI: Find-by-name Video finds Video"); }
    { auto out = get_sim_output("find-by-type pane sim_linkedin"); check_pass(json_contains(out, "total_found"), "LI: Find-by-type pane has total_found"); }
    { auto out = get_sim_output("find-by-type text sim_linkedin"); check_pass(json_contains(out, "total_found"), "LI: Find-by-type text has total_found"); }
    { auto out = get_sim_output("find-by-name Create sim_linkedin"); check_pass(json_contains_value(out, "name", "Create post"), "LI: Find-by-name Create finds Create post"); }

    // Element State & Patterns (15 tests)
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_bool(out, "is_enabled", true), "LI: Elements have is_enabled true"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_bool(out, "is_visible", true), "LI: Elements have is_visible true"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains(out, "has_invoke_pattern"), "LI: Elements have has_invoke_pattern"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains(out, "has_value_pattern"), "LI: Elements have has_value_pattern"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains(out, "is_keyboard_focusable"), "LI: Elements have is_keyboard_focusable"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains(out, "help_text"), "LI: Elements have help_text"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "help_text", "Top navigation bar"), "LI: Top bar has help_text"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "help_text", "Search LinkedIn"), "LI: Search has help_text"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "help_text", "Open messages (3 unread)"), "LI: Messaging has help_text"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "help_text", "View notifications"), "LI: Notifications has help_text"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "help_text", "Author name"), "LI: Author name has help_text"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "help_text", "Author headline/title"), "LI: Author headline has help_text"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "help_text", "Like post"), "LI: Like has help_text"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "help_text", "Comment on post"), "LI: Comment has help_text"); }
    { auto out = get_sim_output("uia-tree sim_linkedin"); check_pass(json_contains_value(out, "help_text", "Send as DM"), "LI: Send has help_text"); }

    print_summary("LINKEDIN TEST SUMMARY");
    return g_tests_failed > 0 ? 1 : 0;
}
