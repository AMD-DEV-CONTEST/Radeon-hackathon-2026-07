// screen_context.h - Screen Context Reader for AI
// Lets AI agents see what's on the user's screen, read content from any app,
// and assess what the user is currently doing.
#pragma once

#include <string>
#include <vector>
#include <map>
#include <functional>

#ifdef _WIN32
#include <windows.h>
#endif

// ===== Data Structures =====

struct TextRegion {
    std::string text;
    int x = 0;
    int y = 0;
    int width = 0;
    int height = 0;
    float confidence = 0.0f;
};

struct AppInfo {
    std::string window_id;
    std::string title;
    std::string process_name;
    int process_id = 0;
    int x = 0, y = 0, width = 0, height = 0;
    bool is_visible = true;
    bool is_focused = false;
    bool is_minimized = false;
    std::string app_category;  // "social_media", "browser", "editor", "email", "media_player", "ide", "terminal", "file_manager", "chat", "unknown"
    std::string platform;      // "windows", "android", "ios", "simulation"
};

struct ScreenContent {
    std::string timestamp;
    std::string active_window_id;
    std::string active_window_title;
    std::string active_process;
    std::vector<AppInfo> open_apps;
    std::vector<TextRegion> visible_text;
    std::string screen_image_path;
    int screen_width = 0;
    int screen_height = 0;
    std::string platform;
};

struct ContentBlock {
    std::string type;       // "post", "message", "article", "code", "email", "comment", "ad", "menu", "notification", "search_result", "video", "image_caption"
    std::string text;
    std::string source;     // Which app produced this content
    std::string author;     // Who wrote it (for social media / email)
    std::string timestamp;  // When it was posted
    int x = 0, y = 0, width = 0, height = 0;
    float relevance = 0.0f; // How relevant to the user's current focus
};

struct UserContext {
    std::string timestamp;
    std::string active_app;
    std::string active_app_category;
    std::string user_activity;    // "scrolling", "reading", "typing", "watching", "browsing", "coding", "idle"
    std::string current_focus;    // What the user is looking at / interacting with
    std::vector<ContentBlock> visible_content;
    std::vector<AppInfo> open_apps;
    std::string assessment;       // Natural language assessment of user situation
    std::vector<std::string> suggested_actions;  // What AI could help with
    std::string platform;
};

struct ScreenCaptureInfo {
    bool success = false;
    std::string file_path;
    int width = 0;
    int height = 0;
    std::string format;  // "bmp", "png"
    std::string error;
};

struct OcrResult {
    bool success = false;
    std::vector<TextRegion> regions;
    std::string full_text;
    std::string error;
};

struct RegionQuery {
    int x, y, width, height;
};

// ===== Platform Detection =====
enum class Platform {
    WINDOWS,
    LINUX,
    MACOS,
    ANDROID,
    IOS,
    SIMULATION
};

std::string platform_to_string(Platform p);
Platform get_current_platform();

// ===== Core API =====

// Simulation mode
void enable_simulation_mode();
bool is_simulation_mode();
void setup_simulation_data();

// App enumeration
std::vector<AppInfo> list_open_apps();
AppInfo get_active_app();

// Screen capture
ScreenCaptureInfo capture_screen(const std::string& output_path = "");
ScreenCaptureInfo capture_window(const std::string& window_id, const std::string& output_path = "");
ScreenCaptureInfo capture_region(int x, int y, int width, int height, const std::string& output_path = "");

// Text extraction
OcrResult ocr_screen();
OcrResult ocr_window(const std::string& window_id);
OcrResult ocr_region(int x, int y, int width, int height);
std::vector<TextRegion> extract_text_from_apps();

// Content analysis
std::vector<ContentBlock> extract_content_blocks(const std::string& window_id = "");
std::string classify_app(const std::string& title, const std::string& process_name);

// Context assessment
UserContext get_user_context();
UserContext assess_user_situation();

// Content search
struct ContentSearchResult {
    ContentBlock block;
    std::string match_context;
    int match_position = 0;
    float score = 0.0f;
};
std::vector<ContentSearchResult> search_content(const std::string& query, const std::string& window_id = "");

// App summary
struct AppSummary {
    int total_apps = 0;
    std::map<std::string, int> apps_by_category;
    std::string active_app_category;
    int focused_app_count = 0;
    int minimized_app_count = 0;
    std::string platform;
};
AppSummary get_app_summary();

// Screen content snapshot
ScreenContent get_screen_content();

