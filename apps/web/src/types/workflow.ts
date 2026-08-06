import type { Node, Edge } from '@xyflow/react';

// 节点类型
// Qualia Studio 三链节点 + legacy + robot recording
export type NodeType =
  // --- Qualia Studio: Data Sources ---
  | 'hf_dataset'              // HuggingFace / LeRobot dataset
  | 'ego_dataset'             // First-person / human demo video
  // --- Qualia Studio: Transforms ---
  | 'camera_noise'            // Camera & Noise augmentation (lighting, noise, blur, occlusion)
  | 'trajectory_noise'        // Trajectory noise augmentation
  | 'depth_estimator'         // Depth estimation from monocular video (API pending)
  | 'pose_action_extractor'   // Pose & action extraction (API pending)
  // --- Qualia Studio: Generative ---
  | 'world_model_generator'   // World model generation (API pending)
  | 'urdf_inpaint'            // URDF-based inpainting (API pending)
  | 'idm_inverse_dynamics'    // Inverse dynamics model (API pending)
  // --- Qualia Studio: Outputs ---
  | 'output_dataset'          // Output / augmented dataset
  | 'merge_datasets'          // Merge multiple output datasets
  // --- Qualia Studio: Foundation Models ---
  | 'qualia_finetune'         // Submit Qualia VLA finetune (ACT, Pi0, SmolVLA, etc.)
  | 'reward_model_tuning'     // SARM reward model training
  | 'job_monitor'             // Poll Qualia job status
  // --- Legacy Finetune chain (kept for backward compat) ---
  | 'dataset_load'
  | 'camera_map'
  | 'finetune_job'
  | 'evaluate'
  | 'publish_skill'
  // --- Skill ---
  | 'skill_invoke'
  // --- Robot Recording ---
  | 'record_dataset_start'
  | 'recording_monitor'
  | 'dataset_check'
  | 'reachy_daemon_check'
  | 'reachy_record_move'
  | 'reachy_move_output'
  // --- Simulation Pretraining (Isaac Sim / IsaacLab) ---
  | 'isaac_sim_pretrain'      // Pretrain a policy in Isaac Sim before real-data finetune
  | 'lekiwi_handshake_collect' // Mobile manipulation scenario: LeKiwi handshake data collection
  // --- Legacy Demo ---
  | 'robot_connect'
  | 'video_input'
  | 'record'
  | 'train'
  | 'deploy'
  | 'visualize'
  | 'camera_denoise'
  | 'trajectory_optimize';

// 节点状态
export type NodeStatus = 'idle' | 'running' | 'success' | 'error' | 'api_pending';

// 端口类型
export type PortDataType =
  | 'robot'
  | 'video'
  | 'dataset'
  | 'ego_video'
  | 'processed_dataset'
  | 'merged_dataset'
  | 'camera_mapping'
  | 'job'
  | 'model'
  | 'reward_model'
  | 'config'
  | 'metrics'
  | 'skill_manifest'
  | 'recording'
  | 'trajectory'
  | 'daemon_status'
  | 'any';

// 端口定义
export interface PortDef {
  id: string;
  name: string;
  type: PortDataType;
  required: boolean;
  description?: string;
}

// ---------- Finetune 主链配置类型 ----------

export interface DatasetLoadConfig {
  datasetId: string;              // e.g. "lerobot/pusht"
  datasetType?: 'lerobot_v3' | 'sarm_progress';
  // 可选：预先填入的 image keys（也可由 camera_map 节点推断）
  imageKeys?: string[];
}

export interface CameraMapEntry {
  slot: string;                   // e.g. "cam_1"
  imageKey: string;               // e.g. "observation.images.top"
}

export interface CameraMapConfig {
  mappings: CameraMapEntry[];
}

export type VlaType =
  | 'act'
  | 'smolvla'
  | 'pi0'
  | 'pi05'
  | 'gr00t_n1_5'
  | 'gr00t_n1_6'
  | 'sarm'
  | 'wall_oss'
  | 'xvla';

