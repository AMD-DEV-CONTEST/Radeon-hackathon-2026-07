#include "ui_locator.h"
#include <iostream>
#include <string>
#include <vector>
#include <sstream>

using namespace uilocator;

static void print_usage() {
    std::cerr << R"USAGE(UI Locator Tool - Cross-Platform UI Element Detection for AI Agents
=========================================================================

USAGE:
  uilocator <command> [options]

DESCRIPTION:
  Detects and locates UI elements (buttons, menus, text fields, etc.) in any
  open application window. Provides x/y coordinates, bounding boxes, and
  metadata so AI agents can interact with any program.

  Works on: Windows, Linux, macOS, Android, iOS
  Simulation mode: --sim for testing without real GUI applications

COMMANDS:
  list-windows [--sim]
      List all open windows with titles, positions, and process info.

  get-elements <window_id> [--sim]
      Get all UI elements in a specific window.
      Returns buttons, text fields, menus, etc. with coordinates.

  get-all-elements [--sim]
      Get all UI elements across all windows.

  get-element <element_id> [--sim]
      Get details of a specific UI element by ID.

  search <query> [--type <type>] [--window <window_id>] [--top-k N] [--sim]
      Search for UI elements by text label and/or type.
      Example: search "Save" --type button
      Example: search "File" --type menu_item

  search-clickable [text_filter] [--window <window_id>] [--sim]
      Search for all clickable elements (buttons, links, menu items).

  search-inputs [text_filter] [--window <window_id>] [--sim]
      Search for all text input elements (text fields, search bars, combos).

  find-at <x> <y> [--sim]
      Find the UI element at specific screen coordinates.

  get-focused [--sim]
      Get the currently focused element and window.

  get-children <element_id> [--sim]
      Get child elements of a specific element.

  get-parent <element_id> [--sim]
      Get parent element of a specific element.

  get-tree <element_id> [--sim]
      Get full element tree (element + all descendants).

  click <element_id> [--sim]
      Click a specific UI element by its ID.

  click-at <x> <y> [--sim]
      Click at specific screen coordinates.

  type-text <text> [--sim]
      Type text into the currently focused element.

  platform
      Print the current platform identifier.

  stats [--sim]
      Print statistics about detected windows and elements.

OPTIONS:
  --sim              Enable simulation mode (mock data for testing)
  --type <type>      Filter by element type (button, text_field, menu_item, etc.)
  --window <id>      Limit search to specific window
  --top-k <N>        Maximum results to return (default: 50)

ELEMENT TYPES:
  button, text_field, text_area, checkbox, radio_button, dropdown,
  combo_box, list_item, list_view, tree_item, tree_view, menu_bar,
  menu_item, context_menu, toolbar, toolbar_button, tab, tab_control,
  slider, spinner, progress_bar, label, link, image, icon, panel,
  group_box, status_bar, scrollbar, separator, dialog, notification,
  tooltip, switch, search_bar, navigation_bar, bottom_bar, fab,
  card, chip, snackbar, table, table_row, table_cell, canvas,
  embedded_view, custom

EXAMPLES:
  uilocator list-windows
  uilocator get-elements 12345
  uilocator search "Save" --type button
  uilocator search "File" --type menu_item
  uilocator search-clickable "Submit"
  uilocator find-at 500 300
  uilocator get-focused
  uilocator click element_42
  uilocator --sim list-windows
  uilocator --sim search "OK" --type button
)USAGE";
}

static std::string get_arg(int argc, char* argv[], int& i, const std::string& flag) {
    if (i + 1 < argc) return argv[++i];
    std::cerr << "Error: Missing value for " << flag << std::endl;
    return "";
}

static bool has_flag(int argc, char* argv[], const std::string& flag) {
    for (int i = 0; i < argc; i++) {
        if (std::string(argv[i]) == flag) return true;
    }
    return false;
}

