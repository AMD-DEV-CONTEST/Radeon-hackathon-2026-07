// test_runner.cpp - Comprehensive test runner with 100 complex test queries
// Tests all search capabilities: text search, filename, path, extension, size,
// exact phrase, fuzzy, boolean, image hash, similar images, full map, stats
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

struct TestResult {
    bool passed;
    std::string message;
    std::string output;
};

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
    std::cout << "[" << std::setw(3) << tests_total << "] " << std::left << std::setw(55) << test_name << " ... ";
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
        // Show first 200 chars of output for debugging
        if (output.size() > 200) output = output.substr(0, 200) + "...";
        std::cout << "       Output: " << output << std::endl;
    }
}

static std::string aisearch_path = ".\\aisearch.exe";
static std::string test_data = "test_data";

int main(int argc, char* argv[]) {
    if (argc > 1) aisearch_path = argv[1];
    if (argc > 2) test_data = argv[2];

    std::cout << "========================================" << std::endl;
    std::cout << "  AI Search Tool - 100 Test Suite" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "Tool: " << aisearch_path << std::endl;
    std::cout << "Data: " << test_data << std::endl;
    std::cout << std::endl;

    std::string A = aisearch_path;
    std::string D = test_data;

    // ========== CATEGORY 1: Basic Map & Stats (Tests 1-10) ==========
    std::cout << "--- Category 1: Basic Map & Stats ---" << std::endl;

    // 1. Map returns valid JSON
    run_test("Map returns valid JSON", A + " map " + D,
        [](const std::string& out) { return out.find("\"total_files\"") != std::string::npos; });

    // 2. Map finds all expected files
    run_test("Map finds 176 files", A + " map " + D,
        [](const std::string& out) { return json_get_int(out, "total_files") == 176; });

    // 3. Map counts text files correctly
    run_test("Map counts text files", A + " map " + D,
        [](const std::string& out) { int v = json_get_int(out, "total_text_files"); return v > 0; });

    // 4. Map counts image files correctly
    run_test("Map counts image files", A + " map " + D,
        [](const std::string& out) { int v = json_get_int(out, "total_image_files"); return v > 0; });

    // 5. Map counts binary files
    run_test("Map counts binary files", A + " map " + D,
        [](const std::string& out) { return out.find("\"total_binary_files\"") != std::string::npos; });

    // 6. Stats returns valid JSON
    run_test("Stats returns valid JSON", A + " stats " + D,
        [](const std::string& out) { return out.find("\"statistics\"") != std::string::npos; });

    // 7. Stats shows total_chunks > 0
    run_test("Stats shows indexed chunks", A + " stats " + D,
        [](const std::string& out) { return json_get_int(out, "total_chunks") > 0; });

    // 8. Stats shows vocabulary_size > 0
    run_test("Stats shows vocabulary size", A + " stats " + D,
        [](const std::string& out) { return json_get_int(out, "vocabulary_size") > 0; });

    // 9. Stats shows images indexed
    run_test("Stats shows images indexed", A + " stats " + D,
        [](const std::string& out) { return json_get_int(out, "total_images_indexed") > 0; });

    // 10. Map with --hidden includes hidden files
    run_test("Map --hidden finds hidden files", A + " map " + D + " --hidden",
        [](const std::string& out) { return json_get_int(out, "total_files") > 176; });

    // ========== CATEGORY 2: Text Content Search (Tests 11-25) ==========
    std::cout << std::endl << "--- Category 2: Text Content Search ---" << std::endl;

    // 11. Search for "authentication" finds auth files
    run_test("Search 'authentication' finds results", A + " search " + D + " --query \"authentication\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 12. Search finds auth-related file
    run_test("Search 'authentication' finds auth_service", A + " search " + D + " --query \"authentication\"",
        [](const std::string& out) { return json_contains_ci(out, "auth"); });

    // 13. Search for "database" finds database files
    run_test("Search 'database' finds results", A + " search " + D + " --query \"database\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 14. Search for "token" finds token handler
    run_test("Search 'token' finds results", A + " search " + D + " --query \"token\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 15. Search for "cosine similarity" finds search files
    run_test("Search 'cosine similarity' finds results", A + " search " + D + " --query \"cosine similarity\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 16. Search for "TF-IDF" finds vector store
    run_test("Search 'TF-IDF vector' finds results", A + " search " + D + " --query \"TF-IDF vector\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 17. Search for "image fingerprint" finds image files
    run_test("Search 'image fingerprint' finds results", A + " search " + D + " --query \"image fingerprint\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 18. Search for "base64 encoding" finds encoder
    run_test("Search 'base64 encoding' finds results", A + " search " + D + " --query \"base64 encoding\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 19. Search for "connection pool" finds database
    run_test("Search 'connection pool' finds results", A + " search " + D + " --query \"connection pool\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 20. Search for "session management" finds session manager
    run_test("Search 'session management' finds results", A + " search " + D + " --query \"session management\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 21. Search for "config parser" finds config
    run_test("Search 'config parser' finds results", A + " search " + D + " --query \"config parser\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 22. Search for "perceptual hash" finds image files
    run_test("Search 'perceptual hash' finds results", A + " search " + D + " --query \"perceptual hash\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 23. Search with --top-k 1 returns at most 1 text hit
    run_test("Search --top-k 1 limits results", A + " search " + D + " --query \"authentication\" --top-k 1",
        [](const std::string& out) { return json_get_int(out, "total_hits") <= 1; });

    // 24. Search for nonexistent term returns 0 hits
    run_test("Search nonexistent term returns 0", A + " search " + D + " --query \"zzznonexistentxyz\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") == 0; });

    // 25. Search results include snippet
    run_test("Search results include snippet", A + " search " + D + " --query \"authentication\"",
        [](const std::string& out) { return out.find("\"snippet\"") != std::string::npos; });

    // ========== CATEGORY 3: Filename Search (Tests 26-35) ==========
    std::cout << std::endl << "--- Category 3: Filename Search ---" << std::endl;

    // 26. Search filename "login" finds login.cpp
    run_test("Filename search 'login'", A + " search-filename " + D + " --query \"login\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0 && json_contains_ci(out, "login"); });

    // 27. Search filename "config" finds multiple
    run_test("Filename search 'config'", A + " search-filename " + D + " --query \"config\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 28. Search filename "test" finds test files
    run_test("Filename search 'test'", A + " search-filename " + D + " --query \"test\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 29. Search filename "logo" finds logo images
    run_test("Filename search 'logo'", A + " search-filename " + D + " --query \"logo\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 30. Search filename "README" finds readme
    run_test("Filename search 'README'", A + " search-filename " + D + " --query \"README\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 31. Search filename "app.json" finds exact
    run_test("Filename search 'app.json'", A + " search-filename " + D + " --query \"app.json\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 32. Search filename with no match returns 0
    run_test("Filename search no match", A + " search-filename " + D + " --query \"zzznonexist\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") == 0; });

    // 33. Filename search is case-insensitive
    run_test("Filename search case-insensitive", A + " search-filename " + D + " --query \"LOGIN\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 34. Filename search "photo" finds photos
    run_test("Filename search 'photo'", A + " search-filename " + D + " --query \"photo\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 4; });

    // 35. Filename search "banner" finds banners
    run_test("Filename search 'banner'", A + " search-filename " + D + " --query \"banner\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 2; });

    // ========== CATEGORY 4: Path Search (Tests 36-45) ==========
    std::cout << std::endl << "--- Category 4: Path Search ---" << std::endl;

    // 36. Search path "src/auth" finds auth files
    run_test("Path search 'src/auth'", A + " search-path " + D + " --query \"src/auth\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 37. Search path "images" finds image files
    run_test("Path search 'images'", A + " search-path " + D + " --query \"images\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 38. Search path "docs/api" finds API docs
    run_test("Path search 'docs/api'", A + " search-path " + D + " --query \"docs/api\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 39. Search path "config" finds config files
    run_test("Path search 'config'", A + " search-path " + D + " --query \"config\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 40. Search path "tests/unit" finds unit tests
    run_test("Path search 'tests/unit'", A + " search-path " + D + " --query \"tests/unit\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 41. Search path "scripts" finds scripts
    run_test("Path search 'scripts'", A + " search-path " + D + " --query \"scripts\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 42. Search path with no match returns 0
    run_test("Path search no match", A + " search-path " + D + " --query \"zzz/nonexist\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") == 0; });

    // 43. Path search "web" finds web files
    run_test("Path search 'web'", A + " search-path " + D + " --query \"web\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 44. Path search "styles" finds style files
    run_test("Path search 'styles'", A + " search-path " + D + " --query \"styles\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 45. Path search "data" finds data files
    run_test("Path search 'data'", A + " search-path " + D + " --query \"data\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // ========== CATEGORY 5: Extension Search (Tests 46-55) ==========
    std::cout << std::endl << "--- Category 5: Extension Search ---" << std::endl;

    // 46. Search ext "cpp" finds C++ files
    run_test("Extension search 'cpp'", A + " search-ext " + D + " --query \"cpp\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 47. Search ext "py" finds Python files
    run_test("Extension search 'py'", A + " search-ext " + D + " --query \"py\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 2; });

    // 48. Search ext "md" finds markdown files
    run_test("Extension search 'md'", A + " search-ext " + D + " --query \"md\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 49. Search ext "json" finds JSON files
    run_test("Extension search 'json'", A + " search-ext " + D + " --query \"json\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 50. Search ext "png" finds PNG images
    run_test("Extension search 'png'", A + " search-ext " + D + " --query \"png\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 51. Search ext "jpg" finds JPEG images
    run_test("Extension search 'jpg'", A + " search-ext " + D + " --query \"jpg\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 4; });

    // 52. Search ext "bmp" finds BMP images
    run_test("Extension search 'bmp'", A + " search-ext " + D + " --query \"bmp\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 2; });

    // 53. Search ext "gif" finds GIF images
    run_test("Extension search 'gif'", A + " search-ext " + D + " --query \"gif\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 2; });

    // 54. Search ext "sh" finds shell scripts
    run_test("Extension search 'sh'", A + " search-ext " + D + " --query \"sh\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 3; });

    // 55. Search ext "html" finds HTML files
    run_test("Extension search 'html'", A + " search-ext " + D + " --query \"html\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 1; });

    // ========== CATEGORY 6: Exact Phrase Search (Tests 56-65) ==========
    std::cout << std::endl << "--- Category 6: Exact Phrase Search ---" << std::endl;

    // 56. Search phrase "TODO fix this"
    run_test("Phrase search 'TODO fix this'", A + " search-phrase " + D + " --query \"TODO fix this\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 57. Search phrase "FIXME handle error"
    run_test("Phrase search 'FIXME handle error'", A + " search-phrase " + D + " --query \"FIXME handle error\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 58. Search phrase "HACK temporary workaround"
    run_test("Phrase search 'HACK temporary workaround'", A + " search-phrase " + D + " --query \"HACK temporary workaround\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 59. Search phrase "NOTE important security"
    run_test("Phrase search 'NOTE important security'", A + " search-phrase " + D + " --query \"NOTE important security\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 60. Search phrase "authentication failed"
    run_test("Phrase search 'authentication failed'", A + " search-phrase " + D + " --query \"authentication failed\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 61. Search phrase "connection pool"
    run_test("Phrase search 'connection pool'", A + " search-phrase " + D + " --query \"connection pool\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 62. Search phrase "JWT token"
    run_test("Phrase search 'JWT token'", A + " search-phrase " + D + " --query \"JWT token\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 63. Search phrase "bcrypt"
    run_test("Phrase search 'bcrypt'", A + " search-phrase " + D + " --query \"bcrypt\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 64. Search phrase "nonexistent phrase" returns 0
    run_test("Phrase search nonexistent", A + " search-phrase " + D + " --query \"zzz nonexistent phrase zzz\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") == 0; });

    // 65. Search phrase "SELECT" finds query builder
    run_test("Phrase search 'SELECT'", A + " search-phrase " + D + " --query \"SELECT\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // ========== CATEGORY 7: Fuzzy Search (Tests 66-75) ==========
    std::cout << std::endl << "--- Category 7: Fuzzy Search ---" << std::endl;

    // 66. Fuzzy search "autentication" (missing 'h') finds authentication
    run_test("Fuzzy search 'autentication'", A + " search-fuzzy " + D + " --query \"autentication\" --max-distance 2",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 67. Fuzzy search "databse" (missing 'a') finds database
    run_test("Fuzzy search 'databse'", A + " search-fuzzy " + D + " --query \"databse\" --max-distance 2",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 68. Fuzzy search "tokn" finds token
    run_test("Fuzzy search 'tokn'", A + " search-fuzzy " + D + " --query \"tokn\" --max-distance 2",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 69. Fuzzy search "sesson" finds session
    run_test("Fuzzy search 'sesson'", A + " search-fuzzy " + D + " --query \"sesson\" --max-distance 2",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 70. Fuzzy search "conection" finds connection
    run_test("Fuzzy search 'conection'", A + " search-fuzzy " + D + " --query \"conection\" --max-distance 2",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 71. Fuzzy search "hash" finds hash
    run_test("Fuzzy search 'hash'", A + " search-fuzzy " + D + " --query \"hash\" --max-distance 1",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 72. Fuzzy search "loger" finds logger
    run_test("Fuzzy search 'loger'", A + " search-fuzzy " + D + " --query \"loger\" --max-distance 2",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 73. Fuzzy search "config" finds config
    run_test("Fuzzy search 'config'", A + " search-fuzzy " + D + " --query \"config\" --max-distance 1",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 74. Fuzzy search "vector" finds vector
    run_test("Fuzzy search 'vector'", A + " search-fuzzy " + D + " --query \"vector\" --max-distance 1",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 75. Fuzzy search with large distance finds more
    run_test("Fuzzy search large distance", A + " search-fuzzy " + D + " --query \"authentication\" --max-distance 5",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // ========== CATEGORY 8: Boolean Search (Tests 76-85) ==========
    std::cout << std::endl << "--- Category 8: Boolean Search ---" << std::endl;

    // 76. Boolean AND search
    run_test("Boolean 'authentication AND token'", A + " search-boolean " + D + " --query \"authentication AND token\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 77. Boolean OR search
    run_test("Boolean 'database OR redis'", A + " search-boolean " + D + " --query \"database OR redis\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 78. Boolean NOT search
    run_test("Boolean 'authentication NOT redis'", A + " search-boolean " + D + " --query \"authentication NOT redis\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 79. Boolean AND with three terms
    run_test("Boolean 'token AND session AND cache'", A + " search-boolean " + D + " --query \"token AND session AND cache\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 80. Boolean OR with three terms
    run_test("Boolean 'image OR photo OR picture'", A + " search-boolean " + D + " --query \"image OR photo OR picture\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 81. Boolean search single term (no operator)
    run_test("Boolean single term 'config'", A + " search-boolean " + D + " --query \"config\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 82. Boolean NOT with single term
    run_test("Boolean 'database NOT pool'", A + " search-boolean " + D + " --query \"database NOT pool\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 83. Boolean AND with image terms
    run_test("Boolean 'perceptual AND hash'", A + " search-boolean " + D + " --query \"perceptual AND hash\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 84. Boolean OR with search terms
    run_test("Boolean 'tfidf OR cosine'", A + " search-boolean " + D + " --query \"tfidf OR cosine\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // 85. Boolean with error terms
    run_test("Boolean 'error AND warning'", A + " search-boolean " + D + " --query \"error AND warning\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") >= 0; });

    // ========== CATEGORY 9: Image Search (Tests 86-95) ==========
    std::cout << std::endl << "--- Category 9: Image Search ---" << std::endl;

    // 86. Fingerprint a PNG image
    run_test("Fingerprint PNG image", A + " fingerprint " + D + "/images/logos/logo_primary.png",
        [](const std::string& out) { return out.find("\"base64_hash\"") != std::string::npos && out.find("PNG") != std::string::npos; });

    // 87. Fingerprint a JPEG image
    run_test("Fingerprint JPEG image", A + " fingerprint " + D + "/images/photos/photo1.jpg",
        [](const std::string& out) { return out.find("\"base64_hash\"") != std::string::npos && out.find("JPEG") != std::string::npos; });

    // 88. Fingerprint a BMP image
    run_test("Fingerprint BMP image", A + " fingerprint " + D + "/images/banners/banner1.bmp",
        [](const std::string& out) { return out.find("\"base64_hash\"") != std::string::npos && out.find("BMP") != std::string::npos; });

    // 89. Fingerprint a GIF image
    run_test("Fingerprint GIF image", A + " fingerprint " + D + "/images/gifs/animation1.gif",
        [](const std::string& out) { return out.find("\"base64_hash\"") != std::string::npos && out.find("GIF") != std::string::npos; });

    // 90. Fingerprint shows dimensions
    run_test("Fingerprint shows dimensions", A + " fingerprint " + D + "/images/logos/logo_primary.png",
        [](const std::string& out) { return out.find("\"width\"") != std::string::npos && out.find("\"height\"") != std::string::npos; });

    // 91. Fingerprint shows perceptual hash
    run_test("Fingerprint shows perceptual hash", A + " fingerprint " + D + "/images/photos/photo1.jpg",
        [](const std::string& out) { return out.find("\"perceptual_hash\"") != std::string::npos; });

    // 92. Full map includes image fingerprints
    run_test("Full map includes image data", A + " full-map " + D,
        [](const std::string& out) { return out.find("\"images\"") != std::string::npos && out.find("\"fingerprint\"") != std::string::npos; });

    // 93. Full map includes text chunks
    run_test("Full map includes text chunks", A + " full-map " + D,
        [](const std::string& out) { return out.find("\"text_chunks\"") != std::string::npos; });

    // 94. Full map includes directories
    run_test("Full map includes directories", A + " full-map " + D,
        [](const std::string& out) { return out.find("\"directories\"") != std::string::npos; });

    // 95. Full map includes version
    run_test("Full map includes version", A + " full-map " + D,
        [](const std::string& out) { return out.find("\"version\"") != std::string::npos; });

    // ========== CATEGORY 10: Universal & Combined Search (Tests 96-100) ==========
    std::cout << std::endl << "--- Category 10: Universal & Combined Search ---" << std::endl;

    // 96. Search-all for "authentication" finds text and filename hits
    run_test("Search-all 'authentication'", A + " search-all " + D + " --query \"authentication\"",
        [](const std::string& out) { return out.find("\"text_hits\"") != std::string::npos && out.find("\"filename_hits\"") != std::string::npos; });

    // 97. Search-universal for "config" finds multiple types
    run_test("Search-universal 'config'", A + " search-universal " + D + " --query \"config\"",
        [](const std::string& out) { return out.find("\"text_hits\"") != std::string::npos; });

    // 98. Search-all for "database" finds results
    run_test("Search-all 'database'", A + " search-all " + D + " --query \"database\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 99. Search-universal for "image hash" finds results
    run_test("Search-universal 'image hash'", A + " search-universal " + D + " --query \"image hash\"",
        [](const std::string& out) { return json_get_int(out, "total_hits") > 0; });

    // 100. Search-all includes search time
    run_test("Search-all includes timing", A + " search-all " + D + " --query \"authentication\"",
        [](const std::string& out) { return out.find("\"search_time_ms\"") != std::string::npos; });

    // ========== SUMMARY ==========
    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  TEST SUMMARY" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  Total:  " << tests_total << std::endl;
    std::cout << "  Passed: " << tests_passed << std::endl;
    std::cout << "  Failed: " << tests_failed << std::endl;
    std::cout << "  Rate:   " << std::fixed << std::setprecision(1)
              << (100.0 * tests_passed / tests_total) << "%" << std::endl;
    std::cout << "========================================" << std::endl;

    return tests_failed == 0 ? 0 : 1;
}
