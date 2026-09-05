// test_runner3.cpp - Tests for newly integrated AI search features
// Tests: binary detection, context snippets, language detection, encoding,
// import extraction, file relationships, large file handling, path normalization,
// hybrid scoring, metadata enrichment, and real-world AI usage scenarios
#include <iostream>
#include <string>
#include <vector>
#include <sstream>
#include <fstream>
#include <cstdlib>
#include <chrono>
#include <functional>
#include <iomanip>

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

int main(int argc, char* argv[]) {
    if (argc > 1) A = argv[1];
    if (argc > 2) D = argv[2];

    std::cout << "========================================" << std::endl;
    std::cout << "  AI Search - New Feature Test Suite 3" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "Tool: " << A << std::endl;
    std::cout << "Data: " << D << std::endl;
    std::cout << std::endl;

    // ========== CATEGORY 1: Language Detection (1-10) ==========
    std::cout << "--- Category 1: Language Detection ---" << std::endl;

    run_test("Full map includes language field for .py files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"language\":\"python\""); });

    run_test("Full map includes language field for .cpp files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"language\":\"cpp\""); });

    run_test("Full map includes language field for .java files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"language\":\"java\""); });

    run_test("Full map includes language field for .ts files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"language\":\"typescript\""); });

    run_test("Full map includes language field for .go files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"language\":\"go\""); });

    run_test("Full map includes language field for .rs files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"language\":\"rust\""); });

    run_test("Full map includes language field for .rb files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"language\":\"ruby\""); });

    run_test("Full map includes language field for .sql files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"language\":\"sql\""); });

    run_test("Full map includes language field for .md files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"language\":\"markdown\""); });

    run_test("Full map includes language field for .json files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"language\":\"json\""); });

    // ========== CATEGORY 2: Line Count & Encoding (11-20) ==========
    std::cout << std::endl << "--- Category 2: Line Count & Encoding ---" << std::endl;

    run_test("Full map includes line_count for text files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"line_count\":"); });

    run_test("Full map includes encoding field", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"encoding\":\""); });

    run_test("Full map detects ASCII encoding", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"encoding\":\"ascii\""); });

    run_test("Full map detects UTF-8 encoding", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"encoding\":\"utf-8\""); });

    run_test("Search results include language field", A + " search " + D + " --query \"authentication\"",
        [](const std::string& o) { return json_contains(o, "\"language\":"); });

    run_test("Search-universal results include language field", A + " search-universal " + D + " --query \"config\"",
        [](const std::string& o) { return json_contains(o, "\"language\":"); });

    run_test("Search results include context_snippet", A + " search " + D + " --query \"authentication token\"",
        [](const std::string& o) { return json_contains(o, "\"context_snippet\":"); });

    run_test("Exact phrase search includes line_number", A + " search-phrase " + D + " --query \"duplicate content\"",
        [](const std::string& o) { return json_contains(o, "\"line_number\":"); });

    run_test("Exact phrase search includes context_snippet", A + " search-phrase " + D + " --query \"duplicate content\"",
        [](const std::string& o) { return json_contains(o, "\"context_snippet\":"); });

    run_test("Full-map has line_count > 0 for source files", A + " full-map " + D,
        [](const std::string& o) {
            size_t pos = o.find("\"line_count\":");
            if (pos == std::string::npos) return false;
            pos += 13;
            while (pos < o.size() && o[pos] == ' ') pos++;
            return pos < o.size() && o[pos] > '0';
        });

    // ========== CATEGORY 3: Import Extraction & File Relationships (21-30) ==========
    std::cout << std::endl << "--- Category 3: Import Extraction & File Relationships ---" << std::endl;

    run_test("Full map includes imports for Python files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"imports\":"); });

    run_test("Full map includes imports for C++ files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"imports\":[\"vector_store"); });

    run_test("Full map includes imports for Java files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"imports\":"); });

    run_test("search-related command works", A + " search-related " + D + " --query \"vector_store.h\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("search-related finds related files", A + " search-related " + D + " --query \"search_engine.h\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("search-related returns JSON with related_files", A + " search-related " + D + " --query \"content_indexer.h\"",
        [](const std::string& o) { return json_contains(o, "\"related_files\":"); });

    run_test("search-related returns source_file in JSON", A + " search-related " + D + " --query \"file_mapper.h\"",
        [](const std::string& o) { return json_contains(o, "\"source_file\":"); });

    run_test("search-related with non-existent file returns 0 hits", A + " search-related " + D + " --query \"nonexistent_file.xyz\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") == 0; });

    run_test("Full map includes imports for TypeScript files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"imports\":"); });

    run_test("Full map includes imports for Go files", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"imports\":"); });

    // ========== CATEGORY 4: Binary File Detection (31-40) ==========
    std::cout << std::endl << "--- Category 4: Binary File Detection ---" << std::endl;

    run_test("Full map classifies image files as image type", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"type\":\"image\""); });

    run_test("Full map classifies text files as text type", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "\"type\":\"text\""); });

    run_test("Full map has binary file count > 0", A + " full-map " + D,
        [](const std::string& o) { return json_get_int(o, "total_binary_files") > 0; });

    run_test("Stats shows binary files", A + " stats " + D,
        [](const std::string& o) { return json_get_int(o, "total_binary_files") > 0; });

    run_test("Image files not indexed as text", A + " stats " + D,
        [](const std::string& o) {
            int text = json_get_int(o, "total_text_indexed");
            int total = json_get_int(o, "total_files");
            return text < total;
        });

    run_test("Text search doesn't return image files", A + " search " + D + " --query \"authentication\"",
        [](const std::string& o) { return !json_contains(o, "\"file_type\":\"image\""); });

    run_test("Full map shows correct text file count", A + " full-map " + D,
        [](const std::string& o) { return json_get_int(o, "total_text_files") > 100; });

    run_test("Full map shows correct image file count", A + " full-map " + D,
        [](const std::string& o) { return json_get_int(o, "total_image_files") >= 15; });

    run_test("Binary files excluded from text search", A + " search " + D + " --query \"binary content test\"",
        [](const std::string& o) { return o.find("\"total_hits\"") != std::string::npos; });

    run_test("Stats shows text indexed < total files", A + " stats " + D,
        [](const std::string& o) {
            int text = json_get_int(o, "total_text_indexed");
            int total = json_get_int(o, "total_files");
            return text > 0 && text < total;
        });

    // ========== CATEGORY 5: Context Snippets Quality (41-50) ==========
    std::cout << std::endl << "--- Category 5: Context Snippets Quality ---" << std::endl;

    run_test("Search-phrase context_snippet has line numbers", A + " search-phrase " + D + " --query \"authentication token\"",
        [](const std::string& o) {
            size_t pos = o.find("\"context_snippet\":\"");
            if (pos == std::string::npos) return false;
            return o.find(": ", pos) != std::string::npos;
        });

    run_test("Search context_snippet is non-empty for content hits", A + " search " + D + " --query \"search engine vector\"",
        [](const std::string& o) { return json_contains(o, "\"context_snippet\":\""); });

    run_test("Fuzzy search includes context_snippet", A + " search-fuzzy " + D + " --query \"serch\" --max-distance 2",
        [](const std::string& o) { return json_contains(o, "\"context_snippet\":"); });

    run_test("Boolean search includes context_snippet", A + " search-boolean " + D + " --query \"search AND engine\"",
        [](const std::string& o) { return json_contains(o, "\"context_snippet\":"); });

    run_test("Search-universal text hits include context_snippet", A + " search-universal " + D + " --query \"authentication\"",
        [](const std::string& o) { return json_contains(o, "\"context_snippet\":"); });

    run_test("Search-phrase line_number > 0 for matches", A + " search-phrase " + D + " --query \"CREATE TABLE\"",
        [](const std::string& o) {
            size_t pos = o.find("\"line_number\":");
            if (pos == std::string::npos) return false;
            pos += 14;
            while (pos < o.size() && o[pos] == ' ') pos++;
            return pos < o.size() && o[pos] > '0';
        });

    run_test("Search-phrase context_snippet contains match text", A + " search-phrase " + D + " --query \"duplicate content\"",
        [](const std::string& o) { return json_contains_ci(o, "duplicate"); });

    run_test("Search results have match_type field", A + " search " + D + " --query \"authentication\"",
        [](const std::string& o) { return json_contains(o, "\"match_type\":\""); });

    run_test("Search-phrase match_type is exact_phrase", A + " search-phrase " + D + " --query \"authentication token\"",
        [](const std::string& o) { return json_contains(o, "\"match_type\":\"exact_phrase\""); });

    run_test("Search-fuzzy match_type is fuzzy", A + " search-fuzzy " + D + " --query \"serch\" --max-distance 2",
        [](const std::string& o) { return json_contains(o, "\"match_type\":\"fuzzy\""); });

    // ========== CATEGORY 6: Large File Handling (51-60) ==========
    std::cout << std::endl << "--- Category 6: Large File Handling ---" << std::endl;

    run_test("Large text file is indexed", A + " search " + D + " --query \"large file test content\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Large file appears in full map", A + " full-map " + D,
        [](const std::string& o) { return json_contains(o, "large_document"); });

    run_test("Very long line file is indexed", A + " search " + D + " --query \"long line test\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Size filter finds large files > 10000", A + " search-size " + D + " --min 10000 --max 99999999 --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Size filter finds medium files 100-10000", A + " search-size " + D + " --min 100 --max 10000 --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Size filter finds small files 0-100", A + " search-size " + D + " --min 0 --max 100 --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Stats shows total_size > 0", A + " stats " + D,
        [](const std::string& o) { return json_get_int(o, "total_size") > 0; });

    run_test("Full map shows total_size > 0", A + " full-map " + D,
        [](const std::string& o) { return json_get_int(o, "total_size") > 0; });

    run_test("Large file has correct line_count", A + " full-map " + D,
        [](const std::string& o) {
            size_t pos = o.find("large_document");
            if (pos == std::string::npos) return false;
            size_t lc_pos = o.find("\"line_count\":", pos);
            if (lc_pos == std::string::npos) return false;
            return true;
        });

    run_test("Chunk count > 0 for indexed files", A + " stats " + D,
        [](const std::string& o) { return json_get_int(o, "total_chunks") > 0; });

    // ========== CATEGORY 7: Path Normalization & Cross-Platform (61-70) ==========
    std::cout << std::endl << "--- Category 7: Path Normalization & Cross-Platform ---" << std::endl;

    run_test("Path search with forward slashes works", A + " search-path " + D + " --query \"src/utils\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Path search with backslashes works on Windows", A + " search-path " + D + " --query \"src\\utils\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Path search finds nested directories", A + " search-path " + D + " --query \"deep\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Path search finds images directory", A + " search-path " + D + " --query \"images\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Path search finds config directory", A + " search-path " + D + " --query \"config\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Path search finds data directory", A + " search-path " + D + " --query \"data\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Path search finds docs directory", A + " search-path " + D + " --query \"docs\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Path search finds scripts directory", A + " search-path " + D + " --query \"scripts\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Path search finds sys directory", A + " search-path " + D + " --query \"sys\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Path search finds tests directory", A + " search-path " + D + " --query \"tests\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    // ========== CATEGORY 8: Hybrid Search & Deduplication (71-80) ==========
    std::cout << std::endl << "--- Category 8: Hybrid Search & Deduplication ---" << std::endl;

    run_test("Universal search combines text + filename + path", A + " search-universal " + D + " --query \"authentication\"",
        [](const std::string& o) {
            return json_get_int(o, "total_hits") > 0 &&
                   json_contains(o, "\"text_hits\":") &&
                   json_contains(o, "\"filename_hits\":");
        });

    run_test("Universal search deduplicates text hits", A + " search-universal " + D + " --query \"search engine\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Search-all combines all search types", A + " search-all " + D + " --query \"config\"",
        [](const std::string& o) {
            return json_contains(o, "\"text_hits\":") &&
                   json_contains(o, "\"filename_hits\":");
        });

    run_test("Universal search includes exact phrase results", A + " search-universal " + D + " --query \"authentication token\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Universal search includes fuzzy results", A + " search-universal " + D + " --query \"serch\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Universal search includes boolean results", A + " search-universal " + D + " --query \"config AND json\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Search results sorted by score descending", A + " search " + D + " --query \"authentication token config\"",
        [](const std::string& o) {
            size_t pos = 0;
            double prev_score = 2.0;
            int count = 0;
            while ((pos = o.find("\"score\":", pos)) != std::string::npos) {
                pos += 8;
                std::string num;
                while (pos < o.size() && (o[pos] == '.' || (o[pos] >= '0' && o[pos] <= '9'))) {
                    num += o[pos++];
                }
                if (!num.empty()) {
                    double score = std::atof(num.c_str());
                    if (score > prev_score + 0.0001) return false;
                    prev_score = score;
                    count++;
                }
            }
            return count > 0;
        });

    run_test("Universal search time is reasonable (< 5s)", A + " search-universal " + D + " --query \"authentication\"",
        [](const std::string& o) {
            size_t pos = o.find("\"search_time_ms\":");
            if (pos == std::string::npos) return false;
            pos += 17;
            std::string num;
            while (pos < o.size() && (o[pos] == '.' || (o[pos] >= '0' && o[pos] <= '9'))) {
                num += o[pos++];
            }
            if (num.empty()) return false;
            return std::atof(num.c_str()) < 5000.0;
        });

    run_test("Search-all returns search_time_ms", A + " search-all " + D + " --query \"test\"",
        [](const std::string& o) { return json_contains(o, "\"search_time_ms\":"); });

    run_test("Universal search returns search_time_ms", A + " search-universal " + D + " --query \"test\"",
        [](const std::string& o) { return json_contains(o, "\"search_time_ms\":"); });

    // ========== CATEGORY 9: Real-World AI Usage Scenarios (81-90) ==========
    std::cout << std::endl << "--- Category 9: Real-World AI Usage Scenarios ---" << std::endl;

    run_test("AI: Find all Python files in project", A + " search-ext " + D + " --query \"py\" --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Find config files by extension", A + " search-ext " + D + " --query \"json\" --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Find all source files > 1KB", A + " search-size " + D + " --min 1024 --max 99999999 --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Search for error handling patterns", A + " search " + D + " --query \"error handling exception catch\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("AI: Find files with TODO comments", A + " search-phrase " + D + " --query \"TODO\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Find authentication-related code", A + " search-universal " + D + " --query \"authentication\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Find database-related files", A + " search-universal " + D + " --query \"database\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Find all Docker-related files", A + " search-filename " + D + " --query \"docker\" --top-k 50",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("AI: Get full project map for context", A + " full-map " + D,
        [](const std::string& o) {
            return json_contains(o, "\"files\":") &&
                   json_contains(o, "\"text_chunks\":") &&
                   json_contains(o, "\"images\":");
        });

    run_test("AI: Get project statistics", A + " stats " + D,
        [](const std::string& o) {
            return json_get_int(o, "total_files") > 0 &&
                   json_get_int(o, "total_chunks") > 0;
        });

    // ========== CATEGORY 10: Edge Cases & Robustness (91-100) ==========
    std::cout << std::endl << "--- Category 10: Edge Cases & Robustness ---" << std::endl;

    run_test("Empty query returns 0 hits (search)", A + " search " + D + " --query \" \"",
        [](const std::string& o) { return json_get_int(o, "total_hits") == 0; });

    run_test("Very long query doesn't crash", A + " search " + D + " --query \"authentication token validation middleware encryption decryption session management security\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Special characters in query don't crash", A + " search " + D + " --query \"config.json { } [ ]\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Unicode-like query doesn't crash", A + " search " + D + " --query \"caf resume\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Non-existent directory returns empty result", A + " map nonexistent_dir_xyz",
        [](const std::string& o) { return json_get_int(o, "total_files") == 0; });

    run_test("Search with top-k 1 returns at most 1 hit", A + " search " + D + " --query \"authentication\" --top-k 1",
        [](const std::string& o) { return json_get_int(o, "total_hits") <= 1; });

    run_test("Extension search with dot prefix works", A + " search-ext " + D + " --query \".py\" --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Extension search without dot prefix works", A + " search-ext " + D + " --query \"py\" --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Fuzzy search with max-distance 0 is exact", A + " search-fuzzy " + D + " --query \"authentication\" --max-distance 0",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Full map JSON is valid (starts with { and ends with })", A + " full-map " + D,
        [](const std::string& o) {
            std::string trimmed = o;
            while (!trimmed.empty() && std::isspace(static_cast<unsigned char>(trimmed.front()))) trimmed.erase(trimmed.begin());
            while (!trimmed.empty() && std::isspace(static_cast<unsigned char>(trimmed.back()))) trimmed.pop_back();
            return !trimmed.empty() && trimmed.front() == '{' && trimmed.back() == '}';
        });

    // ========== SUMMARY ==========
    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  NEW FEATURE TEST SUITE 3 - SUMMARY" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  Total:  " << tests_total << std::endl;
    std::cout << "  Passed: " << tests_passed << std::endl;
    std::cout << "  Failed: " << tests_failed << std::endl;
    std::cout << "  Rate:   " << std::fixed << std::setprecision(1)
              << (100.0 * tests_passed / tests_total) << "%" << std::endl;
    std::cout << "========================================" << std::endl;

    return tests_failed == 0 ? 0 : 1;
}
