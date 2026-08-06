import { Link } from 'react-router-dom'
import { Database, Video, Cloud, AlertCircle } from 'lucide-react'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'
import { Badge } from '../ui/badge'
import type { DatasetSummary } from '../../types/dataset'
import { datasetTrainability, sortDatasetsForWizard } from './types'
import { fmtDuration } from './utils'

export function DatasetStep({
  datasets,
  selectedId,
  onSelect,
}: {
  datasets: DatasetSummary[]
  selectedId: string
  onSelect: (id: string) => void
}) {
  const sorted = sortDatasetsForWizard(datasets)
  const recommended = sorted.find((d) => datasetTrainability(d).level !== 'blocked')

  if (datasets.length === 0) {
    return (
      <Card className="border-dashed">
        <CardContent className="py-12 text-center space-y-4">
          <Database className="h-12 w-12 mx-auto text-muted-foreground/40" />
          <p className="text-muted-foreground">还没有数据集，先去录一段带摄像头的数据。</p>
          <Link to="/teleop">
            <Button>去采集数据</Button>
          </Link>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {recommended && (
        <Card
          className={`cursor-pointer border-2 transition-all ${
            selectedId === recommended.dataset_id
              ? 'border-primary bg-primary/5'
              : 'border-primary/30 hover:border-primary/50'
          }`}
          onClick={() => onSelect(recommended.dataset_id)}
        >
          <CardContent className="py-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-xs text-primary font-medium mb-1">推荐</div>
                <div className="font-mono text-sm break-all">{recommended.name || recommended.dataset_id}</div>
                <p className="text-xs text-muted-foreground mt-2">
                  {datasetTrainability(recommended).hint}
                </p>
              </div>
              <Badge className="bg-primary/20 text-primary border-0">
                {datasetTrainability(recommended).label}
              </Badge>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="text-xs text-muted-foreground">或选择其他数据集：</div>
      <div className="grid gap-2 max-h-[280px] overflow-y-auto pr-1">
        {sorted.map((d) => {
          const t = datasetTrainability(d)
          const selected = selectedId === d.dataset_id
          return (
            <button
              key={d.dataset_id}
              type="button"
              onClick={() => onSelect(d.dataset_id)}
              disabled={t.level === 'blocked'}
              className={`text-left rounded-lg border px-3 py-2.5 transition-colors ${
                selected ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/40'
              } ${t.level === 'blocked' ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-xs truncate flex-1">{d.dataset_id}</span>
                {d.has_images && <Video className="h-3.5 w-3.5 text-sky-400" />}
                {d.hf_repo_id && <Cloud className="h-3.5 w-3.5 text-emerald-400" />}
                <Badge variant="outline" className="text-[10px]">
                  {t.label}
                </Badge>
              </div>
              <div className="text-[10px] text-muted-foreground mt-1">
                {d.frame_count?.toLocaleString() ?? '—'} 帧 · {fmtDuration(d.duration_s)}
              </div>
            </button>
          )
        })}
      </div>

      {selectedId && (() => {
        const sel = datasets.find((d) => d.dataset_id === selectedId)
        return sel && datasetTrainability(sel).level === 'blocked'
      })() && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
          <div className="flex items-start gap-2">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
            <div>
              这个数据集没有摄像头视频，无法训练。按你的接入方式选一条路：
              <ul className="mt-1.5 list-disc space-y-1 pl-4">
                <li>
                  装过 Local Agent？{' '}
                  <Link to="/teleop" className="underline">
                    去重新录制（带摄像头）
                  </Link>
                </li>
                <li>
                  浏览器直连录的？{' '}
                  <Link to="/robots/so101?mode=browser" className="underline">
                    回浏览器直连
                  </Link>
                  ——相机对齐（S5）上线后可直接训练
                </li>
              </ul>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
