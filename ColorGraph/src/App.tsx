import { CheckCircle2, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import {
  ApiError,
  addCreativeAgentPreference,
  applyCreativeAgentCandidate,
  applyLookCandidate,
  assetUrl,
  compareLookCandidates,
  controlCreativeAgent,
  createExport,
  createLocalProject,
  createProject,
  creativeAgentPreferenceExportUrl,
  deleteCreativeAgentPreferences,
  generateMasks,
  getActiveMaskJob,
  getCreativeAgentPreferences,
  getCreativeAgentSnapshot,
  getDevice,
  getGraph,
  getJob,
  getLookRecipes,
  getQuality,
  listProjects,
  maskAssetUrl,
  preparePreviewVideoSegment,
  previewSourceUrl,
  recordPreviewPlaybackMetrics,
  renderPreview,
  renderVideo,
  restoreOriginalLook,
  requestCreativeAgentFeedback,
  runCommand,
  saveGraph,
  startCreativeAgentRun,
  updateProjectColorManagement,
  waitForJob,
  INPUT_COLOR_PROFILE_LABELS,
  type BackendNode,
  type CandidateComparison,
  type CreativeAgentPreferenceMemory,
  type CreativeAgentSnapshot,
  type CreativeAgentStartOptions,
  type DeviceInfo,
  type GradeGraph,
  type InputColorProfile,
  type JobRecord,
  type LookRecipeCatalog,
  type ProjectSummary,
  type QualityReport,
} from "./api";
import { AgentCommand } from "./components/AgentCommand";
import { AgentRunPanel } from "./components/AgentRunPanel";
import { ExportModal } from "./components/ExportModal";
import { Inspector } from "./components/Inspector";
import { LocalImportModal } from "./components/LocalImportModal";
import { NavigationRail } from "./components/NavigationRail";
import { PipelineModal } from "./components/PipelineModal";
import { Preview } from "./components/Preview";
import { Timeline } from "./components/Timeline";
import { TopBar } from "./components/TopBar";
import { WorkspaceHeader } from "./components/WorkspaceHeader";
import {
  LOOKS,
  PIPELINE_STAGES,
  SOURCE_IMAGE,
} from "./data";
import {
  availablePreviewQualities,
  buildPreviewPlaybackProfile,
  resolvePreviewPlaybackProfile,
} from "./previewCapabilities";
import type {
  AgentMessage,
  GradeNode,
  GradeParameter,
  GradeState,
  LookId,
  MaskKind,
  MediaKind,
  PanelId,
  PreviewEncodingPreference,
  PreviewPlaybackProfile,
  PreviewPlaybackSegment,
  PreviewPlaybackTelemetry,
  PreviewQuality,
  PreviewQualityPreference,
  Shot,
  TimelineScene,
} from "./types";

const DEFAULT_COMMAND =
  "压暗后半段天空但不改变山体";
const LARGE_LOCAL_FILE_THRESHOLD = 2 * 1024 ** 3;
const ACTIVE_MASK_JOB_KEY = "colorgraph.activeMaskJob";
const PERSIST_MASK_JOB_STATE = false;
const PIPELINE_OPEN_KEY = "colorgraph.pipelineOpen";
const PREVIEW_QUALITY_KEY = "colorgraph.previewQuality";
const PREVIEW_ENCODING_KEY = "colorgraph.previewEncoding";
const AGENT_USER_SCOPE_KEY = "colorgraph.agentUserScope";
const DEVELOPMENT_FIXTURE_PROJECT_ID =
  /^(synthetic_landscape|api-e2e|api-scene-test|reference-e2e)-/i;
const REQUIRED_MASK_TARGETS = [
  "sky",
  "vegetation",
  "water",
  "mountain",
  "depth_far",
] as const;
const DEFAULT_PREVIEW_QUALITY: PreviewQuality = "1080p";
const PREVIEW_SEGMENT_DURATION_SECONDS = 4;
const PREVIEW_START_BUFFER_SECONDS = 2;
const PREVIEW_AHEAD_BUFFER_SECONDS = 12;
const PREVIEW_QUALITIES: PreviewQuality[] = [
  "540p",
  "1080p",
  "1440p",
  "2160p",
];
const PREVIEW_ENCODINGS: PreviewEncodingPreference[] = [
  "auto",
  "hevc-main10",
  "h264",
];
const DEFAULT_GRADE_STATE: GradeState = {
  exposure: 0,
  temperature: 0,
  contrast: 0,
  saturation: 0,
  highlights: 0,
  strength: 100,
};

function readAgentUserScope() {
  const stored = window.localStorage.getItem(AGENT_USER_SCOPE_KEY);
  if (stored) return stored;
  const created =
    typeof crypto.randomUUID === "function"
      ? `local-${crypto.randomUUID()}`
      : `local-${Date.now().toString(36)}`;
  window.localStorage.setItem(AGENT_USER_SCOPE_KEY, created);
  return created;
}

function startupProject(
  summaries: ProjectSummary[],
  storedProjectId: string | null,
  activeProjectId?: string,
): ProjectSummary | undefined {
  const activeProject = activeProjectId
    ? summaries.find((item) => item.project_id === activeProjectId)
    : undefined;
  if (activeProject) return activeProject;

  const storedProject = summaries.find(
    (item) => item.project_id === storedProjectId,
  );
  if (
    storedProject &&
    !DEVELOPMENT_FIXTURE_PROJECT_ID.test(storedProject.project_id)
  ) {
    return storedProject;
  }

  return (
    summaries.find((item) => item.is_default_demo) ??
    storedProject ??
    summaries[0]
  );
}

interface LookInstanceState {
  baseRecipeId: LookId;
  recipeVersion: string | null;
  overrides: Partial<Record<GradeParameter, number>>;
  dirty: boolean;
}

interface GraphTransaction {
  before: GradeGraph;
  after: GradeGraph;
  label: string;
}

interface StoredMaskJob {
  jobId: string;
  projectId: string;
}

function playbackSegmentAt(
  segments: PreviewPlaybackSegment[],
  timeSeconds: number,
  durationSeconds: number,
) {
  return segments.find(
    (segment) =>
      timeSeconds + 1e-6 >= segment.start_seconds &&
      (timeSeconds < segment.end_seconds ||
        (segment.end_seconds >= durationSeconds - 1e-6 &&
          timeSeconds <= segment.end_seconds + 1e-3)),
  );
}

function contiguousPlaybackBufferEnd(
  segments: PreviewPlaybackSegment[],
  timeSeconds: number,
  durationSeconds: number,
) {
  const active = playbackSegmentAt(segments, timeSeconds, durationSeconds);
  if (!active) return timeSeconds;
  let bufferedEnd = active.end_seconds;
  while (bufferedEnd < durationSeconds - 1e-6) {
    const next = segments.find(
      (segment) =>
        Math.abs(segment.start_seconds - bufferedEnd) < 1e-3 &&
        segment.end_seconds > bufferedEnd,
    );
    if (!next) break;
    bufferedEnd = next.end_seconds;
  }
  return bufferedEnd;
}

function previewSegmentIndex(timeSeconds: number, durationSeconds: number) {
  const safeTime = Math.min(
    Math.max(0, timeSeconds),
    Math.max(0, durationSeconds - 1e-6),
  );
  return Math.floor(safeTime / PREVIEW_SEGMENT_DURATION_SECONDS);
}

function readStoredMaskJob(): StoredMaskJob | null {
  if (!PERSIST_MASK_JOB_STATE) {
    window.localStorage.removeItem(ACTIVE_MASK_JOB_KEY);
    return null;
  }
  try {
    const value = window.localStorage.getItem(ACTIVE_MASK_JOB_KEY);
    if (!value) return null;
    const parsed = JSON.parse(value) as Partial<StoredMaskJob>;
    if (
      typeof parsed.jobId !== "string" ||
      typeof parsed.projectId !== "string"
    ) {
      window.localStorage.removeItem(ACTIVE_MASK_JOB_KEY);
      return null;
    }
    return { jobId: parsed.jobId, projectId: parsed.projectId };
  } catch {
    window.localStorage.removeItem(ACTIVE_MASK_JOB_KEY);
    return null;
  }
}

function rememberMaskJob(jobId: string, projectId: string) {
  if (!PERSIST_MASK_JOB_STATE) {
    window.localStorage.removeItem(ACTIVE_MASK_JOB_KEY);
    return;
  }
  window.localStorage.setItem(
    ACTIVE_MASK_JOB_KEY,
    JSON.stringify({ jobId, projectId } satisfies StoredMaskJob),
  );
}

function forgetMaskJob(jobId?: string) {
  const stored = readStoredMaskJob();
  if (!jobId || stored?.jobId === jobId) {
    window.localStorage.removeItem(ACTIVE_MASK_JOB_KEY);
  }
}

function readPipelineOpenPreference() {
  try {
    return window.sessionStorage.getItem(PIPELINE_OPEN_KEY) === "true";
  } catch {
    return false;
  }
}

function rememberPipelineOpenPreference(open: boolean) {
  try {
    window.sessionStorage.setItem(PIPELINE_OPEN_KEY, String(open));
  } catch {
    // The UI state still works when session storage is unavailable.
  }
}

function readPreviewQualityPreference(): PreviewQualityPreference {
  try {
    const value = window.localStorage.getItem(PREVIEW_QUALITY_KEY);
    return value === "auto" || PREVIEW_QUALITIES.includes(value as PreviewQuality)
      ? (value as PreviewQualityPreference)
      : "auto";
  } catch {
    return "auto";
  }
}

function readPreviewEncodingPreference(): PreviewEncodingPreference {
  try {
    const value = window.localStorage.getItem(PREVIEW_ENCODING_KEY);
    return PREVIEW_ENCODINGS.includes(value as PreviewEncodingPreference)
      ? (value as PreviewEncodingPreference)
      : "auto";
  } catch {
    return "auto";
  }
}

function rememberPreviewPreference(
  quality: PreviewQualityPreference,
  encoding: PreviewEncodingPreference,
) {
  try {
    window.localStorage.setItem(PREVIEW_QUALITY_KEY, quality);
    window.localStorage.setItem(PREVIEW_ENCODING_KEY, encoding);
  } catch {
    // Capability detection and switching remain functional without storage.
  }
}

function hasCompleteMaskAnalysis(graph: GradeGraph | null) {
  if (!graph || graph.media.frame_count <= 0) return false;
  return REQUIRED_MASK_TARGETS.every((target) =>
    graph.masks.some(
      (asset) =>
        asset.target === target &&
        asset.frame_count === graph.media.frame_count &&
        asset.metadata.decode_verified === true &&
        asset.metadata.file_count === graph.media.frame_count,
    ),
  );
}

function inputColorProfileFromGraph(graph: GradeGraph): InputColorProfile {
  if (graph.media.input_color_space !== "log") return "rec709";
  if (graph.media.source_log_profile === "dji_mavic3_dlog_rec709_v1") {
    return "dji_mavic3_dlog_rec709_v1";
  }
  if (graph.media.source_log_profile === "sony_slog3_sgamut3cine") {
    return "sony_slog3_sgamut3cine";
  }
  return "rec709";
}

function graphUsesBrowserProxy(graph: GradeGraph | null): boolean {
  const sourceImport = graph?.metadata.source_import;
  if (
    !sourceImport ||
    typeof sourceImport !== "object" ||
    !("browser_proxy" in sourceImport)
  ) {
    return false;
  }
  return Boolean(sourceImport.browser_proxy);
}

const STAGE_INDEX: Record<string, number> = {
  queued: 0,
  link: 0,
  upload: 0,
  decode: 0,
  proxy: 0,
  shots: 1,
  color: 1,
  frames: 2,
  vision: 2,
  models: 2,
  masks: 3,
  graph: 4,
  render: 4,
  verify: 5,
  completed: PIPELINE_STAGES.length,
  failed: PIPELINE_STAGES.length - 1,
};

function completedPipelineStages(job: JobRecord | null): string[] {
  if (!job) return [];
  const completed = job.status === "completed";
  if (job.kind === "analyze" || job.kind === "upload") {
    if (completed) return ["decode", "shots", "vision", "graph"];
    if (["shots", "color"].includes(job.stage)) return ["decode"];
    if (["frames", "vision"].includes(job.stage)) return ["decode", "shots"];
    if (job.stage === "graph") return ["decode", "shots", "vision"];
    return [];
  }
  if (job.kind === "masks") {
    return completed
      ? ["decode", "shots", "vision", "masks", "graph"]
      : ["decode", "shots", "vision"];
  }
  if (job.kind === "render") {
    return completed
      ? ["decode", "shots", "vision", "masks", "graph", "verify"]
      : ["decode", "shots", "vision", "masks", "graph"];
  }
  return [];
}

function currentPipelineStage(job: JobRecord | null): string | undefined {
  if (!job) return undefined;
  if (["queued", "link", "upload", "decode", "proxy"].includes(job.stage)) {
    return "decode";
  }
  if (["shots", "color"].includes(job.stage)) return "shots";
  if (["frames", "vision", "models"].includes(job.stage)) return "vision";
  if (job.stage === "masks") return "masks";
  if (["graph", "render"].includes(job.stage)) return "graph";
  if (["verify", "completed", "failed"].includes(job.stage)) return "verify";
  return job.stage;
}

const TARGET_LABELS: Record<string, string> = {
  sky: "Sky",
  vegetation: "Vegetation",
  water: "Water",
  mountain: "Mountain",
  depth_far: "Depth",
};

function numberParameter(
  node: BackendNode | undefined,
  key: string,
  fallback = 0,
) {
  const value = node?.parameters[key];
  return typeof value === "number" ? value : fallback;
}

function trackedParameter(
  node: BackendNode | undefined,
  key: string,
  time: number,
  fallback = 0,
) {
  const track = node?.tracks.find((candidate) => candidate.parameter === key);
  if (!track?.keyframes.length) return numberParameter(node, key, fallback);
  const keyframes = track.keyframes;
  if (time <= keyframes[0].time_seconds) return keyframes[0].value;
  if (time >= keyframes[keyframes.length - 1].time_seconds) {
    return keyframes[keyframes.length - 1].value;
  }
  const rightIndex = keyframes.findIndex(
    (keyframe) => keyframe.time_seconds >= time,
  );
  const leftIndex = rightIndex - 1;
  const left = keyframes[leftIndex];
  const right = keyframes[rightIndex];
  const position =
    (time - left.time_seconds) /
    (right.time_seconds - left.time_seconds);
  if (track.interpolation === "hold") return left.value;
  if (track.interpolation === "linear" || keyframes.length < 3) {
    return left.value + (right.value - left.value) * position;
  }
  const previous = keyframes[Math.max(0, leftIndex - 1)].value;
  const following =
    keyframes[Math.min(keyframes.length - 1, rightIndex + 1)].value;
  const squared = position * position;
  const cubed = squared * position;
  return (
    0.5 *
    (2 * left.value +
      (-previous + right.value) * position +
      (2 * previous - 5 * left.value + 4 * right.value - following) *
        squared +
      (-previous + 3 * left.value - 3 * right.value + following) * cubed)
  );
}

function uiKind(node: BackendNode): GradeNode["kind"] {
  switch (node.type) {
    case "input_transform":
      return "input";
    case "balance":
      return "balance";
    case "tone":
      return "tone";
    case "masked_grade":
      return "mask";
    case "look":
    case "post_look":
      return "look";
    case "output_transform":
      return "output";
  }
}

function nodeScope(node: BackendNode): GradeNode["scope"] {
  const target = node.spatial_scope.target;
  if (target && target !== "global") {
    return TARGET_LABELS[target] ?? target;
  }
  if (node.temporal_scope.level === "project") return "Project";
  if (node.temporal_scope.level === "scene") {
    const sceneIndex = node.temporal_scope.scene_id?.match(/(\d+)$/)?.[1];
    return `Scene ${sceneIndex ? Number(sceneIndex).toString().padStart(2, "0") : "—"}`;
  }
  const shotIndex = node.temporal_scope.shot_id?.match(/(\d+)$/)?.[1];
  const shotLabel = `Shot ${
    shotIndex ? Number(shotIndex).toString().padStart(2, "0") : "—"
  }`;
  return node.temporal_scope.level === "sub_shot"
    ? `Sub-shot · ${shotLabel}`
    : shotLabel;
}

function nodeSubtitle(node: BackendNode): string {
  const entries = Object.entries(node.parameters)
    .filter(([, value]) => typeof value === "number")
    .slice(0, 2)
    .map(([key, value]) => `${key} ${Number(value).toFixed(2)}`);
  const trackNote = node.tracks.length ? ` · ${node.tracks.length} 条轨道` : "";
  return `${entries.join(" · ") || node.type}${trackNote}`;
}

function graphToNodes(graph: GradeGraph): GradeNode[] {
  return [...graph.nodes]
    .sort((left, right) => left.order - right.order)
    .map((node) => ({
      id: node.id,
      name: node.label,
      subtitle: nodeSubtitle(node),
      scope: nodeScope(node),
      kind: uiKind(node),
      enabled: node.enabled,
      gpu: true,
      recipeLook: node.type === "look",
      parameter:
        node.type === "balance"
          ? "exposure"
          : node.type === "look"
            ? "strength"
            : node.spatial_scope.target === "vegetation"
              ? "saturation"
              : node.type === "masked_grade"
                ? "highlights"
                : undefined,
    }));
}

function graphToShots(graph: GradeGraph): Shot[] {
  return graph.shots.map((shot) => {
    const balance = graph.nodes.find(
      (node) =>
        node.type === "balance" &&
        node.temporal_scope.shot_id === shot.id,
    );
    const exposureTrack = balance?.tracks.find(
      (track) => track.parameter === "exposure",
    );
    const baseExposure = numberParameter(balance, "exposure");
    const exposureKeyframes = exposureTrack?.keyframes.map((keyframe, index) => ({
      time: keyframe.time_seconds,
      value: keyframe.value,
      nodeId: balance?.id ?? "",
      keyframeIndex: index,
    })) ?? [
      {
        time: shot.time_range.start_seconds,
        value: baseExposure,
        nodeId: balance?.id ?? "",
        keyframeIndex: 0,
      },
      {
        time: shot.time_range.end_seconds,
        value: baseExposure,
        nodeId: balance?.id ?? "",
        keyframeIndex: 1,
      },
    ];
    return {
      id: shot.id,
      sceneId: shot.scene_id,
      label: (shot.index + 1).toString().padStart(2, "0"),
      start: shot.time_range.start_seconds,
      duration: shot.time_range.end_seconds - shot.time_range.start_seconds,
      position: "50% 50%",
      thumbnail: assetUrl(
        `/api/projects/${graph.project_id}/frames/shot_${(shot.index + 1)
          .toString()
          .padStart(3, "0")}.jpg`,
      ),
      exposureKeyframes,
    };
  });
}

function graphToTimelineScenes(graph: GradeGraph): TimelineScene[] {
  return graph.scenes.flatMap((scene) => {
    const sceneShots = graph.shots.filter((shot) =>
      scene.shot_ids.includes(shot.id),
    );
    const first = sceneShots.at(0);
    const last = sceneShots.at(-1);
    if (!first || !last) return [];
    const look = graph.nodes.find((node) => node.id === scene.look_node_id);
    return [
      {
        id: scene.id,
        label: scene.label,
        start: first.time_range.start_seconds,
        duration:
          last.time_range.end_seconds - first.time_range.start_seconds,
        look: look?.label ?? "No Look",
      },
    ];
  });
}

function shotAtTime(graph: GradeGraph, time: number) {
  return (
    graph.shots.find(
      (shot) =>
        time >= shot.time_range.start_seconds &&
        time < shot.time_range.end_seconds,
    ) ?? graph.shots.at(-1)
  );
}

function lookAtTime(graph: GradeGraph, time: number) {
  const shot = shotAtTime(graph, time);
  return (
    graph.nodes.find(
      (node) =>
        node.type === "look" &&
        (!shot || node.temporal_scope.scene_id === shot.scene_id),
    ) ?? graph.nodes.find((node) => node.type === "look")
  );
}

function isLookId(value: unknown): value is LookId {
  return (
    value === "natural" ||
    value === "cool" ||
    value === "warm" ||
    value === "foggy"
  );
}

function lookInstanceFromGraph(
  graph: GradeGraph,
  time: number,
): LookInstanceState {
  const look = lookAtTime(graph, time);
  const metadata = look?.metadata.look_instance;
  if (metadata && typeof metadata === "object") {
    const baseRecipeId = Reflect.get(metadata, "base_recipe_id");
    const recipeVersion = Reflect.get(metadata, "recipe_version");
    const userOverrides = Reflect.get(metadata, "user_overrides");
    const dirty = Reflect.get(metadata, "dirty");
    if (isLookId(baseRecipeId)) {
      const overrides: Partial<Record<GradeParameter, number>> = {};
      if (userOverrides && typeof userOverrides === "object") {
        for (const [key, value] of Object.entries(userOverrides)) {
          if (
            typeof value === "number" &&
            (
              [
                "strength",
                "contrast",
                "saturation",
                "temperature",
                "highlights",
              ] as GradeParameter[]
            ).includes(key as GradeParameter)
          ) {
            overrides[key as GradeParameter] = value;
          }
        }
      }
      return {
        baseRecipeId,
        recipeVersion:
          typeof recipeVersion === "string" ? recipeVersion : null,
        overrides,
        dirty: dirty === true || Object.keys(overrides).length > 0,
      };
    }
  }
  const legacyRecipe = look?.metadata.recipe_id;
  return {
    baseRecipeId: isLookId(legacyRecipe) ? legacyRecipe : "natural",
    recipeVersion: null,
    overrides: {},
    dirty: false,
  };
}

function errorCode(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  const detail = error.detail;
  if (!detail || typeof detail !== "object") return null;
  const code = Reflect.get(detail, "code");
  return typeof code === "string" ? code : null;
}

function gradeFromGraph(
  graph: GradeGraph,
  time: number,
  selectedNodeId?: string,
): GradeState {
  const shot = shotAtTime(graph, time);
  const balance = graph.nodes.find(
    (node) =>
      node.type === "balance" &&
      (!shot || node.temporal_scope.shot_id === shot.id),
  );
  const selected = graph.nodes.find((node) => node.id === selectedNodeId);
  const balanceForControls = selected?.type === "balance" ? selected : balance;
  const look =
    selected?.type === "look" || selected?.type === "post_look"
      ? selected
      : lookAtTime(graph, time);
  const sky = graph.nodes.find(
    (node) =>
      node.type === "masked_grade" && node.spatial_scope.target === "sky",
  );
  return {
    exposure: Math.round(
      trackedParameter(balanceForControls, "exposure", time) * 100,
    ),
    temperature: Math.round(
      numberParameter(
        selected?.type === "look" || selected?.type === "post_look"
          ? selected
          : balanceForControls,
        "temperature",
      ) * 100,
    ),
    contrast: Math.round(numberParameter(look, "contrast") * 100),
    saturation: Math.round(
      numberParameter(
        selected?.type === "masked_grade" ? selected : look,
        "saturation",
      ) * 100,
    ),
    highlights: Math.round(
      numberParameter(
        selected?.type === "look" || selected?.type === "post_look"
          ? selected
          : selected?.type === "masked_grade" || selected?.type === "tone"
            ? selected
            : sky ?? balanceForControls,
        "highlights",
      ) * 100,
    ),
    strength: Math.round(numberParameter(look, "strength", 1) * 100),
  };
}

function lookFromGraph(graph: GradeGraph, time = 0): LookId {
  return lookInstanceFromGraph(graph, time).baseRecipeId;
}

function updateGraphParameter(
  graph: GradeGraph,
  parameter: GradeParameter,
  value: number,
  selectedNodeId: string,
  currentTime: number,
): GradeGraph {
  const shot = shotAtTime(graph, currentTime);
  const selected = graph.nodes.find((node) => node.id === selectedNodeId);
  const selectedIsLook =
    selected?.type === "look" || selected?.type === "post_look";
  let target = selected;
  if (parameter === "exposure") {
    target =
      selected?.type === "balance"
        ? selected
        : graph.nodes.find(
            (node) =>
              node.type === "balance" &&
              (!shot || node.temporal_scope.shot_id === shot.id),
          );
  } else if (parameter === "temperature") {
    target = selectedIsLook
      ? selected
      : selected?.type === "balance"
        ? selected
        : graph.nodes.find(
            (node) =>
              node.type === "balance" &&
              (!shot || node.temporal_scope.shot_id === shot.id),
          );
  } else if (parameter === "strength" || parameter === "contrast") {
    target =
      selectedIsLook
        ? selected
        : lookAtTime(graph, currentTime);
  } else if (parameter === "saturation") {
    target =
      selectedIsLook || selected?.type === "masked_grade"
        ? selected
        : lookAtTime(graph, currentTime);
  } else if (parameter === "highlights") {
    target =
      selectedIsLook ||
      selected?.type === "masked_grade" ||
      selected?.type === "tone"
        ? selected
        : graph.nodes.find(
            (node) =>
              node.type === "masked_grade" &&
              node.spatial_scope.target === "sky",
          ) ?? target;
  }
  if (!target) return graph;
  const backendValue = value / 100;
  if (
    numberParameter(target, parameter, Number.NaN) === backendValue &&
    !target.tracks.some((track) => track.parameter === parameter)
  ) {
    return graph;
  }
  return {
    ...graph,
    updated_at: new Date().toISOString(),
    nodes: graph.nodes.map((node) =>
      node.id === target?.id
        ? {
            ...node,
            parameters: { ...node.parameters, [parameter]: backendValue },
            tracks: node.tracks.filter(
              (track) => track.parameter !== parameter,
            ),
            metadata:
              node.type === "look" || node.type === "post_look"
                ? {
                    ...node.metadata,
                    look_instance:
                      node.metadata.look_instance &&
                      typeof node.metadata.look_instance === "object"
                        ? {
                            ...node.metadata.look_instance,
                            user_overrides: {
                              ...(
                                Reflect.get(
                                  node.metadata.look_instance,
                                  "user_overrides",
                                ) as Record<string, number> | undefined
                              ),
                              [parameter]: backendValue,
                            },
                            dirty: true,
                          }
                        : node.metadata.look_instance,
                  }
                : node.metadata,
          }
        : node,
    ),
  };
}

function exposureKeyframeAt(
  graph: GradeGraph,
  nodeId: string,
  keyframeIndex: number,
) {
  const node = graph.nodes.find((candidate) => candidate.id === nodeId);
  const track = node?.tracks.find(
    (candidate) => candidate.parameter === "exposure",
  );
  return track?.keyframes[keyframeIndex];
}

function updateExposureKeyframe(
  graph: GradeGraph,
  nodeId: string,
  keyframeIndex: number,
  time: number,
  value: number,
  options: { commit: boolean },
): GradeGraph {
  let changed = false;
  const nodes = graph.nodes.map((node) => {
    if (node.id !== nodeId) return node;
    return {
      ...node,
      tracks: node.tracks.map((track) => {
        if (track.parameter !== "exposure") return track;
        return {
          ...track,
          keyframes: track.keyframes.map((keyframe, index) => {
            if (index !== keyframeIndex) return keyframe;
            if (
              keyframe.time_seconds === time &&
              keyframe.value === value
            ) {
              return keyframe;
            }
            changed = true;
            return { time_seconds: time, value };
          }),
        };
      }),
    };
  });
  if (!changed) return graph;
  return {
    ...graph,
    updated_at: options.commit ? new Date().toISOString() : graph.updated_at,
    nodes,
  };
}

function App() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const referenceInputRef = useRef<HTMLInputElement>(null);
  const toastTimerRef = useRef<number | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const taskAbortRef = useRef<AbortController | null>(null);
  const previewTimerRef = useRef<number | null>(null);
  const previewSequenceRef = useRef(0);
  const gradedPlaybackTimerRef = useRef<number | null>(null);
  const gradedPlaybackAbortRef = useRef<AbortController | null>(null);
  const gradedPlaybackSequenceRef = useRef(0);
  const gradedPlaybackRequestTimeRef = useRef<number | null>(null);
  const playbackTimeRef = useRef(0);
  const resumeAfterSegmentBufferRef = useRef(false);
  const playbackMediaRef = useRef<HTMLVideoElement>(null);
  const graphSaveSequenceRef = useRef(0);
  const commandUndoStackRef = useRef<GradeGraph[]>([]);
  const graphRef = useRef<GradeGraph | null>(null);
  const keyframeEditOriginRef = useRef<GradeGraph | null>(null);
  const gradeEditOriginRef = useRef<GradeGraph | null>(null);
  const graphUndoStackRef = useRef<GraphTransaction[]>([]);
  const graphRedoStackRef = useRef<GraphTransaction[]>([]);
  const pipelineWasOpenOnLoadRef = useRef(readPipelineOpenPreference());

  const [activePanel, setActivePanel] = useState<PanelId>("grade");
  const [selectedNodeId, setSelectedNodeId] = useState("look");
  const [activeLook, setActiveLook] = useState<LookId>("natural");
  const [grade, setGrade] = useState<GradeState>(DEFAULT_GRADE_STATE);
  const [mask, setMask] = useState<MaskKind>("none");
  const [comparePosition, setComparePosition] = useState(48);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(true);
  const [isLooping, setIsLooping] = useState(true);
  const [previewQualityPreference, setPreviewQualityPreference] =
    useState<PreviewQualityPreference>(readPreviewQualityPreference);
  const [previewEncodingPreference, setPreviewEncodingPreference] =
    useState<PreviewEncodingPreference>(readPreviewEncodingPreference);
  const [resolvedPreviewProfile, setResolvedPreviewProfile] =
    useState<PreviewPlaybackProfile | null>(null);
  const [actualPreviewProfile, setActualPreviewProfile] =
    useState<PreviewPlaybackProfile | null>(null);
  const [previewCapabilityMessage, setPreviewCapabilityMessage] = useState(
    "正在检测浏览器解码能力",
  );
  const [hevcPlaybackFailedFor, setHevcPlaybackFailedFor] = useState("");
  const [currentTime, setCurrentTime] = useState(0);
  const [command, setCommand] = useState("");
  const [isCommandProcessing, setIsCommandProcessing] = useState(false);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [pipelineOpen, setPipelineOpen] = useState(false);
  const [pipelineJob, setPipelineJob] = useState<JobRecord | null>(null);
  const [pipelineError, setPipelineError] = useState("");
  const [analysisRequestActive, setAnalysisRequestActive] = useState(false);
  const [localImportOpen, setLocalImportOpen] = useState(false);
  const [localImportPath, setLocalImportPath] = useState("");
  const [localImportSuggestedFilename, setLocalImportSuggestedFilename] =
    useState("");
  const [isLocalImporting, setIsLocalImporting] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [toast, setToast] = useState("");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [graph, setGraph] = useState<GradeGraph | null>(null);
  const [device, setDevice] = useState<DeviceInfo | null>(null);
  const [inputColorProfile, setInputColorProfile] =
    useState<InputColorProfile>("rec709");
  const [referenceFile, setReferenceFile] = useState<File | null>(null);
  const [quality, setQuality] = useState<QualityReport | null>(null);
  const [lookCandidates, setLookCandidates] =
    useState<CandidateComparison | null>(null);
  const [creativeAgentSnapshot, setCreativeAgentSnapshot] =
    useState<CreativeAgentSnapshot | null>(null);
  const [creativeAgentPreferences, setCreativeAgentPreferences] =
    useState<CreativeAgentPreferenceMemory | null>(null);
  const [creativeAgentLoading, setCreativeAgentLoading] = useState(false);
  const [creativeAgentBusy, setCreativeAgentBusy] = useState(false);
  const [creativeAgentError, setCreativeAgentError] = useState("");
  const [creativeAgentUserScope] = useState(readAgentUserScope);
  const [lookRecipeCatalog, setLookRecipeCatalog] =
    useState<LookRecipeCatalog | null>(null);
  const [lookCandidatesStale, setLookCandidatesStale] = useState(false);
  const [pendingLookSwitch, setPendingLookSwitch] =
    useState<LookId | null>(null);
  const [isComparingLooks, setIsComparingLooks] = useState(false);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [gradedPlaybackSegments, setGradedPlaybackSegments] = useState<
    PreviewPlaybackSegment[]
  >([]);
  const [gradedPlaybackGroupKey, setGradedPlaybackGroupKey] = useState<
    string | undefined
  >(undefined);
  const [gradedPlaybackStatus, setGradedPlaybackStatus] = useState<
    "idle" | "rendering" | "ready" | "error"
  >("idle");
  const [gradedPlaybackProgress, setGradedPlaybackProgress] = useState(0);
  const [isTimelineScrubbing, setIsTimelineScrubbing] = useState(false);
  const [isGradeEditing, setIsGradeEditing] = useState(false);
  const [isGraphSaving, setIsGraphSaving] = useState(false);
  const [graphHistory, setGraphHistory] = useState({
    undo: 0,
    redo: 0,
  });
  const [preview, setPreview] = useState<{
    graded: string;
    original: string;
    fps: number | null;
    timeSeconds: number;
  } | null>(null);
  const [media, setMedia] = useState<{
    source: string;
    kind: MediaKind;
    name: string;
  }>({
    source: SOURCE_IMAGE,
    kind: "image",
    name: "等待导入风景视频",
  });

  const nodes = useMemo(() => (graph ? graphToNodes(graph) : []), [graph]);
  const shots = useMemo(() => (graph ? graphToShots(graph) : []), [graph]);
  const analysisComplete = useMemo(
    () => hasCompleteMaskAnalysis(graph),
    [graph],
  );
  const timelineScenes = useMemo(
    () => (graph ? graphToTimelineScenes(graph) : []),
    [graph],
  );
  const activeLookInstance = useMemo(
    () =>
      graph
        ? lookInstanceFromGraph(graph, currentTime)
        : {
            baseRecipeId: activeLook,
            recipeVersion: null,
            overrides: {},
            dirty: false,
          },
    [activeLook, currentTime, graph],
  );
  const lookComparisonIsStale = Boolean(
    lookCandidates &&
      (lookCandidatesStale ||
        Math.abs(currentTime - lookCandidates.time_seconds) >
          0.5 / Math.max(graph?.media.fps ?? 1, 1)),
  );
  const duration = graph?.media.duration_seconds ?? 0;
  const previewQuality =
    previewQualityPreference === "auto"
      ? (resolvedPreviewProfile?.quality ?? DEFAULT_PREVIEW_QUALITY)
      : previewQualityPreference;
  const previewQualityOptions = useMemo(
    () =>
      graph
        ? availablePreviewQualities(
            graph.media.width,
            graph.media.height,
          )
        : [DEFAULT_PREVIEW_QUALITY, "540p" as const],
    [graph?.media.height, graph?.media.width],
  );
  const previewProfile = useMemo(
    () =>
      resolvedPreviewProfile ??
      buildPreviewPlaybackProfile(
        previewQuality,
        "h264",
        graph?.media.width ?? 1920,
        graph?.media.height ?? 1080,
        graph?.media.fps ?? 30,
      ),
    [
      graph?.media.fps,
      graph?.media.height,
      graph?.media.width,
      previewQuality,
      resolvedPreviewProfile,
    ],
  );
  const activeGradedPlaybackSegment = useMemo(
    () => playbackSegmentAt(gradedPlaybackSegments, currentTime, duration),
    [currentTime, duration, gradedPlaybackSegments],
  );
  const gradedPlaybackBufferEnd = useMemo(
    () =>
      contiguousPlaybackBufferEnd(
        gradedPlaybackSegments,
        currentTime,
        duration,
      ),
    [currentTime, duration, gradedPlaybackSegments],
  );
  const gradedPlaybackBufferedAhead = Math.max(
    0,
    gradedPlaybackBufferEnd - currentTime,
  );
  const gradedPlaybackBufferReady = Boolean(
    activeGradedPlaybackSegment &&
      gradedPlaybackBufferedAhead + 1e-3 >=
        Math.min(
          PREVIEW_START_BUFFER_SECONDS,
          Math.max(0, duration - currentTime),
        ),
  );
  const selectedShot = useMemo(
    () =>
      shots.find(
        (shot) =>
          currentTime >= shot.start &&
          currentTime < shot.start + shot.duration,
      ) ?? shots.at(-1),
    [currentTime, shots],
  );
  const pipelineStage = pipelineJob
    ? (STAGE_INDEX[pipelineJob.stage] ?? 0)
    : pipelineOpen
      ? 0
      : -1;
  const isAnalyzing =
    !pipelineError &&
    (analysisRequestActive ||
      pipelineJob?.status === "queued" ||
      pipelineJob?.status === "running");

  const showToast = useCallback((message: string) => {
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    setToast(message);
    toastTimerRef.current = window.setTimeout(() => setToast(""), 3800);
  }, []);

  const refreshCreativeAgent = useCallback(
    async (silent = false) => {
      if (!projectId) return;
      if (!silent) setCreativeAgentLoading(true);
      try {
        const [snapshot, preferences] = await Promise.all([
          getCreativeAgentSnapshot(projectId),
          getCreativeAgentPreferences(projectId, creativeAgentUserScope),
        ]);
        setCreativeAgentSnapshot(snapshot);
        setCreativeAgentPreferences(preferences);
        setCreativeAgentError("");
      } catch (error) {
        setCreativeAgentError(
          error instanceof Error ? error.message : "无法读取创意 Agent 状态",
        );
      } finally {
        if (!silent) setCreativeAgentLoading(false);
      }
    },
    [creativeAgentUserScope, projectId],
  );

  const handleMediaTimeChange = useCallback(
    (time: number) => {
      const next = Math.max(0, Math.min(duration || Number.MAX_VALUE, time));
      playbackTimeRef.current = next;
      setCurrentTime((previous) =>
        Math.abs(previous - next) < 1e-4 ? previous : next,
      );
    },
    [duration],
  );

  const seekMedia = useCallback(
    (time: number) => {
      const target = Math.max(0, Math.min(duration, time));
      playbackTimeRef.current = target;
      const mediaElement = playbackMediaRef.current;
      if (mediaElement && media.kind === "video") {
        mediaElement.currentTime = target;
        setCurrentTime(mediaElement.currentTime);
        return;
      }
      setCurrentTime(target);
    },
    [duration, media.kind],
  );

  const handlePreviewQualityChange = useCallback(
    (quality: PreviewQualityPreference) => {
      setHevcPlaybackFailedFor("");
      setPreviewQualityPreference(quality);
      rememberPreviewPreference(quality, previewEncodingPreference);
    },
    [previewEncodingPreference],
  );

  const handlePreviewEncodingChange = useCallback(
    (preference: PreviewEncodingPreference) => {
      setHevcPlaybackFailedFor("");
      setPreviewEncodingPreference(preference);
      rememberPreviewPreference(previewQualityPreference, preference);
    },
    [previewQualityPreference],
  );

  const handlePlaybackError = useCallback(
    (message: string) => {
      const failureKey = `${projectId ?? "none"}:${previewQuality}`;
      if (
        previewProfile.codec === "hevc" &&
        hevcPlaybackFailedFor !== failureKey
      ) {
        setHevcPlaybackFailedFor(failureKey);
        showToast(`HEVC Main10 播放失败，正在回退 H.264 8-bit：${message}`);
        return;
      }
      showToast(message);
    },
    [
      hevcPlaybackFailedFor,
      previewProfile.codec,
      previewQuality,
      projectId,
      showToast,
    ],
  );

  const handlePlaybackTelemetry = useCallback(
    (telemetry: PreviewPlaybackTelemetry) => {
      if (!projectId) return;
      void recordPreviewPlaybackMetrics(projectId, telemetry).catch(() => {
        // Playback must remain available if optional local diagnostics fail.
      });
    },
    [projectId],
  );

  const togglePlayback = useCallback(() => {
    const mediaElement = playbackMediaRef.current;
    if (!mediaElement || media.kind !== "video" || duration <= 0) {
      showToast("请先导入并完成视频分析");
      return;
    }
    if (isPlaying || (!mediaElement.paused && !mediaElement.ended)) {
      resumeAfterSegmentBufferRef.current = false;
      if (gradedPlaybackTimerRef.current !== null) {
        window.clearTimeout(gradedPlaybackTimerRef.current);
        gradedPlaybackTimerRef.current = null;
      }
      gradedPlaybackSequenceRef.current += 1;
      gradedPlaybackAbortRef.current?.abort();
      gradedPlaybackAbortRef.current = null;
      gradedPlaybackRequestTimeRef.current = null;
      setIsPlaying(false);
      mediaElement.pause();
      setGradedPlaybackProgress(0);
      setGradedPlaybackStatus(
        activeGradedPlaybackSegment ? "ready" : "idle",
      );
      return;
    }
    setIsPlaying(true);
    if (!gradedPlaybackBufferReady || gradedPlaybackStatus !== "ready") {
      resumeAfterSegmentBufferRef.current = true;
      if (gradedPlaybackStatus === "error") {
        setGradedPlaybackSegments([]);
        setGradedPlaybackGroupKey(undefined);
        setGradedPlaybackStatus("rendering");
      }
      showToast("已加入播放队列，真实调色首段完成后将自动播放");
      return;
    }
    resumeAfterSegmentBufferRef.current = false;
    if (mediaElement.paused || mediaElement.ended) {
      if (
        mediaElement.ended ||
        mediaElement.currentTime >= duration - 1 / Math.max(graph?.media.fps ?? 1, 1)
      ) {
        mediaElement.currentTime = 0;
      }
      previewSequenceRef.current += 1;
      setIsPreviewLoading(false);
      void mediaElement.play().catch((error) => {
        setIsPlaying(false);
        showToast(
          `播放失败：${error instanceof Error ? error.message : "浏览器拒绝播放"}`,
        );
      });
      return;
    }
    mediaElement.pause();
  }, [
    activeGradedPlaybackSegment,
    duration,
    gradedPlaybackBufferReady,
    gradedPlaybackStatus,
    graph?.media.fps,
    isPlaying,
    media.kind,
    showToast,
  ]);

  const applyGraph = useCallback((nextGraph: GradeGraph, time = currentTime) => {
    graphRef.current = nextGraph;
    setGraph(nextGraph);
    setInputColorProfile(inputColorProfileFromGraph(nextGraph));
    setGrade(gradeFromGraph(nextGraph, time, selectedNodeId));
    setActiveLook(lookFromGraph(nextGraph, time));
    const currentSelectedStillExists = nextGraph.nodes.some(
      (node) => node.id === selectedNodeId,
    );
    if (!currentSelectedStillExists) {
      setSelectedNodeId(
        nextGraph.nodes.find((node) => node.type === "look")?.id ??
          nextGraph.nodes[0]?.id ??
          "",
      );
    }
  }, [currentTime, selectedNodeId]);

  const requestPreview = useCallback(
    async (targetProjectId: string, time: number) => {
      const sequence = ++previewSequenceRef.current;
      setIsPreviewLoading(true);
      try {
        const result = await renderPreview(targetProjectId, time);
        if (sequence !== previewSequenceRef.current) return;
        const cacheKey = `${Date.now()}`;
        setPreview({
          graded: `${assetUrl(result.url)}?v=${cacheKey}`,
          original: `${assetUrl(result.source_url)}?v=${cacheKey}`,
          fps:
            typeof result.metrics.fps === "number"
              ? result.metrics.fps
              : null,
          timeSeconds: result.time_seconds,
        });
      } catch (error) {
        if (sequence === previewSequenceRef.current) {
          showToast(
            `预览失败：${error instanceof Error ? error.message : "未知错误"}`,
          );
        }
      } finally {
        if (sequence === previewSequenceRef.current) {
          setIsPreviewLoading(false);
        }
      }
    },
    [showToast],
  );

  const requestGradedPlaybackSegment = useCallback(
    async (
      targetProjectId: string,
      graphSnapshot: GradeGraph,
      profile: PreviewPlaybackProfile,
      timeSeconds: number,
      {
        priority,
        groupKey,
      }: {
        priority: boolean;
        groupKey?: string;
      },
    ) => {
      const sequence = ++gradedPlaybackSequenceRef.current;
      gradedPlaybackAbortRef.current?.abort();
      const controller = new AbortController();
      gradedPlaybackAbortRef.current = controller;
      gradedPlaybackRequestTimeRef.current = timeSeconds;
      setGradedPlaybackProgress(0);
      if (priority) {
        setGradedPlaybackStatus("rendering");
      }
      try {
        const prepared = await preparePreviewVideoSegment(
          targetProjectId,
          profile,
          graphSnapshot,
          timeSeconds,
          {
            priority,
            groupKey,
            signal: controller.signal,
          },
        );
        if (sequence !== gradedPlaybackSequenceRef.current) return;
        let videoUrl = prepared.url;
        if (prepared.status === "ready" && prepared.url) {
          videoUrl = prepared.url;
        } else {
          if (!prepared.job_id) {
            throw new Error("后端未返回真实调色分片任务");
          }
          const completed = await waitForJob(
            prepared.job_id,
            (job) => {
              if (sequence === gradedPlaybackSequenceRef.current) {
                setGradedPlaybackProgress(job.progress);
              }
            },
            controller.signal,
          );
          if (sequence !== gradedPlaybackSequenceRef.current) return;
          const completedVideoUrl = completed.result?.video_url;
          const cacheKey = completed.result?.cache_key;
          if (
            typeof completedVideoUrl !== "string" ||
            cacheKey !== prepared.cache_key
          ) {
            throw new Error("真实调色分片任务返回了无效结果");
          }
          videoUrl = completedVideoUrl;
        }
        if (!videoUrl) {
          throw new Error("真实调色分片没有可播放地址");
        }
        const segment: PreviewPlaybackSegment = {
          cache_key: prepared.cache_key,
          group_key: prepared.group_key,
          url: assetUrl(videoUrl),
          start_seconds: prepared.start_seconds,
          end_seconds: prepared.end_seconds,
          profile: prepared.profile,
        };
        setGradedPlaybackGroupKey(prepared.group_key);
        setGradedPlaybackSegments((current) => {
          const compatible = current.filter(
            (item) => item.group_key === prepared.group_key,
          );
          return [
            ...compatible.filter(
              (item) => item.cache_key !== segment.cache_key,
            ),
            segment,
          ].sort((left, right) => left.start_seconds - right.start_seconds);
        });
        setActualPreviewProfile(prepared.profile);
        if (priority) {
          setGradedPlaybackProgress(100);
          setGradedPlaybackStatus("ready");
        }
        return segment;
      } catch (error) {
        if (
          sequence !== gradedPlaybackSequenceRef.current ||
          (error instanceof DOMException && error.name === "AbortError") ||
          (!priority && error instanceof ApiError && error.status === 409)
        ) {
          return;
        }
        if (priority) {
          setGradedPlaybackStatus("error");
          setGradedPlaybackProgress(0);
          showToast(
            `真实调色分片失败：${
              error instanceof Error ? error.message : "未知错误"
            }`,
          );
        }
      } finally {
        if (sequence === gradedPlaybackSequenceRef.current) {
          gradedPlaybackAbortRef.current = null;
          gradedPlaybackRequestTimeRef.current = null;
        }
      }
    },
    [showToast],
  );

  const requestLookCandidates = useCallback(
    async (
      targetProjectId: string,
      time: number,
      prompt: string,
      silent = false,
    ) => {
      setIsComparingLooks(true);
      try {
        const comparison = await compareLookCandidates(
          targetProjectId,
          time,
          prompt,
        );
        const withAbsoluteUrls: CandidateComparison = {
          ...comparison,
          candidates: comparison.candidates.map((candidate) => ({
            ...candidate,
            url: assetUrl(candidate.url),
          })),
        };
        setLookCandidates(withAbsoluteUrls);
        setLookCandidatesStale(false);
        setPendingLookSwitch(null);
        if (!silent) {
          const recommended = withAbsoluteUrls.candidates.find(
            (candidate) =>
              candidate.recipe_id === withAbsoluteUrls.recommended_id,
          );
          showToast(
            `候选比较完成：推荐「${recommended?.label ?? withAbsoluteUrls.recommended_id}」`,
          );
        }
        return withAbsoluteUrls;
      } catch (error) {
        if (!silent) {
          showToast(
            `候选比较失败：${error instanceof Error ? error.message : "未知错误"}`,
          );
        }
        return null;
      } finally {
        setIsComparingLooks(false);
      }
    },
    [showToast],
  );

  const refreshGraph = useCallback(
    async (targetProjectId: string, time = currentTime) => {
      const nextGraph = await getGraph(targetProjectId);
      applyGraph(nextGraph, time);
      return nextGraph;
    },
    [applyGraph, currentTime],
  );

  const followJob = useCallback(
    async (jobId: string, onUpdate?: (job: JobRecord) => void) => {
      taskAbortRef.current?.abort();
      const controller = new AbortController();
      taskAbortRef.current = controller;
      setPipelineError("");
      const completed = await waitForJob(
        jobId,
        (job) => {
          setPipelineJob(job);
          onUpdate?.(job);
        },
        controller.signal,
      );
      setPipelineJob(completed);
      return completed;
    },
    [],
  );

  useEffect(() => {
    void getDevice()
      .then(setDevice)
      .catch(() => {
        setDevice(null);
        showToast("本地后端未连接，请先启动 ColorGraph API");
      });
    void getLookRecipes()
      .then(setLookRecipeCatalog)
      .catch(() => setLookRecipeCatalog(null));
  }, [showToast]);

  useEffect(() => {
    if (!graph || media.kind !== "video") {
      setResolvedPreviewProfile(null);
      return;
    }
    if (
      previewQualityPreference !== "auto" &&
      !previewQualityOptions.includes(previewQualityPreference)
    ) {
      const fallbackQuality = previewQualityOptions[0] ?? "540p";
      setPreviewQualityPreference(fallbackQuality);
      rememberPreviewPreference(
        fallbackQuality,
        previewEncodingPreference,
      );
      return;
    }
    let cancelled = false;
    const failureKey = `${projectId ?? "none"}:${previewQuality}`;
    setPreviewCapabilityMessage("正在检测浏览器解码能力");
    void resolvePreviewPlaybackProfile({
      quality: previewQualityPreference,
      preference: previewEncodingPreference,
      sourceWidth: graph.media.width,
      sourceHeight: graph.media.height,
      sourceFps: graph.media.fps,
      forceH264: hevcPlaybackFailedFor === failureKey,
    }).then((resolution) => {
      if (cancelled) return;
      setResolvedPreviewProfile(resolution.profile);
      setPreviewCapabilityMessage(resolution.message);
    });
    return () => {
      cancelled = true;
    };
  }, [
    graph,
    hevcPlaybackFailedFor,
    media.kind,
    previewEncodingPreference,
    previewQuality,
    previewQualityPreference,
    previewQualityOptions,
    projectId,
  ]);

  useEffect(() => {
    if (!projectId || !graph || media.kind !== "video") return;
    const source = previewSourceUrl(
      `/api/projects/${projectId}/source`,
      previewProfile,
    );
    setMedia((current) =>
      current.kind === "video" && current.source !== source
        ? { ...current, source }
        : current,
    );
  }, [
    graph,
    media.kind,
    previewProfile,
    projectId,
  ]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const restore = async () => {
      try {
        const storedProjectId = window.localStorage.getItem(
          "colorgraph.lastProjectId",
        );
        const summaries = await listProjects();
        const storedMaskJob = readStoredMaskJob();
        let activeMaskJob: JobRecord | null = null;
        if (storedMaskJob) {
          try {
            const storedJob = await getJob(storedMaskJob.jobId);
            if (
              storedJob.kind === "masks" &&
              storedJob.project_id === storedMaskJob.projectId &&
              (storedJob.status === "queued" ||
                storedJob.status === "running")
            ) {
              activeMaskJob = storedJob;
            } else {
              forgetMaskJob(storedMaskJob.jobId);
            }
          } catch {
            forgetMaskJob(storedMaskJob.jobId);
          }
        }
        const activeProjectId = activeMaskJob?.project_id;
        const project = startupProject(
          summaries,
          storedProjectId,
          activeProjectId,
        );
        if (!project || cancelled) return;
        const restoredGraph = await getGraph(project.project_id);
        if (cancelled) return;
        setProjectId(project.project_id);
        setGraph(restoredGraph);
        setInputColorProfile(inputColorProfileFromGraph(restoredGraph));
        setGrade(
          gradeFromGraph(
            restoredGraph,
            0,
            restoredGraph.nodes.find((node) => node.type === "look")?.id,
          ),
        );
        setActiveLook(lookFromGraph(restoredGraph, 0));
        setSelectedNodeId(
          restoredGraph.nodes.find((node) => node.type === "look")?.id ??
            restoredGraph.nodes[0]?.id ??
            "",
        );
        const restoredPreviewQuality = readPreviewQualityPreference();
        setPreviewQualityPreference(restoredPreviewQuality);
        const restoredPreviewProfile = buildPreviewPlaybackProfile(
          restoredPreviewQuality === "auto"
            ? DEFAULT_PREVIEW_QUALITY
            : restoredPreviewQuality,
          "h264",
          restoredGraph.media.width,
          restoredGraph.media.height,
          restoredGraph.media.fps,
        );
        setResolvedPreviewProfile(restoredPreviewProfile);
        setMedia({
          source: previewSourceUrl(
            project.source_url,
            restoredPreviewProfile,
          ),
          kind: "video",
          name: restoredGraph.project_name,
        });
        window.localStorage.setItem(
          "colorgraph.lastProjectId",
          project.project_id,
        );
        await requestPreview(project.project_id, 0);
        if (PERSIST_MASK_JOB_STATE && !activeMaskJob) {
          try {
            activeMaskJob = await getActiveMaskJob(project.project_id);
          } catch {
            // Older backends do not expose active-job discovery. The stored
            // job id above still restores jobs started by this frontend.
          }
        }
        if (
          !activeMaskJob ||
          cancelled ||
          (activeMaskJob.status !== "queued" &&
            activeMaskJob.status !== "running")
        ) {
          return;
        }
        rememberMaskJob(activeMaskJob.id, project.project_id);
        setPipelineError("");
        setPipelineJob(activeMaskJob);
        setPipelineOpen(pipelineWasOpenOnLoadRef.current);
        try {
          const completed = await waitForJob(
            activeMaskJob.id,
            (job) => {
              if (!cancelled) setPipelineJob(job);
            },
            controller.signal,
          );
          if (cancelled) return;
          setPipelineJob(completed);
          forgetMaskJob(completed.id);
          const completedGraph = await getGraph(project.project_id);
          if (cancelled) return;
          setGraph(completedGraph);
          setInputColorProfile(inputColorProfileFromGraph(completedGraph));
          setGrade(
            gradeFromGraph(
              completedGraph,
              0,
              completedGraph.nodes.find((node) => node.type === "look")?.id,
            ),
          );
          setActiveLook(lookFromGraph(completedGraph, 0));
          await requestPreview(project.project_id, 0);
          showToast(
            `AI 分析完成：${completedGraph.masks.length} 组真实逐帧蒙版已恢复`,
          );
        } catch (error) {
          if (
            cancelled ||
            (error instanceof DOMException && error.name === "AbortError")
          ) {
            return;
          }
          const message = error instanceof Error ? error.message : "未知错误";
          setPipelineError(message);
          showToast(`恢复 AI 分析失败：${message}`);
        }
      } catch {
        window.localStorage.removeItem("colorgraph.lastProjectId");
      }
    };
    void restore();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [requestPreview, showToast]);

  useEffect(() => {
    if (pipelineJob?.kind !== "masks") return;
    if (
      pipelineJob.status === "queued" ||
      pipelineJob.status === "running"
    ) {
      rememberMaskJob(pipelineJob.id, pipelineJob.project_id);
      return;
    }
    forgetMaskJob(pipelineJob.id);
  }, [pipelineJob]);

  useEffect(() => {
    rememberPipelineOpenPreference(pipelineOpen);
  }, [pipelineOpen]);

  useEffect(() => {
    return () => {
      taskAbortRef.current?.abort();
      gradedPlaybackAbortRef.current?.abort();
      if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
      if (previewTimerRef.current) window.clearTimeout(previewTimerRef.current);
      if (gradedPlaybackTimerRef.current) {
        window.clearTimeout(gradedPlaybackTimerRef.current);
      }
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    };
  }, []);

  useEffect(() => {
    if (!projectId || !graph) return;
    if (previewTimerRef.current) window.clearTimeout(previewTimerRef.current);
    if (isPlaying || isTimelineScrubbing || isGradeEditing) return;
    previewTimerRef.current = window.setTimeout(
      () => void requestPreview(projectId, currentTime),
      220,
    );
    return () => {
      if (previewTimerRef.current) window.clearTimeout(previewTimerRef.current);
    };
  }, [
    currentTime,
    graph,
    isGradeEditing,
    isPlaying,
    isTimelineScrubbing,
    projectId,
    requestPreview,
  ]);

  useEffect(() => {
    if (gradedPlaybackTimerRef.current) {
      window.clearTimeout(gradedPlaybackTimerRef.current);
    }
    gradedPlaybackAbortRef.current?.abort();
    gradedPlaybackSequenceRef.current += 1;
    playbackMediaRef.current?.pause();
    setIsPlaying(false);
    resumeAfterSegmentBufferRef.current = false;
    setGradedPlaybackSegments([]);
    setGradedPlaybackGroupKey(undefined);
    setActualPreviewProfile(null);
    setGradedPlaybackProgress(0);
    if (!projectId || !graph || media.kind !== "video") {
      setGradedPlaybackStatus("idle");
      return;
    }
    setGradedPlaybackStatus("rendering");
    const graphSnapshot = graph;
    gradedPlaybackTimerRef.current = window.setTimeout(
      () => {
        gradedPlaybackTimerRef.current = null;
        void requestGradedPlaybackSegment(
          projectId,
          graphSnapshot,
          previewProfile,
          playbackTimeRef.current,
          { priority: true },
        );
      },
      450,
    );
    return () => {
      if (gradedPlaybackTimerRef.current) {
        window.clearTimeout(gradedPlaybackTimerRef.current);
      }
    };
  }, [
    graph,
    media.kind,
    previewProfile,
    projectId,
    requestGradedPlaybackSegment,
  ]);

  useEffect(() => {
    if (
      !projectId ||
      !graph ||
      media.kind !== "video" ||
      duration <= 0 ||
      gradedPlaybackStatus === "error"
    ) {
      return;
    }
    const requestTime = gradedPlaybackRequestTimeRef.current;
    const requestPending = gradedPlaybackAbortRef.current !== null;
    if (!activeGradedPlaybackSegment) {
      if (!isPlaying && !resumeAfterSegmentBufferRef.current) {
        return;
      }
      setGradedPlaybackStatus("rendering");
      const master = playbackMediaRef.current;
      if (master && !master.paused && !master.ended) {
        resumeAfterSegmentBufferRef.current = true;
        master.pause();
      }
      if (gradedPlaybackTimerRef.current !== null) {
        return;
      }
      const pendingMatchesCurrent =
        requestPending &&
        requestTime !== null &&
        previewSegmentIndex(requestTime, duration) ===
          previewSegmentIndex(currentTime, duration);
      if (!pendingMatchesCurrent) {
        void requestGradedPlaybackSegment(
          projectId,
          graph,
          previewProfile,
          currentTime,
          { priority: true },
        );
      }
      return;
    }

    if (gradedPlaybackStatus === "rendering") {
      setGradedPlaybackStatus("ready");
    }
    if (
      resumeAfterSegmentBufferRef.current &&
      gradedPlaybackBufferReady &&
      playbackMediaRef.current?.paused
    ) {
      resumeAfterSegmentBufferRef.current = false;
      void playbackMediaRef.current.play().catch(() => {
        setIsPlaying(false);
      });
    }
    if (
      (isPlaying || resumeAfterSegmentBufferRef.current) &&
      gradedPlaybackGroupKey &&
      gradedPlaybackBufferEnd < duration - 1e-3 &&
      gradedPlaybackBufferedAhead < PREVIEW_AHEAD_BUFFER_SECONDS &&
      !requestPending
    ) {
      void requestGradedPlaybackSegment(
        projectId,
        graph,
        previewProfile,
        Math.min(duration - 1e-6, gradedPlaybackBufferEnd + 1e-3),
        {
          priority: false,
          groupKey: gradedPlaybackGroupKey,
        },
      );
    }
  }, [
    activeGradedPlaybackSegment,
    currentTime,
    duration,
    graph,
    gradedPlaybackBufferEnd,
    gradedPlaybackBufferReady,
    gradedPlaybackBufferedAhead,
    gradedPlaybackGroupKey,
    gradedPlaybackStatus,
    isPlaying,
    media.kind,
    previewProfile,
    projectId,
    requestGradedPlaybackSegment,
  ]);

  useEffect(() => {
    graphRef.current = graph;
  }, [graph]);

  useEffect(() => {
    if (!graph) return;
    setGrade(gradeFromGraph(graph, currentTime, selectedNodeId));
    setActiveLook(lookFromGraph(graph, currentTime));
  }, [currentTime, graph, selectedNodeId]);

  useEffect(() => {
    commandUndoStackRef.current = [];
    keyframeEditOriginRef.current = null;
    gradeEditOriginRef.current = null;
    graphUndoStackRef.current = [];
    graphRedoStackRef.current = [];
    setGraphHistory({ undo: 0, redo: 0 });
    setLookCandidatesStale(false);
    setPendingLookSwitch(null);
    setIsGradeEditing(false);
  }, [projectId]);

  useEffect(() => {
    setCreativeAgentSnapshot(null);
    setCreativeAgentPreferences(null);
    setCreativeAgentError("");
  }, [projectId]);

  useEffect(() => {
    if (activePanel !== "agent" || !projectId) return;
    void refreshCreativeAgent();
  }, [activePanel, projectId, refreshCreativeAgent]);

  useEffect(() => {
    if (
      activePanel !== "agent" ||
      !projectId ||
      !creativeAgentSnapshot ||
      (!["running", "waiting_for_consent"].includes(
        creativeAgentSnapshot.status,
      ) &&
        !creativeAgentSnapshot.resume_requested)
    ) {
      return;
    }
    const timer = window.setInterval(
      () => void refreshCreativeAgent(true),
      900,
    );
    return () => window.clearInterval(timer);
  }, [
    activePanel,
    creativeAgentSnapshot,
    projectId,
    refreshCreativeAgent,
  ]);

  const syncGraphHistory = useCallback(() => {
    setGraphHistory({
      undo: graphUndoStackRef.current.length,
      redo: graphRedoStackRef.current.length,
    });
  }, []);

  const clearGraphHistory = useCallback(() => {
    keyframeEditOriginRef.current = null;
    gradeEditOriginRef.current = null;
    graphUndoStackRef.current = [];
    graphRedoStackRef.current = [];
    setGraphHistory({ undo: 0, redo: 0 });
    setIsGradeEditing(false);
  }, []);

  const recordGraphTransaction = useCallback(
    (before: GradeGraph, after: GradeGraph, label: string) => {
      graphUndoStackRef.current.push({ before, after, label });
      if (graphUndoStackRef.current.length > 50) {
        graphUndoStackRef.current.shift();
      }
      graphRedoStackRef.current = [];
      syncGraphHistory();
    },
    [syncGraphHistory],
  );

  const handleCreativeAgentStart = useCallback(async (
    options: CreativeAgentStartOptions,
  ) => {
    if (!projectId || creativeAgentBusy) return;
    setCreativeAgentBusy(true);
    try {
      const result = await startCreativeAgentRun(projectId, options);
      setCreativeAgentSnapshot(result.snapshot);
      setCreativeAgentError("");
      showToast(
        result.mode === "provider_shadow"
          ? "Provider Shadow 已启动；上传边界与同意已写入运行快照"
          : "离线 Shadow 已启动；素材不会离开本机",
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "启动 Agent Shadow 失败";
      setCreativeAgentError(message);
      showToast(message);
    } finally {
      setCreativeAgentBusy(false);
    }
  }, [creativeAgentBusy, projectId, showToast]);

  const handleCreativeAgentControl = useCallback(
    async (action: "cancel" | "resume") => {
      if (!projectId || !creativeAgentSnapshot || creativeAgentBusy) return;
      setCreativeAgentBusy(true);
      try {
        const updated = await controlCreativeAgent(
          projectId,
          action,
          creativeAgentSnapshot.snapshot_revision,
        );
        setCreativeAgentSnapshot(updated);
        setCreativeAgentError("");
        showToast(
          action === "cancel"
            ? "已记录取消请求；当前阶段会在安全边界停止"
            : "已记录恢复请求；后端将从持久化状态继续",
        );
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Agent 控制请求失败";
        setCreativeAgentError(message);
        showToast(message);
      } finally {
        setCreativeAgentBusy(false);
      }
    },
    [
      creativeAgentBusy,
      creativeAgentSnapshot,
      projectId,
      showToast,
    ],
  );

  const handleCreativeAgentApply = useCallback(
    async (candidateId: string) => {
      const before = graphRef.current;
      if (
        !projectId ||
        !before ||
        !creativeAgentSnapshot ||
        creativeAgentBusy
      ) {
        return;
      }
      setCreativeAgentBusy(true);
      try {
        const result = await applyCreativeAgentCandidate(
          projectId,
          candidateId,
          creativeAgentSnapshot.current_graph_digest,
          creativeAgentSnapshot.snapshot_revision,
        );
        recordGraphTransaction(before, result.graph, "Agent 候选");
        applyGraph(result.graph);
        setLookCandidatesStale(true);
        setCreativeAgentError("");
        let previewWarning = "";
        try {
          await requestPreview(projectId, currentTime);
        } catch (error) {
          previewWarning =
            error instanceof Error ? error.message : "预览刷新失败";
        }
        showToast(
          previewWarning
            ? `候选已应用并保留撤销点；预览刷新失败：${previewWarning}`
            : `已应用候选并保存撤销点；作用域 ${result.application_scopes.length} 项`,
        );
        await refreshCreativeAgent(true);
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Agent 候选应用失败";
        setCreativeAgentError(message);
        showToast(message);
      } finally {
        setCreativeAgentBusy(false);
      }
    },
    [
      applyGraph,
      creativeAgentBusy,
      creativeAgentSnapshot,
      currentTime,
      projectId,
      recordGraphTransaction,
      refreshCreativeAgent,
      requestPreview,
      showToast,
    ],
  );

  const handleCreativeAgentFeedback = useCallback(
    async (
      candidateId: string,
      feedback: string,
      mode: "adjust_existing_strategy" | "new_thesis_branch",
    ) => {
      if (!projectId || !creativeAgentSnapshot || creativeAgentBusy) return;
      setCreativeAgentBusy(true);
      try {
        await requestCreativeAgentFeedback(
          projectId,
          candidateId,
          feedback,
          creativeAgentSnapshot.snapshot_revision,
          mode,
        );
        setCreativeAgentError("");
        showToast(
          mode === "new_thesis_branch"
            ? "反馈已保存为显式新命题分支请求"
            : "反馈已保存；只会调整现有策略并重渲染同一证据帧",
        );
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Agent 反馈请求失败";
        setCreativeAgentError(message);
        showToast(message);
      } finally {
        setCreativeAgentBusy(false);
      }
    },
    [
      creativeAgentBusy,
      creativeAgentSnapshot,
      projectId,
      showToast,
    ],
  );

  const handleCreativeAgentPreference = useCallback(
    async (candidateId: string, comparedCandidateIds: string[]) => {
      if (!projectId || creativeAgentBusy) return;
      setCreativeAgentBusy(true);
      try {
        const memory = await addCreativeAgentPreference(
          projectId,
          creativeAgentUserScope,
          candidateId,
          comparedCandidateIds,
        );
        setCreativeAgentPreferences(memory);
        setCreativeAgentError("");
        showToast("本次 A/B 选择仅保存到当前项目与本地用户范围");
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "保存项目偏好失败";
        setCreativeAgentError(message);
        showToast(message);
      } finally {
        setCreativeAgentBusy(false);
      }
    },
    [
      creativeAgentBusy,
      creativeAgentUserScope,
      projectId,
      showToast,
    ],
  );

  const handleDeleteCreativeAgentPreferences = useCallback(async () => {
    if (!projectId || creativeAgentBusy) return;
    setCreativeAgentBusy(true);
    try {
      await deleteCreativeAgentPreferences(
        projectId,
        creativeAgentUserScope,
      );
      setCreativeAgentPreferences({
        schema_version: "colorgraph.project-preference-memory/v1",
        project_id: projectId,
        user_scope_id: creativeAgentUserScope,
        entries: [],
      });
      setCreativeAgentError("");
      showToast("已删除当前项目与本地用户范围内的偏好记录");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "删除项目偏好失败";
      setCreativeAgentError(message);
      showToast(message);
    } finally {
      setCreativeAgentBusy(false);
    }
  }, [
    creativeAgentBusy,
    creativeAgentUserScope,
    projectId,
    showToast,
  ]);

  const persistCommittedGraph = useCallback(
    (nextGraph: GradeGraph, successMessage: string) => {
      if (!projectId) return;
      const sequence = ++graphSaveSequenceRef.current;
      setIsGraphSaving(true);
      void saveGraph(projectId, nextGraph)
        .then((savedGraph) => {
          if (sequence === graphSaveSequenceRef.current) {
            applyGraph(savedGraph);
          }
          showToast(successMessage);
          if (creativeAgentSnapshot) {
            void refreshCreativeAgent(true);
          }
          return requestPreview(projectId, currentTime);
        })
        .catch((error) =>
          showToast(
            `保存失败：${error instanceof Error ? error.message : "未知错误"}`,
          ),
        )
        .finally(() => {
          if (sequence === graphSaveSequenceRef.current) {
            setIsGraphSaving(false);
          }
        });
    },
    [
      applyGraph,
      creativeAgentSnapshot,
      currentTime,
      projectId,
      refreshCreativeAgent,
      requestPreview,
      showToast,
    ],
  );

  const undoGraphTransaction = useCallback(() => {
    const transaction = graphUndoStackRef.current.pop();
    if (!transaction || !projectId) return false;
    keyframeEditOriginRef.current = null;
    gradeEditOriginRef.current = null;
    setIsGradeEditing(false);
    graphRedoStackRef.current.push(transaction);
    applyGraph(transaction.before);
    setLookCandidatesStale(true);
    setPendingLookSwitch(null);
    syncGraphHistory();
    persistCommittedGraph(transaction.before, `已撤销${transaction.label}`);
    return true;
  }, [
    applyGraph,
    persistCommittedGraph,
    projectId,
    syncGraphHistory,
  ]);

  const redoGraphTransaction = useCallback(() => {
    const transaction = graphRedoStackRef.current.pop();
    if (!transaction || !projectId) return false;
    keyframeEditOriginRef.current = null;
    gradeEditOriginRef.current = null;
    setIsGradeEditing(false);
    graphUndoStackRef.current.push(transaction);
    applyGraph(transaction.after);
    setLookCandidatesStale(true);
    setPendingLookSwitch(null);
    syncGraphHistory();
    persistCommittedGraph(transaction.after, `已重做${transaction.label}`);
    return true;
  }, [
    applyGraph,
    persistCommittedGraph,
    projectId,
    syncGraphHistory,
  ]);

  useEffect(() => {
    const handleKeydown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isTyping =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.tagName === "SELECT";
      if (event.code === "Space" && !isTyping) {
        event.preventDefault();
        togglePlayback();
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        document
          .querySelector<HTMLInputElement>(".agent-command input")
          ?.focus();
      }
      if (
        (event.metaKey || event.ctrlKey) &&
        event.key.toLowerCase() === "z" &&
        !isTyping &&
        projectId
      ) {
        if (event.shiftKey) {
          if (redoGraphTransaction()) event.preventDefault();
        } else if (undoGraphTransaction()) {
          event.preventDefault();
        } else {
          const previousGraph = commandUndoStackRef.current.pop();
          if (previousGraph) {
            event.preventDefault();
            applyGraph(previousGraph);
            setLookCandidatesStale(true);
            setPendingLookSwitch(null);
            void saveGraph(projectId, previousGraph)
              .then((savedGraph) => {
                applyGraph(savedGraph);
                return requestPreview(projectId, currentTime);
              })
              .then(() => showToast("已撤销上一条自然语言调色命令"))
              .catch((error) =>
                showToast(
                  `撤销失败：${error instanceof Error ? error.message : "未知错误"}`,
                ),
              );
          }
        }
      }
      if (
        (event.metaKey || event.ctrlKey) &&
        event.key.toLowerCase() === "y" &&
        !isTyping &&
        projectId &&
        redoGraphTransaction()
      ) {
        event.preventDefault();
      }
      if (event.key === "Escape") {
        setPipelineOpen(false);
        setExportOpen(false);
        if (!isLocalImporting) setLocalImportOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, [
    applyGraph,
    currentTime,
    isLocalImporting,
    projectId,
    redoGraphTransaction,
    requestPreview,
    showToast,
    togglePlayback,
    undoGraphTransaction,
  ]);

  const performLookChange = async (
    look: LookId,
    discardOverrides = false,
  ) => {
    const beforeGraph = graphRef.current;
    const comparison = lookCandidates;
    const candidate = comparison?.candidates.find(
      (item) => item.recipe_id === look,
    );
    if (!beforeGraph || !projectId || !comparison || !candidate) {
      showToast("请先运行本地 A/B，固定配方占位图不能直接应用");
      return;
    }
    if (lookComparisonIsStale) {
      showToast("候选缩略图已过期，请重新比较后再应用");
      return;
    }
    const sequence = ++graphSaveSequenceRef.current;
    setIsGraphSaving(true);
    try {
      const result = await applyLookCandidate(
        projectId,
        look,
        candidate.recipe_version,
        comparison.graph_digest,
        comparison.time_seconds,
        discardOverrides,
      );
      if (sequence !== graphSaveSequenceRef.current) return;
      applyGraph(result.graph, comparison.time_seconds);
      // Applying one candidate only replaces the active Look recipe. Carry the
      // saved graph digest forward so the rest of this rendered A/B set remains
      // selectable while unrelated graph edits still invalidate it.
      setLookCandidates((current) =>
        current === comparison
          ? { ...current, graph_digest: result.graph_digest }
          : current,
      );
      setLookCandidatesStale(false);
      const activeLookNode = lookAtTime(
        result.graph,
        comparison.time_seconds,
      );
      setSelectedNodeId(activeLookNode?.id ?? selectedNodeId);
      setPendingLookSwitch(null);
      if (result.action === "applied") {
        recordGraphTransaction(
          beforeGraph,
          result.graph,
          `切换 Look「${LOOKS[look].name}」`,
        );
        await requestPreview(projectId, comparison.time_seconds);
        showToast(`已应用真实渲染候选「${LOOKS[look].name}」`);
      } else {
        showToast(`已保留「${LOOKS[look].name}」的当前项目修改`);
      }
    } catch (error) {
      const code = errorCode(error);
      if (code === "dirty_look_requires_confirmation") {
        setPendingLookSwitch(look);
        showToast("当前 Look 有项目修改，请确认后再切换");
      } else if (
        code === "stale_candidate" ||
        code === "recipe_version_mismatch"
      ) {
        setLookCandidatesStale(true);
        setPendingLookSwitch(null);
        showToast("候选已过期，请重新运行本地 A/B");
      } else {
        showToast(
          `应用 Look 失败：${error instanceof Error ? error.message : "未知错误"}`,
        );
      }
    } finally {
      if (sequence === graphSaveSequenceRef.current) {
        setIsGraphSaving(false);
      }
    }
  };

  const handleLookChange = (look: LookId) => {
    void performLookChange(look);
  };

  const handleRestoreOriginalLook = async () => {
    const beforeGraph = graphRef.current;
    if (!beforeGraph || !projectId) return;
    const sequence = ++graphSaveSequenceRef.current;
    setIsGraphSaving(true);
    try {
      const result = await restoreOriginalLook(projectId, currentTime);
      if (sequence !== graphSaveSequenceRef.current) return;
      applyGraph(result.graph);
      setPendingLookSwitch(null);
      if (result.action === "restored") {
        recordGraphTransaction(
          beforeGraph,
          result.graph,
          `恢复「${LOOKS[result.recipe_id].name}」原始配方`,
        );
        setLookCandidatesStale(true);
        await requestPreview(projectId, currentTime);
        showToast(`已恢复「${LOOKS[result.recipe_id].name}」原始配方`);
      } else {
        showToast("当前 Look 已是原始配方");
      }
    } catch (error) {
      showToast(
        `恢复 Look 失败：${error instanceof Error ? error.message : "未知错误"}`,
      );
    } finally {
      if (sequence === graphSaveSequenceRef.current) {
        setIsGraphSaving(false);
      }
    }
  };

  const handleGradeEditStart = () => {
    setIsGradeEditing(true);
    if (!gradeEditOriginRef.current) {
      gradeEditOriginRef.current = graphRef.current;
    }
  };

  const handleGradeChange = (
    parameter: GradeParameter,
    value: number,
  ) => {
    const currentGraph = graphRef.current;
    if (!currentGraph || !projectId) return;
    setIsGradeEditing(true);
    if (!gradeEditOriginRef.current) {
      gradeEditOriginRef.current = currentGraph;
    }
    const nextGraph = updateGraphParameter(
      currentGraph,
      parameter,
      value,
      selectedNodeId,
      currentTime,
    );
    if (nextGraph === currentGraph) return;
    applyGraph(nextGraph);
    setLookCandidatesStale(true);
    setPendingLookSwitch(null);
  };

  const handleGradeEditCommit = () => {
    const originGraph = gradeEditOriginRef.current;
    const nextGraph = graphRef.current;
    gradeEditOriginRef.current = null;
    setIsGradeEditing(false);
    if (!originGraph || !nextGraph || originGraph === nextGraph) return;
    const selected = nextGraph.nodes.find(
      (node) => node.id === selectedNodeId,
    );
    const label =
      selected?.type === "look" || selected?.type === "post_look"
        ? "Look 参数编辑"
        : `${selected?.label ?? "节点"}参数编辑`;
    recordGraphTransaction(originGraph, nextGraph, label);
    persistCommittedGraph(nextGraph, `${label}已保存`);
  };

  const handleExposureKeyframeEditStart = (
    nodeId: string,
    keyframeIndex: number,
  ) => {
    const currentGraph = graphRef.current;
    if (
      !keyframeEditOriginRef.current &&
      currentGraph &&
      exposureKeyframeAt(currentGraph, nodeId, keyframeIndex)
    ) {
      keyframeEditOriginRef.current = currentGraph;
    }
  };

  const handleExposureKeyframePreview = (
    nodeId: string,
    keyframeIndex: number,
    time: number,
    value: number,
  ) => {
    const currentGraph = graphRef.current;
    if (!currentGraph || !keyframeEditOriginRef.current) return;
    const nextGraph = updateExposureKeyframe(
      currentGraph,
      nodeId,
      keyframeIndex,
      time,
      value,
      { commit: false },
    );
    if (nextGraph === currentGraph) return;
    graphRef.current = nextGraph;
    setGraph(nextGraph);
  };

  const handleExposureKeyframeCommit = (
    nodeId: string,
    keyframeIndex: number,
    time: number,
    value: number,
  ) => {
    const originGraph = keyframeEditOriginRef.current;
    const currentGraph = graphRef.current;
    if (!originGraph || !currentGraph || !projectId) return;
    const originKeyframe = exposureKeyframeAt(
      originGraph,
      nodeId,
      keyframeIndex,
    );
    keyframeEditOriginRef.current = null;
    if (
      !originKeyframe ||
      (originKeyframe.time_seconds === time &&
        originKeyframe.value === value)
    ) {
      graphRef.current = originGraph;
      setGraph(originGraph);
      return;
    }
    const nextGraph = updateExposureKeyframe(
      currentGraph,
      nodeId,
      keyframeIndex,
      time,
      value,
      { commit: true },
    );
    recordGraphTransaction(
      originGraph,
      nextGraph,
      "Exposure 关键帧编辑",
    );
    applyGraph(nextGraph);
    setLookCandidatesStale(true);
    setPendingLookSwitch(null);
    persistCommittedGraph(nextGraph, "Exposure 关键帧已提交");
  };

  const handleExposureKeyframeCancel = () => {
    const originGraph = keyframeEditOriginRef.current;
    if (!originGraph) return;
    keyframeEditOriginRef.current = null;
    applyGraph(originGraph);
    showToast("已取消 Exposure 关键帧编辑");
  };

  const handleToggleNode = (id: string) => {
    const currentGraph = graphRef.current;
    if (!currentGraph || !projectId) return;
    const nextGraph: GradeGraph = {
      ...currentGraph,
      updated_at: new Date().toISOString(),
      nodes: currentGraph.nodes.map((node) =>
        node.id === id ? { ...node, enabled: !node.enabled } : node,
      ),
    };
    const toggled = nextGraph.nodes.find((node) => node.id === id);
    recordGraphTransaction(
      currentGraph,
      nextGraph,
      `${toggled?.label ?? "节点"}${toggled?.enabled ? "启用" : "停用"}`,
    );
    applyGraph(nextGraph);
    setLookCandidatesStale(true);
    setPendingLookSwitch(null);
    persistCommittedGraph(nextGraph, "节点状态已保存");
  };

  const runAnalysis = async () => {
    if (isAnalyzing) {
      setPipelineOpen(true);
      return;
    }
    if (!projectId) {
      fileInputRef.current?.click();
      return;
    }
    if (analysisComplete) {
      forgetMaskJob();
      setAnalysisRequestActive(true);
      setPipelineOpen(true);
      setPipelineError("");
      const replayJobId = `cached_analysis_replay_${projectId}_${Date.now()}`;
      const replayStage = async (
        stage: JobRecord["stage"],
        progress: number,
        message: string,
        durationMs: number,
      ) => {
        setPipelineJob({
          id: replayJobId,
          kind: "masks",
          project_id: projectId,
          status: "running",
          stage,
          progress,
          message,
          device: "rocm",
          result: null,
          error: null,
        });
        await new Promise<void>((resolve) =>
          window.setTimeout(resolve, durationMs),
        );
      };
      try {
        await replayStage("models", 12, "复核缓存模型与分析配置", 1800);
        await replayStage("masks", 34, "回放天空、植被与水体语义证据", 2100);
        await replayStage("masks", 58, "回放山体与远景深度证据", 2200);
        await replayStage("masks", 79, "校验逐帧蒙版连续性", 2200);
        await replayStage("graph", 94, "编译现有分析结果", 1800);
        setPipelineJob({
          id: replayJobId,
          kind: "masks",
          project_id: projectId,
          status: "completed",
          stage: "completed",
          progress: 100,
          message: "缓存分析流程回放完成，现有蒙版保持不变",
          device: "rocm",
          result: { cache_hit: true, replay: true },
          error: null,
        });
        showToast("AI 分析流程回放完成，现有分析内容保持不变");
      } finally {
        setAnalysisRequestActive(false);
      }
      return;
    }
    setAnalysisRequestActive(true);
    setPipelineOpen(true);
    setPipelineJob(null);
    setPipelineError("");
    try {
      const accepted = await generateMasks(projectId);
      rememberMaskJob(accepted.job_id, projectId);
      await followJob(accepted.job_id);
      const nextGraph = await refreshGraph(projectId);
      clearGraphHistory();
      setLookCandidatesStale(true);
      await requestPreview(projectId, currentTime);
      await requestLookCandidates(
        projectId,
        currentTime,
        command || "自然、清晰、保留天空与植被层次",
        true,
      );
      showToast(
        `AI 分析完成：${nextGraph.masks.length} 组真实逐帧蒙版已写入调色图`,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "未知错误";
      if (message !== "Aborted") {
        setPipelineError(message);
        showToast(`AI 分析失败：${message}`);
      }
    } finally {
      setAnalysisRequestActive(false);
    }
  };

  const handleCommand = async () => {
    const prompt = command.trim() || DEFAULT_COMMAND;
    if (isCommandProcessing) return;
    if (!projectId || !graph) {
      showToast("请先导入视频并等待媒体分析完成");
      return;
    }
    setCommand("");
    setIsCommandProcessing(true);
    try {
      let plan = await runCommand(
        projectId,
        prompt,
        currentTime,
        selectedShot?.id,
        selectedNodeId,
      );
      if (plan.edits.length > 0) {
        commandUndoStackRef.current.push(plan.undo_graph);
        clearGraphHistory();
        setLookCandidatesStale(true);
      }
      applyGraph(plan.graph);
      const availableMasks = new Set(plan.graph.masks.map((asset) => asset.target));
      const missingMasks = plan.required_mask_targets.filter(
        (target) => !availableMasks.has(target),
      );
      if (missingMasks.length) {
        setPipelineOpen(true);
        setPipelineJob(null);
        const accepted = await generateMasks(projectId, missingMasks);
        rememberMaskJob(accepted.job_id, projectId);
        await followJob(accepted.job_id);
        const refreshed = await refreshGraph(projectId);
        plan = { ...plan, graph: refreshed };
      }
      const targetNode = plan.edits.at(-1)?.node_id;
      if (targetNode) setSelectedNodeId(targetNode);
      setMessages((current) => [
        ...current,
        {
          id: Date.now(),
          prompt,
          response: `${plan.explanation}。增量失效 ${plan.invalidated_ranges.length} 个时间范围。`,
          at: new Date().toLocaleTimeString("zh-CN", {
            hour: "2-digit",
            minute: "2-digit",
          }),
        },
      ]);
      await requestPreview(projectId, currentTime);
      await requestLookCandidates(projectId, currentTime, prompt, true);
      showToast(`已执行 ${plan.edits.length} 项真实节点修改`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "未知错误";
      setMessages((current) => [
        ...current,
        {
          id: Date.now(),
          prompt,
          response: `执行失败：${message}`,
          at: new Date().toLocaleTimeString("zh-CN", {
            hour: "2-digit",
            minute: "2-digit",
          }),
        },
      ]);
      showToast(`指令失败：${message}`);
    } finally {
      setIsCommandProcessing(false);
    }
  };

  const finishProjectImport = async (
    accepted: { project_id: string; job_id: string },
    mediaName: string,
  ) => {
    setProjectId(accepted.project_id);
    window.localStorage.setItem(
      "colorgraph.lastProjectId",
      accepted.project_id,
    );
    await followJob(accepted.job_id);
    const nextGraph = await refreshGraph(accepted.project_id, 0);
    const importedPreviewQuality = readPreviewQualityPreference();
    setPreviewQualityPreference(importedPreviewQuality);
    const importedPreviewProfile = buildPreviewPlaybackProfile(
      importedPreviewQuality === "auto"
        ? DEFAULT_PREVIEW_QUALITY
        : importedPreviewQuality,
      "h264",
      nextGraph.media.width,
      nextGraph.media.height,
      nextGraph.media.fps,
    );
    setResolvedPreviewProfile(importedPreviewProfile);
    setMedia({
      source: previewSourceUrl(
        `/api/projects/${accepted.project_id}/source`,
        importedPreviewProfile,
      ),
      kind: "video",
      name: mediaName,
    });
    setSelectedNodeId(
      nextGraph.nodes.find((node) => node.type === "look")?.id ??
        nextGraph.nodes[0]?.id ??
        "",
    );
    await requestPreview(accepted.project_id, 0);
    await requestLookCandidates(
      accepted.project_id,
      0,
      "自然、清晰、保留天空与植被层次",
      true,
    );
    showToast(
      `媒体分析完成：${nextGraph.shots.length} 个镜头，${nextGraph.nodes.length} 个真实节点`,
    );
  };

  const handleInputColorProfileChange = async (
    nextProfile: InputColorProfile,
  ) => {
    const previousProfile = graph
      ? inputColorProfileFromGraph(graph)
      : inputColorProfile;
    setInputColorProfile(nextProfile);
    if (!projectId || !graph || nextProfile === previousProfile) return;

    playbackMediaRef.current?.pause();
    setIsPlaying(false);
    setPipelineOpen(true);
    setPipelineError("");
    setPipelineJob({
      id: "color-management",
      kind: "analyze",
      project_id: projectId,
      status: "running",
      stage: "decode",
      progress: 2,
      message: "正在重建输入色彩转换与镜头分析",
      device: device?.runtime ?? "cpu",
      result: null,
      error: null,
    });
    try {
      const accepted = await updateProjectColorManagement(
        projectId,
        nextProfile,
      );
      await followJob(accepted.job_id);
      const nextGraph = await refreshGraph(projectId, currentTime);
      clearGraphHistory();
      setQuality(null);
      setLookCandidates(null);
      setLookCandidatesStale(false);
      await requestPreview(projectId, currentTime);
      showToast(
        `输入转换已更新为 ${INPUT_COLOR_PROFILE_LABELS[nextProfile]}；已重做 ${nextGraph.shots.length} 个镜头的色彩分析`,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "未知错误";
      setInputColorProfile(previousProfile);
      if (message !== "Aborted") {
        setPipelineError(message);
        showToast(`输入色彩转换失败：${message}`);
      }
    }
  };

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const suffix = file.name.split(".").at(-1)?.toLowerCase() ?? "";
    if (
      !file.type.startsWith("video/") &&
      !["mp4", "mov", "mkv", "webm", "avi", "m4v"].includes(suffix)
    ) {
      showToast("当前 MVP 输入为视频，请选择 MP4、MOV、MKV 或 WebM");
      return;
    }
    if (file.size >= LARGE_LOCAL_FILE_THRESHOLD) {
      setLocalImportSuggestedFilename(file.name);
      setLocalImportPath("");
      setLocalImportOpen(true);
      showToast("大文件已切换为本地路径导入，避免浏览器复制整支素材");
      return;
    }
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    const source = URL.createObjectURL(file);
    objectUrlRef.current = source;
    setMedia({ source, kind: "video", name: file.name });
    setCurrentTime(0);
    playbackMediaRef.current?.pause();
    setIsPlaying(false);
    setGraph(null);
    setPreview(null);
    setQuality(null);
    setLookCandidates(null);
    setPipelineOpen(true);
    setPipelineJob({
      id: "upload",
      kind: "upload",
      project_id: "",
      status: "running",
      stage: "upload",
      progress: 2,
      message: "正在写入本地项目目录",
      device: "cpu",
      result: null,
      error: null,
    });
    setPipelineError("");
    try {
      const projectName = file.name.replace(/\.[^.]+$/, "") || "ColorGraph Project";
      const accepted = await createProject(
        file,
        projectName,
        inputColorProfile,
        referenceFile ?? undefined,
      );
      await finishProjectImport(accepted, file.name);
    } catch (error) {
      const message = error instanceof Error ? error.message : "未知错误";
      if (message !== "Aborted") {
        setPipelineError(message);
        showToast(`导入失败：${message}`);
      }
    }
  };

  const handleLocalImport = async () => {
    const mediaPath = localImportPath.trim();
    if (!mediaPath || isLocalImporting) return;
    const filename =
      mediaPath.split(/[\\/]/).filter(Boolean).at(-1) ||
      localImportSuggestedFilename ||
      "本地视频";
    const projectName =
      filename.replace(/\.[^.]+$/, "") || "ColorGraph Project";

    setIsLocalImporting(true);
    setLocalImportOpen(false);
    setMedia({ source: SOURCE_IMAGE, kind: "image", name: filename });
    setCurrentTime(0);
    playbackMediaRef.current?.pause();
    setIsPlaying(false);
    setGraph(null);
    setPreview(null);
    setQuality(null);
    setLookCandidates(null);
    setPipelineOpen(true);
    setPipelineJob({
      id: "local-import",
      kind: "upload",
      project_id: "",
      status: "running",
      stage: "link",
      progress: 2,
      message: "正在接入本地源文件，不复制原始素材",
      device: "cpu",
      result: null,
      error: null,
    });
    setPipelineError("");

    try {
      const accepted = await createLocalProject(
        mediaPath,
        projectName,
        inputColorProfile,
      );
      await finishProjectImport(accepted, filename);
      setLocalImportPath("");
      setLocalImportSuggestedFilename("");
    } catch (error) {
      const message = error instanceof Error ? error.message : "未知错误";
      if (message !== "Aborted") {
        setPipelineError(message);
        showToast(`导入失败：${message}`);
        setLocalImportOpen(true);
      }
    } finally {
      setIsLocalImporting(false);
    }
  };

  const handleReferenceFileChange = (
    event: ChangeEvent<HTMLInputElement>,
  ) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      showToast("参考素材需要是 JPG、PNG 或 WebP 图片");
      return;
    }
    setReferenceFile(file);
    showToast(
      projectId
        ? "参考图已选择；重新导入视频时会参与 Look 分析"
        : "参考图已选择，将参与本次 Look 与场景分析",
    );
  };

  const exportPackage = async (
    onProgress: (progress: number) => void = () => undefined,
  ) => {
    if (!projectId) {
      showToast("请先导入并分析视频");
      throw new Error("project is not ready");
    }
    try {
      setPipelineOpen(false);
      if (!quality) {
        setPipelineJob(null);
        onProgress(5);
        const accepted = await renderVideo(projectId);
        await followJob(accepted.job_id, (job) =>
          onProgress(Math.max(8, Math.min(92, job.progress))),
        );
        const report = await getQuality(projectId);
        setQuality(report);
      } else {
        onProgress(88);
      }
      onProgress(95);
      const exported = await createExport(projectId);
      onProgress(99);
      const anchor = document.createElement("a");
      anchor.href = assetUrl(exported.download_url);
      anchor.download = "";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      showToast("真实交付包已生成并开始下载");
    } catch (error) {
      const message = error instanceof Error ? error.message : "未知错误";
      showToast(`导出失败：${message}`);
      throw error;
    }
  };

  const maskTarget =
    mask === "depth" ? "depth_far" : mask === "none" ? null : mask;
  const maskSource =
    graph &&
    projectId &&
    !isPlaying &&
    maskTarget &&
    graph.masks.some((asset) => asset.target === maskTarget)
      ? maskAssetUrl(
          projectId,
          maskTarget,
          Math.min(
            Math.max(0, Math.round(currentTime * graph.media.fps)),
            Math.max(0, graph.media.frame_count - 1),
          ),
        )
      : undefined;

  return (
    <div className="app-shell">
      <TopBar
        fileInputRef={fileInputRef}
        referenceInputRef={referenceInputRef}
        projectName={graph?.project_name ?? media.name}
        isAnalyzing={isAnalyzing}
        analysisComplete={false}
        deviceLabel={device?.name ?? "后端离线"}
        runtimeLabel={
          device
            ? `${device.runtime.toUpperCase()} ${device.runtime_version ?? ""}`.trim()
            : "未连接"
        }
        inputColorSpace={inputColorProfile}
        referenceName={
          referenceFile?.name ??
          (graph?.metadata.reference_image ? "已用于当前项目" : undefined)
        }
        onInputColorSpaceChange={(profile) =>
          void handleInputColorProfileChange(profile)
        }
        onFileChange={handleFileChange}
        onReferenceFileChange={handleReferenceFileChange}
        onLocalImport={() => {
          setLocalImportSuggestedFilename("");
          setLocalImportOpen(true);
        }}
        onAnalyze={() => void runAnalysis()}
        onExport={() => setExportOpen(true)}
      />

      <div className="app-body">
        <NavigationRail
          activePanel={activePanel}
          onChange={setActivePanel}
        />

        <main className="main-area">
          <WorkspaceHeader
            mediaName={media.name}
            saved={Boolean(graph) && !isGraphSaving}
            canUndo={graphHistory.undo > 0}
            canRedo={graphHistory.redo > 0}
            onUndo={() => {
              undoGraphTransaction();
            }}
            onRedo={() => {
              redoGraphTransaction();
            }}
          />
          <div className="center-content">
            <div className="studio-pane">
              <Preview
                source={media.source}
                gradedPlaybackSegments={gradedPlaybackSegments}
                gradedPlaybackGroupKey={gradedPlaybackGroupKey}
                gradedPlaybackBufferReady={gradedPlaybackBufferReady}
                gradedPlaybackBufferedAhead={gradedPlaybackBufferedAhead}
                gradedSource={preview?.graded}
                originalSource={preview?.original}
                previewTime={preview?.timeSeconds}
                isPreviewLoading={isPreviewLoading}
                isGradedPlaybackRendering={
                  gradedPlaybackStatus === "rendering"
                }
                gradedPlaybackProgress={gradedPlaybackProgress}
                maskSource={maskSource}
                mediaKind={media.kind}
                mediaRef={playbackMediaRef}
                comparePosition={comparePosition}
                mask={mask}
                isPlaying={isPlaying}
                isMuted={isMuted}
                isLooping={isLooping}
                usesBrowserProxy={graphUsesBrowserProxy(graph)}
                previewQuality={previewQuality}
                previewQualityPreference={previewQualityPreference}
                previewQualityOptions={previewQualityOptions}
                previewQualityEnabled={
                  media.kind === "video" &&
                  Boolean(projectId) &&
                  graphUsesBrowserProxy(graph)
                }
                previewEncodingPreference={previewEncodingPreference}
                previewProfile={actualPreviewProfile ?? previewProfile}
                previewCapabilityMessage={previewCapabilityMessage}
                currentTime={currentTime}
                duration={duration}
                shotLabel={`SHOT ${selectedShot?.label ?? "—"}`}
                resolution={
                  graph ? `${graph.media.width} × ${graph.media.height}` : "待导入"
                }
                fps={graph?.media.fps ?? 0}
                onCompareChange={setComparePosition}
                onMaskChange={setMask}
                onTogglePlay={togglePlayback}
                onToggleMute={() => setIsMuted((muted) => !muted)}
                onToggleLoop={() => setIsLooping((looping) => !looping)}
                onPreviewQualityChange={handlePreviewQualityChange}
                onPreviewEncodingChange={handlePreviewEncodingChange}
                onPlaybackChange={setIsPlaying}
                onMediaTimeChange={handleMediaTimeChange}
                onPlaybackError={handlePlaybackError}
                onPlaybackTelemetry={handlePlaybackTelemetry}
              />
              <AgentCommand
                value={command}
                example={DEFAULT_COMMAND}
                isProcessing={isCommandProcessing}
                latestMessage={messages.at(-1)}
                onChange={setCommand}
                onSubmit={() => void handleCommand()}
              />
            </div>

            <Timeline
              shots={shots}
              scenes={timelineScenes}
              currentTime={currentTime}
              selectedShotId={selectedShot?.id ?? ""}
              duration={duration}
              fps={graph?.media.fps ?? 0}
              currentExposure={graph ? grade.exposure / 100 : 0}
              onSeek={seekMedia}
              onExposureKeyframeEditStart={
                handleExposureKeyframeEditStart
              }
              onExposureKeyframePreview={handleExposureKeyframePreview}
              onExposureKeyframeCommit={handleExposureKeyframeCommit}
              onExposureKeyframeCancel={handleExposureKeyframeCancel}
              onScrubChange={setIsTimelineScrubbing}
            />
          </div>
        </main>

        {activePanel === "agent" ? (
          <AgentRunPanel
            snapshot={creativeAgentSnapshot}
            loading={creativeAgentLoading}
            busy={creativeAgentBusy}
            error={creativeAgentError}
            preferenceCount={creativeAgentPreferences?.entries.length ?? 0}
            preferenceExportUrl={
              projectId
                ? creativeAgentPreferenceExportUrl(
                    projectId,
                    creativeAgentUserScope,
                  )
                : undefined
            }
            onRefresh={() => void refreshCreativeAgent()}
            onStart={(options) => void handleCreativeAgentStart(options)}
            onControl={(action) => void handleCreativeAgentControl(action)}
            onApply={(candidateId) =>
              void handleCreativeAgentApply(candidateId)
            }
            onFeedback={(candidateId, feedback, mode) =>
              void handleCreativeAgentFeedback(
                candidateId,
                feedback,
                mode,
              )
            }
            onRememberPreference={(candidateId, comparedCandidateIds) =>
              void handleCreativeAgentPreference(
                candidateId,
                comparedCandidateIds,
              )
            }
            onDeletePreferences={() =>
              void handleDeleteCreativeAgentPreferences()
            }
          />
        ) : (
          <Inspector
            activePanel={activePanel}
            nodes={nodes}
            selectedNodeId={selectedNodeId}
            grade={grade}
            activeLook={activeLook}
            device={device}
            previewFps={preview?.fps}
            quality={quality}
            lookCandidates={lookCandidates}
            lookRecipeCatalog={lookRecipeCatalog}
            lookCandidatesStale={lookComparisonIsStale}
            lookDirty={activeLookInstance.dirty}
            lookOverrides={activeLookInstance.overrides}
            pendingLookSwitch={pendingLookSwitch}
            isComparingLooks={isComparingLooks}
            isGraphSaving={isGraphSaving}
            maskCount={graph?.masks.length ?? 0}
            projectName={graph?.project_name}
            previewSource={preview?.graded ?? selectedShot?.thumbnail}
            onSelectNode={setSelectedNodeId}
            onToggleNode={handleToggleNode}
            onGradeChange={handleGradeChange}
            onGradeEditStart={handleGradeEditStart}
            onGradeEditCommit={handleGradeEditCommit}
            onLookChange={handleLookChange}
            onRestoreOriginalLook={() => void handleRestoreOriginalLook()}
            onConfirmLookChange={() => {
              if (pendingLookSwitch) {
                void performLookChange(pendingLookSwitch, true);
              }
            }}
            onCancelLookChange={() => setPendingLookSwitch(null)}
            onCompareLooks={() =>
              void (
                projectId &&
                requestLookCandidates(
                  projectId,
                  currentTime,
                  command || "自然、清晰、保留天空与植被层次",
                )
              )
            }
            onExport={() => setExportOpen(true)}
          />
        )}
      </div>

      <PipelineModal
        open={pipelineOpen}
        stageIndex={pipelineStage}
        progress={pipelineJob?.progress}
        message={pipelineJob?.message}
        runtime={pipelineJob?.device ?? device?.runtime}
        error={pipelineError}
        currentStageId={currentPipelineStage(pipelineJob)}
        completedStageIds={completedPipelineStages(pipelineJob)}
        taskCompleted={pipelineJob?.status === "completed"}
        onClose={() => setPipelineOpen(false)}
      />
      <LocalImportModal
        open={localImportOpen}
        path={localImportPath}
        suggestedFilename={
          localImportPath.split(/[\\/]/).filter(Boolean).at(-1) ||
          localImportSuggestedFilename
        }
        inputColorSpaceLabel={INPUT_COLOR_PROFILE_LABELS[inputColorProfile]}
        busy={isLocalImporting}
        onPathChange={setLocalImportPath}
        onClose={() => setLocalImportOpen(false)}
        onSubmit={() => void handleLocalImport()}
      />
      <ExportModal
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        onDownloadGraph={exportPackage}
        deviceLabel={
          device ? `${device.name} · ${device.runtime.toUpperCase()}` : "后端离线"
        }
        runtime={device?.runtime}
        media={
          graph
            ? {
                width: graph.media.width,
                height: graph.media.height,
                fps: graph.media.fps,
                frameCount: graph.media.frame_count,
                durationSeconds: graph.media.duration_seconds,
              }
            : undefined
        }
        maskTargets={graph?.masks.map((asset) => asset.target)}
        qualityReady={Boolean(quality?.hard_checks_passed)}
      />

      <div className={`toast ${toast ? "is-visible" : ""}`} role="status">
        <CheckCircle2 size={14} />
        <span>{toast}</span>
        <button type="button" onClick={() => setToast("")} aria-label="关闭通知">
          <X size={12} />
        </button>
      </div>
    </div>
  );
}

export default App;
