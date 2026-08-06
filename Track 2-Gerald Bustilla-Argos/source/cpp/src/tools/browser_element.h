#pragma once

#include <string>
#include <vector>
#include <map>
#include <sstream>
#include <iomanip>
#include <cstdint>
#include <algorithm>
#include <cmath>

namespace browsertool {

// ===== Browser Element Types =====
enum class BrowserElementType {
    unknown = 0,
    div, span, paragraph, heading1, heading2, heading3, heading4, heading5, heading6,
    link, image, button, input, textarea, select, option, form, label,
    table, table_row, table_cell, table_header,
    list_ordered, list_unordered, list_item,
    nav, header, footer, section, article, aside, main_,
    figure, figcaption, blockquote, code_block, pre,
    iframe, canvas, svg, video, audio,
    meta, title, script, style, br, hr,
    checkbox, radio, submit, password, email, search_input, file_input, hidden_input,
    breadcrumb, pagination, card, modal, tooltip, dropdown,
    tab_panel, tab_list, tab_tab, accordion, progress_bar, badge, alert,
    social_post, comment, review, rating, price, stock_chart
};

inline std::string element_type_to_string(BrowserElementType t) {
    switch (t) {
        case BrowserElementType::div: return "div";
        case BrowserElementType::span: return "span";
        case BrowserElementType::paragraph: return "paragraph";
        case BrowserElementType::heading1: return "h1";
        case BrowserElementType::heading2: return "h2";
        case BrowserElementType::heading3: return "h3";
        case BrowserElementType::heading4: return "h4";
        case BrowserElementType::heading5: return "h5";
        case BrowserElementType::heading6: return "h6";
        case BrowserElementType::link: return "link";
        case BrowserElementType::image: return "image";
        case BrowserElementType::button: return "button";
        case BrowserElementType::input: return "input";
        case BrowserElementType::textarea: return "textarea";
        case BrowserElementType::select: return "select";
        case BrowserElementType::option: return "option";
        case BrowserElementType::form: return "form";
        case BrowserElementType::label: return "label";
        case BrowserElementType::table: return "table";
        case BrowserElementType::table_row: return "tr";
        case BrowserElementType::table_cell: return "td";
        case BrowserElementType::table_header: return "th";
        case BrowserElementType::list_ordered: return "ol";
        case BrowserElementType::list_unordered: return "ul";
        case BrowserElementType::list_item: return "li";
        case BrowserElementType::nav: return "nav";
        case BrowserElementType::header: return "header";
        case BrowserElementType::footer: return "footer";
        case BrowserElementType::section: return "section";
        case BrowserElementType::article: return "article";
        case BrowserElementType::aside: return "aside";
        case BrowserElementType::main_: return "main";
        case BrowserElementType::figure: return "figure";
        case BrowserElementType::figcaption: return "figcaption";
        case BrowserElementType::blockquote: return "blockquote";
        case BrowserElementType::code_block: return "code";
        case BrowserElementType::pre: return "pre";
        case BrowserElementType::iframe: return "iframe";
        case BrowserElementType::canvas: return "canvas";
        case BrowserElementType::svg: return "svg";
        case BrowserElementType::video: return "video";
        case BrowserElementType::audio: return "audio";
        case BrowserElementType::meta: return "meta";
        case BrowserElementType::title: return "title";
        case BrowserElementType::script: return "script";
        case BrowserElementType::style: return "style";
        case BrowserElementType::br: return "br";
        case BrowserElementType::hr: return "hr";
        case BrowserElementType::checkbox: return "checkbox";
        case BrowserElementType::radio: return "radio";
        case BrowserElementType::submit: return "submit";
        case BrowserElementType::password: return "password";
        case BrowserElementType::email: return "email";
        case BrowserElementType::search_input: return "search_input";
        case BrowserElementType::file_input: return "file_input";
        case BrowserElementType::hidden_input: return "hidden_input";
        case BrowserElementType::breadcrumb: return "breadcrumb";
        case BrowserElementType::pagination: return "pagination";
        case BrowserElementType::card: return "card";
        case BrowserElementType::modal: return "modal";
        case BrowserElementType::tooltip: return "tooltip";
        case BrowserElementType::dropdown: return "dropdown";
        case BrowserElementType::tab_panel: return "tab_panel";
        case BrowserElementType::tab_list: return "tab_list";
        case BrowserElementType::tab_tab: return "tab_tab";
        case BrowserElementType::accordion: return "accordion";
        case BrowserElementType::progress_bar: return "progress_bar";
        case BrowserElementType::badge: return "badge";
        case BrowserElementType::alert: return "alert";
        case BrowserElementType::social_post: return "social_post";
        case BrowserElementType::comment: return "comment";
        case BrowserElementType::review: return "review";
        case BrowserElementType::rating: return "rating";
        case BrowserElementType::price: return "price";
        case BrowserElementType::stock_chart: return "stock_chart";
        default: return "unknown";
    }
}

inline BrowserElementType string_to_element_type(const std::string& s) {
    if (s == "div") return BrowserElementType::div;
    if (s == "span") return BrowserElementType::span;
    if (s == "paragraph" || s == "p") return BrowserElementType::paragraph;
    if (s == "h1") return BrowserElementType::heading1;
    if (s == "h2") return BrowserElementType::heading2;
    if (s == "h3") return BrowserElementType::heading3;
    if (s == "h4") return BrowserElementType::heading4;
    if (s == "h5") return BrowserElementType::heading5;
    if (s == "h6") return BrowserElementType::heading6;
    if (s == "link" || s == "a") return BrowserElementType::link;
    if (s == "image" || s == "img") return BrowserElementType::image;
    if (s == "button") return BrowserElementType::button;
    if (s == "input") return BrowserElementType::input;
    if (s == "textarea") return BrowserElementType::textarea;
    if (s == "select") return BrowserElementType::select;
    if (s == "option") return BrowserElementType::option;
    if (s == "form") return BrowserElementType::form;
    if (s == "label") return BrowserElementType::label;
    if (s == "table") return BrowserElementType::table;
    if (s == "tr") return BrowserElementType::table_row;
    if (s == "td") return BrowserElementType::table_cell;
    if (s == "th") return BrowserElementType::table_header;
    if (s == "ol") return BrowserElementType::list_ordered;
    if (s == "ul") return BrowserElementType::list_unordered;
    if (s == "li") return BrowserElementType::list_item;
    if (s == "nav") return BrowserElementType::nav;
    if (s == "header") return BrowserElementType::header;
    if (s == "footer") return BrowserElementType::footer;
    if (s == "section") return BrowserElementType::section;
    if (s == "article") return BrowserElementType::article;
    if (s == "aside") return BrowserElementType::aside;
    if (s == "main") return BrowserElementType::main_;
    if (s == "checkbox") return BrowserElementType::checkbox;
    if (s == "radio") return BrowserElementType::radio;
    if (s == "submit") return BrowserElementType::submit;
    if (s == "password") return BrowserElementType::password;
    if (s == "email") return BrowserElementType::email;
    if (s == "search_input") return BrowserElementType::search_input;
    if (s == "card") return BrowserElementType::card;
    if (s == "modal") return BrowserElementType::modal;
    if (s == "social_post") return BrowserElementType::social_post;
    if (s == "comment") return BrowserElementType::comment;
    if (s == "review") return BrowserElementType::review;
    if (s == "rating") return BrowserElementType::rating;
    if (s == "price") return BrowserElementType::price;
    return BrowserElementType::unknown;
}

// ===== Bounding Box =====
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
};

