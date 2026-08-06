import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Zap } from 'lucide-react'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'
import type { TrainingGoal, QualiaInstance } from './types'
import type { DatasetSummary } from '../../types/dataset'
import {
  listRemoteComputeNodes,
  remoteComputeAcceleratorLabel,
  type RemoteComputeNode,
} from '../../lib/remoteComputeApi'

const GOAL_LABELS: Record<TrainingGoal, string> = {
  recommended_cloud: '云端视觉训练（ACT）',
  local_quick: '本地 / 自有算力',
  expert: '专家自定义',
}

export function ConfirmStep({
  dataset,
  goal,
  trainBackend,
  qHours,
  qInstance,
  qInstances,
  epochs,
  algo,
  costLabel,
  submitting,
  onSubmit,
  disabled,
}: {
  dataset: DatasetSummary | undefined
  goal: TrainingGoal
  trainBackend: 'local' | 'qualia'
  qHours: number
  qInstance: string
  qInstances: QualiaInstance[]
  epochs: number
  algo: string
  costLabel?: string | null
  submitting: boolean
  onSubmit: () => void
  disabled: boolean
}) {
  const gpu = qInstances.find((i) => i.id === qInstance)
  const [computeNode, setComputeNode] = useState<RemoteComputeNode | null>(null)

  useEffect(() => {
    if (trainBackend !== 'local') {
      setComputeNode(null)
      return
    }
    let cancelled = false
    void listRemoteComputeNodes()
      .then((cfg) => {
        if (cancelled) return
        const id = cfg.default_node_id || 'local'
        setComputeNode(cfg.nodes.find((n) => n.id === id) || null)
      })
      .catch(() => {
        if (!cancelled) setComputeNode(null)
      })
    return () => {
      cancelled = true
    }
  }, [trainBackend])

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="py-4 space-y-3 text-sm">
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground">数据集</span>
            <span className="font-mono text-xs text-right break-all max-w-[60%]">
              {dataset?.dataset_id ?? '—'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">训练方式</span>
            <span>{GOAL_LABELS[goal]}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">运行位置</span>
            <span>{trainBackend === 'qualia' ? '云端 GPU' : '自有算力节点'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">算法</span>
            <span className="font-mono text-xs">{algo}</span>
          </div>
          {trainBackend === 'qualia' && (
            <>
              <div className="flex justify-between">
                <span className="text-muted-foreground">租用时长</span>
                <span>{qHours} 小时</span>
              </div>
              {gpu && (
                <div className="flex justify-between gap-4">
                  <span className="text-muted-foreground shrink-0">GPU</span>
                  <span className="text-right text-xs">{gpu.gpu_description}</span>
                </div>
              )}
              {costLabel && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">预计费用</span>
                  <span className="text-sky-300">{costLabel}</span>
                </div>
              )}
            </>
          )}
          {trainBackend === 'local' && (
            <>
              <div className="flex justify-between gap-4 items-start">
                <span className="text-muted-foreground shrink-0">算力节点</span>
                <span className="text-right text-xs">
                  {computeNode ? (
                    <>
                      <span
                        className={
                          computeNode.accelerator === 'rocm'
                            ? 'text-[var(--ember)]'
                            : computeNode.accelerator === 'cuda'
                              ? 'text-sky-300'
                              : ''
                        }
                      >
                        {remoteComputeAcceleratorLabel(computeNode.accelerator)}
                      </span>
                      {' · '}
                      {computeNode.name}
                    </>
                  ) : (
                    <Link to="/settings/remote-compute" className="underline text-muted-foreground">
                      未配置 — 去设置
                    </Link>
                  )}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">训练轮数</span>
                <span>{epochs} epoch</span>
              </div>
            </>
          )}
        </CardContent>
      </Card>
      <Button
        size="lg"
        className="w-full h-12 text-base"
        onClick={onSubmit}
        disabled={disabled || submitting}
      >
        <Zap className="h-5 w-5 mr-2" />
        {submitting ? '正在提交…' : '开始训练'}
      </Button>
    </div>
  )
}
