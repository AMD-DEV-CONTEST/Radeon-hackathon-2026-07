export type EngineName = 'auto' | 'deterministic' | 'generative'

export interface JobCreate {
  text: string
  engine: EngineName
  style?: Record<string, unknown>
}

export type JobStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface BridgeManifest {
  route?: string
  reason?: string
  meta?: Record<string, unknown>
  keyMoments?: unknown[]
  events?: unknown[]
}

export interface Job {
  id: string
  engine: EngineName
  status: JobStatus
  progress: number
  message: string | null
  created_at: string | null
  updated_at: string | null
  text: string | null
  manifest: BridgeManifest | null
  artifacts: Record<string, string>
  metrics: Record<string, unknown>
  error: { type: string; message: string } | null
}

export interface JobListResponse {
  jobs: Job[]
  total: number
}

export interface EngineHealth {
  available: boolean
  detail: string
}

export interface HealthResponse {
  status: string
  python: string
  gpu: { available: boolean; detail: string } & Record<string, unknown>
  engines: Record<string, EngineHealth>
}
