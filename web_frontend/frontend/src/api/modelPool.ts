import { requestJson, withQuery } from './http'

export type LocalModelKind = 'chat' | 'embedding' | 'image_generation'
export type LocalInferenceEngine = 'llama_cpp_rocm' | 'transformers_rocm' | 'stable_diffusion_cpp_rocm' | 'external'
export type LocalModelDefaultRole = 'main' | 'task' | 'compression' | 'embedding' | 'image_generation'
export type ModelUsageGroupBy = 'model' | 'provider' | 'agent'

export type LocalModelDefaults = Record<LocalModelDefaultRole, string | null>

export interface ModelSelectionRequirement {
  role: 'main' | 'task' | 'compression'
  purpose?: string
  kind?: LocalModelKind
  input_modalities?: string[]
  output_modalities?: string[]
  tool_calling?: boolean
  structured_output_methods?: string[]
  reasoning_required?: boolean
  min_context_window_tokens?: number
  excluded_profile_ids?: string[]
  optimize_for?: 'balanced' | 'quality' | 'latency' | 'context'
  max_candidates?: number
}

export interface ModelSelectionRequest {
  requirements?: ModelSelectionRequirement[]
  tool_requirements?: Array<Record<string, unknown>>
}

export interface ModelSelectionResult {
  status: 'completed' | 'blocked'
  recommendations: Array<{
    role: 'main' | 'task' | 'compression'
    profile_id: string
    display_name: string
    model_name: string
    score: number
    reason: string
  }>
  tool_recommendations: Array<Record<string, unknown>>
  unmatched: Array<Record<string, unknown>>
  profile_count: number
  enabled_profile_count: number
}

export interface LocalEngine {
  engine: LocalInferenceEngine
  display_name: string
  kind: LocalModelKind
  transport: string
  parameters: Record<string, unknown>
}

