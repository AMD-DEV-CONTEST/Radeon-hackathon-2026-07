// filepath: hackathon_ui_operator_distill/native/screenai_core.cpp
// Screen-AI Native Core — Unified C++ implementation
// Used by Phase 3-8 utility classes in pipeline/screenai_pipelines.js
// Build target: ai_pc_operator/data/native/screenai_core.node (Node addon)

#include "screenai_core.h"
#include "verifier_bridge.h"

#include <chrono>
#include <thread>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <vector>
#include <string>
#include <sstream>
#include <iomanip>
#include <algorithm>
#include <set>
#include <unordered_set>
#include <cctype>

#ifdef _WIN32
    #include <windows.h>
    #include <psapi.h>
    #include <iphlpapi.h>
    #include <tlhelp32.h>
    #pragma comment(lib, "psapi.lib")
    #pragma comment(lib, "iphlpapi.lib")
#else
    #include <unistd.h>
    #include <sys/statvfs.h>
    #include <sys/stat.h>
    #include <dirent.h>
    #include <fstream>
    #if defined(__APPLE__)
        #include <sys/sysctl.h>
        #include <mach/mach.h>
    #else
        #include <sys/sysinfo.h>
    #endif
#endif

namespace screenai {

// ============================================================================
// Phase 3 — Execution Runtime
// ============================================================================
namespace runtime {

int64_t monotonic_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()
    ).count();
}

void sleep_ms(int ms) {
    if (ms <= 0) return;
    std::this_thread::sleep_for(std::chrono::milliseconds(ms));
}

} // namespace runtime

// ============================================================================
// Phase 4 — Context Engine
// ============================================================================
namespace context {

#ifdef _WIN32
std::vector<ProcessInfo> enumerate_processes(int32_t max_count) {
    std::vector<ProcessInfo> result;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return result;
    PROCESSENTRY32 entry;
    entry.dwSize = sizeof(entry);
    if (Process32First(snap, &entry)) {
        do {
            ProcessInfo info;
            info.pid = entry.th32ProcessID;
            info.name = entry.szExeFile;
            info.cpu_percent = 0.0;
            info.memory_bytes = 0;
            // Try to get memory info
            HANDLE proc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, entry.th32ProcessID);
            if (proc) {
                PROCESS_MEMORY_COUNTERS pmc;
                if (GetProcessMemoryInfo(proc, &pmc, sizeof(pmc))) {
                    info.memory_bytes = (int64_t)pmc.WorkingSetSize;
                }
                CloseHandle(proc);
            }
            result.push_back(info);
            if ((int32_t)result.size() >= max_count) break;
        } while (Process32Next(snap, &entry));
    }
    CloseHandle(snap);
    return result;
}

std::vector<WindowInfo> enumerate_windows(int32_t max_count) {
    std::vector<WindowInfo> result;
    HWND foreground = GetForegroundWindow();
    // Best-effort: enumerate top-level windows
    struct EnumData {
        std::vector<WindowInfo>* out;
        int32_t max_count;
    };
    EnumData data{ &result, max_count };
    auto enum_proc = [](HWND hwnd, LPARAM lparam) -> BOOL {
        auto* d = reinterpret_cast<EnumData*>(lparam);
        if (!IsWindowVisible(hwnd)) return TRUE;
        int len = GetWindowTextLengthW(hwnd);
        if (len == 0) return TRUE;
        std::vector<wchar_t> buf(len + 1);
        GetWindowTextW(hwnd, buf.data(), len + 1);
        // Convert wide to UTF-8 (simplified)
        std::string title;
        for (int i = 0; i < len; i++) {
            wchar_t wc = buf[i];
            if (wc < 0x80) title += (char)wc;
            else title += '?';
        }
        WindowInfo info;
        info.handle = (int64_t)hwnd;
        info.title = title;
        info.app = "";
        info.visible = true;
        info.focused = (hwnd == GetForegroundWindow());
        d->out->push_back(info);
        if ((int32_t)d->out->size() >= d->max_count) return FALSE;
        return TRUE;
    };
    EnumWindows(enum_proc, (LPARAM)&data);
    return result;
}

std::string get_focused_window_title() {
    HWND hwnd = GetForegroundWindow();
    if (!hwnd) return "";
    int len = GetWindowTextLengthW(hwnd);
    if (len == 0) return "";
    std::vector<wchar_t> buf(len + 1);
    GetWindowTextW(hwnd, buf.data(), len + 1);
    std::string title;
    for (int i = 0; i < len; i++) {
        wchar_t wc = buf[i];
        if (wc < 0x80) title += (char)wc;
        else title += '?';
    }
    return title;
}
#else
std::vector<ProcessInfo> enumerate_processes(int32_t max_count) {
    std::vector<ProcessInfo> result;
    // Read /proc on Linux; use ps on macOS
    #ifdef __APPLE__
    FILE* pipe = popen("ps -axo pid=,comm=", "r");
    if (!pipe) return result;
    char buf[512];
    while (fgets(buf, sizeof(buf), pipe)) {
        std::string line(buf);
        size_t sp = line.find(' ');
        if (sp == std::string::npos) continue;
        ProcessInfo info;
        info.pid = std::atoi(line.substr(0, sp).c_str());
        info.name = line.substr(sp + 1);
        // trim newline
        while (!info.name.empty() && (info.name.back() == '\n' || info.name.back() == '\r'))
            info.name.pop_back();
        info.cpu_percent = 0.0;
        info.memory_bytes = 0;
        result.push_back(info);
        if ((int32_t)result.size() >= max_count) break;
    }
    pclose(pipe);
    #else
    DIR* dir = opendir("/proc");
    if (!dir) return result;
    struct dirent* ent;
    while ((ent = readdir(dir)) != nullptr) {
        if (ent->d_name[0] < '0' || ent->d_name[0] > '9') continue;
        ProcessInfo info;
        info.pid = std::atoi(ent->d_name);
        std::ifstream comm("/proc/" + std::string(ent->d_name) + "/comm");
        if (comm) {
            std::getline(comm, info.name);
        } else {
            info.name = "unknown";
        }
        info.cpu_percent = 0.0;
        info.memory_bytes = 0;
        std::ifstream status("/proc/" + std::string(ent->d_name) + "/status");
        std::string line;
        while (std::getline(status, line)) {
            if (line.rfind("VmRSS:", 0) == 0) {
                info.memory_bytes = std::atoll(line.c_str() + 6) * 1024;
                break;
            }
        }
        result.push_back(info);
        if ((int32_t)result.size() >= max_count) break;
    }
    closedir(dir);
    #endif
    return result;
}

std::vector<WindowInfo> enumerate_windows(int32_t /*max_count*/) {
    // X11/Wayland enumeration is complex; return empty on non-Windows
    return {};
}

std::string get_focused_window_title() {
    return "";  // Not implemented for non-Windows
}
#endif

} // namespace context

