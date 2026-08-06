#include "fastagentfactory-operator-trace.h"

#include <cstdio>
#include <cstdlib>
#include <map>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

namespace fastagentfactory::operator_trace {
namespace {

struct DispatchRecord {
    std::string operation;
    std::string weight_type;
    int64_t m = 0;
    int64_t n = 0;
    int64_t k = 0;
    bool has_ids = false;
    bool has_fusion = false;
    int64_t experts = 0;
    int64_t active_experts = 0;
    int nwarps = 0;
    int rows_per_block = 0;
    int parameter_table_id = 0;
    bool small_k = false;
    int nthreads = 0;
    int occupancy = 0;
    int tile_i = 0;
    int tile_j = 0;
    int tile_k = 0;
    std::size_t shared_memory_bytes = 0;
    bool stream_k = false;
    bool fallback = false;
};

struct KernelRecord {
    std::size_t selected_count = 0;
    std::size_t fallback_count = 0;
    std::map<std::string, std::size_t> fallback_reasons;
};

void write_json_string(FILE * output, const std::string & value) {
    std::fputc('"', output);
    for (const unsigned char character : value) {
        switch (character) {
            case '"': std::fputs("\\\"", output); break;
            case '\\': std::fputs("\\\\", output); break;
            case '\b': std::fputs("\\b", output); break;
            case '\f': std::fputs("\\f", output); break;
            case '\n': std::fputs("\\n", output); break;
            case '\r': std::fputs("\\r", output); break;
            case '\t': std::fputs("\\t", output); break;
            default:
                if (character < 0x20) {
                    std::fprintf(output, "\\u%04x", static_cast<unsigned int>(character));
                } else {
                    std::fputc(character, output);
                }
        }
    }
    std::fputc('"', output);
}

class TraceStore {
public:
    TraceStore() {
        const char * configured_path = std::getenv("AGENTFACTORY_KERNEL_TRACE_OUTPUT");
        if (configured_path != nullptr && configured_path[0] != '\0') {
            output_path_ = configured_path;
        }
    }

    ~TraceStore() {
        flush();
    }

    bool enabled() const {
        return !output_path_.empty();
    }

    void append(DispatchRecord record) {
        if (!enabled()) {
            return;
        }
        std::lock_guard<std::mutex> lock(mutex_);
        records_.push_back(std::move(record));
    }

    void record_kernel_selection(const std::string & kernel_id) {
        if (!enabled()) {
            return;
        }
        std::lock_guard<std::mutex> lock(mutex_);
        ++kernels_[kernel_id].selected_count;
    }

    void record_kernel_rejection(const std::string & kernel_id, const std::string & reason) {
        if (!enabled()) {
            return;
        }
        std::lock_guard<std::mutex> lock(mutex_);
        KernelRecord & record = kernels_[kernel_id];
        ++record.fallback_count;
        ++record.fallback_reasons[reason];
    }

private:
    void flush() noexcept {
        if (!enabled()) {
            return;
        }
        std::lock_guard<std::mutex> lock(mutex_);
        FILE * output = std::fopen(output_path_.c_str(), "wb");
        if (output == nullptr) {
            std::fprintf(stderr, "FastAgentFactory operator trace could not open %s\n", output_path_.c_str());
            return;
        }
        std::fputs("{\n  \"schema_version\": 1,\n  \"kernels\": [", output);
        std::size_t kernel_index = 0;
        for (const auto & [kernel_id, record] : kernels_) {
            std::fputs(kernel_index++ == 0 ? "\n    {\n      \"kernel_id\": " : ",\n    {\n      \"kernel_id\": ", output);
            write_json_string(output, kernel_id);
            std::fprintf(
                output,
                ",\n      \"selected_count\": %zu,\n"
                "      \"dispatch_count\": %zu,\n"
                "      \"fallback_count\": %zu,\n"
                "      \"fallback_reasons\": {",
                record.selected_count,
                record.selected_count,
                record.fallback_count);
            std::size_t reason_index = 0;
            for (const auto & [reason, count] : record.fallback_reasons) {
                std::fputs(reason_index++ == 0 ? "\n        " : ",\n        ", output);
                write_json_string(output, reason);
                std::fprintf(output, ": %zu", count);
            }
            std::fputs(record.fallback_reasons.empty() ? "}\n    }" : "\n      }\n    }", output);
        }
        std::fputs(kernels_.empty() ? "],\n  \"dispatches\": [" : "\n  ],\n  \"dispatches\": [", output);
        for (std::size_t index = 0; index < records_.size(); ++index) {
            const DispatchRecord & row = records_[index];
            std::fputs(index == 0 ? "\n    {\n" : ",\n    {\n", output);
            std::fprintf(output, "      \"sequence\": %zu,\n      \"operation\": ", index);
            write_json_string(output, row.operation);
            std::fputs(",\n      \"weight_type\": ", output);
            write_json_string(output, row.weight_type);
            std::fprintf(
                output,
                ",\n      \"m\": %lld,\n      \"n\": %lld,\n      \"k\": %lld,\n"
                "      \"has_ids\": %s,\n      \"has_fusion\": %s,\n"
                "      \"experts\": %lld,\n      \"active_experts\": %lld,\n"
                "      \"configuration\": {",
                static_cast<long long>(row.m),
                static_cast<long long>(row.n),
                static_cast<long long>(row.k),
                row.has_ids ? "true" : "false",
                row.has_fusion ? "true" : "false",
                static_cast<long long>(row.experts),
                static_cast<long long>(row.active_experts));
            if (row.operation == "mmvq") {
                std::fprintf(
                    output,
                    "\n        \"nwarps\": %d,\n        \"rows_per_block\": %d,\n"
                    "        \"parameter_table_id\": %d,\n        \"small_k\": %s\n",
                    row.nwarps,
                    row.rows_per_block,
                    row.parameter_table_id,
                    row.small_k ? "true" : "false");
            } else {
                std::fprintf(
                    output,
                    "\n        \"nthreads\": %d,\n        \"occupancy\": %d,\n"
                    "        \"tile_i\": %d,\n        \"tile_j\": %d,\n        \"tile_k\": %d,\n"
                    "        \"nwarps\": %d,\n        \"shared_memory_bytes\": %zu,\n"
                    "        \"stream_k\": %s,\n        \"fallback\": %s\n",
                    row.nthreads,
                    row.occupancy,
                    row.tile_i,
                    row.tile_j,
                    row.tile_k,
                    row.nwarps,
                    row.shared_memory_bytes,
                    row.stream_k ? "true" : "false",
                    row.fallback ? "true" : "false");
            }
            std::fputs("      }\n    }", output);
        }
        std::fputs(records_.empty() ? "]\n}\n" : "\n  ]\n}\n", output);
        std::fclose(output);
    }

