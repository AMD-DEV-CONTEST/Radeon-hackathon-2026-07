#include "browser_tool.h"

#if defined(_WIN32)
    #ifndef NOMINMAX
    #define NOMINMAX
    #endif
    #include <windows.h>
    #include <objbase.h>
    #include <oleauto.h>
    #include <UIAutomation.h>
    #pragma comment(lib, "ole32.lib")
    #pragma comment(lib, "oleaut32.lib")
    #pragma comment(lib, "uiautomationcore.lib")
#elif defined(__linux__)
    #include <X11/Xlib.h>
#elif defined(__APPLE__)
    #include <ApplicationServices/ApplicationServices.h>
#endif

#include <fstream>
#include <chrono>
#include <thread>
#include <ctime>
#include <cmath>
#include <set>
#include <algorithm>

namespace browsertool {

// ===== Global State =====
static bool g_simulation_mode = false;
static Platform g_platform = Platform::Windows;

// Simulation state
static std::vector<PageInfo> g_sim_pages;
static std::vector<BrowserElement> g_sim_elements;
static std::vector<TabInfo> g_sim_tabs;
static int g_sim_active_tab = 0;
static int g_sim_current_page = 0;
static std::vector<std::string> g_sim_history;
static int g_sim_scroll_x = 0;
static int g_sim_scroll_y = 0;
static std::map<std::string, std::string> g_sim_cookies;
static std::string g_sim_js_result;

// ===== Platform Detection =====
Platform get_current_platform() {
    if (g_simulation_mode) return Platform::Simulation;
#if defined(_WIN32)
    return Platform::Windows;
#elif defined(__linux__)
    return Platform::Linux;
#elif defined(__APPLE__)
    return Platform::macOS;
#elif defined(__ANDROID__)
    return Platform::Android;
#else
    return Platform::Windows;
#endif
}

std::string platform_to_string(Platform p) {
    switch (p) {
        case Platform::Windows: return "windows";
        case Platform::Linux: return "linux";
        case Platform::macOS: return "macos";
        case Platform::Android: return "android";
        case Platform::iOS: return "ios";
        case Platform::Simulation: return "simulation";
        default: return "unknown";
    }
}

void enable_simulation_mode() {
    g_simulation_mode = true;
    g_platform = Platform::Simulation;
}

bool is_simulation_mode() { return g_simulation_mode; }

// ===== Utility Functions =====
bool contains_ci(const std::string& haystack, const std::string& needle) {
    if (needle.empty()) return true;
    if (haystack.size() < needle.size()) return false;
    auto to_lower = [](const std::string& s) {
        std::string r;
        for (char c : s) r += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        return r;
    };
    std::string h = to_lower(haystack);
    std::string n = to_lower(needle);
    return h.find(n) != std::string::npos;
}

double fuzzy_match(const std::string& a, const std::string& b) {
    if (a.empty() && b.empty()) return 1.0;
    if (a.empty() || b.empty()) return 0.0;
    auto to_lower = [](const std::string& s) {
        std::string r;
        for (char c : s) r += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        return r;
    };
    std::string s1 = to_lower(a);
    std::string s2 = to_lower(b);
    if (s1 == s2) return 1.0;
    if (s1.find(s2) != std::string::npos || s2.find(s1) != std::string::npos) return 0.9;

    size_t len1 = s1.size(), len2 = s2.size();
    std::vector<size_t> prev(len2 + 1), curr(len2 + 1);
    for (size_t j = 0; j <= len2; j++) prev[j] = j;
    for (size_t i = 1; i <= len1; i++) {
        curr[0] = i;
        for (size_t j = 1; j <= len2; j++) {
            size_t cost = (s1[i-1] == s2[j-1]) ? 0 : 1;
            curr[j] = std::min({prev[j] + 1, curr[j-1] + 1, prev[j-1] + cost});
        }
        prev = curr;
    }
    double dist = static_cast<double>(prev[len2]);
    return 1.0 - dist / std::max(len1, len2);
}

// ===== JSON Serialization Helpers =====
std::string elements_to_json(const std::vector<BrowserElement>& elements) {
    std::ostringstream ss;
    ss << "{\"total_elements\":" << elements.size() << ",\"elements\":[";
    for (size_t i = 0; i < elements.size(); i++) {
        if (i > 0) ss << ",";
        ss << elements[i].to_json();
    }
    ss << "]}";
    return ss.str();
}

std::string element_to_json(const BrowserElement& element) {
    std::ostringstream ss;
    ss << "{\"element\":" << element.to_json() << "}";
    return ss.str();
}

std::string page_info_to_json(const PageInfo& info) {
    std::ostringstream ss;
    ss << "{\"page\":" << info.to_json() << "}";
    return ss.str();
}

std::string tabs_to_json(const std::vector<TabInfo>& tabs) {
    std::ostringstream ss;
    ss << "{\"total_tabs\":" << tabs.size() << ",\"tabs\":[";
    for (size_t i = 0; i < tabs.size(); i++) {
        if (i > 0) ss << ",";
        ss << tabs[i].to_json();
    }
    ss << "]}";
    return ss.str();
}

std::string search_results_to_json(const std::vector<ContentSearchResult>& results) {
    std::ostringstream ss;
    ss << "{\"total_results\":" << results.size() << ",\"results\":[";
    for (size_t i = 0; i < results.size(); i++) {
        if (i > 0) ss << ",";
        ss << results[i].to_json();
    }
    ss << "]}";
    return ss.str();
}

std::string screenshot_to_json(const ScreenshotInfo& info) {
    std::ostringstream ss;
    ss << "{\"screenshot\":" << info.to_json() << "}";
    return ss.str();
}

std::string browser_info_to_json(const BrowserInfo& info) {
    std::ostringstream ss;
    ss << "{\"browser\":" << info.to_json() << "}";
    return ss.str();
}

std::string table_data_to_json(const std::vector<TableData>& tables) {
    std::ostringstream ss;
    ss << "{\"total_tables\":" << tables.size() << ",\"tables\":[";
    for (size_t i = 0; i < tables.size(); i++) {
        if (i > 0) ss << ",";
        ss << tables[i].to_json();
    }
    ss << "]}";
    return ss.str();
}

std::string form_fields_to_json(const std::vector<FormField>& fields) {
    std::ostringstream ss;
    ss << "{\"total_fields\":" << fields.size() << ",\"fields\":[";
    for (size_t i = 0; i < fields.size(); i++) {
        if (i > 0) ss << ",";
        ss << fields[i].to_json();
    }
    ss << "]}";
    return ss.str();
}

// ===== Simulation Data Setup =====
void setup_simulation_data() {
    g_sim_pages.clear();
    g_sim_elements.clear();
    g_sim_tabs.clear();
    g_sim_history.clear();
    g_sim_cookies.clear();
    g_sim_scroll_x = 0;
    g_sim_scroll_y = 0;
    g_sim_active_tab = 0;
    g_sim_current_page = 0;

    // --- Page 1: Wikipedia Article about AI ---
    {
        PageInfo page;
        page.url = "https://en.wikipedia.org/wiki/Artificial_intelligence";
        page.title = "Artificial intelligence - Wikipedia";
        page.domain = "en.wikipedia.org";
        page.protocol = "https";
        page.path = "/wiki/Artificial_intelligence";
        page.meta_description = "Artificial intelligence (AI) is the intelligence of machines or software, as opposed to the intelligence of humans or animals.";
        page.meta_keywords = "artificial intelligence, AI, machine learning, deep learning, neural networks";
        page.language = "en";
        page.charset = "UTF-8";
        page.status_code = 200;
        page.loading = false;
        page.secure = true;
        page.page_width = 1920;
        page.page_height = 5000;
        page.viewport_width = 1920;
        page.viewport_height = 1080;
        page.scroll_max_x = 0;
        page.scroll_max_y = 3920;
        page.favicon_url = "https://en.wikipedia.org/favicon.ico";
        page.canonical_url = "https://en.wikipedia.org/wiki/Artificial_intelligence";
        page.page_type = "article";
        page.breadcrumbs = {"Wikipedia", "Artificial intelligence"};
        page.content_text =
            "Artificial intelligence\n"
            "From Wikipedia, the free encyclopedia\n"
            "Artificial intelligence (AI) is the intelligence of machines or software, as opposed to the intelligence of humans or animals. "
            "It is a field of study in computer science that develops and studies intelligent machines. Such machines may be called AIs.\n"
            "AI technology is widely used throughout industry, government, and science. Some high-profile applications include advanced web search engines; "
            "recommendation systems; understanding human speech; self-driving cars; generative and creative tools; and superhuman play and analysis in strategy games.\n"
            "\n"
            "History\n"
            "The study of artificial intelligence began in the 1940s and 1950s with the work of Alan Turing, who proposed the Turing Test as a measure of machine intelligence. "
            "The term \"artificial intelligence\" was coined by John McCarthy in 1956 at the Dartmouth Conference, which is considered the founding event of AI as a field.\n"
            "In the early days, researchers were optimistic about creating general AI within a generation. However, progress was slower than expected, leading to periods of "
            "reduced funding known as \"AI winters\" in the 1970s and 1990s.\n"
            "\n"
            "Machine Learning\n"
            "Machine learning is a subset of AI that enables systems to learn and improve from experience without being explicitly programmed. "
            "Machine learning algorithms build mathematical models based on training data to make predictions or decisions. "
            "Key approaches include supervised learning, unsupervised learning, and reinforcement learning.\n"
            "Deep learning is a specialized form of machine learning that uses neural networks with multiple layers (hence \"deep\") to process complex patterns in data. "
            "Deep learning has been particularly successful in image recognition, natural language processing, and game playing.\n"
            "\n"
            "Neural Networks\n"
            "Artificial neural networks are computing systems inspired by the biological neural networks in animal brains. "
            "A neural network consists of layers of interconnected nodes (neurons), each of which performs a simple computation. "
            "The network learns by adjusting the weights of connections between neurons based on training data.\n"
            "Modern neural networks can have millions or billions of parameters and are trained on massive datasets using powerful hardware like GPUs.\n"
            "\n"
            "Applications\n"
            "AI has applications in numerous fields including healthcare, finance, transportation, education, and entertainment. "
            "In healthcare, AI is used for disease diagnosis, drug discovery, and personalized treatment plans. "
            "In finance, AI powers algorithmic trading, fraud detection, and risk assessment. "
            "In transportation, self-driving cars use AI to perceive their environment and make driving decisions.\n"
            "\n"
            "Ethics and Risks\n"
            "The development of AI raises ethical concerns including bias in AI systems, privacy issues, job displacement, and the potential for AI to be used maliciously. "
            "Researchers and policymakers are working on frameworks for responsible AI development, including fairness, transparency, and accountability.\n"
            "The long-term risk of artificial general intelligence (AGI) surpassing human intelligence is also a topic of serious discussion among researchers.\n"
            "\n"
            "See also: Machine learning, Deep learning, Neural network, Natural language processing, Computer vision, Robotics, Turing test.\n"
            "Categories: Artificial intelligence | Computer science | Emerging technologies\n"
            "This article was last edited on August 1, 2026.";
        g_sim_pages.push_back(page);
    }

    // --- Page 2: Google Search Results ---
    {
        PageInfo page;
        page.url = "https://www.google.com/search?q=artificial+intelligence+tutorial";
        page.title = "artificial intelligence tutorial - Google Search";
        page.domain = "www.google.com";
        page.protocol = "https";
        page.path = "/search?q=artificial+intelligence+tutorial";
        page.meta_description = "Search results for artificial intelligence tutorial";
        page.language = "en";
        page.charset = "UTF-8";
        page.status_code = 200;
        page.secure = true;
        page.page_width = 1920;
        page.page_height = 3000;
        page.scroll_max_y = 1920;
        page.page_type = "search_results";
        page.breadcrumbs = {"Google", "Search", "artificial intelligence tutorial"};
        page.content_text =
            "artificial intelligence tutorial - Google Search\n"
            "About 145,000,000 results (0.42 seconds)\n"
            "\n"
            "Result 1: Artificial Intelligence Tutorial - Tutorialspoint\n"
            "https://www.tutorialspoint.com/artificial_intelligence/\n"
            "This tutorial provides introductory knowledge on Artificial Intelligence. It would come to a great help if you are about to select AI as a course subject.\n"
            "\n"
            "Result 2: Introduction to AI - Stanford University\n"
            "https://ai.stanford.edu/ai-introduction/\n"
            "Stanford AI Lab - Introduction to Artificial Intelligence. Learn about the fundamentals of AI, machine learning, and their applications.\n"
            "\n"
            "Result 3: Machine Learning Crash Course - Google Developers\n"
            "https://developers.google.com/machine-learning/crash-course\n"
            "Google's fast-paced, practical introduction to machine learning. Learn best practices from Google experts on machine learning.\n"
            "\n"
            "Result 4: Deep Learning Specialization - Coursera\n"
            "https://www.coursera.org/specializations/deep-learning\n"
            "Master deep learning, understand how to build neural networks, and lead successful machine learning projects.\n"
            "\n"
            "Result 5: AI for Everyone - Coursera\n"
            "https://www.coursera.org/learn/ai-for-everyone\n"
            "AI is not only for engineers. This non-technical course helps you understand AI technologies and how to apply them in your organization.\n"
            "\n"
            "Result 6: Artificial Intelligence: A Modern Approach\n"
            "https://aima.cs.berkeley.edu/\n"
            "The leading textbook in AI, by Stuart Russell and Peter Norvig. Covers the most widely used AI technologies.\n"
            "\n"
            "Result 7: OpenAI - Research and Engineering\n"
            "https://openai.com/research/\n"
            "OpenAI's research papers and engineering blog covering GPT, DALL-E, and other AI breakthroughs.\n"
            "\n"
            "Result 8: TensorFlow Tutorials\n"
            "https://www.tensorflow.org/tutorials\n"
            "TensorFlow tutorials for beginners and experts. Learn how to build, train, and deploy machine learning models.\n"
            "\n"
            "Related searches: machine learning tutorial, deep learning course, AI programming, neural networks explained\n"
            "Page 1 of about 1,450,000 results";
        g_sim_pages.push_back(page);
    }

    // --- Page 3: News Article ---
    {
        PageInfo page;
        page.url = "https://www.bbc.com/news/technology-ai-breakthrough-2026";
        page.title = "AI Breakthrough: New Model Achieves Human-Level Reasoning - BBC News";
        page.domain = "www.bbc.com";
        page.protocol = "https";
        page.path = "/news/technology-ai-breakthrough-2026";
        page.meta_description = "Researchers announce a breakthrough in AI reasoning capabilities, with a new model matching human performance on complex tasks.";
        page.language = "en";
        page.charset = "UTF-8";
        page.status_code = 200;
        page.secure = true;
        page.page_width = 1920;
        page.page_height = 4000;
        page.scroll_max_y = 2920;
        page.page_type = "news";
        page.breadcrumbs = {"BBC News", "Technology", "AI"};
        page.content_text =
            "AI Breakthrough: New Model Achieves Human-Level Reasoning\n"
            "By Jane Technology Correspondent\n"
            "3 August 2026\n"
            "\n"
            "Researchers at a leading AI laboratory have announced a significant breakthrough in artificial intelligence, "
            "with a new model demonstrating human-level reasoning capabilities on a range of complex cognitive tasks.\n"
            "\n"
            "The model, known as ReasonNet-X, was developed over three years by a team of 50 researchers. "
            "It achieved scores matching or exceeding human performance on benchmarks including logical reasoning, "
            "mathematical problem-solving, and scientific analysis.\n"
            "\n"
            "\"This is a milestone moment for the field of AI,\" said Dr. Sarah Chen, the project's lead researcher. "
            "\"For the first time, we have a system that can reason about complex problems in a way that is genuinely "
            "comparable to human thinking, not just pattern matching.\"\n"
            "\n"
            "The breakthrough builds on recent advances in large language models and reinforcement learning. "
            "The key innovation is a new architecture called Recursive Reasoning Networks, which allows the model "
            "to break down complex problems into smaller steps and reason about each step individually.\n"
            "\n"
            "However, some experts have urged caution. Professor Michael Roberts of Cambridge University said: "
            "\"While these results are impressive, we need to be careful about claiming human-level intelligence. "
            "Reasoning in controlled benchmarks is very different from reasoning in the messy real world.\"\n"
            "\n"
            "The researchers say the model will be open-sourced next month, allowing other scientists to verify "
            "the results and build upon the technology. They emphasize that the system is designed to assist humans, "
            "not replace them.\n"
            "\n"
            "Potential applications include scientific research, medical diagnosis, legal analysis, and education. "
            "The team is already working with hospitals to test the system's ability to assist doctors in diagnosing "
            "rare diseases.\n"
            "\n"
            "The announcement has sparked both excitement and concern in the AI community. While many see it as a "
            "major step forward, others worry about the implications of increasingly capable AI systems.\n"
            "\n"
            "\"We need to have serious conversations about how this technology is used,\" said Dr. Chen. "
            "\"AI this powerful comes with significant responsibility. We are committed to developing it safely and ethically.\"\n"
            "\n"
            "The research paper has been published in the journal Nature and is available online.\n"
            "\n"
            "Related topics: Artificial intelligence | Technology | Science | Research\n"
            "Share this article | Comments (1,247) | Published at 14:32 GMT";
        g_sim_pages.push_back(page);
    }

    // --- Page 4: E-commerce Product Page ---
    {
        PageInfo page;
        page.url = "https://www.amazon.com/dp/B0AI2026GPU";
        page.title = "NVIDIA RTX 5090 Graphics Card - 32GB GDDR7 - Amazon.com";
        page.domain = "www.amazon.com";
        page.protocol = "https";
        page.path = "/dp/B0AI2026GPU";
        page.meta_description = "NVIDIA RTX 5090 Graphics Card with 32GB GDDR7 memory, 2.5GHz clock speed, PCIe 5.0. Free shipping.";
        page.language = "en";
        page.charset = "UTF-8";
        page.status_code = 200;
        page.secure = true;
        page.page_width = 1920;
        page.page_height = 4500;
        page.scroll_max_y = 3420;
        page.page_type = "product";
        page.breadcrumbs = {"Amazon", "Electronics", "Computer Components", "Graphics Cards"};
        page.content_text =
            "NVIDIA RTX 5090 Graphics Card - 32GB GDDR7\n"
            "Brand: NVIDIA | Model: RTX 5090 Founders Edition\n"
            "Price: $1,799.00\n"
            "Regular Price: $1,999.00\n"
            "You Save: $200.00 (10%)\n"
            "In Stock - FREE Shipping by tomorrow\n"
            "\n"
            "About this item:\n"
            "- 32GB GDDR7 memory with 1,008 GB/s memory bandwidth\n"
            "- 2.5GHz boost clock speed with 21,760 CUDA cores\n"
            "- PCIe 5.0 interface, 3x DisplayPort 2.1, 1x HDMI 2.1\n"
            "- Ray tracing cores 3rd generation, Tensor cores 5th generation\n"
            "- DLSS 4.0 with AI frame generation\n"
            "- 450W TDP, requires 1000W power supply\n"
            "- Triple fan cooling system with vapor chamber\n"
            "\n"
            "Technical Details:\n"
            "GPU Architecture: Blackwell\n"
            "Memory: 32GB GDDR7\n"
            "Memory Speed: 28 Gbps\n"
            "Boost Clock: 2.5 GHz\n"
            "CUDA Cores: 21,760\n"
            "RT Cores: 170\n"
            "Tensor Cores: 680\n"
            "Interface: PCIe 5.0 x16\n"
            "Power Connector: 1x 12V-2x6\n"
            "Recommended PSU: 1000W\n"
            "Length: 304mm\n"
            "Height: 137mm\n"
            "Slots: 3.5\n"
            "\n"
            "Customer Reviews: 4.7 out of 5 stars (2,341 ratings)\n"
            "\n"
            "Top Review by TechReviewer123:\n"
            "\"Absolutely incredible performance. This card handles 4K gaming at 120fps with ray tracing enabled. "
            "The AI frame generation is seamless and the temperatures stay well under control. Best GPU I've ever owned.\"\n"
            "5.0 out of 5 stars - Verified Purchase - March 15, 2026\n"
            "\n"
            "Review by GamerPro:\n"
            "\"Worth every penny. The performance jump from RTX 4090 is significant, especially in AI workloads. "
            "DLSS 4.0 is a game changer. Only complaint is the size - make sure your case is big enough.\"\n"
            "4.0 out of 5 stars - Verified Purchase - April 2, 2026\n"
            "\n"
            "Frequently Bought Together:\n"
            "1. NVIDIA RTX 5090 - $1,799.00\n"
            "2. Corsair 1000W PSU - $189.99\n"
            "3. PCIe 5.0 Riser Cable - $39.99\n"
            "Total: $2,028.98 (Save $50)\n"
            "\n"
            "Add to Cart | Buy Now | Add to Wish List\n"
            "Ships from and sold by Amazon.com\n"
            "Return policy: 30-day returns\n"
            "Warranty: 3-year limited warranty";
        g_sim_pages.push_back(page);
    }

    // --- Page 5: Documentation Page ---
    {
        PageInfo page;
        page.url = "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Functions";
        page.title = "Functions - JavaScript | MDN";
        page.domain = "developer.mozilla.org";
        page.protocol = "https";
        page.path = "/en-US/docs/Web/JavaScript/Guide/Functions";
        page.meta_description = "Functions are one of the fundamental building blocks in JavaScript. A function is a reusable set of statements.";
        page.language = "en";
        page.charset = "UTF-8";
        page.status_code = 200;
        page.secure = true;
        page.page_width = 1920;
        page.page_height = 6000;
        page.scroll_max_y = 4920;
        page.page_type = "documentation";
        page.breadcrumbs = {"MDN", "Web", "JavaScript", "Guide", "Functions"};
        page.content_text =
            "Functions\n"
            "Functions are one of the fundamental building blocks in JavaScript. "
            "A function is a reusable set of statements that performs a task or calculates a value.\n"
            "\n"
            "Function declarations\n"
            "A function declaration (also called a function statement) consists of the function keyword, "
            "followed by the function name, a list of parameters, and the function body.\n"
            "Example: function square(number) { return number * number; }\n"
            "The function square takes one parameter, called number. The function consists of one statement "
            "that says to return the parameter of the function multiplied by itself.\n"
            "\n"
            "Function expressions\n"
            "A function expression is a function that is assigned to a variable. "
            "Example: const square = function(number) { return number * number; }\n"
            "Function expressions can be anonymous, meaning they don't have to have a name.\n"
            "\n"
            "Arrow functions\n"
            "Arrow functions provide a shorter syntax for writing function expressions. "
            "Example: const square = (number) => number * number;\n"
            "Arrow functions are always anonymous and do not have their own this, arguments, super, or new.target.\n"
            "\n"
            "Parameters\n"
            "Parameters are variables listed as part of the function definition. "
            "Arguments are values passed to the function when it is invoked. "
            "JavaScript functions can accept any number of arguments, regardless of the number of parameters declared.\n"
            "Default parameters allow you to specify default values for parameters.\n"
            "Example: function greet(name = 'World') { return 'Hello, ' + name; }\n"
            "\n"
            "Rest parameters\n"
            "The rest parameter syntax allows us to represent an indefinite number of arguments as an array. "
            "Example: function sum(...numbers) { return numbers.reduce((a, b) => a + b, 0); }\n"
            "\n"
            "Closures\n"
            "Closures are functions that refer to independent (free) variables. In other words, the function "
            "defined in the closure remembers the environment in which it was created. "
            "Example: function makeAdder(x) { return function(y) { return x + y; }; }\n"
            "Closures are useful for creating private variables and functions.\n"
            "\n"
            "Using objects\n"
            "Functions can work with objects as parameters. JavaScript passes objects by reference, "
            "so changes to the object inside the function affect the original object.\n"
            "\n"
            "Function scope\n"
            "Variables defined inside a function cannot be accessed from outside the function. "
            "This is called function scope. Variables declared with var are function-scoped, "
            "while variables declared with let and const are block-scoped.\n"
            "\n"
            "Recursion\n"
            "A function that calls itself is called recursive. Recursion is useful for tasks that can be "
            "broken down into smaller, similar subtasks.\n"
            "Example: function factorial(n) { if (n <= 1) return 1; return n * factorial(n - 1); }\n"
            "\n"
            "See also: Arrow functions, Closures, Default parameters, Rest parameters, IIFE\n"
            "Last updated: Jul 28, 2026";
        g_sim_pages.push_back(page);
    }

    // --- Page 6: Social Media Feed ---
    {
        PageInfo page;
        page.url = "https://social.example.com/feed";
        page.title = "Home / Social Feed";
        page.domain = "social.example.com";
        page.protocol = "https";
        page.path = "/feed";
        page.meta_description = "Your social media feed with posts from people you follow.";
        page.language = "en";
        page.charset = "UTF-8";
        page.status_code = 200;
        page.secure = true;
        page.page_width = 1920;
        page.page_height = 8000;
        page.scroll_max_y = 6920;
        page.page_type = "social";
        page.breadcrumbs = {"Social", "Home", "Feed"};
        page.content_text =
            "Home / Social Feed\n"
            "What's happening? [Compose new post...]\n"
            "\n"
            "Post 1 by @techguru (2 minutes ago):\n"
            "Just tried the new AI-powered code editor and it's absolutely mind-blowing! "
            "It can understand entire codebases and suggest refactoring that actually makes sense. "
            "The future of programming is here. #AI #Coding #Tech\n"
            "Likes: 1,234 | Comments: 89 | Shares: 234\n"
            "\n"
            "Post 2 by @datascientist (15 minutes ago):\n"
            "Hot take: Most companies saying they do 'AI' are just doing basic statistics with extra steps. "
            "True AI requires understanding causality, not just correlation. Change my mind. #MachineLearning #DataScience\n"
            "Likes: 567 | Comments: 234 | Shares: 78\n"
            "\n"
            "Post 3 by @ailover (1 hour ago):\n"
            "I've been using AI to help me learn Japanese for 3 months now and I can finally have basic conversations! "
            "The personalized learning path and instant feedback are game changers. Highly recommend! #LanguageLearning #AI\n"
            "Likes: 2,345 | Comments: 156 | Shares: 445\n"
            "\n"
            "Post 4 by @skeptical_dev (2 hours ago):\n"
            "Reminder that AI is a tool, not a replacement for human judgment. "
            "Always verify AI-generated content, especially for critical decisions. "
            "Trust but verify. #AI #Ethics #Tech\n"
            "Likes: 3,456 | Comments: 312 | Shares: 891\n"
            "\n"
            "Post 5 by @startup_ceo (3 hours ago):\n"
            "We just integrated AI into our customer support and reduced response times by 80%. "
            "Customer satisfaction is up 35%. The key was training it on our own support history. "
            "Not magic, just good engineering. #Business #AI #CustomerSupport\n"
            "Likes: 1,890 | Comments: 234 | Shares: 567\n"
            "\n"
            "Post 6 by @researcher (5 hours ago):\n"
            "New paper just published: 'Recursive Reasoning Networks for Complex Problem Solving'. "
            "The results are remarkable - the model achieves human-level performance on logical reasoning benchmarks. "
            "This could change everything. #AI #Research #Science\n"
            "Likes: 4,567 | Comments: 456 | Shares: 1,234\n"
            "\n"
            "Post 7 by @devlife (8 hours ago):\n"
            "When the AI suggests a fix and it actually works on the first try: "
            "Me: *surprised pikachu face* #Programming #AI #DevLife\n"
            "Likes: 8,901 | Comments: 234 | Shares: 1,567\n"
            "\n"
            "Trending: #AI #MachineLearning #TechNews #Programming #DataScience\n"
            "Who to follow: @airesearcher @mlengineer @technews";
        g_sim_pages.push_back(page);
    }

    // --- Page 7: Login Form Page ---
    {
        PageInfo page;
        page.url = "https://app.example.com/login";
        page.title = "Sign In - Example App";
        page.domain = "app.example.com";
        page.protocol = "https";
        page.path = "/login";
        page.meta_description = "Sign in to your Example App account.";
        page.language = "en";
        page.charset = "UTF-8";
        page.status_code = 200;
        page.secure = true;
        page.page_width = 1920;
        page.page_height = 1080;
        page.scroll_max_y = 0;
        page.page_type = "login";
        page.breadcrumbs = {"Example App", "Sign In"};
        page.content_text =
            "Sign In\n"
            "Welcome back! Please enter your credentials to access your account.\n"
            "\n"
            "Email: [________________________]\n"
            "Password: [________________________]\n"
            "Remember me [ ]\n"
            "Forgot password?\n"
            "\n"
            "[ Sign In ]\n"
            "\n"
            "Don't have an account? Sign up here.\n"
            "Or sign in with:\n"
            "[ Google ] [ GitHub ] [ Microsoft ]\n"
            "\n"
            "By signing in, you agree to our Terms of Service and Privacy Policy.\n"
            "Need help? Contact support@example.com\n"
            "© 2026 Example App. All rights reserved.";
        g_sim_pages.push_back(page);
    }

    // --- Page 8: Data Table / Statistics Page ---
    {
        PageInfo page;
        page.url = "https://stats.example.com/ai-industry-report-2026";
        page.title = "AI Industry Report 2026 - Statistics & Data";
        page.domain = "stats.example.com";
        page.protocol = "https";
        page.path = "/ai-industry-report-2026";
        page.meta_description = "Comprehensive AI industry statistics for 2026 including market size, adoption rates, and growth projections.";
        page.language = "en";
        page.charset = "UTF-8";
        page.status_code = 200;
        page.secure = true;
        page.page_width = 1920;
        page.page_height = 3500;
        page.scroll_max_y = 2420;
        page.page_type = "table";
        page.breadcrumbs = {"Statistics", "Reports", "AI Industry 2026"};
        page.content_text =
            "AI Industry Report 2026\n"
            "Published: January 2026 | Source: Global AI Research Institute\n"
            "\n"
            "Table 1: AI Market Size by Region (2024-2026)\n"
            "Region | 2024 | 2025 | 2026 | Growth Rate\n"
            "North America | $87.3B | $112.5B | $145.2B | 29.0%\n"
            "Europe | $45.6B | $58.9B | $76.1B | 29.2%\n"
            "Asia Pacific | $62.1B | $81.3B | $106.5B | 31.0%\n"
            "Latin America | $8.2B | $10.7B | $13.9B | 29.9%\n"
            "Middle East & Africa | $5.1B | $6.8B | $9.1B | 33.8%\n"
            "Total | $208.3B | $270.2B | $350.8B | 29.8%\n"
            "\n"
            "Table 2: AI Adoption by Industry\n"
            "Industry | Adoption Rate | Primary Use Case | Investment Level\n"
            "Technology | 89% | Product development | High\n"
            "Healthcare | 72% | Diagnostics & imaging | High\n"
            "Finance | 78% | Risk assessment & fraud | High\n"
            "Manufacturing | 65% | Quality control & automation | Medium\n"
            "Retail | 61% | Customer personalization | Medium\n"
            "Education | 54% | Personalized learning | Medium\n"
            "Transportation | 48% | Route optimization | Medium\n"
            "Agriculture | 32% | Crop monitoring | Low\n"
            "\n"
            "Table 3: AI Job Market Statistics\n"
            "Job Role | Open Positions | Avg Salary | YoY Growth\n"
            "ML Engineer | 45,200 | $165,000 | +34%\n"
            "Data Scientist | 38,700 | $142,000 | +28%\n"
            "AI Research Scientist | 12,300 | $195,000 | +45%\n"
            "NLP Engineer | 18,900 | $158,000 | +52%\n"
            "Computer Vision Engineer | 15,600 | $162,000 | +41%\n"
            "AI Product Manager | 22,100 | $175,000 | +38%\n"
            "MLOps Engineer | 28,400 | $155,000 | +67%\n"
            "\n"
            "Table 4: Popular AI Frameworks Usage\n"
            "Framework | Market Share | Primary Language | License\n"
            "TensorFlow | 32% | Python | Apache 2.0\n"
            "PyTorch | 41% | Python | BSD\n"
            "Scikit-learn | 18% | Python | BSD\n"
            "Keras | 12% | Python | MIT\n"
            "JAX | 8% | Python | Apache 2.0\n"
            "\n"
            "Key Findings:\n"
            "1. The global AI market reached $350.8B in 2026, growing 29.8% year-over-year.\n"
            "2. Asia Pacific shows the highest growth rate at 31.0%, driven by China and India.\n"
            "3. Technology and Finance sectors lead in AI adoption with 89% and 78% respectively.\n"
            "4. MLOps Engineer roles saw the highest growth at 67% year-over-year.\n"
            "5. PyTorch has overtaken TensorFlow as the most popular framework with 41% market share.\n"
            "\n"
            "Download full report (PDF) | Share this data | Cite this page";
        g_sim_pages.push_back(page);
    }

    // --- Create elements for each page ---
    int elem_id_counter = 0;
    for (size_t pi = 0; pi < g_sim_pages.size(); pi++) {
        auto& p = g_sim_pages[pi];
        std::string page_prefix = "page" + std::to_string(pi) + "_";

        // Header/Nav
        {
            BrowserElement e;
            e.id = page_prefix + "header";
            e.tag = "header";
            e.type = BrowserElementType::header;
            e.text = p.title;
            e.bounds = {0, 0, 1920, 80};
            e.is_container = true;
            e.parent_id = "";
            g_sim_elements.push_back(e);
        }
        {
            BrowserElement e;
            e.id = page_prefix + "nav";
            e.tag = "nav";
            e.type = BrowserElementType::nav;
            e.text = "Navigation";
            e.bounds = {0, 80, 1920, 50};
            e.is_container = true;
            e.parent_id = page_prefix + "header";
            g_sim_elements.push_back(e);
        }

        // Title heading
        {
            BrowserElement e;
            e.id = page_prefix + "h1_title";
            e.tag = "h1";
            e.type = BrowserElementType::heading1;
            e.text = p.title;
            e.bounds = {320, 140, 1280, 60};
            e.parent_id = "";
            g_sim_elements.push_back(e);
        }

        // Meta description
        if (!p.meta_description.empty()) {
            BrowserElement e;
            e.id = page_prefix + "meta_desc";
            e.tag = "meta";
            e.type = BrowserElementType::meta;
            e.text = p.meta_description;
            e.bounds = {320, 200, 1280, 40};
            e.parent_id = "";
            g_sim_elements.push_back(e);
        }

        // Breadcrumbs
        if (!p.breadcrumbs.empty()) {
            BrowserElement e;
            e.id = page_prefix + "breadcrumbs";
            e.tag = "nav";
            e.type = BrowserElementType::breadcrumb;
            std::string bc;
            for (size_t i = 0; i < p.breadcrumbs.size(); i++) {
                if (i > 0) bc += " > ";
                bc += p.breadcrumbs[i];
            }
            e.text = bc;
            e.bounds = {320, 210, 1280, 30};
            e.parent_id = "";
            g_sim_elements.push_back(e);
        }

        // Content area
        {
            BrowserElement e;
            e.id = page_prefix + "content";
            e.tag = "main";
            e.type = BrowserElementType::main_;
            e.text = "Main content area";
            e.bounds = {320, 250, 1280, p.page_height - 350};
            e.is_container = true;
            e.parent_id = "";
            g_sim_elements.push_back(e);
        }

        // Parse content text into paragraphs and headings
        std::istringstream content_stream(p.content_text);
        std::string line;
        int y_pos = 260;
        int para_idx = 0;
        while (std::getline(content_stream, line)) {
            if (line.empty()) {
                y_pos += 10;
                continue;
            }

            // Check if it's a heading (short line, no period at end, or starts with "Result", "Table", "Post", "Section")
            bool is_heading = false;
            int heading_level = 2;
            if (line.size() < 80 && line.back() != '.' && line.back() != ',') {
                if (line.find("Result ") == 0 || line.find("Table ") == 0 ||
                    line.find("Post ") == 0 || line.find("Section ") == 0) {
                    is_heading = true;
                    heading_level = 3;
                } else if (line == "History" || line == "Machine Learning" || line == "Neural Networks" ||
                           line == "Applications" || line == "Ethics and Risks" ||
                           line == "Function declarations" || line == "Function expressions" ||
                           line == "Arrow functions" || line == "Parameters" || line == "Rest parameters" ||
                           line == "Closures" || line == "Using objects" || line == "Function scope" ||
                           line == "Recursion" || line == "Key Findings" || line == "See also:" ||
                           line == "About this item:" || line == "Technical Details:" ||
                           line == "Customer Reviews:" || line == "Frequently Bought Together:" ||
                           line == "Top Review by TechReviewer123:" || line == "Related searches:" ||
                           line == "Trending:" || line == "Who to follow:" || line == "Who to follow:") {
                    is_heading = true;
                    heading_level = 2;
                }
            }

            BrowserElement e;
            e.id = page_prefix + "p" + std::to_string(para_idx);
            if (is_heading) {
                e.tag = "h" + std::to_string(heading_level);
                e.type = (heading_level == 2) ? BrowserElementType::heading2 : BrowserElementType::heading3;
                e.bounds = {320, y_pos, 1280, 40};
                y_pos += 50;
            } else {
                e.tag = "p";
                e.type = BrowserElementType::paragraph;
                int h = std::max(30, static_cast<int>(line.size() / 80) * 25 + 25);
                e.bounds = {320, y_pos, 1280, h};
                y_pos += h + 10;
            }
            e.text = line;
            e.parent_id = page_prefix + "content";
            g_sim_elements.push_back(e);
            para_idx++;
        }

        // Footer
        {
            BrowserElement e;
            e.id = page_prefix + "footer";
            e.tag = "footer";
            e.type = BrowserElementType::footer;
            e.text = "Footer - Copyright 2026";
            e.bounds = {0, p.page_height - 100, 1920, 100};
            e.is_container = true;
            e.parent_id = "";
            g_sim_elements.push_back(e);
        }

        // Page-specific elements
        if (p.page_type == "search_results") {
            // Search input
            {
                BrowserElement e;
                e.id = page_prefix + "search_input";
                e.tag = "input";
                e.type = BrowserElementType::search_input;
                e.text = "";
                e.placeholder = "Search Google";
                e.value = "artificial intelligence tutorial";
                e.bounds = {400, 90, 600, 44};
                e.is_input = true;
                e.parent_id = page_prefix + "header";
                g_sim_elements.push_back(e);
            }
            // Search button
            {
                BrowserElement e;
                e.id = page_prefix + "search_btn";
                e.tag = "button";
                e.type = BrowserElementType::button;
                e.text = "Google Search";
                e.bounds = {1010, 90, 120, 44};
                e.clickable = true;
                e.parent_id = page_prefix + "header";
                g_sim_elements.push_back(e);
            }
            // Result links
            for (int i = 1; i <= 8; i++) {
                BrowserElement e;
                e.id = page_prefix + "result_link_" + std::to_string(i);
                e.tag = "a";
                e.type = BrowserElementType::link;
                e.text = "Result " + std::to_string(i);
                e.href = "https://example" + std::to_string(i) + ".com";
                e.bounds = {320, 300 + (i - 1) * 120, 600, 20};
                e.clickable = true;
                e.is_link = true;
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
        }

        if (p.page_type == "product") {
            // Add to cart button
            {
                BrowserElement e;
                e.id = page_prefix + "add_to_cart";
                e.tag = "button";
                e.type = BrowserElementType::button;
                e.text = "Add to Cart";
                e.bounds = {320, 500, 200, 50};
                e.clickable = true;
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
            // Buy now button
            {
                BrowserElement e;
                e.id = page_prefix + "buy_now";
                e.tag = "button";
                e.type = BrowserElementType::button;
                e.text = "Buy Now";
                e.bounds = {530, 500, 200, 50};
                e.clickable = true;
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
            // Price element
            {
                BrowserElement e;
                e.id = page_prefix + "price";
                e.tag = "span";
                e.type = BrowserElementType::price;
                e.text = "$1,799.00";
                e.bounds = {320, 450, 200, 30};
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
            // Rating
            {
                BrowserElement e;
                e.id = page_prefix + "rating";
                e.tag = "span";
                e.type = BrowserElementType::rating;
                e.text = "4.7 out of 5 stars (2,341 ratings)";
                e.bounds = {320, 480, 300, 20};
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
        }

        if (p.page_type == "login") {
            // Email input
            {
                BrowserElement e;
                e.id = page_prefix + "email_input";
                e.tag = "input";
                e.type = BrowserElementType::email;
                e.placeholder = "Enter your email";
                e.name = "email";
                e.bounds = {710, 350, 500, 44};
                e.is_input = true;
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
            // Password input
            {
                BrowserElement e;
                e.id = page_prefix + "password_input";
                e.tag = "input";
                e.type = BrowserElementType::password;
                e.placeholder = "Enter your password";
                e.name = "password";
                e.bounds = {710, 410, 500, 44};
                e.is_input = true;
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
            // Remember me checkbox
            {
                BrowserElement e;
                e.id = page_prefix + "remember_me";
                e.tag = "input";
                e.type = BrowserElementType::checkbox;
                e.text = "Remember me";
                e.name = "remember";
                e.bounds = {710, 470, 20, 20};
                e.is_input = true;
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
            // Sign in button
            {
                BrowserElement e;
                e.id = page_prefix + "signin_btn";
                e.tag = "button";
                e.type = BrowserElementType::submit;
                e.text = "Sign In";
                e.bounds = {710, 510, 500, 50};
                e.clickable = true;
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
            // Social login buttons
            const char* social[] = {"Google", "GitHub", "Microsoft"};
            for (int i = 0; i < 3; i++) {
                BrowserElement e;
                e.id = page_prefix + "social_" + std::to_string(i);
                e.tag = "button";
                e.type = BrowserElementType::button;
                e.text = social[i];
                e.bounds = {710 + i * 170, 600, 160, 44};
                e.clickable = true;
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
        }

        if (p.page_type == "social") {
            // Compose post input
            {
                BrowserElement e;
                e.id = page_prefix + "compose";
                e.tag = "textarea";
                e.type = BrowserElementType::textarea;
                e.placeholder = "What's happening?";
                e.bounds = {320, 140, 1280, 80};
                e.is_input = true;
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
            // Post buttons
            {
                BrowserElement e;
                e.id = page_prefix + "post_btn";
                e.tag = "button";
                e.type = BrowserElementType::button;
                e.text = "Post";
                e.bounds = {1400, 150, 100, 44};
                e.clickable = true;
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
            // Social posts as elements
            for (int i = 1; i <= 7; i++) {
                BrowserElement e;
                e.id = page_prefix + "post_" + std::to_string(i);
                e.tag = "article";
                e.type = BrowserElementType::social_post;
                e.text = "Post " + std::to_string(i);
                e.bounds = {320, 250 + (i - 1) * 200, 1280, 180};
                e.is_container = true;
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);

                // Like button
                BrowserElement like;
                like.id = page_prefix + "like_" + std::to_string(i);
                like.tag = "button";
                like.type = BrowserElementType::button;
                like.text = "Like";
                like.bounds = {340, 390 + (i - 1) * 200, 80, 30};
                like.clickable = true;
                like.parent_id = e.id;
                g_sim_elements.push_back(like);

                // Comment button
                BrowserElement cmt;
                cmt.id = page_prefix + "comment_" + std::to_string(i);
                cmt.tag = "button";
                cmt.type = BrowserElementType::button;
                cmt.text = "Comment";
                cmt.bounds = {430, 390 + (i - 1) * 200, 100, 30};
                cmt.clickable = true;
                cmt.parent_id = e.id;
                g_sim_elements.push_back(cmt);

                // Share button
                BrowserElement shr;
                shr.id = page_prefix + "share_" + std::to_string(i);
                shr.tag = "button";
                shr.type = BrowserElementType::button;
                shr.text = "Share";
                shr.bounds = {540, 390 + (i - 1) * 200, 80, 30};
                shr.clickable = true;
                shr.parent_id = e.id;
                g_sim_elements.push_back(shr);
            }
        }

        if (p.page_type == "table") {
            // Table elements
            for (int i = 1; i <= 4; i++) {
                BrowserElement e;
                e.id = page_prefix + "table_" + std::to_string(i);
                e.tag = "table";
                e.type = BrowserElementType::table;
                e.text = "Table " + std::to_string(i);
                e.bounds = {320, 300 + (i - 1) * 400, 1280, 350};
                e.is_container = true;
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
            // Download button
            {
                BrowserElement e;
                e.id = page_prefix + "download_btn";
                e.tag = "button";
                e.type = BrowserElementType::button;
                e.text = "Download full report (PDF)";
                e.bounds = {320, 1900, 300, 44};
                e.clickable = true;
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
        }

        if (p.page_type == "article") {
            // Edit link
            {
                BrowserElement e;
                e.id = page_prefix + "edit_link";
                e.tag = "a";
                e.type = BrowserElementType::link;
                e.text = "Edit";
                e.href = "/wiki/Artificial_intelligence?action=edit";
                e.bounds = {1500, 140, 60, 30};
                e.clickable = true;
                e.is_link = true;
                e.parent_id = page_prefix + "header";
                g_sim_elements.push_back(e);
            }
            // Categories
            {
                BrowserElement e;
                e.id = page_prefix + "categories";
                e.tag = "div";
                e.type = BrowserElementType::div;
                e.text = "Categories: Artificial intelligence | Computer science | Emerging technologies";
                e.bounds = {320, p.page_height - 200, 1280, 40};
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
        }

        if (p.page_type == "news") {
            // Share button
            {
                BrowserElement e;
                e.id = page_prefix + "share_btn";
                e.tag = "button";
                e.type = BrowserElementType::button;
                e.text = "Share this article";
                e.bounds = {320, p.page_height - 200, 200, 44};
                e.clickable = true;
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
            // Comments section
            {
                BrowserElement e;
                e.id = page_prefix + "comments";
                e.tag = "section";
                e.type = BrowserElementType::section;
                e.text = "Comments (1,247)";
                e.bounds = {320, p.page_height - 150, 1280, 50};
                e.is_container = true;
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
        }

        if (p.page_type == "documentation") {
            // Code blocks
            for (int i = 0; i < 5; i++) {
                BrowserElement e;
                e.id = page_prefix + "code_" + std::to_string(i);
                e.tag = "pre";
                e.type = BrowserElementType::pre;
                e.text = "function example" + std::to_string(i) + "() { /* code */ }";
                e.bounds = {320, 400 + i * 600, 1280, 80};
                e.parent_id = page_prefix + "content";
                g_sim_elements.push_back(e);
            }
            // Sidebar
            {
                BrowserElement e;
                e.id = page_prefix + "sidebar";
                e.tag = "aside";
                e.type = BrowserElementType::aside;
                e.text = "In this article";
                e.bounds = {0, 140, 300, 5000};
                e.is_container = true;
                e.parent_id = "";
                g_sim_elements.push_back(e);
            }
        }
    }

    // Set up tabs
    TabInfo tab1;
    tab1.id = "tab_0";
    tab1.url = g_sim_pages[0].url;
    tab1.title = g_sim_pages[0].title;
    tab1.active = true;
    g_sim_tabs.push_back(tab1);

    TabInfo tab2;
    tab2.id = "tab_1";
    tab2.url = "about:blank";
    tab2.title = "New Tab";
    tab2.active = false;
    g_sim_tabs.push_back(tab2);

    g_sim_history.push_back(g_sim_pages[0].url);
}

// Helper: get current page
static PageInfo& current_page() {
    return g_sim_pages[g_sim_current_page];
}

// Helper: get elements for current page
static std::vector<BrowserElement> current_page_elements() {
    std::vector<BrowserElement> result;
    std::string prefix = "page" + std::to_string(g_sim_current_page) + "_";
    for (const auto& e : g_sim_elements) {
        if (e.id.find(prefix) == 0) {
            result.push_back(e);
        }
    }
    return result;
}

// Helper: get element by id from simulation
static BrowserElement sim_get_element(const std::string& id) {
    for (const auto& e : g_sim_elements) {
        if (e.id == id) return e;
    }
    return BrowserElement{};
}

// ===== Browser Info =====
BrowserInfo get_browser_info() {
    BrowserInfo info;
    if (g_simulation_mode) {
        info.name = "SimulatedBrowser";
        info.version = "1.0.0";
        info.user_agent = "Mozilla/5.0 (Simulated) BrowserTool/1.0";
        info.platform = platform_to_string(get_current_platform());
        info.headless = false;
        info.tab_count = static_cast<int>(g_sim_tabs.size());
    } else {
#if defined(_WIN32)
        info.name = "Chrome";
        info.version = "120.0";
        info.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0";
        info.platform = "windows";
#else
        info.name = "Unknown";
        info.version = "0.0";
        info.user_agent = "Unknown";
        info.platform = platform_to_string(get_current_platform());
#endif
        info.headless = false;
        info.tab_count = 1;
    }
    return info;
}

// ===== Navigation API =====
bool navigate(const std::string& url) {
    if (g_simulation_mode) {
        if (url.empty()) return false;
        // Find page by exact URL match first
        for (size_t i = 0; i < g_sim_pages.size(); i++) {
            if (g_sim_pages[i].url == url) {
                g_sim_current_page = static_cast<int>(i);
                g_sim_scroll_x = 0;
                g_sim_scroll_y = 0;
                g_sim_history.push_back(g_sim_pages[i].url);
                if (!g_sim_tabs.empty()) {
                    g_sim_tabs[g_sim_active_tab].url = g_sim_pages[i].url;
                    g_sim_tabs[g_sim_active_tab].title = g_sim_pages[i].title;
                }
                return true;
            }
        }
        // Try matching by domain
        for (size_t i = 0; i < g_sim_pages.size(); i++) {
            if (contains_ci(g_sim_pages[i].domain, url) || contains_ci(url, g_sim_pages[i].domain)) {
                g_sim_current_page = static_cast<int>(i);
                g_sim_scroll_x = 0;
                g_sim_scroll_y = 0;
                g_sim_history.push_back(g_sim_pages[i].url);
                if (!g_sim_tabs.empty()) {
                    g_sim_tabs[g_sim_active_tab].url = g_sim_pages[i].url;
                    g_sim_tabs[g_sim_active_tab].title = g_sim_pages[i].title;
                }
                return true;
            }
        }
        // Try partial match on path
        for (size_t i = 0; i < g_sim_pages.size(); i++) {
            if (contains_ci(g_sim_pages[i].path, url)) {
                g_sim_current_page = static_cast<int>(i);
                g_sim_scroll_x = 0;
                g_sim_scroll_y = 0;
                g_sim_history.push_back(g_sim_pages[i].url);
                return true;
            }
        }
        return false;
    }
#if defined(_WIN32)
    // Actually open the URL in the default browser
    std::wstring wUrl(url.begin(), url.end());
    HINSTANCE hInst = ShellExecuteW(nullptr, L"open", wUrl.c_str(),
                                    nullptr, nullptr, SW_SHOWNORMAL);
    if ((INT_PTR)hInst <= 32) {
        // Fallback: try cmd /c start
        std::wstring cmd = L"cmd /c start " + wUrl;
        ShellExecuteW(nullptr, L"open", L"cmd.exe",
                      (L"/c start " + wUrl).c_str(), nullptr, SW_HIDE);
    }
    // Give browser time to open and load
    Sleep(2500);
    return true;
#else
    return false;
#endif
}

bool go_back() {
    if (g_simulation_mode) {
        if (g_sim_history.size() > 1) {
            g_sim_history.pop_back();
            std::string prev_url = g_sim_history.back();
            for (size_t i = 0; i < g_sim_pages.size(); i++) {
                if (g_sim_pages[i].url == prev_url) {
                    g_sim_current_page = static_cast<int>(i);
                    g_sim_scroll_x = 0;
                    g_sim_scroll_y = 0;
                    return true;
                }
            }
        }
        return false;
    }
    return false;
}

bool go_forward() {
    if (g_simulation_mode) {
        // Simplified: just return true
        return true;
    }
    return false;
}

bool refresh() {
    if (g_simulation_mode) {
        g_sim_scroll_x = 0;
        g_sim_scroll_y = 0;
        return true;
    }
    return false;
}

bool stop_loading() {
    if (g_simulation_mode) {
        current_page().loading = false;
        return true;
    }
    return false;
}

std::string get_current_url() {
    if (g_simulation_mode) return current_page().url;
#if defined(_WIN32)
    HWND fg = GetForegroundWindow();
    if (fg) {
        wchar_t title[512] = {};
        GetWindowTextW(fg, title, 512);
        if (title[0]) {
            std::wstring wTitle(title);
            return std::string(wTitle.begin(), wTitle.end());
        }
    }
    return "[No browser window detected]";
#else
    return "";
#endif
}

std::string get_current_title() {
    if (g_simulation_mode) return current_page().title;
    return "";
}

bool wait_for_page_load(int timeout_ms) {
    if (g_simulation_mode) return !current_page().loading;
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    return true;
}

// ===== Tab Management =====
std::string new_tab(const std::string& url) {
    if (g_simulation_mode) {
        TabInfo tab;
        tab.id = "tab_" + std::to_string(g_sim_tabs.size());
        tab.url = url.empty() ? "about:blank" : url;
        tab.title = url.empty() ? "New Tab" : "Loading...";
        tab.active = false;
        for (auto& t : g_sim_tabs) t.active = false;
        tab.active = true;
        g_sim_active_tab = static_cast<int>(g_sim_tabs.size());
        g_sim_tabs.push_back(tab);
        return tab.id;
    }
    return "";
}

bool close_tab(const std::string& tab_id) {
    if (g_simulation_mode) {
        for (size_t i = 0; i < g_sim_tabs.size(); i++) {
            if (g_sim_tabs[i].id == tab_id) {
                g_sim_tabs.erase(g_sim_tabs.begin() + i);
                if (g_sim_active_tab >= static_cast<int>(g_sim_tabs.size())) {
                    g_sim_active_tab = static_cast<int>(g_sim_tabs.size()) - 1;
                }
                if (!g_sim_tabs.empty()) g_sim_tabs[g_sim_active_tab].active = true;
                return true;
            }
        }
        return false;
    }
    return false;
}

bool switch_tab(const std::string& tab_id) {
    if (g_simulation_mode) {
        for (size_t i = 0; i < g_sim_tabs.size(); i++) {
            if (g_sim_tabs[i].id == tab_id) {
                for (auto& t : g_sim_tabs) t.active = false;
                g_sim_tabs[i].active = true;
                g_sim_active_tab = static_cast<int>(i);
                return true;
            }
        }
        return false;
    }
    return false;
}

std::vector<TabInfo> list_tabs() {
    if (g_simulation_mode) return g_sim_tabs;
    return {};
}

std::string get_active_tab_id() {
    if (g_simulation_mode && !g_sim_tabs.empty()) {
        return g_sim_tabs[g_sim_active_tab].id;
    }
    return "";
}

// ===== Page Content API =====
PageInfo get_page_info() {
    if (g_simulation_mode) {
        PageInfo p = current_page();
        p.scroll_x = g_sim_scroll_x;
        p.scroll_y = g_sim_scroll_y;
        return p;
    }
    return PageInfo{};
}

// Forward declarations for page content extraction
static std::string get_page_content_uia();
static void collect_text_from_uia(IUIAutomation* pAutomation, IUIAutomationElement* pElement,
                                   std::string& result, int depth);
static std::string get_page_content_clipboard();

std::string get_page_content() {
    if (g_simulation_mode) return current_page().content_text;
#if defined(_WIN32)
    // Method 1: UI Automation — walk the browser's element tree to collect text
    // Chrome and Edge expose their DOM through UIA as Text and Document elements
    std::string uia_content = get_page_content_uia();
    if (!uia_content.empty()) return uia_content;

    // Method 2: Clipboard fallback — Ctrl+A, Ctrl+C, read clipboard
    std::string clip_content = get_page_content_clipboard();
    if (!clip_content.empty()) return clip_content;

    // Method 3: Just return the window title as last resort
    HWND fg = GetForegroundWindow();
    if (fg) {
        wchar_t title[512] = {};
        GetWindowTextW(fg, title, 512);
        if (title[0]) {
            std::wstring wTitle(title);
            return std::string(wTitle.begin(), wTitle.end()) +
                "\n[Could not extract page content. Try screen_capture for visual analysis.]";
        }
    }
    return "[No browser window detected]";
#else
    return "";
#endif
}

// UI Automation: walk browser element tree to collect all text content
static std::string get_page_content_uia() {
#if defined(_WIN32)
    std::string result;

    // Find the foreground window (should be the browser)
    HWND fg = GetForegroundWindow();
    if (!fg) return result;

    // Initialize COM
    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr) && hr != RPC_E_CHANGED_MODE) return result;
    bool need_co_uninit = (hr != RPC_E_CHANGED_MODE);

    // Create UI Automation instance
    IUIAutomation* pAutomation = nullptr;
    hr = CoCreateInstance(CLSID_CUIAutomation, nullptr, CLSCTX_INPROC_SERVER,
                          IID_PPV_ARGS(&pAutomation));
    if (FAILED(hr) || !pAutomation) {
        if (need_co_uninit) CoUninitialize();
        return result;
    }

    // Get element from the foreground window
    IUIAutomationElement* pRoot = nullptr;
    hr = pAutomation->ElementFromHandle(fg, &pRoot);
    if (FAILED(hr) || !pRoot) {
        pAutomation->Release();
        if (need_co_uninit) CoUninitialize();
        return result;
    }

    // Collect text from the element tree
    // We look for Text and Document control types, and also get Name property
    collect_text_from_uia(pAutomation, pRoot, result, 0);

    pRoot->Release();
    pAutomation->Release();
    if (need_co_uninit) CoUninitialize();

    // Trim and return
    if (result.size() > 50000) result = result.substr(0, 50000) + "\n[...truncated...]";
    return result;
#else
    return "";
#endif
}

// Recursively walk UIA tree and collect text from elements
static void collect_text_from_uia(IUIAutomation* pAutomation, IUIAutomationElement* pElement,
                                   std::string& result, int depth) {
#if defined(_WIN32)
    if (!pElement || depth > 15) return;

    // Get element name (often contains visible text)
    BSTR name = nullptr;
    if (SUCCEEDED(pElement->get_CurrentName(&name)) && name) {
        std::wstring wName(name);
        if (!wName.empty() && wName.size() < 2000) {
            std::string sName(wName.begin(), wName.end());
            // Skip generic/system names
            if (sName != "Desktop" && sName != "Taskbar" &&
                sName.find("Microsoft Edge") == std::string::npos &&
                sName.find("Google Chrome") == std::string::npos) {
                if (!result.empty()) result += "\n";
                result += sName;
            }
        }
        SysFreeString(name);
    }

    // Try to get Value property (useful for text fields, address bar)
    VARIANT varValue;
    VariantInit(&varValue);
    if (SUCCEEDED(pElement->GetCurrentPropertyValue(UIA_ValueValuePropertyId, &varValue))) {
        if (varValue.vt == VT_BSTR && varValue.bstrVal) {
            std::wstring wValue(varValue.bstrVal);
            if (!wValue.empty() && wValue.size() < 5000) {
                std::string sValue(wValue.begin(), wValue.end());
                if (sValue.find("http") == 0 || sValue.find("https") == 0) {
                    // This is likely the URL
                    result = "[URL: " + sValue + "]\n" + result;
                }
            }
        }
        VariantClear(&varValue);
    }

    // Try TextPattern for document elements (gives full page text in browsers)
    IUIAutomationTextPattern* pTextPattern = nullptr;
    if (SUCCEEDED(pElement->GetCurrentPattern(UIA_TextPatternId, (IUnknown**)&pTextPattern)) && pTextPattern) {
        IUIAutomationTextRange* pRange = nullptr;
        if (SUCCEEDED(pTextPattern->get_DocumentRange(&pRange)) && pRange) {
            BSTR text = nullptr;
            if (SUCCEEDED(pRange->GetText(-1, &text)) && text) {
                std::wstring wText(text);
                if (!wText.empty()) {
                    std::string sText(wText.begin(), wText.end());
                    if (sText.size() > 50) {
                        result += "\n" + sText;
                    }
                }
                SysFreeString(text);
            }
            pRange->Release();
        }
        pTextPattern->Release();
    }

    // Walk children using control view walker
    IUIAutomationTreeWalker* pWalker = nullptr;
    pAutomation->get_ControlViewWalker(&pWalker);
    if (!pWalker) return;

    IUIAutomationElement* pChild = nullptr;
    pWalker->GetFirstChildElement(pElement, &pChild);
    while (pChild) {
        collect_text_from_uia(pAutomation, pChild, result, depth + 1);
        IUIAutomationElement* pNext = nullptr;
        pWalker->GetNextSiblingElement(pChild, &pNext);
        pChild->Release();
        pChild = pNext;
    }
    pWalker->Release();
#endif
}

// Clipboard fallback: Ctrl+A, Ctrl+C, read clipboard
static std::string get_page_content_clipboard() {
#if defined(_WIN32)
    // Clear clipboard first
    OpenClipboard(nullptr);
    EmptyClipboard();
    CloseClipboard();

    // Small delay to ensure clipboard is clear
    Sleep(50);

    // Send Ctrl+A to select all text on the page
    keybd_event(VK_CONTROL, 0, 0, 0);
    keybd_event('A', 0, 0, 0);
    keybd_event('A', 0, KEYEVENTF_KEYUP, 0);
    keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0);
    Sleep(200);

    // Send Ctrl+C to copy
    keybd_event(VK_CONTROL, 0, 0, 0);
    keybd_event('C', 0, 0, 0);
    keybd_event('C', 0, KEYEVENTF_KEYUP, 0);
    keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0);
    Sleep(300);

    // Read clipboard text
    std::string result;
    if (OpenClipboard(nullptr)) {
        HANDLE hData = GetClipboardData(CF_UNICODETEXT);
        if (hData) {
            wchar_t* pszText = static_cast<wchar_t*>(GlobalLock(hData));
            if (pszText) {
                std::wstring wText(pszText);
                result = std::string(wText.begin(), wText.end());
                GlobalUnlock(hData);
            }
        }
        CloseClipboard();
    }

    // Deselect by pressing Escape
    keybd_event(VK_ESCAPE, 0, 0, 0);
    keybd_event(VK_ESCAPE, 0, KEYEVENTF_KEYUP, 0);

    // Trim large content
    if (result.size() > 50000) result = result.substr(0, 50000) + "\n[...truncated...]";
    return result;
#else
    return "";
#endif
}

std::string get_page_html() {
    if (g_simulation_mode) return "<html><body>" + current_page().content_text + "</body></html>";
    return "";
}

std::string get_page_title() {
    if (g_simulation_mode) return current_page().title;
#if defined(_WIN32)
    HWND fg = GetForegroundWindow();
    if (fg) {
        wchar_t title[512] = {};
        GetWindowTextW(fg, title, 512);
        if (title[0]) {
            std::wstring wTitle(title);
            return std::string(wTitle.begin(), wTitle.end());
        }
    }
    return "[No browser window detected]";
#else
    return "";
#endif
}

std::string get_page_text_by_element(const std::string& element_id) {
    auto e = sim_get_element(element_id);
    return e.text;
}

std::string get_meta_description() {
    if (g_simulation_mode) return current_page().meta_description;
    return "";
}

std::string get_meta_keywords() {
    if (g_simulation_mode) return current_page().meta_keywords;
    return "";
}

// ===== Element Query API =====
std::vector<BrowserElement> get_all_elements() {
    if (g_simulation_mode) return current_page_elements();
    return {};
}

std::vector<BrowserElement> get_elements_by_type(BrowserElementType type) {
    std::vector<BrowserElement> result;
    auto all = get_all_elements();
    for (const auto& e : all) {
        if (e.type == type) result.push_back(e);
    }
    return result;
}

std::vector<BrowserElement> get_elements_by_tag(const std::string& tag) {
    std::vector<BrowserElement> result;
    auto all = get_all_elements();
    for (const auto& e : all) {
        if (e.tag == tag) result.push_back(e);
    }
    return result;
}

BrowserElement get_element_by_id(const std::string& id) {
    if (g_simulation_mode) return sim_get_element(id);
    return BrowserElement{};
}

std::vector<BrowserElement> get_links() {
    return get_elements_by_type(BrowserElementType::link);
}

std::vector<BrowserElement> get_images() {
    return get_elements_by_type(BrowserElementType::image);
}

std::vector<BrowserElement> get_buttons() {
    std::vector<BrowserElement> result;
    auto all = get_all_elements();
    for (const auto& e : all) {
        if (e.type == BrowserElementType::button || e.type == BrowserElementType::submit) {
            result.push_back(e);
        }
    }
    return result;
}

std::vector<BrowserElement> get_forms() {
    return get_elements_by_type(BrowserElementType::form);
}

std::vector<BrowserElement> get_headings() {
    std::vector<BrowserElement> result;
    auto all = get_all_elements();
    for (const auto& e : all) {
        if (e.type == BrowserElementType::heading1 || e.type == BrowserElementType::heading2 ||
            e.type == BrowserElementType::heading3 || e.type == BrowserElementType::heading4 ||
            e.type == BrowserElementType::heading5 || e.type == BrowserElementType::heading6) {
            result.push_back(e);
        }
    }
    return result;
}

std::vector<BrowserElement> get_paragraphs() {
    return get_elements_by_type(BrowserElementType::paragraph);
}

std::vector<BrowserElement> get_inputs() {
    std::vector<BrowserElement> result;
    auto all = get_all_elements();
    for (const auto& e : all) {
        if (e.is_input) result.push_back(e);
    }
    return result;
}

std::vector<BrowserElement> get_tables() {
    return get_elements_by_type(BrowserElementType::table);
}

std::vector<BrowserElement> get_navigation() {
    return get_elements_by_type(BrowserElementType::nav);
}

std::vector<BrowserElement> get_element_children(const std::string& element_id) {
    std::vector<BrowserElement> result;
    auto all = get_all_elements();
    for (const auto& e : all) {
        if (e.parent_id == element_id) result.push_back(e);
    }
    return result;
}

BrowserElement get_element_parent(const std::string& element_id) {
    auto e = sim_get_element(element_id);
    if (e.parent_id.empty()) return BrowserElement{};
    return sim_get_element(e.parent_id);
}

// ===== Content Search API =====
std::vector<ContentSearchResult> search_content(const std::string& query, int max_results) {
    std::vector<ContentSearchResult> results;
    if (query.empty()) return results;
    if (g_simulation_mode) {
        std::string content = current_page().content_text;
        auto elements = current_page_elements();

        // Search in content text
        std::string lower_content = content;
        std::string lower_query = query;
        std::transform(lower_content.begin(), lower_content.end(), lower_content.begin(),
                       [](unsigned char c) { return std::tolower(c); });
        std::transform(lower_query.begin(), lower_query.end(), lower_query.begin(),
                       [](unsigned char c) { return std::tolower(c); });

        size_t pos = 0;
        while ((pos = lower_content.find(lower_query, pos)) != std::string::npos) {
            ContentSearchResult r;
            r.text = content.substr(pos, query.size());
            r.position = static_cast<int>(pos);
            r.match_type = "exact";

            // Calculate line number
            int line = 1;
            for (size_t i = 0; i < pos && i < content.size(); i++) {
                if (content[i] == '\n') line++;
            }
            r.line_number = line;

            // Context
            int ctx_start = std::max(0, static_cast<int>(pos) - 100);
            int ctx_end = std::min(static_cast<int>(content.size()), static_cast<int>(pos + query.size()) + 100);
            r.context_before = content.substr(ctx_start, pos - ctx_start);
            r.context_after = content.substr(pos + query.size(), ctx_end - (pos + query.size()));

            // Find element containing this position
            for (const auto& e : elements) {
                if (contains_ci(e.text, query)) {
                    r.element_id = e.id;
                    r.element_type = e.type;
                    r.bounds = e.bounds;
                    break;
                }
            }

            r.score = 1.0;
            results.push_back(r);
            pos += query.size();
            if (static_cast<int>(results.size()) >= max_results) break;
        }

        // If no exact matches, try fuzzy matching on elements
        if (results.empty()) {
            for (const auto& e : elements) {
                double score = fuzzy_match(e.text, query);
                if (score > 0.5) {
                    ContentSearchResult r;
                    r.text = e.text;
                    r.element_id = e.id;
                    r.element_type = e.type;
                    r.bounds = e.bounds;
                    r.score = score;
                    r.match_type = "fuzzy";
                    r.context_before = "";
                    r.context_after = e.text;
                    results.push_back(r);
                    if (static_cast<int>(results.size()) >= max_results) break;
                }
            }
        }
    }
    return results;
}

std::vector<ContentSearchResult> search_content_in_element(const std::string& element_id, const std::string& query) {
    if (query.empty()) return {};
    auto e = sim_get_element(element_id);
    if (e.id.empty()) return {};
    if (!contains_ci(e.text, query)) return {};

    ContentSearchResult r;
    r.text = e.text;
    r.element_id = e.id;
    r.element_type = e.type;
    r.bounds = e.bounds;
    r.score = 1.0;
    r.match_type = "exact";
    return {r};
}

ContentSearchResult find_first_text(const std::string& text) {
    auto results = search_content(text, 1);
    if (results.empty()) return ContentSearchResult{};
    return results[0];
}

std::vector<ContentSearchResult> find_all_text(const std::string& text) {
    return search_content(text, 1000);
}

BrowserElement find_element_by_text(const std::string& text) {
    auto all = get_all_elements();
    for (const auto& e : all) {
        if (contains_ci(e.text, text)) return e;
    }
    // Try fuzzy
    BrowserElement best;
    double best_score = 0;
    for (const auto& e : all) {
        double s = fuzzy_match(e.text, text);
        if (s > best_score) { best = e; best_score = s; }
    }
    if (best_score > 0.5) return best;
    return BrowserElement{};
}

std::vector<BrowserElement> find_elements_by_text(const std::string& text) {
    std::vector<BrowserElement> result;
    auto all = get_all_elements();
    for (const auto& e : all) {
        if (contains_ci(e.text, text)) result.push_back(e);
    }
    return result;
}

BrowserElement find_paragraph_by_text(const std::string& text) {
    auto paras = get_paragraphs();
    for (const auto& e : paras) {
        if (contains_ci(e.text, text)) return e;
    }
    return BrowserElement{};
}

BrowserElement find_heading_by_text(const std::string& text) {
    auto headings = get_headings();
    for (const auto& e : headings) {
        if (contains_ci(e.text, text)) return e;
    }
    return BrowserElement{};
}

BrowserElement find_link_by_text(const std::string& text) {
    auto links = get_links();
    for (const auto& e : links) {
        if (contains_ci(e.text, text)) return e;
    }
    return BrowserElement{};
}

BrowserElement find_link_by_href(const std::string& href_partial) {
    auto links = get_links();
    for (const auto& e : links) {
        if (contains_ci(e.href, href_partial)) return e;
    }
    return BrowserElement{};
}

BrowserElement find_button_by_text(const std::string& text) {
    auto buttons = get_buttons();
    for (const auto& e : buttons) {
        if (contains_ci(e.text, text)) return e;
    }
    return BrowserElement{};
}

// ===== Content Analysis API =====
std::string explain_content(const std::string& query) {
    if (g_simulation_mode) {
        auto results = search_content(query, 5);
        std::ostringstream ss;
        ss << "{\"query\":\"" << query << "\",";
        ss << "\"matches\":" << results.size() << ",";
        ss << "\"explanation\":\"Found " << results.size() << " matches for '" << query << "'. ";
        if (!results.empty()) {
            ss << "The first match is at position " << results[0].position;
            ss << " on line " << results[0].line_number;
            if (!results[0].element_id.empty()) {
                ss << " in element " << results[0].element_id;
            }
            ss << ". Context: ..." << results[0].context_before << "[" << results[0].text << "]" << results[0].context_after << "...";
        }
        ss << "\",";
        ss << "\"results\":[";
        for (size_t i = 0; i < results.size() && i < 3; i++) {
            if (i > 0) ss << ",";
            ss << results[i].to_json();
        }
        ss << "]}";
        return ss.str();
    }
    return "{\"query\":\"" + query + "\",\"matches\":0,\"explanation\":\"No content available\"}";
}

std::string summarize_page(int max_sentences) {
    if (g_simulation_mode) {
        std::string content = current_page().content_text;
        // Simple: take first N sentences
        std::vector<std::string> sentences;
        std::string current;
        for (char c : content) {
            current += c;
            if (c == '.' || c == '!' || c == '?') {
                sentences.push_back(current);
                current.clear();
            }
        }
        if (!current.empty()) sentences.push_back(current);

        std::ostringstream ss;
        ss << "{\"title\":\"" << current_page().title << "\",";
        ss << "\"url\":\"" << current_page().url << "\",";
        ss << "\"summary\":\"";
        for (int i = 0; i < std::min(max_sentences, static_cast<int>(sentences.size())); i++) {
            if (i > 0) ss << " ";
            ss << sentences[i];
        }
        ss << "\",\"total_sentences\":" << sentences.size() << "}";
        return ss.str();
    }
    return "{}";
}

std::string get_section_by_heading(const std::string& heading_text) {
    if (g_simulation_mode) {
        auto headings = get_headings();
        std::string content = current_page().content_text;

        // Find the heading in content
        size_t heading_pos = std::string::npos;
        for (const auto& h : headings) {
            if (contains_ci(h.text, heading_text)) {
                heading_pos = content.find(h.text);
                break;
            }
        }

        if (heading_pos == std::string::npos) return "{}";

        // Find next heading
        size_t next_heading = content.size();
        for (const auto& h : headings) {
            size_t pos = content.find(h.text, heading_pos + 1);
            if (pos != std::string::npos && pos < next_heading) {
                next_heading = pos;
            }
        }

        std::string section = content.substr(heading_pos, next_heading - heading_pos);

        std::ostringstream ss;
        ss << "{\"heading\":\"" << heading_text << "\",";
        ss << "\"content\":\"" << section << "\",";
        ss << "\"length\":" << section.size() << "}";
        return ss.str();
    }
    return "{}";
}

std::vector<std::string> get_all_headings() {
    std::vector<std::string> result;
    auto headings = get_headings();
    for (const auto& h : headings) {
        result.push_back(h.text);
    }
    return result;
}

std::vector<std::string> get_all_paragraphs() {
    std::vector<std::string> result;
    auto paras = get_paragraphs();
    for (const auto& p : paras) {
        result.push_back(p.text);
    }
    return result;
}

std::string get_context_around_text(const std::string& text, int chars_before, int chars_after) {
    if (g_simulation_mode) {
        std::string content = current_page().content_text;
        size_t pos = content.find(text);
        if (pos == std::string::npos) {
            // Case insensitive search
            std::string lower_content = content;
            std::string lower_text = text;
            std::transform(lower_content.begin(), lower_content.end(), lower_content.begin(),
                           [](unsigned char c) { return std::tolower(c); });
            std::transform(lower_text.begin(), lower_text.end(), lower_text.begin(),
                           [](unsigned char c) { return std::tolower(c); });
            pos = lower_content.find(lower_text);
        }
        if (pos == std::string::npos) return "";

        int start = std::max(0, static_cast<int>(pos) - chars_before);
        int end = std::min(static_cast<int>(content.size()), static_cast<int>(pos + text.size()) + chars_after);
        return content.substr(start, end - start);
    }
    return "";
}

std::vector<ContentSearchResult> search_with_context(const std::string& query, int context_chars) {
    auto results = search_content(query, 50);
    for (auto& r : results) {
        int ctx_start = std::max(0, r.position - context_chars);
        int ctx_end = std::min(static_cast<int>(current_page().content_text.size()),
                               r.position + static_cast<int>(query.size()) + context_chars);
        r.context_before = current_page().content_text.substr(ctx_start, r.position - ctx_start);
        r.context_after = current_page().content_text.substr(r.position + query.size(),
                                                              ctx_end - (r.position + static_cast<int>(query.size())));
    }
    return results;
}

std::string get_page_summary() {
    return summarize_page(3);
}

// ===== Scroll API =====
bool scroll_down(int pixels) {
    if (g_simulation_mode) {
        auto& p = current_page();
        g_sim_scroll_y = std::min(g_sim_scroll_y + pixels, p.scroll_max_y);
        return true;
    }
    return false;
}

bool scroll_up(int pixels) {
    if (g_simulation_mode) {
        g_sim_scroll_y = std::max(0, g_sim_scroll_y - pixels);
        return true;
    }
    return false;
}

bool scroll_to(int x, int y) {
    if (g_simulation_mode) {
        auto& p = current_page();
        g_sim_scroll_x = std::max(0, std::min(x, p.scroll_max_x));
        g_sim_scroll_y = std::max(0, std::min(y, p.scroll_max_y));
        return true;
    }
    return false;
}

bool scroll_to_element(const std::string& element_id) {
    auto e = sim_get_element(element_id);
    if (e.id.empty()) return false;
    return scroll_to(0, e.bounds.y - 100);
}

bool scroll_to_top() {
    if (g_simulation_mode) { g_sim_scroll_y = 0; return true; }
    return false;
}

bool scroll_to_bottom() {
    if (g_simulation_mode) { g_sim_scroll_y = current_page().scroll_max_y; return true; }
    return false;
}

int get_scroll_x() { return g_sim_scroll_x; }
int get_scroll_y() { return g_sim_scroll_y; }
int get_scroll_max_x() { return current_page().scroll_max_x; }
int get_scroll_max_y() { return current_page().scroll_max_y; }

// ===== Screenshot API =====
ScreenshotInfo take_screenshot(bool full_page) {
    ScreenshotInfo info;
    if (g_simulation_mode) {
        info.width = full_page ? current_page().page_width : current_page().viewport_width;
        info.height = full_page ? current_page().page_height : current_page().viewport_height;
        info.format = "png";
        info.full_page = full_page;
        info.base64_data = "iVBORw0KGgoAAAANSUhEUgAA"; // Placeholder base64
        info.filepath = "";
    }
    return info;
}

ScreenshotInfo screenshot_element(const std::string& element_id) {
    ScreenshotInfo info;
    auto e = sim_get_element(element_id);
    if (e.id.empty()) return info;
    if (g_simulation_mode) {
        info.width = e.bounds.width;
        info.height = e.bounds.height;
        info.format = "png";
        info.full_page = false;
        info.base64_data = "iVBORw0KGgoAAAANSUhEUgAA";
    }
    return info;
}

ScreenshotInfo screenshot_region(int x, int y, int width, int height) {
    ScreenshotInfo info;
    if (g_simulation_mode) {
        info.width = width;
        info.height = height;
        info.format = "png";
        info.full_page = false;
        info.base64_data = "iVBORw0KGgoAAAANSUhEUgAA";
    }
    return info;
}

bool save_screenshot(const std::string& filepath, bool full_page) {
    if (g_simulation_mode) {
        auto info = take_screenshot(full_page);
        std::ofstream f(filepath, std::ios::binary);
        if (!f) return false;
        f << "PNG_SIMULATED_SCREENSHOT " << info.width << "x" << info.height;
        f.close();
        return true;
    }
    return false;
}

// ===== Interaction API =====
bool click_element(const std::string& element_id) {
    if (g_simulation_mode) {
        auto e = sim_get_element(element_id);
        return !e.id.empty() && e.clickable;
    }
    return false;
}

bool click_element_at(int x, int y) {
    if (g_simulation_mode) {
        auto all = get_all_elements();
        for (const auto& e : all) {
            if (e.bounds.contains(x, y) && e.clickable) return true;
        }
        return false;
    }
#if defined(_WIN32)
    // Real Win32: move mouse to (x,y), click, then restore position
    POINT oldPos;
    GetCursorPos(&oldPos);
    // Set cursor position
    SetCursorPos(x, y);
    Sleep(100);
    // Mouse down + up (left click)
    mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0);
    mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0);
    Sleep(200);
    // Restore cursor
    SetCursorPos(oldPos.x, oldPos.y);
    return true;
#else
    return false;
#endif
}

bool type_text(const std::string& element_id, const std::string& text) {
    if (g_simulation_mode) {
        auto e = sim_get_element(element_id);
        return !e.id.empty() && e.is_input;
    }
    return false;
}

bool type_text_into_active_element(const std::string& text) {
    if (g_simulation_mode) return true;
#if defined(_WIN32)
    // Real Win32: send each character as a key event to whatever has focus
    for (char c : text) {
        if (c == ' ') {
            keybd_event(VK_SPACE, 0, 0, 0);
            keybd_event(VK_SPACE, 0, KEYEVENTF_KEYUP, 0);
        } else if (c == '\n' || c == '\r') {
            keybd_event(VK_RETURN, 0, 0, 0);
            keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0);
        } else if ((unsigned char)c >= 0x80) {
            // For non-ASCII chars, use Unicode input
            INPUT input = {};
            input.type = INPUT_KEYBOARD;
            input.ki.wScan = (unsigned char)c;
            input.ki.dwFlags = KEYEVENTF_UNICODE;
            SendInput(1, &input, sizeof(INPUT));
            input.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP;
            SendInput(1, &input, sizeof(INPUT));
        } else {
            short vk = VkKeyScanA(c);
            if (vk != -1) {
                BYTE vkey = vk & 0xFF;
                bool shift = (vk & 0x100) != 0;
                if (shift) keybd_event(VK_SHIFT, 0, 0, 0);
                keybd_event(vkey, 0, 0, 0);
                keybd_event(vkey, 0, KEYEVENTF_KEYUP, 0);
                if (shift) keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0);
            }
        }
        Sleep(10);
    }
    return true;
#else
    return false;
#endif
}

bool press_key(const std::string& key) {
    if (g_simulation_mode) return true;
#if defined(_WIN32)
    // Map common key names to virtual key codes
    WORD vk = 0;
    std::string lowerKey = key;
    for (auto& c : lowerKey) c = (char)tolower((unsigned char)c);

    if (lowerKey == "enter" || lowerKey == "return") vk = VK_RETURN;
    else if (lowerKey == "tab") vk = VK_TAB;
    else if (lowerKey == "escape" || lowerKey == "esc") vk = VK_ESCAPE;
    else if (lowerKey == "backspace" || lowerKey == "back") vk = VK_BACK;
    else if (lowerKey == "delete" || lowerKey == "del") vk = VK_DELETE;
    else if (lowerKey == "space") vk = VK_SPACE;
    else if (lowerKey == "up") vk = VK_UP;
    else if (lowerKey == "down") vk = VK_DOWN;
    else if (lowerKey == "left") vk = VK_LEFT;
    else if (lowerKey == "right") vk = VK_RIGHT;
    else if (lowerKey == "home") vk = VK_HOME;
    else if (lowerKey == "end") vk = VK_END;
    else if (lowerKey == "f5") vk = VK_F5;
    else if (key.size() == 1) vk = VkKeyScanA(key[0]) & 0xFF;
    else return false;

    keybd_event(vk, 0, 0, 0);
    keybd_event(vk, 0, KEYEVENTF_KEYUP, 0);
    Sleep(100);
    return true;
#else
    return false;
#endif
}

bool select_option(const std::string& element_id, const std::string& value) {
    if (g_simulation_mode) {
        auto e = sim_get_element(element_id);
        return !e.id.empty() && e.type == BrowserElementType::select;
    }
    return false;
}

bool submit_form(const std::string& form_id) {
    if (g_simulation_mode) return true;
    return false;
}

bool clear_input(const std::string& element_id) {
    if (g_simulation_mode) {
        auto e = sim_get_element(element_id);
        return !e.id.empty() && e.is_input;
    }
    return false;
}

bool focus_element(const std::string& element_id) {
    if (g_simulation_mode) return true;
    return false;
}

bool hover_element(const std::string& element_id) {
    if (g_simulation_mode) return true;
    return false;
}

// ===== Wait API =====
bool wait_for_element(const std::string& selector, int timeout_ms) {
    if (g_simulation_mode) {
        auto all = get_all_elements();
        for (const auto& e : all) {
            if (contains_ci(e.id, selector) || contains_ci(e.text, selector)) return true;
        }
        return false;
    }
    return false;
}

bool wait_for_text(const std::string& text, int timeout_ms) {
    if (g_simulation_mode) {
        return contains_ci(current_page().content_text, text);
    }
    return false;
}

bool wait_for_navigation(int timeout_ms) {
    if (g_simulation_mode) return true;
    return false;
}

// ===== JavaScript API =====
std::string execute_javascript(const std::string& script) {
    if (g_simulation_mode) {
        g_sim_js_result = "Simulated JS execution result";
        return "{\"result\":\"Simulated JS execution result\",\"success\":true}";
    }
    return "{\"result\":\"\",\"success\":false}";
}

// ===== Form Data API =====
std::vector<FormField> get_form_fields(const std::string& form_id) {
    std::vector<FormField> fields;
    if (g_simulation_mode) {
        auto children = get_element_children(form_id);
        for (const auto& e : children) {
            if (e.is_input) {
                FormField f;
                f.name = e.name;
                f.type = element_type_to_string(e.type);
                f.label = e.placeholder;
                f.value = e.value;
                f.placeholder = e.placeholder;
                fields.push_back(f);
            }
        }
    }
    return fields;
}

bool fill_form(const std::string& form_id, const std::map<std::string, std::string>& values) {
    if (g_simulation_mode) return true;
    return false;
}

// ===== Table Data API =====
std::vector<TableData> get_tables_data() {
    std::vector<TableData> tables;
    if (g_simulation_mode) {
        auto content = current_page().content_text;
        // Parse tables from content
        size_t pos = 0;
        int table_idx = 0;
        while ((pos = content.find("Table ", pos)) != std::string::npos) {
            // Find the table caption line
            size_t end_line = content.find('\n', pos);
            if (end_line == std::string::npos) break;
            std::string caption = content.substr(pos, end_line - pos);

            // Find header line (next non-empty line)
            size_t header_start = end_line + 1;
            while (header_start < content.size() && content[header_start] == '\n') header_start++;
            size_t header_end = content.find('\n', header_start);
            if (header_end == std::string::npos) break;
            std::string header_line = content.substr(header_start, header_end - header_start);

            // Parse headers by |
            TableData td;
            td.id = "table_" + std::to_string(table_idx);
            td.caption = caption;
            std::istringstream hss(header_line);
            std::string h;
            while (std::getline(hss, h, '|')) {
                // Trim
                while (!h.empty() && h.front() == ' ') h.erase(0, 1);
                while (!h.empty() && h.back() == ' ') h.pop_back();
                if (!h.empty()) td.headers.push_back(h);
            }

            // Parse rows until empty line or next "Table "
            size_t row_start = header_end + 1;
            while (row_start < content.size()) {
                while (row_start < content.size() && content[row_start] == '\n') {
                    // Check if next is another table or end
                    if (row_start + 1 < content.size() && content.substr(row_start + 1, 5) == "Table") break;
                    row_start++;
                }
                if (row_start >= content.size() || content[row_start] == '\n') break;
                size_t row_end = content.find('\n', row_start);
                if (row_end == std::string::npos) row_end = content.size();
                std::string row_line = content.substr(row_start, row_end - row_start);

                if (row_line.find("Table ") == 0 || row_line.find("Key Findings") == 0 ||
                    row_line.find("Download") == 0 || row_line.find("Related") == 0) break;

                std::vector<std::string> row;
                std::istringstream rss(row_line);
                std::string cell;
                while (std::getline(rss, cell, '|')) {
                    while (!cell.empty() && cell.front() == ' ') cell.erase(0, 1);
                    while (!cell.empty() && cell.back() == ' ') cell.pop_back();
                    if (!cell.empty()) row.push_back(cell);
                }
                if (!row.empty()) td.rows.push_back(row);

                row_start = row_end + 1;
            }

            tables.push_back(td);
            table_idx++;
            pos = row_start;
        }
    }
    return tables;
}

TableData get_table_data(const std::string& table_id) {
    auto tables = get_tables_data();
    for (const auto& t : tables) {
        if (t.id == table_id) return t;
    }
    return TableData{};
}

// ===== History API =====
std::vector<std::string> get_history() {
    if (g_simulation_mode) return g_sim_history;
    return {};
}

bool clear_history() {
    if (g_simulation_mode) {
        g_sim_history.clear();
        return true;
    }
    return false;
}

// ===== Cookie API =====
std::string get_cookies() {
    if (g_simulation_mode) {
        std::ostringstream ss;
        ss << "{\"cookies\":[";
        bool first = true;
        for (const auto& [name, value] : g_sim_cookies) {
            if (!first) ss << ",";
            ss << "{\"name\":\"" << name << "\",\"value\":\"" << value << "\"}";
            first = false;
        }
        ss << "]}";
        return ss.str();
    }
    return "{\"cookies\":[]}";
}

bool set_cookie(const std::string& name, const std::string& value, const std::string& domain) {
    if (g_simulation_mode) {
        g_sim_cookies[name] = value;
        return true;
    }
    return false;
}

bool clear_cookies() {
    if (g_simulation_mode) {
        g_sim_cookies.clear();
        return true;
    }
    return false;
}

// ===== Export API =====
std::string export_page_data() {
    if (g_simulation_mode) {
        std::ostringstream ss;
        ss << "{\"version\":\"1.0\",\"platform\":\"" << platform_to_string(get_current_platform()) << "\",";
        ss << "\"page\":" << current_page().to_json() << ",";
        ss << "\"elements\":" << elements_to_json(current_page_elements()) << ",";
        ss << "\"browser\":" << get_browser_info().to_json() << "}";
        return ss.str();
    }
    return "{}";
}

bool save_page_content(const std::string& filepath) {
    if (g_simulation_mode) {
        std::ofstream f(filepath);
        if (!f) return false;
        f << current_page().content_text;
        f.close();
        return true;
    }
    return false;
}

// ===== High-Level Browser Actions =====

static bool contains_ci_str(const std::string& haystack, const std::string& needle) {
    if (needle.empty()) return true;
    if (haystack.size() < needle.size()) return false;
    auto to_lower = [](const std::string& s) {
        std::string r;
        for (char c : s) r += static_cast<char>(tolower(static_cast<unsigned char>(c)));
        return r;
    };
    return to_lower(haystack).find(to_lower(needle)) != std::string::npos;
}

std::string browser_search(const std::string& query) {
    // Build a YouTube search URL and navigate to it
    std::string url = "https://www.youtube.com/results?search_query=" + query;
    // URL-encode spaces as +
    for (auto& c : url) if (c == ' ') c = '+';
    bool ok = navigate(url);
    if (ok) {
#if defined(_WIN32)
        // Give the browser time to load the search results
        Sleep(3000);
#endif
    }
    return ok ? "{\"success\":true,\"url\":\"" + url + "\",\"message\":\"YouTube search results opened. Use browser_click_text to click a video title.\"}"
              : "{\"success\":false}";
}

std::string browser_click_text(const std::string& text) {
    // On Windows, browser web content is not accessible via EnumChildWindows.
    // Strategy: Use keyboard navigation — Tab through focusable elements and
    // press Enter when we find one matching the text.
#if defined(_WIN32)
    // Fallback: Use keyboard Tab navigation to find and click the element
    // Tab through focusable elements (up to 30 tabs), check if focused element
    // text matches, then press Enter
    for (int i = 0; i < 30; i++) {
        // Press Tab to move to next focusable element
        keybd_event(VK_TAB, 0, 0, 0);
        keybd_event(VK_TAB, 0, KEYEVENTF_KEYUP, 0);
        Sleep(100);

        // Get the focused window title to check if it matches
        HWND fg = GetForegroundWindow();
        if (fg) {
            wchar_t title[512] = {};
            GetWindowTextW(fg, title, 512);
            if (title[0]) {
                std::wstring wTitle(title);
                std::string titleStr(wTitle.begin(), wTitle.end());
                // Check if the title contains our search text
                if (contains_ci_str(titleStr, text)) {
                    // Press Enter to activate this element
                    keybd_event(VK_RETURN, 0, 0, 0);
                    keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0);
                    Sleep(2000);
                    return "{\"success\":true,\"clicked_text\":\"" + text + "\",\"method\":\"keyboard_tab\",\"tabs\":" + std::to_string(i + 1) + "}";
                }
            }
        }
    }
    return "{\"success\":false,\"error\":\"Could not find text on screen: " + text + ". Try using mouse_click with coordinates from screen_capture.\"}";
#else
    (void)text;
    return "{\"success\":false,\"error\":\"Not supported on this platform\"}";
#endif
}

std::string browser_type_active(const std::string& text) {
    bool ok = type_text_into_active_element(text);
    return ok ? "{\"success\":true}" : "{\"success\":false}";
}

std::string browser_press_key(const std::string& key) {
    bool ok = press_key(key);
    return ok ? "{\"success\":true}" : "{\"success\":false}";
}

} // namespace browsertool
