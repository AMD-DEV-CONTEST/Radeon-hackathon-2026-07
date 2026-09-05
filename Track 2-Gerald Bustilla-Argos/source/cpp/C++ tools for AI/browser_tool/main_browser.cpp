#include "browser_tool.h"
#include <iostream>
#include <string>
#include <vector>
#include <sstream>

using namespace browsertool;

static void print_usage() {
    std::cerr << "Usage: browsertool [options] <command> [args]\n"
              << "Options:\n"
              << "  --sim              Enable simulation mode\n"
              << "  --type <type>      Filter by element type\n"
              << "  --window <id>      Filter by window/tab\n"
              << "  --top-k <n>        Limit results to n\n"
              << "\nCommands:\n"
              << "  Navigation:\n"
              << "    navigate <url>           Navigate to URL\n"
              << "    back                     Go back in history\n"
              << "    forward                  Go forward in history\n"
              << "    refresh                  Refresh current page\n"
              << "    stop                     Stop loading\n"
              << "    url                      Get current URL\n"
              << "    title                    Get current page title\n"
              << "\n  Tabs:\n"
              << "    new-tab [url]            Open new tab\n"
              << "    close-tab <id>           Close tab\n"
              << "    switch-tab <id>          Switch to tab\n"
              << "    list-tabs                List all tabs\n"
              << "\n  Content:\n"
              << "    page-info                Get page metadata\n"
              << "    content                  Get full page text content\n"
              << "    html                     Get page HTML\n"
              << "    meta-description         Get meta description\n"
              << "    meta-keywords            Get meta keywords\n"
              << "    summarize [n]            Summarize page (n sentences)\n"
              << "    section <heading>        Get section by heading\n"
              << "    headings                 List all headings\n"
              << "    paragraphs               List all paragraphs\n"
              << "    context <text> [b] [a]   Get context around text\n"
              << "    explain <query>          Explain/search content with context\n"
              << "    search <query> [n]       Search page content (max n results)\n"
              << "    search-context <q> [c]   Search with context (c chars)\n"
              << "    find-text <text>         Find first occurrence of text\n"
              << "    find-all <text>          Find all occurrences of text\n"
              << "    find-element <text>      Find element by text\n"
              << "    find-paragraph <text>    Find paragraph by text\n"
              << "    find-heading <text>      Find heading by text\n"
              << "    find-link <text>         Find link by text\n"
              << "    find-link-href <href>    Find link by href\n"
              << "    find-button <text>       Find button by text\n"
              << "\n  Elements:\n"
              << "    elements                 Get all elements on page\n"
              << "    element <id>             Get element by ID\n"
              << "    links                    Get all links\n"
              << "    buttons                  Get all buttons\n"
              << "    inputs                   Get all input elements\n"
              << "    headings                 Get all headings\n"
              << "    tables                   Get all tables\n"
              << "    nav                      Get navigation elements\n"
              << "    children <id>            Get children of element\n"
              << "    parent <id>              Get parent of element\n"
              << "    by-type <type>           Get elements by type\n"
              << "    by-tag <tag>             Get elements by tag\n"
              << "\n  Scroll:\n"
              << "    scroll-down [px]         Scroll down (default 300px)\n"
              << "    scroll-up [px]           Scroll up (default 300px)\n"
              << "    scroll-to <x> <y>        Scroll to position\n"
              << "    scroll-to-element <id>   Scroll to element\n"
              << "    scroll-top               Scroll to top\n"
              << "    scroll-bottom            Scroll to bottom\n"
              << "    scroll-pos               Get scroll position\n"
              << "\n  Screenshot:\n"
              << "    screenshot [--full]      Take screenshot\n"
              << "    screenshot-element <id>  Screenshot of element\n"
              << "    screenshot-region <x> <y> <w> <h>  Screenshot of region\n"
              << "    save-screenshot <path> [--full]  Save screenshot to file\n"
              << "\n  Interaction:\n"
              << "    click <id>               Click element\n"
              << "    click-at <x> <y>         Click at coordinates\n"
              << "    type <id> <text>         Type text into element\n"
              << "    type-active <text>       Type into active element\n"
              << "    key <key>                Press a key\n"
              << "    select <id> <value>      Select option\n"
              << "    submit <form_id>         Submit form\n"
              << "    clear <id>               Clear input\n"
              << "    focus <id>               Focus element\n"
              << "    hover <id>               Hover element\n"
              << "\n  Wait:\n"
              << "    wait-element <selector>  Wait for element\n"
              << "    wait-text <text>         Wait for text\n"
              << "    wait-nav                 Wait for navigation\n"
              << "\n  JavaScript:\n"
              << "    js <script>              Execute JavaScript\n"
              << "\n  Forms:\n"
              << "    form-fields <form_id>    Get form fields\n"
              << "\n  Tables:\n"
              << "    table-data               Get all table data\n"
              << "    table <id>               Get specific table data\n"
              << "\n  History:\n"
              << "    history                  Get browsing history\n"
              << "    clear-history            Clear history\n"
              << "\n  Cookies:\n"
              << "    cookies                  Get cookies\n"
              << "    set-cookie <name> <val>  Set cookie\n"
              << "    clear-cookies            Clear cookies\n"
              << "\n  Export:\n"
              << "    export                   Export page data as JSON\n"
              << "    save-content <path>      Save page content to file\n"
              << "\n  Browser:\n"
              << "    browser-info             Get browser info\n"
              << "    platform                 Get current platform\n"
              << "    stats                    Get statistics\n";
}

