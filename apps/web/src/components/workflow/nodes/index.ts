import { RobotNode } from './RobotNode';
import { RecordNode } from './RecordNode';
import { TrainNode } from './TrainNode';
import { DeployNode } from './DeployNode';
import { DatasetLoadNode } from './DatasetLoadNode';
import { CameraMapNode } from './CameraMapNode';
import { FinetuneJobNode } from './FinetuneJobNode';
import { JobMonitorNode } from './JobMonitorNode';
import { SkillInvokeNode } from './SkillInvokeNode';
import { EvaluateNode } from './EvaluateNode';
import { PublishSkillNode } from './PublishSkillNode';
import { RecordDatasetStartNode } from './RecordDatasetStartNode';
import { RecordingMonitorNode } from './RecordingMonitorNode';
import { DatasetCheckNode } from './DatasetCheckNode';
import { ReachyDaemonCheckNode } from './ReachyDaemonCheckNode';
import { ReachyRecordMoveNode } from './ReachyRecordMoveNode';
import { ReachyMoveOutputNode } from './ReachyMoveOutputNode';
import { HfDatasetNode } from './HfDatasetNode';
import { EgoDatasetNode } from './EgoDatasetNode';
import { CameraNoiseNode } from './CameraNoiseNode';
import { TrajectoryNoiseNode } from './TrajectoryNoiseNode';
import { ApiPendingNode } from './ApiPendingNode';
import { OutputDatasetNode } from './OutputDatasetNode';
import { MergeDatasetsNode } from './MergeDatasetsNode';
import { QualiaFinetuneNode } from './QualiaFinetuneNode';
import { RewardModelNode } from './RewardModelNode';
import {
  ReachyPlayMoveNode,
  ReachyEmotionNode,
  ReachyStartConversationNode,
  ReachyStopAppNode,
} from './ReachyActionNodes';
import type { NodeTypes } from '@xyflow/react';

export const nodeTypes: NodeTypes = {
  // Qualia Studio: Data Sources
  hf_dataset: HfDatasetNode,
  ego_dataset: EgoDatasetNode,

  // Qualia Studio: Transforms
  camera_noise: CameraNoiseNode,
  trajectory_noise: TrajectoryNoiseNode,
  depth_estimator: ApiPendingNode,
  pose_action_extractor: ApiPendingNode,

  // Qualia Studio: Generative
  world_model_generator: ApiPendingNode,
  urdf_inpaint: ApiPendingNode,
  idm_inverse_dynamics: ApiPendingNode,

  // Qualia Studio: Outputs
  output_dataset: OutputDatasetNode,
  merge_datasets: MergeDatasetsNode,

  // Qualia Studio: Foundation Models
  qualia_finetune: QualiaFinetuneNode,
  reward_model_tuning: RewardModelNode,
  job_monitor: JobMonitorNode,

  // Legacy Finetune chain
  dataset_load: DatasetLoadNode,
  camera_map: CameraMapNode,
  finetune_job: FinetuneJobNode,

  // Skill Factory
  evaluate: EvaluateNode,
  publish_skill: PublishSkillNode,

  // Skill invoke
  skill_invoke: SkillInvokeNode,

  // Real Robot Recording — SO-101
  record_dataset_start: RecordDatasetStartNode,
  recording_monitor: RecordingMonitorNode,
  dataset_check: DatasetCheckNode,

  // Real Robot Recording — Reachy
  reachy_daemon_check: ReachyDaemonCheckNode,
  reachy_record_move: ReachyRecordMoveNode,
  reachy_move_output: ReachyMoveOutputNode,

  // Real Robot Actions — Reachy (M24)
  reachy_play_move: ReachyPlayMoveNode,
  reachy_emotion: ReachyEmotionNode,
  reachy_start_conversation: ReachyStartConversationNode,
  reachy_stop_app: ReachyStopAppNode,

  // Legacy demo
  robot_connect: RobotNode,
  record: RecordNode,
  train: TrainNode,
  deploy: DeployNode,
  visualize: RobotNode,
};

export {
  RobotNode,
  RecordNode,
  TrainNode,
  DeployNode,
  DatasetLoadNode,
  CameraMapNode,
  FinetuneJobNode,
  JobMonitorNode,
  SkillInvokeNode,
  EvaluateNode,
  PublishSkillNode,
  RecordDatasetStartNode,
  RecordingMonitorNode,
  DatasetCheckNode,
  ReachyDaemonCheckNode,
  ReachyRecordMoveNode,
  ReachyMoveOutputNode,
  HfDatasetNode,
  EgoDatasetNode,
  CameraNoiseNode,
  TrajectoryNoiseNode,
  ApiPendingNode,
  OutputDatasetNode,
  MergeDatasetsNode,
  QualiaFinetuneNode,
  RewardModelNode,
  ReachyPlayMoveNode,
  ReachyEmotionNode,
  ReachyStartConversationNode,
  ReachyStopAppNode,
};
