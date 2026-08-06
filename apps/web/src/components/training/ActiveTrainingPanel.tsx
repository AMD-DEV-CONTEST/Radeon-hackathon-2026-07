import { Link } from 'react-router-dom'
import { Cpu, X, ArrowLeft } from 'lucide-react'
import { Button } from '../ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import { StatusBadge, LossChart } from './shared'
import { fmtTs } from './utils'
import type { TrainingJobDTO } from '../../types/training'

export function ActiveTrainingPanel({
  job,
  snapshot,
  lossHistory,
  wsErr,
  onCancel,
  cancelling,
  onDone,
  onBack,
}: {
  job: TrainingJobDTO | null
  snapshot: TrainingJobDTO | null
  lossHistory: { epoch: number; loss: number }[]
  wsErr: string | null
  onCancel: () => void
  cancelling: boolean
  onDone?: () => void
  onBack?: () => void
}) {
  const st = snapshot?.status ?? job?.status ?? 'queued'
  const isLive = st === 'running' || st === 'queued'
  const succeeded = st === 'succeeded'
  const failed = st === 'failed'
  const cancelled = st === 'cancelled'

  if (!job) {
    return (
      <Card className="border-muted">
        <CardContent className="py-8 text-center space-y-3">
          <p className="text-sm text-muted-foreground">没有找到对应的训练任务。</p>
          {onBack && (
            <Button variant="outline" onClick={onBack}>
              <ArrowLeft className="h-4 w-4 mr-1" />
              返回向导
            </Button>
          )}
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className={`${isLive ? 'border-sky-500/30' : succeeded ? 'border-emerald-500/30' : 'border-border'}`}>
      <CardHeader className="py-3 flex flex-row items-center justify-between">
        <CardTitle className="text-base flex items-center gap-2">
          <Cpu className="h-4 w-4" />
          {succeeded ? '训练完成' : failed ? '训练失败' : cancelled ? '训练已取消' : '训练进行中'}
        </CardTitle>
        <div className="flex items-center gap-2">
          {isLive && (
            <Button size="sm" variant="destructive" disabled={cancelling} onClick={onCancel}>
              <X className="h-3 w-3 mr-1" />
              {cancelling ? '取消中…' : '取消训练'}
            </Button>
          )}
          {onBack && (
            <Button size="sm" variant="outline" onClick={onBack}>
              <ArrowLeft className="h-3 w-3 mr-1" />
              返回
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Job summary info - always visible */}
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs rounded-lg border bg-muted/20 p-3">
          <div>
            <span className="text-muted-foreground">状态 </span>
            <StatusBadge status={st} />
          </div>
          <div>
            <span className="text-muted-foreground">方式 </span>
            <span>{job.train_backend === 'qualia' ? '云端' : '本地'}</span>
          </div>
          <div>
            <span className="text-muted-foreground">算法 </span>
            <span className="font-mono">{job.algo}</span>
          </div>
          <div>
            <span className="text-muted-foreground">数据集 </span>
            <span className="font-mono truncate">{job.dataset_id}</span>
          </div>
          <div>
            <span className="text-muted-foreground">创建于 </span>
            <span>{fmtTs(job.created_at)}</span>
          </div>
          {job.finished_at && (
            <div>
              <span className="text-muted-foreground">结束于 </span>
              <span>{fmtTs(job.finished_at)}</span>
            </div>
          )}
        </div>

        {succeeded && (
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
            模型已训练完成，可以去推理页面让机械臂运行新策略。
            <div className="mt-3 flex gap-2">
              <Link to="/inference?from_setup=1">
                <Button size="sm">去推理运行</Button>
              </Link>
              {onDone && (
                <Button size="sm" variant="outline" onClick={onDone}>
                  再训练一个
                </Button>
              )}
            </div>
          </div>
        )}
        {failed && (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {snapshot?.error_msg || job.error_msg || '训练失败，请检查数据或稍后重试。'}
            {onDone && (
              <div className="mt-3">
                <Button size="sm" variant="outline" onClick={onDone}>
                  重新配置训练
                </Button>
              </div>
            )}
          </div>
        )}
        {cancelled && (
          <div className="rounded-lg border border-muted bg-muted/20 px-4 py-3 text-sm text-muted-foreground">
            这个训练任务已被取消。
            {onDone && (
              <div className="mt-3">
                <Button size="sm" variant="outline" onClick={onDone}>
                  重新开始
                </Button>
              </div>
            )}
          </div>
        )}
        {isLive && (
          <>
            <p className="text-sm text-muted-foreground">
              训练{job.train_backend === 'qualia' ? '在云端进行' : '在本机进行'}，你可以离开页面。完成后回来部署即可。
            </p>
            <div className="flex items-center gap-3 flex-wrap">
              <StatusBadge status={st} />
              <span className="text-xs font-mono text-muted-foreground">
                {snapshot?.epoch ?? 0} / {snapshot?.total_epochs ?? '—'} epoch
              </span>
            </div>
            <div className="h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-primary transition-[width] duration-300"
                style={{ width: `${snapshot?.progress_pct ?? 0}%` }}
              />
            </div>
            <LossChart points={lossHistory} />
          </>
        )}
        {wsErr && <p className="text-xs text-red-300">{wsErr}</p>}
      </CardContent>
    </Card>
  )
}
