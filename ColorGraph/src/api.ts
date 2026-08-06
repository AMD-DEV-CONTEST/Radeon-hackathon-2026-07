import type {
  LookId,
  PreviewPlaybackProfile,
  PreviewPlaybackTelemetry,
} from "./types";

const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8010"
).replace(/\/$/, "");

export type RuntimeKind = "cuda" | "rocm" | "cpu";
export type JobStatus = "queued" | "running" | "completed" | "failed";
export type InputColorProfile =
  | "rec709"
  | "sony_slog3_sgamut3cine"
  | "dji_mavic3_dlog_rec709_v1";

export const INPUT_COLOR_PROFILE_LABELS: Record<InputColorProfile, string> = {
  rec709: "Rec.709",
  sony_slog3_sgamut3cine: "Sony S-Log3 / S-Gamut3.Cine",
  dji_mavic3_dlog_rec709_v1:
    "DJI Mavic 3 D-Log / D-Gamut（官方 Rec.709）",
};

function colorManagementPayload(profile: InputColorProfile) {
  return {
    inputColorSpace: profile === "rec709" ? "bt709_oetf" : "log",
    sourceLogProfile: profile === "rec709" ? null : profile,
  } as const;
}

export interface DeviceInfo {
  available: boolean;
  runtime: RuntimeKind;
  vendor: string;
  name: string;
  index: number | null;
  total_memory_mb: number | null;
  allocated_memory_mb: number | null;
  reserved_memory_mb: number | null;
  torch_version: string;
  runtime_version: string | null;
  capability: string | null;
  migration_compatible: boolean;
}

export interface TimeRange {
  start_seconds: number;
  end_seconds: number;
}

export interface BackendKeyframe {
  time_seconds: number;
  value: number;
}

export interface BackendTrack {
  parameter: string;
  keyframes: BackendKeyframe[];
  interpolation: "hold" | "linear" | "pchip" | "cubic_spline";
  max_velocity: number | null;
  max_acceleration: number | null;
}

export interface BackendNode {
  id: string;
  type:
    | "input_transform"
    | "balance"
    | "tone"
    | "masked_grade"
    | "look"
    | "post_look"
    | "output_transform";
  label: string;
  order: number;
  enabled: boolean;
  temporal_scope: {
    level: "project" | "scene" | "shot" | "sub_shot";
    project_id: string;
    scene_id: string | null;
    shot_id: string | null;
    sub_shot_id: string | null;
    time_range: TimeRange | null;
  };
  spatial_scope: {
    kind: string;
    target: string;
    mask_asset_id: string | null;
    expression: string | null;
  };
  parameters: Record<string, string | number | boolean>;
  tracks: BackendTrack[];
  metadata: Record<string, unknown>;
}

export interface BackendShot {
  id: string;
  scene_id: string;
  index: number;
  time_range: TimeRange;
  representative_frame: string | null;
  lighting_change_points: number[];
}

export interface BackendMask {
  id: string;
  kind: string;
  target: string;
  path: string;
  confidence: number | null;
  frame_count: number | null;
  metadata: Record<string, unknown>;
}

export interface MetadataEvidence {
  source:
    | "stream"
    | "container"
    | "pixel_format"
    | "side_data"
    | "user_override"
    | "default"
    | "missing";
  confidence: "high" | "medium" | "low" | "unknown";
  reported_values: string[];
  conflict: boolean;
  note: string | null;
}

export interface MediaMetadataEvidence {
  color_range: MetadataEvidence;
  color_primaries: MetadataEvidence;
  color_transfer: MetadataEvidence;
  color_matrix: MetadataEvidence;
  bit_depth: MetadataEvidence;
  chroma_subsampling: MetadataEvidence;
  chroma_location: MetadataEvidence;
  hdr_metadata: MetadataEvidence;
  input_color_space: MetadataEvidence;
  source_log_profile: MetadataEvidence;
}