// JSON serialization
std::string json_escape(const std::string& s);
std::string content_search_results_to_json(const std::vector<ContentSearchResult>& results);
std::string app_summary_to_json(const AppSummary& summary);
std::string app_info_to_json(const AppInfo& app);
std::string apps_to_json(const std::vector<AppInfo>& apps);
std::string screen_content_to_json(const ScreenContent& content);
std::string content_block_to_json(const ContentBlock& block);
std::string content_blocks_to_json(const std::vector<ContentBlock>& blocks);
std::string user_context_to_json(const UserContext& ctx);
std::string screen_capture_to_json(const ScreenCaptureInfo& info);
std::string ocr_result_to_json(const OcrResult& result);
std::string text_regions_to_json(const std::vector<TextRegion>& regions);

// Utility
std::string get_timestamp();
std::string to_lower(const std::string& s);
bool contains_ci(const std::string& haystack, const std::string& needle);

// ===== UI Automation (UIA) Integration =====
// Provides semantic screen reading: element types, states, control patterns
// 52x faster than OCR, returns structured data instead of raw text

struct UiaElementInfo {
    std::string element_id;          // Unique element ID
    std::string name;                // Element name/label
    std::string control_type;        // "button", "edit", "text", "menu", "combobox", "checkbox", "radio", "tab", "list", "listitem", "tree", "treeitem", "toolbar", "statusbar", "image", "hyperlink", "pane", "window", "custom"
    std::string localized_control_type;  // Human-readable type
    std::string automation_id;       // Automation ID (developer-set)
    std::string class_name;          // Window class name
    int x = 0, y = 0, width = 0, height = 0;
    bool is_enabled = true;          // Can the element be interacted with?
    bool is_visible = true;          // Is the element visible?
    bool is_focused = false;         // Does the element have keyboard focus?
    bool is_offscreen = false;       // Is the element scrolled off-screen?
    bool is_keyboard_focusable = false;  // Can receive keyboard focus?
    bool has_invoke_pattern = false;     // Can be clicked/invoked
    bool has_value_pattern = false;      // Has a value (text fields)
    bool has_toggle_pattern = false;     // Can be toggled (checkboxes)
    bool has_selection_pattern = false;  // Supports selection
    bool has_scroll_pattern = false;     // Supports scrolling
    std::string value;               // Current value (text content)
    std::string help_text;           // Help/description text
    int process_id = 0;
    std::string parent_id;           // Parent element ID
    std::vector<std::string> child_ids;  // Child element IDs
    int depth = 0;                   // Tree depth (0 = root)
};

struct UiaTreeResult {
    bool success = false;
    std::vector<UiaElementInfo> elements;  // Flat list of all elements
    std::string root_element_id;
    int total_elements = 0;
    int max_depth = 0;
    std::string error;
};

struct ElementStateInfo {
    std::string element_id;
    std::string name;
    std::string control_type;
    bool is_enabled = true;
    bool is_visible = true;
    bool is_focused = false;
    bool is_offscreen = false;
    bool is_keyboard_focusable = false;
    std::string value;
    std::string toggle_state;        // "on", "off", "indeterminate"
    std::string selection_state;     // "selected", "unselected"
    std::string expand_collapse_state;  // "expanded", "collapsed", "leaf"
    std::string error;
};

struct InteractiveElement {
    std::string element_id;
    std::string name;
    std::string control_type;
    int x = 0, y = 0, width = 0, height = 0;
    bool is_enabled = true;
    std::string action_type;         // "click", "type", "toggle", "select", "scroll", "expand"
    std::string value;
    std::string help_text;
};

struct ActionVerifyResult {
    bool success = false;
    bool state_changed = false;
    std::string before_state;
    std::string after_state;
    std::string error;
};

// UIA API functions
UiaTreeResult get_uia_tree(const std::string& window_id = "");
std::vector<UiaElementInfo> get_uia_elements(const std::string& window_id = "");
ElementStateInfo get_element_state(const std::string& element_id);
std::vector<InteractiveElement> get_interactive_elements(const std::string& window_id = "");
ActionVerifyResult verify_action(const std::string& element_id, const std::string& action);
std::vector<UiaElementInfo> find_elements_by_type(const std::string& control_type, const std::string& window_id = "");
std::vector<UiaElementInfo> find_elements_by_name(const std::string& name, const std::string& window_id = "");
std::vector<UiaElementInfo> get_focused_element_chain(const std::string& window_id = "");

// UIA JSON serialization
std::string uia_element_to_json(const UiaElementInfo& elem);
std::string uia_tree_to_json(const UiaTreeResult& tree);
std::string element_state_to_json(const ElementStateInfo& state);
std::string interactive_elements_to_json(const std::vector<InteractiveElement>& elements);
std::string action_verify_to_json(const ActionVerifyResult& result);
