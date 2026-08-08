// filepath: hackathon_ui_operator_distill/native/screenai_core.h
// Screen-AI Native Core — Unified C++ bridge for all pipeline phases
// Used by Phase 3-8 utility classes in pipeline/screenai_pipelines.js
// Build target: ai_pc_operator/data/native/screenai_core.node (Node addon)
//
// Build instructions (Windows, MSVC):
//   cl /LD /EHsc screenai_core.cpp /I<node-gyp headers> /link /OUT:screenai_core.node
//
// Build instructions (Linux/macOS):
//   g++ -shared -fPIC -std=c++17 screenai_core.cpp -o screenai_core.node
//
// The JS layer detects absence and falls back to pure-JS implementations,
// so absence is non-fatal.

#ifndef SCREENAI_CORE_H
#define SCREENAI_CORE_H

#include <string>
#include <cstdint>
#include <vector>

namespace screenai {

// ============================================================================
// Phase 3 — Execution Runtime helpers
// ============================================================================
namespace runtime {
    // High-resolution monotonic time in milliseconds
    int64_t monotonic_ms();

    // Sleep for the given number of milliseconds (interruptible)
    void sleep_ms(int ms);
}

// ============================================================================
// Phase 4 — Context Engine helpers
// ============================================================================
namespace context {
    struct ProcessInfo {
        int32_t pid;
        std::string name;
        double cpu_percent;
        int64_t memory_bytes;
    };

    struct WindowInfo {
        int64_t handle;
        std::string title;
        std::string app;
        bool visible;
        bool focused;
    };

    // Enumerate running processes (lightweight, no admin required)
    std::vector<ProcessInfo> enumerate_processes(int32_t max_count = 256);

    // Enumerate visible windows (best-effort, OS-specific)
    std::vector<WindowInfo> enumerate_windows(int32_t max_count = 128);

    // Get the currently focused window title
    std::string get_focused_window_title();
}

// ============================================================================
// Phase 5 — Intent Engine helpers
// ============================================================================
namespace intent {
    // Compute a normalized similarity score between two strings (0.0 - 1.0)
    // Uses Jaccard token overlap + Levenshtein-like char similarity
    double string_similarity(const std::string& a, const std::string& b);

    // Tokenize a string into lowercase word tokens
    std::vector<std::string> tokenize(const std::string& s);

    // Compute Jaccard similarity between two token sets
    double jaccard_similarity(const std::vector<std::string>& a,
                              const std::vector<std::string>& b);

    // Normalize an intent string (lowercase, trim, collapse whitespace)
    std::string normalize_intent(const std::string& s);
}

// ============================================================================
// Phase 6 — Planner helpers
// ============================================================================
namespace planner {
    // Compute a cost estimate for a plan (sum of node costs)
    double compute_plan_cost(const std::vector<double>& node_costs);

    // Compute a risk score (weighted sum of risk levels)
    double compute_risk_score(const std::vector<int>& risk_levels);

    // Topological sort of a DAG given adjacency list
    // Returns true if the graph is acyclic, false otherwise
    bool topological_sort(const std::vector<std::vector<int>>& adj,
                          std::vector<int>& order);

    // Solve a simple constraint: pick the first feasible option
    int solve_constraint(const std::vector<int>& options,
                         const std::vector<int>& constraints);
}

// ============================================================================
// Phase 7 — Observation Engine helpers
// ============================================================================
namespace observation {
    // Get current CPU usage percent (0-100)
    double get_cpu_percent();

    // Get memory usage: returns {used_bytes, total_bytes}
    void get_memory_usage(int64_t& used_bytes, int64_t& total_bytes);

    // Get disk usage for a path: returns {used_bytes, total_bytes}
    void get_disk_usage(const std::string& path,
                        int64_t& used_bytes, int64_t& total_bytes);

    // Get network stats: returns {rx_bytes, tx_bytes} since boot
    void get_network_stats(int64_t& rx_bytes, int64_t& tx_bytes);

    // Get system uptime in seconds
    int64_t get_uptime_seconds();

    // Watch a filesystem path for changes (returns watch handle id, or -1)
    int64_t watch_path(const std::string& path);