export interface HdrMetadata {
  format: string | null;
  mastering_display: {
    red: { x: number; y: number };
    green: { x: number; y: number };
    blue: { x: number; y: number };
    white_point: { x: number; y: number };
    min_luminance: number;
    max_luminance: number;
  } | null;
  content_light: {
    max_content_light_level: number;
    max_frame_average_light_level: number;
  } | null;
  side_data_types: string[];
}

export interface GradeGraph {
  schema_version: string;
  renderer_version: string;
  id: string;
  project_id: string;
  project_name: string;
  created_at: string;
  updated_at: string;
  working_color_space: string;
  output_color_space: string;
  media: {
    path: string;
    duration_seconds: number;
    width: number;
    height: number;
    fps: number;
    frame_count: number;
    codec: string;
    pixel_format: string | null;
    color_range: string | null;
    color_primaries: string | null;
    color_transfer: string | null;
    color_matrix: string | null;
    bit_depth: number | null;
    chroma_subsampling: string | null;
    chroma_location: string | null;
    hdr_metadata: HdrMetadata;
    metadata_evidence: MediaMetadataEvidence;
    input_color_space: string;
    source_log_profile: string | null;
  };
  scenes: Array<{
    id: string;
    index: number;
    label: string;
    shot_ids: string[];
    look_node_id: string | null;
  }>;
  shots: BackendShot[];
  nodes: BackendNode[];
  masks: BackendMask[];
  metadata: Record<string, unknown>;
}

