import { Link } from 'react-router-dom'
import { Loader2, CheckCircle2, List } from 'lucide-react'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import { StatusBadge } from './shared'
import { fmtTs } from './utils'
import type { TrainingJobDTO } from '../../types/training'

export function TrainingJobsBanner({
  jobs,
  watchJobId,
  onWatch,
  onShowAll,
  showAll,
}: {
  jobs: TrainingJobDTO[]
  watchJobId: string | null
  onWatch: (id: string) => void
  onShowAll: () => void
  showAll: boolean
}) {
  const active = jobs.filter((j) => j.status === 'queued' || j.status === 'running')
  const finished = jobs.filter((j) => j.status === 'succeeded' || j.status === 'failed' || j.status === 'cancelled')
  const preview = showAll
    ? jobs
    : [...active, ...finished.slice(0, Math.max(0, 5 - active.length))]

  if (jobs.length === 0) {
    return (
      <div className="rounded-lg border border-dashed px-4 py-3 text-sm text-muted-foreground text-center">
        还没有训练任务
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-border/80 bg-card/50 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 border-b border-border/60 bg-muted/20">
        <div className="flex items-center gap-3 text-sm">
          <List className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium">我的训练任务</span>
          {active.length > 0 && (
            <Badge variant="outline" className="text-sky-300 border-sky-500/40 gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              进行中 {active.length}
            </Badge>
          )}
          {finished.filter((j) => j.status === 'succeeded').length > 0 && (
            <Badge variant="outline" className="text-emerald-300 border-emerald-500/40 gap-1">
              <CheckCircle2 className="h-3 w-3" />
              已完成 {finished.filter((j) => j.status === 'succeeded').length}
            </Badge>
          )}
        </div>
        <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={onShowAll}>
          {showAll ? '收起列表' : `展开全部 (${jobs.length})`}
        </Button>
      </div>
      <ul className="divide-y divide-border/50 max-h-[220px] overflow-y-auto">
        {preview.map((j) => {
          const live = j.status === 'queued' || j.status === 'running'
          return (
            <li
              key={j.id}
              className={`flex items-center gap-2 px-4 py-2 text-sm ${watchJobId === j.id ? 'bg-primary/5' : ''}`}
            >
              <StatusBadge status={j.status} />
              {j.train_backend === 'qualia' && (
                <span className="text-[10px] text-sky-400">云端</span>
              )}
              <span className="font-mono text-xs truncate flex-1" title={j.dataset_id}>
                {j.dataset_id}
              </span>
              <span className="text-[10px] text-muted-foreground hidden sm:inline">{j.algo}</span>
              <span className="text-[10px] text-muted-foreground">{fmtTs(j.created_at)}</span>
              {live ? (
                <Button size="sm" variant="secondary" className="h-7 text-xs" onClick={() => onWatch(j.id)}>
                  看进度
                </Button>
              ) : j.status === 'succeeded' ? (
                <Link to="/inference">
                  <Button size="sm" variant="outline" className="h-7 text-xs">
                    去推理
                  </Button>
                </Link>
              ) : (
                <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => onWatch(j.id)}>
                  详情
                </Button>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
