// main_screen.cpp - CLI for Screen Context Reader
// Lets AI agents see what's on the user's screen and assess context
#include "screen_context.h"
#include <iostream>
#include <string>
#include <cstring>

static bool has_flag(int argc, char* argv[], const char* flag) {
    for (int i = 1; i < argc; i++) {
        if (std::strcmp(argv[i], flag) == 0) return true;
    }
    return false;
}

static void print_usage() {
    std::cout << "Screen Context Reader - AI Screen Awareness Tool" << std::endl;
    std::cout << std::endl;
    std::cout << "Usage: screencontext [options] <command> [args]" << std::endl;
    std::cout << std::endl;
    std::cout << "Options:" << std::endl;
    std::cout << "  --sim          Enable simulation mode (mock data)" << std::endl;
    std::cout << std::endl;
    std::cout << "Commands:" << std::endl;
    std::cout << "  list-apps                    List all open applications" << std::endl;
    std::cout << "  get-active-app               Get the currently focused app" << std::endl;
    std::cout << "  capture-screen [path]        Capture full screen to image file" << std::endl;
    std::cout << "  capture-window <id> [path]   Capture specific window to image" << std::endl;
    std::cout << "  capture-region <x> <y> <w> <h> [path]  Capture screen region" << std::endl;
    std::cout << "  ocr-screen                   Extract text from screen (OCR)" << std::endl;
    std::cout << "  ocr-window <id>              Extract text from specific window" << std::endl;
    std::cout << "  ocr-region <x> <y> <w> <h>   Extract text from screen region" << std::endl;
    std::cout << "  get-content [window_id]      Get content blocks from screen/app" << std::endl;
    std::cout << "  get-context                  Get full user context assessment" << std::endl;
    std::cout << "  assess                       Assess user situation (alias for get-context)" << std::endl;
    std::cout << "  search-content <query> [window_id]  Search visible content for text" << std::endl;
    std::cout << "  app-summary                  Get summary of open apps by category" << std::endl;
    std::cout << "  screen-content               Get full screen content snapshot" << std::endl;
    std::cout << "  uia-tree [window_id]         Get UI Automation tree (semantic elements)" << std::endl;
    std::cout << "  uia-elements [window_id]     Get flat list of UIA elements" << std::endl;
    std::cout << "  element-state <element_id>   Get state of a specific UI element" << std::endl;
    std::cout << "  interactive-elements [window_id]  Get all interactive UI elements" << std::endl;
    std::cout << "  verify-action <element_id> <action>  Verify if action can be performed" << std::endl;
    std::cout << "  find-by-type <control_type> [window_id]  Find elements by control type" << std::endl;
    std::cout << "  find-by-name <name> [window_id]  Find elements by name" << std::endl;
    std::cout << "  focused-chain [window_id]    Get element chain from root to focused element" << std::endl;
    std::cout << "  platform                     Show current platform" << std::endl;
    std::cout << std::endl;
    std::cout << "Examples:" << std::endl;
    std::cout << "  screencontext --sim list-apps" << std::endl;
    std::cout << "  screencontext --sim get-context" << std::endl;
    std::cout << "  screencontext --sim get-content sim_fb" << std::endl;
    std::cout << "  screencontext capture-screen screenshot.bmp" << std::endl;
    std::cout << "  screencontext ocr-screen" << std::endl;
}

