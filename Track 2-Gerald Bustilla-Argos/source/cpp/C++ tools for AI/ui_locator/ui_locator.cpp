#include "ui_locator.h"
#include <algorithm>
#include <cmath>
#include <sstream>
#include <iomanip>
#include <set>
#include <atomic>

// Platform-specific headers
#if defined(_WIN32)
    #ifndef NOMINMAX
    #define NOMINMAX
    #endif
    #include <windows.h>
    #include <psapi.h>
#elif defined(__linux__)
    #include <X11/Xlib.h>
#elif defined(__APPLE__)
    #include <ApplicationServices/ApplicationServices.h>
#endif

namespace uilocator {

// ===== Platform Detection =====

Platform get_current_platform() {
    if (is_simulation_mode()) return Platform::SIMULATION;
#if defined(_WIN32)
    return Platform::WINDOWS;
#elif defined(__ANDROID__)
    return Platform::ANDROID;
#elif defined(__APPLE__)
    #include <TargetConditionals.h>
    #if TARGET_OS_IPHONE
        return Platform::IOS;
    #else
        return Platform::MACOS;
    #endif
#elif defined(__linux__)
    return Platform::LINUX;
#else
    return Platform::SIMULATION;
#endif
}

std::string platform_to_string(Platform p) {
    switch (p) {
        case Platform::WINDOWS: return "windows";
        case Platform::LINUX: return "linux";
        case Platform::MACOS: return "macos";
        case Platform::ANDROID: return "android";
        case Platform::IOS: return "ios";
        case Platform::SIMULATION: return "simulation";
        default: return "unknown";
    }
}

// ===== Simulation State =====

static std::atomic<bool> g_simulation_mode{false};
static std::vector<WindowInfo> g_sim_windows;
static std::vector<UIElement> g_sim_elements;

void enable_simulation_mode() { g_simulation_mode = true; }
void disable_simulation_mode() { g_simulation_mode = false; }
bool is_simulation_mode() { return g_simulation_mode.load(); }

void sim_add_window(const WindowInfo& window, const std::vector<UIElement>& elements) {
    g_sim_windows.push_back(window);
    for (const auto& e : elements) {
        g_sim_elements.push_back(e);
    }
}

void sim_clear() {
    g_sim_windows.clear();
    g_sim_elements.clear();
}

size_t sim_window_count() { return g_sim_windows.size(); }
size_t sim_element_count() { return g_sim_elements.size(); }

// ===== Utility Functions =====

static int json_get_int_helper(const std::string& json, const std::string& key) {
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

int levenshtein_distance(const std::string& a, const std::string& b) {
    int m = static_cast<int>(a.size());
    int n = static_cast<int>(b.size());
    std::vector<int> prev(n + 1), curr(n + 1);
    for (int j = 0; j <= n; j++) prev[j] = j;
    for (int i = 1; i <= m; i++) {
        curr[0] = i;
        for (int j = 1; j <= n; j++) {
            int cost = (std::tolower(static_cast<unsigned char>(a[i-1])) ==
                       std::tolower(static_cast<unsigned char>(b[j-1]))) ? 0 : 1;
            curr[j] = std::min({prev[j] + 1, curr[j-1] + 1, prev[j-1] + cost});
        }
        std::swap(prev, curr);
    }
    return prev[n];
}

double fuzzy_match(const std::string& a, const std::string& b) {
    if (a.empty() && b.empty()) return 1.0;
    if (a.empty() || b.empty()) return 0.0;
    int dist = levenshtein_distance(a, b);
    int max_len = static_cast<int>(std::max(a.size(), b.size()));
    return 1.0 - static_cast<double>(dist) / max_len;
}

// ===== Platform-Specific Window Enumeration =====

#if defined(_WIN32)

struct WinEnumData {
    std::vector<WindowInfo> windows;
};

static BOOL CALLBACK enum_windows_callback(HWND hwnd, LPARAM lParam) {
    auto* data = reinterpret_cast<WinEnumData*>(lParam);

    if (!IsWindowVisible(hwnd)) return TRUE;

    char title[512] = {0};
    GetWindowTextA(hwnd, title, sizeof(title));
    if (title[0] == '\0') return TRUE;

    RECT rect;
    GetWindowRect(hwnd, &rect);

    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);

    char process_name[256] = {0};
    HANDLE hProcess = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, FALSE, pid);
    if (hProcess) {
        HMODULE hMod;
        DWORD cbNeeded;
        if (EnumProcessModules(hProcess, &hMod, sizeof(hMod), &cbNeeded)) {
            GetModuleBaseNameA(hProcess, hMod, process_name, sizeof(process_name));
        }
        CloseHandle(hProcess);
    }

    WindowInfo wi;
    wi.id = std::to_string(reinterpret_cast<uintptr_t>(hwnd));
    wi.title = title;
    wi.process_name = process_name;
    wi.process_id = static_cast<int>(pid);
    wi.bounds.x = rect.left;
    wi.bounds.y = rect.top;
    wi.bounds.width = rect.right - rect.left;
    wi.bounds.height = rect.bottom - rect.top;
    wi.is_visible = true;
    wi.is_focused = (hwnd == GetForegroundWindow());
    wi.is_maximized = IsZoomed(hwnd);
    wi.is_minimized = IsIconic(hwnd);
    wi.platform = "windows";

    data->windows.push_back(std::move(wi));
    return TRUE;
}

static std::vector<WindowInfo> platform_list_windows() {
    WinEnumData data;
    EnumWindows(enum_windows_callback, reinterpret_cast<LPARAM>(&data));
    return data.windows;
}

static std::vector<UIElement> platform_get_elements(const std::string& window_id) {
    std::vector<UIElement> elements;
    try {
        HWND hwnd = reinterpret_cast<HWND>(std::stoull(window_id));
        if (!IsWindow(hwnd)) return elements;

        RECT wr;
        GetWindowRect(hwnd, &wr);
        DWORD pid = 0;
        GetWindowThreadProcessId(hwnd, &pid);

        // Enumerate child windows as UI elements
        struct ChildData {
            std::vector<UIElement>* elements;
            HWND parent;
            DWORD pid;
            int z;
        };
        ChildData cd{&elements, hwnd, pid, 0};

        EnumChildWindows(hwnd, [](HWND child, LPARAM lp) -> BOOL {
            auto* cd = reinterpret_cast<ChildData*>(lp);
            if (!IsWindowVisible(child)) return TRUE;

            char text[256] = {0};
            GetWindowTextA(child, text, sizeof(text));

            char className[256] = {0};
            GetClassNameA(child, className, sizeof(className));

            RECT r;
            GetWindowRect(child, &r);

            UIElement e;
            e.id = std::to_string(reinterpret_cast<uintptr_t>(child));
            e.parent_id = std::to_string(reinterpret_cast<uintptr_t>(cd->parent));
            e.window_id = std::to_string(reinterpret_cast<uintptr_t>(cd->parent));
            e.type_name = className;
            e.text = text;
            e.bounds.x = r.left;
            e.bounds.y = r.top;
            e.bounds.width = r.right - r.left;
            e.bounds.height = r.bottom - r.top;
            e.enabled = IsWindowEnabled(child);
            e.visible = true;
            e.process_id = static_cast<int>(cd->pid);
            e.z_order = cd->z++;

            // Classify type based on window class name
            std::string cn = className;
            std::string cn_lower;
            for (char c : cn) cn_lower += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));

            if (cn_lower.find("button") != std::string::npos) {
                long style = GetWindowLongPtrA(child, GWL_STYLE);
                if (style & BS_CHECKBOX) e.type = ElementType::CHECKBOX;
                else if (style & BS_RADIOBUTTON) e.type = ElementType::RADIO_BUTTON;
                else e.type = ElementType::BUTTON;
            } else if (cn_lower.find("edit") != std::string::npos) {
                long style = GetWindowLongPtrA(child, GWL_STYLE);
                if (style & ES_MULTILINE) e.type = ElementType::TEXT_AREA;
                else e.type = ElementType::TEXT_FIELD;
            } else if (cn_lower.find("static") != std::string::npos) {
                e.type = ElementType::LABEL;
            } else if (cn_lower.find("combobox") != std::string::npos) {
                e.type = ElementType::COMBO_BOX;
            } else if (cn_lower.find("listbox") != std::string::npos) {
                e.type = ElementType::LIST_VIEW;
            } else if (cn_lower.find("listview") != std::string::npos) {
                e.type = ElementType::LIST_VIEW;
            } else if (cn_lower.find("treeview") != std::string::npos) {
                e.type = ElementType::TREE_VIEW;
            } else if (cn_lower.find("progress") != std::string::npos) {
                e.type = ElementType::PROGRESS_BAR;
            } else if (cn_lower.find("trackbar") != std::string::npos || cn_lower.find("slider") != std::string::npos) {
                e.type = ElementType::SLIDER;
            } else if (cn_lower.find("scrollbar") != std::string::npos) {
                e.type = ElementType::SCROLLBAR;
            } else if (cn_lower.find("toolbar") != std::string::npos) {
                e.type = ElementType::TOOLBAR;
            } else if (cn_lower.find("statusbar") != std::string::npos) {
                e.type = ElementType::STATUS_BAR;
            } else if (cn_lower.find("tab") != std::string::npos) {
                e.type = ElementType::TAB_CONTROL;
            } else if (cn_lower.find("menu") != std::string::npos) {
                e.type = ElementType::MENU_BAR;
            } else if (cn_lower.find("link") != std::string::npos) {
                e.type = ElementType::LINK;
            } else {
                e.type = ElementType::CUSTOM;
            }

            cd->elements->push_back(std::move(e));
            return TRUE;
        }, reinterpret_cast<LPARAM>(&cd));

        // Add the window itself as root element
        UIElement root;
        root.id = window_id;
        root.window_id = window_id;
        root.type = ElementType::WINDOW;
        root.type_name = "Window";
        char win_title[512] = {0};
        GetWindowTextA(hwnd, win_title, sizeof(win_title));
        root.text = win_title;
        root.bounds.x = wr.left;
        root.bounds.y = wr.top;
        root.bounds.width = wr.right - wr.left;
        root.bounds.height = wr.bottom - wr.top;
        root.enabled = true;
        root.visible = true;
        root.process_id = static_cast<int>(pid);
        elements.insert(elements.begin(), std::move(root));
    } catch (...) {}
    return elements;
}