export interface LocalModelArtifact {
  artifact_id: string
  display_name: string
  kind: LocalModelKind
  source: 'local_storage' | 'external_endpoint'
  local_path?: string | null
  external_model_id?: string | null
  model_format: string
  revision: string
  checksum: string
  license: string
  native_context_tokens?: number | null
  context_extension?: ModelContextExtensionCapability | null
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface ModelContextExtensionCapability {
  method: 'yarn'
  max_context_tokens: number
}

export interface LocalModelArtifactWritePayload {
  artifact_id?: string
  display_name: string
  kind: LocalModelKind
  source: 'local_storage' | 'external_endpoint'
  local_path: string | null
  external_model_id: string | null
  model_format: string
  revision: string
  checksum: string
  native_context_tokens: number | null
  context_extension: ModelContextExtensionCapability | null
  enabled: boolean
}

export interface LocalModelDirectory {
  relative_path: string
  absolute_path: string
  display_name: string
  model_type: string
  dtype: string
  embedding_dimensions?: number | null
  architectures: string[]
  tokenizer_available: boolean
  supported_kinds: LocalModelKind[]
}

export interface LocalModelStorage {
  inference_mode: 'managed' | 'external'
  root_path: string
  modelscope_cache_path: string
  directories: LocalModelDirectory[]
  remote_models: RemoteInferenceModel[]
  remote_error: string
}

export interface RemoteInferenceModel {
  model_id: string
  profile_id?: string
  kind: LocalModelKind
  engine?: LocalInferenceEngine
  capabilities: string[]
  format: string
  revision?: string
  checksum?: string
  runtime_configuration?: Record<string, unknown>
  context_length?: number | null
  native_context_tokens?: number | null
  context_extension?: ModelContextExtensionCapability | null
  parameter_count?: number | null
  size_bytes?: number | null
  embedding_dimensions?: number | null
  memory_estimate?: InferenceMemoryEstimate | null
}

export interface LlamaCppRuntimeConfiguration {
  gpu_layers: number
  parallel_slots: number
  per_slot_context_tokens?: number | null
  server_context_tokens?: number | null
  cache_type_k: string
  cache_type_v: string
  flash_attention: boolean
  mmproj_path?: string | null
  speculative_decoding: LlamaCppSpeculativeDecodingConfiguration
  rope_scaling?: {
    method: string
    original_context_tokens: number
    target_context_tokens: number
    factor: number
  } | null
}

export interface LlamaCppMtpConfiguration {
  method: 'mtp'
  max_draft_tokens: number
  min_draft_tokens: number
  min_acceptance_probability: number
  backend_sampling: boolean
}

export interface LlamaCppSpeculativeDecodingDisabledConfiguration {
  method: 'disabled'
}

export type LlamaCppSpeculativeDecodingConfiguration =
  | LlamaCppSpeculativeDecodingDisabledConfiguration
  | LlamaCppMtpConfiguration

export interface TransformersRuntimeConfiguration {
  trust_remote_code: boolean
}

export interface StableDiffusionCppRuntimeConfiguration {
  vae_path: string
  clip_l_path: string
  t5xxl_path: string
  diffusion_flash_attention: boolean
  eager_load: boolean
  clip_on_cpu: boolean
  vae_tiling: boolean
  offload_to_cpu: boolean
  max_vram_gib?: number | null
  stream_layers?: number | null
  default_width: number
  default_height: number
  default_steps: number
  default_cfg_scale: number
  default_sampler: string
  residency_policy: 'coexist_if_fit' | 'exclusive'
}

export interface InferenceMemoryEstimate {
  available: boolean
  model_id: string
  context_tokens?: number | null
  total_context_tokens?: number | null
  native_context_tokens?: number | null
  max_context_tokens?: number | null
  rope_scaling_method?: string | null
  rope_scaling_factor?: number | null
  parallel_slots: number
  cache_type_k: string
  cache_type_v: string
  model_allocation_bytes?: number | null
  kv_cache_bytes?: number | null
  current_used_bytes?: number | null
  projected_used_bytes?: number | null
  total_memory_bytes?: number | null
  remaining_memory_bytes?: number | null
  utilization_percent?: number | null
  fits?: boolean | null
  basis: string
  error: string
}

interface LocalModelProfileBase {
  profile_id: string
  display_name: string
  description: string
  artifact_id: string
  served_model_name: string
  enabled: boolean
  capabilities: {
    input_modalities: string[]
    output_modalities: string[]
    tool_calling: boolean
    streaming_tool_calls: boolean
    strict_tool_schema: boolean
    structured_output_methods: string[]
    reasoning_supported: boolean
    reasoning_efforts: string[]
    reasoning_content: boolean
    cache_usage: boolean
    text_to_image: boolean
    image_to_image: boolean
    image_edit: boolean
    batch_generation: boolean
    async_job: boolean
  }
  settings: {
    temperature?: number | null
  }
  limits: {
    max_input_tokens?: number | null
    max_output_tokens?: number | null
    timeout_seconds?: number | null
    context_compression_threshold_tokens?: number | null
  }
  embedding_dimensions?: number | null
  normalize_embeddings: boolean
  notes: string
  artifact?: LocalModelArtifact | null
}

export interface LocalChatModelProfile extends LocalModelProfileBase {
  kind: 'chat'
  engine: 'llama_cpp_rocm' | 'external'
  inference: {
    gpu_layers: number
    parallel_slots: number
    cache_type_k: string
    cache_type_v: string
    flash_attention: boolean
    mmproj_path?: string | null
    speculative_decoding: LlamaCppSpeculativeDecodingConfiguration
  } | {
    external: true
    remote_inference?: LlamaCppRuntimeConfiguration | null
  }
}

export interface LocalEmbeddingModelProfile extends LocalModelProfileBase {
  kind: 'embedding'
  engine: 'transformers_rocm' | 'external'
  inference: {
    trust_remote_code: boolean
  } | {
    external: true
    remote_inference?: TransformersRuntimeConfiguration | null
  }
}

export interface LocalImageGenerationProfile extends LocalModelProfileBase {
  kind: 'image_generation'
  engine: 'stable_diffusion_cpp_rocm' | 'external'
  inference: StableDiffusionCppRuntimeConfiguration | {
    external: true
    remote_inference?: StableDiffusionCppRuntimeConfiguration | null
  }
}

export type LocalModelProfile = LocalChatModelProfile | LocalEmbeddingModelProfile | LocalImageGenerationProfile
export type ModelPoolProfile = LocalModelProfile

export function isAvailableChatModelProfile(
  profile: LocalModelProfile,
): profile is LocalChatModelProfile {
  if (profile.kind !== 'chat' || !profile.enabled) return false
  return isAvailableModelArtifact(profile.artifact, 'chat')
}

export function isAvailableEmbeddingModelProfile(
  profile: LocalModelProfile,
): profile is LocalEmbeddingModelProfile {
  if (profile.kind !== 'embedding' || !profile.enabled) return false
  return isAvailableModelArtifact(profile.artifact, 'embedding')
}

function isAvailableModelArtifact(
  artifact: LocalModelArtifact | null | undefined,
  kind: LocalModelKind,
): boolean {
  if (!artifact?.enabled || artifact.kind !== kind) return false
  if (artifact.source === 'local_storage') {
    return Boolean(artifact.local_path?.trim())
  }
  return Boolean(artifact.external_model_id?.trim())
}

export async function resolveRuntimeMainModelProfileId(
  profiles: LocalModelProfile[],
  preferredProfileId?: string | null,
): Promise<string> {
  const availableProfiles = profiles.filter(isAvailableChatModelProfile)
  if (availableProfiles.length === 0) return ''

  const availableIds = new Set(availableProfiles.map(profile => profile.profile_id))
  const preferredId = String(preferredProfileId || '').trim()
  if (availableIds.has(preferredId)) return preferredId

  try {
    const configuredId = String((await modelPoolApi.defaults()).defaults.main || '').trim()
    if (availableIds.has(configuredId)) return configuredId
  } catch {
    // The loaded profiles remain usable when optional defaults are unavailable.
  }

  try {
    const selection = await modelPoolApi.select({
      requirements: [{
        role: 'main',
        purpose: 'Runtime main conversation model',
        kind: 'chat',
        input_modalities: ['text'],
        output_modalities: ['text'],
        tool_calling: true,
        structured_output_methods: ['json_mode', 'function_calling'],
        optimize_for: 'balanced',
      }],
    })
    const recommendedId = String(
      selection.recommendations.find(item => item.role === 'main')?.profile_id || '',
    ).trim()
    if (availableIds.has(recommendedId)) return recommendedId
  } catch {
    // Fall back to the first available profile when recommendation is unavailable.
  }
  return availableProfiles[0].profile_id
}

export type LocalModelRuntimePhase = 'idle' | 'starting' | 'loading' | 'ready' | 'stopping' | 'failed'

export interface LocalModelRuntime {
  kind: LocalModelKind
  mode: 'managed' | 'external'
  profile_id: string
  phase: LocalModelRuntimePhase
  stage: string
  progress_percent?: number | null
  pid?: number | null
  error: string
  started_at: string
  updated_at: string
  logs: string[]
}

export interface LocalModelRuntimeSummary {
  runtimes: LocalModelRuntime[]
  rocm: RocmRuntimeInfo
}

export interface RocmRuntimeInfo {
  available: boolean
  torch_version: string
  hip_version: string
  rocm_version: string
  device_count: number
  devices: RocmDeviceInfo[]
  telemetry_source: string
  error: string
}

export interface RocmDeviceInfo {
  index: number
  name: string
  total_memory_bytes: number
  used_memory_bytes?: number | null
  gpu_utilization_percent?: number | null
  gpu_utilization_source?: string
  memory_activity_percent?: number | null
  temperature_edge_celsius?: number | null
  temperature_hotspot_celsius?: number | null
  temperature_memory_celsius?: number | null
  power_watts?: number | null
  architecture: string
  pci_bus: string
  pci_device_id: string
  vram_type: string
  compute_units?: number | null
}

export type LlamaImplementationId = 'official' | 'amd'

export interface LlamaImplementationBuild {
  implementation: LlamaImplementationId
  display_name: string
  source_revision: string
  source_build_number: number
  source_sha256: string
  binary_path: string
  binary_sha256: string
  benchmark_binary_path: string
  benchmark_binary_sha256: string
  kernel_catalog_path: string
  kernel_catalog_sha256: string
  custom_kernels: boolean
  optimization_status: 'baseline' | 'placeholder' | 'experimental' | 'optimized'
  build_options: Record<string, unknown>
  built_at: string
}

export interface LlamaImplementationStatus {
  available: boolean
  active?: LlamaImplementationId | null
  active_build?: LlamaImplementationBuild | null
  builds: LlamaImplementationBuild[]
  error: string
}

export interface ModelUsageTotals {
  call_count: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  reasoning_tokens: number
  cache_hit_tokens: number
  cache_miss_tokens: number
  cache_hit_ratio: number | null
  estimated_cost: number | null
}

export interface ModelUsageGroup {
  key: string
  label: string
  provider: string
  provider_display_name: string
  model_name: string
  model_profile_id: string
  agent_id: string
  agent_label: string
  totals: ModelUsageTotals
}

export interface ModelUsageSeries {
  key: string
  label: string
  points: Array<{ bucket: string } & ModelUsageTotals>
}

export interface ModelUsageSummary {
  group_by: ModelUsageGroupBy
  since: string
  until: string
  totals: ModelUsageTotals
  groups: ModelUsageGroup[]
  series: ModelUsageSeries[]
}

export const modelPoolApi = {
  engines: () => requestJson<{ engines: LocalEngine[] }>('/api/model-pool/engines'),
  runtimes: () => requestJson<LocalModelRuntimeSummary>('/api/model-pool/runtimes'),
  rocmRuntime: () => requestJson<RocmRuntimeInfo>('/api/model-pool/runtime/rocm'),
  llamaRuntime: () => requestJson<LlamaImplementationStatus>('/api/model-pool/runtime/llama'),
  activateLlamaImplementation: (implementation: LlamaImplementationId) =>
    requestJson<{ implementation: LlamaImplementationStatus; runtime: LocalModelRuntime }>(
      '/api/model-pool/runtime/llama/activate',
      {
        method: 'POST',
        body: JSON.stringify({ implementation }),
      },
    ),
  storage: () => requestJson<LocalModelStorage>('/api/model-pool/storage'),
  defaults: () => requestJson<{ defaults: LocalModelDefaults }>('/api/model-pool/defaults'),
  setDefault: (role: LocalModelDefaultRole, profileId: string) =>
    requestJson<{ role: LocalModelDefaultRole; profile_id: string | null }>(
      `/api/model-pool/defaults/${encodeURIComponent(role)}`,
      {
        method: 'PUT',
        body: JSON.stringify({ profile_id: profileId }),
      },
    ),
  artifacts: () => requestJson<{ artifacts: LocalModelArtifact[] }>('/api/model-pool/artifacts'),
  saveArtifact: (payload: LocalModelArtifactWritePayload) =>
    requestJson<{ artifact: LocalModelArtifact }>('/api/model-pool/artifacts', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  patchArtifact: (artifactId: string, payload: LocalModelArtifactWritePayload) =>
    requestJson<{ artifact: LocalModelArtifact }>(`/api/model-pool/artifacts/${encodeURIComponent(artifactId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteArtifact: (artifactId: string) =>
    requestJson<{ deleted: boolean }>(`/api/model-pool/artifacts/${encodeURIComponent(artifactId)}`, {
      method: 'DELETE',
    }),
  profiles: () => requestJson<{ profiles: LocalModelProfile[] }>('/api/model-pool/profiles'),
  select: (payload: ModelSelectionRequest) =>
    requestJson<ModelSelectionResult>('/api/model-pool/select', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  estimateMemory: (payload: Record<string, unknown>) =>
    requestJson<{ estimate: InferenceMemoryEstimate }>('/api/model-pool/memory-estimate', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  saveProfile: (payload: Record<string, unknown>) =>
    requestJson<{ profile: LocalModelProfile; runtime: LocalModelRuntime }>('/api/model-pool/profiles', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  patchProfile: (profileId: string, payload: Record<string, unknown>) =>
    requestJson<{ profile: LocalModelProfile; runtime: LocalModelRuntime }>(`/api/model-pool/profiles/${encodeURIComponent(profileId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteProfile: (profileId: string) =>
    requestJson<{ deleted: boolean }>(`/api/model-pool/profiles/${encodeURIComponent(profileId)}`, {
      method: 'DELETE',
    }),
  loadProfile: (profileId: string) =>
    requestJson<{ runtime: LocalModelRuntime }>(`/api/model-pool/profiles/${encodeURIComponent(profileId)}/load`, {
      method: 'POST',
    }),
  unloadProfile: (profileId: string) =>
    requestJson<{ runtime: LocalModelRuntime }>(`/api/model-pool/profiles/${encodeURIComponent(profileId)}/unload`, {
      method: 'POST',
    }),
  restartProfile: (profileId: string) =>
    requestJson<{ runtime: LocalModelRuntime }>(`/api/model-pool/profiles/${encodeURIComponent(profileId)}/restart`, {
      method: 'POST',
    }),
  usage: (params: { groupBy?: ModelUsageGroupBy; days?: number } = {}) =>
    requestJson<ModelUsageSummary>(
      withQuery('/api/model-pool/usage', { group_by: params.groupBy, days: params.days }),
    ),
}
