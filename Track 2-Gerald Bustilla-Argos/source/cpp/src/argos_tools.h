#pragma once
#include <string>
#include <vector>
#include <functional>

// Argos Tools — unified interface to all C++ AI tool libraries.
// Gives Argos built-in capabilities for file search, browser automation,
// screen reading, and UI element location — no external dependencies needed.

namespace argos_tools {

// ── AI Search (RAG-style file indexing & retrieval) ──

// Index a directory: scan files, index text content (TF-IDF), fingerprint images
std::string index_directory(const std::string& path, bool include_hidden = false);

// Search indexed text content with cosine similarity ranking
std::string search_text(const std::string& path, const std::string& query, size_t top_k = 10);

// Search for files by filename pattern
std::string search_filename(const std::string& path, const std::string& pattern, size_t top_k = 50);

// Full map: complete JSON index of files + content for AI consumption
std::string full_map(const std::string& path, bool include_hidden = false);

// Get statistics about an indexed directory
std::string stats(const std::string& path, bool include_hidden = false);

// ── Browser Tool ──

// Navigate to a URL
std::string browser_navigate(const std::string& url);

// Get current page content (text)
std::string browser_get_content();

// Get current page title
std::string browser_get_title();

// Get current URL
std::string browser_get_url();

// Search for elements by text
std::string browser_find_elements(const std::string& text);

// Click an element by ID
std::string browser_click(const std::string& element_id);

// Type text into an element
std::string browser_type(const std::string& element_id, const std::string& text);

// Take a screenshot of the browser
std::string browser_screenshot(bool full_page = false);

// Get all links on the page
std::string browser_get_links();

// Summarize page content
std::string browser_summarize();

// Search on YouTube (opens search results in browser)
std::string browser_search(const std::string& query);

// Click on text visible on screen (uses UI automation)
std::string browser_click_text(const std::string& text);

// Type text into the currently focused element
std::string browser_type_active(const std::string& text);

// Press a keyboard key (enter, tab, escape, etc.)
std::string browser_press_key(const std::string& key);

// ── Computer Use Tools (direct mouse & keyboard control) ──

std::string mouse_click(int x, int y);
std::string mouse_right_click(int x, int y);
std::string mouse_double_click(int x, int y);
std::string mouse_move(int x, int y);
std::string keyboard_type(const std::string& text);
std::string keyboard_key(const std::string& key);
std::string keyboard_hotkey(const std::string& keys);

// ── Screen Context ──

// List all open application windows
std::string screen_list_apps();

// Get the active/focused application
std::string screen_get_active_app();

// Capture the entire screen
std::string screen_capture(const std::string& output_path = "");

// OCR: extract text from the screen
std::string screen_ocr();

// Get user context assessment (what user is doing)
std::string screen_get_user_context();

// Search for content on screen
std::string screen_search_content(const std::string& query);

// Get app summary (categories of open apps)
std::string screen_app_summary();

// ── UI Locator ──

// List all open windows
std::string ui_list_windows();

// Get all UI elements in a window
std::string ui_get_elements(const std::string& window_id = "");

// Search for UI elements by text
std::string ui_search_by_text(const std::string& query, const std::string& window_id = "");

// Search for clickable elements (buttons, links)
std::string ui_search_clickable(const std::string& text_filter = "", const std::string& window_id = "");

// Click at coordinates
std::string ui_click_at(int x, int y);

// Click an element by ID
std::string ui_click_element(const std::string& element_id);

// Type text into focused element
std::string ui_type_text(const std::string& text);

// Get element state
std::string ui_get_element_state(const std::string& element_id);

// Focus a window
std::string ui_focus_window(const std::string& window_id);

// Close a window
std::string ui_close_window(const std::string& window_id);

// Export full element map as JSON
std::string ui_export_map();

// ── RAG (Retrieval-Augmented Generation) — Modern Hybrid Pipeline ──

// Modern RAG pipeline with:
// - Hybrid search: TF-IDF cosine similarity + BM25 fused via Reciprocal Rank Fusion (RRF)
// - Hierarchical chunking: returns parent context (larger window) around child chunk matches
// - Contextual chunking: prepends file path and language context to each chunk
// - Lightweight reranker: query-chunk term overlap scoring for precision boost
// - Persistent index: saves/loads index to disk for fast subsequent queries
// Returns clean text snippets (not JSON) suitable for injecting into AI context.
std::string rag_search(const std::string& query, const std::string& dir_path = "", size_t top_k = 5);

// RAG with persistent memory — saves conversation + index to SQLite
std::string rag_search_with_memory(const std::string& query, const std::string& dir_path = "", size_t top_k = 5);

// SQLite memory management
bool rag_memory_init(const std::string& db_path = "");
bool rag_memory_save_conversation(const std::string& role, const std::string& content);
std::string rag_memory_load_conversation(size_t max_messages = 20);
bool rag_memory_clear();

// ── RAG Manual Sync — user-controlled folder indexing ──
// RAG no longer auto-indexes the working directory. The user must explicitly
// sync one or more of: Desktop, Documents, Downloads, Music, Videos from Settings.
// If nothing is synced, RAG is skipped entirely in the chat pipeline (no errors).

struct RagFolderInfo {
    std::string label;   // "Desktop", "Documents", "Downloads", "Music", "Videos"
    std::string path;    // Full path on disk
    bool synced = false; // Whether this folder has been indexed
    int file_count = 0;  // Number of files indexed (after sync)
};

// Get the list of available folders (Desktop/Documents/Downloads/Music/Videos)
// with their current sync status.
std::vector<RagFolderInfo> rag_get_available_folders();

// Synchronously index one folder by label ("Desktop", "Documents", etc.).
// Calls progress_cb(percent 0-100) periodically as files are processed.
// Safe to call from a background thread. Returns true on success.
bool rag_sync_folder(const std::string& label, const std::string& path,
                      std::function<void(int)> progress_cb = nullptr);

// Remove a previously synced folder from the RAG index.
bool rag_unsync_folder(const std::string& label);

// Clear all synced folders and their indexed data.
void rag_clear_sync();

// True if at least one folder has been synced (RAG is usable).
bool rag_is_synced();

// True while a sync operation is currently running.
bool rag_is_syncing();

// ── Tool Dispatch ──

// Dispatch a tool command string (e.g. "search_files C:\path query")
// Returns JSON result string
std::string dispatch_tool(const std::string& tool_name, const std::string& args);

} // namespace argos_tools