    // Poll a watched path for events since last poll
    // Returns list of {event_type, path} pairs
    struct FsEvent {
        std::string event_type;  // "create", "modify", "delete"
        std::string path;
    };
    std::vector<FsEvent> poll_fs_events(int64_t watch_handle);
}

// ============================================================================
// Phase 8 — Verification Engine helpers (already in verifier_bridge.h)
// ============================================================================
// Re-exported here for unified access
#ifndef SCREENAI_VERIFY_RESULT_DEFINED
#define SCREENAI_VERIFY_RESULT_DEFINED
struct VerifyResult {
    bool passed;
    std::string details;
};
#endif

VerifyResult verify_native(int check_type,
                           const char* target,
                           const char* options);

// ============================================================================
// Phase 9 — Recovery Engine helpers
// ============================================================================
namespace recovery {
    // Classify a failure message into a category string
    // Returns one of: "timeout", "permission", "network", "not_found",
    //                 "crash", "memory", "validation", "rate_limit",
    //                 "conflict", "dependency", "unknown"
    std::string classify_failure(const std::string& error_msg);

    // Compute exponential backoff delay in milliseconds
    // attempt: zero-based attempt number
    // base_ms: base delay in milliseconds
    int64_t compute_backoff(int attempt, int64_t base_ms);

    // Compute a stable hash signature for an error message (for dedup)
    // Returns a hex string suitable for use as a map key
    std::string hash_error_signature(const std::string& error_msg);

    // Compute retry budget remaining (max - used, clamped to >= 0)
    int compute_retry_budget(int used, int max);
}

// ============================================================================
// Phase 10 — Event System helpers
// ============================================================================
namespace event {
    int64_t event_timestamp();
    std::string generate_event_id(const std::string& prefix);
    std::string hash_event_payload(const std::string& payload);
    int compute_event_priority(const std::string& event_type, int64_t age_ms);
}

// ============================================================================
// Phase 11 — Memory System helpers
// ============================================================================
namespace memory {
    int compute_memory_relevance(const std::string& query,
                                 const std::string& key,
                                 int64_t age_ms);
    std::string hash_memory_key(const std::string& key);
    int64_t compute_memory_ttl(int importance, int64_t age_ms);
    int compute_cleanup_priority(int64_t age_ms, int access_count, int importance);
}

// ============================================================================
// Phase 13 — Skill Orchestrator helpers
// ============================================================================
namespace skill {
    // Compute skill match score (0-100) for a query against a skill
    // input format: "query|skill_name|tags_csv"
    int compute_skill_match(const std::string& query,
                            const std::string& skill_name,
                            const std::string& tags_csv);

    // Compute skill health score (0-100) from success/fail counts and avg duration
    // input format: "success_count|fail_count|avg_duration_ms"
    int compute_skill_health(int success_count, int fail_count, int64_t avg_duration_ms);

    // Compute total cost of a skill chain (sum of per-skill costs)
    // input format: "skill1,skill2,skill3"
    int compute_skill_chain_cost(const std::string& skills_csv);

    // Compute retry budget remaining for a skill (max - used, clamped to >= 0)
    // input format: "used|max"
    int compute_skill_retry_budget(int used, int max);
}

// ============================================================================
// Phase 14 — State Manager helpers
// ============================================================================
namespace state {
    // Compute a stable hash for a state JSON string (for change detection)
    // Returns a hex string suitable for use as a map key
    std::string compute_state_hash(const std::string& state_json);

    // Compute a diff score (0-100) between two state hashes
    // input format: "hash_a|hash_b"
    int compute_state_diff(const std::string& hash_a, const std::string& hash_b);

    // Compute freshness score (0-100) given age and max age in ms
    // input format: "age_ms|max_age_ms"
    int compute_state_freshness(int64_t age_ms, int64_t max_age_ms);

    // Compute eviction priority (0-100) given age, access count, and size
    // input format: "age_ms|access_count|size_bytes"
    int compute_state_eviction_priority(int64_t age_ms, int access_count, int64_t size_bytes);
}

// ============================================================================
// Phase 15 — Workflow Engine helpers
// ============================================================================
namespace workflow {
    // Compute workflow complexity score (0-100) from node count and depth
    // input format: "node_count|max_depth"
    int compute_workflow_complexity(int node_count, int max_depth);

    // Compute workflow parallelism score (0-100) from branch count and width
    // input format: "branch_count|max_width"
    int compute_workflow_parallelism(int branch_count, int max_width);

    // Compute workflow schedule priority (0-100) from priority and due time
    // input format: "priority|due_in_ms"
    int compute_workflow_priority(int priority, int64_t due_in_ms);

    // Compute workflow retry budget remaining (max - used, clamped to >= 0)
    // input format: "used|max"
    int compute_workflow_retry_budget(int used, int max);
}

// ============================================================================
// Phase 16 — Provider Abstraction helpers
// ============================================================================
namespace provider {
    // Compute provider selection score (0-100) from health, cost, latency
    // input format: "health|cost|latency_ms"
    int compute_provider_score(int health, int cost, int latency_ms);

