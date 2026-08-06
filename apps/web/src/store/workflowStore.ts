import { create } from 'zustand';
import type { Node, Edge, NodeChange, EdgeChange } from '@xyflow/react';
import { applyNodeChanges, applyEdgeChanges } from '@xyflow/react';
import type { WorkflowNodeData, NodeTemplate, ExecutionLog, PortDataType } from '../types/workflow';

export interface ConnectingFromState {
  nodeId: string;
  handleId: string;
  handleType: 'source' | 'target';
  portType: PortDataType;
}

interface WorkflowState {
  // 当前工作流
  nodes: Node<WorkflowNodeData>[];
  edges: Edge[];
  selectedNode: string | null;

  // 执行状态
  isRunning: boolean;
  executionLogs: ExecutionLog[];
  activeRunningNodeId: string | null;
  completedNodeIds: string[];
  connectingFrom: ConnectingFromState | null;
  consoleExpanded: boolean;
  consoleFilterNodeId: string | null;

  // Actions
  setNodes: (nodes: Node<WorkflowNodeData>[] | ((prev: Node<WorkflowNodeData>[]) => Node<WorkflowNodeData>[])) => void;
  setEdges: (edges: Edge[] | ((prev: Edge[]) => Edge[])) => void;
  onNodesChange: (changes: NodeChange<Node<WorkflowNodeData>>[]) => void;
  onEdgesChange: (changes: EdgeChange<Edge>[]) => void;
  setSelectedNode: (id: string | null) => void;
  updateNodeData: (id: string, data: Partial<WorkflowNodeData>) => void;
  updateNodeStatus: (id: string, status: WorkflowNodeData['status'], progress?: number) => void;
  addNode: (node: Node<WorkflowNodeData>) => void;
  removeNode: (id: string) => void;
  addEdge: (edge: Edge) => void;
  removeEdge: (id: string) => void;

  // 执行控制
  setIsRunning: (running: boolean) => void;
  addExecutionLog: (log: ExecutionLog) => void;
  clearExecutionLogs: () => void;
  resetExecutionState: () => void;
  setActiveRunningNodeId: (id: string | null) => void;
  markNodeCompleted: (id: string) => void;
  setConnectingFrom: (state: ConnectingFromState | null) => void;
  setConsoleExpanded: (expanded: boolean) => void;
  setConsoleFilterNodeId: (id: string | null) => void;
}

export const useWorkflowStore = create<WorkflowState>((set) => ({
  // 初始状态
  nodes: [],
  edges: [],
  selectedNode: null,
  isRunning: false,
  executionLogs: [],
  activeRunningNodeId: null,
  completedNodeIds: [],
  connectingFrom: null,
  consoleExpanded: false,
  consoleFilterNodeId: null,

  // Node actions
  setNodes: (nodes) => set((state) => ({
    nodes: typeof nodes === 'function' ? nodes(state.nodes) : nodes,
  })),

  setEdges: (edges) => set((state) => ({
    edges: typeof edges === 'function' ? edges(state.edges) : edges,
  })),

  onNodesChange: (changes) => set((state) => ({
    nodes: applyNodeChanges(changes, state.nodes) as Node<WorkflowNodeData>[],
  })),

  onEdgesChange: (changes) => set((state) => ({
    edges: applyEdgeChanges(changes, state.edges),
  })),

  setSelectedNode: (id) => set({ selectedNode: id }),

  updateNodeData: (id, data) => set((state) => ({
    nodes: state.nodes.map((node) =>
      node.id === id
        ? { ...node, data: { ...node.data, ...data } }
        : node
    ),
  })),

  updateNodeStatus: (id, status, progress) => set((state) => ({
    nodes: state.nodes.map((node) =>
      node.id === id
        ? { ...node, data: { ...node.data, status, progress } }
        : node
    ),
  })),

  addNode: (node) => set((state) => ({
    nodes: [...state.nodes, node],
  })),

  removeNode: (id) => set((state) => ({
    nodes: state.nodes.filter((n) => n.id !== id),
    edges: state.edges.filter((e) => e.source !== id && e.target !== id),
    selectedNode: state.selectedNode === id ? null : state.selectedNode,
  })),

  addEdge: (edge) => set((state) => ({
    edges: [...state.edges, edge],
  })),

  removeEdge: (id) => set((state) => ({
    edges: state.edges.filter((e) => e.id !== id),
  })),

  // Execution actions
  setIsRunning: (running) => set({ isRunning: running }),

  addExecutionLog: (log) => set((state) => ({
    executionLogs: [...state.executionLogs, log],
  })),

  clearExecutionLogs: () => set({ executionLogs: [] }),

  resetExecutionState: () => set((state) => ({
    isRunning: false,
    executionLogs: [],
    activeRunningNodeId: null,
    completedNodeIds: [],
    nodes: state.nodes.map((node) => ({
      ...node,
      data: { ...node.data, status: 'idle', progress: undefined, validationErrors: undefined },
    })),
  })),

  setActiveRunningNodeId: (id) => set({ activeRunningNodeId: id }),

  markNodeCompleted: (id) => set((state) => ({
    completedNodeIds: state.completedNodeIds.includes(id)
      ? state.completedNodeIds
      : [...state.completedNodeIds, id],
  })),

  setConnectingFrom: (connectingFrom) => set({ connectingFrom }),

  setConsoleExpanded: (consoleExpanded) => set({ consoleExpanded }),

  setConsoleFilterNodeId: (consoleFilterNodeId) => set({ consoleFilterNodeId }),
}));

