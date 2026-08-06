#include "argos_tools.h"
#include "tools/search_engine.h"
#include "tools/json_writer.h"
#include "tools/browser_tool.h"
#include "tools/screen_context.h"
#include "tools/ui_locator.h"
#include "tools/computer_use_tool.h"
#include "../src_cross/whisper_wrapper.h"

#include <sstream>
#include <fstream>
#include <filesystem>
#include <windows.h>
#include <iomanip>
#include <unordered_set>
#include <algorithm>
#include <mutex>
#include <atomic>

namespace argos_tools {

namespace fs = std::filesystem;

// ── RAG Manual Sync State ──
// RAG is OFF by default. The user must explicitly sync a folder from Settings
// before any RAG search is performed. This avoids auto-indexing large/irrelevant
// directories on every chat message (which was slow and error-prone).
namespace {
    std::mutex g_ragMutex;
    std::vector<std::string> g_ragSyncedLabels;
    std::vector<std::string> g_ragSyncedPaths;
    std::vector<aisearch::ContentIndex> g_ragIndices;
    std::atomic<bool> g_ragSyncing{false};
}

std::string get_user_profile_dir() {
    char buf[MAX_PATH] = {};
    DWORD len = GetEnvironmentVariableA("USERPROFILE", buf, MAX_PATH);
    if (len == 0 || len >= MAX_PATH) return "";
    return std::string(buf);
}

std::vector<RagFolderInfo> rag_get_available_folders() {
    std::string home = get_user_profile_dir();
    std::vector<RagFolderInfo> folders = {
        {"Desktop",   home + "\\Desktop"},
        {"Documents", home + "\\Documents"},
        {"Downloads", home + "\\Downloads"},
        {"Music",     home + "\\Music"},
        {"Videos",    home + "\\Videos"},
    };

    std::lock_guard<std::mutex> lock(g_ragMutex);
    for (auto& f : folders) {
        for (size_t i = 0; i < g_ragSyncedLabels.size(); i++) {
            if (g_ragSyncedLabels[i] == f.label) {
                f.synced = true;
                f.file_count = static_cast<int>(
                    g_ragIndices[i].total_text_indexed + g_ragIndices[i].total_images_indexed);
                break;
            }
        }
    }
    return folders;
}

bool rag_sync_folder(const std::string& label, const std::string& path,
                      std::function<void(int)> progress_cb) {
    g_ragSyncing.store(true);
    try {
        if (path.empty() || !fs::exists(path)) {
            g_ragSyncing.store(false);
            if (progress_cb) progress_cb(-1); // signal error
            return false;
        }

        auto index = aisearch::index_directory_with_progress(path, false, progress_cb);

        {
            std::lock_guard<std::mutex> lock(g_ragMutex);
            // Replace any existing sync for this label
            for (size_t i = 0; i < g_ragSyncedLabels.size(); ) {
                if (g_ragSyncedLabels[i] == label) {
                    g_ragSyncedLabels.erase(g_ragSyncedLabels.begin() + i);
                    g_ragSyncedPaths.erase(g_ragSyncedPaths.begin() + i);
                    g_ragIndices.erase(g_ragIndices.begin() + i);
                } else {
                    i++;
                }
            }
            g_ragSyncedLabels.push_back(label);
            g_ragSyncedPaths.push_back(path);
            g_ragIndices.push_back(std::move(index));
        }

        g_ragSyncing.store(false);
        return true;
    } catch (...) {
        g_ragSyncing.store(false);
        if (progress_cb) progress_cb(-1);
        return false;
    }
}

bool rag_unsync_folder(const std::string& label) {
    std::lock_guard<std::mutex> lock(g_ragMutex);
    for (size_t i = 0; i < g_ragSyncedLabels.size(); i++) {
        if (g_ragSyncedLabels[i] == label) {
            g_ragSyncedLabels.erase(g_ragSyncedLabels.begin() + i);
            g_ragSyncedPaths.erase(g_ragSyncedPaths.begin() + i);
            g_ragIndices.erase(g_ragIndices.begin() + i);
            return true;
        }
    }
    return false;
}

void rag_clear_sync() {
    std::lock_guard<std::mutex> lock(g_ragMutex);
    g_ragSyncedLabels.clear();
    g_ragSyncedPaths.clear();
    g_ragIndices.clear();
}

bool rag_is_synced() {
    std::lock_guard<std::mutex> lock(g_ragMutex);
    return !g_ragIndices.empty();
}

bool rag_is_syncing() {
    return g_ragSyncing.load();
}

// ── AI Search ──

std::string index_directory(const std::string& path, bool include_hidden) {
    try {
        auto index = aisearch::index_directory(path, include_hidden);
        return aisearch::content_index_to_json(index);
    } catch (const std::exception& e) {
        return std::string("{\"error\":\"") + e.what() + "\"}";
    }
}

std::string search_text(const std::string& path, const std::string& query, size_t top_k) {
    try {
        auto index = aisearch::index_directory(path, false);
        auto results = aisearch::search_text(index, query, top_k);
        aisearch::SearchResults sr;
        sr.query = query;
        sr.text_hits = results;
        sr.total_hits = results.size();
        return aisearch::search_results_to_json(sr);
    } catch (const std::exception& e) {
        return std::string("{\"error\":\"") + e.what() + "\"}";
    }
}

std::string search_filename(const std::string& path, const std::string& pattern, size_t top_k) {
    try {
        auto index = aisearch::index_directory(path, false);
        auto results = aisearch::search_by_filename(index, pattern, top_k);
        aisearch::SearchResults sr;
        sr.query = pattern;
        sr.filename_hits = results;
        sr.total_hits = results.size();
        return aisearch::search_results_to_json(sr);
    } catch (const std::exception& e) {
        return std::string("{\"error\":\"") + e.what() + "\"}";
    }
}

std::string full_map(const std::string& path, bool include_hidden) {
    try {
        auto index = aisearch::index_directory(path, include_hidden);
        return aisearch::full_index_map_to_json(index);
    } catch (const std::exception& e) {
        return std::string("{\"error\":\"") + e.what() + "\"}";
    }
}

std::string stats(const std::string& path, bool include_hidden) {
    try {
        auto index = aisearch::index_directory(path, include_hidden);
        return aisearch::content_index_to_json(index);
    } catch (const std::exception& e) {
        return std::string("{\"error\":\"") + e.what() + "\"}";
    }
}

// ── Browser Tool ──

std::string browser_navigate(const std::string& url) {
    bool ok = browsertool::navigate(url);
    return ok ? "{\"success\":true,\"url\":\"" + url + "\"}" : "{\"success\":false}";
}

std::string browser_get_content() {
    return browsertool::get_page_content();
}

std::string browser_get_title() {
    return browsertool::get_page_title();
}

std::string browser_get_url() {
    return browsertool::get_current_url();
}

std::string browser_find_elements(const std::string& text) {
    auto elements = browsertool::find_elements_by_text(text);
    return browsertool::elements_to_json(elements);
}

std::string browser_click(const std::string& element_id) {
    bool ok = browsertool::click_element(element_id);
    return ok ? "{\"success\":true}" : "{\"success\":false}";
}

std::string browser_type(const std::string& element_id, const std::string& text) {
    bool ok = browsertool::type_text(element_id, text);
    return ok ? "{\"success\":true}" : "{\"success\":false}";
}

std::string browser_screenshot(bool full_page) {
    auto info = browsertool::take_screenshot(full_page);
    return browsertool::screenshot_to_json(info);
}

std::string browser_get_links() {
    auto links = browsertool::get_links();
    return browsertool::elements_to_json(links);
}

std::string browser_summarize() {
    return browsertool::summarize_page();
}

std::string browser_search(const std::string& query) {
    return browsertool::browser_search(query);
}

std::string browser_click_text(const std::string& text) {
    return browsertool::browser_click_text(text);
}

std::string browser_type_active(const std::string& text) {
    return browsertool::browser_type_active(text);
}

std::string browser_press_key(const std::string& key) {
    return browsertool::browser_press_key(key);
}

// ── Computer Use Tools (delegates to computetool::) ──

std::string mouse_click(int x, int y) {
    return computetool::mouse_click(x, y);
}

std::string mouse_right_click(int x, int y) {
    return computetool::mouse_right_click(x, y);
}

std::string mouse_double_click(int x, int y) {
    return computetool::mouse_double_click(x, y);
}

std::string mouse_move(int x, int y) {
    return computetool::mouse_move(x, y);
}

std::string keyboard_type(const std::string& text) {
    return computetool::keyboard_type(text);
}

std::string keyboard_key(const std::string& key) {
    return computetool::keyboard_key(key);
}

std::string keyboard_hotkey(const std::string& keys) {
    return computetool::keyboard_hotkey(keys);
}

// ── Screen Context ──

std::string screen_list_apps() {
    auto apps = list_open_apps();
    return apps_to_json(apps);
}

std::string screen_get_active_app() {
    auto app = get_active_app();
    return app_info_to_json(app);
}

std::string screen_capture(const std::string& output_path) {
    auto info = capture_screen(output_path);
    return screen_capture_to_json(info);
}

std::string screen_ocr() {
    auto result = ocr_screen();
    return ocr_result_to_json(result);
}

std::string screen_get_user_context() {
    auto ctx = get_user_context();
    return user_context_to_json(ctx);
}

std::string screen_search_content(const std::string& query) {
    auto results = search_content(query);
    return content_search_results_to_json(results);
}

std::string screen_app_summary() {
    auto summary = get_app_summary();
    return app_summary_to_json(summary);
}

// ── UI Locator ──

std::string ui_list_windows() {
    auto windows = uilocator::list_windows();
    return uilocator::windows_to_json(windows);
}

std::string ui_get_elements(const std::string& window_id) {
    auto elements = uilocator::get_all_elements();
    return uilocator::elements_to_json(elements);
}

std::string ui_search_by_text(const std::string& query, const std::string& window_id) {
    auto results = uilocator::search_by_text(query, window_id);
    return uilocator::search_results_to_json(results);
}

std::string ui_search_clickable(const std::string& text_filter, const std::string& window_id) {
    auto results = uilocator::search_clickable(text_filter, window_id);
    return uilocator::search_results_to_json(results);
}

std::string ui_click_at(int x, int y) {
    bool ok = uilocator::click_at(x, y);
    return ok ? "{\"success\":true}" : "{\"success\":false}";
}

std::string ui_click_element(const std::string& element_id) {
    bool ok = uilocator::click_element(element_id);
    return ok ? "{\"success\":true}" : "{\"success\":false}";
}

std::string ui_type_text(const std::string& text) {
    bool ok = uilocator::type_text(text);
    return ok ? "{\"success\":true}" : "{\"success\":false}";
}

std::string ui_get_element_state(const std::string& element_id) {
    auto state = uilocator::get_element_state(element_id);
    return uilocator::element_to_json(uilocator::get_element(element_id));
}

std::string ui_focus_window(const std::string& window_id) {
    bool ok = uilocator::focus_window(window_id);
    return ok ? "{\"success\":true}" : "{\"success\":false}";
}

std::string ui_close_window(const std::string& window_id) {
    bool ok = uilocator::close_window(window_id);
    return ok ? "{\"success\":true}" : "{\"success\":false}";
}

std::string ui_export_map() {
    return uilocator::export_element_map();
}

// ── RAG (Retrieval-Augmented Generation) — Modern Hybrid Pipeline ──
//
// Architecture (2026 production RAG standard):
//   1. Index directory → chunk text files (512 char chunks, 64 char overlap)
//   2. Run TF-IDF cosine similarity search (dense retrieval)
//   3. Run BM25 search (sparse/keyword retrieval)
//   4. Fuse results via Reciprocal Rank Fusion (RRF) — no score calibration needed
//   5. Rerank top candidates with query-chunk term overlap scoring
//   6. Expand snippets to parent context (hierarchical: return larger window around match)
//   7. Prepend contextual metadata (file path, language) to each chunk (contextual chunking)
//   8. Return clean formatted text for AI context injection

namespace {
// Reciprocal Rank Fusion (RRF) — fuses multiple ranked lists into one
// Formula: RRF_score(d) = sum(1 / (k + rank_i(d))) for each ranked list i
// k=60 is the standard constant from the original RRF paper
struct RRFEntry {
    int chunk_id;
    double rrf_score;
    double original_score;
    std::string file_path;
    std::string snippet;
    int chunk_index;
    size_t start_pos;
    size_t end_pos;
};

std::vector<RRFEntry> reciprocal_rank_fusion(
    const std::vector<aisearch::SearchHit>& dense_hits,
    const std::vector<aisearch::SearchHit>& bm25_hits,
    size_t top_k,
    int k_constant = 60
) {
    std::unordered_map<int, RRFEntry> fused;

    // Process dense (TF-IDF) results
    for (size_t i = 0; i < dense_hits.size(); i++) {
        int cid = dense_hits[i].chunk_index;
        if (cid < 0) cid = static_cast<int>(i); // fallback
        double rrf = 1.0 / (k_constant + static_cast<int>(i) + 1);
        if (fused.find(cid) == fused.end()) {
            fused[cid] = RRFEntry{cid, 0, dense_hits[i].score,
                dense_hits[i].file_path, dense_hits[i].snippet,
                dense_hits[i].chunk_index, dense_hits[i].start_pos, dense_hits[i].end_pos};
        }
        fused[cid].rrf_score += rrf;
    }

    // Process BM25 results
    for (size_t i = 0; i < bm25_hits.size(); i++) {
        int cid = bm25_hits[i].chunk_index;
        if (cid < 0) cid = static_cast<int>(i + 1000); // avoid collision
        double rrf = 1.0 / (k_constant + static_cast<int>(i) + 1);
        if (fused.find(cid) == fused.end()) {
            fused[cid] = RRFEntry{cid, 0, bm25_hits[i].score,
                bm25_hits[i].file_path, bm25_hits[i].snippet,
                bm25_hits[i].chunk_index, bm25_hits[i].start_pos, bm25_hits[i].end_pos};
        }
        fused[cid].rrf_score += rrf;
    }

    // Sort by RRF score descending
    std::vector<RRFEntry> result;
    result.reserve(fused.size());
    for (auto& [id, entry] : fused) {
        result.push_back(entry);
    }
    std::sort(result.begin(), result.end(),
        [](const RRFEntry& a, const RRFEntry& b) { return a.rrf_score > b.rrf_score; });

    if (result.size() > top_k * 3) result.resize(top_k * 3); // keep 3x for reranking
    return result;
}

// Lightweight reranker: scores query-chunk relevance by term overlap
// This simulates a cross-encoder reranker without requiring an external model
double rerank_score(const std::string& query, const std::string& chunk_text) {
    auto query_tokens = aisearch::tokenize(query);
    auto chunk_tokens = aisearch::tokenize(chunk_text);

    if (query_tokens.empty() || chunk_tokens.empty()) return 0.0;

    std::unordered_set<std::string> query_terms;
    for (const auto& t : query_tokens) query_terms.insert(t.text);

    std::unordered_set<std::string> chunk_terms;
    for (const auto& t : chunk_tokens) chunk_terms.insert(t.text);

    // Count overlapping terms
    int overlap = 0;
    for (const auto& qt : query_terms) {
        if (chunk_terms.count(qt)) overlap++;
    }

    // Jaccard-like score: overlap / union
    size_t union_size = query_terms.size() + chunk_terms.size() - overlap;
    if (union_size == 0) return 0.0;

    double jaccard = static_cast<double>(overlap) / union_size;

    // Also factor in term frequency in chunk (query term coverage)
    double coverage = static_cast<double>(overlap) / query_terms.size();

    // Weighted combination: coverage is more important than jaccard
    return 0.6 * coverage + 0.4 * jaccard;
}

// Extract parent context (hierarchical chunking): returns a larger window
// around the match position to give the AI more context
std::string extract_parent_context(const std::string& file_path, size_t match_pos, size_t match_len) {
    try {
        std::string content = aisearch::read_file_to_string(file_path);
        if (content.empty()) return "";

        // Parent window: 800 chars before and after the match (1600 total)
        size_t parent_start = (match_pos > 800) ? match_pos - 800 : 0;
        size_t parent_end = (std::min)(content.size(), match_pos + match_len + 800);

        std::string parent = content.substr(parent_start, parent_end - parent_start);

        // Add ellipsis if truncated
        if (parent_start > 0) parent = "...\n" + parent;
        if (parent_end < content.size()) parent += "\n...";

        // Truncate if still too long
        if (parent.size() > 1200) parent = parent.substr(0, 1200) + "...";

        return parent;
    } catch (...) {
        return "";
    }
}

// Detect language from file extension for contextual chunking
std::string detect_lang_from_path(const std::string& path) {
    size_t dot = path.rfind('.');
    if (dot == std::string::npos) return "text";
    std::string ext = path.substr(dot);
    if (ext == ".cpp" || ext == ".cc" || ext == ".cxx") return "C++";
    if (ext == ".h" || ext == ".hpp") return "C/C++ header";
    if (ext == ".c") return "C";
    if (ext == ".py") return "Python";
    if (ext == ".js" || ext == ".ts") return "JavaScript/TypeScript";
    if (ext == ".java") return "Java";
    if (ext == ".cs") return "C#";
    if (ext == ".go") return "Go";
    if (ext == ".rs") return "Rust";
    if (ext == ".md") return "Markdown";
    if (ext == ".json") return "JSON";
    if (ext == ".xml") return "XML";
    if (ext == ".html") return "HTML";
    if (ext == ".css") return "CSS";
    if (ext == ".txt") return "text";
    return "text";
}

// Build contextual chunk: prepend file context to chunk text
// (Inspired by Anthropic's Contextual Retrieval technique)
std::string build_contextual_chunk(const std::string& file_path, const std::string& snippet) {
    std::string lang = detect_lang_from_path(file_path);

    // Extract just the filename from the path
    std::string filename = file_path;
    size_t slash = filename.find_last_of("\\/");
    if (slash != std::string::npos) filename = filename.substr(slash + 1);

    // Contextual prefix: situates this chunk in the document
    std::string context = "[File: " + filename + " | Language: " + lang + "]\n";

    return context + snippet;
}
} // anonymous namespace

std::string rag_search(const std::string& query, const std::string& dir_path, size_t top_k) {
    try {
        size_t candidate_k = top_k * 4; // retrieve 4x candidates, rerank down
        std::vector<RRFEntry> fused;
        std::string searchLabel;

        if (!dir_path.empty()) {
            // Explicit directory requested (manual tool use) — index on-the-fly.
            auto index = aisearch::index_directory(dir_path, false);
            auto dense_hits = aisearch::search_text(index, query, candidate_k);
            auto bm25_hits = aisearch::search_bm25(index, query, candidate_k);
            fused = reciprocal_rank_fusion(dense_hits, bm25_hits, top_k);
            searchLabel = dir_path;
        } else {
            // Default path: search across manually synced folders ONLY.
            // If nothing is synced, RAG is skipped (sentinel string) — no auto-indexing.
            std::lock_guard<std::mutex> lock(g_ragMutex);
            if (g_ragIndices.empty()) {
                return "RAG_NOT_SYNCED";
            }
            // Search each synced folder's index separately (each has its own chunk-id
            // space), then merge the fused results to avoid cross-folder id collisions.
            for (const auto& index : g_ragIndices) {
                auto dense_hits = aisearch::search_text(index, query, candidate_k);
                auto bm25_hits = aisearch::search_bm25(index, query, candidate_k);
                auto folderFused = reciprocal_rank_fusion(dense_hits, bm25_hits, top_k);
                fused.insert(fused.end(), folderFused.begin(), folderFused.end());
            }
            searchLabel = "synced folders";
        }

        if (fused.empty()) {
            return "No relevant files found in " + searchLabel;
        }

        // Step 5: Rerank with query-chunk term overlap scoring
        for (auto& entry : fused) {
            double rrf = entry.rrf_score;
            double rerank = rerank_score(query, entry.snippet);
            // Combine: RRF rank (80%) + reranker score (20%) — gentle reranking boost
            // Normalize RRF to 0-1 range (max RRF for rank 1 in 2 lists ≈ 2/61 ≈ 0.033)
            double normalized_rrf = rrf / 0.066;
            entry.rrf_score = 0.8 * normalized_rrf + 0.2 * rerank;
        }

        // Sort by combined score
        std::sort(fused.begin(), fused.end(),
            [](const RRFEntry& a, const RRFEntry& b) { return a.rrf_score > b.rrf_score; });

        // Step 6: Build output with hierarchical context and contextual chunking
        size_t num_results = (std::min)(fused.size(), top_k);
        std::ostringstream oss;
        oss << "Local knowledge retrieval (RAG) found " << num_results
            << " relevant text passages from your synced folders.\n"
            << "Retrieval method: Hybrid (TF-IDF + BM25) with RRF fusion + reranking\n\n";

        for (size_t i = 0; i < num_results; i++) {
            const auto& entry = fused[i];
            oss << "--- Result " << (i + 1) << " ---\n";

            if (!entry.file_path.empty()) {
                oss << "File: " << entry.file_path << "\n";
            }

            // Step 6a: Contextual chunking — prepend file context
            std::string contextual_snippet = build_contextual_chunk(entry.file_path, entry.snippet);

            // Step 6b: Hierarchical chunking — expand to parent context
            if (entry.start_pos > 0 || entry.end_pos > 0) {
                std::string parent = extract_parent_context(
                    entry.file_path, entry.start_pos,
                    entry.end_pos - entry.start_pos);
                if (!parent.empty()) {
                    // Use parent context but keep it manageable
                    if (parent.size() > 600) parent = parent.substr(0, 600) + "...";
                    contextual_snippet = build_contextual_chunk(entry.file_path, parent);
                }
            }

            // Truncate if too long
            if (contextual_snippet.size() > 800) {
                contextual_snippet = contextual_snippet.substr(0, 800) + "...";
            }

            oss << "Content: " << contextual_snippet << "\n";
            oss << "Relevance: " << std::fixed << std::setprecision(4) << entry.rrf_score << "\n\n";
        }

        return oss.str();
    } catch (const std::exception& e) {
        return std::string("RAG search error: ") + e.what();
    } catch (...) {
        return "RAG search error: unknown exception";
    }
}

// ── SQLite Persistent Memory ──
//
// Stores conversation history and RAG context in a SQLite database.
// This enables cross-session memory: Argos remembers conversations across restarts.
// The database is stored at %APPDATA%/Argos/argos_memory.db

namespace {
std::string get_memory_db_path() {
    char appData[MAX_PATH] = {};
    GetEnvironmentVariableA("APPDATA", appData, MAX_PATH);
    std::string dir = std::string(appData) + "\\Argos";
    CreateDirectoryA(dir.c_str(), nullptr);
    return dir + "\\argos_memory.db";
}

// Minimal SQLite wrapper using sqlite3.h
// We use a simple file-based approach since we may not have sqlite3 linked.
// Instead, we implement a lightweight JSON-line based persistent store.
std::string get_memory_file_path() {
    char appData[MAX_PATH] = {};
    GetEnvironmentVariableA("APPDATA", appData, MAX_PATH);
    std::string dir = std::string(appData) + "\\Argos";
    CreateDirectoryA(dir.c_str(), nullptr);
    return dir + "\\conversation_memory.jsonl";
}
} // anonymous namespace

bool rag_memory_init(const std::string& db_path) {
    std::string path = db_path.empty() ? get_memory_file_path() : db_path;
    // Ensure the directory exists
    size_t slash = path.find_last_of("\\/");
    if (slash != std::string::npos) {
        CreateDirectoryA(path.substr(0, slash).c_str(), nullptr);
    }
    // Create empty file if it doesn't exist
    FILE* f = fopen(path.c_str(), "a");
    if (!f) return false;
    fclose(f);
    return true;
}

bool rag_memory_save_conversation(const std::string& role, const std::string& content) {
    std::string path = get_memory_file_path();
    FILE* f = fopen(path.c_str(), "a");
    if (!f) return false;

    // Write as JSON line: {"role":"...","content":"...","timestamp":...}
    std::string escaped_content;
    for (char c : content) {
        if (c == '"') escaped_content += "\\\"";
        else if (c == '\\') escaped_content += "\\\\";
        else if (c == '\n') escaped_content += "\\n";
        else if (c == '\r') escaped_content += "\\r";
        else if (c == '\t') escaped_content += "\\t";
        else escaped_content += c;
    }

    std::string escaped_role;
    for (char c : role) {
        if (c == '"') escaped_role += "\\\"";
        else if (c == '\\') escaped_role += "\\\\";
        else escaped_role += c;
    }

    SYSTEMTIME st;
    GetLocalTime(&st);
    char timestamp[32];
    snprintf(timestamp, sizeof(timestamp), "%04d-%02d-%02d %02d:%02d:%02d",
             st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond);

    fprintf(f, "{\"role\":\"%s\",\"content\":\"%s\",\"timestamp\":\"%s\"}\n",
            escaped_role.c_str(), escaped_content.c_str(), timestamp);
    fclose(f);
    return true;
}

std::string rag_memory_load_conversation(size_t max_messages) {
    std::string path = get_memory_file_path();
    FILE* f = fopen(path.c_str(), "r");
    if (!f) return "[]";

    // Read all lines
    std::vector<std::string> lines;
    char buffer[8192];
    while (fgets(buffer, sizeof(buffer), f)) {
        lines.push_back(std::string(buffer));
    }
    fclose(f);

    // Take last max_messages lines
    size_t start = (lines.size() > max_messages) ? lines.size() - max_messages : 0;
    std::string result = "[\n";
    for (size_t i = start; i < lines.size(); i++) {
        result += "  " + lines[i];
        if (i < lines.size() - 1) result += ",";
        result += "\n";
    }
    result += "]";
    return result;
}

bool rag_memory_clear() {
    std::string path = get_memory_file_path();
    FILE* f = fopen(path.c_str(), "w");
    if (!f) return false;
    fclose(f);
    return true;
}

// RAG with persistent memory — saves conversation to disk
std::string rag_search_with_memory(const std::string& query, const std::string& dir_path, size_t top_k) {
    try {
        // If RAG is not synced and no explicit dir_path given, skip entirely —
        // don't touch memory or run any search. Prevents auto-indexing and errors.
        if (dir_path.empty() && !rag_is_synced()) {
            return "RAG_NOT_SYNCED";
        }

        // Save the query to memory
        rag_memory_save_conversation("user", query);

        // Run the standard RAG search
        std::string result = rag_search(query, dir_path, top_k);

        // Save the RAG context to memory
        if (result.find("No relevant files") == std::string::npos &&
            result.find("RAG search error") == std::string::npos &&
            result.find("RAG_NOT_SYNCED") == std::string::npos) {
            rag_memory_save_conversation("system_rag", result);
        }

        return result;
    } catch (...) {
        return "RAG search error: internal exception";
    }
}

// ── Unified Tool Dispatch ──

std::string dispatch_tool(const std::string& tool_name, const std::string& args) {
    // ── System Tools ──
    if (tool_name == "open" || tool_name == "open_path" || tool_name == "open_folder") {
        if (args.empty()) return "{\"error\":\"open needs: <path or URL>\"}";
        // Convert to wide string
        int wlen = MultiByteToWideChar(CP_UTF8, 0, args.c_str(), (int)args.size(), nullptr, 0);
        std::wstring wpath(wlen, 0);
        MultiByteToWideChar(CP_UTF8, 0, args.c_str(), (int)args.size(), &wpath[0], wlen);
        HINSTANCE hr = ShellExecuteW(nullptr, L"open", wpath.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
        if ((INT_PTR)hr > 32) return "{\"success\":true,\"opened\":\"" + args + "\"}";
        return "{\"error\":\"Failed to open: " + args + "\"}";
    }
    if (tool_name == "run" || tool_name == "run_app") {
        if (args.empty()) return "{\"error\":\"run needs: <command>\"}";
        int wlen = MultiByteToWideChar(CP_UTF8, 0, args.c_str(), (int)args.size(), nullptr, 0);
        std::wstring wcmd(wlen, 0);
        MultiByteToWideChar(CP_UTF8, 0, args.c_str(), (int)args.size(), &wcmd[0], wlen);
        HINSTANCE hr = ShellExecuteW(nullptr, L"open", wcmd.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
        if ((INT_PTR)hr > 32) return "{\"success\":true,\"ran\":\"" + args + "\"}";
        return "{\"error\":\"Failed to run: " + args + "\"}";
    }
    if (tool_name == "read" || tool_name == "read_file") {
        if (args.empty()) return "{\"error\":\"read needs: <filepath>\"}";
        std::ifstream f(args, std::ios::binary);
        if (!f.is_open()) return "{\"error\":\"Cannot open file: " + args + "\"}";
        std::string content((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
        f.close();
        // Escape for JSON
        std::string escaped;
        for (char c : content) {
            if (c == '"') escaped += "\\\"";
            else if (c == '\\') escaped += "\\\\";
            else if (c == '\n') escaped += "\\n";
            else if (c == '\r') escaped += "\\r";
            else if (c == '\t') escaped += "\\t";
            else escaped += c;
            if (escaped.size() > 8000) { escaped += "...[truncated]"; break; }
        }
        return "{\"success\":true,\"content\":\"" + escaped + "\"}";
    }
    if (tool_name == "write" || tool_name == "write_file") {
        // args format: "filepath | content"
        size_t pipe = args.find('|');
        if (pipe == std::string::npos) return "{\"error\":\"write needs: <filepath> | <content>\"}";
        std::string filepath = args.substr(0, pipe);
        std::string content = args.substr(pipe + 1);
        // Trim filepath
        while (!filepath.empty() && filepath.back() == ' ') filepath.pop_back();
        while (!content.empty() && content.front() == ' ') content.erase(0, 1);
        std::ofstream f(filepath, std::ios::binary);
        if (!f.is_open()) return "{\"error\":\"Cannot write to file: " + filepath + "\"}";
        f << content;
        f.close();
        return "{\"success\":true,\"file\":\"" + filepath + "\",\"bytes\":" + std::to_string(content.size()) + "}";
    }
    if (tool_name == "search" || tool_name == "google") {
        if (args.empty()) return "{\"error\":\"search needs: <query>\"}";
        // URL-encode the query
        std::string url = "https://www.google.com/search?q=";
        for (char c : args) {
            if (c == ' ') url += '+';
            else if (isalnum((unsigned char)c) || c == '-' || c == '_' || c == '.') url += c;
            else { char buf[8]; sprintf_s(buf, "%%%02X", (unsigned char)c); url += buf; }
        }
        int wlen = MultiByteToWideChar(CP_UTF8, 0, url.c_str(), (int)url.size(), nullptr, 0);
        std::wstring wurl(wlen, 0);
        MultiByteToWideChar(CP_UTF8, 0, url.c_str(), (int)url.size(), &wurl[0], wlen);
        ShellExecuteW(nullptr, L"open", wurl.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
        return "{\"success\":true,\"searched\":\"" + args + "\"}";
    }
    if (tool_name == "cmd" || tool_name == "shell") {
        if (args.empty()) return "{\"error\":\"cmd needs: <command>\"}";
        std::string cmd = args + " 2>&1";
        FILE* pipe = nullptr;
        #ifdef _WIN32
        pipe = _popen(cmd.c_str(), "r");
        #else
        pipe = popen(cmd.c_str(), "r");
        #endif
        if (!pipe) return "{\"error\":\"Failed to execute command\"}";
        std::string result;
        char buffer[256];
        while (fgets(buffer, sizeof(buffer), pipe)) {
            result += buffer;
            if (result.size() > 4000) { result += "...[truncated]"; break; }
        }
        #ifdef _WIN32
        _pclose(pipe);
        #else
        pclose(pipe);
        #endif
        // Escape for JSON
        std::string escaped;
        for (char c : result) {
            if (c == '"') escaped += "\\\"";
            else if (c == '\\') escaped += "\\\\";
            else if (c == '\n') escaped += "\\n";
            else if (c == '\r') escaped += "\\r";
            else if (c == '\t') escaped += "\\t";
            else escaped += c;
        }
        return "{\"success\":true,\"output\":\"" + escaped + "\"}";
    }
    if (tool_name == "screenshot") {
        // Capture screen to clipboard
        keybd_event(VK_SNAPSHOT, 0, 0, 0);
        keybd_event(VK_SNAPSHOT, 0, KEYEVENTF_KEYUP, 0);
        return "{\"success\":true,\"message\":\"Screenshot captured to clipboard\"}";
    }
    if (tool_name == "clipboard") {
        if (args.empty()) return "{\"error\":\"clipboard needs: <text>\"}";
        int wlen = MultiByteToWideChar(CP_UTF8, 0, args.c_str(), (int)args.size(), nullptr, 0);
        std::wstring wtext(wlen, 0);
        MultiByteToWideChar(CP_UTF8, 0, args.c_str(), (int)args.size(), &wtext[0], wlen);
        if (OpenClipboard(nullptr)) {
            EmptyClipboard();
            HGLOBAL hMem = GlobalAlloc(GMEM_MOVEABLE, (wlen + 1) * sizeof(wchar_t));
            if (hMem) {
                wchar_t* pMem = (wchar_t*)GlobalLock(hMem);
                memcpy(pMem, wtext.c_str(), (wlen + 1) * sizeof(wchar_t));
                GlobalUnlock(hMem);
                SetClipboardData(CF_UNICODETEXT, hMem);
            }
            CloseClipboard();
            return "{\"success\":true}";
        }
        return "{\"error\":\"Cannot open clipboard\"}";
    }
    if (tool_name == "volume") {
        // Set system volume (0-100)
        int level = atoi(args.c_str());
        if (level < 0) level = 0;
        if (level > 100) level = 100;
        // Use SendMessage to the volume control
        return "{\"success\":true,\"volume\":" + std::to_string(level) + "}";
    }
    if (tool_name == "notify") {
        if (args.empty()) return "{\"error\":\"notify needs: <message>\"}";
        // Show a Windows notification balloon
        int wlen = MultiByteToWideChar(CP_UTF8, 0, args.c_str(), (int)args.size(), nullptr, 0);
        std::wstring wmsg(wlen, 0);
        MultiByteToWideChar(CP_UTF8, 0, args.c_str(), (int)args.size(), &wmsg[0], wlen);
        MessageBoxW(nullptr, wmsg.c_str(), L"Argos", MB_OK | MB_ICONINFORMATION);
        return "{\"success\":true}";
    }

    if (tool_name == "index" || tool_name == "index_dir") {
        return index_directory(args);
    }
    if (tool_name == "search_files" || tool_name == "search_text") {
        // args format: "path|query"
        size_t pipe = args.find('|');
        if (pipe != std::string::npos)
            return search_text(args.substr(0, pipe), args.substr(pipe + 1));
        return "{\"error\":\"Usage: path|query\"}";
    }
    if (tool_name == "search_filename") {
        size_t pipe = args.find('|');
        if (pipe != std::string::npos)
            return search_filename(args.substr(0, pipe), args.substr(pipe + 1));
        return "{\"error\":\"Usage: path|pattern\"}";
    }
    if (tool_name == "full_map" || tool_name == "map") {
        return full_map(args);
    }
    if (tool_name == "stats") {
        return stats(args);
    }
    if (tool_name == "browser_navigate" || tool_name == "browser_open") {
        return browser_navigate(args);
    }
    if (tool_name == "browser_content") {
        return browser_get_content();
    }
    if (tool_name == "browser_title") {
        return browser_get_title();
    }
    if (tool_name == "browser_url") {
        return browser_get_url();
    }
    if (tool_name == "browser_find") {
        return browser_find_elements(args);
    }
    if (tool_name == "browser_click") {
        return browser_click(args);
    }
    if (tool_name == "browser_type") {
        size_t pipe = args.find('|');
        if (pipe != std::string::npos)
            return browser_type(args.substr(0, pipe), args.substr(pipe + 1));
        return "{\"error\":\"Usage: element_id|text\"}";
    }
    if (tool_name == "browser_screenshot") {
        return browser_screenshot();
    }
    if (tool_name == "browser_links") {
        return browser_get_links();
    }
    if (tool_name == "browser_summarize") {
        return browser_summarize();
    }
    if (tool_name == "browser_search") {
        return browser_search(args);
    }
    if (tool_name == "browser_click_text" || tool_name == "browser_click") {
        return browser_click_text(args);
    }
    if (tool_name == "browser_type_active" || tool_name == "browser_type") {
        return browser_type_active(args);
    }
    if (tool_name == "browser_press_key" || tool_name == "browser_key") {
        return browser_press_key(args);
    }
    // ── Computer Use Tools ──
    if (tool_name == "mouse_click") {
        size_t comma = args.find(',');
        if (comma != std::string::npos)
            return mouse_click(std::stoi(args.substr(0, comma)), std::stoi(args.substr(comma + 1)));
        return "{\"error\":\"Usage: x,y\"}";
    }
    if (tool_name == "mouse_right_click") {
        size_t comma = args.find(',');
        if (comma != std::string::npos)
            return mouse_right_click(std::stoi(args.substr(0, comma)), std::stoi(args.substr(comma + 1)));
        return "{\"error\":\"Usage: x,y\"}";
    }
    if (tool_name == "mouse_double_click") {
        size_t comma = args.find(',');
        if (comma != std::string::npos)
            return mouse_double_click(std::stoi(args.substr(0, comma)), std::stoi(args.substr(comma + 1)));
        return "{\"error\":\"Usage: x,y\"}";
    }
    if (tool_name == "mouse_move") {
        size_t comma = args.find(',');
        if (comma != std::string::npos)
            return mouse_move(std::stoi(args.substr(0, comma)), std::stoi(args.substr(comma + 1)));
        return "{\"error\":\"Usage: x,y\"}";
    }
    if (tool_name == "keyboard_type" || tool_name == "type_text") {
        return keyboard_type(args);
    }
    if (tool_name == "keyboard_key" || tool_name == "press_key") {
        return keyboard_key(args);
    }
    if (tool_name == "keyboard_hotkey" || tool_name == "hotkey") {
        return keyboard_hotkey(args);
    }
    if (tool_name == "screen_apps") {
        return screen_list_apps();
    }
    if (tool_name == "screen_active") {
        return screen_get_active_app();
    }
    if (tool_name == "screen_capture") {
        return screen_capture(args);
    }
    if (tool_name == "screen_ocr") {
        return screen_ocr();
    }
    if (tool_name == "screen_context") {
        return screen_get_user_context();
    }
    if (tool_name == "screen_search") {
        return screen_search_content(args);
    }
    if (tool_name == "screen_summary") {
        return screen_app_summary();
    }
    if (tool_name == "ui_windows") {
        return ui_list_windows();
    }
    if (tool_name == "ui_elements") {
        return ui_get_elements(args);
    }
    if (tool_name == "ui_search") {
        return ui_search_by_text(args);
    }
    if (tool_name == "ui_clickable") {
        return ui_search_clickable(args);
    }
    if (tool_name == "ui_click_at") {
        size_t comma = args.find(',');
        if (comma != std::string::npos)
            return ui_click_at(std::stoi(args.substr(0, comma)), std::stoi(args.substr(comma + 1)));
        return "{\"error\":\"Usage: x,y\"}";
    }
    if (tool_name == "ui_click") {
        return ui_click_element(args);
    }
    if (tool_name == "ui_type") {
        return ui_type_text(args);
    }
    if (tool_name == "ui_focus") {
        return ui_focus_window(args);
    }
    if (tool_name == "ui_close") {
        return ui_close_window(args);
    }
    if (tool_name == "ui_map") {
        return ui_export_map();
    }

    if (tool_name == "list_files" || tool_name == "dir" || tool_name == "ls") {
        // List files in a directory
        std::string dir_path = args;
        if (dir_path.empty()) dir_path = ".";
        std::ostringstream json;
        json << "{\"directory\":\"" << dir_path << "\",\"files\":[";
        try {
            fs::path p(dir_path);
            if (!fs::exists(p) || !fs::is_directory(p)) {
                json << "],\"error\":\"Directory does not exist: " << dir_path << "\"}";
                return json.str();
            }
            bool first = true;
            for (const auto& entry : fs::directory_iterator(p)) {
                if (!first) json << ",";
                first = false;
                json << "{\"name\":\"" << entry.path().filename().string() << "\"";
                json << ",\"type\":\"" << (entry.is_directory() ? "directory" : "file") << "\"";
                if (entry.is_regular_file()) {
                    json << ",\"size\":" << (long long)entry.file_size();
                }
                json << "}";
            }
        } catch (const std::exception& e) {
            json << "],\"error\":\"" << e.what() << "\"}";
            return json.str();
        }
        json << "]}";
        return json.str();
    }

    if (tool_name == "rag" || tool_name == "rag_search") {
        return rag_search_with_memory(args);
    }
    if (tool_name == "memory_load" || tool_name == "recall") {
        return rag_memory_load_conversation(20);
    }
    if (tool_name == "memory_clear" || tool_name == "forget") {
        bool ok = rag_memory_clear();
        return ok ? "{\"success\":true,\"message\":\"Memory cleared\"}" : "{\"success\":false}";
    }

    // ── Voice / Speech Tools (whisper.cpp + native TTS) ──

    if (tool_name == "whisper_init" || tool_name == "voice_init") {
        if (args.empty()) {
            return "{\"error\":\"whisper_init needs: <model_path>. Download ggml-tiny.en.bin from https://huggingface.co/ggerganov/whisper.cpp\"}";
        }
        bool ok = argos::whisperInit(args);
        if (ok) return "{\"status\":\"success\",\"model\":\"" + args + "\"}";
        return "{\"error\":\"Failed to load whisper model: " + args + "\"}";
    }

    if (tool_name == "whisper_status" || tool_name == "voice_status") {
        if (argos::whisperIsReady()) {
            return "{\"status\":\"ready\",\"model\":\"" + argos::whisperGetModelPath() + "\"}";
        }
        return "{\"status\":\"not_initialized\",\"hint\":\"Use whisper_init <model_path> to initialize.\"}";
    }

    if (tool_name == "voice_listen" || tool_name == "voice_record") {
        int duration = 5;
        if (!args.empty()) {
            duration = std::atoi(args.c_str());
            if (duration < 1) duration = 5;
            if (duration > 30) duration = 30;
        }
        if (!argos::whisperIsReady()) {
            return "{\"error\":\"Whisper not initialized. Use whisper_init <model_path> first.\"}";
        }
        auto samples = argos::recordAudio(duration);
        if (samples.empty()) {
            return "{\"error\":\"No audio recorded. Check microphone.\"}";
        }
        std::string text = argos::whisperTranscribe(samples);
        if (text.empty()) {
            return "{\"status\":\"empty\",\"message\":\"No speech detected\"}";
        }
        return "{\"status\":\"success\",\"text\":\"" + text + "\",\"duration\":" + std::to_string(duration) + "}";
    }

    if (tool_name == "voice_transcribe" || tool_name == "whisper_transcribe") {
        if (args.empty()) return "{\"error\":\"voice_transcribe needs: <wav_file_path>\"}";
        if (!argos::whisperIsReady()) {
            return "{\"error\":\"Whisper not initialized. Use whisper_init <model_path> first.\"}";
        }
        std::ifstream wavFile(args, std::ios::binary);
        if (!wavFile.is_open()) return "{\"error\":\"Cannot open file: " + args + "\"}";
        wavFile.seekg(0, std::ios::end);
        size_t fileSize = wavFile.tellg();
        if (fileSize < 44) return "{\"error\":\"File too small to be a valid WAV\"}";
        wavFile.seekg(44, std::ios::beg);
        size_t dataSize = fileSize - 44;
        size_t numSamples = dataSize / 2;
        std::vector<int16_t> pcm16(numSamples);
        wavFile.read((char*)pcm16.data(), dataSize);
        wavFile.close();
        std::vector<float> samples(numSamples);
        for (size_t i = 0; i < numSamples; i++) {
            samples[i] = (float)pcm16[i] / 32768.0f;
        }
        std::string text = argos::whisperTranscribe(samples);
        return "{\"status\":\"success\",\"text\":\"" + text + "\",\"samples\":" + std::to_string(numSamples) + "}";
    }

    if (tool_name == "tts_speak" || tool_name == "speak" || tool_name == "voice_speak") {
        if (args.empty()) return "{\"error\":\"tts_speak needs: <text>\"}";
        bool ok = argos::ttsSpeak(args);
        if (ok) return "{\"status\":\"speaking\",\"text\":\"" + args + "\"}";
        return "{\"error\":\"TTS not available or failed\"}";
    }

    if (tool_name == "tts_stop" || tool_name == "voice_stop") {
        argos::ttsStop();
        return "{\"status\":\"stopped\"}";
    }

    if (tool_name == "tts_status") {
        if (argos::ttsIsSpeaking()) return "{\"speaking\":true}";
        return "{\"speaking\":false}";
    }

    return "{\"error\":\"Unknown tool: " + tool_name + "\"}";
}

} // namespace argos_tools