// ============================================================================
// Phase 5 — Intent Engine
// ============================================================================
namespace intent {

std::vector<std::string> tokenize(const std::string& s) {
    std::vector<std::string> tokens;
    std::string current;
    for (char c : s) {
        if (std::isalnum((unsigned char)c)) {
            current += std::tolower((unsigned char)c);
        } else if (!current.empty()) {
            tokens.push_back(current);
            current.clear();
        }
    }
    if (!current.empty()) tokens.push_back(current);
    return tokens;
}

double jaccard_similarity(const std::vector<std::string>& a,
                          const std::vector<std::string>& b) {
    if (a.empty() && b.empty()) return 1.0;
    if (a.empty() || b.empty()) return 0.0;
    std::unordered_set<std::string> sa(a.begin(), a.end());
    std::unordered_set<std::string> sb(b.begin(), b.end());
    size_t intersection = 0;
    for (const auto& t : sa) if (sb.count(t)) intersection++;
    size_t union_size = sa.size() + sb.size() - intersection;
    return union_size == 0 ? 0.0 : (double)intersection / (double)union_size;
}

double string_similarity(const std::string& a, const std::string& b) {
    if (a == b) return 1.0;
    if (a.empty() || b.empty()) return 0.0;
    auto ta = tokenize(a);
    auto tb = tokenize(b);
    double j = jaccard_similarity(ta, tb);
    // Char-level similarity (length-normalized)
    size_t max_len = std::max(a.size(), b.size());
    size_t min_len = std::min(a.size(), b.size());
    double char_sim = (double)min_len / (double)max_len;
    return 0.7 * j + 0.3 * char_sim;
}

std::string normalize_intent(const std::string& s) {
    std::string out;
    out.reserve(s.size());
    bool prev_space = false;
    for (char c : s) {
        if (std::isalnum((unsigned char)c)) {
            out += std::tolower((unsigned char)c);
            prev_space = false;
        } else if (std::isspace((unsigned char)c)) {
            if (!prev_space && !out.empty()) {
                out += ' ';
                prev_space = true;
            }
        }
    }
    while (!out.empty() && out.back() == ' ') out.pop_back();
    return out;
}

} // namespace intent

// ============================================================================
// Phase 6 — Planner
// ============================================================================
namespace planner {

double compute_plan_cost(const std::vector<double>& node_costs) {
    double total = 0.0;
    for (double c : node_costs) total += c;
    return total;
}

double compute_risk_score(const std::vector<int>& risk_levels) {
    if (risk_levels.empty()) return 0.0;
    // Weighted: higher risk levels contribute more
    double total = 0.0;
    double weight_sum = 0.0;
    for (size_t i = 0; i < risk_levels.size(); i++) {
        double w = 1.0 + (double)i * 0.1;  // later nodes slightly more important
        total += risk_levels[i] * w;
        weight_sum += w;
    }
    return weight_sum == 0.0 ? 0.0 : total / weight_sum;
}

bool topological_sort(const std::vector<std::vector<int>>& adj,
                      std::vector<int>& order) {
    size_t n = adj.size();
    std::vector<int> indegree(n, 0);
    for (const auto& neighbors : adj) {
        for (int v : neighbors) {
            if (v >= 0 && v < (int)n) indegree[v]++;
        }
    }
    std::vector<int> queue;
    for (size_t i = 0; i < n; i++) {
        if (indegree[i] == 0) queue.push_back((int)i);
    }
    order.clear();
    while (!queue.empty()) {
        int u = queue.back();
        queue.pop_back();
        order.push_back(u);
        for (int v : adj[u]) {
            if (v >= 0 && v < (int)n) {
                indegree[v]--;
                if (indegree[v] == 0) queue.push_back(v);
            }
        }
    }
    return order.size() == n;
}

int solve_constraint(const std::vector<int>& options,
                     const std::vector<int>& constraints) {
    std::set<int> cset(constraints.begin(), constraints.end());
    for (int opt : options) {
        if (cset.count(opt) == 0) return opt;
    }
    return -1;
}

} // namespace planner

