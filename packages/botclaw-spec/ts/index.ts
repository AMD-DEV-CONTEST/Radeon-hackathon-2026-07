/**
 * BotClaw contract spec — TypeScript types (v0.1)
 *
 * Source of truth lives in `../schemas/*.schema.json`. This file is manually
 * kept in sync; any change MUST be reflected in the Python Pydantic models
 * (`../python/botclaw_spec/__init__.py`) and JSON Schemas at the same time.
 */

export const BOTCLAW_SPEC_VERSION = '0.4.0';

// ---------- JointUpdate (realtime frame) ----------

export type JointName = '1' | '2' | '3' | '4' | '5' | '6';

export type JointMap = Record<JointName, number>;

export interface JointUpdateMeta {
  fps?: number;
  source?: string;
  [extra: string]: unknown;
}

export interface JointUpdate {
  type: 'joint_update';
  robot_id: string;
  timestamp: number;
  joints: JointMap;
  servo_values?: Partial<Record<JointName, number>>;
  meta?: JointUpdateMeta;
  /** v0.4 optional telemetry */
  temperatures_c?: Partial<Record<JointName, number>>;
  currents_a?: Partial<Record<JointName, number>>;
  voltages_v?: Partial<Record<JointName, number>>;
}

// ---------- RobotState (snapshot, v0.4) ----------

export interface JointLimit {
  lo: number;
  hi: number;
}

export interface RobotSafety {
  estop: boolean;
  clamped?: string[];
  max_delta_rad?: number;
  [extra: string]: unknown;
}

export interface RobotState {
  type: 'robot_state';
  robot_id: string;
  timestamp: number;
  joints?: Partial<Record<JointName, number | null>>;
  servo_values?: Partial<Record<JointName, number | null>>;
  teleop_connected: boolean;
  ui_clients: number;
  is_recording: boolean;
  buffer_size?: number;
  /** v0.4 */
  temperatures_c?: Partial<Record<JointName, number | null>>;
  currents_a?: Partial<Record<JointName, number | null>>;
  voltages_v?: Partial<Record<JointName, number | null>>;
  limits_rad?: Partial<Record<JointName, JointLimit>>;
  safety?: RobotSafety;
  fps_observed?: number;
  [extra: string]: unknown;
}

// ---------- DeviceCapabilities ----------

export type RobotModel = 'so101' | 'so100' | 'reachy_mini' | 'reachy_mini_lite' | 'openclaw' | 'generic';
export type ControlMode = 'leader_follower' | 'keyboard' | 'vr' | 'replay' | 'telemetry' | 'inference';

export interface CameraSource {
  camera_id: string;
  display_name: string;
  device_type?: 'usb' | 'realsense' | 'ip';
  default_device?: string;
  width?: number;
  height?: number;
  fps?: number;
}

export interface DeviceCapabilities {
  robot_id: string;
  robot_model: RobotModel;
  display_name?: string;
  joint_count: number;
  joint_names: string[];
  control_modes: ControlMode[];
  max_fps: number;
  urdf_url?: string;
  has_gripper?: boolean;
  supports_telemetry?: boolean;
  camera_sources?: CameraSource[];
}

// ---------- Skill (BotClaw v0.9 registry entry) ----------

export type SkillParamType = 'string' | 'number' | 'bool' | 'enum';
export type SkillTrainBackend = 'local' | 'qualia' | 'none';
export type SkillCompatibilityLevel = 'A+' | 'A' | 'B' | 'C' | 'D';

export interface SkillParamSchema {
  key: string;
  label: string;
  type: SkillParamType;
  default?: unknown;
  min?: number;
  max?: number;
  options?: Array<string | number | boolean>;
  required?: boolean;
}

export interface SkillCompatibility {
  level?: SkillCompatibilityLevel;
  verified_runtimes?: string[];
  notes?: string;
}

export interface Skill {
  skill_id: string;
  verb: string;
  robot_type: string;
  compatible_types: string[];
  params_schema: SkillParamSchema[];
  params?: Record<string, unknown>;
  joint_count?: number;
  train_backend?: SkillTrainBackend;
  hf_model_id?: string;
  hf_dataset_id?: string;
  min_episodes?: number;
  episode_duration_s?: number;
  description?: string;
  tags?: string[];
  author?: string;
  version?: string;
  created_at?: string;
  compatibility?: SkillCompatibility;
}

// ---------- DatasetEpisode ----------

export interface JointStats {
  min: number;
  max: number;
  mean: number;
  std: number;
  range: number;
  jitter: number;
}

export interface DatasetStats {
  frame_count?: number;
  duration_s?: number;
  fps_nominal?: number | null;
  fps_observed_mean?: number;
  fps_observed_std?: number;
  joints?: Record<string, JointStats>;
  [extra: string]: unknown;
}

export type DatasetQualityFlag =
  | 'low_frame_count'
  | 'too_short'
  | 'fps_unstable'
  | 'no_motion'
  | 'joint_jitter'
  | string;

export interface DatasetEpisode {
  spec_version?: string;
  id: string;
  robot_id: string;
  recorded_at: string;
  duration_sec?: number;
  frame_count: number;
  fps: number;
  fps_nominal?: number;
  source?: string;
  artifacts: {
    json?: string;
    parquet?: string;
    video?: string;
  };
  tags?: string[];
  /** v0.2: integer 0-100 (previously 0..1 float placeholder). */
  quality_score?: number;
  flags?: DatasetQualityFlag[];
  stats?: DatasetStats;
}

// ---------- TrainingJob ----------

export type TrainingJobStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

export interface TrainingJob {
  id: string;
  status: TrainingJobStatus;
  algorithm: string;
  dataset_ids: string[];
  hyperparameters?: Record<string, unknown>;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  metrics?: Record<string, number>;
  artifact_url?: string;
  error_message?: string;
  progress?: number;
}

// ---------- Model (v0.3) ----------

export type PredictionMode = 'delta' | 'absolute';

export interface ModelArtifact {
  model_key: string;
  name?: string;
  algo: string;
  dataset_id?: string;
  checkpoint?: string;
  input_dim?: number;
  output_dim?: number;
  prediction_mode?: PredictionMode;
  hparams?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
}

// ---------- CompareFrame (v0.3) ----------

export interface CompareFrame {
  type: 'compare_frame';
  frame_index: number;
  gt: JointMap;
  pred: JointMap;
  error: JointMap;
  step_rmse: number;
  latency_ms?: number;
}

// ---------- Union helpers ----------

export type RealtimeMessage = JointUpdate | CompareFrame | RobotState;

export const JOINT_NAMES: JointName[] = ['1', '2', '3', '4', '5', '6'];

export function isJointUpdate(msg: unknown): msg is JointUpdate {
  if (!msg || typeof msg !== 'object') return false;
  const m = msg as Record<string, unknown>;
  if (m.type !== 'joint_update') return false;
  if (typeof m.robot_id !== 'string') return false;
  if (typeof m.timestamp !== 'number') return false;
  const joints = m.joints as Record<string, unknown> | undefined;
  if (!joints || typeof joints !== 'object') return false;
  return JOINT_NAMES.every((k) => typeof joints[k] === 'number');
}