    std::string output_path_;
    std::mutex mutex_;
    std::map<std::string, KernelRecord> kernels_;
    std::vector<DispatchRecord> records_;
};

TraceStore & trace_store() {
    static TraceStore store;
    return store;
}

} // namespace

void record_kernel_selection(const char * kernel_id) {
    if (kernel_id == nullptr || kernel_id[0] == '\0') {
        return;
    }
    TraceStore & store = trace_store();
    if (!store.enabled()) {
        return;
    }
    store.record_kernel_selection(kernel_id);
}

void record_kernel_rejection(const char * kernel_id, const char * reason) {
    if (kernel_id == nullptr || kernel_id[0] == '\0' || reason == nullptr || reason[0] == '\0') {
        return;
    }
    TraceStore & store = trace_store();
    if (!store.enabled()) {
        return;
    }
    store.record_kernel_rejection(kernel_id, reason);
}

void record_mmvq(
        const char * weight_type,
        int64_t m,
        int64_t n,
        int64_t k,
        bool has_ids,
        bool has_fusion,
        int64_t experts,
        int64_t active_experts,
        int nwarps,
        int rows_per_block,
        int parameter_table_id,
        bool small_k) {
    TraceStore & store = trace_store();
    if (!store.enabled()) {
        return;
    }
    DispatchRecord record;
    record.operation = "mmvq";
    record.weight_type = weight_type != nullptr ? weight_type : "unknown";
    record.m = m;
    record.n = n;
    record.k = k;
    record.has_ids = has_ids;
    record.has_fusion = has_fusion;
    record.experts = experts;
    record.active_experts = active_experts;
    record.nwarps = nwarps;
    record.rows_per_block = rows_per_block;
    record.parameter_table_id = parameter_table_id;
    record.small_k = small_k;
    store.append(std::move(record));
}

void record_mmq(
        const char * weight_type,
        int64_t m,
        int64_t n,
        int64_t k,
        bool has_ids,
        int64_t experts,
        int64_t active_experts,
        int nthreads,
        int occupancy,
        int tile_i,
        int tile_j,
        int tile_k,
        int nwarps,
        std::size_t shared_memory_bytes,
        bool stream_k,
        bool fallback) {
    TraceStore & store = trace_store();
    if (!store.enabled()) {
        return;
    }
    DispatchRecord record;
    record.operation = "mmq";
    record.weight_type = weight_type != nullptr ? weight_type : "unknown";
    record.m = m;
    record.n = n;
    record.k = k;
    record.has_ids = has_ids;
    record.experts = experts;
    record.active_experts = active_experts;
    record.nthreads = nthreads;
    record.occupancy = occupancy;
    record.tile_i = tile_i;
    record.tile_j = tile_j;
    record.tile_k = tile_k;
    record.nwarps = nwarps;
    record.shared_memory_bytes = shared_memory_bytes;
    record.stream_k = stream_k;
    record.fallback = fallback;
    store.append(std::move(record));
}

} // namespace fastagentfactory::operator_trace