// ============================================================================
// Phase 7 — Observation Engine
// ============================================================================
namespace observation {

#ifdef _WIN32
double get_cpu_percent() {
    // Simplified: use GetSystemTimes for overall CPU
    FILETIME idle, kernel, user;
    if (!GetSystemTimes(&idle, &kernel, &user)) return 0.0;
    auto to_u64 = [](FILETIME ft) -> uint64_t {
        return ((uint64_t)ft.dwHighDateTime << 32) | ft.dwLowDateTime;
    };
    static uint64_t last_idle = 0, last_kernel = 0, last_user = 0;
    uint64_t i = to_u64(idle), k = to_u64(kernel), u = to_u64(user);
    if (last_idle == 0) {
        last_idle = i; last_kernel = k; last_user = u;
        return 0.0;
    }
    uint64_t idle_diff = i - last_idle;
    uint64_t total_diff = (k - last_kernel) + (u - last_user);
    last_idle = i; last_kernel = k; last_user = u;
    if (total_diff == 0) return 0.0;
    return 100.0 * (1.0 - (double)idle_diff / (double)total_diff);
}

void get_memory_usage(int64_t& used_bytes, int64_t& total_bytes) {
    MEMORYSTATUSEX ms;
    ms.dwLength = sizeof(ms);
    if (GlobalMemoryStatusEx(&ms)) {
        total_bytes = (int64_t)ms.ullTotalPhys;
        used_bytes = (int64_t)(ms.ullTotalPhys - ms.ullAvailPhys);
    } else {
        used_bytes = 0; total_bytes = 0;
    }
}

void get_disk_usage(const std::string& path,
                    int64_t& used_bytes, int64_t& total_bytes) {
    ULARGE_INTEGER free_bytes, total, total_free;
    if (GetDiskFreeSpaceExA(path.c_str(), &free_bytes, &total, &total_free)) {
        total_bytes = (int64_t)total.QuadPart;
        used_bytes = (int64_t)(total.QuadPart - total_free.QuadPart);
    } else {
        used_bytes = 0; total_bytes = 0;
    }
}

void get_network_stats(int64_t& rx_bytes, int64_t& tx_bytes) {
    // Use GetIfTable for interface stats
    ULONG buf_len = 0;
    GetIfTable(nullptr, &buf_len, FALSE);
    if (buf_len == 0) { rx_bytes = 0; tx_bytes = 0; return; }
    std::vector<uint8_t> buf(buf_len);
    if (GetIfTable((MIB_IFTABLE*)buf.data(), &buf_len, FALSE) != NO_ERROR) {
        rx_bytes = 0; tx_bytes = 0; return;
    }
    auto* table = (MIB_IFTABLE*)buf.data();
    rx_bytes = 0; tx_bytes = 0;
    for (DWORD i = 0; i < table->dwNumEntries; i++) {
        rx_bytes += table->table[i].dwInOctets;
        tx_bytes += table->table[i].dwOutOctets;
    }
}

int64_t get_uptime_seconds() {
    return GetTickCount64() / 1000;
}
#else
double get_cpu_percent() {
    // Read /proc/stat for overall CPU
    std::ifstream f("/proc/stat");
    if (!f) return 0.0;
    std::string line;
    if (!std::getline(f, line)) return 0.0;
    static uint64_t last_total = 0, last_idle = 0;
    uint64_t user=0, nice=0, system=0, idle=0;
    sscanf(line.c_str(), "cpu %lu %lu %lu %lu", &user, &nice, &system, &idle);
    uint64_t total = user + nice + system + idle;
    uint64_t idle_diff = idle - last_idle;
    uint64_t total_diff = total - last_total;
    last_total = total; last_idle = idle;
    if (total_diff == 0) return 0.0;
    return 100.0 * (1.0 - (double)idle_diff / (double)total_diff);
}

void get_memory_usage(int64_t& used_bytes, int64_t& total_bytes) {
    #ifdef __APPLE__
    mach_port_t host = mach_host_self();
    vm_size_t page_size;
    host_page_size(host, &page_size);
    vm_statistics64_data_t vm_stats;
    mach_msg_type_number_t count = HOST_VM_INFO64_COUNT;
    host_statistics64(host, HOST_VM_INFO64, (host_info64_t)&vm_stats, &count);
    used_bytes = (int64_t)(vm_stats.active_count + vm_stats.inactive_count + vm_stats.wire_count) * page_size;
    int64_t total_mem = 0;
    size_t size = sizeof(total_mem);
    sysctlbyname("hw.memsize", &total_mem, &size, nullptr, 0);
    total_bytes = total_mem;
    #else
    struct sysinfo si;
    if (sysinfo(&si) == 0) {
        total_bytes = (int64_t)si.totalram * si.mem_unit;
        used_bytes = (int64_t)(si.totalram - si.freeram) * si.mem_unit;
    } else {
        used_bytes = 0; total_bytes = 0;
    }
    #endif
}

void get_disk_usage(const std::string& path,
                    int64_t& used_bytes, int64_t& total_bytes) {
    struct statvfs sv;
    if (statvfs(path.c_str(), &sv) == 0) {
        total_bytes = (int64_t)sv.f_blocks * sv.f_frsize;
        used_bytes = (int64_t)(sv.f_blocks - sv.f_bfree) * sv.f_frsize;
    } else {
        used_bytes = 0; total_bytes = 0;
    }
}

void get_network_stats(int64_t& rx_bytes, int64_t& tx_bytes) {
    std::ifstream f("/proc/net/dev");
    if (!f) { rx_bytes = 0; tx_bytes = 0; return; }
    rx_bytes = 0; tx_bytes = 0;
    std::string line;
    while (std::getline(f, line)) {
        size_t colon = line.find(':');
        if (colon == std::string::npos) continue;
        std::string iface = line.substr(0, colon);
        // Skip loopback
        if (iface.find("lo") != std::string::npos) continue;
        uint64_t rx = 0, tx = 0;
        sscanf(line.c_str() + colon + 1, "%lu", &rx);
        // tx is the 9th field after the colon
        std::istringstream iss(line.substr(colon + 1));
        uint64_t tmp;
        for (int i = 0; i < 8; i++) iss >> tmp;
        iss >> tx;
        rx_bytes += rx;
        tx_bytes += tx;
    }
}

int64_t get_uptime_seconds() {
    std::ifstream f("/proc/uptime");
    if (!f) return 0;
    double up = 0;
    f >> up;
    return (int64_t)up;
}
#endif

int64_t watch_path(const std::string& /*path*/) {
    // Simplified: return a fake handle; real impl would use ReadDirectoryChangesW/inotify
    return -1;
}

std::vector<FsEvent> poll_fs_events(int64_t /*watch_handle*/) {
    return {};  // Simplified
}

} // namespace observation

// ============================================================================
// Phase 9 — Recovery Engine helpers
// ============================================================================
namespace recovery {

    std::string classify_failure(const std::string& error_msg) {
        std::string msg = error_msg;
        std::transform(msg.begin(), msg.end(), msg.begin(),
                       [](unsigned char c) { return std::tolower(c); });
        if (msg.find("timeout") != std::string::npos ||
            msg.find("timed out") != std::string::npos ||
            msg.find("etimedout") != std::string::npos) {
            return "timeout";
        }
        if (msg.find("permission") != std::string::npos ||
            msg.find("denied") != std::string::npos ||
            msg.find("forbidden") != std::string::npos ||
            msg.find("eacces") != std::string::npos ||
            msg.find("eperm") != std::string::npos) {
            return "permission";
        }
        if (msg.find("network") != std::string::npos ||
            msg.find("econnrefused") != std::string::npos ||
            msg.find("enotfound") != std::string::npos ||
            msg.find("econnreset") != std::string::npos) {
            return "network";
        }
        if (msg.find("not found") != std::string::npos ||
            msg.find("enoent") != std::string::npos ||
            msg.find("missing") != std::string::npos) {
            return "not_found";
        }
        if (msg.find("crash") != std::string::npos ||
            msg.find("segfault") != std::string::npos ||
            msg.find("panic") != std::string::npos ||
            msg.find("abort") != std::string::npos) {
            return "crash";
        }
        if (msg.find("memory") != std::string::npos ||
            msg.find("oom") != std::string::npos ||
            msg.find("out of memory") != std::string::npos) {
            return "memory";
        }
        if (msg.find("validation") != std::string::npos ||
            msg.find("invalid") != std::string::npos ||
            msg.find("malformed") != std::string::npos) {
            return "validation";
        }
        if (msg.find("rate") != std::string::npos ||
            msg.find("limit") != std::string::npos ||
            msg.find("429") != std::string::npos ||
            msg.find("too many") != std::string::npos) {
            return "rate_limit";
        }
        if (msg.find("conflict") != std::string::npos ||
            msg.find("already exists") != std::string::npos ||
            msg.find("eexist") != std::string::npos) {
            return "conflict";
        }
        if (msg.find("dependency") != std::string::npos ||
            msg.find("requires") != std::string::npos ||
            msg.find("missing dep") != std::string::npos) {
            return "dependency";
        }
        return "unknown";
    }

    int64_t compute_backoff(int attempt, int64_t base_ms) {
        if (base_ms < 0) base_ms = 0;
        if (attempt < 0) attempt = 0;
        if (attempt > 10) attempt = 10;
        int64_t delay = base_ms;
        for (int i = 0; i < attempt; i++) delay *= 2;
        // Add up to 10% jitter
        int64_t jitter = (delay * (std::rand() % 11)) / 100;
        return delay + jitter;
    }