// Simulation data setup for --sim mode
static void setup_simulation_data() {
    sim_clear();

    // Simulated Window 1: Text Editor
    WindowInfo editor;
    editor.id = "sim_win_editor";
    editor.title = "Untitled - TextEditor";
    editor.process_name = "texteditor.exe";
    editor.process_id = 1001;
    editor.bounds = {100, 50, 800, 600};
    editor.is_visible = true;
    editor.is_focused = true;
    editor.platform = "simulation";

    std::vector<UIElement> editor_elements;

    // Menu bar
    UIElement menu_bar;
    menu_bar.id = "elem_menubar";
    menu_bar.window_id = "sim_win_editor";
    menu_bar.type = ElementType::MENU_BAR;
    menu_bar.type_name = "MenuBar";
    menu_bar.text = "";
    menu_bar.bounds = {100, 50, 800, 25};
    menu_bar.enabled = true;
    menu_bar.visible = true;
    editor_elements.push_back(menu_bar);

    // Menu items
    const char* menu_items[] = {"File", "Edit", "View", "Insert", "Format", "Tools", "Help"};
    for (int i = 0; i < 7; i++) {
        UIElement mi;
        mi.id = "elem_menu_" + std::to_string(i);
        mi.parent_id = "elem_menubar";
        mi.window_id = "sim_win_editor";
        mi.type = ElementType::MENU_ITEM;
        mi.type_name = "MenuItem";
        mi.text = menu_items[i];
        mi.bounds = {100 + i * 60, 50, 55, 25};
        mi.enabled = true;
        mi.visible = true;
        editor_elements.push_back(mi);
    }

    // Toolbar
    UIElement toolbar;
    toolbar.id = "elem_toolbar";
    toolbar.window_id = "sim_win_editor";
    toolbar.type = ElementType::TOOLBAR;
    toolbar.type_name = "Toolbar";
    toolbar.bounds = {100, 75, 800, 35};
    toolbar.enabled = true;
    toolbar.visible = true;
    editor_elements.push_back(toolbar);

    // Toolbar buttons
    const char* tb_buttons[] = {"New", "Open", "Save", "Save As", "Print", "Cut", "Copy", "Paste", "Undo", "Redo"};
    for (int i = 0; i < 10; i++) {
        UIElement tb;
        tb.id = "elem_tb_" + std::to_string(i);
        tb.parent_id = "elem_toolbar";
        tb.window_id = "sim_win_editor";
        tb.type = ElementType::TOOLBAR_BUTTON;
        tb.type_name = "ToolbarButton";
        tb.text = tb_buttons[i];
        tb.bounds = {105 + i * 50, 78, 45, 30};
        tb.enabled = (i != 3); // "Save As" disabled for testing
        tb.visible = true;
        editor_elements.push_back(tb);
    }

    // Text area
    UIElement text_area;
    text_area.id = "elem_textarea";
    text_area.window_id = "sim_win_editor";
    text_area.type = ElementType::TEXT_AREA;
    text_area.type_name = "TextArea";
    text_area.text = "Hello World";
    text_area.bounds = {100, 110, 800, 480};
    text_area.enabled = true;
    text_area.visible = true;
    text_area.focused = true;
    editor_elements.push_back(text_area);

    // Status bar
    UIElement status_bar;
    status_bar.id = "elem_statusbar";
    status_bar.window_id = "sim_win_editor";
    status_bar.type = ElementType::STATUS_BAR;
    status_bar.type_name = "StatusBar";
    status_bar.text = "Ln 1, Col 1";
    status_bar.bounds = {100, 590, 800, 25};
    status_bar.enabled = true;
    status_bar.visible = true;
    editor_elements.push_back(status_bar);

    editor.element_count = static_cast<int>(editor_elements.size());
    sim_add_window(editor, editor_elements);

    // Simulated Window 2: Web Browser
    WindowInfo browser;
    browser.id = "sim_win_browser";
    browser.title = "Google - WebBrowser";
    browser.process_name = "webbrowser.exe";
    browser.process_id = 1002;
    browser.bounds = {200, 100, 1000, 700};
    browser.is_visible = true;
    browser.is_focused = false;
    browser.platform = "simulation";

    std::vector<UIElement> browser_elements;

    // Navigation bar
    UIElement nav_bar;
    nav_bar.id = "elem_navbar";
    nav_bar.window_id = "sim_win_browser";
    nav_bar.type = ElementType::NAVIGATION_BAR;
    nav_bar.bounds = {200, 100, 1000, 40};
    nav_bar.enabled = true;
    nav_bar.visible = true;
    browser_elements.push_back(nav_bar);

    // Back/Forward/Reload buttons
    const char* nav_buttons[] = {"Back", "Forward", "Reload"};
    for (int i = 0; i < 3; i++) {
        UIElement nb;
        nb.id = "elem_nav_" + std::to_string(i);
        nb.parent_id = "elem_navbar";
        nb.window_id = "sim_win_browser";
        nb.type = ElementType::BUTTON;
        nb.text = nav_buttons[i];
        nb.bounds = {205 + i * 40, 105, 35, 30};
        nb.enabled = (i != 0); // Back disabled
        nb.visible = true;
        browser_elements.push_back(nb);
    }

    // URL/Search bar
    UIElement url_bar;
    url_bar.id = "elem_urlbar";
    url_bar.parent_id = "elem_navbar";
    url_bar.window_id = "sim_win_browser";
    url_bar.type = ElementType::SEARCH_BAR;
    url_bar.type_name = "SearchBar";
    url_bar.text = "https://www.google.com";
    url_bar.name = "url_input";
    url_bar.bounds = {330, 105, 600, 30};
    url_bar.enabled = true;
    url_bar.visible = true;
    browser_elements.push_back(url_bar);

    // Go button
    UIElement go_btn;
    go_btn.id = "elem_go";
    go_btn.parent_id = "elem_navbar";
    go_btn.window_id = "sim_win_browser";
    go_btn.type = ElementType::BUTTON;
    go_btn.text = "Go";
    go_btn.bounds = {940, 105, 40, 30};
    go_btn.enabled = true;
    go_btn.visible = true;
    browser_elements.push_back(go_btn);

    // Web content area (panel)
    UIElement content;
    content.id = "elem_content";
    content.window_id = "sim_win_browser";
    content.type = ElementType::PANEL;
    content.bounds = {200, 140, 1000, 600};
    content.enabled = true;
    content.visible = true;
    browser_elements.push_back(content);

    // Search input on page
    UIElement search_input;
    search_input.id = "elem_search_input";
    search_input.parent_id = "elem_content";
    search_input.window_id = "sim_win_browser";
    search_input.type = ElementType::TEXT_FIELD;
    search_input.type_name = "TextField";
    search_input.text = "";
    search_input.name = "search_query";
    search_input.description = "Search the web";
    search_input.bounds = {500, 300, 400, 44};
    search_input.enabled = true;
    search_input.visible = true;
    browser_elements.push_back(search_input);

    // Google Search button
    UIElement google_search_btn;
    google_search_btn.id = "elem_google_search";
    google_search_btn.parent_id = "elem_content";
    google_search_btn.window_id = "sim_win_browser";
    google_search_btn.type = ElementType::BUTTON;
    google_search_btn.text = "Google Search";
    google_search_btn.bounds = {520, 360, 120, 36};
    google_search_btn.enabled = true;
    google_search_btn.visible = true;
    browser_elements.push_back(google_search_btn);

    // I'm Feeling Lucky button
    UIElement lucky_btn;
    lucky_btn.id = "elem_lucky";
    lucky_btn.parent_id = "elem_content";
    lucky_btn.window_id = "sim_win_browser";
    lucky_btn.type = ElementType::BUTTON;
    lucky_btn.text = "I'm Feeling Lucky";
    lucky_btn.bounds = {650, 360, 140, 36};
    lucky_btn.enabled = true;
    lucky_btn.visible = true;
    browser_elements.push_back(lucky_btn);

    // Links
    const char* links[] = {"Gmail", "Images", "Maps", "News", "Shopping"};
    for (int i = 0; i < 5; i++) {
        UIElement link;
        link.id = "elem_link_" + std::to_string(i);
        link.parent_id = "elem_content";
        link.window_id = "sim_win_browser";
        link.type = ElementType::LINK;
        link.text = links[i];
        link.bounds = {600 + i * 60, 160, 50, 20};
        link.enabled = true;
        link.visible = true;
        browser_elements.push_back(link);
    }

    browser.element_count = static_cast<int>(browser_elements.size());
    sim_add_window(browser, browser_elements);

    // Simulated Window 3: Settings Dialog
    WindowInfo dialog;
    dialog.id = "sim_win_dialog";
    dialog.title = "Settings";
    dialog.process_name = "settings.exe";
    dialog.process_id = 1003;
    dialog.bounds = {300, 200, 500, 400};
    dialog.is_visible = true;
    dialog.is_focused = false;
    dialog.platform = "simulation";

    std::vector<UIElement> dialog_elements;

    // Dialog root
    UIElement dlg_root;
    dlg_root.id = "elem_dialog";
    dlg_root.window_id = "sim_win_dialog";
    dlg_root.type = ElementType::DIALOG;
    dlg_root.text = "Settings";
    dlg_root.bounds = {300, 200, 500, 400};
    dlg_root.enabled = true;
    dlg_root.visible = true;
    dialog_elements.push_back(dlg_root);

    // Tab control
    UIElement tab_ctrl;
    tab_ctrl.id = "elem_tabctrl";
    tab_ctrl.parent_id = "elem_dialog";
    tab_ctrl.window_id = "sim_win_dialog";
    tab_ctrl.type = ElementType::TAB_CONTROL;
    tab_ctrl.bounds = {310, 230, 480, 350};
    tab_ctrl.enabled = true;
    tab_ctrl.visible = true;
    dialog_elements.push_back(tab_ctrl);

    // Tabs
    const char* tabs[] = {"General", "Privacy", "Security", "Advanced"};
    for (int i = 0; i < 4; i++) {
        UIElement tab;
        tab.id = "elem_tab_" + std::to_string(i);
        tab.parent_id = "elem_tabctrl";
        tab.window_id = "sim_win_dialog";
        tab.type = ElementType::TAB;
        tab.text = tabs[i];
        tab.bounds = {315 + i * 100, 235, 95, 25};
        tab.enabled = true;
        tab.visible = true;
        tab.selected = (i == 0);
        dialog_elements.push_back(tab);
    }

    // Checkboxes
    const char* checkboxes[] = {"Enable notifications", "Auto-update", "Send usage data", "Dark mode"};
    for (int i = 0; i < 4; i++) {
        UIElement cb;
        cb.id = "elem_checkbox_" + std::to_string(i);
        cb.parent_id = "elem_tabctrl";
        cb.window_id = "sim_win_dialog";
        cb.type = ElementType::CHECKBOX;
        cb.text = checkboxes[i];
        cb.bounds = {320, 280 + i * 35, 200, 25};
        cb.enabled = true;
        cb.visible = true;
        cb.checked = (i == 1); // Auto-update checked
        dialog_elements.push_back(cb);
    }

    // Dropdown
    UIElement dropdown;
    dropdown.id = "elem_dropdown";
    dropdown.parent_id = "elem_tabctrl";
    dropdown.window_id = "sim_win_dialog";
    dropdown.type = ElementType::DROPDOWN;
    dropdown.text = "English (US)";
    dropdown.bounds = {320, 430, 150, 30};
    dropdown.enabled = true;
    dropdown.visible = true;
    dialog_elements.push_back(dropdown);

    // Slider
    UIElement slider;
    slider.id = "elem_slider";
    slider.parent_id = "elem_tabctrl";
    slider.window_id = "sim_win_dialog";
    slider.type = ElementType::SLIDER;
    slider.text = "Volume";
    slider.bounds = {320, 470, 200, 30};
    slider.enabled = true;
    slider.visible = true;
    dialog_elements.push_back(slider);

    // OK / Cancel / Apply buttons
    const char* dlg_buttons[] = {"OK", "Cancel", "Apply"};
    for (int i = 0; i < 3; i++) {
        UIElement btn;
        btn.id = "elem_dlg_btn_" + std::to_string(i);
        btn.parent_id = "elem_dialog";
        btn.window_id = "sim_win_dialog";
        btn.type = ElementType::BUTTON;
        btn.text = dlg_buttons[i];
        btn.bounds = {500 + i * 90, 560, 80, 30};
        btn.enabled = true;
        btn.visible = true;
        dialog_elements.push_back(btn);
    }

    dialog.element_count = static_cast<int>(dialog_elements.size());
    sim_add_window(dialog, dialog_elements);

    // Simulated Window 4: Mobile App (Android-style)
    WindowInfo mobile;
    mobile.id = "sim_win_mobile";
    mobile.title = "ChatApp";
    mobile.process_name = "com.example.chatapp";
    mobile.process_id = 1004;
    mobile.bounds = {50, 50, 360, 640};
    mobile.is_visible = true;
    mobile.is_focused = false;
    mobile.platform = "simulation";

    std::vector<UIElement> mobile_elements;

    // Navigation bar
    UIElement m_nav;
    m_nav.id = "elem_m_nav";
    m_nav.window_id = "sim_win_mobile";
    m_nav.type = ElementType::NAVIGATION_BAR;
    m_nav.text = "ChatApp";
    m_nav.bounds = {50, 50, 360, 56};
    m_nav.enabled = true;
    m_nav.visible = true;
    mobile_elements.push_back(m_nav);

    // FAB (Floating Action Button)
    UIElement fab;
    fab.id = "elem_fab";
    fab.parent_id = "elem_m_nav";
    fab.window_id = "sim_win_mobile";
    fab.type = ElementType::FAB;
    fab.text = "New Chat";
    fab.bounds = {350, 610, 56, 56};
    fab.enabled = true;
    fab.visible = true;
    mobile_elements.push_back(fab);

    // Search bar
    UIElement m_search;
    m_search.id = "elem_m_search";
    m_search.parent_id = "elem_m_nav";
    m_search.window_id = "sim_win_mobile";
    m_search.type = ElementType::SEARCH_BAR;
    m_search.text = "Search contacts";
    m_search.bounds = {60, 115, 340, 40};
    m_search.enabled = true;
    m_search.visible = true;
    mobile_elements.push_back(m_search);

    // Chat list items
    const char* chats[] = {"John Doe", "Jane Smith", "Bob Wilson", "Alice Brown", "Charlie Davis"};
    for (int i = 0; i < 5; i++) {
        UIElement item;
        item.id = "elem_chat_" + std::to_string(i);
        item.parent_id = "elem_m_nav";
        item.window_id = "sim_win_mobile";
        item.type = ElementType::LIST_ITEM;
        item.text = chats[i];
        item.bounds = {60, 170 + i * 70, 340, 60};
        item.enabled = true;
        item.visible = true;
        mobile_elements.push_back(item);
    }

    // Bottom navigation
    UIElement bottom_nav;
    bottom_nav.id = "elem_bottom_nav";
    bottom_nav.window_id = "sim_win_mobile";
    bottom_nav.type = ElementType::BOTTOM_BAR;
    bottom_nav.bounds = {50, 580, 360, 60};
    bottom_nav.enabled = true;
    bottom_nav.visible = true;
    mobile_elements.push_back(bottom_nav);

    // Bottom nav items
    const char* nav_items[] = {"Chats", "Contacts", "Settings"};
    for (int i = 0; i < 3; i++) {
        UIElement ni;
        ni.id = "elem_bottom_" + std::to_string(i);
        ni.parent_id = "elem_bottom_nav";
        ni.window_id = "sim_win_mobile";
        ni.type = ElementType::BUTTON;
        ni.text = nav_items[i];
        ni.bounds = {60 + i * 120, 585, 115, 50};
        ni.enabled = true;
        ni.visible = true;
        ni.selected = (i == 0);
        mobile_elements.push_back(ni);
    }

    mobile.element_count = static_cast<int>(mobile_elements.size());
    sim_add_window(mobile, mobile_elements);

    // Simulated Window 5: IDE (VS Code-like)
    WindowInfo ide;
    ide.id = "sim_win_ide";
    ide.title = "main.cpp - MyProject - IDE";
    ide.process_name = "ide.exe";
    ide.process_id = 1005;
    ide.bounds = {0, 0, 1920, 1040};
    ide.is_visible = true;
    ide.is_focused = false;
    ide.platform = "simulation";

    std::vector<UIElement> ide_elements;

    // Title bar
    UIElement ide_titlebar;
    ide_titlebar.id = "ide_titlebar";
    ide_titlebar.window_id = "sim_win_ide";
    ide_titlebar.type = ElementType::MENU_BAR;
    ide_titlebar.type_name = "MenuBar";
    ide_titlebar.bounds = {0, 0, 1920, 30};
    ide_titlebar.enabled = true;
    ide_titlebar.visible = true;
    ide_elements.push_back(ide_titlebar);

    // Menu items
    const char* ide_menus[] = {"File", "Edit", "Selection", "View", "Go", "Run", "Terminal", "Help"};
    for (int i = 0; i < 8; i++) {
        UIElement m;
        m.id = "ide_menu_" + std::to_string(i);
        m.parent_id = "ide_titlebar";
        m.window_id = "sim_win_ide";
        m.type = ElementType::MENU_ITEM;
        m.type_name = "MenuItem";
        m.text = ide_menus[i];
        m.bounds = {5 + i * 60, 0, 55, 30};
        m.enabled = true;
        m.visible = true;
        ide_elements.push_back(m);
    }

    // Activity bar (left sidebar)
    UIElement activity_bar;
    activity_bar.id = "ide_activitybar";
    activity_bar.window_id = "sim_win_ide";
    activity_bar.type = ElementType::TOOLBAR;
    activity_bar.type_name = "Toolbar";
    activity_bar.bounds = {0, 30, 48, 1010};
    activity_bar.enabled = true;
    activity_bar.visible = true;
    ide_elements.push_back(activity_bar);

    // Activity bar icons
    const char* activities[] = {"Explorer", "Search", "Source Control", "Run and Debug", "Extensions"};
    for (int i = 0; i < 5; i++) {
        UIElement a;
        a.id = "ide_activity_" + std::to_string(i);
        a.parent_id = "ide_activitybar";
        a.window_id = "sim_win_ide";
        a.type = ElementType::TOOLBAR_BUTTON;
        a.type_name = "ToolbarButton";
        a.text = activities[i];
        a.bounds = {0, 40 + i * 48, 48, 48};
        a.enabled = true;
        a.visible = true;
        a.selected = (i == 0);
        ide_elements.push_back(a);
    }

    // Sidebar (file explorer)
    UIElement sidebar;
    sidebar.id = "ide_sidebar";
    sidebar.window_id = "sim_win_ide";
    sidebar.type = ElementType::PANEL;
    sidebar.type_name = "Panel";
    sidebar.text = "Explorer";
    sidebar.bounds = {48, 30, 250, 1010};
    sidebar.enabled = true;
    sidebar.visible = true;
    ide_elements.push_back(sidebar);

    // File tree items
    const char* files[] = {"src", "main.cpp", "utils.h", "utils.cpp", "config.json", "README.md", ".gitignore"};
    for (int i = 0; i < 7; i++) {
        UIElement f;
        f.id = "ide_file_" + std::to_string(i);
        f.parent_id = "ide_sidebar";
        f.window_id = "sim_win_ide";
        f.type = ElementType::TREE_ITEM;
        f.type_name = "TreeItem";
        f.text = files[i];
        f.bounds = {58, 60 + i * 22, 230, 22};
        f.enabled = true;
        f.visible = true;
        f.selected = (i == 1);
        ide_elements.push_back(f);
    }

    // Editor tabs
    const char* tabs_ide[] = {"main.cpp", "utils.h", "config.json"};
    for (int i = 0; i < 3; i++) {
        UIElement t;
        t.id = "ide_tab_" + std::to_string(i);
        t.parent_id = "ide_titlebar";
        t.window_id = "sim_win_ide";
        t.type = ElementType::TAB;
        t.type_name = "Tab";
        t.text = tabs_ide[i];
        t.bounds = {300 + i * 120, 30, 120, 35};
        t.enabled = true;
        t.visible = true;
        t.selected = (i == 0);
        ide_elements.push_back(t);
    }

    // Code editor area
    UIElement code_editor;
    code_editor.id = "ide_editor";
    code_editor.window_id = "sim_win_ide";
    code_editor.type = ElementType::TEXT_AREA;
    code_editor.type_name = "TextArea";
    code_editor.text = "int main() { return 0; }";
    code_editor.bounds = {300, 65, 1200, 900};
    code_editor.enabled = true;
    code_editor.visible = true;
    code_editor.focused = true;
    ide_elements.push_back(code_editor);

    // Terminal panel
    UIElement ide_terminal;
    ide_terminal.id = "ide_terminal";
    ide_terminal.window_id = "sim_win_ide";
    ide_terminal.type = ElementType::PANEL;
    ide_terminal.type_name = "Panel";
    ide_terminal.text = "Terminal";
    ide_terminal.bounds = {300, 700, 1200, 340};
    ide_terminal.enabled = true;
    ide_terminal.visible = true;
    ide_elements.push_back(ide_terminal);

    // Status bar
    UIElement ide_status;
    ide_status.id = "ide_statusbar";
    ide_status.window_id = "sim_win_ide";
    ide_status.type = ElementType::STATUS_BAR;
    ide_status.type_name = "StatusBar";
    ide_status.text = "Ln 1, Col 1  UTF-8  C++  Spaces: 4";
    ide_status.bounds = {0, 1010, 1920, 30};
    ide_status.enabled = true;
    ide_status.visible = true;
    ide_elements.push_back(ide_status);

    // Command palette button
    UIElement cmd_palette;
    cmd_palette.id = "ide_cmd_palette";
    cmd_palette.parent_id = "ide_titlebar";
    cmd_palette.window_id = "sim_win_ide";
    cmd_palette.type = ElementType::BUTTON;
    cmd_palette.text = "Command Palette";
    cmd_palette.bounds = {1850, 0, 70, 30};
    cmd_palette.enabled = true;
    cmd_palette.visible = true;
    ide_elements.push_back(cmd_palette);

    ide.element_count = static_cast<int>(ide_elements.size());
    sim_add_window(ide, ide_elements);

    // Simulated Window 6: Spreadsheet (Excel-like)
    WindowInfo spreadsheet;
    spreadsheet.id = "sim_win_spreadsheet";
    spreadsheet.title = "SalesData.xlsx - Spreadsheet";
    spreadsheet.process_name = "spreadsheet.exe";
    spreadsheet.process_id = 1006;
    spreadsheet.bounds = {50, 50, 1200, 800};
    spreadsheet.is_visible = true;
    spreadsheet.is_focused = false;
    spreadsheet.platform = "simulation";

    std::vector<UIElement> ss_elements;

    // Ribbon
    UIElement ribbon;
    ribbon.id = "ss_ribbon";
    ribbon.window_id = "sim_win_spreadsheet";
    ribbon.type = ElementType::TOOLBAR;
    ribbon.type_name = "Toolbar";
    ribbon.bounds = {50, 50, 1200, 120};
    ribbon.enabled = true;
    ribbon.visible = true;
    ss_elements.push_back(ribbon);

    // Ribbon tabs
    const char* ribbon_tabs[] = {"Home", "Insert", "Page Layout", "Formulas", "Data", "Review", "View"};
    for (int i = 0; i < 7; i++) {
        UIElement rt;
        rt.id = "ss_ribbon_tab_" + std::to_string(i);
        rt.parent_id = "ss_ribbon";
        rt.window_id = "sim_win_spreadsheet";
        rt.type = ElementType::TAB;
        rt.text = ribbon_tabs[i];
        rt.bounds = {55 + i * 90, 50, 85, 25};
        rt.enabled = true;
        rt.visible = true;
        rt.selected = (i == 0);
        ss_elements.push_back(rt);
    }

    // Ribbon buttons - Home tab
    const char* ss_buttons[] = {"Copy", "Cut", "Paste", "Bold", "Italic", "Underline", "Sort Ascending", "Sort Descending", "AutoSum", "Format Cells"};
    for (int i = 0; i < 10; i++) {
        UIElement rb;
        rb.id = "ss_btn_" + std::to_string(i);
        rb.parent_id = "ss_ribbon";
        rb.window_id = "sim_win_spreadsheet";
        rb.type = ElementType::BUTTON;
        rb.text = ss_buttons[i];
        rb.bounds = {55 + (i % 5) * 80, 80 + (i / 5) * 40, 75, 35};
        rb.enabled = true;
        rb.visible = true;
        ss_elements.push_back(rb);
    }

    // Formula bar
    UIElement formula_bar;
    formula_bar.id = "ss_formula_bar";
    formula_bar.window_id = "sim_win_spreadsheet";
    formula_bar.type = ElementType::TEXT_FIELD;
    formula_bar.type_name = "TextField";
    formula_bar.text = "=SUM(A1:A10)";
    formula_bar.name = "formula_input";
    formula_bar.bounds = {50, 170, 1200, 30};
    formula_bar.enabled = true;
    formula_bar.visible = true;
    ss_elements.push_back(formula_bar);

    // Cell grid (table)
    UIElement cell_grid;
    cell_grid.id = "ss_grid";
    cell_grid.window_id = "sim_win_spreadsheet";
    cell_grid.type = ElementType::TABLE;
    cell_grid.type_name = "Table";
    cell_grid.bounds = {50, 200, 1200, 600};
    cell_grid.enabled = true;
    cell_grid.visible = true;
    ss_elements.push_back(cell_grid);

    // Some cells
    const char* cell_values[] = {"A1", "B1", "C1", "A2", "B2", "C2"};
    for (int i = 0; i < 6; i++) {
        UIElement cell;
        cell.id = "ss_cell_" + std::to_string(i);
        cell.parent_id = "ss_grid";
        cell.window_id = "sim_win_spreadsheet";
        cell.type = ElementType::TABLE_CELL;
        cell.type_name = "TableCell";
        cell.text = cell_values[i];
        cell.bounds = {50 + (i % 3) * 100, 200 + (i / 3) * 25, 100, 25};
        cell.enabled = true;
        cell.visible = true;
        cell.selected = (i == 0);
        ss_elements.push_back(cell);
    }

    // Status bar
    UIElement ss_status;
    ss_status.id = "ss_statusbar";
    ss_status.window_id = "sim_win_spreadsheet";
    ss_status.type = ElementType::STATUS_BAR;
    ss_status.type_name = "StatusBar";
    ss_status.text = "Ready  Average: 42.5  Count: 10  Sum: 425";
    ss_status.bounds = {50, 800, 1200, 25};
    ss_status.enabled = true;
    ss_status.visible = true;
    ss_elements.push_back(ss_status);

    spreadsheet.element_count = static_cast<int>(ss_elements.size());
    sim_add_window(spreadsheet, ss_elements);

    // Simulated Window 7: Media Player (VLC-like)
    WindowInfo media;
    media.id = "sim_win_media";
    media.title = "video.mp4 - Media Player";
    media.process_name = "mediaplayer.exe";
    media.process_id = 1007;
    media.bounds = {100, 100, 800, 600};
    media.is_visible = true;
    media.is_focused = false;
    media.platform = "simulation";

    std::vector<UIElement> media_elements;

    // Menu bar
    UIElement mp_menubar;
    mp_menubar.id = "mp_menubar";
    mp_menubar.window_id = "sim_win_media";
    mp_menubar.type = ElementType::MENU_BAR;
    mp_menubar.bounds = {100, 100, 800, 25};
    mp_menubar.enabled = true;
    mp_menubar.visible = true;
    media_elements.push_back(mp_menubar);

    const char* mp_menus[] = {"Media", "Playback", "Audio", "Video", "Subtitle", "Tools", "View", "Help"};
    for (int i = 0; i < 8; i++) {
        UIElement mm;
        mm.id = "mp_menu_" + std::to_string(i);
        mm.parent_id = "mp_menubar";
        mm.window_id = "sim_win_media";
        mm.type = ElementType::MENU_ITEM;
        mm.text = mp_menus[i];
        mm.bounds = {100 + i * 60, 100, 55, 25};
        mm.enabled = true;
        mm.visible = true;
        media_elements.push_back(mm);
    }

    // Video display area
    UIElement video_area;
    video_area.id = "mp_video";
    video_area.window_id = "sim_win_media";
    video_area.type = ElementType::CANVAS;
    video_area.type_name = "Canvas";
    video_area.bounds = {100, 125, 800, 400};
    video_area.enabled = true;
    video_area.visible = true;
    media_elements.push_back(video_area);

    // Progress bar / seek bar
    UIElement seek_bar;
    seek_bar.id = "mp_seekbar";
    seek_bar.window_id = "sim_win_media";
    seek_bar.type = ElementType::SLIDER;
    seek_bar.type_name = "Slider";
    seek_bar.text = "Seek";
    seek_bar.bounds = {100, 525, 800, 20};
    seek_bar.enabled = true;
    seek_bar.visible = true;
    media_elements.push_back(seek_bar);

    // Time label
    UIElement time_label;
    time_label.id = "mp_time";
    time_label.window_id = "sim_win_media";
    time_label.type = ElementType::LABEL;
    time_label.type_name = "Label";
    time_label.text = "00:02:35 / 00:15:42";
    time_label.bounds = {100, 545, 150, 20};
    time_label.enabled = true;
    time_label.visible = true;
    media_elements.push_back(time_label);

    // Playback controls
    const char* playback_ctrls[] = {"Play", "Pause", "Stop", "Previous", "Next", "Fullscreen", "Mute", "Volume"};
    for (int i = 0; i < 8; i++) {
        UIElement pc;
        pc.id = "mp_ctrl_" + std::to_string(i);
        pc.parent_id = "mp_menubar";
        pc.window_id = "sim_win_media";
        pc.type = ElementType::BUTTON;
        pc.text = playback_ctrls[i];
        pc.bounds = {200 + i * 70, 555, 65, 35};
        pc.enabled = (i != 1); // Pause disabled when playing
        pc.visible = true;
        media_elements.push_back(pc);
    }

    // Volume slider
    UIElement vol_slider;
    vol_slider.id = "mp_volume";
    vol_slider.window_id = "sim_win_media";
    vol_slider.type = ElementType::SLIDER;
    vol_slider.type_name = "Slider";
    vol_slider.text = "Volume";
    vol_slider.bounds = {700, 555, 150, 35};
    vol_slider.enabled = true;
    vol_slider.visible = true;
    media_elements.push_back(vol_slider);

    media.element_count = static_cast<int>(media_elements.size());
    sim_add_window(media, media_elements);

    // Simulated Window 8: File Manager (Explorer-like)
    WindowInfo file_mgr;
    file_mgr.id = "sim_win_filemgr";
    file_mgr.title = "File Manager";
    file_mgr.process_name = "filemanager.exe";
    file_mgr.process_id = 1008;
    file_mgr.bounds = {150, 80, 1000, 700};
    file_mgr.is_visible = true;
    file_mgr.is_focused = false;
    file_mgr.platform = "simulation";

    std::vector<UIElement> fm_elements;

    // Navigation toolbar
    UIElement fm_nav;
    fm_nav.id = "fm_navbar";
    fm_nav.window_id = "sim_win_filemgr";
    fm_nav.type = ElementType::NAVIGATION_BAR;
    fm_nav.bounds = {150, 80, 1000, 40};
    fm_nav.enabled = true;
    fm_nav.visible = true;
    fm_elements.push_back(fm_nav);

    // Nav buttons
    const char* fm_nav_btns[] = {"Back", "Forward", "Up", "Refresh"};
    for (int i = 0; i < 4; i++) {
        UIElement nb;
        nb.id = "fm_nav_btn_" + std::to_string(i);
        nb.parent_id = "fm_navbar";
        nb.window_id = "sim_win_filemgr";
        nb.type = ElementType::BUTTON;
        nb.text = fm_nav_btns[i];
        nb.bounds = {155 + i * 40, 82, 35, 35};
        nb.enabled = (i != 1); // Forward disabled
        nb.visible = true;
        fm_elements.push_back(nb);
    }

    // Address bar
    UIElement addr_bar;
    addr_bar.id = "fm_addrbar";
    addr_bar.parent_id = "fm_navbar";
    addr_bar.window_id = "sim_win_filemgr";
    addr_bar.type = ElementType::TEXT_FIELD;
    addr_bar.type_name = "TextField";
    addr_bar.text = "C:\\Users\\Documents";
    addr_bar.name = "address";
    addr_bar.bounds = {320, 82, 600, 35};
    addr_bar.enabled = true;
    addr_bar.visible = true;
    fm_elements.push_back(addr_bar);

    // Search bar
    UIElement fm_search;
    fm_search.id = "fm_search";
    fm_search.parent_id = "fm_navbar";
    fm_search.window_id = "sim_win_filemgr";
    fm_search.type = ElementType::SEARCH_BAR;
    fm_search.type_name = "SearchBar";
    fm_search.text = "Search files";
    fm_search.bounds = {930, 82, 200, 35};
    fm_search.enabled = true;
    fm_search.visible = true;
    fm_elements.push_back(fm_search);

    // Sidebar (quick access)
    UIElement fm_sidebar;
    fm_sidebar.id = "fm_sidebar";
    fm_sidebar.window_id = "sim_win_filemgr";
    fm_sidebar.type = ElementType::PANEL;
    fm_sidebar.text = "Quick Access";
    fm_sidebar.bounds = {150, 120, 200, 660};
    fm_sidebar.enabled = true;
    fm_sidebar.visible = true;
    fm_elements.push_back(fm_sidebar);

    // Quick access items
    const char* quick_access[] = {"Desktop", "Downloads", "Documents", "Pictures", "Music", "Videos", "This PC", "Network"};
    for (int i = 0; i < 8; i++) {
        UIElement qa;
        qa.id = "fm_qa_" + std::to_string(i);
        qa.parent_id = "fm_sidebar";
        qa.window_id = "sim_win_filemgr";
        qa.type = ElementType::LIST_ITEM;
        qa.text = quick_access[i];
        qa.bounds = {155, 130 + i * 30, 190, 28};
        qa.enabled = true;
        qa.visible = true;
        fm_elements.push_back(qa);
    }

    // File list view
    UIElement fm_listview;
    fm_listview.id = "fm_listview";
    fm_listview.window_id = "sim_win_filemgr";
    fm_listview.type = ElementType::LIST_VIEW;
    fm_listview.type_name = "ListView";
    fm_listview.bounds = {350, 120, 800, 660};
    fm_listview.enabled = true;
    fm_listview.visible = true;
    fm_elements.push_back(fm_listview);

    // File items
    const char* file_items[] = {"Projects", "Reports", "Photos", "backup.zip", "notes.txt", "resume.pdf", "budget.xlsx"};
    for (int i = 0; i < 7; i++) {
        UIElement fi;
        fi.id = "fm_file_" + std::to_string(i);
        fi.parent_id = "fm_listview";
        fi.window_id = "sim_win_filemgr";
        fi.type = ElementType::LIST_ITEM;
        fi.text = file_items[i];
        fi.bounds = {360, 130 + i * 40, 780, 38};
        fi.enabled = true;
        fi.visible = true;
        fi.selected = (i == 0);
        fm_elements.push_back(fi);
    }

    // Status bar
    UIElement fm_status;
    fm_status.id = "fm_statusbar";
    fm_status.window_id = "sim_win_filemgr";
    fm_status.type = ElementType::STATUS_BAR;
    fm_status.text = "7 items  1 item selected";
    fm_status.bounds = {150, 780, 1000, 25};
    fm_status.enabled = true;
    fm_status.visible = true;
    fm_elements.push_back(fm_status);

    file_mgr.element_count = static_cast<int>(fm_elements.size());
    sim_add_window(file_mgr, fm_elements);

    // Simulated Window 9: Email Client (Outlook-like)
    WindowInfo email;
    email.id = "sim_win_email";
    email.title = "Inbox - user@email.com - Email Client";
    email.process_name = "emailclient.exe";
    email.process_id = 1009;
    email.bounds = {0, 0, 1400, 900};
    email.is_visible = true;
    email.is_focused = false;
    email.platform = "simulation";

    std::vector<UIElement> email_elements;

    // Ribbon
    UIElement em_ribbon;
    em_ribbon.id = "em_ribbon";
    em_ribbon.window_id = "sim_win_email";
    em_ribbon.type = ElementType::TOOLBAR;
    em_ribbon.bounds = {0, 0, 1400, 100};
    em_ribbon.enabled = true;
    em_ribbon.visible = true;
    email_elements.push_back(em_ribbon);

    // Ribbon buttons
    const char* em_buttons[] = {"New Email", "Reply", "Reply All", "Forward", "Delete", "Archive", "Move", "Send/Receive", "Rules", "Search"};
    for (int i = 0; i < 10; i++) {
        UIElement eb;
        eb.id = "em_btn_" + std::to_string(i);
        eb.parent_id = "em_ribbon";
        eb.window_id = "sim_win_email";
        eb.type = ElementType::BUTTON;
        eb.text = em_buttons[i];
        eb.bounds = {5 + (i % 5) * 100, 5 + (i / 5) * 45, 95, 40};
        eb.enabled = (i != 1 && i != 2 && i != 3); // Reply/Reply All/Forward disabled (no email selected)
        eb.visible = true;
        email_elements.push_back(eb);
    }

    // Folder pane
    UIElement em_folders;
    em_folders.id = "em_folders";
    em_folders.window_id = "sim_win_email";
    em_folders.type = ElementType::PANEL;
    em_folders.text = "Folders";
    em_folders.bounds = {0, 100, 250, 800};
    em_folders.enabled = true;
    em_folders.visible = true;
    email_elements.push_back(em_folders);

    // Folder items
    const char* folders[] = {"Inbox", "Sent", "Drafts", "Deleted", "Junk", "Archive", "Custom Folder"};
    for (int i = 0; i < 7; i++) {
        UIElement fd;
        fd.id = "em_folder_" + std::to_string(i);
        fd.parent_id = "em_folders";
        fd.window_id = "sim_win_email";
        fd.type = ElementType::TREE_ITEM;
        fd.text = folders[i];
        fd.bounds = {5, 110 + i * 30, 240, 28};
        fd.enabled = true;
        fd.visible = true;
        fd.selected = (i == 0);
        email_elements.push_back(fd);
    }

    // Email list
    UIElement em_list;
    em_list.id = "em_list";
    em_list.window_id = "sim_win_email";
    em_list.type = ElementType::LIST_VIEW;
    em_list.type_name = "ListView";
    em_list.bounds = {250, 100, 500, 800};
    em_list.enabled = true;
    em_list.visible = true;
    email_elements.push_back(em_list);

    // Email items
    const char* email_subjects[] = {"Meeting Tomorrow", "Project Update", "Invoice #1234", "Welcome!", "Security Alert", "Newsletter"};
    for (int i = 0; i < 6; i++) {
        UIElement ei;
        ei.id = "em_email_" + std::to_string(i);
        ei.parent_id = "em_list";
        ei.window_id = "sim_win_email";
        ei.type = ElementType::LIST_ITEM;
        ei.text = email_subjects[i];
        ei.bounds = {255, 110 + i * 60, 490, 55};
        ei.enabled = true;
        ei.visible = true;
        email_elements.push_back(ei);
    }

    // Reading pane
    UIElement em_reading;
    em_reading.id = "em_reading";
    em_reading.window_id = "sim_win_email";
    em_reading.type = ElementType::PANEL;
    em_reading.text = "Email Content";
    em_reading.bounds = {750, 100, 650, 800};
    em_reading.enabled = true;
    em_reading.visible = true;
    email_elements.push_back(em_reading);

    // Search bar
    UIElement em_search;
    em_search.id = "em_search";
    em_search.parent_id = "em_ribbon";
    em_search.window_id = "sim_win_email";
    em_search.type = ElementType::SEARCH_BAR;
    em_search.text = "Search Mail";
    em_search.bounds = {1100, 10, 280, 35};
    em_search.enabled = true;
    em_search.visible = true;
    email_elements.push_back(em_search);

    // Status bar
    UIElement em_status;
    em_status.id = "em_statusbar";
    em_status.window_id = "sim_win_email";
    em_status.type = ElementType::STATUS_BAR;
    em_status.text = "Connected  6 items  1 unread";
    em_status.bounds = {0, 875, 1400, 25};
    em_status.enabled = true;
    em_status.visible = true;
    email_elements.push_back(em_status);

    email.element_count = static_cast<int>(email_elements.size());
    sim_add_window(email, email_elements);

    // Simulated Window 10: Terminal / Console
    WindowInfo terminal;
    terminal.id = "sim_win_terminal";
    terminal.title = "Terminal - C:\\Users";
    terminal.process_name = "terminal.exe";
    terminal.process_id = 1010;
    terminal.bounds = {400, 200, 900, 600};
    terminal.is_visible = true;
    terminal.is_focused = false;
    terminal.platform = "simulation";

    std::vector<UIElement> term_elements;

    // Terminal title bar
    UIElement term_titlebar;
    term_titlebar.id = "term_titlebar";
    term_titlebar.window_id = "sim_win_terminal";
    term_titlebar.type = ElementType::MENU_BAR;
    term_titlebar.bounds = {400, 200, 900, 25};
    term_titlebar.enabled = true;
    term_titlebar.visible = true;
    term_elements.push_back(term_titlebar);

    // Terminal menu items
    const char* term_menus[] = {"File", "Edit", "View", "Search", "Terminal", "Help"};
    for (int i = 0; i < 6; i++) {
        UIElement tm;
        tm.id = "term_menu_" + std::to_string(i);
        tm.parent_id = "term_titlebar";
        tm.window_id = "sim_win_terminal";
        tm.type = ElementType::MENU_ITEM;
        tm.text = term_menus[i];
        tm.bounds = {405 + i * 55, 200, 50, 25};
        tm.enabled = true;
        tm.visible = true;
        term_elements.push_back(tm);
    }

    // Terminal text area
    UIElement term_text;
    term_text.id = "term_textarea";
    term_text.window_id = "sim_win_terminal";
    term_text.type = ElementType::TEXT_AREA;
    term_text.type_name = "TextArea";
    term_text.text = "C:\\Users> dir";
    term_text.bounds = {400, 225, 900, 540};
    term_text.enabled = true;
    term_text.visible = true;
    term_text.focused = true;
    term_elements.push_back(term_text);

    // New tab button
    UIElement term_newtab;
    term_newtab.id = "term_newtab";
    term_newtab.parent_id = "term_titlebar";
    term_newtab.window_id = "sim_win_terminal";
    term_newtab.type = ElementType::BUTTON;
    term_newtab.text = "New Tab";
    term_newtab.bounds = {1250, 200, 50, 25};
    term_newtab.enabled = true;
    term_newtab.visible = true;
    term_elements.push_back(term_newtab);

    // Split pane button
    UIElement term_split;
    term_split.id = "term_split";
    term_split.parent_id = "term_titlebar";
    term_split.window_id = "sim_win_terminal";
    term_split.type = ElementType::BUTTON;
    term_split.text = "Split Pane";
    term_split.bounds = {1200, 200, 50, 25};
    term_split.enabled = true;
    term_split.visible = true;
    term_elements.push_back(term_split);

    // Scrollbar
    UIElement term_scroll;
    term_scroll.id = "term_scrollbar";
    term_scroll.window_id = "sim_win_terminal";
    term_scroll.type = ElementType::SCROLLBAR;
    term_scroll.bounds = {1280, 225, 20, 540};
    term_scroll.enabled = true;
    term_scroll.visible = true;
    term_elements.push_back(term_scroll);

    terminal.element_count = static_cast<int>(term_elements.size());
    sim_add_window(terminal, term_elements);
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

    // Parse common options (starting after the command)
    std::string type_filter;
    std::string window_filter;
    size_t top_k = 50;

    for (int i = cmd_idx + 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--type" && i + 1 < argc) {
            type_filter = argv[++i];
        } else if (arg == "--window" && i + 1 < argc) {
            window_filter = argv[++i];
        } else if (arg == "--top-k" && i + 1 < argc) {
            top_k = static_cast<size_t>(std::stoul(argv[++i]));
        } else if (arg == "--sim") {
            // Already handled
        }
    }

    try {
        if (command == "list-windows") {
            auto windows = list_windows();
            std::cout << windows_to_json(windows) << std::endl;
        }
        else if (command == "get-elements") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: get-elements requires <window_id>" << std::endl; return 1; }
            auto elements = get_elements(argv[cmd_idx + 1]);
            std::cout << elements_to_json(elements) << std::endl;
        }
        else if (command == "get-all-elements") {
            auto elements = get_all_elements();
            std::cout << elements_to_json(elements) << std::endl;
        }
        else if (command == "get-element") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: get-element requires <element_id>" << std::endl; return 1; }
            auto elem = get_element(argv[cmd_idx + 1]);
            std::cout << element_to_json(elem) << std::endl;
        }
        else if (command == "search") {
            std::string query;
            if (cmd_idx + 1 < argc && argv[cmd_idx + 1][0] != '-') {
                query = argv[cmd_idx + 1];
            }
            auto results = search_elements(query, type_filter, window_filter, top_k);
            std::cout << search_results_to_json(results) << std::endl;
        }
        else if (command == "search-clickable") {
            std::string text_filter = (cmd_idx + 1 < argc && argv[cmd_idx + 1][0] != '-') ? argv[cmd_idx + 1] : "";
            auto results = search_clickable(text_filter, window_filter);
            std::cout << search_results_to_json(results) << std::endl;
        }
        else if (command == "search-inputs") {
            std::string text_filter = (cmd_idx + 1 < argc && argv[cmd_idx + 1][0] != '-') ? argv[cmd_idx + 1] : "";
            auto results = search_text_inputs(text_filter, window_filter);
            std::cout << search_results_to_json(results) << std::endl;
        }
        else if (command == "find-at") {
            if (cmd_idx + 2 >= argc) { std::cerr << "Error: find-at requires <x> <y>" << std::endl; return 1; }
            int x = std::stoi(argv[cmd_idx + 1]);
            int y = std::stoi(argv[cmd_idx + 2]);
            auto elem = find_element_at(x, y);
            std::cout << element_to_json(elem) << std::endl;
        }
        else if (command == "get-focused") {
            auto elem = get_focused_element();
            auto win = get_focused_window();
            std::ostringstream ss;
            ss << "{\"focused_window\":" << win.to_json() << ",";
            ss << "\"focused_element\":" << elem.to_json() << "}";
            std::cout << ss.str() << std::endl;
        }
        else if (command == "get-children") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: get-children requires <element_id>" << std::endl; return 1; }
            auto children = get_children(argv[cmd_idx + 1]);
            std::cout << elements_to_json(children) << std::endl;
        }
        else if (command == "get-parent") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: get-parent requires <element_id>" << std::endl; return 1; }
            auto parent = get_parent(argv[cmd_idx + 1]);
            std::cout << element_to_json(parent) << std::endl;
        }
        else if (command == "get-tree") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: get-tree requires <element_id>" << std::endl; return 1; }
            auto tree = get_element_tree(argv[cmd_idx + 1]);
            std::cout << elements_to_json(tree) << std::endl;
        }
        else if (command == "click") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: click requires <element_id>" << std::endl; return 1; }
            std::string elem_id = argv[cmd_idx + 1];
            bool ok = click_element(elem_id);
            std::cout << "{\"clicked\":" << (ok ? "true" : "false") << ",\"element_id\":\"" << elem_id << "\"}" << std::endl;
        }
        else if (command == "click-at") {
            if (cmd_idx + 2 >= argc) { std::cerr << "Error: click-at requires <x> <y>" << std::endl; return 1; }
            int x = std::stoi(argv[cmd_idx + 1]);
            int y = std::stoi(argv[cmd_idx + 2]);
            bool ok = click_at(x, y);
            std::cout << "{\"clicked\":" << (ok ? "true" : "false") << ",\"x\":" << x << ",\"y\":" << y << "}" << std::endl;
        }
        else if (command == "type-text") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: type-text requires <text>" << std::endl; return 1; }
            bool ok = type_text(argv[cmd_idx + 1]);
            std::cout << "{\"typed\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "stats") {
            auto windows = list_windows();
            auto elements = get_all_elements();
            std::ostringstream ss;
            ss << "{\"total_windows\":" << windows.size() << ",";
            ss << "\"total_elements\":" << elements.size() << ",";
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
        // ===== Multi-Monitor =====
        else if (command == "screens") {
            auto screens = get_screens();
            std::cout << screens_to_json(screens) << std::endl;
        }
        else if (command == "primary-screen") {
            auto screen = get_primary_screen();
            std::cout << "{\"screen\":" << screen.to_json() << "}" << std::endl;
        }
        else if (command == "screen-at") {
            if (cmd_idx + 2 >= argc) { std::cerr << "Error: screen-at requires <x> <y>" << std::endl; return 1; }
            auto screen = get_screen_at(std::stoi(argv[cmd_idx + 1]), std::stoi(argv[cmd_idx + 2]));
            std::cout << "{\"screen\":" << screen.to_json() << "}" << std::endl;
        }
        // ===== Element State =====
        else if (command == "element-state") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: element-state requires <element_id>" << std::endl; return 1; }
            auto state = get_element_state(argv[cmd_idx + 1]);
            std::cout << "{\"state\":" << state.to_json() << "}" << std::endl;
        }
        else if (command == "is-enabled") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: is-enabled requires <element_id>" << std::endl; return 1; }
            std::cout << "{\"enabled\":" << (is_element_enabled(argv[cmd_idx + 1]) ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "is-visible") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: is-visible requires <element_id>" << std::endl; return 1; }
            std::cout << "{\"visible\":" << (is_element_visible(argv[cmd_idx + 1]) ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "is-checked") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: is-checked requires <element_id>" << std::endl; return 1; }
            std::cout << "{\"checked\":" << (is_element_checked(argv[cmd_idx + 1]) ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "element-value") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: element-value requires <element_id>" << std::endl; return 1; }
            std::cout << "{\"value\":\"" << get_element_value(argv[cmd_idx + 1]) << "\"}" << std::endl;
        }
        // ===== Advanced Actions =====
        else if (command == "scroll") {
            if (cmd_idx + 2 >= argc) { std::cerr << "Error: scroll requires <x> <y> [dx] [dy]" << std::endl; return 1; }
            int sx = std::stoi(argv[cmd_idx + 1]);
            int sy = std::stoi(argv[cmd_idx + 2]);
            int dx = (cmd_idx + 3 < argc) ? std::stoi(argv[cmd_idx + 3]) : 0;
            int dy = (cmd_idx + 4 < argc) ? std::stoi(argv[cmd_idx + 4]) : -3;
            bool ok = scroll_at(sx, sy, dx, dy);
            std::cout << "{\"scrolled\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "hover") {
            if (cmd_idx + 2 >= argc) { std::cerr << "Error: hover requires <x> <y>" << std::endl; return 1; }
            bool ok = hover_at(std::stoi(argv[cmd_idx + 1]), std::stoi(argv[cmd_idx + 2]));
            std::cout << "{\"hovered\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "hover-element") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: hover-element requires <element_id>" << std::endl; return 1; }
            bool ok = hover_element(argv[cmd_idx + 1]);
            std::cout << "{\"hovered\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "drag") {
            if (cmd_idx + 4 >= argc) { std::cerr << "Error: drag requires <from_x> <from_y> <to_x> <to_y>" << std::endl; return 1; }
            bool ok = drag(std::stoi(argv[cmd_idx + 1]), std::stoi(argv[cmd_idx + 2]),
                          std::stoi(argv[cmd_idx + 3]), std::stoi(argv[cmd_idx + 4]));
            std::cout << "{\"dragged\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "send-shortcut") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: send-shortcut requires <shortcut_name>" << std::endl; return 1; }
            bool ok = send_shortcut(argv[cmd_idx + 1]);
            std::cout << "{\"sent\":" << (ok ? "true" : "false") << ",\"shortcut\":\"" << argv[cmd_idx + 1] << "\"}" << std::endl;
        }
        // ===== Wait/Poll =====
        else if (command == "wait-for-element") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: wait-for-element requires <query>" << std::endl; return 1; }
            int timeout = (cmd_idx + 2 < argc && argv[cmd_idx + 2][0] != '-') ? std::stoi(argv[cmd_idx + 2]) : 5000;
            auto elem = wait_for_element(argv[cmd_idx + 1], timeout, type_filter, window_filter);
            std::cout << element_to_json(elem) << std::endl;
        }
        else if (command == "wait-for-window") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: wait-for-window requires <title_contains>" << std::endl; return 1; }
            int timeout = (cmd_idx + 2 < argc) ? std::stoi(argv[cmd_idx + 2]) : 5000;
            auto win = wait_for_window(argv[cmd_idx + 1], timeout);
            std::cout << window_to_json(win) << std::endl;
        }
        // ===== Element Path =====
        else if (command == "find-by-path") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: find-by-path requires <path>" << std::endl; return 1; }
            auto elems = find_by_path(argv[cmd_idx + 1]);
            std::cout << elements_to_json(elems) << std::endl;
        }
        else if (command == "element-path") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: element-path requires <element_id>" << std::endl; return 1; }
            std::string path = get_element_path(argv[cmd_idx + 1]);
            std::cout << "{\"path\":\"" << path << "\"}" << std::endl;
        }
        // ===== Window Management =====
        else if (command == "focus-window") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: focus-window requires <window_id>" << std::endl; return 1; }
            bool ok = focus_window(argv[cmd_idx + 1]);
            std::cout << "{\"focused\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "minimize-window") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: minimize-window requires <window_id>" << std::endl; return 1; }
            bool ok = minimize_window(argv[cmd_idx + 1]);
            std::cout << "{\"minimized\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "maximize-window") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: maximize-window requires <window_id>" << std::endl; return 1; }
            bool ok = maximize_window(argv[cmd_idx + 1]);
            std::cout << "{\"maximized\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "restore-window") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: restore-window requires <window_id>" << std::endl; return 1; }
            bool ok = restore_window(argv[cmd_idx + 1]);
            std::cout << "{\"restored\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "close-window") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: close-window requires <window_id>" << std::endl; return 1; }
            bool ok = close_window(argv[cmd_idx + 1]);
            std::cout << "{\"closed\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "move-window") {
            if (cmd_idx + 3 >= argc) { std::cerr << "Error: move-window requires <window_id> <x> <y>" << std::endl; return 1; }
            bool ok = move_window(argv[cmd_idx + 1], std::stoi(argv[cmd_idx + 2]), std::stoi(argv[cmd_idx + 3]));
            std::cout << "{\"moved\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "resize-window") {
            if (cmd_idx + 3 >= argc) { std::cerr << "Error: resize-window requires <window_id> <width> <height>" << std::endl; return 1; }
            bool ok = resize_window(argv[cmd_idx + 1], std::stoi(argv[cmd_idx + 2]), std::stoi(argv[cmd_idx + 3]));
            std::cout << "{\"resized\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        // ===== Nearest Element =====
        else if (command == "nearest-clickable") {
            if (cmd_idx + 2 >= argc) { std::cerr << "Error: nearest-clickable requires <x> <y>" << std::endl; return 1; }
            int max_dist = (cmd_idx + 3 < argc) ? std::stoi(argv[cmd_idx + 3]) : 200;
            auto elem = find_nearest_clickable(std::stoi(argv[cmd_idx + 1]), std::stoi(argv[cmd_idx + 2]), max_dist);
            std::cout << element_to_json(elem) << std::endl;
        }
        else if (command == "nearest-by-type") {
            if (cmd_idx + 3 >= argc) { std::cerr << "Error: nearest-by-type requires <x> <y> <type>" << std::endl; return 1; }
            int max_dist = (cmd_idx + 4 < argc) ? std::stoi(argv[cmd_idx + 4]) : 200;
            auto elem = find_nearest_by_type(std::stoi(argv[cmd_idx + 1]), std::stoi(argv[cmd_idx + 2]),
                                             string_to_element_type(argv[cmd_idx + 3]), max_dist);
            std::cout << element_to_json(elem) << std::endl;
        }
        else if (command == "nearest-by-text") {
            if (cmd_idx + 3 >= argc) { std::cerr << "Error: nearest-by-text requires <x> <y> <text>" << std::endl; return 1; }
            int max_dist = (cmd_idx + 4 < argc) ? std::stoi(argv[cmd_idx + 4]) : 200;
            auto elem = find_nearest_by_text(std::stoi(argv[cmd_idx + 1]), std::stoi(argv[cmd_idx + 2]),
                                             argv[cmd_idx + 3], max_dist);
            std::cout << element_to_json(elem) << std::endl;
        }
        // ===== Export/Import =====
        else if (command == "export-map") {
            std::cout << export_element_map() << std::endl;
        }
        else if (command == "save-map") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: save-map requires <filepath>" << std::endl; return 1; }
            bool ok = save_element_map(argv[cmd_idx + 1]);
            std::cout << "{\"saved\":" << (ok ? "true" : "false") << ",\"filepath\":\"" << argv[cmd_idx + 1] << "\"}" << std::endl;
        }
        else if (command == "load-map") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: load-map requires <filepath>" << std::endl; return 1; }
            bool ok = load_element_map(argv[cmd_idx + 1]);
            std::cout << "{\"loaded\":" << (ok ? "true" : "false") << ",\"filepath\":\"" << argv[cmd_idx + 1] << "\"}" << std::endl;
        }
        // ===== Keyboard Shortcuts =====
        else if (command == "shortcuts") {
            std::cout << shortcuts_to_json() << std::endl;
        }
        else if (command == "get-shortcut") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: get-shortcut requires <name>" << std::endl; return 1; }
            auto sc = get_shortcut(argv[cmd_idx + 1]);
            std::cout << "{\"shortcut\":" << sc.to_json() << "}" << std::endl;
        }
        // ===== Regions =====
        else if (command == "detect-regions") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: detect-regions requires <window_id>" << std::endl; return 1; }
            auto regions = detect_regions(argv[cmd_idx + 1]);
            std::cout << regions_to_json(regions) << std::endl;
        }
        else if (command == "elements-in-region") {
            if (cmd_idx + 2 >= argc) { std::cerr << "Error: elements-in-region requires <window_id> <region_type>" << std::endl; return 1; }
            auto elems = get_elements_in_region(argv[cmd_idx + 1], argv[cmd_idx + 2]);
            std::cout << elements_to_json(elems) << std::endl;
        }
        // ===== Change Detection =====
        else if (command == "snapshot") {
            std::cout << snapshot_elements() << std::endl;
        }
        // ===== Highlight =====
        else if (command == "highlight") {
            if (cmd_idx + 1 >= argc) { std::cerr << "Error: highlight requires <element_id>" << std::endl; return 1; }
            bool ok = highlight_element(argv[cmd_idx + 1]);
            std::cout << "{\"highlighted\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "highlight-region") {
            if (cmd_idx + 4 >= argc) { std::cerr << "Error: highlight-region requires <x> <y> <width> <height>" << std::endl; return 1; }
            bool ok = highlight_region(std::stoi(argv[cmd_idx + 1]), std::stoi(argv[cmd_idx + 2]),
                                       std::stoi(argv[cmd_idx + 3]), std::stoi(argv[cmd_idx + 4]));
            std::cout << "{\"highlighted\":" << (ok ? "true" : "false") << "}" << std::endl;
        }
        else if (command == "clear-highlights") {
            bool ok = clear_highlights();
            std::cout << "{\"cleared\":" << (ok ? "true" : "false") << "}" << std::endl;
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
