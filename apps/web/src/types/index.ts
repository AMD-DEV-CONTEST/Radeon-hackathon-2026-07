export interface Robot {
  id: string;
  name: string;
  type: string;
  status: 'online' | 'offline' | 'busy';
  jointPositions?: number[];
  cameraConnected?: boolean;
  lastSeen?: string;
}

export interface Dataset {
  id: string;
  name: string;
  episodes: number;
  frames: number;
  size: string;
  createdAt: string;
  robotType: string;
}

export interface Model {
  id: string;
  name: string;
  type: 'act' | 'diffusion' | 'vla';
  status: 'training' | 'ready' | 'deployed' | 'error';
  datasetId?: string;
  createdAt: string;
  size?: string;
}

export interface HubModel {
  repo_id: string;
  author: string;
  name: string;
  description: string;
  tags: string[];
  downloads: number;
  likes: number;
  created_at: string;
  updated_at: string;
  size: string;
  task_type: string;
  robot_type: string;
}

export interface HubSearchParams {
  query?: string;
  tags?: string;
  sort?: 'downloads' | 'likes' | 'recent';
  limit?: number;
}

export interface TrainingJob {
  id: string;
  modelId: string;
  modelName: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'stopped';
  progress: number;
  epoch: number;
  totalEpochs: number;
  loss?: number;
  startedAt?: string;
  estimatedEnd?: string;
}

export interface RecordingSession {
  id: string;
  datasetId: string;
  episode: number;
  totalEpisodes: number;
  frames: number;
  isRecording: boolean;
  fps: number;
}

export interface SystemStatus {
  robots: {
    total: number;
    online: number;
  };
  datasets: {
    total: number;
    totalFrames: number;
  };
  models: {
    total: number;
    training: number;
    deployed: number;
  };
  trainingJobs: TrainingJob[];
}