static UIElement platform_get_focused_element() {
    UIElement e;
    HWND focused = GetFocus();
    if (!focused) {
        focused = GetForegroundWindow();
    }
    if (focused) {
        char text[256] = {0};
        GetWindowTextA(focused, text, sizeof(text));
        char className[256] = {0};
        GetClassNameA(focused, className, sizeof(className));
        RECT r;
        GetWindowRect(focused, &r);
        DWORD pid = 0;
        GetWindowThreadProcessId(focused, &pid);

        e.id = std::to_string(reinterpret_cast<uintptr_t>(focused));
        e.type_name = className;
        e.text = text;
        e.bounds.x = r.left;
        e.bounds.y = r.top;
        e.bounds.width = r.right - r.left;
        e.bounds.height = r.bottom - r.top;
        e.focused = true;
        e.process_id = static_cast<int>(pid);
    }
    return e;
}

static bool platform_click_at(int x, int y) {
    INPUT input = {0};
    input.type = INPUT_MOUSE;
    input.mi.dx = (LONG)(x * 65535.0 / GetSystemMetrics(SM_CXSCREEN));
    input.mi.dy = (LONG)(y * 65535.0 / GetSystemMetrics(SM_CYSCREEN));
    input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE;
    SendInput(1, &input, sizeof(INPUT));

    ZeroMemory(&input, sizeof(INPUT));
    input.type = INPUT_MOUSE;
    input.mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
    SendInput(1, &input, sizeof(INPUT));

    ZeroMemory(&input, sizeof(INPUT));
    input.type = INPUT_MOUSE;
    input.mi.dwFlags = MOUSEEVENTF_LEFTUP;
    SendInput(1, &input, sizeof(INPUT));
    return true;
}

static bool platform_type_text(const std::string& text) {
    for (char c : text) {
        INPUT input = {0};
        input.type = INPUT_KEYBOARD;
        input.ki.wScan = c;
        input.ki.dwFlags = KEYEVENTF_UNICODE;
        SendInput(1, &input, sizeof(INPUT));
        input.ki.dwFlags |= KEYEVENTF_KEYUP;
        SendInput(1, &input, sizeof(INPUT));
    }
    return true;
}

#else
// Stubs for non-Windows platforms
static std::vector<WindowInfo> platform_list_windows() { return {}; }
static std::vector<UIElement> platform_get_elements(const std::string&) { return {}; }
static UIElement platform_get_focused_element() { return UIElement{}; }
static bool platform_click_at(int, int) { return false; }
static bool platform_type_text(const std::string&) { return false; }
#endif

// ===== Core API Implementation =====

std::vector<WindowInfo> list_windows() {
    if (is_simulation_mode()) return g_sim_windows;
    return platform_list_windows();
}

std::vector<UIElement> get_elements(const std::string& window_id) {
    if (is_simulation_mode()) {
        std::vector<UIElement> result;
        for (const auto& e : g_sim_elements) {
            if (e.window_id == window_id) result.push_back(e);
        }
        return result;
    }
    return platform_get_elements(window_id);
}

std::vector<UIElement> get_all_elements() {
    if (is_simulation_mode()) return g_sim_elements;
    std::vector<UIElement> all;
    auto windows = list_windows();
    for (const auto& w : windows) {
        auto elems = get_elements(w.id);
        for (auto& e : elems) all.push_back(std::move(e));
    }
    return all;
}

UIElement get_element(const std::string& element_id) {
    if (is_simulation_mode()) {
        for (const auto& e : g_sim_elements) {
            if (e.id == element_id) return e;
        }
        return UIElement{};
    }
    auto all = get_all_elements();
    for (const auto& e : all) {
        if (e.id == element_id) return e;
    }
    return UIElement{};
}

UIElement get_focused_element() {
    if (is_simulation_mode()) {
        for (const auto& e : g_sim_elements) {
            if (e.focused) return e;
        }
        return UIElement{};
    }
    return platform_get_focused_element();
}

WindowInfo get_focused_window() {
    auto windows = list_windows();
    for (const auto& w : windows) {
        if (w.is_focused) return w;
    }
    if (!windows.empty()) return windows[0];
    return WindowInfo{};
}

// ===== Search Implementation =====

std::vector<ElementSearchResult> search_by_text(const std::string& query, const std::string& window_id) {
    std::vector<ElementSearchResult> results;
    auto all_elements = (window_id.empty()) ? get_all_elements() : get_elements(window_id);

    for (const auto& e : all_elements) {
        double best_score = 0.0;
        std::string reason;

        // Exact text match
        if (e.text == query) {
            best_score = 1.0;
            reason = "exact_text_match";
        }
        // Case-insensitive text match
        else if (contains_ci(e.text, query)) {
            best_score = 0.9;
            reason = "text_contains";
        }
        // Fuzzy text match
        else {
            double fuzzy = fuzzy_match(e.text, query);
            if (fuzzy > 0.6) {
                best_score = fuzzy * 0.8;
                reason = "fuzzy_text";
            }
            // Word-level fuzzy match: try each word in the element text
            if (best_score == 0.0) {
                std::istringstream iss(e.text);
                std::string word;
                while (iss >> word) {
                    double wfuzzy = fuzzy_match(word, query);
                    if (wfuzzy > 0.6) {
                        double ws = wfuzzy * 0.75;
                        if (ws > best_score) {
                            best_score = ws;
                            reason = "fuzzy_word_match";
                        }
                    }
                }
            }
        }

        // Also check name field
        if (contains_ci(e.name, query)) {
            double name_score = 0.85;
            if (name_score > best_score) {
                best_score = name_score;
                reason = "name_match";
            }
        }

        // Check description
        if (contains_ci(e.description, query)) {
            double desc_score = 0.75;
            if (desc_score > best_score) {
                best_score = desc_score;
                reason = "description_match";
            }
        }

        // Check help_text
        if (contains_ci(e.help_text, query)) {
            double help_score = 0.7;
            if (help_score > best_score) {
                best_score = help_score;
                reason = "help_text_match";
            }
        }

        if (best_score > 0.0) {
            ElementSearchResult r;
            r.element = e;
            r.score = best_score;
            r.match_reason = reason;
            results.push_back(std::move(r));
        }
    }

    std::sort(results.begin(), results.end(),
              [](const ElementSearchResult& a, const ElementSearchResult& b) { return a.score > b.score; });
    return results;
}

