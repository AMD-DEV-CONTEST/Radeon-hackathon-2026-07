import type { Robot, Dataset, Model, TrainingJob, SystemStatus, RecordingSession, HubModel, HubSearchParams } from '../types';

const API_BASE = '/api/v1';

async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ message: 'Unknown error' }));
    throw new Error(error.message || `HTTP ${response.status}`);
  }

  return response.json();
}

// System
export const getSystemStatus = () => fetchApi<SystemStatus>('/status');

// Robots
export const getRobots = () => fetchApi<Robot[]>('/robots');
export const getRobot = (id: string) => fetchApi<Robot>(`/robots/${id}`);
export const connectRobot = (id: string) => fetchApi<Robot>(`/robots/${id}/connect`, { method: 'POST' });
export const disconnectRobot = (id: string) => fetchApi<void>(`/robots/${id}/disconnect`, { method: 'POST' });

// Datasets
export const getDatasets = () => fetchApi<Dataset[]>('/datasets');
export const getDataset = (id: string) => fetchApi<Dataset>(`/datasets/${id}`);
export const deleteDataset = (id: string) => fetchApi<void>(`/datasets/${id}`, { method: 'DELETE' });

// Recording
export const startRecording = (datasetId: string, config?: { episodes?: number; fps?: number }) =>
  fetchApi<RecordingSession>('/record/start', {
    method: 'POST',
    body: JSON.stringify({ datasetId, ...config }),
  });

export const stopRecording = () =>
  fetchApi<void>('/record/stop', { method: 'POST' });

export const getRecordingStatus = () =>
  fetchApi<RecordingSession>('/record/status');

// Models
export const getModels = () => fetchApi<Model[]>('/models');
export const getModel = (id: string) => fetchApi<Model>(`/models/${id}`);
export const deleteModel = (id: string) => fetchApi<void>(`/models/${id}`, { method: 'DELETE' });

// Training
export const startTraining = (config: { modelId: string; datasetId: string; epochs?: number; batchSize?: number }) =>
  fetchApi<TrainingJob>('/train', {
    method: 'POST',
    body: JSON.stringify(config),
  });

export const stopTraining = (jobId: string) =>
  fetchApi<void>(`/train/${jobId}/stop`, { method: 'POST' });

export const getTrainingJobs = () => fetchApi<TrainingJob[]>('/training/status');
export const getTrainingJob = (id: string) => fetchApi<TrainingJob>(`/training/status/${id}`);

// Hub API
export const searchHubModels = (params?: HubSearchParams) => {
  const queryParams = new URLSearchParams();
  if (params?.query) queryParams.set('query', params.query);
  if (params?.tags) queryParams.set('tags', params.tags);
  if (params?.sort) queryParams.set('sort', params.sort);
  if (params?.limit) queryParams.set('limit', params.limit.toString());

  const queryString = queryParams.toString();
  return fetchApi<HubModel[]>(`/hub/models${queryString ? `?${queryString}` : ''}`);
};

export const getHubModel = (repo_id: string) =>
  fetchApi<HubModel>(`/hub/models/${repo_id}`);

export const uploadToHub = (data: {
  local_model_id: string;
  repo_name: string;
  description: string;
  tags: string[];
  readme: string;
  private?: boolean;
}) => fetchApi<{ url: string; message?: string }>('/hub/upload', {
  method: 'POST',
  body: JSON.stringify(data),
});

export const downloadFromHub = (data: {
  repo_id: string;
  local_name: string;
}) => fetchApi<{ success: boolean; message: string; local_name: string }>('/hub/download', {
  method: 'POST',
  body: JSON.stringify(data),
});

export const likeHubModel = (repo_id: string) =>
  fetchApi<{ message: string; url: string }>(`/hub/models/${repo_id}/like`, { method: 'POST' });