    std::string hash_error_signature(const std::string& error_msg) {
        // djb2 hash
        uint64_t hash = 5381;
        for (char c : error_msg) {
            hash = ((hash << 5) + hash) + static_cast<unsigned char>(c);
        }
        std::ostringstream oss;
        oss << "sig_" << std::hex << hash;
        return oss.str();
    }

    int compute_retry_budget(int used, int max) {
        int remaining = max - used;
        return remaining > 0 ? remaining : 0;
    }

} // namespace recovery

// ============================================================================
// Phase 10 — Event System
// ============================================================================
namespace event {

    static std::string djb2_prefixed(const std::string& prefix, const std::string& value) {
        uint64_t hash = 5381;
        for (char c : value) {
            hash = ((hash << 5) + hash) + static_cast<unsigned char>(c);
        }
        std::ostringstream oss;
        oss << prefix << "_" << std::hex << (hash & 0xffffffffULL);
        return oss.str();
    }

    int64_t event_timestamp() {
        return runtime::monotonic_ms();
    }

    std::string generate_event_id(const std::string& prefix) {
        std::ostringstream oss;
        oss << (prefix.empty() ? "evt" : prefix)
            << "_" << event_timestamp()
            << "_" << std::hex << (std::rand() & 0xffff);
        return oss.str();
    }

    std::string hash_event_payload(const std::string& payload) {
        return djb2_prefixed("evt", payload);
    }

    int compute_event_priority(const std::string& event_type, int64_t age_ms) {
        int base = 25;
        if (event_type == "PipelineFailed") base = 100;
        else if (event_type == "UserInterrupted") base = 95;
        else if (event_type == "ApprovalGranted" || event_type == "ApprovalRejected") base = 90;
        else if (event_type == "PipelineStarted") base = 50;
        else if (event_type == "PipelineCompleted") base = 40;
        else if (event_type == "WindowOpened" || event_type == "BrowserLoaded" || event_type == "DownloadFinished") base = 30;
        else if (event_type == "FileChanged" || event_type == "OCRCompleted" || event_type == "VisionDetected") base = 20;
        else if (event_type == "ContextUpdated") base = 10;
        int decay = (int)(age_ms > 0 ? age_ms / 1000 : 0);
        int score = base - decay;
        if (score < 0) return 0;
        return score > 100 ? 100 : score;
    }

} // namespace event

// ============================================================================
// Phase 11 — Memory System
// ============================================================================
namespace memory {

    static std::vector<std::string> tokenize_lower_words(const std::string& s) {
        std::vector<std::string> out;
        std::string cur;
        for (char c : s) {
            if (std::isalnum((unsigned char)c)) {
                cur.push_back((char)std::tolower((unsigned char)c));
            } else if (!cur.empty()) {
                out.push_back(cur);
                cur.clear();
            }
        }
        if (!cur.empty()) out.push_back(cur);
        return out;
    }

    static std::string djb2_prefixed(const std::string& prefix, const std::string& value) {
        uint64_t hash = 5381;
        for (char c : value) {
            hash = ((hash << 5) + hash) + static_cast<unsigned char>(c);
        }
        std::ostringstream oss;
        oss << prefix << "_" << std::hex << (hash & 0xffffffffULL);
        return oss.str();
    }

    int compute_memory_relevance(const std::string& query,
                                 const std::string& key,
                                 int64_t age_ms) {
        std::vector<std::string> q = tokenize_lower_words(query);
        std::vector<std::string> k = tokenize_lower_words(key);
        if (q.empty()) return 0;
        int overlap = 0;
        for (const auto& token : q) {
            if (std::find(k.begin(), k.end(), token) != k.end()) overlap++;
        }
        int token_score = (overlap * 70) / (int)q.size();
        int recency = 30 - (int)(age_ms > 0 ? age_ms / 86400000 : 0);
        if (recency < 0) recency = 0;
        int total = token_score + recency;
        return total > 100 ? 100 : total;
    }

    std::string hash_memory_key(const std::string& key) {
        return djb2_prefixed("mem", key);
    }

    int64_t compute_memory_ttl(int importance, int64_t age_ms) {
        if (importance < 0) importance = 0;
        if (importance > 100) importance = 100;
        int64_t ttl = (86400000LL * importance) / 50;
        if (ttl < 3600000LL) ttl = 3600000LL;
        return ttl > age_ms ? ttl - age_ms : 0;
    }

    int compute_cleanup_priority(int64_t age_ms, int access_count, int importance) {
        if (access_count < 0) access_count = 0;
        if (importance < 0) importance = 0;
        if (importance > 100) importance = 100;
        int age_score = (int)(age_ms > 0 ? age_ms / 86400000 : 0);
        if (age_score > 50) age_score = 50;
        int access_score = 30 - access_count * 3;
        if (access_score < 0) access_score = 0;
        int importance_score = 20 - importance / 5;
        if (importance_score < 0) importance_score = 0;
        int total = age_score + access_score + importance_score;
        return total > 100 ? 100 : total;
    }

} // namespace memory

// ============================================================================
// Phase 13 — Skill Orchestrator
// ============================================================================
namespace skill {

    // Split a CSV string into trimmed tokens
    static std::vector<std::string> split_csv(const std::string& csv) {
        std::vector<std::string> out;
        std::string cur;
        for (char c : csv) {
            if (c == ',') {
                if (!cur.empty()) {
                    // trim
                    size_t a = cur.find_first_not_of(" \t");
                    size_t b = cur.find_last_not_of(" \t");
                    if (a != std::string::npos) {
                        out.push_back(cur.substr(a, b - a + 1));
                    }
                    cur.clear();
                }
            } else {
                cur += c;
            }
        }
        if (!cur.empty()) {
            size_t a = cur.find_first_not_of(" \t");
            size_t b = cur.find_last_not_of(" \t");
            if (a != std::string::npos) {
                out.push_back(cur.substr(a, b - a + 1));
            }
        }
        return out;
    }

    // Lowercase a string
    static std::string to_lower(const std::string& s) {
        std::string r;
        r.reserve(s.size());
        for (char c : s) {
            r.push_back(c >= 'A' && c <= 'Z' ? (char)(c + 32) : c);
        }
        return r;
    }

    // Tokenize a string into lowercase word tokens (split on whitespace and underscores)
    static std::vector<std::string> tokenize_lower(const std::string& s) {
        std::vector<std::string> out;
        std::string cur;
        for (char c : s) {
            if (c == ' ' || c == '\t' || c == '_' || c == '-') {
                if (!cur.empty()) { out.push_back(cur); cur.clear(); }
            } else if (c >= 'A' && c <= 'Z') {
                cur.push_back((char)(c + 32));
            } else {
                cur.push_back(c);
            }
        }
        if (!cur.empty()) out.push_back(cur);
        return out;
    }

