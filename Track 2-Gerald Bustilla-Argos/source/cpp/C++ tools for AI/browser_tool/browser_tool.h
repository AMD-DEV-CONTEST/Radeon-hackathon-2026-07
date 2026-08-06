#pragma once

#include "browser_element.h"
#include <string>
#include <vector>
#include <functional>

namespace browsertool {

// ===== Platform Detection =====
enum class Platform { Windows, Linux, macOS, Android, iOS, Simulation };
Platform get_current_platform();
std::string platform_to_string(Platform p);

// ===== Simulation Mode =====
void enable_simulation_mode();
bool is_simulation_mode();
void setup_simulation_data();

// ===== Browser Info =====
BrowserInfo get_browser_info();

// ===== Navigation API =====
bool navigate(const std::string& url);
bool go_back();
bool go_forward();
bool refresh();
bool stop_loading();
std::string get_current_url();
std::string get_current_title();
bool wait_for_page_load(int timeout_ms = 10000);

// ===== Tab Management =====
std::string new_tab(const std::string& url = "");
bool close_tab(const std::string& tab_id);
bool switch_tab(const std::string& tab_id);
std::vector<TabInfo> list_tabs();
std::string get_active_tab_id();

// ===== Page Content API =====
PageInfo get_page_info();
std::string get_page_content();         // Full text content
std::string get_page_html();            // Full HTML
std::string get_page_title();
std::string get_page_text_by_element(const std::string& element_id);
std::string get_meta_description();
std::string get_meta_keywords();

// ===== Element Query API =====
std::vector<BrowserElement> get_all_elements();
std::vector<BrowserElement> get_elements_by_type(BrowserElementType type);
std::vector<BrowserElement> get_elements_by_tag(const std::string& tag);
BrowserElement get_element_by_id(const std::string& id);
std::vector<BrowserElement> get_links();
std::vector<BrowserElement> get_images();
std::vector<BrowserElement> get_buttons();
std::vector<BrowserElement> get_forms();
std::vector<BrowserElement> get_headings();
std::vector<BrowserElement> get_paragraphs();
std::vector<BrowserElement> get_inputs();
std::vector<BrowserElement> get_tables();
std::vector<BrowserElement> get_navigation();
std::vector<BrowserElement> get_element_children(const std::string& element_id);
BrowserElement get_element_parent(const std::string& element_id);

// ===== Content Search API =====
std::vector<ContentSearchResult> search_content(const std::string& query, int max_results = 50);
std::vector<ContentSearchResult> search_content_in_element(const std::string& element_id, const std::string& query);
ContentSearchResult find_first_text(const std::string& text);
std::vector<ContentSearchResult> find_all_text(const std::string& text);
BrowserElement find_element_by_text(const std::string& text);
std::vector<BrowserElement> find_elements_by_text(const std::string& text);
BrowserElement find_paragraph_by_text(const std::string& text);
BrowserElement find_heading_by_text(const std::string& text);
BrowserElement find_link_by_text(const std::string& text);
BrowserElement find_link_by_href(const std::string& href_partial);
BrowserElement find_button_by_text(const std::string& text);

// ===== Content Analysis API =====
std::string explain_content(const std::string& query);
std::string summarize_page(int max_sentences = 5);
std::string get_section_by_heading(const std::string& heading_text);
std::vector<std::string> get_all_headings();
std::vector<std::string> get_all_paragraphs();
std::string get_context_around_text(const std::string& text, int chars_before = 100, int chars_after = 100);
std::vector<ContentSearchResult> search_with_context(const std::string& query, int context_chars = 200);
std::string get_page_summary();

// ===== Scroll API =====
bool scroll_down(int pixels = 300);
bool scroll_up(int pixels = 300);
bool scroll_to(int x, int y);
bool scroll_to_element(const std::string& element_id);
bool scroll_to_top();
bool scroll_to_bottom();
int get_scroll_x();
int get_scroll_y();
int get_scroll_max_x();
int get_scroll_max_y();

// ===== Screenshot API =====
ScreenshotInfo take_screenshot(bool full_page = false);
ScreenshotInfo screenshot_element(const std::string& element_id);
ScreenshotInfo screenshot_region(int x, int y, int width, int height);
bool save_screenshot(const std::string& filepath, bool full_page = false);

// ===== Interaction API =====
bool click_element(const std::string& element_id);
bool click_element_at(int x, int y);
bool type_text(const std::string& element_id, const std::string& text);
bool type_text_into_active_element(const std::string& text);
bool press_key(const std::string& key);
bool select_option(const std::string& element_id, const std::string& value);
bool submit_form(const std::string& form_id);
bool clear_input(const std::string& element_id);
bool focus_element(const std::string& element_id);
bool hover_element(const std::string& element_id);

// ===== Wait API =====
bool wait_for_element(const std::string& selector, int timeout_ms = 5000);
bool wait_for_text(const std::string& text, int timeout_ms = 5000);
bool wait_for_navigation(int timeout_ms = 10000);

// ===== JavaScript API =====
std::string execute_javascript(const std::string& script);

// ===== Form Data API =====
std::vector<FormField> get_form_fields(const std::string& form_id);
bool fill_form(const std::string& form_id, const std::map<std::string, std::string>& values);

// ===== Table Data API =====
std::vector<TableData> get_tables_data();
TableData get_table_data(const std::string& table_id);

// ===== History API =====
std::vector<std::string> get_history();
bool clear_history();

// ===== Cookie API =====
std::string get_cookies();
bool set_cookie(const std::string& name, const std::string& value, const std::string& domain = "");
bool clear_cookies();

// ===== Export API =====
std::string export_page_data();
bool save_page_content(const std::string& filepath);

// ===== Utility Functions =====
double fuzzy_match(const std::string& a, const std::string& b);
bool contains_ci(const std::string& haystack, const std::string& needle);

// ===== JSON Serialization Helpers =====
std::string elements_to_json(const std::vector<BrowserElement>& elements);
std::string element_to_json(const BrowserElement& element);
std::string page_info_to_json(const PageInfo& info);
std::string tabs_to_json(const std::vector<TabInfo>& tabs);
std::string search_results_to_json(const std::vector<ContentSearchResult>& results);
std::string screenshot_to_json(const ScreenshotInfo& info);
std::string browser_info_to_json(const BrowserInfo& info);
std::string table_data_to_json(const std::vector<TableData>& tables);
std::string form_fields_to_json(const std::vector<FormField>& fields);

} // namespace browsertool
