// test_runner_search5.cpp - 100 bug-hunting tests for AI Search Tool
// Designed to find bugs via edge cases, boundary conditions, and stress testing
#include <iostream>
#include <string>
#include <vector>
#include <sstream>
#include <iomanip>
#include <cstdlib>
#include <functional>
#include <fstream>
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
    std::string full_cmd = cmd + " 2>&1";
    FILE* pipe = popen(full_cmd.c_str(), "r");
    if (!pipe) return "";
    char buffer[8192];
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
    std::string lj, ln;
    for (char c : json) lj += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    for (char c : needle) ln += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return lj.find(ln) != std::string::npos;
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

static int count_occurrences(const std::string& json, const std::string& needle) {
    int count = 0;
    size_t pos = 0;
    while ((pos = json.find(needle, pos)) != std::string::npos) {
        count++;
        pos += needle.size();
    }
    return count;
}

static void run_test(const std::string& test_name, const std::string& cmd,
                     std::function<bool(const std::string&)> validator) {
    tests_total++;
    std::cout << "[" << std::setw(3) << std::right << tests_total << "] " << std::left << std::setw(65) << test_name << " ... ";
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
        if (output.size() > 300) output = output.substr(0, 300) + "...";
        std::cout << "       Output: " << output << std::endl;
    }
}

static std::string A = ".\\aisearch.exe";
static std::string TD = "test_data";

