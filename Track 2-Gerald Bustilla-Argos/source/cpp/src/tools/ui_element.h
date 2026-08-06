#pragma once

#include <string>
#include <vector>
#include <map>
#include <cstdint>
#include <algorithm>
#include <sstream>
#include <iomanip>

namespace uilocator {

// UI element types - covers all common UI controls across platforms
enum class ElementType : int {
    UNKNOWN = 0,
    WINDOW,
    BUTTON,
    TEXT_FIELD,
    TEXT_AREA,
    CHECKBOX,
    RADIO_BUTTON,
    DROPDOWN,
    COMBO_BOX,
    LIST_ITEM,
    LIST_VIEW,
    TREE_ITEM,
    TREE_VIEW,
    MENU_BAR,
    MENU_ITEM,
    CONTEXT_MENU,
    TOOLBAR,
    TOOLBAR_BUTTON,
    TAB,
    TAB_CONTROL,
    SLIDER,
    SPINNER,
    PROGRESS_BAR,
    LABEL,
    LINK,
    IMAGE,
    ICON,
    PANEL,
    GROUP_BOX,
    STATUS_BAR,
    SCROLLBAR,
    SEPARATOR,
    DIALOG,
    NOTIFICATION,
    TOOLTIP,
    SWITCH,
    SEARCH_BAR,
    NAVIGATION_BAR,
    BOTTOM_BAR,
    FAB,  // Floating Action Button (Android)
    CARD,
    CHIP,
    SNACKBAR,
    TABLE,
    TABLE_ROW,
    TABLE_CELL,
    CANVAS,
    EMBEDDED_VIEW,
    CUSTOM
};

// Convert ElementType to string
inline std::string element_type_to_string(ElementType type) {
    switch (type) {
        case ElementType::WINDOW: return "window";
        case ElementType::BUTTON: return "button";
        case ElementType::TEXT_FIELD: return "text_field";
        case ElementType::TEXT_AREA: return "text_area";
        case ElementType::CHECKBOX: return "checkbox";
        case ElementType::RADIO_BUTTON: return "radio_button";
        case ElementType::DROPDOWN: return "dropdown";
        case ElementType::COMBO_BOX: return "combo_box";
        case ElementType::LIST_ITEM: return "list_item";
        case ElementType::LIST_VIEW: return "list_view";
        case ElementType::TREE_ITEM: return "tree_item";
        case ElementType::TREE_VIEW: return "tree_view";
        case ElementType::MENU_BAR: return "menu_bar";
        case ElementType::MENU_ITEM: return "menu_item";
        case ElementType::CONTEXT_MENU: return "context_menu";
        case ElementType::TOOLBAR: return "toolbar";
        case ElementType::TOOLBAR_BUTTON: return "toolbar_button";
        case ElementType::TAB: return "tab";
        case ElementType::TAB_CONTROL: return "tab_control";
        case ElementType::SLIDER: return "slider";
        case ElementType::SPINNER: return "spinner";
        case ElementType::PROGRESS_BAR: return "progress_bar";
        case ElementType::LABEL: return "label";
        case ElementType::LINK: return "link";
        case ElementType::IMAGE: return "image";
        case ElementType::ICON: return "icon";
        case ElementType::PANEL: return "panel";
        case ElementType::GROUP_BOX: return "group_box";
        case ElementType::STATUS_BAR: return "status_bar";
        case ElementType::SCROLLBAR: return "scrollbar";
        case ElementType::SEPARATOR: return "separator";
        case ElementType::DIALOG: return "dialog";
        case ElementType::NOTIFICATION: return "notification";
        case ElementType::TOOLTIP: return "tooltip";
        case ElementType::SWITCH: return "switch";
        case ElementType::SEARCH_BAR: return "search_bar";
        case ElementType::NAVIGATION_BAR: return "navigation_bar";
        case ElementType::BOTTOM_BAR: return "bottom_bar";
        case ElementType::FAB: return "fab";
        case ElementType::CARD: return "card";
        case ElementType::CHIP: return "chip";
        case ElementType::SNACKBAR: return "snackbar";
        case ElementType::TABLE: return "table";
        case ElementType::TABLE_ROW: return "table_row";
        case ElementType::TABLE_CELL: return "table_cell";
        case ElementType::CANVAS: return "canvas";
        case ElementType::EMBEDDED_VIEW: return "embedded_view";
        case ElementType::CUSTOM: return "custom";
        default: return "unknown";
    }
}

// Convert string to ElementType
inline ElementType string_to_element_type(const std::string& s) {
    std::string lower;
    for (char c : s) lower += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    if (lower == "window") return ElementType::WINDOW;
    if (lower == "button") return ElementType::BUTTON;
    if (lower == "text_field" || lower == "textfield" || lower == "input") return ElementType::TEXT_FIELD;
    if (lower == "text_area" || lower == "textarea") return ElementType::TEXT_AREA;
    if (lower == "checkbox" || lower == "check_box") return ElementType::CHECKBOX;
    if (lower == "radio_button" || lower == "radio") return ElementType::RADIO_BUTTON;
    if (lower == "dropdown" || lower == "drop_down") return ElementType::DROPDOWN;
    if (lower == "combo_box" || lower == "combobox" || lower == "select") return ElementType::COMBO_BOX;
    if (lower == "list_item") return ElementType::LIST_ITEM;
    if (lower == "list_view" || lower == "listview") return ElementType::LIST_VIEW;
    if (lower == "tree_item") return ElementType::TREE_ITEM;
    if (lower == "tree_view" || lower == "treeview") return ElementType::TREE_VIEW;
    if (lower == "menu_bar" || lower == "menubar") return ElementType::MENU_BAR;
    if (lower == "menu_item" || lower == "menuitem") return ElementType::MENU_ITEM;
    if (lower == "context_menu") return ElementType::CONTEXT_MENU;
    if (lower == "toolbar") return ElementType::TOOLBAR;
    if (lower == "toolbar_button") return ElementType::TOOLBAR_BUTTON;
    if (lower == "tab") return ElementType::TAB;
    if (lower == "tab_control") return ElementType::TAB_CONTROL;
    if (lower == "slider") return ElementType::SLIDER;
    if (lower == "spinner") return ElementType::SPINNER;
    if (lower == "progress_bar") return ElementType::PROGRESS_BAR;
    if (lower == "label") return ElementType::LABEL;
    if (lower == "link" || lower == "hyperlink") return ElementType::LINK;
    if (lower == "image") return ElementType::IMAGE;
    if (lower == "icon") return ElementType::ICON;
    if (lower == "panel") return ElementType::PANEL;
    if (lower == "group_box") return ElementType::GROUP_BOX;
    if (lower == "status_bar") return ElementType::STATUS_BAR;
    if (lower == "scrollbar" || lower == "scroll_bar") return ElementType::SCROLLBAR;
    if (lower == "separator" || lower == "divider") return ElementType::SEPARATOR;
    if (lower == "dialog" || lower == "modal") return ElementType::DIALOG;
    if (lower == "notification") return ElementType::NOTIFICATION;
    if (lower == "tooltip") return ElementType::TOOLTIP;
    if (lower == "switch" || lower == "toggle") return ElementType::SWITCH;
    if (lower == "search_bar") return ElementType::SEARCH_BAR;
    if (lower == "navigation_bar" || lower == "navbar") return ElementType::NAVIGATION_BAR;
    if (lower == "bottom_bar") return ElementType::BOTTOM_BAR;
    if (lower == "fab" || lower == "floating_action_button") return ElementType::FAB;
    if (lower == "card") return ElementType::CARD;
    if (lower == "chip") return ElementType::CHIP;
    if (lower == "snackbar") return ElementType::SNACKBAR;
    if (lower == "table") return ElementType::TABLE;
    if (lower == "table_row") return ElementType::TABLE_ROW;
    if (lower == "table_cell") return ElementType::TABLE_CELL;
    if (lower == "canvas") return ElementType::CANVAS;
    if (lower == "embedded_view") return ElementType::EMBEDDED_VIEW;
    if (lower == "custom") return ElementType::CUSTOM;
    return ElementType::UNKNOWN;
}

// Bounding box for UI elements
struct BoundingBox {
    int x = 0;
    int y = 0;
    int width = 0;
    int height = 0;