    // Compute provider fallback chain depth (0-100) from chain length and reliability
    // input format: "chain_length|reliability"
    int compute_fallback_depth(int chain_length, int reliability);

    // Compute provider load balancing weight (0-100) from capacity and current load
    // input format: "capacity|current_load"
    int compute_load_weight(int capacity, int current_load);

    // Compute provider circuit breaker state (0=closed, 1=half-open, 2=open)
    // input format: "failure_count|threshold"
    int compute_circuit_state(int failure_count, int threshold);
}

// ============================================================================
// Phase 17 — Agent Runtime helpers
// ============================================================================
namespace runtime {
    // Compute runtime stage priority (0-100) from stage name and age
    // input format: "stage|age_ms"
    int compute_stage_priority(const std::string& stage, int64_t age_ms);

    // Compute runtime request hash for dedup (returns hex string)
    // input format: JSON request object
    std::string hash_runtime_request(const std::string& request_json);

    // Compute runtime memory relevance score (0-100) from text and query
    // input format: "text|query"
    int compute_runtime_relevance(const std::string& text, const std::string& query);

    // Compute runtime stage transition cost (0-100) from source and target stages
    // input format: "source_stage|target_stage"
    int compute_stage_transition_cost(const std::string& source, const std::string& target);
}

// ============================================================================
// Unified entry point — single C export for Node addon binding
// ============================================================================
// op codes:
//   0  = monotonic_ms
//   1  = sleep_ms
//   10 = enumerate_processes (returns JSON array)
//   11 = enumerate_windows (returns JSON array)
//   12 = get_focused_window_title
//   20 = string_similarity
//   21 = normalize_intent
//   30 = compute_plan_cost
//   31 = compute_risk_score
//   32 = topological_sort (returns JSON array or empty on cycle)
//   40 = get_cpu_percent
//   41 = get_memory_usage (returns JSON {used,total})
//   42 = get_disk_usage (returns JSON {used,total})
//   43 = get_network_stats (returns JSON {rx,tx})
//   44 = get_uptime_seconds
//   50 = verify (Phase 8 — see verifier_bridge.h for check types)
//   60 = classify_failure (Phase 9 — returns category string)
//   61 = compute_backoff (Phase 9 — returns ms as integer string)
//   62 = hash_error_signature (Phase 9 — returns hex string)
//   63 = compute_retry_budget (Phase 9 — returns integer string)
//   70 = event_timestamp (Phase 10 — returns monotonic ms)
//   71 = generate_event_id (Phase 10 — returns string)
//   72 = hash_event_payload (Phase 10 — returns hex string)
//   73 = compute_event_priority (Phase 10 — returns integer 0-100)
//   80 = compute_memory_relevance (Phase 11 — returns integer 0-100)
//   81 = hash_memory_key (Phase 11 — returns hex string)
//   82 = compute_memory_ttl (Phase 11 — returns milliseconds)
//   83 = compute_cleanup_priority (Phase 11 — returns integer 0-100)
//   90 = compute_skill_match (Phase 13 — returns integer 0-100)
//   91 = compute_skill_health (Phase 13 — returns integer 0-100)
//   92 = compute_skill_chain_cost (Phase 13 — returns integer)
//   93 = compute_skill_retry_budget (Phase 13 — returns integer)
//   100 = compute_state_hash (Phase 14 — returns hex string)
//   101 = compute_state_diff (Phase 14 — returns integer 0-100)
//   102 = compute_state_freshness (Phase 14 — returns integer 0-100)
//   103 = compute_state_eviction_priority (Phase 14 — returns integer 0-100)
//   110 = compute_workflow_complexity (Phase 15 — returns integer 0-100)
//   111 = compute_workflow_parallelism (Phase 15 — returns integer 0-100)
//   112 = compute_workflow_priority (Phase 15 — returns integer 0-100)
//   113 = compute_workflow_retry_budget (Phase 15 — returns integer)
//   120 = compute_provider_score (Phase 16 — returns integer 0-100)
//   121 = compute_fallback_depth (Phase 16 — returns integer 0-100)
//   122 = compute_load_weight (Phase 16 — returns integer 0-100)
//   123 = compute_circuit_state (Phase 16 — returns integer 0-2)
//   130 = compute_stage_priority (Phase 17 — returns integer 0-100)
//   131 = hash_runtime_request (Phase 17 — returns hex string)
//   132 = compute_runtime_relevance (Phase 17 — returns integer 0-100)
//   133 = compute_stage_transition_cost (Phase 17 — returns integer 0-100)
std::string screenai_call(int op, const std::string& input);

} // namespace screenai

#endif // SCREENAI_CORE_H
