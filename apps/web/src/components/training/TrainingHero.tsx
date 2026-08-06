import { Link } from 'react-router-dom'
import { Sparkles } from 'lucide-react'
import { Button } from '../ui/button'
import type { WizardStep } from './types'

const SUBTITLE: Record<WizardStep, string> = {
  data: '选一个数据集',
  goal: '选云端或本地，设好参数',
  prepare: '检查环境',
  confirm: '确认后开始',
  running: '训练中…',
  done: '训练完成',
}

export function TrainingHero({
  step,
  token,
}: {
  step: WizardStep
  token: string | null
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/15">
          <Sparkles className="h-5 w-5 text-primary" />
        </div>
        <div>
          <h1 className="text-xl font-bold">训练</h1>
          <p className="text-xs text-muted-foreground">{SUBTITLE[step]}</p>
        </div>
      </div>
      {!token && step !== 'running' && step !== 'done' && (
        <Link to="/login">
          <Button variant="outline" size="sm">登录</Button>
        </Link>
      )}
    </div>
  )
}
