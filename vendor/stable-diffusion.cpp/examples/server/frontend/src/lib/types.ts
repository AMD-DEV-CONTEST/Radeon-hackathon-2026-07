import type { CACHE_MODES } from "./form-defaults";

// ---------------------------------------------------------------------------
// Image helpers
// ---------------------------------------------------------------------------

export interface ImageEntry {
  name: string;
  type: string;
  dataUrl: string;
}

export type ImageTarget =
  | "init_image"
  | "mask_image"
  | "control_image"
  | "end_image"
  | "ref_images"
  | "control_frames";

export type GenerationMode = "image" | "video";

export interface ImageInputConfig {
  target: ImageTarget;
  label: string;
  description: string;
  layout: "grid" | "full";
}

// ---------------------------------------------------------------------------
// Form model
// ---------------------------------------------------------------------------

export interface GuidanceParams {
  txt_cfg: number;
  img_cfg: string | number;
  distilled_guidance: number;
  slg_layers: string;
  layer_start: number;
  layer_end: number;
  scale: number;
}

export interface SampleParams {
  scheduler: string;
  sample_method: string;
  sample_steps: number;
  eta: string | number;
  shifted_timestep: number;
  flow_shift: string | number;
  guidance: GuidanceParams;
}

export interface VaeTilingParams {
  enabled: boolean;
  tile_size_x: number;
  tile_size_y: number;
  target_overlap: number;
  rel_size_x: number;
  rel_size_y: number;
}

export interface CacheParams {
  mode: string;
  option: string;
  scm_mask: string;
  scm_policy_dynamic: boolean;
}

export interface FormLoraEntry {
  path: string;
  multiplier: number;
  is_high_noise: boolean;
}

export interface GenerationForm {
  prompt: string;
  negative_prompt: string;
  width: number;
  height: number;
  batch_count: number;
  video_frames: number;
  fps: number;
  seed: number;
  clip_skip: number;
  strength: number;
  control_strength: number;
  moe_boundary: number;
  vace_strength: number;
  output_format: string;
  output_compression: number;
  sample_params: SampleParams;
  high_noise_sample_params: SampleParams;
  init_image: ImageEntry | null;
  end_image: ImageEntry | null;
  ref_images: ImageEntry[];
  control_frames: ImageEntry[];
  mask_image: ImageEntry | null;
  control_image: ImageEntry | null;
  lora: FormLoraEntry[];
  vae_tiling_params: VaeTilingParams;
  cache: CacheParams;
}

// ---------------------------------------------------------------------------
// LoRA
// ---------------------------------------------------------------------------

export interface AvailableLora {
  name: string;
  path: string;
}

// ---------------------------------------------------------------------------
// Capabilities (API response)
// ---------------------------------------------------------------------------

export interface Capabilities {
  model?: {
    stem?: string;
    name?: string;
  };
  current_mode?: "img_gen" | "vid_gen";
  supported_modes?: Array<"img_gen" | "vid_gen">;
  output_formats?: string[];
  output_formats_by_mode?: Partial<Record<"img_gen" | "vid_gen", string[]>>;
  samplers?: string[];
  schedulers?: string[];
  loras?: AvailableLora[];
  limits?: {
    max_queue_size?: number;
  };
  features?: {
    cancel_queued?: boolean;
    cancel_generating?: boolean;
  };
  features_by_mode?: Partial<Record<"img_gen" | "vid_gen", Record<string, any>>>;
  defaults?: Record<string, any>;
  defaults_by_mode?: Partial<Record<"img_gen" | "vid_gen", Record<string, any>>>;
}

// ---------------------------------------------------------------------------
// Job (API response)
// ---------------------------------------------------------------------------

export interface ImageOutput {
  index: number;
  b64_json: string;
}

export type JobKind = "img_gen" | "vid_gen";

export interface JobResult {
  images?: ImageOutput[];
  output_format?: string;
  b64_json?: string;
  mime_type?: string;
  fps?: number;
  frame_count?: number;
}

export interface Job {
  id: string;
  kind?: JobKind;
  status: string;
  queue_position?: number;
  created?: number;
  started?: number;
  completed?: number;
  result?: JobResult | null;
  error?: {
    code?: string;
    message?: string;
  } | null;
}

// ---------------------------------------------------------------------------
// Cache mode literal union
// ---------------------------------------------------------------------------

export type CacheMode = (typeof CACHE_MODES)[number];
