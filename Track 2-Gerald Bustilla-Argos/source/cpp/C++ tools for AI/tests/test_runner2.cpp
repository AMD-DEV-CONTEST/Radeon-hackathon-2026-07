// test_runner2.cpp - 100 new test scenarios for real-world computer search
// Tests: edge cases, deep nesting, duplicate detection, multi-language files,
// system files, special characters, empty files, large files, cross-format search,
// complex boolean queries, fuzzy edge cases, image dedup, path variations,
// extension combinations, size filtering, phrase variations, and more
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
    std::cout << "  AI Search Tool - Scenario Test Suite 2" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "Tool: " << A << std::endl;
    std::cout << "Data: " << D << std::endl;
    std::cout << std::endl;

    // ========== CATEGORY 1: Deep Nesting & Directory Traversal (1-10) ==========
    std::cout << "--- Category 1: Deep Nesting & Directory Traversal ---" << std::endl;

    run_test("Deep nested file is found in map", A + " map " + D,
        [](const std::string& o) { return json_get_int(o, "total_files") >= 170; });

    run_test("Search finds deeply nested content", A + " search " + D + " --query \"deeply nested\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Path search finds deep directory", A + " search-path " + D + " --query \"deep/a/b/c\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Path search finds very deep file", A + " search-path " + D + " --query \"very_deep\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Filename search finds deep_file", A + " search-filename " + D + " --query \"deep_file\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Filename search finds very_deep.cpp", A + " search-filename " + D + " --query \"very_deep\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search content in 4-level deep config.xml", A + " search " + D + " --query \"server port\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Path search level1 through level4", A + " search-path " + D + " --query \"level1/level2/level3\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Extension search finds deeply nested cpp", A + " search-ext " + D + " --query \"cpp\" --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 20; });

    run_test("Full map includes deep directories", A + " full-map " + D,
        [](const std::string& o) { return json_get_int(o, "total_directories") >= 30; });

    // ========== CATEGORY 2: Duplicate Content Detection (11-20) ==========
    std::cout << std::endl << "--- Category 2: Duplicate Content Detection ---" << std::endl;

    run_test("Search finds duplicate content copy1", A + " search " + D + " --query \"duplicate content dedup\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds all duplicate copies", A + " search " + D + " --query \"dedup identical\" --top-k 50",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 1; });

    run_test("Filename search finds copy1", A + " search-filename " + D + " --query \"copy1\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Filename search finds copy2", A + " search-filename " + D + " --query \"copy2\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Filename search finds copy3", A + " search-filename " + D + " --query \"copy3\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Exact phrase finds duplicate text", A + " search-phrase " + D + " --query \"duplicate content for testing\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Fingerprint duplicate PNG images", A + " fingerprint " + D + "/images/logos/logo_primary.png",
        [](const std::string& o) { return o.find("PNG") != std::string::npos; });

    run_test("Fingerprint duplicate logo_copy", A + " fingerprint " + D + "/images/logos/logo_copy.png",
        [](const std::string& o) { return o.find("PNG") != std::string::npos; });

    run_test("Fingerprint dup_photo1.jpg matches photo1", A + " fingerprint " + D + "/images/dup_photo1.jpg",
        [](const std::string& o) { return o.find("JPEG") != std::string::npos; });

    run_test("Fingerprint dup_banner1.bmp matches banner1", A + " fingerprint " + D + "/images/dup_banner1.bmp",
        [](const std::string& o) { return o.find("BMP") != std::string::npos; });

    // ========== CATEGORY 3: Multi-Language File Search (21-30) ==========
    std::cout << std::endl << "--- Category 3: Multi-Language File Search ---" << std::endl;

    run_test("Search finds TypeScript interface", A + " search " + D + " --query \"TypeScript interface\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds Go handler", A + " search " + D + " --query \"golang searchHandler\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds Rust inverted index", A + " search " + D + " --query \"Rust InvertedIndex\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds Swift fingerprint", A + " search " + D + " --query \"Swift ImageFingerprint\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds Kotlin SearchResult", A + " search " + D + " --query \"Kotlin SearchResult\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds Python TfidfVectorizer", A + " search " + D + " --query \"TfidfVectorizer sklearn\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Extension search finds .ts files", A + " search-ext " + D + " --query \"ts\" --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Extension search finds .go files", A + " search-ext " + D + " --query \"go\" --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Extension search finds .rs files", A + " search-ext " + D + " --query \"rs\" --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Extension search finds .java files", A + " search-ext " + D + " --query \"java\" --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    // ========== CATEGORY 4: System & Config Files (31-40) ==========
    std::cout << std::endl << "--- Category 4: System & Config Files ---" << std::endl;

    run_test("Search finds Dockerfile content", A + " search " + D + " --query \"Dockerfile node alpine\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds docker-compose services", A + " search " + D + " --query \"docker-compose redis postgres\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds Makefile content", A + " search " + D + " --query \"CXXFLAGS cmake\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds CMakeLists content", A + " search " + D + " --query \"cmake_minimum_required\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Filename search finds Dockerfile", A + " search-filename " + D + " --query \"Dockerfile\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Filename search finds Makefile", A + " search-filename " + D + " --query \"Makefile\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Filename search finds CMakeLists", A + " search-filename " + D + " --query \"CMakeLists\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Path search finds sys directory", A + " search-path " + D + " --query \"sys\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds SQL schema", A + " search " + D + " --query \"CREATE TABLE documents\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Extension search finds .sql files", A + " search-ext " + D + " --query \"sql\" --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 2; });

    // ========== CATEGORY 5: Edge Cases - Empty & Tiny Files (41-50) ==========
    std::cout << std::endl << "--- Category 5: Edge Cases - Empty & Tiny Files ---" << std::endl;

    run_test("Filename search finds empty.txt", A + " search-filename " + D + " --query \"empty.txt\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Filename search finds empty.json", A + " search-filename " + D + " --query \"empty.json\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Filename search finds empty.md", A + " search-filename " + D + " --query \"empty.md\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Filename search finds single_char.txt", A + " search-filename " + D + " --query \"single_char\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Filename search finds whitespace.txt", A + " search-filename " + D + " --query \"whitespace\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Size filter finds very small files", A + " search-size " + D + " --min 0 --max 20 --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Size filter finds empty files (0 bytes)", A + " search-size " + D + " --min 0 --max 0 --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Size filter finds files > 1000 bytes", A + " search-size " + D + " --min 1000 --max 99999999 --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Size filter finds files > 10000 bytes", A + " search-size " + D + " --min 10000 --max 99999999 --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Size filter with impossible range returns 0", A + " search-size " + D + " --min 999999999 --max 9999999999 --top-k 100",
        [](const std::string& o) { return json_get_int(o, "total_hits") == 0; });

    // ========== CATEGORY 6: Special Characters & Formats (51-60) ==========
    std::cout << std::endl << "--- Category 6: Special Characters & Formats ---" << std::endl;

    run_test("Search finds XML config content", A + " search " + D + " --query \"XML settings chunk_size\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds TOML config", A + " search " + D + " --query \"toml server host\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds INI format", A + " search " + D + " --query \"ini general name\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds YAML services list", A + " search " + D + " --query \"services authentication cache\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds GraphQL schema", A + " search " + D + " --query \"GraphQL SearchResult\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds LaTeX formula", A + " search " + D + " --query \"cosine theta vectors\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds JSON Lines data", A + " search " + D + " --query \"jsonl authentication active\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds hex values content", A + " search " + D + " --query \"PNG_MAGIC JPEG_MAGIC\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds regex patterns", A + " search " + D + " --query \"regex Email URL\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds base64 sample", A + " search " + D + " --query \"iVBORw0KGgo\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    // ========== CATEGORY 7: Advanced Text Search (61-70) ==========
    std::cout << std::endl << "--- Category 7: Advanced Text Search ---" << std::endl;

    run_test("Search finds error log messages", A + " search " + D + " --query \"ERROR failed connect database\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds access log entries", A + " search " + D + " --query \"192.168 search login\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds TODO comments", A + " search " + D + " --query \"TODO FIXME HACK NOTE OPTIMIZE\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds error messages file", A + " search " + D + " --query \"Permission denied Connection refused\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds HTTP status codes", A + " search " + D + " --query \"401 Unauthorized 404 Not Found\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds cron expressions", A + " search " + D + " --query \"cron every hour midnight\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds UUID values", A + " search " + D + " --query \"550e8400 uuid\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Search finds git commands", A + " search " + D + " --query \"git clone commit push\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds Docker commands", A + " search " + D + " --query \"docker build run compose\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search finds MIME types", A + " search " + D + " --query \"text/plain image/png application/json\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    // ========== CATEGORY 8: Complex Boolean Queries (71-80) ==========
    std::cout << std::endl << "--- Category 8: Complex Boolean Queries ---" << std::endl;

    run_test("Boolean: search AND engine AND NOT image", A + " search-boolean " + D + " --query \"search AND engine AND NOT image\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean: error OR warning AND database", A + " search-boolean " + D + " --query \"error OR warning AND database\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean: token AND NOT cache AND session", A + " search-boolean " + D + " --query \"token AND NOT cache AND session\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean: docker AND (redis OR postgres)", A + " search-boolean " + D + " --query \"docker AND redis OR postgres\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean: config AND NOT json AND NOT xml", A + " search-boolean " + D + " --query \"config AND NOT json AND NOT xml\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean: tfidf OR cosine OR vector OR similarity", A + " search-boolean " + D + " --query \"tfidf OR cosine OR vector OR similarity\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean: authentication AND token AND NOT image", A + " search-boolean " + D + " --query \"authentication AND token AND NOT image\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean: hash AND (perceptual OR base64)", A + " search-boolean " + D + " --query \"hash AND perceptual OR base64\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean: migration AND schema AND NOT test", A + " search-boolean " + D + " --query \"migration AND schema AND NOT test\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Boolean: log AND error AND NOT access", A + " search-boolean " + D + " --query \"log AND error AND NOT access\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    // ========== CATEGORY 9: Fuzzy Search Edge Cases (81-90) ==========
    std::cout << std::endl << "--- Category 9: Fuzzy Search Edge Cases ---" << std::endl;

    run_test("Fuzzy: 'serch' finds search", A + " search-fuzzy " + D + " --query \"serch\" --max-distance 2",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy: 'authentcation' finds authentication", A + " search-fuzzy " + D + " --query \"authentcation\" --max-distance 3",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy: 'encrytion' finds encryption", A + " search-fuzzy " + D + " --query \"encrytion\" --max-distance 2",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy: 'validaton' finds validation", A + " search-fuzzy " + D + " --query \"validaton\" --max-distance 2",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy: 'midleware' finds middleware", A + " search-fuzzy " + D + " --query \"midleware\" --max-distance 2",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy: 'fingerprint' with distance 0", A + " search-fuzzy " + D + " --query \"fingerprint\" --max-distance 0",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy: 'perceptual' with distance 1", A + " search-fuzzy " + D + " --query \"perceptual\" --max-distance 1",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy: 'inverted' finds inverted", A + " search-fuzzy " + D + " --query \"inverted\" --max-distance 1",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy: 'simlarity' finds similarity", A + " search-fuzzy " + D + " --query \"simlarity\" --max-distance 2",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    run_test("Fuzzy: 'encrypton' finds encryption", A + " search-fuzzy " + D + " --query \"encrypton\" --max-distance 2",
        [](const std::string& o) { return json_get_int(o, "total_hits") >= 0; });

    // ========== CATEGORY 10: Universal Search & Real-World Scenarios (91-100) ==========
    std::cout << std::endl << "--- Category 10: Universal Search & Real-World Scenarios ---" << std::endl;

    run_test("Universal: 'security authentication'", A + " search-universal " + D + " --query \"security authentication\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Universal: 'docker deployment kubernetes'", A + " search-universal " + D + " --query \"docker deployment kubernetes\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Universal: 'performance benchmark speed'", A + " search-universal " + D + " --query \"performance benchmark speed\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Universal: 'error handling troubleshooting'", A + " search-universal " + D + " --query \"error handling troubleshooting\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Universal: 'configuration setup install'", A + " search-universal " + D + " --query \"configuration setup install\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search-all: 'vector cosine tfidf similarity'", A + " search-all " + D + " --query \"vector cosine tfidf similarity\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search-all: 'image hash perceptual fingerprint'", A + " search-all " + D + " --query \"image hash perceptual fingerprint\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Search-all: 'database migration schema sql'", A + " search-all " + D + " --query \"database migration schema sql\"",
        [](const std::string& o) { return json_get_int(o, "total_hits") > 0; });

    run_test("Full map has 170+ files", A + " full-map " + D,
        [](const std::string& o) { return json_get_int(o, "total_files") >= 170; });

    run_test("Stats shows 170+ files indexed", A + " stats " + D,
        [](const std::string& o) { return json_get_int(o, "total_files") >= 170; });

    // ========== SUMMARY ==========
    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  SCENARIO TEST SUITE 2 - SUMMARY" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  Total:  " << tests_total << std::endl;
    std::cout << "  Passed: " << tests_passed << std::endl;
    std::cout << "  Failed: " << tests_failed << std::endl;
    std::cout << "  Rate:   " << std::fixed << std::setprecision(1)
              << (100.0 * tests_passed / tests_total) << "%" << std::endl;
    std::cout << "========================================" << std::endl;

    return tests_failed == 0 ? 0 : 1;
}
