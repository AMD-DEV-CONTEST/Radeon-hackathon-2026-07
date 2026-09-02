export type MediaKind = "image" | "video";

export type PreviewQuality = "540p" | "1080p" | "1440p" | "2160p";

export type PreviewQualityPreference = "auto" | PreviewQuality;

export type PreviewCodec = "h264" | "hevc";

export type PreviewEncodingPreference = "auto" | "hevc-main10" | "h264";

export interface PreviewPlaybackProfile {
  quality: PreviewQuality;
  codec: PreviewCodec;
  codec_profile: "high" | "main10";
  bit_depth: 8 | 10;
  pixel_format: "yuv420p" | "yuv420p10le";
  width: number;
  height: number;
  fps: number;
  color_range: "limited";
  color_primaries: "bt709";
  color_transfer: "bt709";
  color_matrix: "bt709";
  mov_tag: "avc1" | "hvc1";
}

export interface PreviewPlaybackSegment {
  cache_key: string;
  group_key: string;
  url: string;
  start_seconds: number;
  end_seconds: number;
  profile: PreviewPlaybackProfile;
}

export interface PreviewPlaybackTelemetry {
  session_id: string;
  cache_key: string;
  profile: PreviewPlaybackProfile;
  first_frame_wait_ms: number | null;
  total_video_frames: number;
  dropped_video_frames: number;
  sync_error_ms: number;
  buffering_events: number;
  master_ready_state: number;
  graded_ready_state: number;
  playing: boolean;
}

export type MaskKind = "none" | "sky" | "vegetation" | "water" | "depth";

export type LookId = "natural" | "cool" | "warm" | "foggy";

export type PanelId = "grade" | "agent" | "graph" | "quality" | "assets";

export type GradeParameter =
  | "exposure"
  | "temperature"
  | "contrast"
  | "saturation"
  | "highlights"
  | "strength";

export interface GradeState {
  exposure: number;
  temperature: number;
  contrast: number;
  saturation: number;
  highlights: number;
  strength: number;
}

export interface GradeNode {
  id: string;
  name: string;
  subtitle: string;
  scope: string;
  kind: "input" | "balance" | "tone" | "mask" | "look" | "output";
  enabled: boolean;
  gpu?: boolean;
  recipeLook?: boolean;
  parameter?: GradeParameter;
}

export interface Shot {
  id: string;
  sceneId?: string;
  label: string;
  duration: number;
  start: number;
  position: string;
  thumbnail?: string;
  exposureKeyframes?: Array<{
    time: number;
    value: number;
    nodeId: string;
    keyframeIndex: number;
  }>;
}

export interface TimelineScene {
  id: string;
  label: string;
  start: number;
  duration: number;
  look: string;
}

export interface AgentMessage {
  id: number;
  prompt: string;
  response: string;
  at: string;
}

export interface PipelineStage {
  id: string;
  label: string;
  detail: string;
  device: string;
}