std::vector<ElementSearchResult> search_by_type(ElementType type, const std::string& window_id) {
    std::vector<ElementSearchResult> results;
    auto all_elements = (window_id.empty()) ? get_all_elements() : get_elements(window_id);

    for (const auto& e : all_elements) {
        if (e.type == type) {
            ElementSearchResult r;
            r.element = e;
            r.score = 1.0;
            r.match_reason = "type_match";
            results.push_back(std::move(r));
        }
    }
    return results;
}

std::vector<ElementSearchResult> search_by_type_string(const std::string& type_str, const std::string& window_id) {
    return search_by_type(string_to_element_type(type_str), window_id);
}

std::vector<ElementSearchResult> search_elements(const std::string& query, const std::string& type_filter, const std::string& window_id, size_t top_k) {
    std::vector<ElementSearchResult> results;

    // Get text matches
    auto text_results = search_by_text(query, window_id);

    // Filter by type if specified
    if (!type_filter.empty()) {
        ElementType filter_type = string_to_element_type(type_filter);
        for (auto& r : text_results) {
            if (r.element.type == filter_type) {
                results.push_back(r);
            }
        }
    } else {
        results = text_results;
    }

    // If no text query but type filter, search by type
    if (query.empty() && !type_filter.empty()) {
        results = search_by_type_string(type_filter, window_id);
    }

    // Sort by score
    std::sort(results.begin(), results.end(),
              [](const ElementSearchResult& a, const ElementSearchResult& b) { return a.score > b.score; });

    if (results.size() > top_k) results.resize(top_k);
    return results;
}

std::vector<ElementSearchResult> search_clickable(const std::string& text_filter, const std::string& window_id) {
    std::vector<ElementSearchResult> results;
    auto all_elements = (window_id.empty()) ? get_all_elements() : get_elements(window_id);

    for (const auto& e : all_elements) {
        if (!e.is_clickable()) continue;
        if (!e.enabled || !e.visible) continue;

        double score = 1.0;
        std::string reason = "clickable";

        if (!text_filter.empty()) {
            if (contains_ci(e.text, text_filter)) {
                score = 0.95;
                reason = "clickable_text_match";
            } else if (contains_ci(e.name, text_filter)) {
                score = 0.85;
                reason = "clickable_name_match";
            } else {
                double fuzzy = fuzzy_match(e.text, text_filter);
                if (fuzzy > 0.5) {
                    score = fuzzy * 0.8;
                    reason = "clickable_fuzzy";
                } else {
                    continue;
                }
            }
        }

        ElementSearchResult r;
        r.element = e;
        r.score = score;
        r.match_reason = reason;
        results.push_back(std::move(r));
    }

    std::sort(results.begin(), results.end(),
              [](const ElementSearchResult& a, const ElementSearchResult& b) { return a.score > b.score; });
    return results;
}

std::vector<ElementSearchResult> search_text_inputs(const std::string& text_filter, const std::string& window_id) {
    std::vector<ElementSearchResult> results;
    auto all_elements = (window_id.empty()) ? get_all_elements() : get_elements(window_id);

    for (const auto& e : all_elements) {
        if (!e.is_text_input()) continue;
        if (!e.enabled || !e.visible) continue;

        double score = 1.0;
        std::string reason = "text_input";

        if (!text_filter.empty()) {
            if (contains_ci(e.text, text_filter) || contains_ci(e.name, text_filter)) {
                score = 0.9;
                reason = "text_input_match";
            } else {
                continue;
            }
        }

        ElementSearchResult r;
        r.element = e;
        r.score = score;
        r.match_reason = reason;
        results.push_back(std::move(r));
    }

    std::sort(results.begin(), results.end(),
              [](const ElementSearchResult& a, const ElementSearchResult& b) { return a.score > b.score; });
    return results;
}

UIElement find_element_at(int x, int y) {
    auto all = get_all_elements();
    UIElement best;
    int best_area = INT_MAX;

    for (const auto& e : all) {
        if (!e.visible) continue;
        if (e.bounds.contains(x, y)) {
            int area = e.bounds.area();
            if (area < best_area) {
                best = e;
                best_area = area;
            }
        }
    }
    return best;
}

std::vector<UIElement> find_elements_at(int x, int y) {
    std::vector<UIElement> results;
    auto all = get_all_elements();
    for (const auto& e : all) {
        if (e.visible && e.bounds.contains(x, y)) {
            results.push_back(e);
        }
    }
    // Sort by area (smallest first = most specific)
    std::sort(results.begin(), results.end(),
              [](const UIElement& a, const UIElement& b) { return a.bounds.area() < b.bounds.area(); });
    return results;
}

// ===== Hierarchy API =====

std::vector<UIElement> get_children(const std::string& element_id) {
    std::vector<UIElement> children;
    auto all = get_all_elements();
    for (const auto& e : all) {
        if (e.parent_id == element_id) children.push_back(e);
    }
    return children;
}

UIElement get_parent(const std::string& element_id) {
    auto elem = get_element(element_id);
    if (elem.parent_id.empty()) return UIElement{};
    return get_element(elem.parent_id);
}

std::vector<UIElement> get_element_tree(const std::string& element_id) {
    std::vector<UIElement> tree;
    auto root = get_element(element_id);
    if (root.id.empty()) return tree;
    tree.push_back(root);

    std::function<void(const std::string&)> collect = [&](const std::string& pid) {
        auto children = get_children(pid);
        for (const auto& child : children) {
            tree.push_back(child);
            collect(child.id);
        }
    };
    collect(element_id);
    return tree;
}

// ===== Action API =====

bool click_at(int x, int y) {
    if (is_simulation_mode()) return true;
    return platform_click_at(x, y);
}

bool click_element(const std::string& element_id) {
    auto e = get_element(element_id);
    if (e.id.empty()) return false;
    return click_at(e.bounds.center_x(), e.bounds.center_y());
}

bool double_click_at(int x, int y) {
    click_at(x, y);
    // Small delay
    click_at(x, y);
    return true;
}

bool right_click_at(int x, int y) {
    if (is_simulation_mode()) return true;
#if defined(_WIN32)
    INPUT input = {0};
    input.type = INPUT_MOUSE;
    input.mi.dx = (LONG)(x * 65535.0 / GetSystemMetrics(SM_CXSCREEN));
    input.mi.dy = (LONG)(y * 65535.0 / GetSystemMetrics(SM_CYSCREEN));
    input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE;
    SendInput(1, &input, sizeof(INPUT));

    ZeroMemory(&input, sizeof(INPUT));
    input.type = INPUT_MOUSE;
    input.mi.dwFlags = MOUSEEVENTF_RIGHTDOWN;
    SendInput(1, &input, sizeof(INPUT));

    ZeroMemory(&input, sizeof(INPUT));
    input.type = INPUT_MOUSE;
    input.mi.dwFlags = MOUSEEVENTF_RIGHTUP;
    SendInput(1, &input, sizeof(INPUT));
    return true;
#else
    return false;
#endif
}

bool type_text(const std::string& text) {
    if (is_simulation_mode()) return true;
    return platform_type_text(text);
}

bool press_key(int key_code) {
    if (is_simulation_mode()) return true;
#if defined(_WIN32)
    INPUT input = {0};
    input.type = INPUT_KEYBOARD;
    input.ki.wVk = static_cast<WORD>(key_code);
    SendInput(1, &input, sizeof(INPUT));
    input.ki.dwFlags |= KEYEVENTF_KEYUP;
    SendInput(1, &input, sizeof(INPUT));
    return true;
#else
    return false;
#endif
}