    int compute_skill_match(const std::string& query,
                            const std::string& skill_name,
                            const std::string& tags_csv) {
        std::vector<std::string> qTokens = tokenize_lower(query);
        std::vector<std::string> sTokens = tokenize_lower(skill_name);
        std::vector<std::string> tags = split_csv(to_lower(tags_csv));

        if (qTokens.empty()) return 0;

        // Token overlap with skill name (60% weight)
        int overlap = 0;
        for (const auto& t : qTokens) {
            for (const auto& s : sTokens) {
                if (t == s) { overlap++; break; }
            }
        }
        int tokenScore = (overlap * 60) / (int)qTokens.size();

        // Tag match (10 points per matching tag, capped)
        int tagScore = 0;
        for (const auto& t : qTokens) {
            for (const auto& tag : tags) {
                if (t == tag) { tagScore += 10; break; }
            }
        }
        if (tagScore > 40) tagScore = 40;

        int total = tokenScore + tagScore;
        return total > 100 ? 100 : total;
    }

    int compute_skill_health(int success_count, int fail_count, int64_t avg_duration_ms) {
        int total = success_count + fail_count;
        if (total == 0) return 50; // unknown

        double successRate = (double)success_count / (double)total;
        // Speed score: 20 points if fast, decays with duration
        int speedScore = 20;
        if (avg_duration_ms > 0) {
            int decay = (int)(avg_duration_ms / 1000);
            speedScore = 20 - decay;
            if (speedScore < 0) speedScore = 0;
        }

        int health = (int)(successRate * 80.0) + speedScore;
        return health > 100 ? 100 : (health < 0 ? 0 : health);
    }

    int compute_skill_chain_cost(const std::string& skills_csv) {
        std::vector<std::string> skills = split_csv(skills_csv);
        return (int)skills.size() * 10;
    }

    int compute_skill_retry_budget(int used, int max) {
        int remaining = max - used;
        return remaining > 0 ? remaining : 0;
    }

} // namespace skill

// ============================================================================
// Phase 14 — State Manager
// ============================================================================
namespace state {

    // djb2 hash returning hex string with "st_" prefix
    std::string compute_state_hash(const std::string& state_json) {
        uint64_t hash = 5381;
        for (char c : state_json) {
            hash = ((hash << 5) + hash) + (uint64_t)(unsigned char)c;
            hash = hash & 0xffffffffffffffffULL;
        }
        std::ostringstream oss;
        oss << "st_" << std::hex << (hash & 0xffffffffULL);
        return oss.str();
    }

    int compute_state_diff(const std::string& hash_a, const std::string& hash_b) {
        if (hash_a == hash_b) return 0;
        size_t maxLen = hash_a.size() > hash_b.size() ? hash_a.size() : hash_b.size();
        if (maxLen == 0) return 0;
        size_t diff = 0;
        for (size_t i = 0; i < maxLen; i++) {
            char a = i < hash_a.size() ? hash_a[i] : 0;
            char b = i < hash_b.size() ? hash_b[i] : 0;
            if (a != b) diff++;
        }
        int score = (int)((diff * 100) / maxLen);
        return score > 100 ? 100 : score;
    }

    int compute_state_freshness(int64_t age_ms, int64_t max_age_ms) {
        if (max_age_ms <= 0) return 0;
        if (age_ms >= max_age_ms) return 0;
        int score = (int)(((max_age_ms - age_ms) * 100) / max_age_ms);
        return score > 100 ? 100 : (score < 0 ? 0 : score);
    }

    int compute_state_eviction_priority(int64_t age_ms, int access_count, int64_t size_bytes) {
        int ageScore = (int)(age_ms / 60000);
        if (ageScore > 40) ageScore = 40;
        int accessScore = 30 - access_count * 3;
        if (accessScore < 0) accessScore = 0;
        int sizeScore = (int)(size_bytes / 1024);
        if (sizeScore > 30) sizeScore = 30;
        int total = ageScore + accessScore + sizeScore;
        return total > 100 ? 100 : total;
    }

} // namespace state

// ============================================================================
// Phase 15 — Workflow Engine
// ============================================================================
namespace workflow {

    int compute_workflow_complexity(int node_count, int max_depth) {
        int nodeScore = node_count * 5;
        if (nodeScore > 60) nodeScore = 60;
        int depthScore = max_depth * 10;
        if (depthScore > 40) depthScore = 40;
        int total = nodeScore + depthScore;
        return total > 100 ? 100 : total;
    }

    int compute_workflow_parallelism(int branch_count, int max_width) {
        int branchScore = branch_count * 15;
        if (branchScore > 60) branchScore = 60;
        int widthScore = max_width * 10;
        if (widthScore > 40) widthScore = 40;
        int total = branchScore + widthScore;
        return total > 100 ? 100 : total;
    }

    int compute_workflow_priority(int priority, int64_t due_in_ms) {
        int priorityScore = priority * 10;
        if (priorityScore > 60) priorityScore = 60;
        int dueScore = 0;
        if (due_in_ms <= 0) {
            dueScore = 40;
        } else if (due_in_ms < 60000) {
            dueScore = 35;
        } else if (due_in_ms < 300000) {
            dueScore = 25;
        } else if (due_in_ms < 3600000) {
            dueScore = 15;
        } else {
            dueScore = 5;
        }
        int total = priorityScore + dueScore;
        return total > 100 ? 100 : total;
    }

    int compute_workflow_retry_budget(int used, int max) {
        int remaining = max - used;
        return remaining > 0 ? remaining : 0;
    }

} // namespace workflow

// ============================================================================
// Phase 16 — Provider Abstraction
// ============================================================================
namespace provider {

    int compute_provider_score(int health, int cost, int latency_ms) {
        // Health: 0-100 (higher is better)
        // Cost: 0-100 (lower is better, inverted)
        // Latency: ms (lower is better, inverted)
        int healthScore = health;
        if (healthScore > 100) healthScore = 100;
        if (healthScore < 0) healthScore = 0;
        int costScore = 100 - cost;
        if (costScore > 100) costScore = 100;
        if (costScore < 0) costScore = 0;
        int latencyScore = 0;
        if (latency_ms <= 0) {
            latencyScore = 100;
        } else if (latency_ms < 100) {
            latencyScore = 95;
        } else if (latency_ms < 500) {
            latencyScore = 80;
        } else if (latency_ms < 2000) {
            latencyScore = 60;
        } else if (latency_ms < 10000) {
            latencyScore = 30;
        } else {
            latencyScore = 10;
        }
        // Weighted: health 50%, cost 20%, latency 30%
        int total = (healthScore * 50 + costScore * 20 + latencyScore * 30) / 100;
        return total > 100 ? 100 : total;
    }

    int compute_fallback_depth(int chain_length, int reliability) {
        // chain_length: number of fallback providers
        // reliability: 0-100 (higher is better)
        int lengthScore = chain_length * 15;
        if (lengthScore > 60) lengthScore = 60;
        int reliabilityScore = reliability / 2;
        if (reliabilityScore > 40) reliabilityScore = 40;
        int total = lengthScore + reliabilityScore;
        return total > 100 ? 100 : total;
    }

