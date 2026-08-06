/** Dataset item shape — union of realtime /api/datasets and API /api/v1/datasets. */
export interface DatasetSummary {
  dataset_id: string
  name: string
  path?: string
  source: string
  robot_id: string | null
  frame_count: number | null
  duration_s: number | null
  fps_nominal: number | null
  recorded_at?: string | null
  created_at?: string | null
  has_images?: boolean
  image_frames?: number
  parquet?: string
  meta?: Record<string, unknown>
  hf_repo_id?: string | null
  hf_url?: string | null
  hf_private?: boolean | null
  status?: string
  quality_score?: number
}

export interface DatasetListResponse {
  total: number
  items: DatasetSummary[]
  storage_root?: string
}

export interface PlaybackMeta {
  dataset_id: string
  frame_count: number | null
  fps_nominal: number | null
  duration_s: number
  robot_id: string | null
  joints: string[]
  meta: Record<string, unknown>
}