// ===== JSON Serialization =====

std::string windows_to_json(const std::vector<WindowInfo>& windows) {
    std::ostringstream ss;
    ss << "{\"total_windows\":" << windows.size() << ",\"windows\":[";
    for (size_t i = 0; i < windows.size(); i++) {
        if (i > 0) ss << ",";
        ss << windows[i].to_json();
    }
    ss << "]}";
    return ss.str();
}

std::string elements_to_json(const std::vector<UIElement>& elements) {
    std::ostringstream ss;
    ss << "{\"total_elements\":" << elements.size() << ",\"elements\":[";
    for (size_t i = 0; i < elements.size(); i++) {
        if (i > 0) ss << ",";
        ss << elements[i].to_json();
    }
    ss << "]}";
    return ss.str();
}

std::string search_results_to_json(const std::vector<ElementSearchResult>& results) {
    std::ostringstream ss;
    ss << "{\"total_results\":" << results.size() << ",\"results\":[";
    for (size_t i = 0; i < results.size(); i++) {
        if (i > 0) ss << ",";
        ss << results[i].to_json();
    }
    ss << "]}";
    return ss.str();
}

std::string element_to_json(const UIElement& element) {
    std::ostringstream ss;
    ss << "{\"element\":" << element.to_json() << "}";
    return ss.str();
}

std::string window_to_json(const WindowInfo& window) {
    std::ostringstream ss;
    ss << "{\"window\":" << window.to_json() << "}";
    return ss.str();
}

// ===== Multi-Monitor API =====

std::vector<ScreenInfo> get_screens() {
    std::vector<ScreenInfo> screens;
    if (is_simulation_mode()) {
        ScreenInfo primary;
        primary.id = 0;
        primary.name = "Simulated Primary Monitor";
        primary.bounds = {0, 0, 1920, 1080};
        primary.work_area = {0, 0, 1920, 1040};
        primary.is_primary = true;
        primary.dpi_scale = 100;
        primary.color_depth = 32;
        screens.push_back(primary);

        ScreenInfo secondary;
        secondary.id = 1;
        secondary.name = "Simulated Secondary Monitor";
        secondary.bounds = {1920, 0, 1920, 1080};
        secondary.work_area = {1920, 0, 1920, 1040};
        secondary.is_primary = false;
        secondary.dpi_scale = 100;
        secondary.color_depth = 32;
        screens.push_back(secondary);
        return screens;
    }
#if defined(_WIN32)
    struct MonEnumData {
        std::vector<ScreenInfo> screens;
    };
    MonEnumData data;
    EnumDisplayMonitors(nullptr, nullptr, [](HMONITOR hMon, HDC, LPRECT lprcMonitor, LPARAM lParam) -> BOOL {
        auto* data = reinterpret_cast<MonEnumData*>(lParam);
        MONITORINFOEXA mi;
        mi.cbSize = sizeof(mi);
        GetMonitorInfoA(hMon, &mi);
        ScreenInfo si;
        si.id = static_cast<int>(data->screens.size());
        si.name = mi.szDevice;
        si.bounds = {mi.rcMonitor.left, mi.rcMonitor.top,
                     mi.rcMonitor.right - mi.rcMonitor.left,
                     mi.rcMonitor.bottom - mi.rcMonitor.top};
        si.work_area = {mi.rcWork.left, mi.rcWork.top,
                        mi.rcWork.right - mi.rcWork.left,
                        mi.rcWork.bottom - mi.rcWork.top};
        si.is_primary = (mi.dwFlags & MONITORINFOF_PRIMARY) != 0;
        si.dpi_scale = 100;
        si.color_depth = 32;
        data->screens.push_back(si);
        return TRUE;
    }, reinterpret_cast<LPARAM>(&data));
    return data.screens;
#else
    ScreenInfo primary;
    primary.id = 0;
    primary.name = "Default Screen";
    primary.bounds = {0, 0, 1920, 1080};
    primary.work_area = {0, 0, 1920, 1040};
    primary.is_primary = true;
    screens.push_back(primary);
    return screens;
#endif
}

ScreenInfo get_primary_screen() {
    auto screens = get_screens();
    for (const auto& s : screens) {
        if (s.is_primary) return s;
    }
    if (!screens.empty()) return screens[0];
    return ScreenInfo{};
}

ScreenInfo get_screen_at(int x, int y) {
    auto screens = get_screens();
    for (const auto& s : screens) {
        if (s.bounds.contains(x, y)) return s;
    }
    return get_primary_screen();
}

ScreenInfo get_screen_for_window(const std::string& window_id) {
    auto windows = list_windows();
    for (const auto& w : windows) {
        if (w.id == window_id) {
            return get_screen_at(w.bounds.center_x(), w.bounds.center_y());
        }
    }
    return get_primary_screen();
}

std::string screens_to_json(const std::vector<ScreenInfo>& screens) {
    std::ostringstream ss;
    ss << "{\"total_screens\":" << screens.size() << ",\"screens\":[";
    for (size_t i = 0; i < screens.size(); i++) {
        if (i > 0) ss << ",";
        ss << screens[i].to_json();
    }
    ss << "]}";
    return ss.str();
}

// ===== Element State API =====

ElementState get_element_state(const std::string& element_id) {
    ElementState state;
    auto elem = get_element(element_id);
    if (elem.id.empty()) return state;
    state.element_id = element_id;
    state.enabled = elem.enabled;
    state.visible = elem.visible;
    state.focused = elem.focused;
    state.selected = elem.selected;
    state.checked = elem.checked;
    state.clickable = elem.is_clickable();
    state.is_container = elem.is_container();
    state.is_text_input = elem.is_text_input();
    state.current_value = elem.text;
    state.current_text = elem.text;
    return state;
}

bool is_element_enabled(const std::string& element_id) {
    auto elem = get_element(element_id);
    if (elem.id.empty()) return false;
    return elem.enabled;
}

bool is_element_visible(const std::string& element_id) {
    auto elem = get_element(element_id);
    if (elem.id.empty()) return false;
    return elem.visible;
}

bool is_element_checked(const std::string& element_id) {
    auto elem = get_element(element_id);
    return elem.checked;
}

bool is_element_focused(const std::string& element_id) {
    auto elem = get_element(element_id);
    return elem.focused;
}

std::string get_element_value(const std::string& element_id) {
    auto elem = get_element(element_id);
    return elem.text;
}

// ===== Advanced Actions API =====

bool scroll_at(int x, int y, int dx, int dy) {
    if (is_simulation_mode()) return true;
#if defined(_WIN32)
    // Move mouse to position first
    INPUT move = {0};
    move.type = INPUT_MOUSE;
    move.mi.dx = (LONG)(x * 65535.0 / GetSystemMetrics(SM_CXSCREEN));
    move.mi.dy = (LONG)(y * 65535.0 / GetSystemMetrics(SM_CYSCREEN));
    move.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE;
    SendInput(1, &move, sizeof(INPUT));
    // Scroll
    INPUT scroll = {0};
    scroll.type = INPUT_MOUSE;
    scroll.mi.dwFlags = MOUSEEVENTF_WHEEL;
    scroll.mi.mouseData = static_cast<DWORD>(-dy * WHEEL_DELTA);
    SendInput(1, &scroll, sizeof(INPUT));
    return true;
#else
    return false;
#endif
}

bool scroll_element(const std::string& element_id, int dx, int dy) {
    auto e = get_element(element_id);
    if (e.id.empty()) return false;
    return scroll_at(e.bounds.center_x(), e.bounds.center_y(), dx, dy);
}

bool hover_at(int x, int y) {
    if (is_simulation_mode()) return true;
#if defined(_WIN32)
    INPUT input = {0};
    input.type = INPUT_MOUSE;
    input.mi.dx = (LONG)(x * 65535.0 / GetSystemMetrics(SM_CXSCREEN));
    input.mi.dy = (LONG)(y * 65535.0 / GetSystemMetrics(SM_CYSCREEN));
    input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE;
    SendInput(1, &input, sizeof(INPUT));
    return true;
#else
    return false;
#endif
}

