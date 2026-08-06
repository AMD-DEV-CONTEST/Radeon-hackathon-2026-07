import { useEffect, useState } from 'react'
import { Cloud, Cpu, Database } from 'lucide-react'
import type { TrainingGoal } from './types'
import type { DatasetSummary } from '../../types/dataset'
import type { QualiaInstance } from './types'
import {
  listRemoteComputeNodes,
  remoteComputeAcceleratorLabel,
} from '../../lib/remoteComputeApi'

const GOAL_SHORT: Record<TrainingGoal, string> = {
  recommended_cloud: '云端训练',
  local_quick: '本地 / 自有算力',
  expert: '专家自定义',
}

export function WizardChoicesSummary({
  dataset,
  goal,
  goalTouched,
  trainBackend,
  qHours,
  qInstance,
  qInstances,
  epochs,
  costLabel,
}: {
  dataset: DatasetSummary | undefined
  goal: TrainingGoal
  goalTouched: boolean
  trainBackend: 'local' | 'qualia'
  qHours: number
  qInstance: string
  qInstances: QualiaInstance[]
  epochs: number
  costLabel?: string | null
}) {
  const gpu = qInstances.find((i) => i.id === qInstance)
  const datasetName = dataset?.name || dataset?.dataset_id || '未选择'
  const [accLabel, setAccLabel] = useState<string | null>(null)

  useEffect(() => {
    if (!goalTouched || trainBackend !== 'local') {
      setAccLabel(null)
      return
    }
    let cancelled = false
    void listRemoteComputeNodes()
      .then((cfg) => {
        if (cancelled) return
        const id = cfg.default_node_id || 'local'
        const n = cfg.nodes.find((x) => x.id === id)
        setAccLabel(n ? remoteComputeAcceleratorLabel(n.accelerator) : null)
      })
      .catch(() => {
        if (!cancelled) setAccLabel(null)
      })
    return () => {
      cancelled = true
    }
  }, [goalTouched, trainBackend])

  return (
    <div className="rounded-lg border bg-muted/25 px-3 py-2.5 text-xs space-y-1.5">
      <div className="font-medium text-muted-foreground text-[11px]">已选</div>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <span className="inline-flex items-center gap-1.5">
          <Database className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-muted-foreground">数据</span>
          <span className="font-mono truncate max-w-[200px]" title={dataset?.dataset_id}>
            {datasetName}
          </span>
        </span>
        <span className="inline-flex items-center gap-1.5">
          {trainBackend === 'qualia' ? (
            <Cloud className="h-3.5 w-3.5 text-sky-400" />
          ) : (
            <Cpu className="h-3.5 w-3.5 text-emerald-400" />
          )}
          <span className="text-muted-foreground">方式</span>
          <span>{GOAL_SHORT[goal]}</span>
        </span>
        {goalTouched && trainBackend === 'qualia' && (
          <>
            <span>
              <span className="text-muted-foreground">时长 </span>
              {qHours} 小时
            </span>
            {gpu && (
              <span>
                <span className="text-muted-foreground">GPU </span>
                {gpu.gpu_description}
              </span>
            )}
            {costLabel && (
              <span className="text-sky-300">{costLabel}</span>
            )}
          </>
        )}
        {goalTouched && trainBackend === 'local' && (
          <>
            {accLabel ? (
              <span>
                <span className="text-muted-foreground">加速 </span>
                {accLabel}
              </span>
            ) : null}
            <span>
              <span className="text-muted-foreground">轮数 </span>
              {epochs} epoch
            </span>
          </>
        )}
      </div>
    </div>
  )
}