    int compute_load_weight(int capacity, int current_load) {
        // capacity: max concurrent requests
        // current_load: current concurrent requests
        if (capacity <= 0) return 0;
        int used = current_load > capacity ? capacity : current_load;
        int free = capacity - used;
        int weight = (free * 100) / capacity;
        return weight > 100 ? 100 : weight;
    }

    int compute_circuit_state(int failure_count, int threshold) {
        // 0 = closed (healthy), 1 = half-open (testing), 2 = open (failing)
        if (threshold <= 0) return 0;
        if (failure_count >= threshold) return 2;       // open
        if (failure_count >= threshold / 2) return 1;   // half-open
        return 0;                                        // closed
    }

} // namespace provider

// ============================================================================
// Phase 17 — Agent Runtime implementations
// ============================================================================
namespace runtime {

    int compute_stage_priority(const std::string& stage, int64_t age_ms) {
        // Base priority by stage importance, minus age decay
        int base = 50;
        if (stage == "intent") base = 90;
        else if (stage == "context") base = 80;
        else if (stage == "plan") base = 85;
        else if (stage == "graph") base = 75;
        else if (stage == "registry") base = 60;
        else if (stage == "runtime") base = 95;
        else if (stage == "skills") base = 70;
        else if (stage == "observe") base = 65;
        else if (stage == "verify") base = 85;
        else if (stage == "recover") base = 90;
        else if (stage == "memory") base = 50;
        else if (stage == "complete") base = 40;

        int decay = (int)(age_ms / 1000);  // 1 point per second
        int priority = base - decay;
        if (priority < 0) priority = 0;
        if (priority > 100) priority = 100;
        return priority;
    }

    std::string hash_runtime_request(const std::string& request_json) {
        // djb2 hash for runtime request dedup
        unsigned long hash = 5381;
        for (char c : request_json) {
            hash = ((hash << 5) + hash) + (unsigned char)c;
        }
        std::ostringstream oss;
        oss << "rt_" << std::hex << hash;
        return oss.str();
    }

    int compute_runtime_relevance(const std::string& text, const std::string& query) {
        // Token overlap + recency-style scoring
        if (text.empty() || query.empty()) return 0;

        // Simple word overlap
        std::istringstream textStream(text);
        std::istringstream queryStream(query);
        std::string word;
        std::vector<std::string> textWords;
        std::vector<std::string> queryWords;

        while (textStream >> word) textWords.push_back(word);
        while (queryStream >> word) queryWords.push_back(word);

        if (queryWords.empty()) return 0;

        int matches = 0;
        for (const auto& qw : queryWords) {
            for (const auto& tw : textWords) {
                if (qw == tw) { matches++; break; }
            }
        }

        int score = (matches * 100) / (int)queryWords.size();
        if (score > 100) score = 100;
        return score;
    }

    int compute_stage_transition_cost(const std::string& source, const std::string& target) {
        // Cost of transitioning between runtime stages (0-100)
        // Lower cost for natural flow, higher for skips/loops
        if (source == target) return 90;  // loop = expensive

        // Natural flow costs
        if ((source == "intent" && target == "context") ||
            (source == "context" && target == "plan") ||
            (source == "plan" && target == "graph") ||
            (source == "graph" && target == "registry") ||
            (source == "registry" && target == "runtime") ||
            (source == "runtime" && target == "skills") ||
            (source == "skills" && target == "observe") ||
            (source == "observe" && target == "verify") ||
            (source == "verify" && target == "recover") ||
            (source == "recover" && target == "memory") ||
            (source == "memory" && target == "complete")) {
            return 10;
        }

        // Skip stages = moderate cost
        return 50;
    }

} // namespace runtime

