import { requestJson, withQuery } from './http'

export type BenchmarkRunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
export type BenchmarkImplementationId = 'official' | 'amd'
export type BenchmarkPromptCacheMode = 'legacy' | 'cold' | 'warm'

export interface BenchmarkImplementation {
  label: string
  revision: string
  parameters: Record<string, unknown>
}

export interface BenchmarkRunSpec {
  kind: 'performance' | 'concurrency' | 'operator_analysis'
  name: string
  profile_id: string
  prompt: string
  max_output_tokens: number
  temperature: number
  seed: number
  warmup_iterations: number
  measured_iterations: number
  telemetry_interval_ms: number
  prompt_cache_mode: BenchmarkPromptCacheMode
  implementation: BenchmarkImplementation
  concurrency?: BenchmarkConcurrencySpec | null
  operator_analysis?: BenchmarkOperatorAnalysisSpec | null
}

export interface BenchmarkConcurrencySpec {
  concurrent_requests: number
  requests_per_worker: number
  warmup_requests_per_worker: number
}

export interface BenchmarkOperatorAnalysisSpec {
  prefill_tokens: number
  decode_tokens: number
  repetitions: number
  top_kernels: number
}

export interface BenchmarkTelemetryPoint {
  elapsed_ms: number
  used_memory_bytes?: number | null
  gpu_utilization_percent?: number | null
  memory_activity_percent?: number | null
  power_watts?: number | null
  temperature_celsius?: number | null
}

export interface BenchmarkSample {
  sample_index: number
  warmup: boolean
  status: 'completed' | 'failed'
  started_at: string
  ttft_ms?: number | null
  request_to_headers_ms?: number | null
  first_event_ms?: number | null
  model_compute_ttft_ms?: number | null
  first_token_decode_ms?: number | null
  outside_model_compute_ms?: number | null
  end_to_end_ms?: number | null
  prompt_tokens?: number | null
  completion_tokens?: number | null
  cache_tokens?: number | null
  prompt_ms?: number | null
  decode_ms?: number | null
  prompt_tokens_per_second?: number | null
  decode_tokens_per_second?: number | null
  draft_tokens?: number | null
  accepted_draft_tokens?: number | null
  draft_acceptance_rate_percent?: number | null
  peak_vram_bytes?: number | null
  average_gpu_utilization_percent?: number | null
  peak_gpu_utilization_percent?: number | null
  average_power_watts?: number | null
  peak_power_watts?: number | null
  peak_temperature_celsius?: number | null
  output_text: string
  finish_reason: string
  telemetry: BenchmarkTelemetryPoint[]
  error: string
}

export interface BenchmarkMetricStats {
  count: number
  mean: number
  minimum: number
  maximum: number
  p50: number
  p95: number
  standard_deviation: number
}

export interface BenchmarkPromptCacheSummary {
  metric_version: 'legacy' | 'prompt_prefix_reuse.v1'
  prompt_tokens: number
  cached_tokens: number
  processed_tokens: number
  hit_rate_percent: number
}

export interface BenchmarkSpeculativeDecodingSummary {
  draft_tokens: number
  accepted_draft_tokens: number
  acceptance_rate_percent: number
}

export interface BenchmarkConcurrencyResult {
  concurrent_requests: number
  request_count: number
  successful_requests: number
  error_rate_percent: number
  elapsed_seconds: number
  requests_per_second: number
  input_tokens_per_second: number
  output_tokens_per_second: number
  request_latency_ms?: BenchmarkMetricStats | null
  ttft_ms?: BenchmarkMetricStats | null
}

export interface BenchmarkOperatorKernelStat {
  name: string
  display_name: string
  family: string
  descriptions: Record<string, string>
  variants: string[]
  variant_count: number
  calls: number
  total_duration_ns: number
  average_duration_ns: number
  duration_percent: number
}

export interface BenchmarkOperatorGraphStat {
  operation: string
  backend: string
  count: number
}

export interface BenchmarkCustomKernelStat {
  kernel_id: string
  display_name: string
  family: string
  descriptions: Record<string, string>
  selected_count: number
  dispatch_count: number
  fallback_count: number
  fallback_reasons: Record<string, number>
}

export interface BenchmarkOperatorDispatchVariantStat {
  operation: 'mmvq' | 'mmq'
  weight_type: string
  m: number
  n: number
  k: number
  has_ids: boolean
  has_fusion: boolean
  experts: number
  active_experts: number
  configuration: Record<string, unknown>
  calls: number
  total_duration_ns: number
  average_duration_ns: number
  duration_percent: number
}

export interface BenchmarkOperatorPhaseResult {
  phase: 'prefill' | 'decode'
  elapsed_seconds: number
  benchmark_rows: Array<Record<string, unknown>>
  top_kernels: BenchmarkOperatorKernelStat[]
  graph_operators: BenchmarkOperatorGraphStat[]
  custom_kernels: BenchmarkCustomKernelStat[]
  dispatch_variants: BenchmarkOperatorDispatchVariantStat[]
  artifact_directory: string
  warnings: string[]
}