export interface JobRecord {
  id: string;
  kind: string;
  project_id: string;
  status: JobStatus;
  stage: string;
  progress: number;
  message: string;
  device: string;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface QualityCheck {
  id: string;
  label: string;
  status: "pass" | "warn" | "fail";
  value: number;
  threshold: number;
  unit: string;
  detail: string;
  category?: "hard_technical" | "perceptual_risk" | "aesthetic_preference";
  metric_version?: string;
}

export interface AuxiliaryQualityScore {
  id: string;
  kind: "perceptual_risk" | "aesthetic_preference";
  value: number;
  provider: string;
  model_id: string;
  model_revision: string;
  calibration_id: string;
  calibration_digest: string;
  domain_calibrated: boolean;
  detail: string;
}

export interface QualityReport {
  score: number;
  hard_checks_passed: boolean;
  sampled_frames: number;
  checks: QualityCheck[];
  summary: string;
  metrics: Record<string, number>;
  technical_score?: number;
  perceptual_risk_score?: number;
  technical_hard_failures?: string[];
  perceptual_risks?: string[];
  auxiliary_scores?: AuxiliaryQualityScore[];
  aesthetic_preferences?: AuxiliaryQualityScore[];
}

export interface CommandPlan {
  graph: GradeGraph;
  undo_graph: GradeGraph;
  edits: Array<{
    node_id: string;
    operation: string;
    parameters: Record<string, string | number | boolean>;
    affected_range: TimeRange;
  }>;
  required_mask_targets: string[];
  invalidated_ranges: TimeRange[];
  explanation: string;
  planner: string;
}

export type LookRecipeParameters = Record<
  "strength" | "contrast" | "saturation" | "temperature" | "highlights",
  number
>;

export interface LookRecipe {
  id: LookId;
  label: string;
  parameters: LookRecipeParameters;
}

export interface LookRecipeCatalog {
  schema_version: string;
  recipe_version: string;
  recipes: LookRecipe[];
}

export interface LookCandidate {
  recipe_id: LookId;
  recipe_version: string;
  label: string;
  parameters: LookRecipeParameters;
  url: string;
  intent_score: number;
  semantic_prior: number;
  technical_score: number;
  /** Compatibility mirror of technical_score; ranking v2 does not select on it. */
  combined_score: number;
  aesthetic_score: number;
  conservatism_score: number;
  objective_values: Record<string, number>;
  hard_checks_passed: boolean;
  hard_failures: Array<{
    check_id: string;
    sample_index: number;
    frame_index: number;
    time_seconds: number;
    observed: number;
    threshold: number;
    requirement: string;
    detail: string;
  }>;
  pareto_rank: number | null;
  pareto_front: boolean;
  dominated_by: string[];
  pairwise_wins: number;
  metrics: Record<string, number>;
  sample_evidence: Array<{
    sample_index: number;
    frame_index: number;
    time_seconds: number;
    reasons: string[];
    filename: string;
    intent_score: number;
    metrics: Record<string, number>;
    hard_failure_ids: string[];
  }>;
}

export interface CandidateComparison {
  time_seconds: number;
  prompt: string;
  canonical_intent: string;
  graph_digest: string;
  recipe_version: string;
  ranking_version: string;
  recommended_id: LookCandidate["recipe_id"];
  recommendation_status: string;
  candidates: LookCandidate[];
  sample_frame_indices: number[];
  sample_timestamps: number[];
  pareto_recipe_ids: string[];
  selection_evidence: Array<{
    recipe_id: LookCandidate["recipe_id"];
    selected: boolean;
    hard_checks_passed: boolean;
    pareto_rank: number | null;
    dominated_by: string[];
    rejection_reasons: string[];
  }>;
  comparison_method: string;
  device_runtime: RuntimeKind;
}

export type CreativeAgentStage =
  | "idle"
  | "analyzing"
  | "interpreting"
  | "retrieving"
  | "compiling"
  | "rendering"
  | "criticizing"
  | "refining"
  | "ready";

export type CreativeAgentRunStatus =
  | "idle"
  | "running"
  | "waiting_for_consent"
  | "ready_for_review"
  | "failed"
  | "cancelled"
  | "offline_fallback";

export interface CreativeAgentEvidence {
  evidence_id: string;
  label: string;
  role: "support" | "counterevidence" | "source" | "current" | "candidate";
  scene_id: string | null;
  shot_id: string | null;
  frame_index: number | null;
  thumbnail_url: string | null;
}

export interface CreativeAgentDirection {
  brief_id: string;
  direction: "faithful" | "amplified" | "counterpoint";
  title: string;
  interpretation: string;
  emotional_target: string;
  support_evidence_ids: string[];
  counterevidence_ids: string[];
  protections: string[];
  intentional_exceptions: string[];
  failure_conditions: string[];
  candidate_id: string | null;
  candidate_thumbnail_urls: string[];
  qc_status: "pending" | "pass" | "fail";
  critique: Array<{
    dimension:
      | "concept_alignment"
      | "scene_support"
      | "visual_hierarchy"
      | "expressive_strength"
      | "naturalness"
      | "distinctiveness"
      | "overgrading_risk"
      | "context_consistency";
    score: number;
    confidence: number;
    concise_reason: string;
  }>;
  is_pareto: boolean;
  is_preferred: boolean;
  is_runner_up: boolean;
  application_scopes: Array<{
    project_id: string;
    scene_id: string | null;
    shot_id: string | null;
    time_range: TimeRange | null;
    mask_target: string | null;
  }>;
  refinement: {
    patch_id: string;
    status: string;
    hypothesis: string;
    changes: string[];
    rollback_available: boolean;
  } | null;
}

export interface CreativeAgentSnapshot {
  schema_version: "colorgraph.creative-agent-ui/v1";
  project_id: string;
  run_id: string;
  snapshot_revision: number;
  snapshot_digest: string;
  status: CreativeAgentRunStatus;
  stage: CreativeAgentStage;
  progress: number;
  message: string;
  updated_at: string;
  shadow_mode: boolean;
  current_graph_digest: string;
  current_graph_unchanged: boolean;
  offline_available: boolean;
  project_visual_thesis: string | null;
  palette_character: string | null;
  contrast_character: string | null;
  provider: {
    provider_id: string;
    model_id: string;
    model_revision: string;
    boundary: "local" | "cloud" | "openai_compatible";
    network_enabled: boolean;
    cloud_upload_required: boolean;
    cloud_upload_consented: boolean;
  };
  budget: {
    model_calls_used: number;
    model_calls_limit: number;
    rendered_frames_used: number;
    rendered_frames_limit: number;
    cost_usd_used: number;
    cost_usd_limit: number;
    elapsed_seconds: number;
    wall_seconds_limit: number;
    refinements_used: number;
    refinements_limit: number;
  };
  scenes: Array<{
    scene_id: string;
    scene_label: string;
    narrative_role: string;
    continuity_notes: string[];
    evidence: CreativeAgentEvidence[];
    directions: CreativeAgentDirection[];
  }>;
  selection: {
    status: string;
    preferred_candidate_id: string | null;
    runner_up_candidate_id: string | null;
    pareto_candidate_ids: string[];
    gate_trace: string[];
    automatic_selection_allowed: boolean;
    requires_user_confirmation: boolean;
    applied_candidate_id: string | null;
    undo_revision: string | null;
    applied_at: string | null;
  };
  skipped_stages: CreativeAgentStage[];
  cancellation_requested: boolean;
  resume_requested: boolean;
  last_error: string | null;
}

export interface CreativeAgentApplicationResult {
  action: "applied";
  candidate_id: string;
  previous_graph_digest: string;
  applied_graph_digest: string;
  undo_revision: string;
  application_scopes: CreativeAgentDirection["application_scopes"];
  graph: GradeGraph;
}

export interface CreativeAgentStartResult {
  project_id: string;
  run_id: string;
  job_id: string;
  status: JobStatus;
  mode: "offline_shadow" | "provider_shadow";
  snapshot: CreativeAgentSnapshot;
}

export interface CreativeAgentStartOptions {
  userIntent?: string;
  enableProviderShadow?: boolean;
  enableReflectionShadow?: boolean;
  confirmCloudRun?: boolean;
  consentCloudUpload?: boolean;
  maximumProviderCalls?: number;
  maximumProviderCostUsd?: number;
}

export interface CreativeAgentPreferenceMemory {
  schema_version: "colorgraph.project-preference-memory/v1";
  project_id: string;
  user_scope_id: string;
  entries: Array<{
    entry_id: string;
    project_id: string;
    user_scope_id: string;
    selected_candidate_id: string;
    compared_candidate_ids: string[];
    preferred_strength: number | null;
    recorded_at: string;
  }>;
}

export interface LookMutationResult {
  action: "applied" | "restored" | "unchanged";
  recipe_id: LookId;
  graph_digest: string;
  graph: GradeGraph;
}

export interface ProjectSummary {
  project_id: string;
  project_name: string;
  is_default_demo: boolean;
  updated_at: string;
  duration_seconds: number;
  shot_count: number;
  mask_count: number;
  source_url: string;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown, fallback: string) {
    const message =
      typeof detail === "string"
        ? detail
        : detail &&
            typeof detail === "object" &&
            "message" in detail &&
            typeof detail.message === "string"
          ? detail.message
          : fallback;
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail: unknown;
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = body.detail;
    } catch {
      // Keep the HTTP status when an endpoint does not return JSON.
    }
    throw new ApiError(
      response.status,
      detail,
      `${response.status} ${response.statusText}`,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function assetUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  return `${API_BASE}${path}`;
}

export function previewSourceUrl(
  path: string,
  profile: Pick<
    PreviewPlaybackProfile,
    "quality" | "codec" | "bit_depth"
  >,
): string {
  const source = assetUrl(path);
  const separator = source.includes("?") ? "&" : "?";
  const parameters = new URLSearchParams({
    quality: profile.quality,
    codec: profile.codec,
    bit_depth: String(profile.bit_depth),
  });
  return `${source}${separator}${parameters.toString()}`;
}

export function maskAssetUrl(
  projectId: string,
  target: string,
  frameIndex: number,
): string {
  return assetUrl(
    `/api/projects/${projectId}/masks/${target}/${Math.max(0, frameIndex)}`,
  );
}

export async function getDevice(): Promise<DeviceInfo> {
  return request<DeviceInfo>("/api/system/device");
}

export async function getLookRecipes(): Promise<LookRecipeCatalog> {
  return request<LookRecipeCatalog>("/api/system/look-recipes");
}

export async function createProject(
  file: File,
  name: string,
  inputColorProfile: InputColorProfile = "rec709",
  referenceImage?: File,
): Promise<{ project_id: string; job_id: string; status: JobStatus }> {
  const colorManagement = colorManagementPayload(inputColorProfile);
  const body = new FormData();
  body.append("name", name);
  body.append("input_color_space", colorManagement.inputColorSpace);
  if (colorManagement.sourceLogProfile) {
    body.append("source_log_profile", colorManagement.sourceLogProfile);
  }
  body.append("media", file);
  if (referenceImage) body.append("reference_image", referenceImage);
  return request("/api/projects", { method: "POST", body });
}

export async function createLocalProject(
  mediaPath: string,
  name: string,
  inputColorProfile: InputColorProfile = "rec709",
): Promise<{ project_id: string; job_id: string; status: JobStatus }> {
  const colorManagement = colorManagementPayload(inputColorProfile);
  return request("/api/projects/local", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      media_path: mediaPath,
      name,
      input_color_space: colorManagement.inputColorSpace,
      source_log_profile: colorManagement.sourceLogProfile,
    }),
  });
}

