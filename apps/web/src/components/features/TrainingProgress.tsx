import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import { Badge } from '../ui/badge'
import { Brain, Clock, TrendingDown } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { TrainingJob } from '../../types'

interface TrainingProgressProps {
  job: TrainingJob
  onStop?: (id: string) => void
}

export function TrainingProgress({ job, onStop }: TrainingProgressProps) {
  const statusConfig = {
    pending: { variant: 'secondary' as const, text: 'Pending' },
    running: { variant: 'success' as const, text: 'Running' },
    completed: { variant: 'default' as const, text: 'Completed' },
    failed: { variant: 'error' as const, text: 'Failed' },
    stopped: { variant: 'warning' as const, text: 'Stopped' },
  }

  const config = statusConfig[job.status]

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-primary/10 flex items-center justify-center">
              <Brain className="h-5 w-5 text-primary" />
            </div>
            <div>
              <CardTitle className="text-base">{job.modelName}</CardTitle>
              <div className="text-xs text-muted-foreground">
                Epoch {job.epoch}/{job.totalEpochs}
              </div>
            </div>
          </div>
          <Badge variant={config.variant}>{config.text}</Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Progress Bar */}
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Progress</span>
            <span className="font-medium">{job.progress}%</span>
          </div>
          <div className="h-2 rounded-full bg-muted overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500",
                job.status === 'running' ? "bg-primary animate-pulse" : "bg-primary"
              )}
              style={{ width: `${job.progress}%` }}
            />
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 gap-4">
          {job.loss !== undefined && (
            <div className="flex items-center gap-2">
              <TrendingDown className="h-4 w-4 text-green-400" />
              <div>
                <div className="text-xs text-muted-foreground">Loss</div>
                <div className="text-sm font-medium">{job.loss.toFixed(4)}</div>
              </div>
            </div>
          )}

          {job.estimatedEnd && (
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <div>
                <div className="text-xs text-muted-foreground">Remaining</div>
                <div className="text-sm font-medium">{job.estimatedEnd}</div>
              </div>
            </div>
          )}
        </div>

        {/* Stop Button */}
        {job.status === 'running' && onStop && (
          <button
            onClick={() => onStop(job.id)}
            className="w-full py-2 text-sm text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition-colors"
          >
            Stop Training
          </button>
        )}
      </CardContent>
    </Card>
  )
}