    int center_x() const { return x + width / 2; }
    int center_y() const { return y + height / 2; }
    int right() const { return x + width; }
    int bottom() const { return y + height; }

    bool contains(int px, int py) const {
        return px >= x && px < x + width && py >= y && py < y + height;
    }

    bool overlaps(const BoundingBox& other) const {
        return !(right() <= other.x || other.right() <= x ||
                 bottom() <= other.y || other.bottom() <= y);
    }

    int area() const { return width * height; }
};

// UIElement - represents any UI control in any application
struct UIElement {
    std::string id;              // Unique element identifier
    std::string parent_id;       // Parent element ID (for hierarchy)
    std::string window_id;       // Window this element belongs to
    ElementType type = ElementType::UNKNOWN;
    std::string type_name;       // Original type name from platform
    std::string text;            // Visible text/label
    std::string name;            // Internal name (automation ID)
    std::string description;     // Accessibility description
    std::string help_text;       // Help/tooltip text
    BoundingBox bounds;          // Screen coordinates
    bool enabled = true;
    bool visible = true;
    bool focused = false;
    bool selected = false;
    bool checked = false;
    std::string process_name;    // Application process name
    int process_id = 0;          // OS process ID
    int z_order = 0;             // Z-order (stacking)
    std::map<std::string, std::string> attributes; // Platform-specific attributes