export async function updateProjectColorManagement(
  projectId: string,
  inputColorProfile: InputColorProfile,
): Promise<{ project_id: string; job_id: string; status: JobStatus }> {
  const colorManagement = colorManagementPayload(inputColorProfile);
  return request(`/api/projects/${projectId}/color-management`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      input_color_space: colorManagement.inputColorSpace,
      source_log_profile: colorManagement.sourceLogProfile,
    }),
  });
}

export async function getJob(jobId: string): Promise<JobRecord> {
  return request<JobRecord>(`/api/jobs/${jobId}`);
}

export async function waitForJob(
  jobId: string,
  onUpdate?: (job: JobRecord) => void,
  signal?: AbortSignal,
): Promise<JobRecord> {
  while (true) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const job = await getJob(jobId);
    onUpdate?.(job);
    if (job.status === "completed") return job;
    if (job.status === "failed") {
      throw new Error(job.error || "后台任务失败");
    }
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(resolve, 450);
      signal?.addEventListener(
        "abort",
        () => {
          window.clearTimeout(timer);
          reject(new DOMException("Aborted", "AbortError"));
        },
        { once: true },
      );
    });
  }
}

export async function getGraph(projectId: string): Promise<GradeGraph> {
  return request<GradeGraph>(`/api/projects/${projectId}/grade-graph`);
}