int main(int argc, char* argv[]) {
    if (argc < 2) {
        print_usage();
        return 1;
    }

    bool sim = false;
    std::string type_filter;
    std::string window_filter;
    int top_k = 50;

    // Parse flags and find command
    int cmd_idx = 1;
    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--sim") {
            sim = true;
            cmd_idx = i + 1;
        } else if (arg == "--type" && i + 1 < argc) {
            type_filter = argv[++i];
            cmd_idx = i + 1;
        } else if (arg == "--window" && i + 1 < argc) {
            window_filter = argv[++i];
            cmd_idx = i + 1;
        } else if (arg == "--top-k" && i + 1 < argc) {
            top_k = std::atoi(argv[++i]);
            cmd_idx = i + 1;
        } else if (arg[0] != '-' || arg == "--full") {
            cmd_idx = i;
            break;
        }
    }

    if (sim) {
        enable_simulation_mode();
        setup_simulation_data();
    }

    if (cmd_idx >= argc) {
        std::cerr << "Error: No command specified" << std::endl;
        print_usage();
        return 1;
    }

    std::string command = argv[cmd_idx];

    try {
        // ===== Navigation =====
        if (command == "navigate" || command == "nav") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: navigate requires <url>" << std::endl; return 1; }
            bool ok = navigate(argv[cmd_idx + 1]);
            std::cout << "{\"navigated\":" << (ok ? "true" : "false") << ",\"url\":\"" << argv[cmd_idx + 1] << "\"}" << std::endl;
        }
        else if (command == "back") {
            bool ok = go_back();
            std::cout << "{\"back\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "forward") {
            bool ok = go_forward();
            std::cout << "{\"forward\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "refresh") {
            bool ok = refresh();
            std::cout << "{\"refreshed\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "stop") {
            bool ok = stop_loading();
            std::cout << "{\"stopped\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "url") {
            std::cout << "{\"url\":\"" << get_current_url() << "\"}" << std::endl;
        }
        else if (command == "title") {
            std::cout << "{\"title\":\"" << get_current_title() << "\"}" << std::endl;
        }
        // ===== Tabs =====
        else if (command == "new-tab") {
            std::string url = (cmd_idx + 1 < argc) ? argv[cmd_idx + 1] : "";
            std::string id = new_tab(url);
            std::cout << "{\"tab_id\":\"" << id << "\"}" << std::endl;
        }
        else if (command == "close-tab") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: close-tab requires <id>" << std::endl; return 1; }
            bool ok = close_tab(argv[cmd_idx + 1]);
            std::cout << "{\"closed\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "switch-tab") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: switch-tab requires <id>" << std::endl; return 1; }
            bool ok = switch_tab(argv[cmd_idx + 1]);
            std::cout << "{\"switched\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "list-tabs") {
            std::cout << tabs_to_json(list_tabs()) << std::endl;
        }
        // ===== Content =====
        else if (command == "page-info") {
            std::cout << page_info_to_json(get_page_info()) << std::endl;
        }
        else if (command == "content") {
            std::string c = get_page_content();
            std::cout << "{\"content_length\":" << c.size() << ",\"content\":\"" << c << "\"}" << std::endl;
        }
        else if (command == "html") {
            std::string h = get_page_html();
            std::cout << "{\"html\":\"" << h << "\"}" << std::endl;
        }
        else if (command == "meta-description") {
            std::cout << "{\"description\":\"" << get_meta_description() << "\"}" << std::endl;
        }
        else if (command == "meta-keywords") {
            std::cout << "{\"keywords\":\"" << get_meta_keywords() << "\"}" << std::endl;
        }
        else if (command == "summarize") {
            int n = (cmd_idx + 1 < argc) ? std::atoi(argv[cmd_idx + 1]) : 5;
            std::cout << summarize_page(n) << std::endl;
        }
        else if (command == "section") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: section requires <heading>" << std::endl; return 1; }
            std::cout << get_section_by_heading(argv[cmd_idx + 1]) << std::endl;
        }
        else if (command == "headings") {
            auto h = get_all_headings();
            std::ostringstream ss;
            ss << "{\"total_headings\":" << h.size() << ",\"headings\":[";
            for (size_t i = 0; i < h.size(); i++) {
                if (i > 0) ss << ",";
                ss << "\"" << h[i] << "\"";
            }
            ss << "]}";
            std::cout << ss.str() << std::endl;
        }
        else if (command == "paragraphs") {
            auto p = get_all_paragraphs();
            std::ostringstream ss;
            ss << "{\"total_paragraphs\":" << p.size() << ",\"paragraphs\":[";
            for (size_t i = 0; i < p.size(); i++) {
                if (i > 0) ss << ",";
                ss << "\"" << p[i] << "\"";
            }
            ss << "]}";
            std::cout << ss.str() << std::endl;
        }
        else if (command == "context") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: context requires <text>" << std::endl; return 1; }
            int before = (cmd_idx + 2 < argc) ? std::atoi(argv[cmd_idx + 2]) : 100;
            int after = (cmd_idx + 3 < argc) ? std::atoi(argv[cmd_idx + 3]) : 100;
            std::string ctx = get_context_around_text(argv[cmd_idx + 1], before, after);
            std::cout << "{\"context\":\"" << ctx << "\"}" << std::endl;
        }
        else if (command == "explain") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: explain requires <query>" << std::endl; return 1; }
            std::cout << explain_content(argv[cmd_idx + 1]) << std::endl;
        }
        else if (command == "search") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: search requires <query>" << std::endl; return 1; }
            int max = (cmd_idx + 2 < argc && argv[cmd_idx + 2][0] != '-') ? std::atoi(argv[cmd_idx + 2]) : top_k;
            std::cout << search_results_to_json(search_content(argv[cmd_idx + 1], max)) << std::endl;
        }
        else if (command == "search-context") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: search-context requires <query>" << std::endl; return 1; }
            int ctx = (cmd_idx + 2 < argc) ? std::atoi(argv[cmd_idx + 2]) : 200;
            std::cout << search_results_to_json(search_with_context(argv[cmd_idx + 1], ctx)) << std::endl;
        }
        else if (command == "find-text") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: find-text requires <text>" << std::endl; return 1; }
            auto r = find_first_text(argv[cmd_idx + 1]);
            std::ostringstream ss;
            ss << "{\"result\":" << r.to_json() << "}";
            std::cout << ss.str() << std::endl;
        }
        else if (command == "find-all") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: find-all requires <text>" << std::endl; return 1; }
            std::cout << search_results_to_json(find_all_text(argv[cmd_idx + 1])) << std::endl;
        }
        else if (command == "find-element") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: find-element requires <text>" << std::endl; return 1; }
            std::cout << element_to_json(find_element_by_text(argv[cmd_idx + 1])) << std::endl;
        }
        else if (command == "find-paragraph") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: find-paragraph requires <text>" << std::endl; return 1; }
            std::cout << element_to_json(find_paragraph_by_text(argv[cmd_idx + 1])) << std::endl;
        }
        else if (command == "find-heading") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: find-heading requires <text>" << std::endl; return 1; }
            std::cout << element_to_json(find_heading_by_text(argv[cmd_idx + 1])) << std::endl;
        }
        else if (command == "find-link") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: find-link requires <text>" << std::endl; return 1; }
            std::cout << element_to_json(find_link_by_text(argv[cmd_idx + 1])) << std::endl;
        }
        else if (command == "find-link-href") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: find-link-href requires <href>" << std::endl; return 1; }
            std::cout << element_to_json(find_link_by_href(argv[cmd_idx + 1])) << std::endl;
        }
        else if (command == "find-button") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: find-button requires <text>" << std::endl; return 1; }
            std::cout << element_to_json(find_button_by_text(argv[cmd_idx + 1])) << std::endl;
        }
        // ===== Elements =====
        else if (command == "elements") {
            std::cout << elements_to_json(get_all_elements()) << std::endl;
        }
        else if (command == "element") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: element requires <id>" << std::endl; return 1; }
            std::cout << element_to_json(get_element_by_id(argv[cmd_idx + 1])) << std::endl;
        }
        else if (command == "links") {
            std::cout << elements_to_json(get_links()) << std::endl;
        }
        else if (command == "buttons") {
            std::cout << elements_to_json(get_buttons()) << std::endl;
        }
        else if (command == "inputs") {
            std::cout << elements_to_json(get_inputs()) << std::endl;
        }
        else if (command == "tables") {
            std::cout << elements_to_json(get_tables()) << std::endl;
        }
        else if (command == "nav") {
            std::cout << elements_to_json(get_navigation()) << std::endl;
        }
        else if (command == "children") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: children requires <id>" << std::endl; return 1; }
            std::cout << elements_to_json(get_element_children(argv[cmd_idx + 1])) << std::endl;
        }
        else if (command == "parent") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: parent requires <id>" << std::endl; return 1; }
            std::cout << element_to_json(get_element_parent(argv[cmd_idx + 1])) << std::endl;
        }
        else if (command == "by-type") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: by-type requires <type>" << std::endl; return 1; }
            std::cout << elements_to_json(get_elements_by_type(string_to_element_type(argv[cmd_idx + 1]))) << std::endl;
        }
        else if (command == "by-tag") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: by-tag requires <tag>" << std::endl; return 1; }
            std::cout << elements_to_json(get_elements_by_tag(argv[cmd_idx + 1])) << std::endl;
        }
        // ===== Scroll =====
        else if (command == "scroll-down") {
            int px = (cmd_idx + 1 < argc) ? std::atoi(argv[cmd_idx + 1]) : 300;
            bool ok = scroll_down(px);
            std::cout << "{\"scrolled\":" << (ok ? "true" : "false") << ",\"scroll_y\":" << get_scroll_y() << "}" << std::endl;
        }
        else if (command == "scroll-up") {
            int px = (cmd_idx + 1 < argc) ? std::atoi(argv[cmd_idx + 1]) : 300;
            bool ok = scroll_up(px);
            std::cout << "{\"scrolled\":" << (ok ? "true" : "false") << ",\"scroll_y\":" << get_scroll_y() << "}" << std::endl;
        }
        else if (command == "scroll-to") {
            if (cmd_idx + 2 >= argc) { std::cerr << "Error: scroll-to requires <x> <y>" << std::endl; return 1; }
            bool ok = scroll_to(std::atoi(argv[cmd_idx + 1]), std::atoi(argv[cmd_idx + 2]));
            std::cout << "{\"scrolled\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "scroll-to-element") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: scroll-to-element requires <id>" << std::endl; return 1; }
            bool ok = scroll_to_element(argv[cmd_idx + 1]);
            std::cout << "{\"scrolled\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "scroll-top") {
            bool ok = scroll_to_top();
            std::cout << "{\"scrolled\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "scroll-bottom") {
            bool ok = scroll_to_bottom();
            std::cout << "{\"scrolled\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "scroll-pos") {
            std::cout << "{\"scroll_x\":" << get_scroll_x() << ",\"scroll_y\":" << get_scroll_y()
                      << ",\"max_x\":" << get_scroll_max_x() << ",\"max_y\":" << get_scroll_max_y() << "}" << std::endl;
        }
        // ===== Screenshot =====
        else if (command == "screenshot") {
            bool full = (cmd_idx + 1 < argc && std::string(argv[cmd_idx + 1]) == "--full");
            std::cout << screenshot_to_json(take_screenshot(full)) << std::endl;
        }
        else if (command == "screenshot-element") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: screenshot-element requires <id>" << std::endl; return 1; }
            std::cout << screenshot_to_json(screenshot_element(argv[cmd_idx + 1])) << std::endl;
        }
        else if (command == "screenshot-region") {
            if (cmd_idx + 4 >= argc) { std::cerr << "Error: screenshot-region requires <x> <y> <w> <h>" << std::endl; return 1; }
            std::cout << screenshot_to_json(screenshot_region(std::atoi(argv[cmd_idx+1]), std::atoi(argv[cmd_idx+2]),
                                                              std::atoi(argv[cmd_idx+3]), std::atoi(argv[cmd_idx+4]))) << std::endl;
        }
        else if (command == "save-screenshot") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: save-screenshot requires <path>" << std::endl; return 1; }
            bool full = (cmd_idx + 2 < argc && std::string(argv[cmd_idx + 2]) == "--full");
            bool ok = save_screenshot(argv[cmd_idx + 1], full);
            std::cout << "{\"saved\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        // ===== Interaction =====
        else if (command == "click") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: click requires <id>" << std::endl; return 1; }
            bool ok = click_element(argv[cmd_idx + 1]);
            std::cout << "{\"clicked\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "click-at") {
            if (cmd_idx + 2 >= argc) { std::cerr << "Error: click-at requires <x> <y>" << std::endl; return 1; }
            bool ok = click_element_at(std::atoi(argv[cmd_idx+1]), std::atoi(argv[cmd_idx+2]));
            std::cout << "{\"clicked\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "type") {
            if (cmd_idx + 2 >= argc) { std::cerr << "Error: type requires <id> <text>" << std::endl; return 1; }
            bool ok = type_text(argv[cmd_idx + 1], argv[cmd_idx + 2]);
            std::cout << "{\"typed\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "type-active") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: type-active requires <text>" << std::endl; return 1; }
            bool ok = type_text_into_active_element(argv[cmd_idx + 1]);
            std::cout << "{\"typed\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "key") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: key requires <key>" << std::endl; return 1; }
            bool ok = press_key(argv[cmd_idx + 1]);
            std::cout << "{\"pressed\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "select") {
            if (cmd_idx + 2 >= argc) { std::cerr << "Error: select requires <id> <value>" << std::endl; return 1; }
            bool ok = select_option(argv[cmd_idx + 1], argv[cmd_idx + 2]);
            std::cout << "{\"selected\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "submit") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: submit requires <form_id>" << std::endl; return 1; }
            bool ok = submit_form(argv[cmd_idx + 1]);
            std::cout << "{\"submitted\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "clear") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: clear requires <id>" << std::endl; return 1; }
            bool ok = clear_input(argv[cmd_idx + 1]);
            std::cout << "{\"cleared\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "focus") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: focus requires <id>" << std::endl; return 1; }
            bool ok = focus_element(argv[cmd_idx + 1]);
            std::cout << "{\"focused\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "hover") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: hover requires <id>" << std::endl; return 1; }
            bool ok = hover_element(argv[cmd_idx + 1]);
            std::cout << "{\"hovered\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        // ===== Wait =====
        else if (command == "wait-element") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: wait-element requires <selector>" << std::endl; return 1; }
            bool ok = wait_for_element(argv[cmd_idx + 1]);
            std::cout << "{\"found\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "wait-text") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: wait-text requires <text>" << std::endl; return 1; }
            bool ok = wait_for_text(argv[cmd_idx + 1]);
            std::cout << "{\"found\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "wait-nav") {
            bool ok = wait_for_navigation();
            std::cout << "{\"navigated\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        // ===== JavaScript =====
        else if (command == "js") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: js requires <script>" << std::endl; return 1; }
            std::cout << execute_javascript(argv[cmd_idx + 1]) << std::endl;
        }
        // ===== Forms =====
        else if (command == "form-fields") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: form-fields requires <form_id>" << std::endl; return 1; }
            std::cout << form_fields_to_json(get_form_fields(argv[cmd_idx + 1])) << std::endl;
        }
        // ===== Tables =====
        else if (command == "table-data") {
            std::cout << table_data_to_json(get_tables_data()) << std::endl;
        }
        else if (command == "table") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: table requires <id>" << std::endl; return 1; }
            auto t = get_table_data(argv[cmd_idx + 1]);
            std::ostringstream ss;
            ss << "{\"table\":" << t.to_json() << "}";
            std::cout << ss.str() << std::endl;
        }
        // ===== History =====
        else if (command == "history") {
            auto h = get_history();
            std::ostringstream ss;
            ss << "{\"total\":" << h.size() << ",\"history\":[";
            for (size_t i = 0; i < h.size(); i++) {
                if (i > 0) ss << ",";
                ss << "\"" << h[i] << "\"";
            }
            ss << "]}";
            std::cout << ss.str() << std::endl;
        }
        else if (command == "clear-history") {
            bool ok = clear_history();
            std::cout << "{\"cleared\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        // ===== Cookies =====
        else if (command == "cookies") {
            std::cout << get_cookies() << std::endl;
        }
        else if (command == "set-cookie") {
            if (cmd_idx + 2 >= argc) { std::cerr << "Error: set-cookie requires <name> <value>" << std::endl; return 1; }
            bool ok = set_cookie(argv[cmd_idx + 1], argv[cmd_idx + 2]);
            std::cout << "{\"set\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "clear-cookies") {
            bool ok = clear_cookies();
            std::cout << "{\"cleared\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        // ===== Export =====
        else if (command == "export") {
            std::cout << export_page_data() << std::endl;
        }
        else if (command == "save-content") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: save-content requires <path>" << std::endl; return 1; }
            bool ok = save_page_content(argv[cmd_idx + 1]);
            std::cout << "{\"saved\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        // ===== Browser Info =====
        else if (command == "browser-info") {
            std::cout << browser_info_to_json(get_browser_info()) << std::endl;
        }
        else if (command == "platform") {
            std::cout << "{\"platform\":\"" << platform_to_string(get_current_platform()) << "\"}" << std::endl;
        }
        else if (command == "stats") {
            auto elements = get_all_elements();
            auto page = get_page_info();
            std::ostringstream ss;
            ss << "{\"url\":\"" << page.url << "\",";
            ss << "\"title\":\"" << page.title << "\",";
            ss << "\"total_elements\":" << elements.size() << ",";
            ss << "\"content_length\":" << page.content_text.size() << ",";
            ss << "\"page_type\":\"" << page.page_type << "\",";
            ss << "\"scroll_y\":" << get_scroll_y() << ",";
            ss << "\"scroll_max_y\":" << get_scroll_max_y() << ",";
            // Count by type
            std::map<std::string, int> type_counts;
            for (const auto& e : elements) type_counts[e.type_string()]++;
            ss << "\"type_counts\":{";
            bool first = true;
            for (const auto& [t, c] : type_counts) {
                if (!first) ss << ",";
                ss << "\"" << t << "\":" << c;
                first = false;
            }
            ss << "},\"platform\":\"" << platform_to_string(get_current_platform()) << "\",";
            ss << "\"simulation_mode\":" << (is_simulation_mode() ? "true" : "false") << "}";
            std::cout << ss.str() << std::endl;
        }
        else {
            std::cerr << "Error: Unknown command: " << command << std::endl;
            print_usage();
            return 1;
        }
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