export interface FinetuneJobConfig {
  projectId?: string;             // uuid
  vlaType: VlaType;
  hours: number;                  // (0, 168]
  batchSize?: number;             // [1, 512]
  instanceType?: string;          // e.g. A100, H100
  region?: string;
  jobName?: string;
  jobType?: 'vla' | 'reward' | 'vla_w_reward';
  useRabc?: boolean;
}

export interface JobMonitorConfig {
  pollIntervalSec?: number;       // 默认 5s
  timeoutMin?: number;            // 默认 60min
}

// Phase 5: 将已安装 Skill 作为 Workflow 节点复用执行入口
export interface SkillInvokeConfig {
  skillId: string;                // 必填；对应 /api/v1/skills 返回的 skill_id
  runtimeId: string;              // 必填；目标 runtime
  params?: Record<string, unknown>; // 覆盖安装时保存的 params
}

// 节点数据 - 添加索引签名以满足 React Flow 的类型约束
export interface WorkflowNodeData {
  label: string;
  type: NodeType;
  description: string;
  icon: string;
  color: string;           // 主题色
  status: NodeStatus;
  progress?: number;       // 0-100
  logs?: string[];
  // 各节点的具体 config 结构由 type 决定；运行时做 narrowing
  config: Record<string, any>;
  inputs: PortDef[];
  outputs: PortDef[];
  // 运行前/运行中产生的校验问题，供节点UI与控制台展示
  validationErrors?: string[];
  // 索引签名
  [key: string]: unknown;
}

// 工作流定义
export interface Workflow {
  id: string;
  name: string;
  description: string;
  nodes: Node<WorkflowNodeData>[];
  edges: Edge[];
  createdAt: string;
  updatedAt: string;
}

// 执行上下文
export interface ExecutionContext {
  workflowId: string;
  nodeResults: Map<string, any>;  // 节点执行结果
  globalState: Record<string, any>;
}

// 节点分类（用于左侧面板分组）
export type NodeCategory =
  | 'qualia_data'        // Qualia Studio: DATA SOURCES
  | 'qualia_transforms'  // Qualia Studio: TRANSFORMS
  | 'qualia_generative'  // Qualia Studio: GENERATIVE
  | 'qualia_outputs'     // Qualia Studio: OUTPUTS
  | 'qualia_models'      // Qualia Studio: FOUNDATION MODELS
  | 'input'              // legacy data sources
  | 'process'            // legacy preprocessing
  | 'training'           // legacy training
  | 'monitor'            // legacy monitor
  | 'skill_factory'      // Skill factory (evaluate / publish)
  | 'robot_recording'    // Real robot recording
  | 'skill_run'          // Run installed Skill
  | 'deployment'         // Deploy (legacy)
  | 'output'             // Visualize / output (legacy)
  | 'simulation'         // Simulation pretraining (Isaac Sim)
  | 'scenarios';         // Application scenario templates (LeKiwi handshake, etc.)

// 节点模板 (用于左侧面板)
export interface NodeTemplate {
  type: NodeType;
  label: string;
  description: string;
  icon: string;
  color: string;
  category: NodeCategory;
  defaultConfig: Record<string, any>;
  inputs: PortDef[];
  outputs: PortDef[];
  // 是否属于 Finetune 主链核心节点（参与运行前检查）
  finetuneCore?: boolean;
  /** Minimum subscription tier to add this node from the palette */
  minTier?: 'free' | 'pro' | 'creator';
}

// 预设工作流模板
export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  icon: string;
  nodes: Node<WorkflowNodeData>[];
  edges: Edge[];
}

// 执行日志
export interface ExecutionLog {
  timestamp: string;
  nodeId: string;
  nodeType: NodeType;
  level: 'info' | 'warn' | 'error' | 'success';
  message: string;
}

// ---------- 校验相关 ----------
export interface NodeValidationResult {
  nodeId: string;
  errors: string[];
}

export interface WorkflowValidationResult {
  ok: boolean;
  errors: string[];               // workflow 级错误（结构性）
  nodeErrors: NodeValidationResult[];
}