    // Convenience
    std::string type_string() const { return element_type_to_string(type); }

    bool is_clickable() const {
        return type == ElementType::BUTTON ||
               type == ElementType::TOOLBAR_BUTTON ||
               type == ElementType::MENU_ITEM ||
               type == ElementType::CHECKBOX ||
               type == ElementType::RADIO_BUTTON ||
               type == ElementType::LINK ||
               type == ElementType::TAB ||
               type == ElementType::LIST_ITEM ||
               type == ElementType::TREE_ITEM ||
               type == ElementType::FAB ||
               type == ElementType::SWITCH ||
               type == ElementType::CHIP ||
               type == ElementType::ICON;
    }

    bool is_container() const {
        return type == ElementType::WINDOW ||
               type == ElementType::PANEL ||
               type == ElementType::GROUP_BOX ||
               type == ElementType::DIALOG ||
               type == ElementType::TAB_CONTROL ||
               type == ElementType::MENU_BAR ||
               type == ElementType::TOOLBAR ||
               type == ElementType::LIST_VIEW ||
               type == ElementType::TREE_VIEW ||
               type == ElementType::TABLE ||
               type == ElementType::CARD ||
               type == ElementType::NAVIGATION_BAR;
    }

    bool is_text_input() const {
        return type == ElementType::TEXT_FIELD ||
               type == ElementType::TEXT_AREA ||
               type == ElementType::SEARCH_BAR ||
               type == ElementType::COMBO_BOX;
    }