export async function listProjects(): Promise<ProjectSummary[]> {
  return request<ProjectSummary[]>("/api/projects");
}

export async function saveGraph(
  projectId: string,
  graph: GradeGraph,
): Promise<GradeGraph> {
  return request<GradeGraph>(`/api/projects/${projectId}/grade-graph`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(graph),
  });
}

export async function generateMasks(
  projectId: string,
  targets?: string[],
): Promise<{ project_id: string; job_id: string; status: JobStatus }> {
  return request(`/api/projects/${projectId}/masks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(targets ? { targets } : {}),
  });
}

export async function getActiveMaskJob(
  projectId: string,
): Promise<JobRecord | null> {
  return request<JobRecord | null>(`/api/projects/${projectId}/masks/job`);
}

export async function runCommand(
  projectId: string,
  prompt: string,
  currentTime: number,
  selectedShotId?: string,
  selectedNodeId?: string,
): Promise<CommandPlan> {
  return request<CommandPlan>(`/api/projects/${projectId}/commands`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt,
      context: {
        current_time: currentTime,
        selected_shot_id: selectedShotId ?? null,
        selected_node_id: selectedNodeId ?? null,
      },
    }),
  });
}

export async function renderPreview(
  projectId: string,
  timeSeconds: number,
): Promise<{
  url: string;
  source_url: string;
  time_seconds: number;
  metrics: Record<string, string | number>;
  cache_hit: boolean;
  cache_key: string;
}> {
  return request(`/api/projects/${projectId}/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ time_seconds: timeSeconds }),
  });
}

export interface PreviewVideoPreparation {
  status: "ready" | "rendering";
  cache_key: string;
  cache_hit: boolean;
  url: string | null;
  job_id: string | null;
  profile: PreviewPlaybackProfile;
}