export interface BenchmarkOperatorAnalysisResult {
  profiler: string
  gpu_graphs_disabled_for_attribution: boolean
  runtime_was_paused: boolean
  runtime_restored: boolean
  phases: BenchmarkOperatorPhaseResult[]
  warnings: string[]
}

export interface BenchmarkSummary {
  measured_samples: number
  successful_samples: number
  ttft_ms?: BenchmarkMetricStats | null
  request_to_headers_ms?: BenchmarkMetricStats | null
  first_event_ms?: BenchmarkMetricStats | null
  model_compute_ttft_ms?: BenchmarkMetricStats | null
  first_token_decode_ms?: BenchmarkMetricStats | null
  outside_model_compute_ms?: BenchmarkMetricStats | null
  end_to_end_ms?: BenchmarkMetricStats | null
  prompt_ms?: BenchmarkMetricStats | null
  decode_ms?: BenchmarkMetricStats | null
  prompt_tokens_per_second?: BenchmarkMetricStats | null
  decode_tokens_per_second?: BenchmarkMetricStats | null
  peak_vram_bytes?: BenchmarkMetricStats | null
  average_gpu_utilization_percent?: BenchmarkMetricStats | null
  peak_gpu_utilization_percent?: BenchmarkMetricStats | null
  average_power_watts?: BenchmarkMetricStats | null
  peak_power_watts?: BenchmarkMetricStats | null
  prompt_cache?: BenchmarkPromptCacheSummary | null
  speculative_decoding?: BenchmarkSpeculativeDecodingSummary | null
}

export interface BenchmarkRun {
  run_id: string
  status: BenchmarkRunStatus
  spec: BenchmarkRunSpec
  progress_completed: number
  progress_total: number
  environment: Record<string, unknown>
  samples: BenchmarkSample[]
  summary?: BenchmarkSummary | null
  concurrency?: BenchmarkConcurrencyResult | null
  operator_analysis?: BenchmarkOperatorAnalysisResult | null
  error: string
  created_at: string
  started_at: string
  completed_at: string
  updated_at: string
}

export interface BenchmarkExperimentGroupSpec {
  name: string
  profile_id: string
  prompt: string
  repetitions: number
  max_output_tokens: number
  temperature: number
  seed: number
  warmup_iterations: number
  measured_iterations: number
  telemetry_interval_ms: number
  prompt_cache_mode: BenchmarkPromptCacheMode
  concurrency: BenchmarkConcurrencySpec
  operator_analysis: BenchmarkOperatorAnalysisSpec
}

export interface BenchmarkExperimentRunRef {
  run_id: string
  repetition_index: number
  implementation: BenchmarkImplementationId
  kind: BenchmarkRunSpec['kind']
}

export interface BenchmarkExperimentGroup {
  group_id: string
  status: BenchmarkRunStatus
  spec: BenchmarkExperimentGroupSpec
  runs: BenchmarkExperimentRunRef[]
  progress_completed: number
  progress_total: number
  initial_implementation?: BenchmarkImplementationId | null
  active_implementation?: BenchmarkImplementationId | null
  error: string
  created_at: string
  started_at: string
  completed_at: string
  updated_at: string
}

export const benchmarkApi = {
  list: (limit = 100) =>
    requestJson<{ runs: BenchmarkRun[] }>(withQuery('/api/benchmarks', { limit })),
  get: (runId: string) =>
    requestJson<{ run: BenchmarkRun }>(`/api/benchmarks/${encodeURIComponent(runId)}`),
  start: (spec: BenchmarkRunSpec) =>
    requestJson<{ run: BenchmarkRun }>('/api/benchmarks', {
      method: 'POST',
      body: JSON.stringify(spec),
    }),
  cancel: (runId: string) =>
    requestJson<{ run: BenchmarkRun }>(`/api/benchmarks/${encodeURIComponent(runId)}/cancel`, {
      method: 'POST',
    }),
  delete: (runId: string) =>
    requestJson<{ deleted: boolean }>(`/api/benchmarks/${encodeURIComponent(runId)}`, {
      method: 'DELETE',
    }),
  listGroups: (limit = 100) =>
    requestJson<{
      groups: BenchmarkExperimentGroup[]
      runs: Record<string, BenchmarkRun[]>
    }>(withQuery('/api/benchmarks/groups', { limit })),
  getGroup: (groupId: string) =>
    requestJson<{ group: BenchmarkExperimentGroup; runs: BenchmarkRun[] }>(
      `/api/benchmarks/groups/${encodeURIComponent(groupId)}`,
    ),
  startGroup: (spec: BenchmarkExperimentGroupSpec) =>
    requestJson<{ group: BenchmarkExperimentGroup }>('/api/benchmarks/groups', {
      method: 'POST',
      body: JSON.stringify(spec),
    }),
  deleteGroup: (groupId: string) =>
    requestJson<{ deleted: boolean }>(`/api/benchmarks/groups/${encodeURIComponent(groupId)}`, {
      method: 'DELETE',
    }),
}