bool hover_element(const std::string& element_id) {
    auto e = get_element(element_id);
    if (e.id.empty()) return false;
    return hover_at(e.bounds.center_x(), e.bounds.center_y());
}

bool drag(int from_x, int from_y, int to_x, int to_y) {
    if (is_simulation_mode()) return true;
#if defined(_WIN32)
    // Move to start
    INPUT input = {0};
    input.type = INPUT_MOUSE;
    input.mi.dx = (LONG)(from_x * 65535.0 / GetSystemMetrics(SM_CXSCREEN));
    input.mi.dy = (LONG)(from_y * 65535.0 / GetSystemMetrics(SM_CYSCREEN));
    input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE;
    SendInput(1, &input, sizeof(INPUT));
    // Mouse down
    ZeroMemory(&input, sizeof(INPUT));
    input.type = INPUT_MOUSE;
    input.mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
    SendInput(1, &input, sizeof(INPUT));
    // Move to end
    ZeroMemory(&input, sizeof(INPUT));
    input.type = INPUT_MOUSE;
    input.mi.dx = (LONG)(to_x * 65535.0 / GetSystemMetrics(SM_CXSCREEN));
    input.mi.dy = (LONG)(to_y * 65535.0 / GetSystemMetrics(SM_CYSCREEN));
    input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE;
    SendInput(1, &input, sizeof(INPUT));
    // Mouse up
    ZeroMemory(&input, sizeof(INPUT));
    input.type = INPUT_MOUSE;
    input.mi.dwFlags = MOUSEEVENTF_LEFTUP;
    SendInput(1, &input, sizeof(INPUT));
    return true;
#else
    return false;
#endif
}

bool drag_element_to(const std::string& element_id, int to_x, int to_y) {
    auto e = get_element(element_id);
    if (e.id.empty()) return false;
    return drag(e.bounds.center_x(), e.bounds.center_y(), to_x, to_y);
}

bool send_key_combination(int ctrl_or_cmd, int key_code, bool shift, bool alt) {
    if (is_simulation_mode()) return true;
#if defined(_WIN32)
    std::vector<INPUT> inputs;
    // Press modifiers
    if (ctrl_or_cmd == 1) { // Ctrl
        INPUT inp = {0};
        inp.type = INPUT_KEYBOARD;
        inp.ki.wVk = VK_CONTROL;
        inputs.push_back(inp);
    }
    if (shift) {
        INPUT inp = {0};
        inp.type = INPUT_KEYBOARD;
        inp.ki.wVk = VK_SHIFT;
        inputs.push_back(inp);
    }
    if (alt) {
        INPUT inp = {0};
        inp.type = INPUT_KEYBOARD;
        inp.ki.wVk = VK_MENU;
        inputs.push_back(inp);
    }
    // Press key
    INPUT key_inp = {0};
    key_inp.type = INPUT_KEYBOARD;
    key_inp.ki.wVk = static_cast<WORD>(key_code);
    inputs.push_back(key_inp);
    // Release key
    key_inp.ki.dwFlags = KEYEVENTF_KEYUP;
    inputs.push_back(key_inp);
    // Release modifiers
    if (alt) {
        INPUT inp = {0};
        inp.type = INPUT_KEYBOARD;
        inp.ki.wVk = VK_MENU;
        inp.ki.dwFlags = KEYEVENTF_KEYUP;
        inputs.push_back(inp);
    }
    if (shift) {
        INPUT inp = {0};
        inp.type = INPUT_KEYBOARD;
        inp.ki.wVk = VK_SHIFT;
        inp.ki.dwFlags = KEYEVENTF_KEYUP;
        inputs.push_back(inp);
    }
    if (ctrl_or_cmd == 1) {
        INPUT inp = {0};
        inp.type = INPUT_KEYBOARD;
        inp.ki.wVk = VK_CONTROL;
        inp.ki.dwFlags = KEYEVENTF_KEYUP;
        inputs.push_back(inp);
    }
    SendInput(static_cast<UINT>(inputs.size()), inputs.data(), sizeof(INPUT));
    return true;
#else
    return false;
#endif
}

bool send_shortcut(const std::string& shortcut_name) {
    auto shortcut = get_shortcut(shortcut_name);
    if (shortcut.key_code == 0) return false;
    return send_key_combination(shortcut.ctrl_or_cmd, shortcut.key_code, shortcut.shift, shortcut.alt);
}

// ===== Wait/Poll API =====

UIElement wait_for_element(const std::string& query, int timeout_ms,
                           const std::string& type_filter, const std::string& window_id) {
    if (is_simulation_mode()) {
        auto results = search_elements(query, type_filter, window_id, 1);
        if (!results.empty()) return results[0].element;
        return UIElement{};
    }
    int elapsed = 0;
    int interval = 100;
    while (elapsed < timeout_ms) {
        auto results = search_elements(query, type_filter, window_id, 1);
        if (!results.empty()) return results[0].element;
        elapsed += interval;
    }
    return UIElement{};
}

WindowInfo wait_for_window(const std::string& title_contains, int timeout_ms) {
    if (is_simulation_mode()) {
        auto windows = list_windows();
        for (const auto& w : windows) {
            if (contains_ci(w.title, title_contains)) return w;
        }
        return WindowInfo{};
    }
    int elapsed = 0;
    int interval = 100;
    while (elapsed < timeout_ms) {
        auto windows = list_windows();
        for (const auto& w : windows) {
            if (contains_ci(w.title, title_contains)) return w;
        }
        elapsed += interval;
    }
    return WindowInfo{};
}

bool wait_for_element_enabled(const std::string& element_id, int timeout_ms) {
    if (is_simulation_mode()) return is_element_enabled(element_id);
    int elapsed = 0;
    int interval = 100;
    while (elapsed < timeout_ms) {
        if (is_element_enabled(element_id)) return true;
        elapsed += interval;
    }
    return false;
}

bool wait_for_element_visible(const std::string& element_id, int timeout_ms) {
    if (is_simulation_mode()) return is_element_visible(element_id);
    int elapsed = 0;
    int interval = 100;
    while (elapsed < timeout_ms) {
        if (is_element_visible(element_id)) return true;
        elapsed += interval;
    }
    return false;
}

// ===== Element Path / Selector API =====

std::vector<UIElement> find_by_path(const std::string& path) {
    std::vector<UIElement> results;
    if (path.empty()) return results;

    // Split path by '/' or '>'
    std::vector<std::string> parts;
    std::string current;
    for (char c : path) {
        if (c == '>' || c == '/') {
            if (!current.empty()) parts.push_back(current);
            current.clear();
        } else {
            current += c;
        }
    }
    if (!current.empty()) parts.push_back(current);
    if (parts.empty()) return results;

    auto all = get_all_elements();

    // First part: match window_id, element id, or text
    std::vector<UIElement> candidates;
    for (const auto& e : all) {
        if (contains_ci(e.window_id, parts[0]) ||
            contains_ci(e.id, parts[0]) ||
            contains_ci(e.text, parts[0])) {
            candidates.push_back(e);
        }
    }

    // For each subsequent part, find children of current candidates matching the part
    for (size_t i = 1; i < parts.size(); i++) {
        std::vector<UIElement> next_candidates;
        for (const auto& parent : candidates) {
            for (const auto& e : all) {
                bool match = false;
                // Match via parent_id chain
                if (e.parent_id == parent.id &&
                    (contains_ci(e.text, parts[i]) || contains_ci(e.id, parts[i]) ||
                     contains_ci(e.type_string(), parts[i]))) {
                    match = true;
                }
                // Match via window_id when parent was matched by window_id (root-level elements)
                if (!match && parent.window_id == e.window_id &&
                    contains_ci(parent.window_id, parts[0]) &&
                    (contains_ci(e.id, parts[i]) || contains_ci(e.text, parts[i]))) {
                    match = true;
                }
                if (match) {
                    next_candidates.push_back(e);
                }
            }
        }
        // Deduplicate
        std::set<std::string> seen;
        std::vector<UIElement> deduped;
        for (const auto& e : next_candidates) {
            if (seen.find(e.id) == seen.end()) {
                seen.insert(e.id);
                deduped.push_back(e);
            }
        }
        candidates = std::move(deduped);
        if (candidates.empty()) break;
    }

    return candidates;
}