// ---------- 节点模板 ----------
export const nodeTemplates: NodeTemplate[] = [
  // ========== QUALIA STUDIO: DATA SOURCES ==========
  {
    type: 'hf_dataset',
    label: 'HF Dataset',
    description: 'Load a HuggingFace / LeRobot dataset',
    icon: '📦',
    color: '#0ea5e9',
    category: 'qualia_data',
    defaultConfig: { datasetId: '', datasetType: 'lerobot_v3', imageKeys: [] },
    inputs: [],
    outputs: [{ id: 'dataset', name: 'Dataset', type: 'dataset', required: true }],
    finetuneCore: true,
  },
  {
    type: 'ego_dataset',
    label: 'Ego Dataset',
    description: 'First-person / human demo video for synthesis',
    icon: '🎥',
    color: '#06b6d4',
    category: 'qualia_data',
    defaultConfig: { source: '', prompt: '' },
    inputs: [],
    outputs: [{ id: 'ego_video', name: 'Ego Video', type: 'ego_video', required: true }],
  },

  // ========== QUALIA STUDIO: TRANSFORMS ==========
  {
    type: 'camera_noise',
    label: 'Camera & Noise',
    description: 'Augment: lighting, noise, blur, occlusion (deterministic)',
    icon: '🔆',
    color: '#eab308',
    category: 'qualia_transforms',
    defaultConfig: {
      transforms: 'lighting,noise',
      mode: 'stacked',
      copies: 3,
      datasetMode: 'copy',
      brightnessMin: -15, brightnessMax: 15,
      contrastMin: -10, contrastMax: 10,
      colorTempMin: 4000, colorTempMax: 6500,
    },
    inputs: [{ id: 'dataset', name: 'Dataset', type: 'dataset', required: true }],
    outputs: [{ id: 'dataset_out', name: 'Augmented Dataset', type: 'processed_dataset', required: true }],
    finetuneCore: true,
  },
  {
    type: 'trajectory_noise',
    label: 'Trajectory Noise',
    description: 'Add noise to joint angles, velocity, timestamps',
    icon: '〰️',
    color: '#f97316',
    category: 'qualia_transforms',
    defaultConfig: { strength: 0.1, jointNoise: true, timestampJitter: false },
    inputs: [{ id: 'dataset', name: 'Dataset', type: 'processed_dataset', required: true }],
    outputs: [{ id: 'dataset_out', name: 'Noisy Dataset', type: 'processed_dataset', required: true }],
    finetuneCore: true,
  },
  {
    type: 'depth_estimator',
    label: 'Depth Estimator',
    description: 'Monocular depth estimation (API pending)',
    icon: '🌊',
    color: '#64748b',
    category: 'qualia_transforms',
    defaultConfig: {},
    inputs: [{ id: 'ego_video', name: 'Video', type: 'ego_video', required: true }],
    outputs: [{ id: 'dataset_out', name: 'Depth Data', type: 'processed_dataset', required: true }],
  },
  {
    type: 'pose_action_extractor',
    label: 'Pose & Action Extractor',
    description: 'Extract robot poses from video (API pending)',
    icon: '🦾',
    color: '#64748b',
    category: 'qualia_transforms',
    defaultConfig: {},
    inputs: [{ id: 'dataset', name: 'Depth Data', type: 'processed_dataset', required: true }],
    outputs: [{ id: 'dataset_out', name: 'Action Dataset', type: 'processed_dataset', required: true }],
  },

  // ========== QUALIA STUDIO: GENERATIVE ==========
  {
    type: 'world_model_generator',
    label: 'World Model Generator',
    description: 'Generate scene videos from text prompts (API pending)',
    icon: '🌍',
    color: '#64748b',
    category: 'qualia_generative',
    defaultConfig: { prompt: '' },
    inputs: [{ id: 'ego_video', name: 'Ego Video', type: 'ego_video', required: true }],
    outputs: [{ id: 'dataset_out', name: 'Generated Video', type: 'ego_video', required: true }],
  },
  {
    type: 'urdf_inpaint',
    label: 'URDF Inpaint',
    description: 'Inpaint occluded robot parts using URDF (API pending)',
    icon: '🩹',
    color: '#64748b',
    category: 'qualia_generative',
    defaultConfig: {},
    inputs: [{ id: 'ego_video', name: 'Ego Video', type: 'ego_video', required: true }],
    outputs: [{ id: 'dataset_out', name: 'Inpainted Video', type: 'ego_video', required: true }],
  },
  {
    type: 'idm_inverse_dynamics',
    label: 'IDM (Inverse Dynamics)',
    description: 'Extract action commands from video (API pending)',
    icon: '⚙️',
    color: '#64748b',
    category: 'qualia_generative',
    defaultConfig: {},
    inputs: [{ id: 'ego_video', name: 'Video', type: 'ego_video', required: true }],
    outputs: [{ id: 'dataset_out', name: 'Action Dataset', type: 'processed_dataset', required: true }],
  },

  // ========== QUALIA STUDIO: OUTPUTS ==========
  {
    type: 'output_dataset',
    label: 'Output Dataset',
    description: 'Export processed data as training-ready dataset',
    icon: '💾',
    color: '#22c55e',
    category: 'qualia_outputs',
    defaultConfig: { outputName: '', datasetMode: 'copy' },
    inputs: [{ id: 'dataset', name: 'Data', type: 'processed_dataset', required: true }],
    outputs: [{ id: 'dataset_out', name: 'Output Dataset', type: 'dataset', required: true }],
    finetuneCore: true,
  },
  {
    type: 'merge_datasets',
    label: 'Merge Datasets',
    description: 'Combine multiple output datasets into one',
    icon: '🔀',
    color: '#14b8a6',
    category: 'qualia_outputs',
    defaultConfig: {},
    inputs: [
      { id: 'dataset_1', name: 'Dataset 1', type: 'dataset', required: true },
      { id: 'dataset_2', name: 'Dataset 2', type: 'dataset', required: false },
      { id: 'dataset_3', name: 'Dataset 3', type: 'dataset', required: false },
    ],
    outputs: [{ id: 'merged', name: 'Merged Dataset', type: 'merged_dataset', required: true }],
    finetuneCore: true,
  },

  // ========== QUALIA STUDIO: FOUNDATION MODELS ==========
  {
    type: 'qualia_finetune',
    label: 'Qualia Finetune',
    description: 'Submit VLA finetune: ACT, Pi0, SmolVLA, Cosmos, GROOT...',
    icon: '🧠',
    color: '#f59e0b',
    category: 'qualia_models',
    defaultConfig: {
      vlaType: 'act',
      hours: 2,
      batchSize: 32,
      instanceType: 'A100',
      region: '',
      jobName: '',
      jobType: 'vla',
      useRabc: false,
      cameraMappings: [{ slot: 'cam_1', imageKey: '' }],
    },
    inputs: [
      { id: 'dataset', name: 'Dataset', type: 'dataset', required: true },
    ],
    outputs: [{ id: 'job', name: 'Job', type: 'job', required: true }],
    finetuneCore: true,
  },
  {
    type: 'reward_model_tuning',
    label: 'Reward Model Tuning',
    description: 'Train SARM reward model for RL',
    icon: '🏆',
    color: '#d946ef',
    category: 'qualia_models',
    defaultConfig: {
      headMode: 'dense',
      instanceType: 'H100',
      hours: 2,
      imageObservationKey: '',
    },
    inputs: [{ id: 'dataset', name: 'Dataset', type: 'dataset', required: true }],
    outputs: [{ id: 'reward_model', name: 'Reward Model', type: 'reward_model', required: true }],
  },
  {
    type: 'job_monitor',
    label: 'Job Monitor',
    description: 'Poll Qualia job: queued → running → completed',
    icon: '📡',
    color: '#10b981',
    category: 'qualia_models',
    defaultConfig: { pollIntervalSec: 5, timeoutMin: 60 },
    inputs: [{ id: 'job', name: 'Job', type: 'job', required: true }],
    outputs: [{ id: 'model', name: 'Model', type: 'model', required: false }],
    finetuneCore: true,
  },

  // ========== LEGACY FINETUNE CHAIN (backward compat) ==========
  {
    type: 'dataset_load',
    label: 'Dataset Load',
    description: 'Load a HuggingFace / LeRobot dataset (legacy)',
    icon: '📦',
    color: '#0ea5e9',
    category: 'input',
    defaultConfig: { datasetId: '', datasetType: 'lerobot_v3', imageKeys: [] },
    inputs: [],
    outputs: [{ id: 'dataset', name: 'Dataset', type: 'dataset', required: true }],
    finetuneCore: true,
  },
  {
    type: 'camera_map',
    label: 'Camera Map',
    description: 'Map model camera slots to dataset image keys',
    icon: '🎥',
    color: '#6366f1',
    category: 'process',
    defaultConfig: { mappings: [{ slot: 'cam_1', imageKey: '' }] },
    inputs: [{ id: 'dataset', name: 'Dataset', type: 'dataset', required: true }],
    outputs: [
      { id: 'mapping', name: 'Camera Mapping', type: 'camera_mapping', required: true },
      { id: 'dataset_out', name: 'Dataset', type: 'dataset', required: false },
    ],
    finetuneCore: true,
  },
  {
    type: 'finetune_job',
    label: 'Finetune Job',
    description: 'Submit a Qualia finetune training job (legacy)',
    icon: '🧠',
    color: '#f59e0b',
    category: 'training',
    defaultConfig: {
      vlaType: 'act', hours: 2, batchSize: 32,
      instanceType: 'A100', region: '', jobName: '', jobType: 'vla', useRabc: false,
    },
    inputs: [
      { id: 'dataset', name: 'Dataset', type: 'dataset', required: true },
      { id: 'mapping', name: 'Camera Mapping', type: 'camera_mapping', required: true },
    ],
    outputs: [{ id: 'job', name: 'Job', type: 'job', required: true }],
    finetuneCore: true,
  },

  // ---------- Skill Factory 延伸 ----------
  {
    type: 'evaluate',
    label: 'Evaluate',
    description: 'Evaluate trained model quality',
    icon: '📊',
    color: '#06b6d4', // cyan-500
    category: 'skill_factory',
    defaultConfig: {
      passThreshold: 0.7,
      metrics: ['success_rate', 'loss'],
    },
    inputs: [
      { id: 'model', name: 'Model / Job', type: 'model', required: true },
    ],
    outputs: [
      { id: 'metrics', name: 'Metrics', type: 'metrics', required: true },
    ],
    finetuneCore: true,
  },
  {
    type: 'publish_skill',
    label: 'Publish Skill',
    description: 'Generate Skill manifest from evaluation',
    icon: '🏷️',
    color: '#8b5cf6', // violet-500
    category: 'skill_factory',
    defaultConfig: {
      skillName: '',
      verb: 'manipulate',
      version: '1.0.0',
      description: '',
      runtimeId: '',
    },
    inputs: [
      { id: 'metrics', name: 'Eval Metrics', type: 'metrics', required: true },
    ],
    outputs: [
      { id: 'skill_manifest', name: 'Skill Manifest', type: 'skill_manifest', required: true },
    ],
    finetuneCore: true,
  },

  // ---------- Real Robot Recording: SO-101 ----------
  {
    type: 'record_dataset_start',
    label: 'Record Dataset Start',
    description: 'Start SO-101 dataset recording (real API)',
    icon: '🎬',
    color: '#ef4444', // red-500
    category: 'robot_recording',
    defaultConfig: {
      leaderPort: '/dev/ttyACM0',
      followerPort: '/dev/ttyACM1',
      taskName: 'pick_place',
      episodes: 1,
      fps: 30,
      cameraIds: '0',
      repoId: '',
    },
    inputs: [],
    outputs: [
      { id: 'recording', name: 'Recording', type: 'recording', required: true },
    ],
  },
  {
    type: 'recording_monitor',
    label: 'Recording Monitor',
    description: 'Monitor SO-101 recording progress (real API)',
    icon: '📡',
    color: '#f97316', // orange-500
    category: 'robot_recording',
    defaultConfig: {
      pollIntervalSec: 3,
      timeoutMin: 30,
    },
    inputs: [
      { id: 'recording', name: 'Recording', type: 'recording', required: true },
    ],
    outputs: [
      { id: 'recording_out', name: 'Recording', type: 'recording', required: true },
    ],
  },
  {
    type: 'dataset_check',
    label: 'Dataset Check',
    description: 'Validate recorded dataset (real API)',
    icon: '✅',
    color: '#22c55e', // green-500
    category: 'robot_recording',
    defaultConfig: {
      repoId: '',
    },
    inputs: [
      { id: 'recording', name: 'Recording', type: 'recording', required: true },
    ],
    outputs: [
      { id: 'dataset', name: 'Dataset', type: 'dataset', required: true },
    ],
  },

  // ---------- Real Robot Recording: Reachy Mini ----------
  {
    type: 'reachy_daemon_check',
    label: 'Reachy Daemon Check',
    description: 'Verify Reachy Mini daemon is online (real API)',
    icon: '🤖',
    color: '#3b82f6', // blue-500
    category: 'robot_recording',
    defaultConfig: {},
    inputs: [],
    outputs: [
      { id: 'daemon', name: 'Daemon', type: 'daemon_status', required: true },
    ],
  },
  {
    type: 'reachy_record_move',
    label: 'Reachy Record Move',
    description: 'Record a Reachy custom move (real API)',
    icon: '🎯',
    color: '#ef4444', // red-500
    category: 'robot_recording',
    defaultConfig: {
      moveName: '',
      durationS: 10,
      sampleHz: 100,
    },
    inputs: [
      { id: 'daemon', name: 'Daemon', type: 'daemon_status', required: true },
    ],
    outputs: [
      { id: 'trajectory', name: 'Trajectory', type: 'trajectory', required: true },
    ],
  },
  {
    type: 'reachy_move_output',
    label: 'Move Output',
    description: 'Display saved Reachy custom move',
    icon: '💾',
    color: '#10b981', // emerald-500
    category: 'robot_recording',
    defaultConfig: {},
    inputs: [
      { id: 'trajectory', name: 'Trajectory', type: 'trajectory', required: true },
    ],
    outputs: [],
  },

  // ---------- Reachy Actions (M24): HF official moves + Conversation App ----------
  {
    type: 'reachy_play_move',
    label: 'Reachy 播放官方动作',
    description: '播放 Pollen Robotics HF 表情/舞蹈库中的预录动作',
    icon: '🎵',
    color: '#f59e0b', // amber-500
    category: 'robot_recording',
    defaultConfig: {
      datasetKind: 'emotions',
      moveName: '',
    },
    inputs: [
      { id: 'daemon', name: 'Daemon', type: 'daemon_status', required: true },
    ],
    outputs: [
      { id: 'played', name: 'Played', type: 'played_move', required: false },
    ],
  },
  {
    type: 'reachy_emotion',
    label: 'Reachy 表情',
    description: '快捷播放官方表情库中的一个表情 (happy/sad/...)',
    icon: '😊',
    color: '#fbbf24', // amber-400
    category: 'robot_recording',
    defaultConfig: {
      emotion: 'happy',
    },
    inputs: [
      { id: 'daemon', name: 'Daemon', type: 'daemon_status', required: true },
    ],
    outputs: [
      { id: 'played', name: 'Played', type: 'played_move', required: false },
    ],
  },
  {
    type: 'reachy_start_conversation',
    label: 'Reachy 启动对话',
    description: '一键安装+启动官方 Conversation App (LLM 语音对话)',
    icon: '💬',
    color: '#06b6d4', // cyan-500
    category: 'robot_recording',
    defaultConfig: {
      backend: 'huggingface',
      apiKey: '',
      model: '',
    },
    inputs: [
      { id: 'daemon', name: 'Daemon', type: 'daemon_status', required: true },
    ],
    outputs: [
      { id: 'app', name: 'App', type: 'app_status', required: false },
    ],
  },
  {
    type: 'reachy_stop_app',
    label: 'Reachy 停止 App',
    description: '停止当前运行的 Reachy App (含 Conversation App)',
    icon: '⏹️',
    color: '#64748b', // slate-500
    category: 'robot_recording',
    defaultConfig: {},
    inputs: [],
    outputs: [],
  },

  // ---------- Skill Invoke（Phase 5: 复用 Skills API 执行已安装 Skill） ----------
  {
    type: 'skill_invoke',
    label: 'Skill Invoke',
    description: 'Run an installed skill via the Skills API',
    icon: '⚡',
    color: '#f97316', // orange-500
    category: 'skill_run',
    defaultConfig: {
      skillId: '',
      runtimeId: '',
      params: {},
    },
    inputs: [],
    outputs: [
      { id: 'run', name: 'Run', type: 'any', required: false },
    ],
    minTier: 'free',
  },
  {
    type: 'camera_denoise',
    label: 'Camera Denoise',
    description: 'Denoise camera frames before training (Pro)',
    icon: '🎥',
    color: '#8b5cf6',
    category: 'process',
    defaultConfig: { strength: 0.5 },
    inputs: [{ id: 'dataset', name: 'Dataset', type: 'dataset', required: true }],
    outputs: [{ id: 'dataset_out', name: 'Dataset', type: 'dataset', required: true }],
    minTier: 'pro',
  },
  {
    type: 'trajectory_optimize',
    label: 'Trajectory Optimize',
    description: 'Smooth joint trajectories (Pro)',
    icon: '🛠️',
    color: '#a855f7',
    category: 'process',
    defaultConfig: { smoothing: 0.3 },
    inputs: [{ id: 'dataset', name: 'Dataset', type: 'dataset', required: true }],
    outputs: [{ id: 'dataset_out', name: 'Dataset', type: 'dataset', required: true }],
    minTier: 'pro',
  },

  // ---------- Legacy Demo 节点（兼容旧工作流，不参与 Finetune 运行前检查） ----------
  {
    type: 'robot_connect',
    label: 'Robot Connect',
    description: 'Connect to a robot (legacy demo)',
    icon: '🤖',
    color: '#3b82f6',
    category: 'input',
    defaultConfig: { robotId: '' },
    inputs: [],
    outputs: [{ id: 'robot', name: 'Robot', type: 'robot', required: true }],
  },
  {
    type: 'record',
    label: 'Record Data',
    description: 'Record robot data (legacy demo)',
    icon: '📹',
    color: '#8b5cf6',
    category: 'process',
    defaultConfig: { episodes: 10, fps: 30, datasetName: '' },
    inputs: [{ id: 'robot', name: 'Robot', type: 'robot', required: true }],
    outputs: [{ id: 'dataset', name: 'Dataset', type: 'dataset', required: true }],
  },
  {
    type: 'train',
    label: 'Train Model',
    description: 'Local train demo (legacy)',
    icon: '🛠️',
    color: '#a855f7',
    category: 'training',
    defaultConfig: { modelType: 'act', epochs: 100, batchSize: 8 },
    inputs: [{ id: 'dataset', name: 'Dataset', type: 'dataset', required: true }],
    outputs: [{ id: 'model', name: 'Model', type: 'model', required: true }],
  },
  {
    type: 'deploy',
    label: 'Deploy',
    description: 'Deploy model to robot (legacy demo)',
    icon: '🚀',
    color: '#14b8a6',
    category: 'deployment',
    defaultConfig: {},
    inputs: [
      { id: 'model', name: 'Model', type: 'model', required: true },
      { id: 'robot', name: 'Robot', type: 'robot', required: true },
    ],
    outputs: [],
  },
  {
    type: 'visualize',
    label: 'Visualize',
    description: 'Visualize results (legacy demo)',
    icon: '📊',
    color: '#ec4899',
    category: 'output',
    defaultConfig: {},
    inputs: [{ id: 'data', name: 'Data', type: 'any', required: true }],
    outputs: [],
  },

  // ---------- Simulation Pretraining (Isaac Sim / IsaacLab) ----------
  {
    type: 'isaac_sim_pretrain',
    label: 'Isaac Sim 预训练',
    description: '在 Isaac Sim 仿真里先训一版策略，再迁移到真机微调（冷启动利器）',
    icon: '🛰️',
    color: '#22d3ee', // cyan-400
    category: 'simulation',
    defaultConfig: {
      scenario: 'roco_task_board',   // IROS 2026 task-board by default
      robot: 'lekiwi',                // lekiwi | so101 | unitree_g1 | ...
      algorithm: 'rl_ppo',            // rl_ppo | sac | diffusion_policy
      total_steps: 100_000,
      seed: 42,
      compute_node_id: '',            // empty = use default Remote Compute Node
      output_model_id: '',            // HF repo id to push the resulting policy
    },
    inputs: [],
    outputs: [
      { id: 'model', name: 'Pretrained Policy', type: 'model', required: true },
    ],
    minTier: 'free',
  },

  // ---------- Application Scenarios ----------
  {
    type: 'lekiwi_handshake_collect',
    label: 'LeKiwi 握手采集',
    description: '应用场景模板：LeKiwi 在人群中握手。三段式 L1/L2/L3 数据计划，反哺大脑。',
    icon: '🤝',
    color: '#f59e0b', // amber-500
    category: 'scenarios',
    defaultConfig: {
      // L1: basic handshake (single person, fixed pose)
      l1_target_episodes: 20,
      l1_description: '单人正面握手，固定距离',
      // L2: varied approach angles + different hand heights
      l2_target_episodes: 50,
      l2_description: '不同接近角度、不同手高度',
      // L3: crowd + dynamic + noise
      l3_target_episodes: 100,
      l3_description: '人群环境、动态干扰、噪声',
      teleop_method: 'quest',          // 'quest' | 'leader_arm'
      dataset_repo_id: '',             // HF repo id, e.g. user/lekiwi-handshake
      compute_node_id: '',
    },
    inputs: [],
    outputs: [
      { id: 'dataset', name: 'Handshake Dataset', type: 'dataset', required: true },
    ],
    minTier: 'free',
  },
];
