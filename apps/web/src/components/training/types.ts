import type { TrainingJobDTO } from '../../types/training'
import type { DatasetSummary } from '../../types/dataset'

export type WizardStep = 'data' | 'goal' | 'prepare' | 'confirm' | 'running' | 'done'

export type TrainingGoal = 'recommended_cloud' | 'local_quick' | 'expert'

export type PrepareCheckStatus = 'pending' | 'running' | 'ok' | 'block' | 'warn'

export interface PrepareCheck {
  id: string
  label: string
  status: PrepareCheckStatus
  detail?: string
  actionLabel?: string
  actionHref?: string
}

export interface AlgoOption {
  id: string
  name: string
  backend: string
  description: string
  available?: boolean
  reason?: string
  requires_cloud?: boolean
  requires_camera?: boolean
  model_size_mb?: number
  min_episodes?: number
  tags?: string[]
}

export interface QualiaInstance {
  id: string
  gpu_description: string
  credits_per_hour: number
  specs: { gpu_count: number; memory_gib: number }
  regions: string[]
}

export interface QualiaDefaults {
  instance_type: string
  hours: number
  batch_size: number
  model_id: string | null
}

export interface JobDetail extends TrainingJobDTO {
  qualia_status?: {
    status?: string
    phase?: string
    phases?: { name: string; events: { message?: string }[] }[]
    output_model_id?: string | null
  }
}

export type DatasetReadiness = {
  ready: boolean
  status: string
  label: string
  dataset_hf_id?: string
  camera_keys?: string[]
}

export function datasetTrainability(d: DatasetSummary): {
  level: 'ready' | 'needs_prep' | 'blocked'
  label: string
  hint: string
} {
  if (d.hf_repo_id) {
    return {
      level: 'ready',
      label: '可直接训练',
      hint: '已上传到云端，选它就能开始。',
    }
  }
  if (d.has_images) {
    return {
      level: 'needs_prep',
      label: '有视频',
      hint: '系统会自动帮你准备好云端训练。',
    }
  }
  return {
    level: 'blocked',
    label: '不能训练',
    hint: '没有摄像头视频，请重新录制时打开摄像头。',
  }
}

export function sortDatasetsForWizard(items: DatasetSummary[]): DatasetSummary[] {
  const order = { ready: 0, needs_prep: 1, blocked: 2 }
  return [...items].sort((a, b) => {
    const oa = order[datasetTrainability(a).level]
    const ob = order[datasetTrainability(b).level]
    if (oa !== ob) return oa - ob
    const ta = a.recorded_at || a.created_at || ''
    const tb = b.recorded_at || b.created_at || ''
    return tb.localeCompare(ta)
  })
}
