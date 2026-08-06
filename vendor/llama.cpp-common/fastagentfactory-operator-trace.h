#pragma once

#include <cstddef>
#include <cstdint>

namespace fastagentfactory::operator_trace {

void record_kernel_selection(const char * kernel_id);
void record_kernel_rejection(const char * kernel_id, const char * reason);

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
    bool small_k);

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
    bool fallback);

} // namespace fastagentfactory::operator_trace
