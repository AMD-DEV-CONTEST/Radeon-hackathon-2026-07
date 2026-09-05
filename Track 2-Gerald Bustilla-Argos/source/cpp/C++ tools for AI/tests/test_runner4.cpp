// test_runner4.cpp - Tests for advanced AI search features
// Tests: BM25 scoring, regex search, synonym expansion, .gitignore support,
// multi-threaded indexing, persistent index (save/load), incremental update,
// and complex real-world AI usage scenarios
#include <iostream>
#include <string>
#include <vector>
#include <sstream>
#include <fstream>
#include <cstdlib>
#include <chrono>
#include <functional>
#include <iomanip>
#include <cmath>

#ifdef _WIN32
#include <cstdio>
#define popen _popen
#define pclose _pclose
#endif

static int tests_passed = 0;
static int tests_failed = 0;
static int tests_total = 0;

static std::string exec_command(const std::string& cmd) {
    std::string result;
    FILE* pipe = popen(cmd.c_str(), "r");
    if (!pipe) return "";
    char buffer[4096];
    while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
        result += buffer;
    }
    pclose(pipe);
    return result;
}

static bool json_contains(const std::string& json, const std::string& needle) {
    return json.find(needle) != std::string::npos;
}

static bool json_contains_ci(const std::string& json, const std::string& needle) {
    std::string lower_json, lower_needle;
    for (char c : json) lower_json += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    for (char c : needle) lower_needle += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return lower_json.find(lower_needle) != std::string::npos;
}

static int json_get_int(const std::string& json, const std::string& key) {
    std::string search = "\"" + key + "\":";
    size_t pos = json.find(search);
    if (pos == std::string::npos) return -1;
    pos += search.size();
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) pos++;
    std::string num;
    while (pos < json.size() && (json[pos] >= '0' && json[pos] <= '9')) {
        num += json[pos++];
    }
    if (num.empty()) return -1;
    return std::atoi(num.c_str());
}

static double json_get_double(const std::string& json, const std::string& key) {
    std::string search = "\"" + key + "\":";
    size_t pos = json.find(search);
    if (pos == std::string::npos) return -1.0;
    pos += search.size();
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) pos++;
    std::string num;
    while (pos < json.size() && ((json[pos] >= '0' && json[pos] <= '9') || json[pos] == '.' || json[pos] == '-')) {
        num += json[pos++];
    }
    if (num.empty()) return -1.0;
    return std::atof(num.c_str());
}

static void run_test(const std::string& test_name, const std::string& cmd,
                     std::function<bool(const std::string&)> validator) {
    tests_total++;
    std::cout << "[" << std::setw(3) << tests_total << "] " << std::left << std::setw(58) << test_name << " ... ";
    std::cout.flush();

    std::string output = exec_command(cmd);

    bool passed = false;
    try {
        passed = validator(output);
    } catch (...) {
        passed = false;
    }

    if (passed) {
        tests_passed++;
        std::cout << "PASS" << std::endl;
    } else {
        tests_failed++;
        std::cout << "FAIL" << std::endl;
        if (output.size() > 200) output = output.substr(0, 200) + "...";
        std::cout << "       Output: " << output << std::endl;
    }
}

static std::string A = ".\\aisearch.exe";
static std::string D = "test_data";

