// test_runner_screen4_ig.cpp - Instagram 100 tests
#include "test_screen4_common.h"

int main() {
    std::cout << "=== PLATFORM 2: Instagram - 100 tests ===" << std::endl;

    // UIA Tree Structure (20 tests)
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains(out, "success"), "IG: UIA-tree returns success"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Instagram"), "IG: Root element is 'Instagram'"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "control_type", "window"), "IG: Has window control type"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains(out, "total_elements"), "IG: Has total_elements field"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Top bar"), "IG: Has Top bar pane"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Stories tray"), "IG: Has Stories tray pane"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Bottom navigation"), "IG: Has Bottom navigation pane"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Direct Messages"), "IG: Has Direct Messages button"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(count_depth(out, 0) == 1, "IG: Has 1 root at depth 0"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(count_depth(out, 1) >= 3, "IG: Has >=3 elements at depth 1"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(count_type(out, "button") >= 10, "IG: Has >=10 button elements"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(count_type(out, "image") >= 3, "IG: Has >=3 image elements"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(count_type(out, "text") >= 5, "IG: Has >=5 text elements"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(count_type(out, "pane") >= 5, "IG: Has >=5 pane elements"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains(out, "element_id"), "IG: Elements have element_id"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains(out, "parent_id"), "IG: Elements have parent_id"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains(out, "bounds"), "IG: Elements have bounds"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains(out, "max_depth"), "IG: Has max_depth field"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains(out, "root_element_id"), "IG: Has root_element_id"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains(out, "error"), "IG: Has error field"); }

    // Platform-Specific Elements (20 tests)
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Story by @naturelover"), "IG: Has Story by @naturelover"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Story by @chefathome"), "IG: Has Story by @chefathome"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Story by @travelbug"), "IG: Has Story by @travelbug"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Save"), "IG: Has Save button"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Like"), "IG: Has Like button"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Comment"), "IG: Has Comment button"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Share"), "IG: Has Share button"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Home"), "IG: Has Home nav button"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Search"), "IG: Has Search nav button"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Reels"), "IG: Has Reels nav button"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Shop"), "IG: Has Shop nav button"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Profile"), "IG: Has Profile nav button"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "@naturelover"), "IG: Has @naturelover author"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "@chefathome"), "IG: Has @chefathome author"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Sponsored: GlowUp skincare"), "IG: Has sponsored content pane"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "Shop now"), "IG: Has Shop now ad link"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "name", "1,234 likes"), "IG: Has like count text"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "help_text", "Stories from friends and creators"), "IG: Stories tray has help_text"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "help_text", "Bottom nav bar"), "IG: Bottom nav has help_text"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "help_text", "Save/bookmark post"), "IG: Save button has help_text"); }

    // Interactive Elements (15 tests)
    { auto out = get_sim_output("interactive-elements sim_instagram"); check_pass(json_contains(out, "total_elements"), "IG: Interactive-elements returns total_elements"); }
    { auto out = get_sim_output("interactive-elements sim_instagram"); check_pass(json_contains(out, "total_elements"), "IG: Interactive-elements has total_elements"); }
    { auto out = get_sim_output("interactive-elements sim_instagram"); check_pass(json_contains_value(out, "name", "Like"), "IG: Interactive-elements has Like"); }
    { auto out = get_sim_output("interactive-elements sim_instagram"); check_pass(json_contains_value(out, "name", "Comment"), "IG: Interactive-elements has Comment"); }
    { auto out = get_sim_output("interactive-elements sim_instagram"); check_pass(json_contains_value(out, "name", "Share"), "IG: Interactive-elements has Share"); }
    { auto out = get_sim_output("interactive-elements sim_instagram"); check_pass(json_contains_value(out, "name", "Save"), "IG: Interactive-elements has Save"); }
    { auto out = get_sim_output("interactive-elements sim_instagram"); check_pass(json_contains_value(out, "name", "Home"), "IG: Interactive-elements has Home"); }
    { auto out = get_sim_output("interactive-elements sim_instagram"); check_pass(json_contains_value(out, "name", "Reels"), "IG: Interactive-elements has Reels"); }
    { auto out = get_sim_output("interactive-elements sim_instagram"); check_pass(json_contains_value(out, "name", "Shop"), "IG: Interactive-elements has Shop"); }
    { auto out = get_sim_output("interactive-elements sim_instagram"); check_pass(json_contains_value(out, "name", "Profile"), "IG: Interactive-elements has Profile"); }
    { auto out = get_sim_output("interactive-elements sim_instagram"); check_pass(json_contains_value(out, "name", "Direct Messages"), "IG: Interactive-elements has DM button"); }
    { auto out = get_sim_output("interactive-elements sim_instagram"); check_pass(json_contains_value(out, "name", "Shop now"), "IG: Interactive-elements has Shop now link"); }
    { auto out = get_sim_output("interactive-elements sim_instagram"); check_pass(json_contains_value(out, "action_type", "click"), "IG: Interactive-elements has click action"); }
    { auto out = get_sim_output("interactive-elements sim_instagram"); check_pass(json_contains(out, "element_id"), "IG: Interactive-elements has element_id"); }
    { auto out = get_sim_output("interactive-elements sim_instagram"); check_pass(get_total(out, "total_elements") >= 15, "IG: Has >=15 interactive elements"); }

    // Content & OCR (15 tests)
    { auto out = get_sim_output("get-content sim_instagram"); check_pass(json_contains(out, "total_blocks"), "IG: Get-content returns total_blocks"); }
    { auto out = get_sim_output("get-content sim_instagram"); check_pass(json_contains_value(out, "source", "Instagram"), "IG: Get-content returns Instagram source"); }
    { auto out = get_sim_output("get-content sim_instagram"); check_pass(json_contains(out, "blocks"), "IG: Get-content has blocks array"); }
    { auto out = get_sim_output("get-content sim_instagram"); check_pass(json_contains_value(out, "type", "post"), "IG: Get-content has post-type blocks"); }
    { auto out = get_sim_output("get-content sim_instagram"); check_pass(out.find("naturelover") != std::string::npos, "IG: Get-content contains naturelover"); }
    { auto out = get_sim_output("ocr-window sim_instagram"); check_pass(json_contains(out, "success"), "IG: OCR-window returns success"); }
    { auto out = get_sim_output("ocr-window sim_instagram"); check_pass(out.find("Sunset hike") != std::string::npos, "IG: OCR-window contains 'Sunset hike'"); }
    { auto out = get_sim_output("ocr-window sim_instagram"); check_pass(out.find("Creamy garlic pasta") != std::string::npos, "IG: OCR-window contains recipe text"); }
    { auto out = get_sim_output("ocr-window sim_instagram"); check_pass(json_contains(out, "regions"), "IG: OCR-window has regions array"); }
    { auto out = get_sim_output("search-content sunset sim_instagram"); check_pass(json_contains(out, "total_results"), "IG: Search-content 'sunset' returns total_results"); }
    { auto out = get_sim_output("search-content sunset sim_instagram"); check_pass(json_contains_value(out, "source", "Instagram"), "IG: Search-content returns Instagram source"); }
    { auto out = get_sim_output("search-content hiking sim_instagram"); check_pass(out.find("hiking") != std::string::npos || json_contains_number(out, "total_results", 0), "IG: Search-content finds hiking or returns 0"); }
    { auto out = get_sim_output("search-content nonexistent12345 sim_instagram"); check_pass(json_contains(out, "total_results"), "IG: Search-content nonexistent returns total_results"); }
    { auto out = get_sim_output("search-content sponsored sim_instagram"); check_pass(json_contains(out, "total_results"), "IG: Search-content 'sponsored' has total_results"); }
    { auto out = get_sim_output("get-content sim_instagram"); check_pass(json_contains(out, "total_blocks"), "IG: Get-content has total_blocks field"); }

    // Find Elements (15 tests)
    { auto out = get_sim_output("find-by-type button sim_instagram"); check_pass(json_contains(out, "total_found"), "IG: Find-by-type button returns total_found"); }
    { auto out = get_sim_output("find-by-type button sim_instagram"); check_pass(json_contains_value(out, "name", "Like"), "IG: Find-by-type button finds Like"); }
    { auto out = get_sim_output("find-by-type button sim_instagram"); check_pass(json_contains_value(out, "name", "Save"), "IG: Find-by-type button finds Save"); }
    { auto out = get_sim_output("find-by-type button sim_instagram"); check_pass(json_contains_value(out, "name", "Reels"), "IG: Find-by-type button finds Reels"); }
    { auto out = get_sim_output("find-by-type button sim_instagram"); check_pass(json_contains_value(out, "name", "Shop"), "IG: Find-by-type button finds Shop"); }
    { auto out = get_sim_output("find-by-type image sim_instagram"); check_pass(json_contains_value(out, "name", "Story by @naturelover"), "IG: Find-by-type image finds Story"); }
    { auto out = get_sim_output("find-by-type image sim_instagram"); check_pass(json_contains_value(out, "name", "Sunset hike photo"), "IG: Find-by-type image finds photo"); }
    { auto out = get_sim_output("find-by-name Save sim_instagram"); check_pass(json_contains_value(out, "name", "Save"), "IG: Find-by-name Save finds Save"); }
    { auto out = get_sim_output("find-by-name Reels sim_instagram"); check_pass(json_contains_value(out, "name", "Reels"), "IG: Find-by-name Reels finds Reels"); }
    { auto out = get_sim_output("find-by-name Stories sim_instagram"); check_pass(json_contains_value(out, "name", "Stories tray"), "IG: Find-by-name Stories finds Stories tray"); }
    { auto out = get_sim_output("find-by-name Direct sim_instagram"); check_pass(json_contains_value(out, "name", "Direct Messages"), "IG: Find-by-name Direct finds DM"); }
    { auto out = get_sim_output("find-by-name sponsored sim_instagram"); check_pass(json_contains_value(out, "name", "Sponsored: GlowUp skincare"), "IG: Find-by-name sponsored finds ad"); }
    { auto out = get_sim_output("find-by-type pane sim_instagram"); check_pass(json_contains(out, "total_found"), "IG: Find-by-type pane has total_found"); }
    { auto out = get_sim_output("find-by-type text sim_instagram"); check_pass(json_contains(out, "total_found"), "IG: Find-by-type text has total_found"); }
    { auto out = get_sim_output("find-by-type hyperlink sim_instagram"); check_pass(json_contains(out, "total_found"), "IG: Find-by-type hyperlink has total_found"); }

    // Element State & Patterns (15 tests)
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_bool(out, "is_enabled", true), "IG: Elements have is_enabled true"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_bool(out, "is_visible", true), "IG: Elements have is_visible true"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains(out, "has_invoke_pattern"), "IG: Elements have has_invoke_pattern"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains(out, "has_value_pattern"), "IG: Elements have has_value_pattern"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains(out, "is_keyboard_focusable"), "IG: Elements have is_keyboard_focusable"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains(out, "help_text"), "IG: Elements have help_text"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "help_text", "Top navigation bar"), "IG: Top bar has help_text"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "help_text", "Open DMs"), "IG: DM button has help_text"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "help_text", "Story avatar with gradient ring"), "IG: Story has help_text"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "help_text", "Like post"), "IG: Like has help_text"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "help_text", "Save/bookmark post"), "IG: Save has help_text"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "help_text", "Reels (short videos)"), "IG: Reels has help_text"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "help_text", "Shop marketplace"), "IG: Shop has help_text"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "help_text", "Your profile"), "IG: Profile has help_text"); }
    { auto out = get_sim_output("uia-tree sim_instagram"); check_pass(json_contains_value(out, "help_text", "Sponsored content"), "IG: Sponsored pane has help_text"); }

    print_summary("INSTAGRAM TEST SUMMARY");
    return g_tests_failed > 0 ? 1 : 0;
}