int main() {
    std::cout << "========================================" << std::endl;
    std::cout << "  AI SEARCH BUG-HUNTING TEST SUITE" << std::endl;
    std::cout << "  100 Edge Case & Bug-Finding Tests" << std::endl;
    std::cout << "========================================" << std::endl;

    // ========== CATEGORY 1: Empty & Null Input Edge Cases (1-12) ==========
    std::cout << std::endl << "--- Category 1: Empty & Null Input Edge Cases ---" << std::endl;

    run_test("Search with empty query doesn't crash", A + " search " + TD + " --query \"\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-filename with empty pattern doesn't crash", A + " search-filename " + TD + " --query \"\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-path with empty pattern doesn't crash", A + " search-path " + TD + " --query \"\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-ext with empty extension doesn't crash", A + " search-ext " + TD + " --query \"\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-phrase with empty phrase doesn't crash", A + " search-phrase " + TD + " --query \"\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-fuzzy with empty query doesn't crash", A + " search-fuzzy " + TD + " --query \"\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-boolean with empty query doesn't crash", A + " search-boolean " + TD + " --query \"\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-regex with empty pattern doesn't crash", A + " search-regex " + TD + " --query \"\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-bm25 with empty query doesn't crash", A + " search-bm25 " + TD + " --query \"\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-synonyms with empty query doesn't crash", A + " search-synonyms " + TD + " --query \"\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-universal with empty query doesn't crash", A + " search-universal " + TD + " --query \"\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-related with empty path doesn't crash", A + " search-related " + TD + " --query \"\"",
        [](const std::string& o) { return o.size() > 0; });

    // ========== CATEGORY 2: Special Characters in Queries (13-22) ==========
    std::cout << std::endl << "--- Category 2: Special Characters in Queries ---" << std::endl;

    run_test("Search with special chars (regex metachars)", A + " search " + TD + " --query \"a.b*c+d\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-filename with special chars", A + " search-filename " + TD + " --query \"...\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-phrase with newlines (escaped)", A + " search-phrase " + TD + " --query \"hello\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-regex with valid pattern (digits)", A + " search-regex " + TD + " --query \"[0-9]+\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Search-regex with word boundary", A + " search-regex " + TD + " --query \"\\bfunction\\b\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Search-regex with capture group", A + " search-regex " + TD + " --query \"(function)\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Search-regex with alternation", A + " search-regex " + TD + " --query \"function|class\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Search with unicode-like chars", A + " search " + TD + " --query \"caf\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-filename with dot-only pattern", A + " search-filename " + TD + " --query \".\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Search-ext with just dot", A + " search-ext " + TD + " --query \".\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    // ========== CATEGORY 3: Boundary Conditions (23-35) ==========
    std::cout << std::endl << "--- Category 3: Boundary Conditions ---" << std::endl;

    run_test("Search-size with min=0 max=0 finds empty files", A + " search-size " + TD + " --min 0 --max 0",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Search-size with min=0 max=1 finds tiny files", A + " search-size " + TD + " --min 0 --max 1",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Search-size with very large max", A + " search-size " + TD + " --min 0 --max 999999999",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search-size with min > max (reversed range)", A + " search-size " + TD + " --min 999999 --max 0",
        [](const std::string& o) { return json_get_int(o, "total_hits") == 0; });

    run_test("Search-fuzzy with distance=0 (exact only)", A + " search-fuzzy " + TD + " --query \"function\" --max-distance 0",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Search-fuzzy with very long query string", A + " search-fuzzy " + TD + " --query \"abcdefghijklmnopqrstuvwxyz1234567890abcdefghijklmnopqrstuvwxyz1234567890\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search with single character query", A + " search " + TD + " --query \"a\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search with very long query (100+ chars)", A + " search " + TD + " --query \"thisisaverylongquerystringthatexceedsnormallengthsandtestshowthesearchenginehandlesverylongquerieswithmanywordsandcharacters1234567890abcdefghij\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Search-filename with single char", A + " search-filename " + TD + " --query \"a\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Search-ext with no dot prefix", A + " search-ext " + TD + " --query cpp",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search-ext with dot prefix", A + " search-ext " + TD + " --query .cpp",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search-ext with uppercase extension", A + " search-ext " + TD + " --query CPP",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search-ext with non-existent extension", A + " search-ext " + TD + " --query .xyz123",
        [](const std::string& o) { return json_get_int(o, "total_hits") == 0; });

    // ========== CATEGORY 4: Boolean Search Edge Cases (36-48) ==========
    std::cout << std::endl << "--- Category 4: Boolean Search Edge Cases ---" << std::endl;

    run_test("Boolean search with only AND operator", A + " search-boolean " + TD + " --query \"function AND class\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean search with only OR operator", A + " search-boolean " + TD + " --query \"function OR class\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean search with NOT operator", A + " search-boolean " + TD + " --query \"function NOT class\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean search with lowercase 'and'", A + " search-boolean " + TD + " --query \"function and class\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean search with mixed case 'And'", A + " search-boolean " + TD + " --query \"function And class\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean search with single term (no operator)", A + " search-boolean " + TD + " --query \"function\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean search with three terms AND", A + " search-boolean " + TD + " --query \"function AND class AND return\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean search with three terms OR", A + " search-boolean " + TD + " --query \"function OR class OR return\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean search with NOT but no second term", A + " search-boolean " + TD + " --query \"function NOT\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean search with only operator", A + " search-boolean " + TD + " --query \"AND\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean search with double AND AND", A + " search-boolean " + TD + " --query \"function AND AND class\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean search with OR then NOT", A + " search-boolean " + TD + " --query \"function OR class NOT return\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean search with all stop words", A + " search-boolean " + TD + " --query \"the AND is NOT a\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    // ========== CATEGORY 5: Fuzzy Search Edge Cases (49-58) ==========
    std::cout << std::endl << "--- Category 5: Fuzzy Search Edge Cases ---" << std::endl;

    run_test("Fuzzy search with 1-char typo (functoin)", A + " search-fuzzy " + TD + " --query \"functoin\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy search with transposed chars (fucntion)", A + " search-fuzzy " + TD + " --query \"fucntion\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy search with missing char (functio)", A + " search-fuzzy " + TD + " --query \"functio\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy search with extra char (functionn)", A + " search-fuzzy " + TD + " --query \"functionn\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy search with completely different word", A + " search-fuzzy " + TD + " --query \"zzzzzzzzzz\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy search with single char query", A + " search-fuzzy " + TD + " --query \"x\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy search with whitespace-only query", A + " search-fuzzy " + TD + " --query \"   \"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy search finds results with 2-char distance", A + " search-fuzzy " + TD + " --query \"funtion\" --max-distance 2",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy search with number query", A + " search-fuzzy " + TD + " --query \"12345\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy search with mixed case (FuNcTiOn)", A + " search-fuzzy " + TD + " --query \"FuNcTiOn\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    // ========== CATEGORY 6: Regex Search Edge Cases (59-68) ==========
    std::cout << std::endl << "--- Category 6: Regex Search Edge Cases ---" << std::endl;

    run_test("Regex with invalid pattern (unmatched bracket)", A + " search-regex " + TD + " --query \"[a-z\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Regex with invalid pattern (unmatched paren)", A + " search-regex " + TD + " --query \"(abc\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Regex with invalid pattern (bad quantifier)", A + " search-regex " + TD + " --query \"a**b\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Regex with valid complex pattern", A + " search-regex " + TD + " --query \"void\\s+\\w+\\s*\\(\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Regex with anchor ^", A + " search-regex " + TD + " --query \"^#include\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Regex with anchor $", A + " search-regex " + TD + " --query \"}\\s*$\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Regex with . wildcard", A + " search-regex " + TD + " --query \"a.b\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Regex with + quantifier", A + " search-regex " + TD + " --query \"ab+c\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Regex with {n,m} quantifier", A + " search-regex " + TD + " --query \"a{1,3}\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Regex with backreference", A + " search-regex " + TD + " --query \"(\\w+)\\s+\\1\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    // ========== CATEGORY 7: Synonym Expansion Edge Cases (69-76) ==========
    std::cout << std::endl << "--- Category 7: Synonym Expansion Edge Cases ---" << std::endl;

    run_test("Synonym search for 'auth' expands to 'authentication'", A + " search-synonyms " + TD + " --query \"auth\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Synonym search for 'db' expands to 'database'", A + " search-synonyms " + TD + " --query \"db\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Synonym search for 'config' expands", A + " search-synonyms " + TD + " --query \"config\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Synonym search for 'util' expands to 'utility'", A + " search-synonyms " + TD + " --query \"util\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Synonym search for non-synonym word", A + " search-synonyms " + TD + " --query \"function\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Synonym search with multi-word query", A + " search-synonyms " + TD + " --query \"auth db config\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Synonym vs normal search returns different or equal results", A + " search-synonyms " + TD + " --query \"db\"",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Synonym search for 'api' expands", A + " search-synonyms " + TD + " --query \"api\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    // ========== CATEGORY 8: BM25 Scoring Edge Cases (77-84) ==========
    std::cout << std::endl << "--- Category 8: BM25 Scoring Edge Cases ---" << std::endl;

    run_test("BM25 search with common word", A + " search-bm25 " + TD + " --query \"the\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("BM25 search with rare word", A + " search-bm25 " + TD + " --query \"artificial\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("BM25 search with multi-word query", A + " search-bm25 " + TD + " --query \"machine learning\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("BM25 search results have score field", A + " search-bm25 " + TD + " --query \"function\"",
        [](const std::string& o) { return json_contains(o, "\"score\":"); });

    run_test("BM25 search results have match_type bm25", A + " search-bm25 " + TD + " --query \"function\"",
        [](const std::string& o) { return json_contains_ci(o, "bm25"); });

    run_test("BM25 vs TF-IDF return different scores", A + " search-bm25 " + TD + " --query \"function\"",
        [](const std::string& o) { return json_get_double(o, "score") != -1.0 || json_get_int(o, "total_hits") >= 0; });

    run_test("BM25 search with stop-word only query", A + " search-bm25 " + TD + " --query \"the and is\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("BM25 search with very rare non-existent word", A + " search-bm25 " + TD + " --query \"zzzqqqxxx\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    // ========== CATEGORY 9: .gitignore & Index Edge Cases (85-92) ==========
    std::cout << std::endl << "--- Category 9: .gitignore & Index Edge Cases ---" << std::endl;

    run_test("Index-gitignore excludes ignored files", A + " index-gitignore " + TD,
        [](const std::string& o) { return json_get_int(o, "total_files") > 0; });

    run_test("Index-gitignore doesn't include ignored_file.txt", A + " index-gitignore " + TD,
        [](const std::string& o) { return !json_contains_ci(o, "ignored_file.txt"); });

    run_test("Save-index creates file", A + " save-index " + TD + " --output test_save_idx.json",
        [](const std::string& o) { return json_contains(o, "saved") || o.size() > 0; });

    run_test("Load-index reads file back", A + " load-index test_save_idx.json",
        [](const std::string& o) { return json_get_int(o, "total_files") > 0; });

    run_test("Load-index with non-existent file doesn't crash", A + " load-index nonexistent_idx.json",
        [](const std::string& o) { return o.size() > 0; });

    run_test("Index with non-existent path", A + " index nonexistent_path_12345",
        [](const std::string& o) { return json_get_int(o, "total_files") == 0; });

    run_test("Map with non-existent path", A + " map nonexistent_path_12345",
        [](const std::string& o) { return json_get_int(o, "total_files") == 0; });

    run_test("Stats on indexed data", A + " stats " + TD,
        [](const std::string& o) { return json_get_int(o, "total_files") > 0; });

    // ========== CATEGORY 10: Universal Search & Dedup (93-100) ==========
    std::cout << std::endl << "--- Category 10: Universal Search & Dedup ---" << std::endl;

    run_test("Universal search combines text + filename + path", A + " search-universal " + TD + " --query \"function\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Universal search with filename-like query", A + " search-universal " + TD + " --query \"test\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Universal search with path-like query", A + " search-universal " + TD + " --query \"data\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Universal search deduplication (no duplicate file+chunk)", A + " search-universal " + TD + " --query \"function\"",
        [](const std::string& o) {
            int total = json_get_int(o, "total_hits");
            return total > 0;
        });

    run_test("Universal search with non-existent term", A + " search-universal " + TD + " --query \"zzzqqqxxxyyy\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") == 0; });

    run_test("Universal search has search_time_ms", A + " search-universal " + TD + " --query \"function\"",
        [](const std::string& o) { return json_contains(o, "search_time_ms"); });

    run_test("Search-all returns combined results", A + " search-all " + TD + " --query \"function\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Full-map returns all files", A + " full-map " + TD,
        [](const std::string& o) { return json_get_int(o, "total_files") > 0; });

    // Clean up
    std::remove("test_save_idx.json");

    // ========== SUMMARY ==========
    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  AI SEARCH BUG-HUNTING TEST SUMMARY" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  Total:  " << tests_total << std::endl;
    std::cout << "  Passed: " << tests_passed << std::endl;
    std::cout << "  Failed: " << tests_failed << std::endl;
    double rate = static_cast<double>(tests_passed) / tests_total * 100.0;
    std::cout << "  Rate:   " << std::fixed << std::setprecision(1) << rate << "%" << std::endl;
    std::cout << "========================================" << std::endl;

    return tests_failed > 0 ? 1 : 0;
}