export async function preparePreviewVideo(
  projectId: string,
  profile: Pick<
    PreviewPlaybackProfile,
    "quality" | "codec" | "bit_depth"
  >,
  graph: GradeGraph,
): Promise<PreviewVideoPreparation> {
  return request(`/api/projects/${projectId}/preview-video`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      quality: profile.quality,
      codec: profile.codec,
      bit_depth: profile.bit_depth,
      batch_size: 4,
      graph,
    }),
  });
}

export interface PreviewVideoSegmentPreparation {
  status: "ready" | "rendering";
  cache_key: string;
  group_key: string;
  cache_hit: boolean;
  start_seconds: number;
  end_seconds: number;
  url: string | null;
  job_id: string | null;
  profile: PreviewPlaybackProfile;
}

export async function preparePreviewVideoSegment(
  projectId: string,
  profile: Pick<
    PreviewPlaybackProfile,
    "quality" | "codec" | "bit_depth"
  >,
  graph: GradeGraph,
  timeSeconds: number,
  {
    priority,
    groupKey,
    signal,
  }: {
    priority: boolean;
    groupKey?: string;
    signal?: AbortSignal;
  },
): Promise<PreviewVideoSegmentPreparation> {
  return request(`/api/projects/${projectId}/preview-video-segment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal,
    body: JSON.stringify({
      quality: profile.quality,
      codec: profile.codec,
      bit_depth: profile.bit_depth,
      batch_size: 4,
      graph,
      time_seconds: timeSeconds,
      priority,
      group_key: groupKey,
    }),
  });
}

export async function recordPreviewPlaybackMetrics(
  projectId: string,
  telemetry: PreviewPlaybackTelemetry,
): Promise<void> {
  await request(`/api/projects/${projectId}/preview-playback-metrics`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(telemetry),
  });
}

export async function compareLookCandidates(
  projectId: string,
  timeSeconds: number,
  prompt: string,
): Promise<CandidateComparison> {
  return request(`/api/projects/${projectId}/candidates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      time_seconds: timeSeconds,
      prompt,
      limit: 3,
    }),
  });
}

export async function applyLookCandidate(
  projectId: string,
  recipeId: LookId,
  recipeVersion: string,
  graphDigest: string,
  timeSeconds: number,
  discardOverrides = false,
): Promise<LookMutationResult> {
  return request(`/api/projects/${projectId}/looks/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      recipe_id: recipeId,
      recipe_version: recipeVersion,
      graph_digest: graphDigest,
      time_seconds: timeSeconds,
      discard_overrides: discardOverrides,
    }),
  });
}

export async function restoreOriginalLook(
  projectId: string,
  timeSeconds: number,
): Promise<LookMutationResult> {
  return request(`/api/projects/${projectId}/looks/restore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ time_seconds: timeSeconds }),
  });
}

export async function getCreativeAgentSnapshot(
  projectId: string,
): Promise<CreativeAgentSnapshot> {
  return request<CreativeAgentSnapshot>(
    `/api/projects/${projectId}/creative-agent`,
  );
}

export async function startCreativeAgentRun(
  projectId: string,
  options: CreativeAgentStartOptions = {},
): Promise<CreativeAgentStartResult> {
  return request<CreativeAgentStartResult>(
    `/api/projects/${projectId}/creative-agent/runs`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_intent: options.userIntent?.trim() || null,
        enable_provider_shadow: options.enableProviderShadow ?? false,
        enable_reflection_shadow: options.enableReflectionShadow ?? false,
        confirm_cloud_run: options.confirmCloudRun ?? false,
        consent_cloud_upload: options.consentCloudUpload ?? false,
        maximum_provider_calls: options.maximumProviderCalls ?? 32,
        maximum_provider_cost_usd: options.maximumProviderCostUsd ?? 1,
      }),
    },
  );
}

