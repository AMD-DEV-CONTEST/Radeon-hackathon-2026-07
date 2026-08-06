export type TrainingStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface TrainingJobDTO {
  id: string
  dataset_id: string
  algo: string
  hparams: Record<string, unknown>
  status: TrainingStatus
  progress_pct: number
  epoch: number
  total_epochs: number
  loss: number | null
  pid: number | null
  log_path: string | null
  error_msg: string | null
  model_id: string | null
  train_backend?: string
  skill_id?: string
  created_at: string | null
  started_at: string | null
  finished_at: string | null
}

export interface ModelDTO {
  id: string
  model_key: string
  name: string
  algo: string
  dataset_id: string | null
  checkpoint_path: string
  size_bytes: number
  metrics: Record<string, unknown>
  hparams: Record<string, unknown>
  input_dim: number | null
  output_dim: number | null
  status: string
  created_at: string | null
}