std::string get_element_path(const std::string& element_id) {
    std::vector<std::string> parts;
    std::string current_id = element_id;

    while (!current_id.empty()) {
        auto elem = get_element(current_id);
        if (elem.id.empty()) break;
        std::string label = elem.text.empty() ? elem.id : elem.text;
        parts.insert(parts.begin(), label);
        current_id = elem.parent_id;
    }

    std::string path;
    for (size_t i = 0; i < parts.size(); i++) {
        if (i > 0) path += "/";
        path += parts[i];
    }
    return path;
}

// ===== Batch Search API =====

std::vector<std::vector<ElementSearchResult>> batch_search(const std::vector<BatchSearchQuery>& queries) {
    std::vector<std::vector<ElementSearchResult>> results;
    for (const auto& q : queries) {
        results.push_back(search_elements(q.text, q.type_filter, q.window_id, q.top_k));
    }
    return results;
}

// ===== Window Management API =====

bool focus_window(const std::string& window_id) {
    if (is_simulation_mode()) {
        for (const auto& w : g_sim_windows) if (w.id == window_id) return true;
        return false;
    }
#if defined(_WIN32)
    try {
        HWND hwnd = reinterpret_cast<HWND>(std::stoull(window_id));
        if (IsWindow(hwnd)) {
            SetForegroundWindow(hwnd);
            return true;
        }
    } catch (...) {}
    return false;
#else
    return false;
#endif
}

bool minimize_window(const std::string& window_id) {
    if (is_simulation_mode()) {
        for (const auto& w : g_sim_windows) if (w.id == window_id) return true;
        return false;
    }
#if defined(_WIN32)
    try {
        HWND hwnd = reinterpret_cast<HWND>(std::stoull(window_id));
        if (IsWindow(hwnd)) {
            ShowWindow(hwnd, SW_MINIMIZE);
            return true;
        }
    } catch (...) {}
    return false;
#else
    return false;
#endif
}

bool maximize_window(const std::string& window_id) {
    if (is_simulation_mode()) {
        for (const auto& w : g_sim_windows) if (w.id == window_id) return true;
        return false;
    }
#if defined(_WIN32)
    try {
        HWND hwnd = reinterpret_cast<HWND>(std::stoull(window_id));
        if (IsWindow(hwnd)) {
            ShowWindow(hwnd, SW_MAXIMIZE);
            return true;
        }
    } catch (...) {}
    return false;
#else
    return false;
#endif
}

bool restore_window(const std::string& window_id) {
    if (is_simulation_mode()) {
        for (const auto& w : g_sim_windows) if (w.id == window_id) return true;
        return false;
    }
#if defined(_WIN32)
    try {
        HWND hwnd = reinterpret_cast<HWND>(std::stoull(window_id));
        if (IsWindow(hwnd)) {
            ShowWindow(hwnd, SW_RESTORE);
            return true;
        }
    } catch (...) {}
    return false;
#else
    return false;
#endif
}

bool close_window(const std::string& window_id) {
    if (is_simulation_mode()) {
        for (const auto& w : g_sim_windows) if (w.id == window_id) return true;
        return false;
    }
#if defined(_WIN32)
    try {
        HWND hwnd = reinterpret_cast<HWND>(std::stoull(window_id));
        if (IsWindow(hwnd)) {
            PostMessageA(hwnd, WM_CLOSE, 0, 0);
            return true;
        }
    } catch (...) {}
    return false;
#else
    return false;
#endif
}

bool move_window(const std::string& window_id, int x, int y) {
    if (is_simulation_mode()) {
        for (const auto& w : g_sim_windows) if (w.id == window_id) return true;
        return false;
    }
#if defined(_WIN32)
    try {
        HWND hwnd = reinterpret_cast<HWND>(std::stoull(window_id));
        if (IsWindow(hwnd)) {
            RECT rect;
            GetWindowRect(hwnd, &rect);
            int w = rect.right - rect.left;
            int h = rect.bottom - rect.top;
            SetWindowPos(hwnd, nullptr, x, y, w, h, SWP_NOZORDER);
            return true;
        }
    } catch (...) {}
    return false;
#else
    return false;
#endif
}

bool resize_window(const std::string& window_id, int width, int height) {
    if (is_simulation_mode()) {
        for (const auto& w : g_sim_windows) if (w.id == window_id) return true;
        return false;
    }
#if defined(_WIN32)
    try {
        HWND hwnd = reinterpret_cast<HWND>(std::stoull(window_id));
        if (IsWindow(hwnd)) {
            RECT rect;
            GetWindowRect(hwnd, &rect);
            SetWindowPos(hwnd, nullptr, rect.left, rect.top, width, height, SWP_NOZORDER);
            return true;
        }
    } catch (...) {}
    return false;
#else
    return false;
#endif
}

// ===== Nearest Element API =====

double distance(int x1, int y1, int x2, int y2) {
    int dx = x2 - x1;
    int dy = y2 - y1;
    return std::sqrt(static_cast<double>(dx * dx + dy * dy));
}

UIElement find_nearest_clickable(int x, int y, int max_distance) {
    auto all = get_all_elements();
    UIElement best;
    double best_dist = static_cast<double>(max_distance);

    for (const auto& e : all) {
        if (!e.is_clickable() || !e.enabled || !e.visible) continue;
        double d = distance(x, y, e.bounds.center_x(), e.bounds.center_y());
        if (d < best_dist) {
            best = e;
            best_dist = d;
        }
    }
    return best;
}

UIElement find_nearest_by_type(int x, int y, ElementType type, int max_distance) {
    auto all = get_all_elements();
    UIElement best;
    double best_dist = static_cast<double>(max_distance);

    for (const auto& e : all) {
        if (e.type != type || !e.visible) continue;
        double d = distance(x, y, e.bounds.center_x(), e.bounds.center_y());
        if (d < best_dist) {
            best = e;
            best_dist = d;
        }
    }
    return best;
}

UIElement find_nearest_by_text(int x, int y, const std::string& text, int max_distance) {
    auto all = get_all_elements();
    UIElement best;
    double best_dist = static_cast<double>(max_distance);

    for (const auto& e : all) {
        if (!e.visible) continue;
        if (!contains_ci(e.text, text)) continue;
        double d = distance(x, y, e.bounds.center_x(), e.bounds.center_y());
        if (d < best_dist) {
            best = e;
            best_dist = d;
        }
    }
    return best;
}

// ===== Export/Import API =====

std::string export_element_map() {
    auto windows = list_windows();
    auto elements = get_all_elements();
    auto screens = get_screens();

    std::ostringstream ss;
    ss << "{\"version\":\"1.0\",\"platform\":\"" << platform_to_string(get_current_platform()) << "\",";
    ss << "\"exported_at\":\"" << "sim" << "\",";
    ss << "\"screens\":" << screens_to_json(screens) << ",";
    ss << "\"windows\":" << windows_to_json(windows) << ",";
    ss << "\"elements\":" << elements_to_json(elements);
    ss << "}";
    return ss.str();
}

size_t import_element_map(const std::string& json) {
    // Simple count - in production would parse JSON
    size_t count = 0;
    size_t pos = 0;
    while ((pos = json.find("\"id\":", pos)) != std::string::npos) {
        count++;
        pos += 5;
    }
    return count;
}

bool save_element_map(const std::string& filepath) {
#if defined(_WIN32)
    std::string data = export_element_map();
    FILE* f = nullptr;
    fopen_s(&f, filepath.c_str(), "w");
    if (!f) return false;
    fputs(data.c_str(), f);
    fclose(f);
    return true;
#else
    std::string data = export_element_map();
    FILE* f = fopen(filepath.c_str(), "w");
    if (!f) return false;
    fputs(data.c_str(), f);
    fclose(f);
    return true;
#endif
}

