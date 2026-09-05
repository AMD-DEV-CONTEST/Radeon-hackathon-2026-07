#pragma once

#include "ui_element.h"
#include <functional>

namespace uilocator {

// Platform identifiers
enum class Platform {
    WINDOWS,
    LINUX,
    MACOS,
    ANDROID,
    IOS,
    SIMULATION  // For testing without real GUI
};

// Get current platform
Platform get_current_platform();
std::string platform_to_string(Platform p);

// ===== Core API =====

// List all open windows (across all platforms)
std::vector<WindowInfo> list_windows();

// Get all UI elements in a specific window
std::vector<UIElement> get_elements(const std::string& window_id);

// Get all UI elements across all windows
std::vector<UIElement> get_all_elements();

// Get a specific element by ID
UIElement get_element(const std::string& element_id);

// Get the currently focused element
UIElement get_focused_element();

// Get the currently focused window
WindowInfo get_focused_window();

// ===== Search API =====

// Search for elements by text label (case-insensitive substring match)
std::vector<ElementSearchResult> search_by_text(const std::string& query, const std::string& window_id = "");

// Search for elements by type
std::vector<ElementSearchResult> search_by_type(ElementType type, const std::string& window_id = "");

// Search for elements by type string
std::vector<ElementSearchResult> search_by_type_string(const std::string& type_str, const std::string& window_id = "");

// Universal search: search by text and/or type, with scoring
std::vector<ElementSearchResult> search_elements(const std::string& query, const std::string& type_filter = "", const std::string& window_id = "", size_t top_k = 50);

// Search for clickable elements (buttons, links, menu items)
std::vector<ElementSearchResult> search_clickable(const std::string& text_filter = "", const std::string& window_id = "");

// Search for text input elements
std::vector<ElementSearchResult> search_text_inputs(const std::string& text_filter = "", const std::string& window_id = "");

// Find element at specific screen coordinates
UIElement find_element_at(int x, int y);

// Find all elements containing a point
std::vector<UIElement> find_elements_at(int x, int y);

// ===== Hierarchy API =====

// Get children of an element
std::vector<UIElement> get_children(const std::string& element_id);

// Get parent of an element
UIElement get_parent(const std::string& element_id);

// Get full element tree (element + all descendants)
std::vector<UIElement> get_element_tree(const std::string& element_id);

// ===== Action API =====

// Click at specific coordinates
bool click_at(int x, int y);

// Click an element by ID
bool click_element(const std::string& element_id);

// Double-click at coordinates
bool double_click_at(int x, int y);

// Right-click at coordinates
bool right_click_at(int x, int y);

// Type text into a focused element
bool type_text(const std::string& text);

// Press a key (virtual key code)
bool press_key(int key_code);

// ===== Simulation API (for testing) =====

// Enable simulation mode with mock windows and elements
void enable_simulation_mode();

// Disable simulation mode
void disable_simulation_mode();

// Check if simulation mode is active
bool is_simulation_mode();

// Register a simulated window with elements
void sim_add_window(const WindowInfo& window, const std::vector<UIElement>& elements);

// Clear all simulated data
void sim_clear();

// Get simulation statistics
size_t sim_window_count();
size_t sim_element_count();

// ===== Utility Functions =====

// Fuzzy string matching (Levenshtein distance based)
double fuzzy_match(const std::string& a, const std::string& b);

// Case-insensitive string contains
bool contains_ci(const std::string& haystack, const std::string& needle);

// JSON serialization helpers
std::string windows_to_json(const std::vector<WindowInfo>& windows);
std::string elements_to_json(const std::vector<UIElement>& elements);
std::string search_results_to_json(const std::vector<ElementSearchResult>& results);
std::string element_to_json(const UIElement& element);
std::string window_to_json(const WindowInfo& window);

// ===== Multi-Monitor API =====

// Get all monitors/screens
std::vector<ScreenInfo> get_screens();

// Get the primary screen
ScreenInfo get_primary_screen();

// Get the screen at specific coordinates
ScreenInfo get_screen_at(int x, int y);

// Get screen containing a specific window
ScreenInfo get_screen_for_window(const std::string& window_id);

// JSON serialization for screens
std::string screens_to_json(const std::vector<ScreenInfo>& screens);

// ===== Element State API =====

// Get the full state of an element
ElementState get_element_state(const std::string& element_id);

// Check if element is enabled
bool is_element_enabled(const std::string& element_id);

// Check if element is visible
bool is_element_visible(const std::string& element_id);

// Check if element is checked
bool is_element_checked(const std::string& element_id);

// Check if element is focused
bool is_element_focused(const std::string& element_id);

// Get current text/value of an element
std::string get_element_value(const std::string& element_id);

// ===== Advanced Actions API =====

// Scroll at coordinates (dx, dy = scroll direction)
bool scroll_at(int x, int y, int dx, int dy);

// Scroll within an element
bool scroll_element(const std::string& element_id, int dx, int dy);

// Hover at coordinates
bool hover_at(int x, int y);

// Hover over an element
bool hover_element(const std::string& element_id);

// Drag from one point to another
bool drag(int from_x, int from_y, int to_x, int to_y);

// Drag an element to a target position
bool drag_element_to(const std::string& element_id, int to_x, int to_y);

// Send a keyboard shortcut (cross-platform)
bool send_shortcut(const std::string& shortcut_name);

// Send a custom key combination
bool send_key_combination(int ctrl_or_cmd, int key_code, bool shift, bool alt);

// ===== Wait/Poll API =====

// Wait for an element to appear (returns element if found, empty if timeout)
UIElement wait_for_element(const std::string& query, int timeout_ms = 5000,
                           const std::string& type_filter = "", const std::string& window_id = "");

// Wait for a window to appear
WindowInfo wait_for_window(const std::string& title_contains, int timeout_ms = 5000);

// Wait for element to be enabled
bool wait_for_element_enabled(const std::string& element_id, int timeout_ms = 5000);

// Wait for element to be visible
bool wait_for_element_visible(const std::string& element_id, int timeout_ms = 5000);

// ===== Element Path / Selector API =====

// Find element by path (e.g. "window>panel>toolbar>Save")
std::vector<UIElement> find_by_path(const std::string& path);

// Get the path of an element (e.g. "sim_win_editor>elem_toolbar>elem_tb_2")
std::string get_element_path(const std::string& element_id);

// ===== Batch Search API =====

// Search multiple queries at once
std::vector<std::vector<ElementSearchResult>> batch_search(const std::vector<BatchSearchQuery>& queries);

// ===== Window Management API =====

// Focus a window
bool focus_window(const std::string& window_id);

// Minimize a window
bool minimize_window(const std::string& window_id);

// Maximize a window
bool maximize_window(const std::string& window_id);

// Restore a window (from minimized/maximized)
bool restore_window(const std::string& window_id);

// Close a window
bool close_window(const std::string& window_id);

// Move a window to new position
bool move_window(const std::string& window_id, int x, int y);

// Resize a window
bool resize_window(const std::string& window_id, int width, int height);

// ===== Nearest Element API =====

// Find the nearest clickable element to a point
UIElement find_nearest_clickable(int x, int y, int max_distance = 200);

// Find the nearest element of a specific type to a point
UIElement find_nearest_by_type(int x, int y, ElementType type, int max_distance = 200);

// Find the nearest element with matching text to a point
UIElement find_nearest_by_text(int x, int y, const std::string& text, int max_distance = 200);

// Get distance between two points
double distance(int x1, int y1, int x2, int y2);

// ===== Export/Import API =====

// Export full element map to JSON string
std::string export_element_map();

// Import element map from JSON string (returns number of elements loaded)
size_t import_element_map(const std::string& json);

// Save element map to file
bool save_element_map(const std::string& filepath);

// Load element map from file
bool load_element_map(const std::string& filepath);

// ===== Keyboard Shortcuts API =====

// Get all known keyboard shortcuts
std::vector<ShortcutMapping> get_all_shortcuts();

// Get a specific shortcut by name
ShortcutMapping get_shortcut(const std::string& name);

// Get shortcuts as JSON
std::string shortcuts_to_json();

// ===== Element Regions API =====

// Detect logical regions in a window
std::vector<ElementRegion> detect_regions(const std::string& window_id);

// Get elements in a specific region
std::vector<UIElement> get_elements_in_region(const std::string& window_id, const std::string& region_type);

// Get regions as JSON
std::string regions_to_json(const std::vector<ElementRegion>& regions);

// ===== Change Detection API =====

// Snapshot current element state (for later comparison)
std::string snapshot_elements();

// Compare two snapshots (returns list of added/removed/changed element IDs)
struct ElementChange {
    std::string element_id;
    std::string change_type;  // "added", "removed", "text_changed", "state_changed"
    std::string old_value;
    std::string new_value;
};

std::vector<ElementChange> compare_snapshots(const std::string& old_snapshot, const std::string& new_snapshot);

// Get changes as JSON
std::string changes_to_json(const std::vector<ElementChange>& changes);

// ===== Highlight API =====

// Highlight an element (draw outline around it)
bool highlight_element(const std::string& element_id, int duration_ms = 2000);

// Highlight a region on screen
bool highlight_region(int x, int y, int width, int height, int duration_ms = 2000);

// Clear all highlights
bool clear_highlights();

} // namespace uilocator