    // JSON serialization
    std::string to_json(int indent = 0) const {
        std::ostringstream ss;
        std::string pad(indent * 2, ' ');
        ss << pad << "{";
        ss << "\"id\":\"" << escape_json(id) << "\",";
        ss << "\"parent_id\":\"" << escape_json(parent_id) << "\",";
        ss << "\"window_id\":\"" << escape_json(window_id) << "\",";
        ss << "\"type\":\"" << type_string() << "\",";
        ss << "\"type_name\":\"" << escape_json(type_name) << "\",";
        ss << "\"text\":\"" << escape_json(text) << "\",";
        ss << "\"name\":\"" << escape_json(name) << "\",";
        ss << "\"description\":\"" << escape_json(description) << "\",";
        ss << "\"help_text\":\"" << escape_json(help_text) << "\",";
        ss << "\"bounds\":{";
        ss << "\"x\":" << bounds.x << ",";
        ss << "\"y\":" << bounds.y << ",";
        ss << "\"width\":" << bounds.width << ",";
        ss << "\"height\":" << bounds.height << ",";
        ss << "\"center_x\":" << bounds.center_x() << ",";
        ss << "\"center_y\":" << bounds.center_y();
        ss << "},";
        ss << "\"enabled\":" << (enabled ? "true" : "false") << ",";
        ss << "\"visible\":" << (visible ? "true" : "false") << ",";
        ss << "\"focused\":" << (focused ? "true" : "false") << ",";
        ss << "\"selected\":" << (selected ? "true" : "false") << ",";
        ss << "\"checked\":" << (checked ? "true" : "false") << ",";
        ss << "\"clickable\":" << (is_clickable() ? "true" : "false") << ",";
        ss << "\"container\":" << (is_container() ? "true" : "false") << ",";
        ss << "\"text_input\":" << (is_text_input() ? "true" : "false") << ",";
        ss << "\"process_name\":\"" << escape_json(process_name) << "\",";
        ss << "\"process_id\":" << process_id << ",";
        ss << "\"z_order\":" << z_order;
        if (!attributes.empty()) {
            ss << ",\"attributes\":{";
            bool first = true;
            for (const auto& [k, v] : attributes) {
                if (!first) ss << ",";
                ss << "\"" << escape_json(k) << "\":\"" << escape_json(v) << "\"";
                first = false;
            }
            ss << "}";
        }
        ss << "}";
        return ss.str();
    }

private:
    static std::string escape_json(const std::string& s) {
        std::string result;
        for (char c : s) {
            switch (c) {
                case '"': result += "\\\""; break;
                case '\\': result += "\\\\"; break;
                case '\n': result += "\\n"; break;
                case '\r': result += "\\r"; break;
                case '\t': result += "\\t"; break;
                default:
                    if (static_cast<unsigned char>(c) < 0x20) {
                        char buf[8];
                        std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                        result += buf;
                    } else {
                        result += c;
                    }
            }
        }
        return result;
    }
};

// WindowInfo - represents an open window/application
struct WindowInfo {
    std::string id;
    std::string title;
    std::string process_name;
    int process_id = 0;
    BoundingBox bounds;
    bool is_visible = true;
    bool is_focused = false;
    bool is_minimized = false;
    bool is_maximized = false;
    int element_count = 0;
    std::string platform;  // "windows", "linux", "macos", "android", "ios"

    std::string to_json(int indent = 0) const {
        std::ostringstream ss;
        std::string pad(indent * 2, ' ');
        ss << pad << "{";
        ss << "\"id\":\"" << id << "\",";
        ss << "\"title\":\"" << escape_json_str(title) << "\",";
        ss << "\"process_name\":\"" << escape_json_str(process_name) << "\",";
        ss << "\"process_id\":" << process_id << ",";
        ss << "\"bounds\":{";
        ss << "\"x\":" << bounds.x << ",";
        ss << "\"y\":" << bounds.y << ",";
        ss << "\"width\":" << bounds.width << ",";
        ss << "\"height\":" << bounds.height;
        ss << "},";
        ss << "\"is_visible\":" << (is_visible ? "true" : "false") << ",";
        ss << "\"is_focused\":" << (is_focused ? "true" : "false") << ",";
        ss << "\"is_minimized\":" << (is_minimized ? "true" : "false") << ",";
        ss << "\"is_maximized\":" << (is_maximized ? "true" : "false") << ",";
        ss << "\"element_count\":" << element_count << ",";
        ss << "\"platform\":\"" << platform << "\"";
        ss << "}";
        return ss.str();
    }

private:
    static std::string escape_json_str(const std::string& s) {
        std::string result;
        for (char c : s) {
            switch (c) {
                case '"': result += "\\\""; break;
                case '\\': result += "\\\\"; break;
                case '\n': result += "\\n"; break;
                case '\r': result += "\\r"; break;
                case '\t': result += "\\t"; break;
                default:
                    if (static_cast<unsigned char>(c) < 0x20) {
                        char buf[8];
                        std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                        result += buf;
                    } else {
                        result += c;
                    }
            }
        }
        return result;
    }
};

// SearchResult - element with match score
struct ElementSearchResult {
    UIElement element;
    double score = 0.0;
    std::string match_reason;

    std::string to_json() const {
        std::ostringstream ss;
        ss << "{\"score\":" << std::fixed << std::setprecision(4) << score << ",";
        ss << "\"match_reason\":\"" << match_reason << "\",";
        ss << "\"element\":" << element.to_json();
        ss << "}";
        return ss.str();
    }
};

// ScreenInfo - represents a monitor/display
struct ScreenInfo {
    int id = 0;
    std::string name;
    BoundingBox bounds;         // Full screen bounds
    BoundingBox work_area;      // Usable area (excluding taskbar/dock)
    bool is_primary = false;
    int dpi_scale = 100;        // DPI scaling percentage (100 = 100%)
    int color_depth = 32;       // Bits per pixel