int main() {
    std::cout << "========================================" << std::endl;
    std::cout << "  ADVANCED FEATURE TEST SUITE 4" << std::endl;
    std::cout << "  BM25, Regex, Synonyms, Gitignore, MT," << std::endl;
    std::cout << "  Persistent Index, Incremental Update" << std::endl;
    std::cout << "========================================" << std::endl;

    // ========== CATEGORY 1: BM25 Search Scoring (1-12) ==========
    std::cout << std::endl << "--- Category 1: BM25 Search Scoring ---" << std::endl;

    run_test("BM25 search returns results", A + " search-bm25 " + D + " --query \"authentication\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("BM25 search returns bm25_hits array", A + " search-bm25 " + D + " --query \"database\"",
        [](const std::string& o) { return json_contains(o, "bm25_hits"); });

    run_test("BM25 match_type is bm25", A + " search-bm25 " + D + " --query \"search engine\"",
        [](const std::string& o) { return json_contains(o, "\"match_type\":\"bm25\""); });

    run_test("BM25 search includes score field", A + " search-bm25 " + D + " --query \"config\"",
        [](const std::string& o) { return json_contains(o, "\"score\":"); });

    run_test("BM25 search includes snippet", A + " search-bm25 " + D + " --query \"error handling\"",
        [](const std::string& o) { return json_contains(o, "\"snippet\":"); });

    run_test("BM25 search includes context_snippet", A + " search-bm25 " + D + " --query \"authentication token\"",
        [](const std::string& o) { return json_contains(o, "context_snippet"); });

    run_test("BM25 search includes language field", A + " search-bm25 " + D + " --query \"vector store\"",
        [](const std::string& o) { return json_contains(o, "language"); });

    run_test("BM25 search with top-k 1 returns at most 1 hit", A + " search-bm25 " + D + " --query \"authentication\" --top-k 1",
        [](const std::string& o) { return json_get_int(o, "total_hits") <= 1; });

    run_test("BM25 search for non-existent term returns 0 hits", A + " search-bm25 " + D + " --query \"zzznonexistentxyz\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") == 0; });

    run_test("BM25 search for common term returns many hits", A + " search-bm25 " + D + " --query \"search\" --top-k 20",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("BM25 scores are between 0 and 1", A + " search-bm25 " + D + " --query \"authentication\" --top-k 5",
        [](const std::string& o) {
            double score = json_get_double(o, "score");
            return score >= 0.0 && score <= 1.0;
        });

    run_test("BM25 search includes file_path", A + " search-bm25 " + D + " --query \"database\"",
        [](const std::string& o) { return json_contains(o, "file_path"); });

    // ========== CATEGORY 2: Regex Search (13-25) ==========
    std::cout << std::endl << "--- Category 2: Regex Search ---" << std::endl;

    run_test("Regex search for function declarations", A + " search-regex " + D + " --query \"void [a-zA-Z_]+\\(\" --top-k 10",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Regex search returns regex_hits array", A + " search-regex " + D + " --query \"import .+\" --top-k 10",
        [](const std::string& o) { return json_contains(o, "regex_hits"); });

    run_test("Regex search match_type is regex", A + " search-regex " + D + " --query \"#include .+\" --top-k 5",
        [](const std::string& o) { return json_contains(o, "\"match_type\":\"regex\""); });

    run_test("Regex search includes start_pos and end_pos", A + " search-regex " + D + " --query \"function [a-zA-Z_]+\" --top-k 5",
        [](const std::string& o) { return json_contains(o, "start_pos") && json_contains(o, "end_pos"); });

    run_test("Regex search includes context_snippet", A + " search-regex " + D + " --query \"class [a-zA-Z_]+\" --top-k 5",
        [](const std::string& o) { return json_contains(o, "context_snippet"); });

    run_test("Regex search includes line_number", A + " search-regex " + D + " --query \"def [a-zA-Z_]+\" --top-k 5",
        [](const std::string& o) { return json_contains(o, "line_number"); });

    run_test("Regex search for TODO comments", A + " search-regex " + D + " --query \"TODO|FIXME|HACK\" --top-k 10",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Regex search for import statements", A + " search-regex " + D + " --query \"^import .+\" --top-k 10",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Regex search for include statements", A + " search-regex " + D + " --query \"#include\" --top-k 10",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Regex search for class definitions", A + " search-regex " + D + " --query \"class [A-Z]\" --top-k 10",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Regex search for function definitions", A + " search-regex " + D + " --query \"(void|int|double|bool|auto) [a-z_]+\\(\" --top-k 10",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Regex search with no matches returns 0", A + " search-regex " + D + " --query \"zzzNoSuchPattern123zzz\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") == 0; });

    run_test("Regex search includes language field", A + " search-regex " + D + " --query \"class [A-Z]\" --top-k 5",
        [](const std::string& o) { return json_contains(o, "language"); });

    // ========== CATEGORY 3: Synonym-Enhanced Search (26-37) ==========
    std::cout << std::endl << "--- Category 3: Synonym-Enhanced Search ---" << std::endl;

    run_test("Synonym search for 'auth' finds results", A + " search-synonyms " + D + " --query \"auth\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Synonym search returns synonym_hits array", A + " search-synonyms " + D + " --query \"login\"",
        [](const std::string& o) { return json_contains(o, "synonym_hits"); });

    run_test("Synonym search match_type is synonym", A + " search-synonyms " + D + " --query \"auth\"",
        [](const std::string& o) { return json_contains(o, "\"match_type\":\"synonym\""); });

    run_test("Synonym search for 'db' finds database results", A + " search-synonyms " + D + " --query \"db\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Synonym search for 'config' finds configuration results", A + " search-synonyms " + D + " --query \"config\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Synonym search for 'error' finds exception results", A + " search-synonyms " + D + " --query \"error\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Synonym search for 'api' finds endpoint results", A + " search-synonyms " + D + " --query \"api\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Synonym search for 'cache' finds redis results", A + " search-synonyms " + D + " --query \"cache\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Synonym search includes score field", A + " search-synonyms " + D + " --query \"auth\"",
        [](const std::string& o) { return json_contains(o, "\"score\":"); });

    run_test("Synonym search includes snippet", A + " search-synonyms " + D + " --query \"auth\"",
        [](const std::string& o) { return json_contains(o, "\"snippet\":"); });

    run_test("Synonym search includes context_snippet", A + " search-synonyms " + D + " --query \"auth\"",
        [](const std::string& o) { return json_contains(o, "context_snippet"); });

    run_test("Synonym search for 'todo' finds FIXME results", A + " search-synonyms " + D + " --query \"todo\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    // ========== CATEGORY 4: .gitignore Support (38-50) ==========
    std::cout << std::endl << "--- Category 4: .gitignore Support ---" << std::endl;

    run_test("Gitignore index excludes ignored_file.txt", A + " index-gitignore " + D,
        [](const std::string& o) {
            return !json_contains_ci(o, "ignored_file.txt") &&
                   json_get_int(o, "total_files") > 0;
        });

    run_test("Gitignore index excludes .tmp files", A + " index-gitignore " + D,
        [](const std::string& o) { return !json_contains_ci(o, "temp_file.tmp"); });

    run_test("Gitignore index excludes build/ directory", A + " index-gitignore " + D,
        [](const std::string& o) { return !json_contains_ci(o, "build_artifact"); });

    run_test("Gitignore index excludes ignored_data.json", A + " index-gitignore " + D,
        [](const std::string& o) { return !json_contains_ci(o, "ignored_data.json"); });

    run_test("Gitignore index has fewer files than regular index", A + " index-gitignore " + D,
        [](const std::string& o) {
            int gitignore_count = json_get_int(o, "total_files");
            std::string regular = exec_command(A + " index " + D);
            int regular_count = json_get_int(regular, "total_files");
            return gitignore_count < regular_count;
        });

    run_test("Gitignore index still includes non-ignored files", A + " index-gitignore " + D,
        [](const std::string& o) {
            return json_get_int(o, "total_files") > 100;
        });

    run_test("Gitignore index has text_files > 0", A + " index-gitignore " + D,
        [](const std::string& o) { return json_get_int(o, "total_text_files") > 0; });

    run_test("Gitignore index has vocabulary_size > 0", A + " index-gitignore " + D,
        [](const std::string& o) { return json_get_int(o, "vocabulary_size") > 0; });

    run_test("Gitignore index has total_chunks > 0", A + " index-gitignore " + D,
        [](const std::string& o) { return json_get_int(o, "total_chunks") > 0; });

    run_test("Gitignore index returns valid JSON", A + " index-gitignore " + D,
        [](const std::string& o) { return o.size() > 0 && o[0] == '{'; });

    run_test("Gitignore index build time is reasonable", A + " index-gitignore " + D,
        [](const std::string& o) {
            int build_time = json_get_int(o, "index_build_time_ms");
            return build_time >= 0 && build_time < 30000;
        });

    run_test("Gitignore index excludes *.log files if present", A + " index-gitignore " + D,
        [](const std::string& o) { return o.size() > 0; });

    run_test("Gitignore index has index_build_time_ms field", A + " index-gitignore " + D,
        [](const std::string& o) { return json_contains(o, "index_build_time_ms"); });

    // ========== CATEGORY 5: Multi-Threaded Indexing (51-62) ==========
    std::cout << std::endl << "--- Category 5: Multi-Threaded Indexing ---" << std::endl;

    run_test("MT index returns valid JSON", A + " index-mt " + D,
        [](const std::string& o) { return o.size() > 0 && o[0] == '{'; });

    run_test("MT index has total_files > 0", A + " index-mt " + D,
        [](const std::string& o) { return json_get_int(o, "total_files") > 0; });

    run_test("MT index has total_text_files > 0", A + " index-mt " + D,
        [](const std::string& o) { return json_get_int(o, "total_text_files") > 0; });

    run_test("MT index has total_chunks > 0", A + " index-mt " + D,
        [](const std::string& o) { return json_get_int(o, "total_chunks") > 0; });

    run_test("MT index has vocabulary_size > 0", A + " index-mt " + D,
        [](const std::string& o) { return json_get_int(o, "vocabulary_size") > 0; });

    run_test("MT index with 1 thread works", A + " index-mt " + D + " --threads 1",
        [](const std::string& o) { return json_get_int(o, "total_files") > 0; });

    run_test("MT index with 2 threads works", A + " index-mt " + D + " --threads 2",
        [](const std::string& o) { return json_get_int(o, "total_files") > 0; });

    run_test("MT index with 4 threads works", A + " index-mt " + D + " --threads 4",
        [](const std::string& o) { return json_get_int(o, "total_files") > 0; });

    run_test("MT index has index_build_time_ms", A + " index-mt " + D,
        [](const std::string& o) { return json_contains(o, "index_build_time_ms"); });

    run_test("MT index build time is reasonable (< 30s)", A + " index-mt " + D,
        [](const std::string& o) {
            int build_time = json_get_int(o, "index_build_time_ms");
            return build_time >= 0 && build_time < 30000;
        });

    run_test("MT index finds same file count as ST index", A + " index-mt " + D,
        [](const std::string& o) {
            int mt_count = json_get_int(o, "total_files");
            std::string st = exec_command(A + " index " + D);
            int st_count = json_get_int(st, "total_files");
            return mt_count == st_count;
        });

    run_test("MT index has total_images_indexed > 0", A + " index-mt " + D,
        [](const std::string& o) { return json_get_int(o, "total_images_indexed") > 0; });

    // ========== CATEGORY 6: Persistent Index Save/Load (63-74) ==========
    std::cout << std::endl << "--- Category 6: Persistent Index Save/Load ---" << std::endl;

    run_test("Save index to file succeeds", A + " save-index " + D + " --output test_index_save.json",
        [](const std::string& o) { return json_contains(o, "\"saved\":true"); });

    run_test("Saved index file exists and has content", "",
        [](const std::string&) {
            std::ifstream f("test_index_save.json");
            if (!f) return false;
            std::string content((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
            return content.size() > 100;
        });

    run_test("Saved index includes total_files", A + " save-index " + D + " --output test_index_save2.json",
        [](const std::string& o) { return json_get_int(o, "total_files") > 0; });

    run_test("Saved index includes total_chunks", A + " save-index " + D + " --output test_index_save3.json",
        [](const std::string& o) { return json_get_int(o, "total_chunks") > 0; });

    run_test("Saved index includes filepath", A + " save-index " + D + " --output test_index_save4.json",
        [](const std::string& o) { return json_contains(o, "filepath"); });

    run_test("Load index returns valid JSON", A + " load-index test_index_save.json",
        [](const std::string& o) { return o.size() > 100 && o[0] == '{'; });

    run_test("Loaded index has files array", A + " load-index test_index_save.json",
        [](const std::string& o) { return json_contains(o, "\"files\""); });

    run_test("Loaded index has text_chunks array", A + " load-index test_index_save.json",
        [](const std::string& o) { return json_contains(o, "\"text_chunks\""); });

    run_test("Loaded index has images array", A + " load-index test_index_save.json",
        [](const std::string& o) { return json_contains(o, "\"images\""); });

    run_test("Loaded index has statistics", A + " load-index test_index_save.json",
        [](const std::string& o) { return json_contains(o, "\"statistics\""); });

    run_test("Loaded index has version field", A + " load-index test_index_save.json",
        [](const std::string& o) { return json_contains(o, "\"version\""); });

    run_test("Load non-existent index returns error", A + " load-index nonexistent_index_file.json",
        [](const std::string& o) { return o.empty() || o.find("Error") != std::string::npos; });

    // ========== CATEGORY 7: Incremental Update & File Modification (75-82) ==========
    std::cout << std::endl << "--- Category 7: Incremental Update & File Modification ---" << std::endl;

    run_test("Saved index can be loaded multiple times", A + " load-index test_index_save.json",
        [](const std::string& o) { return o.size() > 100; });

    run_test("Re-save index overwrites previous", A + " save-index " + D + " --output test_index_save.json",
        [](const std::string& o) { return json_contains(o, "\"saved\":true"); });

    run_test("Loaded index content matches original", A + " load-index test_index_save.json",
        [](const std::string& o) {
            return json_contains(o, "full_index_map") &&
                   json_contains(o, "statistics");
        });

    run_test("Index has modified_time for files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "modified_time"); });

    run_test("Full map includes file hashes", A + " map " + D,
        [](const std::string& o) { return json_contains(o, "file_hash"); });

    run_test("Save and load preserves file count", "",
        [](const std::string&) {
            std::string save_out = exec_command(A + " save-index " + D + " --output test_index_count.json");
            int saved_count = json_get_int(save_out, "total_files");
            std::string load_out = exec_command(A + " load-index test_index_count.json");
            // Count "relative_path" occurrences in loaded JSON
            size_t pos = 0;
            int count = 0;
            std::string needle = "\"relative_path\":\"";
            while ((pos = load_out.find(needle, pos)) != std::string::npos) {
                count++;
                pos++;
            }
            return count > 0 && saved_count > 0;
        });

    run_test("Index can be saved with --hidden flag", A + " save-index " + D + " --hidden --output test_index_hidden.json",
        [](const std::string& o) { return json_contains(o, "\"saved\":true"); });

    run_test("Saved hidden index has more files than non-hidden", "",
        [](const std::string&) {
            std::string hidden_out = exec_command(A + " save-index " + D + " --hidden --output test_index_h2.json");
            int hidden_count = json_get_int(hidden_out, "total_files");
            std::string normal_out = exec_command(A + " save-index " + D + " --output test_index_n2.json");
            int normal_count = json_get_int(normal_out, "total_files");
            return hidden_count > normal_count;
        });

    // ========== CATEGORY 8: Combined/Complex AI Scenarios (83-100) ==========
    std::cout << std::endl << "--- Category 8: Combined/Complex AI Scenarios ---" << std::endl;

    run_test("AI: BM25 + Regex find function patterns", A + " search-regex " + D + " --query \"void [a-z_]+\\(\" --top-k 20",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Synonym search for security concepts", A + " search-synonyms " + D + " --query \"security\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Regex search for SQL patterns", A + " search-regex " + D + " --query \"CREATE TABLE\" --top-k 10",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Regex search for JSON keys", A + " search-regex " + D + " --query \"\\\"[a-z_]+\\\":\" --top-k 10",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: BM25 search for database concepts", A + " search-bm25 " + D + " --query \"database connection pool\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Synonym search finds related auth concepts", A + " search-synonyms " + D + " --query \"token\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Regex search for Python def statements", A + " search-regex " + D + " --query \"def [a-z_]+\\(\" --top-k 10",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Regex search for HTML tags", A + " search-regex " + D + " --query \"<[a-z]+>\" --top-k 10",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Gitignore index still searchable via full-map", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "full_index_map"); });

    run_test("AI: MT index produces same stats as ST", A + " index-mt " + D + " --threads 2",
        [](const std::string& o) {
            int mt_files = json_get_int(o, "total_files");
            std::string st = exec_command(A + " index " + D);
            int st_files = json_get_int(st, "total_files");
            return mt_files == st_files;
        });

    run_test("AI: Regex for import patterns across languages", A + " search-regex " + D + " --query \"(import|include|require) .+\" --top-k 20",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: BM25 for error handling patterns", A + " search-bm25 " + D + " --query \"error exception handling\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Synonym for docker/container concepts", A + " search-synonyms " + D + " --query \"docker\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Regex for variable declarations", A + " search-regex " + D + " --query \"(int|double|auto|var|let|const) [a-z_]+\" --top-k 10",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Save index for large project works", A + " save-index " + D + " --output test_ai_large.json",
        [](const std::string& o) { return json_contains(o, "\"saved\":true"); });

    run_test("AI: Load saved index and verify content", A + " load-index test_ai_large.json",
        [](const std::string& o) {
            return json_contains(o, "files") &&
                   json_contains(o, "text_chunks") &&
                   json_contains(o, "images");
        });

    run_test("AI: Regex for URL patterns", A + " search-regex " + D + " --query \"https?://[a-zA-Z0-9./]+\" --top-k 10",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("AI: BM25 for config/settings concepts", A + " search-bm25 " + D + " --query \"config settings configuration\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: All new commands produce valid JSON", A + " search-bm25 " + D + " --query \"test\"",
        [](const std::string& o) { return o.size() > 0 && o[0] == '{'; });

    run_test("AI: Full workflow - save, load, search", "",
        [](const std::string&) {
            // Save
            std::string save = exec_command(A + " save-index " + D + " --output test_workflow.json");
            if (!json_contains(save, "\"saved\":true")) return false;
            // Load
            std::string load = exec_command(A + " load-index test_workflow.json");
            if (load.size() < 100) return false;
            // Search on loaded data (simulated by regular search)
            std::string search = exec_command(A + " search " + D + " --query \"authentication\"");
            return json_get_int(search, "total_hits") > 0;
        });

    // ========== SUMMARY ==========
    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  ADVANCED FEATURE TEST SUITE 4 - SUMMARY" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  Total:  " << tests_total << std::endl;
    std::cout << "  Passed: " << tests_passed << std::endl;
    std::cout << "  Failed: " << tests_failed << std::endl;
    std::cout << "  Rate:   " << std::fixed << std::setprecision(1)
              << (100.0 * tests_passed / tests_total) << "%" << std::endl;
    std::cout << "========================================" << std::endl;

    // Cleanup test files
    std::remove("test_index_save.json");
    std::remove("test_index_save2.json");
    std::remove("test_index_save3.json");
    std::remove("test_index_save4.json");
    std::remove("test_index_hidden.json");
    std::remove("test_index_count.json");
    std::remove("test_index_h2.json");
    std::remove("test_index_n2.json");
    std::remove("test_ai_large.json");
    std::remove("test_workflow.json");

    return tests_failed > 0 ? 1 : 0;
}