bool load_element_map(const std::string& filepath) {
#if defined(_WIN32)
    FILE* f = nullptr;
    fopen_s(&f, filepath.c_str(), "r");
    if (!f) return false;
    std::string data;
    char buf[4096];
    while (fgets(buf, sizeof(buf), f)) data += buf;
    fclose(f);
    return import_element_map(data) > 0;
#else
    FILE* f = fopen(filepath.c_str(), "r");
    if (!f) return false;
    std::string data;
    char buf[4096];
    while (fgets(buf, sizeof(buf), f)) data += buf;
    fclose(f);
    return import_element_map(data) > 0;
#endif
}

// ===== Keyboard Shortcuts API =====

static std::vector<ShortcutMapping> build_shortcut_table() {
    std::vector<ShortcutMapping> shortcuts;
#if defined(_WIN32)
    auto add = [&](const std::string& name, const std::string& desc, int key, const std::string& key_name,
                   bool shift = false, bool alt = false) {
        ShortcutMapping s;
        s.name = name;
        s.description = desc;
        s.ctrl_or_cmd = 1; // Ctrl on Windows
        s.key_code = key;
        s.key_name = key_name;
        s.shift = shift;
        s.alt = alt;
        shortcuts.push_back(s);
    };
    add("copy", "Copy to clipboard", 'C', "C");
    add("paste", "Paste from clipboard", 'V', "V");
    add("cut", "Cut to clipboard", 'X', "X");
    add("undo", "Undo last action", 'Z', "Z");
    add("redo", "Redo last action", 'Y', "Y");
    add("save", "Save file", 'S', "S");
    add("save_all", "Save all files", 'S', "S", true);
    add("open", "Open file", 'O', "O");
    add("new", "New file", 'N', "N");
    add("print", "Print", 'P', "P");
    add("find", "Find", 'F', "F");
    add("find_replace", "Find and replace", 'H', "H");
    add("select_all", "Select all", 'A', "A");
    add("close", "Close window", 'W', "W");
    add("switch_app", "Switch application", VK_TAB, "Tab", false, true);
    add("lock_screen", "Lock screen", 'L', "L", false, true);
    add("task_manager", "Task manager", VK_ESCAPE, "Esc", false, true);
    add("show_desktop", "Show desktop", 'D', "D", false, true);
    add("screenshot", "Screenshot (entire screen)", VK_SNAPSHOT, "PrtScn", false, false);
    add("screenshot_region", "Screenshot (region)", VK_SNAPSHOT, "PrtScn", true, false);
    add("minimize_all", "Minimize all windows", 'M', "M", false, true);
    add("run_dialog", "Run dialog", 'R', "R", false, true);
    add("explorer", "Open file explorer", 'E', "E", false, true);
    add("settings", "Open settings", 'I', "I", false, true);
    add("search", "Search", 'S', "S", false, true);
    add("fullscreen", "Toggle fullscreen", VK_F11, "F11", false, false);
    add("refresh", "Refresh", VK_F5, "F5", false, false);
    add("zoom_in", "Zoom in", '=', "+", true);
    add("zoom_out", "Zoom out", '-', "-", true);
    add("reset_zoom", "Reset zoom", '0', "0", true);
    add("tab_new", "New tab", 'T', "T");
    add("tab_close", "Close tab", 'W', "W");
    add("tab_next", "Next tab", VK_TAB, "Tab", true);
    add("tab_prev", "Previous tab", VK_TAB, "Tab", true, true);
    add("go_back", "Go back", VK_LEFT, "Left", false, true);
    add("go_forward", "Go forward", VK_RIGHT, "Right", false, true);
    add("home", "Go to start of line", VK_HOME, "Home");
    add("end", "Go to end of line", VK_END, "End");
    add("page_up", "Page up", VK_PRIOR, "PageUp");
    add("page_down", "Page down", VK_NEXT, "PageDown");
    add("delete", "Delete", VK_DELETE, "Delete");
    add("rename", "Rename", 'F', "F", true);
    add("properties", "Properties", VK_RETURN, "Enter", false, true);
#else
    // Mac/Linux: similar but with Cmd on Mac
    auto add = [&](const std::string& name, const std::string& desc, int key, const std::string& key_name,
                   bool shift = false, bool alt = false) {
        ShortcutMapping s;
        s.name = name;
        s.description = desc;
#if defined(__APPLE__)
        s.ctrl_or_cmd = 2; // Cmd on Mac
#else
        s.ctrl_or_cmd = 1; // Ctrl on Linux
#endif
        s.key_code = key;
        s.key_name = key_name;
        s.shift = shift;
        s.alt = alt;
        shortcuts.push_back(s);
    };
    add("copy", "Copy to clipboard", 'C', "C");
    add("paste", "Paste from clipboard", 'V', "V");
    add("cut", "Cut to clipboard", 'X', "X");
    add("undo", "Undo last action", 'Z', "Z");
    add("redo", "Redo last action", 'Z', "Z", true);
    add("save", "Save file", 'S', "S");
    add("open", "Open file", 'O', "O");
    add("new", "New file", 'N', "N");
    add("find", "Find", 'F', "F");
    add("select_all", "Select all", 'A', "A");
    add("close", "Close window", 'W', "W");
    add("fullscreen", "Toggle fullscreen", 0x7A, "F11");
    add("refresh", "Refresh", 0x7E, "F5");
    add("delete", "Delete", 0x75, "Delete");
    add("screenshot", "Screenshot", 0x1B, "Esc", false, true);
#endif
    return shortcuts;
}

std::vector<ShortcutMapping> get_all_shortcuts() {
    return build_shortcut_table();
}

ShortcutMapping get_shortcut(const std::string& name) {
    auto shortcuts = get_all_shortcuts();
    for (const auto& s : shortcuts) {
        if (s.name == name) return s;
    }
    return ShortcutMapping{};
}

std::string shortcuts_to_json() {
    auto shortcuts = get_all_shortcuts();
    std::ostringstream ss;
    ss << "{\"total_shortcuts\":" << shortcuts.size() << ",\"shortcuts\":[";
    for (size_t i = 0; i < shortcuts.size(); i++) {
        if (i > 0) ss << ",";
        ss << shortcuts[i].to_json();
    }
    ss << "]}";
    return ss.str();
}

// ===== Element Regions API =====

std::vector<ElementRegion> detect_regions(const std::string& window_id) {
    std::vector<ElementRegion> regions;
    auto elements = get_elements(window_id);
    auto windows = list_windows();

    WindowInfo win;
    for (const auto& w : windows) {
        if (w.id == window_id) { win = w; break; }
    }
    if (win.id.empty()) return regions;

    int win_x = win.bounds.x;
    int win_y = win.bounds.y;
    int win_w = win.bounds.width;
    int win_h = win.bounds.height;

    // Detect header/navigation bar region (top ~10% of window)
    ElementRegion header;
    header.name = "header";
    header.window_id = window_id;
    header.bounds = {win_x, win_y, win_w, std::max(40, win_h / 10)};
    header.region_type = "header";
    for (const auto& e : elements) {
        if (e.bounds.y < win_y + header.bounds.height) {
            header.element_ids.push_back(e.id);
        }
    }
    regions.push_back(header);

    // Detect footer/status bar region (bottom ~8% of window)
    ElementRegion footer;
    footer.name = "footer";
    footer.window_id = window_id;
    int footer_h = std::max(25, win_h / 12);
    footer.bounds = {win_x, win_y + win_h - footer_h, win_w, footer_h};
    footer.region_type = "footer";
    for (const auto& e : elements) {
        if (e.bounds.bottom() > win_y + win_h - footer_h) {
            footer.element_ids.push_back(e.id);
        }
    }
    regions.push_back(footer);

    // Detect toolbar region (below header, ~6% of window)
    ElementRegion toolbar;
    toolbar.name = "toolbar";
    toolbar.window_id = window_id;
    int tb_y = win_y + header.bounds.height;
    int tb_h = std::max(30, win_h / 15);
    toolbar.bounds = {win_x, tb_y, win_w, tb_h};
    toolbar.region_type = "toolbar";
    for (const auto& e : elements) {
        if (e.bounds.y >= tb_y && e.bounds.bottom() <= tb_y + tb_h + 10) {
            toolbar.element_ids.push_back(e.id);
        }
    }
    regions.push_back(toolbar);

    // Detect content region (between toolbar and footer)
    ElementRegion content;
    content.name = "content";
    content.window_id = window_id;
    int content_y = tb_y + tb_h;
    int content_h = (win_y + win_h - footer_h) - content_y;
    content.bounds = {win_x, content_y, win_w, content_h};
    content.region_type = "content";
    for (const auto& e : elements) {
        if (e.bounds.y >= content_y && e.bounds.bottom() <= win_y + win_h - footer_h) {
            content.element_ids.push_back(e.id);
        }
    }
    regions.push_back(content);

    // Detect sidebar (left ~20% of window, if elements exist there)
    ElementRegion sidebar;
    sidebar.name = "sidebar";
    sidebar.window_id = window_id;
    int side_w = win_w / 5;
    sidebar.bounds = {win_x, win_y + header.bounds.height, side_w, win_h - header.bounds.height - footer_h};
    sidebar.region_type = "sidebar";
    for (const auto& e : elements) {
        if (e.bounds.right() <= win_x + side_w && e.bounds.y > win_y + header.bounds.height) {
            sidebar.element_ids.push_back(e.id);
        }
    }
    if (!sidebar.element_ids.empty()) {
        regions.push_back(sidebar);
    }

    return regions;
}