// ===== Browser Element =====
struct BrowserElement {
    std::string id;
    std::string tag;                    // HTML tag name
    BrowserElementType type = BrowserElementType::unknown;
    std::string text;                   // Visible text content
    std::string html;                   // Inner HTML (optional)
    std::string href;                   // For links
    std::string src;                    // For images/media
    std::string alt;                    // Alt text for images
    std::string name;                   // Form element name
    std::string value;                  // Form element value
    std::string placeholder;            // Input placeholder
    std::string role;                   // ARIA role
    std::string aria_label;             // ARIA label
    std::string css_class;              // CSS class
    std::string xpath;                  // XPath selector
    std::string parent_id;              // Parent element ID
    std::vector<std::string> child_ids; // Child element IDs
    BoundingBox bounds;
    bool visible = true;
    bool enabled = true;
    bool checked = false;
    bool selected = false;
    bool focused = false;
    bool clickable = false;
    bool is_container = false;
    bool is_input = false;
    bool is_link = false;
    std::map<std::string, std::string> attributes; // All attributes
    int scroll_x = 0;
    int scroll_y = 0;
    int z_index = 0;

    std::string type_string() const { return element_type_to_string(type); }

    std::string to_json() const {
        std::ostringstream ss;
        ss << "{\"id\":\"" << escape_json(id) << "\",";
        ss << "\"tag\":\"" << escape_json(tag) << "\",";
        ss << "\"type\":\"" << type_string() << "\",";
        ss << "\"text\":\"" << escape_json(text) << "\",";
        if (!href.empty()) ss << "\"href\":\"" << escape_json(href) << "\",";
        if (!src.empty()) ss << "\"src\":\"" << escape_json(src) << "\",";
        if (!alt.empty()) ss << "\"alt\":\"" << escape_json(alt) << "\",";
        if (!name.empty()) ss << "\"name\":\"" << escape_json(name) << "\",";
        if (!value.empty()) ss << "\"value\":\"" << escape_json(value) << "\",";
        if (!placeholder.empty()) ss << "\"placeholder\":\"" << escape_json(placeholder) << "\",";
        if (!role.empty()) ss << "\"role\":\"" << escape_json(role) << "\",";
        if (!aria_label.empty()) ss << "\"aria_label\":\"" << escape_json(aria_label) << "\",";
        if (!css_class.empty()) ss << "\"class\":\"" << escape_json(css_class) << "\",";
        if (!xpath.empty()) ss << "\"xpath\":\"" << escape_json(xpath) << "\",";
        if (!parent_id.empty()) ss << "\"parent_id\":\"" << escape_json(parent_id) << "\",";
        ss << "\"bounds\":{\"x\":" << bounds.x << ",\"y\":" << bounds.y
           << ",\"width\":" << bounds.width << ",\"height\":" << bounds.height
           << ",\"center_x\":" << bounds.center_x()
           << ",\"center_y\":" << bounds.center_y() << "},";
        ss << "\"visible\":" << (visible ? "true" : "false") << ",";
        ss << "\"enabled\":" << (enabled ? "true" : "false") << ",";
        ss << "\"checked\":" << (checked ? "true" : "false") << ",";
        ss << "\"selected\":" << (selected ? "true" : "false") << ",";
        ss << "\"focused\":" << (focused ? "true" : "false") << ",";
        ss << "\"clickable\":" << (clickable ? "true" : "false") << ",";
        ss << "\"is_container\":" << (is_container ? "true" : "false") << ",";
        ss << "\"is_input\":" << (is_input ? "true" : "false") << ",";
        ss << "\"is_link\":" << (is_link ? "true" : "false");
        if (!child_ids.empty()) {
            ss << ",\"child_ids\":[";
            for (size_t i = 0; i < child_ids.size(); i++) {
                if (i > 0) ss << ",";
                ss << "\"" << escape_json(child_ids[i]) << "\"";
            }
            ss << "]";
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

// ===== Page Info =====
struct PageInfo {
    std::string url;
    std::string title;
    std::string domain;
    std::string protocol;
    std::string path;
    std::string content_text;           // Full visible text content
    std::string content_html;           // Full HTML
    std::string meta_description;
    std::string meta_keywords;
    std::string meta_author;
    std::string language;
    std::string charset;
    int status_code = 200;
    bool loading = false;
    bool secure = true;                 // HTTPS
    int scroll_x = 0;
    int scroll_y = 0;
    int scroll_max_x = 0;
    int scroll_max_y = 0;
    int page_width = 1920;
    int page_height = 1080;
    int viewport_width = 1920;
    int viewport_height = 1080;
    std::string favicon_url;
    std::string canonical_url;
    std::vector<std::string> breadcrumbs;
    std::string page_type;              // "article", "search_results", "product", "login", "documentation", "social", "table", "news"

    std::string to_json() const {
        std::ostringstream ss;
        ss << "{\"url\":\"" << escape_json(url) << "\",";
        ss << "\"title\":\"" << escape_json(title) << "\",";
        ss << "\"domain\":\"" << escape_json(domain) << "\",";
        ss << "\"protocol\":\"" << escape_json(protocol) << "\",";
        ss << "\"path\":\"" << escape_json(path) << "\",";
        ss << "\"meta_description\":\"" << escape_json(meta_description) << "\",";
        ss << "\"meta_keywords\":\"" << escape_json(meta_keywords) << "\",";
        ss << "\"meta_author\":\"" << escape_json(meta_author) << "\",";
        ss << "\"language\":\"" << escape_json(language) << "\",";
        ss << "\"charset\":\"" << escape_json(charset) << "\",";
        ss << "\"status_code\":" << status_code << ",";
        ss << "\"loading\":" << (loading ? "true" : "false") << ",";
        ss << "\"secure\":" << (secure ? "true" : "false") << ",";
        ss << "\"scroll_x\":" << scroll_x << ",";
        ss << "\"scroll_y\":" << scroll_y << ",";
        ss << "\"scroll_max_x\":" << scroll_max_x << ",";
        ss << "\"scroll_max_y\":" << scroll_max_y << ",";
        ss << "\"page_width\":" << page_width << ",";
        ss << "\"page_height\":" << page_height << ",";
        ss << "\"viewport_width\":" << viewport_width << ",";
        ss << "\"viewport_height\":" << viewport_height << ",";
        ss << "\"favicon_url\":\"" << escape_json(favicon_url) << "\",";
        ss << "\"canonical_url\":\"" << escape_json(canonical_url) << "\",";
        ss << "\"page_type\":\"" << escape_json(page_type) << "\",";
        ss << "\"content_length\":" << content_text.size() << ",";
        ss << "\"breadcrumbs\":[";
        for (size_t i = 0; i < breadcrumbs.size(); i++) {
            if (i > 0) ss << ",";
            ss << "\"" << escape_json(breadcrumbs[i]) << "\"";
        }
        ss << "]}";
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

// ===== Tab Info =====
struct TabInfo {
    std::string id;
    std::string url;
    std::string title;
    bool active = false;
    std::string favicon;
    bool loading = false;

    std::string to_json() const {
        std::ostringstream ss;
        ss << "{\"id\":\"" << id << "\",";
        ss << "\"url\":\"" << title << "\",";
        ss << "\"title\":\"" << title << "\",";
        ss << "\"active\":" << (active ? "true" : "false") << ",";
        ss << "\"loading\":" << (loading ? "true" : "false") << "}";
        return ss.str();
    }
};

// ===== Content Search Result =====
struct ContentSearchResult {
    std::string text;                   // Matched text
    std::string element_id;             // Element containing the match
    std::string context_before;         // Text before match
    std::string context_after;          // Text after match
    int position = 0;                   // Character position in page content
    int line_number = 0;                // Line number in content
    double score = 0.0;
    std::string match_type;             // "exact", "fuzzy", "contains"
    BrowserElementType element_type = BrowserElementType::unknown;
    BoundingBox bounds;

    std::string to_json() const {
        std::ostringstream ss;
        ss << "{\"text\":\"" << escape_json(text) << "\",";
        ss << "\"element_id\":\"" << escape_json(element_id) << "\",";
        ss << "\"context_before\":\"" << escape_json(context_before) << "\",";
        ss << "\"context_after\":\"" << escape_json(context_after) << "\",";
        ss << "\"position\":" << position << ",";
        ss << "\"line_number\":" << line_number << ",";
        ss << "\"score\":" << std::fixed << std::setprecision(4) << score << ",";
        ss << "\"match_type\":\"" << match_type << "\",";
        ss << "\"element_type\":\"" << element_type_to_string(element_type) << "\"";
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

// ===== Screenshot Info =====
struct ScreenshotInfo {
    int width = 0;
    int height = 0;
    std::string format;                 // "png", "jpeg"
    std::string base64_data;
    std::string filepath;
    bool full_page = false;

    std::string to_json() const {
        std::ostringstream ss;
        ss << "{\"width\":" << width << ",";
        ss << "\"height\":" << height << ",";
        ss << "\"format\":\"" << format << "\",";
        ss << "\"full_page\":" << (full_page ? "true" : "false") << ",";
        ss << "\"data_length\":" << base64_data.size() << ",";
        ss << "\"filepath\":\"" << filepath << "\"}";
        return ss.str();
    }
};

// ===== Browser Info =====
struct BrowserInfo {
    std::string name;                   // "Chrome", "Edge", "Firefox"
    std::string version;
    std::string user_agent;
    std::string platform;
    bool headless = false;
    int tab_count = 0;

    std::string to_json() const {
        std::ostringstream ss;
        ss << "{\"name\":\"" << name << "\",";
        ss << "\"version\":\"" << version << "\",";
        ss << "\"user_agent\":\"" << user_agent << "\",";
        ss << "\"platform\":\"" << platform << "\",";
        ss << "\"headless\":" << (headless ? "true" : "false") << ",";
        ss << "\"tab_count\":" << tab_count << "}";
        return ss.str();
    }
};

// ===== Form Field =====
struct FormField {
    std::string name;
    std::string type;
    std::string label;
    std::string value;
    bool required = false;
    std::string placeholder;
    std::vector<std::string> options;   // For select elements

    std::string to_json() const {
        std::ostringstream ss;
        ss << "{\"name\":\"" << name << "\",";
        ss << "\"type\":\"" << type << "\",";
        ss << "\"label\":\"" << label << "\",";
        ss << "\"value\":\"" << value << "\",";
        ss << "\"required\":" << (required ? "true" : "false") << ",";
        ss << "\"placeholder\":\"" << placeholder << "\"";
        if (!options.empty()) {
            ss << ",\"options\":[";
            for (size_t i = 0; i < options.size(); i++) {
                if (i > 0) ss << ",";
                ss << "\"" << options[i] << "\"";
            }
            ss << "]";
        }
        ss << "}";
        return ss.str();
    }
};

// ===== Table Data =====
struct TableData {
    std::string id;
    std::string caption;
    std::vector<std::string> headers;
    std::vector<std::vector<std::string>> rows;

    std::string to_json() const {
        std::ostringstream ss;
        ss << "{\"id\":\"" << id << "\",";
        ss << "\"caption\":\"" << caption << "\",";
        ss << "\"headers\":[";
        for (size_t i = 0; i < headers.size(); i++) {
            if (i > 0) ss << ",";
            ss << "\"" << headers[i] << "\"";
        }
        ss << "],\"rows\":[";
        for (size_t i = 0; i < rows.size(); i++) {
            if (i > 0) ss << ",";
            ss << "[";
            for (size_t j = 0; j < rows[i].size(); j++) {
                if (j > 0) ss << ",";
                ss << "\"" << rows[i][j] << "\"";
            }
            ss << "]";
        }
        ss << "]}";
        return ss.str();
    }
};

} // namespace browsertool
