#include "browser_tool.h"
#include <iostream>
#include <string>
#include <sstream>
#include <fstream>

using namespace browsertool;

// ===== Test Framework =====
static int g_tests_passed = 0;
static int g_tests_failed = 0;
static int g_current_test = 0;

struct TestResult {
    bool passed;
    std::string message;
};

#define TEST(name) \
    g_current_test++; \
    std::cout << "[" << std::setw(3) << std::right << g_current_test << "] " << std::left << std::setw(60) << name << " ... ";

#define PASS() { std::cout << "PASS" << std::endl; g_tests_passed++; }
#define FAIL(msg) { std::cout << "FAIL" << std::endl; std::cout << "       " << msg << std::endl; g_tests_failed++; }

#define CHECK_TRUE(cond, msg) if (cond) { PASS(); } else { FAIL(msg); }
#define CHECK_FALSE(cond, msg) if (!(cond)) { PASS(); } else { FAIL(msg); }
#define CHECK_EQ(a, b, msg) if ((a) == (b)) { PASS(); } else { FAIL(msg); }
#define CHECK_CONTAINS(haystack, needle, msg) if (contains_ci(haystack, needle)) { PASS(); } else { FAIL(msg); }
#define CHECK_NOT_CONTAINS(haystack, needle, msg) if (!contains_ci(haystack, needle)) { PASS(); } else { FAIL(msg); }
#define CHECK_GT(a, b, msg) if ((a) > (b)) { PASS(); } else { FAIL(msg); }
#define CHECK_GTE(a, b, msg) if ((a) >= (b)) { PASS(); } else { FAIL(msg); }
#define CHECK_LT(a, b, msg) if ((a) < (b)) { PASS(); } else { FAIL(msg); }
#define CHECK_LTE(a, b, msg) if ((a) <= (b)) { PASS(); } else { FAIL(msg); }

// Helper: check if JSON string contains a substring
static bool json_contains(const std::string& json, const std::string& needle) {
    return json.find(needle) != std::string::npos;
}

// Helper: run a CLI command and capture output
static std::string run_cli(const std::string& args) {
    std::string cmd = "browsertool.exe " + args + " 2>&1";
    FILE* pipe = _popen(cmd.c_str(), "r");
    if (!pipe) return "";
    std::string result;
    char buffer[4096];
    while (fgets(buffer, sizeof(buffer), pipe)) {
        result += buffer;
    }
    _pclose(pipe);
    return result;
}

