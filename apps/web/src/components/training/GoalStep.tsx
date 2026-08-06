import { Cloud, Cpu, Settings2 } from 'lucide-react'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'
import { CloudTrainingOptions } from './CloudTrainingOptions'
import { LocalTrainingOptions } from './LocalTrainingOptions'
import type { TrainingGoal, QualiaInstance } from './types'

const GOALS: {
  id: TrainingGoal
  title: string
  desc: string
  icon: React.ReactNode
  recommended?: boolean
}[] = [
  {
    id: 'recommended_cloud',
    title: '云端训练',
    desc: '云端 GPU，效果最好',
    icon: <Cloud className="h-6 w-6 text-sky-400" />,
    recommended: true,
  },
  {
    id: 'local_quick',
    title: '本地 / 自有算力',
    desc: '选 AMD·ROCm 或 NVIDIA·CUDA 节点，不扣云端 credits',
    icon: <Cpu className="h-6 w-6 text-emerald-400" />,
  },
  {
    id: 'expert',
    title: '专家模式',
    desc: '手动选算法和参数',
    icon: <Settings2 className="h-6 w-6 text-muted-foreground" />,
  },
]

export function GoalStep({
  goal,
  goalTouched,
  onSelect,
  qualiaLocked,
  onUpgrade,
  qHours,
  setQHours,
  qInstance,
  setQInstance,
  qInstances,
  costLabel,
  epochs,
  setEpochs,
}: {
  goal: TrainingGoal
  goalTouched: boolean
  onSelect: (g: TrainingGoal) => void
  qualiaLocked: boolean
  onUpgrade: () => void
  qHours: number
  setQHours: (n: number) => void
  qInstance: string
  setQInstance: (s: string) => void
  qInstances: QualiaInstance[]
  costLabel?: string | null
  epochs: number
  setEpochs: (n: number) => void
}) {
  return (
    <div className="space-y-4">
      {!goalTouched && (
        <p className="text-sm text-muted-foreground">点选一种训练方式：</p>
      )}

      <div className="grid gap-3">
        {GOALS.map((g) => {
          const selected = goal === g.id
          const locked = g.id === 'recommended_cloud' && qualiaLocked
          return (
            <Card
              key={g.id}
              className={`cursor-pointer border-2 transition-all ${
                selected && goalTouched ? 'border-primary bg-primary/5' : 'hover:border-primary/40'
              } ${locked ? 'opacity-70' : ''}`}
              onClick={() => !locked && onSelect(g.id)}
            >
              <CardContent className="py-4 flex items-start gap-4">
                {g.icon}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{g.title}</span>
                    {g.recommended && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/20 text-primary">
                        推荐
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">{g.desc}</p>
                  {locked && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="mt-2 h-7 text-xs"
                      onClick={(e) => {
                        e.stopPropagation()
                        onUpgrade()
                      }}
                    >
                      升级后使用云端训练
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      {goalTouched && goal === 'recommended_cloud' && !qualiaLocked && (
        <CloudTrainingOptions
          qHours={qHours}
          setQHours={setQHours}
          qInstance={qInstance}
          setQInstance={setQInstance}
          qInstances={qInstances}
          costLabel={costLabel}
          qualiaLocked={qualiaLocked}
        />
      )}

      {goalTouched && goal === 'local_quick' && (
        <LocalTrainingOptions epochs={epochs} setEpochs={setEpochs} />
      )}
    </div>
  )
}