export async function controlCreativeAgent(
  projectId: string,
  action: "cancel" | "resume",
  expectedSnapshotRevision: number,
): Promise<CreativeAgentSnapshot> {
  let revision = expectedSnapshotRevision;
  const current = await getCreativeAgentSnapshot(projectId);
  if (current.snapshot_revision !== revision) {
    revision = current.snapshot_revision;
  }
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      return await request<CreativeAgentSnapshot>(
        `/api/projects/${projectId}/creative-agent/control`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action,
            expected_snapshot_revision: revision,
          }),
        },
      );
    } catch (error) {
      const staleControl =
        error instanceof ApiError &&
        error.status === 409 &&
        error.detail === "creative Agent control request is stale";
      if (!staleControl || attempt === 2) throw error;
      const latest = await getCreativeAgentSnapshot(projectId);
      revision = latest.snapshot_revision;
    }
  }
  throw new Error("creative Agent control retry limit reached");
}

export async function applyCreativeAgentCandidate(
  projectId: string,
  candidateId: string,
  expectedGraphDigest: string,
  expectedSnapshotRevision: number,
): Promise<CreativeAgentApplicationResult> {
  return request<CreativeAgentApplicationResult>(
    `/api/projects/${projectId}/creative-agent/apply`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        candidate_id: candidateId,
        expected_graph_digest: expectedGraphDigest,
        expected_snapshot_revision: expectedSnapshotRevision,
        confirmation: true,
      }),
    },
  );
}

export async function requestCreativeAgentFeedback(
  projectId: string,
  candidateId: string,
  feedback: string,
  expectedSnapshotRevision: number,
  mode: "adjust_existing_strategy" | "new_thesis_branch",
): Promise<{
  schema_version: "colorgraph.agent-feedback-request/v1";
  project_id: string;
  run_id: string;
  candidate_id: string;
  feedback: string;
  expected_snapshot_revision: number;
  requested_at: string;
  mode: "adjust_existing_strategy" | "new_thesis_branch";
}> {
  return request(`/api/projects/${projectId}/creative-agent/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      candidate_id: candidateId,
      feedback,
      expected_snapshot_revision: expectedSnapshotRevision,
      mode,
    }),
  });
}

export async function getCreativeAgentPreferences(
  projectId: string,
  userScopeId: string,
): Promise<CreativeAgentPreferenceMemory> {
  return request<CreativeAgentPreferenceMemory>(
    `/api/projects/${projectId}/creative-agent/preferences/${encodeURIComponent(userScopeId)}`,
  );
}

export async function addCreativeAgentPreference(
  projectId: string,
  userScopeId: string,
  selectedCandidateId: string,
  comparedCandidateIds: string[],
): Promise<CreativeAgentPreferenceMemory> {
  const entryId =
    typeof crypto.randomUUID === "function"
      ? `preference:${crypto.randomUUID()}`
      : `preference:${Date.now().toString(36)}`;
  return request<CreativeAgentPreferenceMemory>(
    `/api/projects/${projectId}/creative-agent/preferences/${encodeURIComponent(userScopeId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        entry_id: entryId,
        project_id: projectId,
        user_scope_id: userScopeId,
        selected_candidate_id: selectedCandidateId,
        compared_candidate_ids: comparedCandidateIds,
        preferred_strength: null,
        recorded_at: new Date().toISOString(),
      }),
    },
  );
}

export async function deleteCreativeAgentPreferences(
  projectId: string,
  userScopeId: string,
): Promise<void> {
  await request(
    `/api/projects/${projectId}/creative-agent/preferences/${encodeURIComponent(userScopeId)}`,
    { method: "DELETE" },
  );
}

export function creativeAgentPreferenceExportUrl(
  projectId: string,
  userScopeId: string,
): string {
  return assetUrl(
    `/api/projects/${projectId}/creative-agent/preferences/${encodeURIComponent(userScopeId)}/export`,
  );
}

export async function renderVideo(
  projectId: string,
): Promise<{ project_id: string; job_id: string; status: JobStatus }> {
  return request(`/api/projects/${projectId}/render`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bit_depth: 10 }),
  });
}

export async function getQuality(projectId: string): Promise<QualityReport> {
  return request<QualityReport>(`/api/projects/${projectId}/quality`);
}

export async function createExport(
  projectId: string,
): Promise<{ download_url: string }> {
  return request(`/api/projects/${projectId}/export`, { method: "POST" });
}