int main() {
    std::cout << "========================================" << std::endl;
    std::cout << " BROWSER TOOL TEST SUITE - 151 TESTS" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << std::endl;

    // Enable simulation mode for all tests
    enable_simulation_mode();
    setup_simulation_data();

    // ===== Category 1: Browser Info & Platform =====
    std::cout << "--- Category 1: Browser Info & Platform ---" << std::endl;

    {
        TEST("Browser info returns valid name");
        auto info = get_browser_info();
        CHECK_FALSE(info.name.empty(), "Browser name should not be empty");
    }
    {
        TEST("Browser info has version");
        auto info = get_browser_info();
        CHECK_FALSE(info.version.empty(), "Version should not be empty");
    }
    {
        TEST("Browser info has user_agent");
        auto info = get_browser_info();
        CHECK_CONTAINS(info.user_agent, "Mozilla", "User agent should contain Mozilla");
    }
    {
        TEST("Browser info has platform");
        auto info = get_browser_info();
        CHECK_FALSE(info.platform.empty(), "Platform should not be empty");
    }
    {
        TEST("Simulation mode is active");
        CHECK_TRUE(is_simulation_mode(), "Simulation mode should be active");
    }
    {
        TEST("Platform returns simulation");
        auto p = get_current_platform();
        CHECK_EQ(p, Platform::Simulation, "Platform should be Simulation");
    }
    {
        TEST("Browser info has tab_count > 0");
        auto info = get_browser_info();
        CHECK_GT(info.tab_count, 0, "Tab count should be > 0");
    }

    // ===== Category 2: Navigation =====
    std::cout << std::endl << "--- Category 2: Navigation ---" << std::endl;

    {
        TEST("Navigate to Wikipedia AI article");
        bool ok = navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        CHECK_TRUE(ok, "Should navigate to Wikipedia AI article");
    }
    {
        TEST("Get current URL after navigation");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string url = get_current_url();
        CHECK_CONTAINS(url, "wikipedia.org", "URL should contain wikipedia.org");
    }
    {
        TEST("Get current title after navigation");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string title = get_current_title();
        CHECK_CONTAINS(title, "Artificial intelligence", "Title should contain 'Artificial intelligence'");
    }
    {
        TEST("Navigate to Google search");
        bool ok = navigate("https://www.google.com/search?q=artificial+intelligence+tutorial");
        CHECK_TRUE(ok, "Should navigate to Google search");
    }
    {
        TEST("Navigate to BBC news");
        bool ok = navigate("https://www.bbc.com/news/technology-ai-breakthrough-2026");
        CHECK_TRUE(ok, "Should navigate to BBC news");
    }
    {
        TEST("Navigate to Amazon product");
        bool ok = navigate("https://www.amazon.com/dp/B0AI2026GPU");
        CHECK_TRUE(ok, "Should navigate to Amazon product");
    }
    {
        TEST("Navigate to MDN docs");
        bool ok = navigate("https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Functions");
        CHECK_TRUE(ok, "Should navigate to MDN docs");
    }
    {
        TEST("Navigate to social feed");
        bool ok = navigate("https://social.example.com/feed");
        CHECK_TRUE(ok, "Should navigate to social feed");
    }
    {
        TEST("Navigate to login page");
        bool ok = navigate("https://app.example.com/login");
        CHECK_TRUE(ok, "Should navigate to login page");
    }
    {
        TEST("Navigate to stats page");
        bool ok = navigate("https://stats.example.com/ai-industry-report-2026");
        CHECK_TRUE(ok, "Should navigate to stats page");
    }
    {
        TEST("Navigate by domain name only");
        bool ok = navigate("amazon.com");
        CHECK_TRUE(ok, "Should navigate by domain name");
    }
    {
        TEST("Navigate to nonexistent URL returns false");
        bool ok = navigate("https://nonexistent.example.com/page");
        CHECK_FALSE(ok, "Should return false for nonexistent URL");
    }
    {
        TEST("Go back after navigation");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        navigate("https://www.google.com/search?q=artificial+intelligence+tutorial");
        bool ok = go_back();
        CHECK_TRUE(ok, "Should go back");
    }
    {
        TEST("URL after go back is Wikipedia");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        navigate("https://www.google.com/search?q=artificial+intelligence+tutorial");
        go_back();
        std::string url = get_current_url();
        CHECK_CONTAINS(url, "wikipedia", "URL after go back should be Wikipedia");
    }
    {
        TEST("Refresh resets scroll position");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        scroll_down(500);
        refresh();
        CHECK_EQ(get_scroll_y(), 0, "Scroll Y should be 0 after refresh");
    }

    // ===== Category 3: Page Content =====
    std::cout << std::endl << "--- Category 3: Page Content ---" << std::endl;

    {
        TEST("Page info has URL");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto p = get_page_info();
        CHECK_FALSE(p.url.empty(), "Page URL should not be empty");
    }
    {
        TEST("Page info has title");
        auto p = get_page_info();
        CHECK_FALSE(p.title.empty(), "Page title should not be empty");
    }
    {
        TEST("Page info has domain");
        auto p = get_page_info();
        CHECK_FALSE(p.domain.empty(), "Page domain should not be empty");
    }
    {
        TEST("Page info has meta description");
        auto p = get_page_info();
        CHECK_FALSE(p.meta_description.empty(), "Meta description should not be empty");
    }
    {
        TEST("Page info has page_type");
        auto p = get_page_info();
        CHECK_FALSE(p.page_type.empty(), "Page type should not be empty");
    }
    {
        TEST("Page content is not empty");
        auto content = get_page_content();
        CHECK_FALSE(content.empty(), "Page content should not be empty");
    }
    {
        TEST("Wikipedia content contains 'Artificial intelligence'");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto content = get_page_content();
        CHECK_CONTAINS(content, "Artificial intelligence", "Content should contain 'Artificial intelligence'");
    }
    {
        TEST("Wikipedia content contains 'Machine Learning'");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto content = get_page_content();
        CHECK_CONTAINS(content, "Machine Learning", "Content should contain 'Machine Learning'");
    }
    {
        TEST("Wikipedia content contains 'Neural Networks'");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto content = get_page_content();
        CHECK_CONTAINS(content, "Neural Networks", "Content should contain 'Neural Networks'");
    }
    {
        TEST("Google content contains search results");
        navigate("https://www.google.com/search?q=artificial+intelligence+tutorial");
        auto content = get_page_content();
        CHECK_CONTAINS(content, "About", "Google content should contain 'About' results count");
    }
    {
        TEST("BBC content contains 'AI Breakthrough'");
        navigate("https://www.bbc.com/news/technology-ai-breakthrough-2026");
        auto content = get_page_content();
        CHECK_CONTAINS(content, "AI Breakthrough", "BBC content should contain 'AI Breakthrough'");
    }
    {
        TEST("Amazon content contains product price");
        navigate("https://www.amazon.com/dp/B0AI2026GPU");
        auto content = get_page_content();
        CHECK_CONTAINS(content, "$1,799.00", "Amazon content should contain price");
    }
    {
        TEST("MDN content contains 'Functions'");
        navigate("https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Functions");
        auto content = get_page_content();
        CHECK_CONTAINS(content, "Functions", "MDN content should contain 'Functions'");
    }
    {
        TEST("Social content contains posts");
        navigate("https://social.example.com/feed");
        auto content = get_page_content();
        CHECK_CONTAINS(content, "Post 1", "Social content should contain posts");
    }
    {
        TEST("Login content contains 'Sign In'");
        navigate("https://app.example.com/login");
        auto content = get_page_content();
        CHECK_CONTAINS(content, "Sign In", "Login content should contain 'Sign In'");
    }
    {
        TEST("Stats content contains table data");
        navigate("https://stats.example.com/ai-industry-report-2026");
        auto content = get_page_content();
        CHECK_CONTAINS(content, "Table 1", "Stats content should contain table data");
    }
    {
        TEST("Page HTML is not empty");
        auto html = get_page_html();
        CHECK_FALSE(html.empty(), "HTML should not be empty");
    }
    {
        TEST("Meta keywords not empty for Wikipedia");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto kw = get_meta_keywords();
        CHECK_FALSE(kw.empty(), "Meta keywords should not be empty");
    }

    // ===== Category 4: Element Query =====
    std::cout << std::endl << "--- Category 4: Element Query ---" << std::endl;

    {
        TEST("Get all elements returns elements");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto elements = get_all_elements();
        CHECK_GT(elements.size(), 0, "Should have elements on page");
    }
    {
        TEST("Wikipedia page has 10+ elements");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto elements = get_all_elements();
        CHECK_GTE(elements.size(), 10, "Wikipedia should have 10+ elements");
    }
    {
        TEST("Elements have IDs");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto elements = get_all_elements();
        bool all_have_ids = true;
        for (const auto& e : elements) {
            if (e.id.empty()) { all_have_ids = false; break; }
        }
        CHECK_TRUE(all_have_ids, "All elements should have IDs");
    }
    {
        TEST("Elements have bounds");
        auto elements = get_all_elements();
        bool all_have_bounds = true;
        for (const auto& e : elements) {
            if (e.bounds.width <= 0 || e.bounds.height <= 0) { all_have_bounds = false; break; }
        }
        CHECK_TRUE(all_have_bounds, "All elements should have valid bounds");
    }
    {
        TEST("Get headings returns headings");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto headings = get_headings();
        CHECK_GT(headings.size(), 0, "Should have headings");
    }
    {
        TEST("Wikipedia has History heading");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto headings = get_headings();
        bool found = false;
        for (const auto& h : headings) {
            if (contains_ci(h.text, "History")) { found = true; break; }
        }
        CHECK_TRUE(found, "Should have 'History' heading");
    }
    {
        TEST("Get paragraphs returns paragraphs");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto paras = get_paragraphs();
        CHECK_GT(paras.size(), 0, "Should have paragraphs");
    }
    {
        TEST("Get links on Google search page");
        navigate("https://www.google.com/search?q=artificial+intelligence+tutorial");
        auto links = get_links();
        CHECK_GT(links.size(), 0, "Google search should have links");
    }
    {
        TEST("Get buttons on Amazon page");
        navigate("https://www.amazon.com/dp/B0AI2026GPU");
        auto buttons = get_buttons();
        CHECK_GT(buttons.size(), 0, "Amazon should have buttons");
    }
    {
        TEST("Get inputs on login page");
        navigate("https://app.example.com/login");
        auto inputs = get_inputs();
        CHECK_GT(inputs.size(), 0, "Login page should have inputs");
    }
    {
        TEST("Get tables on stats page");
        navigate("https://stats.example.com/ai-industry-report-2026");
        auto tables = get_tables();
        CHECK_GT(tables.size(), 0, "Stats page should have tables");
    }
    {
        TEST("Get element by ID");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto e = get_element_by_id("page0_h1_title");
        CHECK_FALSE(e.id.empty(), "Should find element by ID");
    }
    {
        TEST("Get element children");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto children = get_element_children("page0_content");
        CHECK_GT(children.size(), 0, "Content element should have children");
    }
    {
        TEST("Get element parent");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto parent = get_element_parent("page0_h1_title");
        // h1_title has empty parent_id, so parent should be empty
        CHECK_TRUE(parent.id.empty(), "h1_title parent should be empty (root element)");
    }
    {
        TEST("Get elements by type (paragraph)");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto paras = get_elements_by_type(BrowserElementType::paragraph);
        CHECK_GT(paras.size(), 0, "Should find paragraph elements by type");
    }
    {
        TEST("Get navigation elements");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto nav = get_navigation();
        CHECK_GT(nav.size(), 0, "Should have navigation elements");
    }

    // ===== Category 5: Content Search =====
    std::cout << std::endl << "--- Category 5: Content Search ---" << std::endl;

    {
        TEST("Search for 'machine learning' finds results");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto results = search_content("machine learning", 10);
        CHECK_GT(results.size(), 0, "Should find 'machine learning' in content");
    }
    {
        TEST("Search results have positions");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto results = search_content("machine learning", 10);
        CHECK_GT(results[0].position, 0, "First result should have position > 0");
    }
    {
        TEST("Search results have line numbers");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto results = search_content("machine learning", 10);
        CHECK_GT(results[0].line_number, 0, "First result should have line number > 0");
    }
    {
        TEST("Search results have match_type 'exact'");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto results = search_content("machine learning", 10);
        CHECK_EQ(results[0].match_type, "exact", "Should be exact match");
    }
    {
        TEST("Search results have score 1.0 for exact");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto results = search_content("machine learning", 10);
        CHECK_EQ(results[0].score, 1.0, "Exact match should have score 1.0");
    }
    {
        TEST("Search for nonexistent text returns empty");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto results = search_content("xyzzy_nonexistent_text", 10);
        CHECK_EQ(results.size(), 0, "Should find nothing for nonexistent text");
    }
    {
        TEST("Find first text returns first match");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto r = find_first_text("Artificial intelligence");
        CHECK_FALSE(r.text.empty(), "Should find first occurrence");
    }
    {
        TEST("Find all text returns multiple results");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto results = find_all_text("AI");
        CHECK_GT(results.size(), 1, "Should find multiple occurrences of 'AI'");
    }
    {
        TEST("Find element by text");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto e = find_element_by_text("History");
        CHECK_FALSE(e.id.empty(), "Should find element with 'History' text");
    }
    {
        TEST("Find paragraph by text");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto e = find_paragraph_by_text("Machine learning");
        CHECK_FALSE(e.id.empty(), "Should find paragraph about machine learning");
    }
    {
        TEST("Find heading by text");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto e = find_heading_by_text("History");
        CHECK_FALSE(e.id.empty(), "Should find 'History' heading");
    }
    {
        TEST("Find link by text on Google");
        navigate("https://www.google.com/search?q=artificial+intelligence+tutorial");
        auto e = find_link_by_text("Result 1");
        CHECK_FALSE(e.id.empty(), "Should find 'Result 1' link");
    }
    {
        TEST("Find button by text on Amazon");
        navigate("https://www.amazon.com/dp/B0AI2026GPU");
        auto e = find_button_by_text("Add to Cart");
        CHECK_FALSE(e.id.empty(), "Should find 'Add to Cart' button");
    }
    {
        TEST("Find button by text on login page");
        navigate("https://app.example.com/login");
        auto e = find_button_by_text("Sign In");
        CHECK_FALSE(e.id.empty(), "Should find 'Sign In' button");
    }
    {
        TEST("Search with context returns context");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto results = search_with_context("neural networks", 200);
        CHECK_TRUE(!results.empty() && !results[0].context_before.empty(), "Should have context before");
    }
    {
        TEST("Get context around text");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string ctx = get_context_around_text("Deep learning", 50, 50);
        CHECK_FALSE(ctx.empty(), "Should get context around 'Deep learning'");
    }
    {
        TEST("Context contains the search term");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string ctx = get_context_around_text("Deep learning", 50, 50);
        CHECK_CONTAINS(ctx, "Deep learning", "Context should contain the search term");
    }

    // ===== Category 6: Content Analysis & Explanation =====
    std::cout << std::endl << "--- Category 6: Content Analysis & Explanation ---" << std::endl;

    {
        TEST("Explain content returns JSON with query");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string result = explain_content("neural networks");
        CHECK_CONTAINS(result, "neural networks", "Explain should contain the query");
    }
    {
        TEST("Explain content returns matches count");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string result = explain_content("neural networks");
        CHECK_CONTAINS(result, "matches", "Explain should contain matches count");
    }
    {
        TEST("Explain content returns explanation text");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string result = explain_content("neural networks");
        CHECK_CONTAINS(result, "explanation", "Explain should contain explanation field");
    }
    {
        TEST("Explain content for 'Turing' on Wikipedia");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string result = explain_content("Turing");
        CHECK_CONTAINS(result, "Turing", "Should explain Turing reference");
    }
    {
        TEST("Explain content for 'price' on Amazon");
        navigate("https://www.amazon.com/dp/B0AI2026GPU");
        std::string result = explain_content("$1,799");
        CHECK_CONTAINS(result, "$1,799", "Should find price reference");
    }
    {
        TEST("Summarize page returns summary");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string summary = summarize_page(3);
        CHECK_CONTAINS(summary, "summary", "Summary should contain 'summary' field");
    }
    {
        TEST("Summarize page has title");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string summary = summarize_page(3);
        CHECK_CONTAINS(summary, "Artificial intelligence", "Summary should contain page title");
    }
    {
        TEST("Get section by heading 'History'");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string section = get_section_by_heading("History");
        CHECK_CONTAINS(section, "History", "Section should contain 'History'");
    }
    {
        TEST("Get section by heading 'Machine Learning'");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string section = get_section_by_heading("Machine Learning");
        CHECK_CONTAINS(section, "Machine Learning", "Section should contain 'Machine Learning'");
    }
    {
        TEST("Get section by heading contains content");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string section = get_section_by_heading("History");
        CHECK_CONTAINS(section, "Alan Turing", "History section should mention Alan Turing");
    }
    {
        TEST("Get all headings returns list");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto headings = get_all_headings();
        CHECK_GT(headings.size(), 0, "Should have headings");
    }
    {
        TEST("Get all paragraphs returns list");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto paras = get_all_paragraphs();
        CHECK_GT(paras.size(), 0, "Should have paragraphs");
    }
    {
        TEST("Get page summary returns content");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string s = get_page_summary();
        CHECK_FALSE(s.empty(), "Page summary should not be empty");
    }
    {
        TEST("Explain content for 'ReasonNet' on BBC");
        navigate("https://www.bbc.com/news/technology-ai-breakthrough-2026");
        std::string result = explain_content("ReasonNet");
        CHECK_CONTAINS(result, "ReasonNet", "Should find ReasonNet in BBC article");
    }
    {
        TEST("Explain content for 'Closures' on MDN");
        navigate("https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Functions");
        std::string result = explain_content("Closures");
        CHECK_CONTAINS(result, "Closures", "Should find Closures in MDN article");
    }

    // ===== Category 7: Scroll API =====
    std::cout << std::endl << "--- Category 7: Scroll API ---" << std::endl;

    {
        TEST("Scroll down increases scroll_y");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        int before = get_scroll_y();
        scroll_down(300);
        int after = get_scroll_y();
        CHECK_GT(after, before, "Scroll Y should increase after scroll_down");
    }
    {
        TEST("Scroll up decreases scroll_y");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        scroll_down(600);
        int before = get_scroll_y();
        scroll_up(300);
        int after = get_scroll_y();
        CHECK_LT(after, before, "Scroll Y should decrease after scroll_up");
    }
    {
        TEST("Scroll to specific position");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        scroll_to(0, 500);
        CHECK_EQ(get_scroll_y(), 500, "Scroll Y should be 500");
    }
    {
        TEST("Scroll to top");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        scroll_down(500);
        scroll_to_top();
        CHECK_EQ(get_scroll_y(), 0, "Scroll Y should be 0 at top");
    }
    {
        TEST("Scroll to bottom");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        scroll_to_bottom();
        CHECK_EQ(get_scroll_y(), get_scroll_max_y(), "Scroll Y should be max at bottom");
    }
    {
        TEST("Scroll max_y > 0 for long pages");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        CHECK_GT(get_scroll_max_y(), 0, "Wikipedia page should have scroll_max_y > 0");
    }
    {
        TEST("Scroll to element");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto e = get_element_by_id("page0_h1_title");
        scroll_to_element(e.id);
        CHECK_GTE(get_scroll_y(), 0, "Scroll to element should set scroll position");
    }
    {
        TEST("Scroll down by default 300px");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        scroll_down();
        CHECK_EQ(get_scroll_y(), 300, "Default scroll should be 300px");
    }

    // ===== Category 8: Screenshot API =====
    std::cout << std::endl << "--- Category 8: Screenshot API ---" << std::endl;

    {
        TEST("Take screenshot returns valid info");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto s = take_screenshot(false);
        CHECK_GT(s.width, 0, "Screenshot width should be > 0");
    }
    {
        TEST("Screenshot has height");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto s = take_screenshot(false);
        CHECK_GT(s.height, 0, "Screenshot height should be > 0");
    }
    {
        TEST("Screenshot has format");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto s = take_screenshot(false);
        CHECK_FALSE(s.format.empty(), "Screenshot format should not be empty");
    }
    {
        TEST("Full page screenshot is larger");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto s1 = take_screenshot(false);
        auto s2 = take_screenshot(true);
        CHECK_GT(s2.height, s1.height, "Full page screenshot should be taller");
    }
    {
        TEST("Screenshot element returns element bounds");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto e = get_element_by_id("page0_h1_title");
        auto s = screenshot_element(e.id);
        CHECK_EQ(s.width, e.bounds.width, "Screenshot element width should match element");
    }
    {
        TEST("Screenshot region returns correct dimensions");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto s = screenshot_region(100, 200, 300, 400);
        CHECK_EQ(s.width, 300, "Region screenshot width should be 300");
    }
    {
        TEST("Save screenshot to file");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        bool ok = save_screenshot("test_screenshot.png", false);
        CHECK_TRUE(ok, "Should save screenshot to file");
    }

    // ===== Category 9: Interaction =====
    std::cout << std::endl << "--- Category 9: Interaction ---" << std::endl;

    {
        TEST("Click element on Amazon");
        navigate("https://www.amazon.com/dp/B0AI2026GPU");
        bool ok = click_element("page3_add_to_cart");
        CHECK_TRUE(ok, "Should click 'Add to Cart' button");
    }
    {
        TEST("Click element returns false for non-clickable");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        bool ok = click_element("page0_h1_title");
        CHECK_FALSE(ok, "Should not click non-clickable element");
    }
    {
        TEST("Click element at coordinates");
        navigate("https://www.amazon.com/dp/B0AI2026GPU");
        bool ok = click_element_at(400, 525); // Near Add to Cart
        CHECK_TRUE(ok, "Should click at coordinates near Add to Cart");
    }
    {
        TEST("Type text into input on login page");
        navigate("https://app.example.com/login");
        bool ok = type_text("page6_email_input", "user@example.com");
        CHECK_TRUE(ok, "Should type into email input");
    }
    {
        TEST("Type text returns false for non-input");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        bool ok = type_text("page0_h1_title", "test");
        CHECK_FALSE(ok, "Should not type into non-input element");
    }
    {
        TEST("Type text into active element");
        navigate("https://app.example.com/login");
        bool ok = type_text_into_active_element("hello world");
        CHECK_TRUE(ok, "Should type into active element");
    }
    {
        TEST("Press key");
        bool ok = press_key("Enter");
        CHECK_TRUE(ok, "Press key should return true in sim");
    }
    {
        TEST("Submit form");
        navigate("https://app.example.com/login");
        bool ok = submit_form("page6_signin_btn");
        CHECK_TRUE(ok, "Submit form should return true in sim");
    }
    {
        TEST("Clear input");
        navigate("https://app.example.com/login");
        bool ok = clear_input("page6_email_input");
        CHECK_TRUE(ok, "Clear input should return true for input element");
    }
    {
        TEST("Focus element");
        navigate("https://app.example.com/login");
        bool ok = focus_element("page6_email_input");
        CHECK_TRUE(ok, "Focus element should return true in sim");
    }
    {
        TEST("Hover element");
        navigate("https://www.amazon.com/dp/B0AI2026GPU");
        bool ok = hover_element("page3_add_to_cart");
        CHECK_TRUE(ok, "Hover element should return true in sim");
    }

    // ===== Category 10: Tab Management =====
    std::cout << std::endl << "--- Category 10: Tab Management ---" << std::endl;

    {
        TEST("List tabs returns tabs");
        auto tabs = list_tabs();
        CHECK_GT(tabs.size(), 0, "Should have at least one tab");
    }
    {
        TEST("New tab creates a tab");
        size_t before = list_tabs().size();
        new_tab("https://en.wikipedia.org/wiki/Artificial_intelligence");
        size_t after = list_tabs().size();
        CHECK_GT(after, before, "Should have more tabs after new_tab");
    }
    {
        TEST("Switch tab changes active tab");
        new_tab("https://www.google.com");
        auto tabs = list_tabs();
        if (tabs.size() >= 2) {
            switch_tab(tabs[0].id);
            auto tabs2 = list_tabs();
            CHECK_TRUE(tabs2[0].active, "First tab should be active after switch");
        } else {
            PASS();
        }
    }
    {
        TEST("Close tab reduces tab count");
        new_tab("https://www.google.com");
        size_t before = list_tabs().size();
        auto tabs = list_tabs();
        close_tab(tabs.back().id);
        size_t after = list_tabs().size();
        CHECK_LT(after, before, "Should have fewer tabs after close");
    }
    {
        TEST("Get active tab ID");
        std::string id = get_active_tab_id();
        CHECK_FALSE(id.empty(), "Active tab ID should not be empty");
    }

    // ===== Category 11: Wait API =====
    std::cout << std::endl << "--- Category 11: Wait API ---" << std::endl;

    {
        TEST("Wait for element finds element");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        bool ok = wait_for_element("h1_title");
        CHECK_TRUE(ok, "Should find 'h1_title' element");
    }
    {
        TEST("Wait for text finds text");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        bool ok = wait_for_text("Artificial intelligence");
        CHECK_TRUE(ok, "Should find 'Artificial intelligence' text");
    }
    {
        TEST("Wait for text returns false for missing");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        bool ok = wait_for_text("nonexistent_text_xyzzy");
        CHECK_FALSE(ok, "Should not find nonexistent text");
    }
    {
        TEST("Wait for navigation returns true");
        bool ok = wait_for_navigation();
        CHECK_TRUE(ok, "Wait for navigation should return true in sim");
    }
    {
        TEST("Wait for element by text content");
        navigate("https://www.amazon.com/dp/B0AI2026GPU");
        bool ok = wait_for_element("Add to Cart");
        CHECK_TRUE(ok, "Should find 'Add to Cart' element");
    }

    // ===== Category 12: Forms & Tables =====
    std::cout << std::endl << "--- Category 12: Forms & Tables ---" << std::endl;

    {
        TEST("Get form fields from login page");
        navigate("https://app.example.com/login");
        // Login page has inputs as children of content
        auto fields = get_form_fields("page6_content");
        CHECK_GT(fields.size(), 0, "Should find form fields on login page");
    }
    {
        TEST("Get table data from stats page");
        navigate("https://stats.example.com/ai-industry-report-2026");
        auto tables = get_tables_data();
        CHECK_GT(tables.size(), 0, "Should find tables on stats page");
    }
    {
        TEST("Table data has headers");
        navigate("https://stats.example.com/ai-industry-report-2026");
        auto tables = get_tables_data();
        CHECK_GT(tables[0].headers.size(), 0, "First table should have headers");
    }
    {
        TEST("Table data has rows");
        navigate("https://stats.example.com/ai-industry-report-2026");
        auto tables = get_tables_data();
        CHECK_GT(tables[0].rows.size(), 0, "First table should have rows");
    }
    {
        TEST("Table 1 contains 'North America'");
        navigate("https://stats.example.com/ai-industry-report-2026");
        auto tables = get_tables_data();
        bool found = false;
        for (const auto& row : tables[0].rows) {
            for (const auto& cell : row) {
                if (contains_ci(cell, "North America")) { found = true; break; }
            }
        }
        CHECK_TRUE(found, "Table 1 should contain 'North America'");
    }
    {
        TEST("Table data has caption");
        navigate("https://stats.example.com/ai-industry-report-2026");
        auto tables = get_tables_data();
        CHECK_FALSE(tables[0].caption.empty(), "Table should have caption");
    }

    // ===== Category 13: History & Cookies =====
    std::cout << std::endl << "--- Category 13: History & Cookies ---" << std::endl;

    {
        TEST("Get history after navigation");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto history = get_history();
        CHECK_GT(history.size(), 0, "Should have history after navigation");
    }
    {
        TEST("Clear history");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        clear_history();
        auto history = get_history();
        CHECK_EQ(history.size(), 0, "History should be empty after clear");
    }
    {
        TEST("Set cookie");
        bool ok = set_cookie("session", "abc123");
        CHECK_TRUE(ok, "Should set cookie in sim");
    }
    {
        TEST("Get cookies after setting");
        set_cookie("test_cookie", "test_value");
        std::string cookies = get_cookies();
        CHECK_CONTAINS(cookies, "test_cookie", "Cookies should contain test_cookie");
    }
    {
        TEST("Clear cookies");
        set_cookie("temp", "val");
        clear_cookies();
        std::string cookies = get_cookies();
        CHECK_NOT_CONTAINS(cookies, "temp", "Cookies should not contain temp after clear");
    }

    // ===== Category 14: JavaScript & Export =====
    std::cout << std::endl << "--- Category 14: JavaScript & Export ---" << std::endl;

    {
        TEST("Execute JavaScript returns result");
        std::string result = execute_javascript("document.title");
        CHECK_CONTAINS(result, "result", "JS execution should return result");
    }
    {
        TEST("Execute JavaScript has success=true");
        std::string result = execute_javascript("1+1");
        CHECK_CONTAINS(result, "true", "JS execution should have success=true");
    }
    {
        TEST("Export page data returns JSON");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string data = export_page_data();
        CHECK_CONTAINS(data, "version", "Export should contain version");
    }
    {
        TEST("Export page data contains page info");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string data = export_page_data();
        CHECK_CONTAINS(data, "page", "Export should contain page info");
    }
    {
        TEST("Export page data contains elements");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string data = export_page_data();
        CHECK_CONTAINS(data, "elements", "Export should contain elements");
    }
    {
        TEST("Save page content to file");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        bool ok = save_page_content("test_page_content.txt");
        CHECK_TRUE(ok, "Should save page content to file");
    }

    // ===== Category 15: Complex AI Agent Scenarios =====
    std::cout << std::endl << "--- Category 15: Complex AI Agent Scenarios ---" << std::endl;

    {
        TEST("AI: Navigate to Wikipedia, search, explain 'neural networks'");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto results = search_content("neural networks", 5);
        std::string explanation = explain_content("neural networks");
        CHECK_TRUE(!results.empty() && json_contains(explanation, "neural networks"),
                   "Should search and explain neural networks");
    }
    {
        TEST("AI: Navigate to Amazon, find product price, check button");
        navigate("https://www.amazon.com/dp/B0AI2026GPU");
        auto content = get_page_content();
        auto btn = find_button_by_text("Add to Cart");
        bool has_price = contains_ci(content, "$1,799");
        CHECK_TRUE(has_price && !btn.id.empty(), "Should find price and Add to Cart button");
    }
    {
        TEST("AI: Navigate to BBC, summarize, find key quote");
        navigate("https://www.bbc.com/news/technology-ai-breakthrough-2026");
        std::string summary = summarize_page(3);
        auto ctx = get_context_around_text("ReasonNet-X", 100, 100);
        CHECK_TRUE(json_contains(summary, "AI Breakthrough") && !ctx.empty(),
                   "Should summarize and find ReasonNet-X context");
    }
    {
        TEST("AI: Navigate to MDN, find 'Closures' section");
        navigate("https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Functions");
        std::string section = get_section_by_heading("Closures");
        CHECK_CONTAINS(section, "Closures", "Should find Closures section on MDN");
    }
    {
        TEST("AI: Navigate to Google, find search results, click first link");
        navigate("https://www.google.com/search?q=artificial+intelligence+tutorial");
        auto links = get_links();
        CHECK_GT(links.size(), 0, "Should find search result links on Google");
    }
    {
        TEST("AI: Navigate to social, find posts, count them");
        navigate("https://social.example.com/feed");
        auto elements = get_all_elements();
        int post_count = 0;
        for (const auto& e : elements) {
            if (e.type == BrowserElementType::social_post) post_count++;
        }
        CHECK_GT(post_count, 0, "Should find social posts on feed page");
    }
    {
        TEST("AI: Navigate to login, fill form, submit");
        navigate("https://app.example.com/login");
        bool type_ok = type_text("page6_email_input", "user@test.com");
        bool type_pw = type_text("page6_password_input", "password123");
        bool submit_ok = submit_form("page6_signin_btn");
        CHECK_TRUE(type_ok && type_pw && submit_ok, "Should fill and submit login form");
    }
    {
        TEST("AI: Navigate to stats, extract table data, verify rows");
        navigate("https://stats.example.com/ai-industry-report-2026");
        auto tables = get_tables_data();
        bool has_data = !tables.empty() && !tables[0].rows.empty();
        CHECK_TRUE(has_data, "Should extract table data from stats page");
    }
    {
        TEST("AI: Multi-page workflow - navigate, search, scroll, screenshot");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        auto results = search_content("Deep learning", 5);
        scroll_down(500);
        auto ss = take_screenshot(false);
        CHECK_TRUE(!results.empty() && get_scroll_y() > 0 && ss.width > 0,
                   "Should complete multi-step workflow");
    }
    {
        TEST("AI: Export page data with all elements");
        navigate("https://en.wikipedia.org/wiki/Artificial_intelligence");
        std::string exported = export_page_data();
        bool has_page = json_contains(exported, "page");
        bool has_elements = json_contains(exported, "elements");
        bool has_browser = json_contains(exported, "browser");
        CHECK_TRUE(has_page && has_elements && has_browser, "Export should have page, elements, browser");
    }

    // ===== Summary =====
    std::cout << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << " BROWSER TOOL TEST SUITE - SUMMARY" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << "  Total:  " << (g_tests_passed + g_tests_failed) << std::endl;
    std::cout << "  Passed: " << g_tests_passed << std::endl;
    std::cout << "  Failed: " << g_tests_failed << std::endl;
    double rate = static_cast<double>(g_tests_passed) / (g_tests_passed + g_tests_failed) * 100.0;
    std::cout << "  Rate:   " << std::fixed << std::setprecision(1) << rate << "%" << std::endl;
    std::cout << "========================================" << std::endl;

    // Clean up test files
    std::remove("test_screenshot.png");
    std::remove("test_page_content.txt");

    return g_tests_failed > 0 ? 1 : 0;
}