std::vector<UIElement> get_elements_in_region(const std::string& window_id, const std::string& region_type) {
    auto regions = detect_regions(window_id);
    for (const auto& r : regions) {
        if (r.region_type == region_type) {
            std::vector<UIElement> result;
            auto all = get_elements(window_id);
            for (const auto& id : r.element_ids) {
                for (const auto& e : all) {
                    if (e.id == id) {
                        result.push_back(e);
                        break;
                    }
                }
            }
            return result;
        }
    }
    return {};
}

std::string regions_to_json(const std::vector<ElementRegion>& regions) {
    std::ostringstream ss;
    ss << "{\"total_regions\":" << regions.size() << ",\"regions\":[";
    for (size_t i = 0; i < regions.size(); i++) {
        if (i > 0) ss << ",";
        ss << regions[i].to_json();
    }
    ss << "]}";
    return ss.str();
}

// ===== Change Detection API =====

std::string snapshot_elements() {
    auto elements = get_all_elements();
    std::ostringstream ss;
    ss << "{\"element_count\":" << elements.size() << ",\"elements\":[";
    for (size_t i = 0; i < elements.size(); i++) {
        if (i > 0) ss << ",";
        ss << "{\"id\":\"" << elements[i].id << "\",";
        ss << "\"text\":\"" << elements[i].text << "\",";
        ss << "\"enabled\":" << (elements[i].enabled ? "true" : "false") << ",";
        ss << "\"visible\":" << (elements[i].visible ? "true" : "false") << ",";
        ss << "\"checked\":" << (elements[i].checked ? "true" : "false") << ",";
        ss << "\"focused\":" << (elements[i].focused ? "true" : "false") << "}";
    }
    ss << "]}";
    return ss.str();
}

std::vector<ElementChange> compare_snapshots(const std::string& old_snapshot, const std::string& new_snapshot) {
    std::vector<ElementChange> changes;

    // Simple comparison: count elements and find differences
    int old_count = json_get_int_helper(old_snapshot, "element_count");
    int new_count = json_get_int_helper(new_snapshot, "element_count");

    if (old_count != new_count) {
        ElementChange change;
        change.element_id = "__global__";
        change.change_type = "count_changed";
        change.old_value = std::to_string(old_count);
        change.new_value = std::to_string(new_count);
        changes.push_back(change);
    }

    // Find element text changes by simple string search
    // This is a simplified comparison
    auto extract_elements = [](const std::string& snap) {
        std::vector<std::pair<std::string, std::string>> elems;
        size_t pos = 0;
        while ((pos = snap.find("\"id\":\"", pos)) != std::string::npos) {
            pos += 6;
            size_t end = snap.find("\"", pos);
            if (end == std::string::npos) break;
            std::string id = snap.substr(pos, end - pos);

            // Find text for this element
            size_t text_pos = snap.find("\"text\":\"", end);
            if (text_pos != std::string::npos && text_pos < snap.find("\"id\":\"", end)) {
                text_pos += 8;
                size_t text_end = snap.find("\"", text_pos);
                if (text_end != std::string::npos) {
                    std::string text = snap.substr(text_pos, text_end - text_pos);
                    elems.push_back({id, text});
                }
            }
            pos = end;
        }
        return elems;
    };

    auto old_elems = extract_elements(old_snapshot);
    auto new_elems = extract_elements(new_snapshot);

    // Find added elements
    for (const auto& [nid, ntext] : new_elems) {
        bool found = false;
        for (const auto& [oid, otext] : old_elems) {
            if (oid == nid) { found = true; break; }
        }
        if (!found) {
            ElementChange change;
            change.element_id = nid;
            change.change_type = "added";
            change.old_value = "";
            change.new_value = ntext;
            changes.push_back(change);
        }
    }

    // Find removed elements
    for (const auto& [oid, otext] : old_elems) {
        bool found = false;
        for (const auto& [nid, ntext] : new_elems) {
            if (nid == oid) { found = true; break; }
        }
        if (!found) {
            ElementChange change;
            change.element_id = oid;
            change.change_type = "removed";
            change.old_value = otext;
            change.new_value = "";
            changes.push_back(change);
        }
    }

    // Find text changes
    for (const auto& [oid, otext] : old_elems) {
        for (const auto& [nid, ntext] : new_elems) {
            if (oid == nid && otext != ntext) {
                ElementChange change;
                change.element_id = nid;
                change.change_type = "text_changed";
                change.old_value = otext;
                change.new_value = ntext;
                changes.push_back(change);
            }
        }
    }

    return changes;
}

std::string changes_to_json(const std::vector<ElementChange>& changes) {
    std::ostringstream ss;
    ss << "{\"total_changes\":" << changes.size() << ",\"changes\":[";
    for (size_t i = 0; i < changes.size(); i++) {
        if (i > 0) ss << ",";
        ss << "{\"element_id\":\"" << changes[i].element_id << "\",";
        ss << "\"change_type\":\"" << changes[i].change_type << "\",";
        ss << "\"old_value\":\"" << changes[i].old_value << "\",";
        ss << "\"new_value\":\"" << changes[i].new_value << "\"}";
    }
    ss << "]}";
    return ss.str();
}

// ===== Highlight API =====

bool highlight_element(const std::string& element_id, int duration_ms) {
    if (is_simulation_mode()) return true;
    auto e = get_element(element_id);
    if (e.id.empty()) return false;
    return highlight_region(e.bounds.x, e.bounds.y, e.bounds.width, e.bounds.height, duration_ms);
}

bool highlight_region(int x, int y, int width, int height, int duration_ms) {
    if (is_simulation_mode()) return true;
#if defined(_WIN32)
    // Create a transparent topmost window as highlight overlay
    HWND hwnd = CreateWindowExA(
        WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE,
        "STATIC", "",
        WS_POPUP,
        x, y, width, height,
        nullptr, nullptr, GetModuleHandle(nullptr), nullptr);
    if (!hwnd) return false;
    // Set background color to red
    SetLayeredWindowAttributes(hwnd, RGB(255, 0, 0), 128, LWA_COLORKEY | LWA_ALPHA);
    ShowWindow(hwnd, SW_SHOWNOACTIVATE);
    // Set a timer to destroy it
    SetTimer(hwnd, 1, duration_ms, [](HWND hw, UINT, UINT_PTR id, DWORD) {
        KillTimer(hw, id);
        DestroyWindow(hw);
    });
    return true;
#else
    return false;
#endif
}

bool clear_highlights() {
    if (is_simulation_mode()) return true;
    // Highlights auto-destroy via timer, nothing to do
    return true;
}

} // namespace uilocator