    std::string to_json() const {
        std::ostringstream ss;
        ss << "{\"id\":" << id << ",";
        ss << "\"name\":\"" << name << "\",";
        ss << "\"bounds\":{\"x\":" << bounds.x << ",\"y\":" << bounds.y
           << ",\"width\":" << bounds.width << ",\"height\":" << bounds.height << "},";
        ss << "\"work_area\":{\"x\":" << work_area.x << ",\"y\":" << work_area.y
           << ",\"width\":" << work_area.width << ",\"height\":" << work_area.height << "},";
        ss << "\"is_primary\":" << (is_primary ? "true" : "false") << ",";
        ss << "\"dpi_scale\":" << dpi_scale << ",";
        ss << "\"color_depth\":" << color_depth << "}";
        return ss.str();
    }
};

// ElementState - queryable state of an element
struct ElementState {
    std::string element_id;
    bool enabled = false;
    bool visible = false;
    bool focused = false;
    bool selected = false;
    bool checked = false;
    bool clickable = false;
    bool is_container = false;
    bool is_text_input = false;
    std::string current_value;   // Current text/value for inputs
    std::string current_text;    // Current displayed text

    std::string to_json() const {
        std::ostringstream ss;
        ss << "{\"element_id\":\"" << element_id << "\",";
        ss << "\"enabled\":" << (enabled ? "true" : "false") << ",";
        ss << "\"visible\":" << (visible ? "true" : "false") << ",";
        ss << "\"focused\":" << (focused ? "true" : "false") << ",";
        ss << "\"selected\":" << (selected ? "true" : "false") << ",";
        ss << "\"checked\":" << (checked ? "true" : "false") << ",";
        ss << "\"clickable\":" << (clickable ? "true" : "false") << ",";
        ss << "\"is_container\":" << (is_container ? "true" : "false") << ",";
        ss << "\"is_text_input\":" << (is_text_input ? "true" : "false") << ",";
        ss << "\"current_value\":\"" << current_value << "\",";
        ss << "\"current_text\":\"" << current_text << "\"}";
        return ss.str();
    }
};

// BatchSearchQuery - multiple search queries in one request
struct BatchSearchQuery {
    std::string text;
    std::string type_filter;
    std::string window_id;
    size_t top_k = 10;
};

// ShortcutMapping - cross-platform keyboard shortcut
struct ShortcutMapping {
    std::string name;           // e.g. "copy", "paste", "save"
    std::string description;
    int ctrl_or_cmd = 0;        // 1 = Ctrl (Win/Linux), 2 = Cmd (Mac)
    int key_code = 0;           // Virtual key code
    std::string key_name;       // Human-readable key name
    bool shift = false;
    bool alt = false;

    std::string to_json() const {
        std::ostringstream ss;
        ss << "{\"name\":\"" << name << "\",";
        ss << "\"description\":\"" << description << "\",";
        ss << "\"modifier\":\"" << (ctrl_or_cmd == 2 ? "cmd" : "ctrl") << "\",";
        ss << "\"key_code\":" << key_code << ",";
        ss << "\"key_name\":\"" << key_name << "\",";
        ss << "\"shift\":" << (shift ? "true" : "false") << ",";
        ss << "\"alt\":" << (alt ? "true" : "false") << "}";
        return ss.str();
    }
};

// ElementRegion - logical grouping of elements
struct ElementRegion {
    std::string name;
    std::string window_id;
    BoundingBox bounds;
    std::vector<std::string> element_ids;
    std::string region_type;    // "header", "sidebar", "content", "footer", "toolbar", "modal"

    std::string to_json() const {
        std::ostringstream ss;
        ss << "{\"name\":\"" << name << "\",";
        ss << "\"window_id\":\"" << window_id << "\",";
        ss << "\"bounds\":{\"x\":" << bounds.x << ",\"y\":" << bounds.y
           << ",\"width\":" << bounds.width << ",\"height\":" << bounds.height << "},";
        ss << "\"region_type\":\"" << region_type << "\",";
        ss << "\"element_ids\":[";
        for (size_t i = 0; i < element_ids.size(); i++) {
            if (i > 0) ss << ",";
            ss << "\"" << element_ids[i] << "\"";
        }
        ss << "]}";
        return ss.str();
    }
};

} // namespace uilocator
