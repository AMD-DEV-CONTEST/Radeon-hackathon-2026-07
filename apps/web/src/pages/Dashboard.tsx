import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, buttonVariants } from '../components/ui/button'
import { cn } from '../lib/utils'
import { StatCard } from '../components/features/StatCard'
import { SetupChecklistCard } from '../components/setup/SetupChecklistCard'
import { Card, CardContent } from '../components/ui/card'
import { authJson } from '../lib/auth'
import { listRuntimes } from '../lib/robotApi'
import {
  Bot,
  Database,
  Brain,
  Activity,
  Gamepad2,
  Settings,
  Sparkles,
  Video,
  Rocket,
  Zap,
  Cpu,
} from 'lucide-react'

interface PlatformStats {
  datasets: { total: number; total_frames: number }
  models: { total: number }
  training_jobs: { total: number; running: number; succeeded: number }
  skills: { unique: number }
}

interface RuntimeInfo {
  runtime_id: string
  display_name: string
  joint_count: number
}

export function Dashboard() {
  const [stats, setStats] = useState<PlatformStats | null>(null)
  const [runtimes, setRuntimes] = useState<RuntimeInfo[]>([])
  const [statsLoading, setStatsLoading] = useState(true)
  const [statsError, setStatsError] = useState<string | null>(null)


  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    setStatsError(null)
    try {
      const data = await authJson<PlatformStats>('/api/v1/stats')
      setStats(data)
    } catch (e) {
      setStatsError((e as Error).message)
    } finally {
      setStatsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadStats()

    listRuntimes()
      .then((data) => setRuntimes(data.runtimes || []))
      .catch(() => {})
  }, [loadStats])

  const ds = stats?.datasets ?? { total: 0, total_frames: 0 }
  const md = stats?.models ?? { total: 0 }
  const tj = stats?.training_jobs ?? { total: 0, running: 0, succeeded: 0 }
  const sk = stats?.skills ?? { unique: 0 }

  return (
    <div className="space-y-8">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">欢迎回来</h1>
          <p className="text-muted-foreground mt-1">
            BotverseX 平台总览 — 来自数据库的实时统计。
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/teleop" className={cn(buttonVariants({ variant: 'outline' }), 'gap-2')}>
            <Video className="h-4 w-4" />
            录制
          </Link>
          <Link to="/training" className={cn(buttonVariants({ variant: 'default' }), 'gap-2')}>
            <Brain className="h-4 w-4" />
            训练
          </Link>
        </div>
      </div>

      {statsError && (
        <div className="px-4 py-2 rounded-md bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
          统计不可用：{statsError}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="数据集"
          value={statsLoading ? '…' : ds.total}
          description={statsLoading ? '加载中…' : `${ds.total_frames.toLocaleString()} 帧`}
          icon={Database}
        />
        <StatCard
          title="模型"
          value={statsLoading ? '...' : md.total}
          description={`${tj.succeeded} 个训练成功`}
          icon={Brain}
        />
        <StatCard
          title="训练任务"
          value={statsLoading ? '...' : tj.running}
          description={tj.running > 0 ? '运行中' : `共 ${tj.total} 个`}
          icon={Activity}
          trend={tj.running > 0 ? { value: 100, positive: true } : undefined}
        />
        <StatCard
          title="技能"
          value={statsLoading ? '...' : sk.unique}
          description={`已注册 ${runtimes.length} 个运行时`}
          icon={Zap}
        />
      </div>

      {/* M9.2: SO-101 onboarding readiness — surfaces hardware issues + CTA */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1">
          <SetupChecklistCard />
        </div>
      </div>

      {/* Runtimes */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold flex items-center gap-2">
            <Cpu className="h-5 w-5" />
            已注册运行时
          </h2>
          <Link to="/skills">
            <Button variant="ghost" size="sm">查看全部</Button>
          </Link>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {runtimes.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center text-sm text-muted-foreground">
                未检测到运行时。请确认 realtime 服务（:8002）在运行。
              </CardContent>
            </Card>
          ) : (
            runtimes.map((rt) => (
              <Card key={rt.runtime_id}>
                <CardContent className="p-5">
                  <div className="flex items-center gap-3">
                    <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
                      <Bot className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <h3 className="font-semibold text-sm">{rt.display_name}</h3>
                      <p className="text-xs text-muted-foreground font-mono">{rt.runtime_id} — {rt.joint_count} DoF</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      </section>

      {/* 快捷操作 */}
      <section className="botverse-gradient rounded-2xl p-6">
        <h2 className="text-xl font-semibold text-white mb-4">快捷操作</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <Link
            to="/teleop"
            className={cn(
              buttonVariants({ variant: 'secondary' }),
              'bg-white/10 text-white border-0 hover:bg-white/20',
            )}
          >
            <Video className="h-4 w-4 mr-2" />
            录制
          </Link>
          <Link
            to="/training"
            className={cn(
              buttonVariants({ variant: 'secondary' }),
              'bg-white/10 text-white border-0 hover:bg-white/20',
            )}
          >
            <Brain className="h-4 w-4 mr-2" />
            训练
          </Link>
          <Link to="/teleop" className="w-full">
            <Button
              variant="secondary"
              className="bg-white/10 text-white border-0 hover:bg-white/20 w-full"
            >
              <Gamepad2 className="h-4 w-4 mr-2" />
              遥操
            </Button>
          </Link>
          <Link to="/inference" className="w-full">
            <Button
              variant="secondary"
              className="bg-white/10 text-white border-0 hover:bg-white/20 w-full"
            >
              <Sparkles className="h-4 w-4 mr-2" />
              推理
            </Button>
          </Link>
          <Link to="/ai-hub" className="w-full">
            <Button
              variant="secondary"
              className="bg-white/10 text-white border-0 hover:bg-white/20 w-full"
            >
              <Rocket className="h-4 w-4 mr-2" />
              AI Hub
            </Button>
          </Link>
          <Link to="/skills" className="w-full">
            <Button
              variant="secondary"
              className="bg-white/10 text-white border-0 hover:bg-white/20 w-full"
            >
              <Settings className="h-4 w-4 mr-2" />
              技能
            </Button>
          </Link>
        </div>
      </section>

    </div>
  )
}