int main(int argc, char* argv[]) {
    if (argc < 2) {
        print_usage();
        return 1;
    }

    // Find the actual command (skip --sim if it comes first)
    int cmd_idx = 1;
    bool sim_mode = false;
    while (cmd_idx < argc) {
        std::string arg = argv[cmd_idx];
        if (arg == "--sim") {
            sim_mode = true;
            cmd_idx++;
        } else {
            break;
        }
    }

    if (cmd_idx >= argc) {
        print_usage();
        return 1;
    }

    std::string command = argv[cmd_idx];

    if (command == "--help" || command == "-h" || command == "help") {
        print_usage();
        return 0;
    }

    // Also check for --sim anywhere in args
    if (has_flag(argc, argv, "--sim")) {
        sim_mode = true;
    }

    if (sim_mode) {
        enable_simulation_mode();
        setup_simulation_data();
    }

    if (command == "platform") {
        std::cout << "{\"platform\":\"" << platform_to_string(get_current_platform()) << "\"}" << std::endl;
        return 0;
    }

    try {
        if (command == "list-apps") {
            auto apps = list_open_apps();
            std::cout << apps_to_json(apps) << std::endl;
        }
        else if (command == "get-active-app") {
            auto app = get_active_app();
            std::cout << app_info_to_json(app) << std::endl;
        }
        else if (command == "capture-screen") {
            std::string path = (cmd_idx + 1 < argc && argv[cmd_idx + 1][0] != '-') ? argv[cmd_idx + 1] : "";
            auto info = capture_screen(path);
            std::cout << screen_capture_to_json(info) << std::endl;
        }
        else if (command == "capture-window") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: capture-window requires <window_id>" << std::endl; return 1; }
            std::string window_id = argv[cmd_idx + 1];
            std::string path = (cmd_idx + 2 < argc && argv[cmd_idx + 2][0] != '-') ? argv[cmd_idx + 2] : "";
            auto info = capture_window(window_id, path);
            std::cout << screen_capture_to_json(info) << std::endl;
        }
        else if (command == "capture-region") {
            if (cmd_idx + 4 >= argc) { std::cerr << "Error: capture-region requires <x> <y> <w> <h>" << std::endl; return 1; }
            int x = std::stoi(argv[cmd_idx + 1]);
            int y = std::stoi(argv[cmd_idx + 2]);
            int w = std::stoi(argv[cmd_idx + 3]);
            int h = std::stoi(argv[cmd_idx + 4]);
            std::string path = (cmd_idx + 5 < argc && argv[cmd_idx + 5][0] != '-') ? argv[cmd_idx + 5] : "";
            auto info = capture_region(x, y, w, h, path);
            std::cout << screen_capture_to_json(info) << std::endl;
        }
        else if (command == "ocr-screen") {
            auto result = ocr_screen();
            std::cout << ocr_result_to_json(result) << std::endl;
        }
        else if (command == "ocr-window") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: ocr-window requires <window_id>" << std::endl; return 1; }
            std::string window_id = argv[cmd_idx + 1];
            auto result = ocr_window(window_id);
            std::cout << ocr_result_to_json(result) << std::endl;
        }
        else if (command == "ocr-region") {
            if (cmd_idx + 4 >= argc) { std::cerr << "Error: ocr-region requires <x> <y> <w> <h>" << std::endl; return 1; }
            int x = std::stoi(argv[cmd_idx + 1]);
            int y = std::stoi(argv[cmd_idx + 2]);
            int w = std::stoi(argv[cmd_idx + 3]);
            int h = std::stoi(argv[cmd_idx + 4]);
            auto result = ocr_region(x, y, w, h);
            std::cout << ocr_result_to_json(result) << std::endl;
        }
        else if (command == "get-content") {
            std::string window_id = (cmd_idx + 1 < argc && argv[cmd_idx + 1][0] != '-') ? argv[cmd_idx + 1] : "";
            auto blocks = extract_content_blocks(window_id);
            std::cout << content_blocks_to_json(blocks) << std::endl;
        }
        else if (command == "get-context" || command == "assess") {
            auto ctx = get_user_context();
            std::cout << user_context_to_json(ctx) << std::endl;
        }
        else if (command == "search-content") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: search-content requires <query>" << std::endl; return 1; }
            std::string query = argv[cmd_idx + 1];
            std::string window_id = (cmd_idx + 2 < argc && argv[cmd_idx + 2][0] != '-') ? argv[cmd_idx + 2] : "";
            auto results = search_content(query, window_id);
            std::cout << content_search_results_to_json(results) << std::endl;
        }
        else if (command == "app-summary") {
            auto summary = get_app_summary();
            std::cout << app_summary_to_json(summary) << std::endl;
        }
        else if (command == "screen-content") {
            auto content = get_screen_content();
            std::cout << screen_content_to_json(content) << std::endl;
        }
        else if (command == "uia-tree") {
            std::string window_id = (cmd_idx + 1 < argc && argv[cmd_idx + 1][0] != '-') ? argv[cmd_idx + 1] : "";
            auto tree = get_uia_tree(window_id);
            std::cout << uia_tree_to_json(tree) << std::endl;
        }
        else if (command == "uia-elements") {
            std::string window_id = (cmd_idx + 1 < argc && argv[cmd_idx + 1][0] != '-') ? argv[cmd_idx + 1] : "";
            auto elements = get_uia_elements(window_id);
            std::cout << "{\"total_elements\":" << elements.size() << ",\"elements\":[";
            for (size_t i = 0; i < elements.size(); i++) {
                if (i > 0) std::cout << ",";
                std::cout << uia_element_to_json(elements[i]);
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "element-state") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: element-state requires <element_id>" << std::endl; return 1; }
            std::string element_id = argv[cmd_idx + 1];
            auto state = get_element_state(element_id);
            std::cout << element_state_to_json(state) << std::endl;
        }
        else if (command == "interactive-elements") {
            std::string window_id = (cmd_idx + 1 < argc && argv[cmd_idx + 1][0] != '-') ? argv[cmd_idx + 1] : "";
            auto elements = get_interactive_elements(window_id);
            std::cout << interactive_elements_to_json(elements) << std::endl;
        }
        else if (command == "verify-action") {
            if (cmd_idx + 2 >= argc) { std::cerr << "Error: verify-action requires <element_id> <action>" << std::endl; return 1; }
            std::string element_id = argv[cmd_idx + 1];
            std::string action = argv[cmd_idx + 2];
            auto result = verify_action(element_id, action);
            std::cout << action_verify_to_json(result) << std::endl;
        }
        else if (command == "find-by-type") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: find-by-type requires <control_type>" << std::endl; return 1; }
            std::string control_type = argv[cmd_idx + 1];
            std::string window_id = (cmd_idx + 2 < argc && argv[cmd_idx + 2][0] != '-') ? argv[cmd_idx + 2] : "";
            auto elements = find_elements_by_type(control_type, window_id);
            std::cout << "{\"total_found\":" << elements.size() << ",\"elements\":[";
            for (size_t i = 0; i < elements.size(); i++) {
                if (i > 0) std::cout << ",";
                std::cout << uia_element_to_json(elements[i]);
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "find-by-name") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: find-by-name requires <name>" << std::endl; return 1; }
            std::string name = argv[cmd_idx + 1];
            std::string window_id = (cmd_idx + 2 < argc && argv[cmd_idx + 2][0] != '-') ? argv[cmd_idx + 2] : "";
            auto elements = find_elements_by_name(name, window_id);
            std::cout << "{\"total_found\":" << elements.size() << ",\"elements\":[";
            for (size_t i = 0; i < elements.size(); i++) {
                if (i > 0) std::cout << ",";
                std::cout << uia_element_to_json(elements[i]);
            }
            std::cout << "]}" << std::endl;
        }
        else if (command == "focused-chain") {
            std::string window_id = (cmd_idx + 1 < argc && argv[cmd_idx + 1][0] != '-') ? argv[cmd_idx + 1] : "";
            auto chain = get_focused_element_chain(window_id);
            std::cout << "{\"chain_length\":" << chain.size() << ",\"elements\":[";
            for (size_t i = 0; i < chain.size(); i++) {
                if (i > 0) std::cout << ",";
                std::cout << uia_element_to_json(chain[i]);
            }
            std::cout << "]}" << std::endl;
        }
        else {
            std::cerr << "Unknown command: " << command << std::endl;
            std::cerr << "Run 'screencontext help' for usage." << std::endl;
            return 1;
        }
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