// ============================================================================
// Unified entry point
// ============================================================================
std::string screenai_call(int op, const std::string& input) {
    std::ostringstream out;
    switch (op) {
        case 0: {  // monotonic_ms
            out << runtime::monotonic_ms();
            break;
        }
        case 1: {  // sleep_ms
            int ms = std::atoi(input.c_str());
            runtime::sleep_ms(ms);
            out << "ok";
            break;
        }
        case 10: {  // enumerate_processes
            auto procs = context::enumerate_processes(256);
            out << "[";
            for (size_t i = 0; i < procs.size(); i++) {
                if (i > 0) out << ",";
                out << "{\"pid\":" << procs[i].pid
                    << ",\"name\":\"" << procs[i].name << "\""
                    << ",\"cpu\":" << procs[i].cpu_percent
                    << ",\"memory\":" << procs[i].memory_bytes << "}";
            }
            out << "]";
            break;
        }
        case 11: {  // enumerate_windows
            auto wins = context::enumerate_windows(128);
            out << "[";
            for (size_t i = 0; i < wins.size(); i++) {
                if (i > 0) out << ",";
                out << "{\"handle\":" << wins[i].handle
                    << ",\"title\":\"" << wins[i].title << "\""
                    << ",\"app\":\"" << wins[i].app << "\""
                    << ",\"focused\":" << (wins[i].focused ? "true" : "false") << "}";
            }
            out << "]";
            break;
        }
        case 12: {  // get_focused_window_title
            out << "\"" << context::get_focused_window_title() << "\"";
            break;
        }
        case 20: {  // string_similarity
            // input format: "a|b"
            size_t sep = input.find('|');
            std::string a = (sep == std::string::npos) ? "" : input.substr(0, sep);
            std::string b = (sep == std::string::npos) ? "" : input.substr(sep + 1);
            out << intent::string_similarity(a, b);
            break;
        }
        case 21: {  // normalize_intent
            out << "\"" << intent::normalize_intent(input) << "\"";
            break;
        }
        case 30: {  // compute_plan_cost
            // input format: "1.0,2.5,3.0"
            std::vector<double> costs;
            std::istringstream iss(input);
            std::string tok;
            while (std::getline(iss, tok, ',')) {
                costs.push_back(std::atof(tok.c_str()));
            }
            out << planner::compute_plan_cost(costs);
            break;
        }
        case 31: {  // compute_risk_score
            std::vector<int> risks;
            std::istringstream iss(input);
            std::string tok;
            while (std::getline(iss, tok, ',')) {
                risks.push_back(std::atoi(tok.c_str()));
            }
            out << planner::compute_risk_score(risks);
            break;
        }
        case 32: {  // topological_sort
            // input format: "n|adj1;adj2;..."
            size_t sep = input.find('|');
            if (sep == std::string::npos) { out << "[]"; break; }
            int n = std::atoi(input.substr(0, sep).c_str());
            std::vector<std::vector<int>> adj(n);
            std::istringstream iss(input.substr(sep + 1));
            std::string row;
            for (int i = 0; i < n; i++) {
                std::getline(iss, row, ';');
                std::istringstream rs(row);
                std::string tok;
                while (std::getline(rs, tok, ',')) {
                    int v = std::atoi(tok.c_str());
                    if (v >= 0 && v < n) adj[i].push_back(v);
                }
            }
            std::vector<int> order;
            bool ok = planner::topological_sort(adj, order);
            if (!ok) { out << "[]"; break; }
            out << "[";
            for (size_t i = 0; i < order.size(); i++) {
                if (i > 0) out << ",";
                out << order[i];
            }
            out << "]";
            break;
        }
        case 40: {  // get_cpu_percent
            out << observation::get_cpu_percent();
            break;
        }
        case 41: {  // get_memory_usage
            int64_t used = 0, total = 0;
            observation::get_memory_usage(used, total);
            out << "{\"used\":" << used << ",\"total\":" << total << "}";
            break;
        }
        case 42: {  // get_disk_usage
            int64_t used = 0, total = 0;
            observation::get_disk_usage(input, used, total);
            out << "{\"used\":" << used << ",\"total\":" << total << "}";
            break;
        }
        case 43: {  // get_network_stats
            int64_t rx = 0, tx = 0;
            observation::get_network_stats(rx, tx);
            out << "{\"rx\":" << rx << ",\"tx\":" << tx << "}";
            break;
        }
        case 44: {  // get_uptime_seconds
            out << observation::get_uptime_seconds();
            break;
        }
        case 50: {  // verify (Phase 8)
            // input format: "check_type|target|options"
            size_t p1 = input.find('|');
            size_t p2 = (p1 == std::string::npos) ? std::string::npos : input.find('|', p1 + 1);
            int ct = std::atoi(input.substr(0, p1).c_str());
            std::string target = (p1 == std::string::npos) ? "" : input.substr(p1 + 1, (p2 == std::string::npos ? std::string::npos : p2 - p1 - 1));
            std::string options = (p2 == std::string::npos) ? "" : input.substr(p2 + 1);
            auto r = verify_native(ct, target.c_str(), options.c_str());
            out << "{\"passed\":" << (r.passed ? "true" : "false")
                << ",\"details\":\"" << r.details << "\"}";
            break;
        }
        case 60: {  // classify_failure (Phase 9)
            out << "\"" << recovery::classify_failure(input) << "\"";
            break;
        }
        case 61: {  // compute_backoff (Phase 9)
            // input format: "attempt|base_ms"
            size_t sep = input.find('|');
            int attempt = std::atoi(input.substr(0, sep).c_str());
            int64_t base_ms = std::atoll(input.substr(sep + 1).c_str());
            out << recovery::compute_backoff(attempt, base_ms);
            break;
        }
        case 62: {  // hash_error_signature (Phase 9)
            out << "\"" << recovery::hash_error_signature(input) << "\"";
            break;
        }
        case 63: {  // compute_retry_budget (Phase 9)
            // input format: "used|max"
            size_t sep = input.find('|');
            int used = std::atoi(input.substr(0, sep).c_str());
            int max = std::atoi(input.substr(sep + 1).c_str());
            out << recovery::compute_retry_budget(used, max);
            break;
        }
        case 70: {  // event_timestamp (Phase 10)
            out << event::event_timestamp();
            break;
        }
        case 71: {  // generate_event_id (Phase 10)
            out << event::generate_event_id(input.empty() ? "evt" : input);
            break;
        }
        case 72: {  // hash_event_payload (Phase 10)
            out << event::hash_event_payload(input);
            break;
        }
        case 73: {  // compute_event_priority (Phase 10)
            // input format: "event_type|age_ms"
            size_t sep = input.find('|');
            std::string event_type = (sep == std::string::npos) ? input : input.substr(0, sep);
            int64_t age = (sep == std::string::npos) ? 0 : std::atoll(input.substr(sep + 1).c_str());
            out << event::compute_event_priority(event_type, age);
            break;
        }
        case 80: {  // compute_memory_relevance (Phase 11)
            // input format: "query|key|age_ms"
            size_t p1 = input.find('|');
            size_t p2 = (p1 == std::string::npos) ? std::string::npos : input.find('|', p1 + 1);
            std::string query = (p1 == std::string::npos) ? input : input.substr(0, p1);
            std::string key = (p1 == std::string::npos) ? "" : input.substr(p1 + 1, (p2 == std::string::npos ? std::string::npos : p2 - p1 - 1));
            int64_t age = (p2 == std::string::npos) ? 0 : std::atoll(input.substr(p2 + 1).c_str());
            out << memory::compute_memory_relevance(query, key, age);
            break;
        }
        case 81: {  // hash_memory_key (Phase 11)
            out << memory::hash_memory_key(input);
            break;
        }
        case 82: {  // compute_memory_ttl (Phase 11)
            // input format: "importance|age_ms"
            size_t sep = input.find('|');
            int importance = std::atoi(input.substr(0, sep).c_str());
            int64_t age = (sep == std::string::npos) ? 0 : std::atoll(input.substr(sep + 1).c_str());
            out << memory::compute_memory_ttl(importance, age);
            break;
        }
        case 83: {  // compute_cleanup_priority (Phase 11)
            // input format: "age_ms|access_count|importance"
            size_t p1 = input.find('|');
            size_t p2 = (p1 == std::string::npos) ? std::string::npos : input.find('|', p1 + 1);
            int64_t age = std::atoll(input.substr(0, p1).c_str());
            int access = (p1 == std::string::npos) ? 0 : std::atoi(input.substr(p1 + 1, (p2 == std::string::npos ? std::string::npos : p2 - p1 - 1)).c_str());
            int importance = (p2 == std::string::npos) ? 50 : std::atoi(input.substr(p2 + 1).c_str());
            out << memory::compute_cleanup_priority(age, access, importance);
            break;
        }
        case 90: {  // compute_skill_match (Phase 13)
            // input format: "query|skill_name|tags_csv"
            size_t p1 = input.find('|');
            size_t p2 = (p1 == std::string::npos) ? std::string::npos : input.find('|', p1 + 1);
            std::string q = (p1 == std::string::npos) ? input : input.substr(0, p1);
            std::string n = (p1 == std::string::npos) ? "" : input.substr(p1 + 1, (p2 == std::string::npos ? std::string::npos : p2 - p1 - 1));
            std::string t = (p2 == std::string::npos) ? "" : input.substr(p2 + 1);
            out << skill::compute_skill_match(q, n, t);
            break;
        }
        case 91: {  // compute_skill_health (Phase 13)
            // input format: "success_count|fail_count|avg_duration_ms"
            size_t p1 = input.find('|');
            size_t p2 = (p1 == std::string::npos) ? std::string::npos : input.find('|', p1 + 1);
            int s = std::atoi(input.substr(0, p1).c_str());
            int f = std::atoi(input.substr(p1 + 1, (p2 == std::string::npos ? std::string::npos : p2 - p1 - 1)).c_str());
            int64_t d = std::atoll(input.substr(p2 + 1).c_str());
            out << skill::compute_skill_health(s, f, d);
            break;
        }
        case 92: {  // compute_skill_chain_cost (Phase 13)
            out << skill::compute_skill_chain_cost(input);
            break;
        }
        case 93: {  // compute_skill_retry_budget (Phase 13)
            // input format: "used|max"
            size_t sep = input.find('|');
            int used = std::atoi(input.substr(0, sep).c_str());
            int max = std::atoi(input.substr(sep + 1).c_str());
            out << skill::compute_skill_retry_budget(used, max);
            break;
        }
        case 100: {  // compute_state_hash (Phase 14)
            out << "\"" << state::compute_state_hash(input) << "\"";
            break;
        }
        case 101: {  // compute_state_diff (Phase 14)
            // input format: "hash_a|hash_b"
            size_t sep = input.find('|');
            std::string a = (sep == std::string::npos) ? input : input.substr(0, sep);
            std::string b = (sep == std::string::npos) ? "" : input.substr(sep + 1);
            out << state::compute_state_diff(a, b);
            break;
        }
        case 102: {  // compute_state_freshness (Phase 14)
            // input format: "age_ms|max_age_ms"
            size_t sep = input.find('|');
            int64_t age = std::atoll(input.substr(0, sep).c_str());
            int64_t max = std::atoll(input.substr(sep + 1).c_str());
            out << state::compute_state_freshness(age, max);
            break;
        }
        case 103: {  // compute_state_eviction_priority (Phase 14)
            // input format: "age_ms|access_count|size_bytes"
            size_t p1 = input.find('|');
            size_t p2 = (p1 == std::string::npos) ? std::string::npos : input.find('|', p1 + 1);
            int64_t age = std::atoll(input.substr(0, p1).c_str());
            int access = std::atoi(input.substr(p1 + 1, (p2 == std::string::npos ? std::string::npos : p2 - p1 - 1)).c_str());
            int64_t size = std::atoll(input.substr(p2 + 1).c_str());
            out << state::compute_state_eviction_priority(age, access, size);
            break;
        }
        case 110: {  // compute_workflow_complexity (Phase 15)
            // input format: "node_count|max_depth"
            size_t sep = input.find('|');
            int nodes = std::atoi(input.substr(0, sep).c_str());
            int depth = std::atoi(input.substr(sep + 1).c_str());
            out << workflow::compute_workflow_complexity(nodes, depth);
            break;
        }
        case 111: {  // compute_workflow_parallelism (Phase 15)
            // input format: "branch_count|max_width"
            size_t sep = input.find('|');
            int branches = std::atoi(input.substr(0, sep).c_str());
            int width = std::atoi(input.substr(sep + 1).c_str());
            out << workflow::compute_workflow_parallelism(branches, width);
            break;
        }
        case 112: {  // compute_workflow_priority (Phase 15)
            // input format: "priority|due_in_ms"
            size_t sep = input.find('|');
            int priority = std::atoi(input.substr(0, sep).c_str());
            int64_t due = std::atoll(input.substr(sep + 1).c_str());
            out << workflow::compute_workflow_priority(priority, due);
            break;
        }
        case 113: {  // compute_workflow_retry_budget (Phase 15)
            // input format: "used|max"
            size_t sep = input.find('|');
            int used = std::atoi(input.substr(0, sep).c_str());
            int max = std::atoi(input.substr(sep + 1).c_str());
            out << workflow::compute_workflow_retry_budget(used, max);
            break;
        }
        case 120: {  // compute_provider_score (Phase 16)
            // input format: "health|cost|latency_ms"
            size_t sep1 = input.find('|');
            size_t sep2 = input.find('|', sep1 + 1);
            int health = std::atoi(input.substr(0, sep1).c_str());
            int cost = std::atoi(input.substr(sep1 + 1, sep2 - sep1 - 1).c_str());
            int latency = std::atoi(input.substr(sep2 + 1).c_str());
            out << provider::compute_provider_score(health, cost, latency);
            break;
        }
        case 121: {  // compute_fallback_depth (Phase 16)
            // input format: "chain_length|reliability"
            size_t sep = input.find('|');
            int chain = std::atoi(input.substr(0, sep).c_str());
            int reliability = std::atoi(input.substr(sep + 1).c_str());
            out << provider::compute_fallback_depth(chain, reliability);
            break;
        }
        case 122: {  // compute_load_weight (Phase 16)
            // input format: "capacity|current_load"
            size_t sep = input.find('|');
            int capacity = std::atoi(input.substr(0, sep).c_str());
            int load = std::atoi(input.substr(sep + 1).c_str());
            out << provider::compute_load_weight(capacity, load);
            break;
        }
        case 123: {  // compute_circuit_state (Phase 16)
            // input format: "failure_count|threshold"
            size_t sep = input.find('|');
            int failures = std::atoi(input.substr(0, sep).c_str());
            int threshold = std::atoi(input.substr(sep + 1).c_str());
            out << provider::compute_circuit_state(failures, threshold);
            break;
        }
        case 130: {  // compute_stage_priority (Phase 17)
            // input format: "stage|age_ms"
            size_t sep = input.find('|');
            std::string stage = input.substr(0, sep);
            int64_t age = std::atoll(input.substr(sep + 1).c_str());
            out << runtime::compute_stage_priority(stage, age);
            break;
        }
        case 131: {  // hash_runtime_request (Phase 17)
            out << runtime::hash_runtime_request(input);
            break;
        }
        case 132: {  // compute_runtime_relevance (Phase 17)
            // input format: "text|query"
            size_t sep = input.find('|');
            std::string text = input.substr(0, sep);
            std::string query = input.substr(sep + 1);
            out << runtime::compute_runtime_relevance(text, query);
            break;
        }
        case 133: {  // compute_stage_transition_cost (Phase 17)
            // input format: "source|target"
            size_t sep = input.find('|');
            std::string source = input.substr(0, sep);
            std::string target = input.substr(sep + 1);
            out << runtime::compute_stage_transition_cost(source, target);
            break;
        }
        default:
            out << "{\"error\":\"unknown op " << op << "\"}";
            break;
    }
    return out.str();
}

} // namespace screenai

// Plain C exports for Node addon binding
extern "C" {
    const char* screenai_call_c(int op, const char* input) {
        std::string in = input ? input : "";
        std::string result = screenai::screenai_call(op, in);
        // Return a heap-allocated copy; caller (JS) must free
        char* out = (char*)std::malloc(result.size() + 1);
        std::memcpy(out, result.c_str(), result.size() + 1);
        return out;
    }
    void screenai_free(char* p) {
        if (p) std::free(p);
    }
    int screenai_verify(int check_type, const char* target, const char* options) {
        auto r = screenai::verify_native(check_type, target, options);
        return r.passed ? 1 : 0;
    }
}
