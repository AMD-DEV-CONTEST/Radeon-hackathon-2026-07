import { useState } from 'react'
import { ChevronDown, ChevronRight, X } from 'lucide-react'
import { Button } from '../ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import { Badge } from '../ui/badge'
import { StatusBadge } from './shared'
import { fmtTs } from './utils'
import type { TrainingJobDTO } from '../../types/training'
import type { JobDetail } from './types'

export function TrainingHistoryPanel({
  jobs,
  watchJobId,
  onWatch,
  expandedJobId,
  onToggleExpand,
  jobDetail,
  detailLoading,
  onCancel,
  cancellingId,
}: {
  jobs: TrainingJobDTO[]
  watchJobId: string | null
  onWatch: (id: string) => void
  expandedJobId: string | null
  onToggleExpand: (id: string) => void
  jobDetail: JobDetail | null
  detailLoading: boolean
  onCancel: (id: string) => void
  cancellingId: string | null
}) {
  const [showAll, setShowAll] = useState(false)
  const latest = jobs[0]
  const display = showAll ? jobs : jobs.slice(0, 3)

  if (jobs.length === 0) return null

  return (
    <Card>
      <CardHeader className="py-3 flex flex-row items-center justify-between">
        <CardTitle className="text-base">训练记录</CardTitle>
        {jobs.length > 3 && (
          <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setShowAll(!showAll)}>
            {showAll ? '收起' : `查看全部 (${jobs.length})`}
          </Button>
        )}
      </CardHeader>
      <CardContent className="p-0 divide-y">
        {display.map((j) => {
          const isOpen = expandedJobId === j.id
          const isLive = j.status === 'running' || j.status === 'queued'
          const isCloud = j.train_backend === 'qualia'
          const isLatest = latest?.id === j.id
          return (
            <div key={j.id} className={isLatest ? 'bg-muted/10' : ''}>
              <div className="flex items-center gap-2 px-4 py-2.5 text-sm">
                <button type="button" onClick={() => onToggleExpand(j.id)} className="p-0.5">
                  {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                </button>
                <StatusBadge status={j.status} />
                {isCloud && (
                  <Badge variant="outline" className="text-[9px] border-sky-500/40 text-sky-300">
                    云端
                  </Badge>
                )}
                {isLatest && (
                  <Badge variant="outline" className="text-[9px]">
                    最近
                  </Badge>
                )}
                <span className="font-mono text-xs truncate flex-1">{j.dataset_id}</span>
                <span className="text-xs text-muted-foreground hidden md:inline">{j.algo}</span>
                <button
                  type="button"
                  onClick={() => onWatch(j.id)}
                  className={`text-[11px] ${watchJobId === j.id ? 'text-primary font-medium' : 'text-muted-foreground hover:underline'}`}
                >
                  查看
                </button>
                {isLive && (
                  <Button
                    size="sm"
                    variant="destructive"
                    className="h-6 px-2 text-[10px]"
                    disabled={cancellingId === j.id}
                    onClick={() => onCancel(j.id)}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                )}
              </div>
              {isOpen && jobDetail?.id === j.id && (
                <div className="px-4 pb-3 text-[11px] font-mono text-muted-foreground space-y-1 border-t border-border/40 bg-muted/10">
                  {detailLoading && <div>加载中…</div>}
                  <div>id: {jobDetail.id}</div>
                  {jobDetail.error_msg && (
                    <div className="text-red-300">{jobDetail.error_msg}</div>
                  )}
                  {jobDetail.qualia_status?.phase && (
                    <div className="text-sky-300">phase: {jobDetail.qualia_status.phase}</div>
                  )}
                </div>
              )}
              {!isOpen && (
                <div className="px-4 pb-2 text-[10px] text-muted-foreground">{fmtTs(j.created_at)}</div>
              )}
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
