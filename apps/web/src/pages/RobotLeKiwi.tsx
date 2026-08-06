import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowLeft,
  BrainCircuit,
  Camera,
  CheckCircle2,
  CircleDot,
  Database,
  Gamepad2,
  Loader2,
  Radio,
  RefreshCw,
  ShieldAlert,
  Square,
  Wifi,
} from 'lucide-react'
import { Button } from '../components/ui/button'
import { CommunityResources } from '../components/features/CommunityResources'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { LazyUrdfPreview } from '../components/features/LazyUrdfPreview'
import {
  DEFAULT_LEKIWI_HANDSHAKE_PLAN,
  LeKiwiHandshakeProgressCard,
} from '../components/workflow/LeKiwiHandshakeProgressCard'
import {
  emergencyStopLeKiwi,
  getLeKiwiHealth,
  getLeKiwiRecordStatus,
  getLeKiwiTeleopStatus,
  startLeKiwiRecord,
  startLeKiwiTeleop,
  stopLeKiwiRecord,
  stopLeKiwiTeleop,
  type LeKiwiHealth,
  type LeKiwiSessionStatus,
} from '../lib/lekiwiApi'

const LEKIWI_URDF = '/api/urdf/lekiwi/lekiwi.urdf?v=official-cad-1'

function StatusDot({ on }: { on: boolean }) {
  return <span className={`h-2 w-2 rounded-full ${on ? 'bg-emerald-400 shadow-[0_0_10px_#34d399]' : 'bg-slate-600'}`} />
}

function Metric({
  icon: Icon,
  label,
  value,
  ok,
}: {
  icon: typeof Wifi
  label: string
  value: string
  ok: boolean
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/20 p-3">
      <div className="flex items-center justify-between">
        <Icon className="h-4 w-4 text-slate-400" />
        <StatusDot on={ok} />
      </div>
      <p className="mt-3 text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <p className="mt-1 truncate text-xs font-medium text-slate-200">{value}</p>
    </div>
  )
}

export function RobotLeKiwi() {
  const [health, setHealth] = useState<LeKiwiHealth | null>(null)
  const [teleop, setTeleop] = useState<LeKiwiSessionStatus | null>(null)
  const [record, setRecord] = useState<LeKiwiSessionStatus | null>(null)
  const [remoteIp, setRemoteIp] = useState('192.168.1.50')
  const [leaderPort, setLeaderPort] = useState('/dev/ttyACM1')
  const [repoId, setRepoId] = useState('local/lekiwi-handshake')
  const [task, setTask] = useState('与正前方的人握手，然后松开')
  const [episodes, setEpisodes] = useState(20)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [nextHealth, nextTeleop, nextRecord] = await Promise.all([
        getLeKiwiHealth(),
        getLeKiwiTeleopStatus(),
        getLeKiwiRecordStatus(),
      ])
      setHealth(nextHealth)
      setTeleop(nextTeleop)
      setRecord(nextRecord)
      setRemoteIp((current) => (current === '192.168.1.50' ? nextHealth.remote_ip : current))
      setLeaderPort((current) => (current === '/dev/ttyACM1' ? nextHealth.leader_port : current))
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法读取 LeKiwi 状态')
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = window.setInterval(() => void refresh(), 5_000)
    return () => window.clearInterval(timer)
  }, [refresh])

  const act = useCallback(async (name: string, action: () => Promise<unknown>) => {
    setBusy(name)
    setNotice(null)
    setError(null)
    try {
      const result = await action()
      const message = (result as { message?: string })?.message
      if (message) setNotice(message)
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '操作失败')
    } finally {
      setBusy(null)
    }
  }, [refresh])

  const questUrl = useMemo(() => {
    const host = window.location.hostname || '本机 IP'
    return `https://${host}:8002/quest`
  }, [])

  return (
    <div className="container mx-auto px-4 py-6 space-y-5">
      <div className="flex items-center justify-between gap-3">
        <Link to="/robots" className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          机器人目录
        </Link>
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          <span className="rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2.5 py-1 text-emerald-200">
            Runtime available
          </span>
          <span>Official CAD</span>
        </div>
      </div>

      <section className="relative overflow-hidden rounded-3xl border border-white/10 bg-[#080c14]">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_18%_20%,rgba(249,115,22,0.14),transparent_35%),radial-gradient(circle_at_85%_30%,rgba(56,189,248,0.12),transparent_35%)]" />
        <div className="relative grid min-h-[440px] lg:grid-cols-[0.9fr_1.1fr]">
          <div className="flex flex-col justify-between p-7 lg:p-10">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.28em] text-orange-300">
                Mobile manipulation workstation
              </p>
              <h1 className="mt-4 text-4xl font-semibold tracking-tight text-white">LeKiwi</h1>
              <p className="mt-2 text-lg text-slate-300">不是桌面 SO-101，而是一套会移动、会看、会采数据的操作系统。</p>
              <p className="mt-5 max-w-xl text-sm leading-7 text-slate-400">
                6 轴 SO-101 机械臂与三轮 Kiwi 全向底盘共用一条 Feetech STS3215 总线。
                树莓派或 Orin 在机器人端运行 LeKiwi Host，工作区相机与腕部相机通过 ZMQ 回传到 BotverseX。
              </p>
            </div>

            <div className="mt-8 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Metric icon={Wifi} label="Robot host" value={`${remoteIp}:5555`} ok={Boolean(health?.command_reachable)} />
              <Metric icon={Camera} label="Vision stream" value="ZMQ · 5556" ok={Boolean(health?.observations_reachable)} />
              <Metric icon={Gamepad2} label="Teleoperation" value={teleop?.running ? '运行中' : '待机'} ok={Boolean(teleop?.running)} />
              <Metric icon={Database} label="Dataset" value={record?.running ? `${record.episode_current ?? 0}/${record.episode_total ?? episodes}` : repoId} ok={Boolean(record?.running)} />
            </div>
          </div>

          <div className="relative min-h-[360px] border-t border-white/10 lg:border-l lg:border-t-0">
            <LazyUrdfPreview
              urdfUrl={LEKIWI_URDF}
              runtimeId="lekiwi"
              stage
              waitForMeshes
              className="absolute inset-0"
            />
            <div className="pointer-events-none absolute bottom-4 left-4 rounded-full border border-white/10 bg-black/60 px-3 py-1.5 text-[10px] text-slate-300 backdrop-blur">
              官方 LeKiwi CAD · SIGRobotics-UIUC
            </div>
          </div>
        </div>
      </section>

      <CommunityResources
        intro="LeKiwi 是开源移动机械臂（Apache-2.0），社区依托 LeRobot 主社区——问题大多在 LeRobot Discord 的 mobile-so100-arm 频道得到解答。"
        docs={[
          { label: 'LeKiwi 官方仓库（BOM/装配）', url: 'https://github.com/SIGRobotics-UIUC/LeKiwi' },
          { label: 'LeRobot 文档（LeKiwi）', url: 'https://github.com/huggingface/lerobot/blob/main/docs/source/lekiwi.mdx' },
        ]}
        communities={[
          { label: 'LeRobot Discord（mobile-so100-arm 频道）', url: 'https://discord.gg/q8Dzzpym3f' },
          { label: 'HF 博客：LeKiwi + PincOpen 实战', url: 'https://huggingface.co/blog/zuoxingdong/mobile-manipulation-lekiwi-pincopen' },
        ]}
        faqs={[
          {
            q: '局域网设备能随便控制我的 LeKiwi？',
            a: 'LeKiwi host 默认绑定 tcp://*:5555/5556 无鉴权——建议绑到具体 IP 段（社区 issue #890）。',
          },
          {
            q: '控制循环偶发崩溃（There is no status packet!）？',
            a: '是 Feetech 总线瞬态读错误，不是接线问题——开启读重试即可（社区 PR #4207）。',
          },
          {
            q: '校准 leader 前要做什么？',
            a: '先给电机配唯一 ID，否则报 ConnectionError（issue #1042）。',
          },
          {
            q: '连不上树莓派？',
            a: '先 hostname -I 确认 IP、开 SSH；Linux 串口 chmod 666。ROS2 版本组合严格：Pi5=Jazzy / PC=Humble，且要 LD_PRELOAD 环境变量。',
          },
        ]}
      />

      {(error || notice) && (
        <div className={`rounded-xl border px-4 py-3 text-xs ${error ? 'border-red-500/30 bg-red-500/10 text-red-200' : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'}`}>
          {error ?? notice}
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
        <div className="space-y-5">
          <Card className="overflow-hidden bg-card/60">
            <CardHeader className="border-b border-border/70">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Radio className="h-4 w-4 text-orange-400" />
                    01 · 连接机器人端 Host
                  </CardTitle>
                  <CardDescription className="mt-1">
                    在 LeKiwi 的树莓派/Orin 上启动 Host；笔电只保存 IP，不直接抢占舵机串口。
                  </CardDescription>
                </div>
                <Button size="sm" variant="ghost" onClick={() => void refresh()} disabled={busy !== null}>
                  <RefreshCw className={`h-3.5 w-3.5 ${busy ? 'animate-spin' : ''}`} />
                  刷新
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4 pt-5">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1.5 text-xs">
                  <span className="text-muted-foreground">LeKiwi Host IP</span>
                  <input
                    value={remoteIp}
                    onChange={(event) => setRemoteIp(event.target.value)}
                    className="h-10 w-full rounded-lg border border-input bg-background px-3 font-mono text-sm outline-none focus:border-orange-400/60"
                    placeholder="192.168.1.50"
                  />
                </label>
                <label className="space-y-1.5 text-xs">
                  <span className="text-muted-foreground">SO-101 主臂串口</span>
                  <input
                    value={leaderPort}
                    onChange={(event) => setLeaderPort(event.target.value)}
                    className="h-10 w-full rounded-lg border border-input bg-background px-3 font-mono text-sm outline-none focus:border-orange-400/60"
                  />
                </label>
              </div>
              <div className="rounded-xl border border-sky-400/20 bg-sky-400/5 p-3 font-mono text-[11px] leading-6 text-sky-100/80">
                python -m lerobot.robots.lekiwi.lekiwi_host --robot.id=botversex-lekiwi
              </div>
              <div className="grid gap-2 sm:grid-cols-3">
                <div className="flex items-center gap-2 rounded-lg border border-border/70 p-2.5 text-xs">
                  <StatusDot on={Boolean(health?.command_reachable)} /> 命令 5555
                </div>
                <div className="flex items-center gap-2 rounded-lg border border-border/70 p-2.5 text-xs">
                  <StatusDot on={Boolean(health?.observations_reachable)} /> 图像 5556
                </div>
                <div className="flex items-center gap-2 rounded-lg border border-border/70 p-2.5 text-xs">
                  <StatusDot on={Boolean(health?.leader_present)} /> 主臂串口
                </div>
              </div>
              {health?.issues?.length ? (
                <ul className="space-y-1 text-[11px] text-amber-200/80">
                  {health.issues.map((issue) => <li key={issue}>· {issue}</li>)}
                </ul>
              ) : null}
            </CardContent>
          </Card>

          <Card className="bg-card/60">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Gamepad2 className="h-4 w-4 text-orange-400" />
                02 · 移动遥操
              </CardTitle>
              <CardDescription>
                主臂控制机械臂；键盘 W/A/S/D 平移，Z/X 旋转，R/F 调整底盘速度。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-[1fr_auto] gap-3">
                <Button
                  onClick={() => void act('teleop-start', () => startLeKiwiTeleop({ remoteIp, leaderPort }))}
                  disabled={busy !== null || Boolean(teleop?.running)}
                >
                  {busy === 'teleop-start' ? <Loader2 className="h-4 w-4 animate-spin" /> : <CircleDot className="h-4 w-4" />}
                  启动底盘 + 机械臂遥操
                </Button>
                <Button
                  variant="outline"
                  onClick={() => void act('teleop-stop', stopLeKiwiTeleop)}
                  disabled={busy !== null || !teleop?.running}
                >
                  <Square className="h-4 w-4" />
                  停止
                </Button>
              </div>
              <div className="rounded-xl border border-violet-400/20 bg-violet-400/5 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-medium text-violet-100">Quest 2/3 空间遥操</p>
                    <p className="mt-1 text-[11px] text-violet-200/60">头显负责空间输入，机器人 Host 仍负责硬件安全与相机流。</p>
                  </div>
                  <code className="hidden rounded bg-black/35 px-2 py-1 text-[10px] text-violet-100 sm:block">{questUrl}</code>
                </div>
              </div>
              <Button
                variant="destructive"
                className="w-full"
                onClick={() => void act('emergency', emergencyStopLeKiwi)}
                disabled={busy !== null}
              >
                <ShieldAlert className="h-4 w-4" />
                停止本地会话并触发 Host watchdog
              </Button>
            </CardContent>
          </Card>

          <Card className="bg-card/60">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Database className="h-4 w-4 text-orange-400" />
                03 · 录制应用场景
              </CardTitle>
              <CardDescription>不是为了“凑集数”，而是围绕场景变量采集可泛化的数据。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1.5 text-xs">
                  <span className="text-muted-foreground">LeRobot 数据集</span>
                  <input value={repoId} onChange={(event) => setRepoId(event.target.value)} className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none" />
                </label>
                <label className="space-y-1.5 text-xs">
                  <span className="text-muted-foreground">本轮集数</span>
                  <input type="number" min={1} max={500} value={episodes} onChange={(event) => setEpisodes(Number(event.target.value))} className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none" />
                </label>
              </div>
              <label className="block space-y-1.5 text-xs">
                <span className="text-muted-foreground">场景任务</span>
                <input value={task} onChange={(event) => setTask(event.target.value)} className="h-10 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none" />
              </label>
              <div className="grid grid-cols-[1fr_auto] gap-3">
                <Button
                  onClick={() => void act('record-start', () => startLeKiwiRecord({ remoteIp, leaderPort, repoId, task, episodes }))}
                  disabled={busy !== null || Boolean(record?.running)}
                >
                  {busy === 'record-start' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Database className="h-4 w-4" />}
                  开始录制
                </Button>
                <Button variant="outline" onClick={() => void act('record-stop', stopLeKiwiRecord)} disabled={busy !== null || !record?.running}>
                  <Square className="h-4 w-4" />
                  结束
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-5">
          <Card className="overflow-hidden border-orange-400/20 bg-gradient-to-b from-orange-500/10 to-card/60">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <BrainCircuit className="h-4 w-4 text-orange-400" />
                场景 → 数据 → 大脑 → 再部署
              </CardTitle>
              <CardDescription>
                握手只是第一个可验证场景。每达到一层覆盖度，自动计算 norm stats、续训并部署到用户选择的算力节点。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <LeKiwiHandshakeProgressCard
                plan={DEFAULT_LEKIWI_HANDSHAKE_PLAN}
                repoId={repoId}
              />
            </CardContent>
          </Card>

          <Card className="bg-card/60">
            <CardHeader>
              <CardTitle className="text-sm">真实系统边界</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-xs text-muted-foreground">
              <div className="flex gap-3">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                <p><strong className="text-foreground">机器人端：</strong>舵机、双相机、500ms watchdog，由 Raspberry Pi/Orin 上的 LeKiwi Host 管理。</p>
              </div>
              <div className="flex gap-3">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                <p><strong className="text-foreground">本地端：</strong>主臂、键盘/Quest、录制会话与网页工作台。</p>
              </div>
              <div className="flex gap-3">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                <p><strong className="text-foreground">算力端：</strong>可以是本机 GPU、远程工作站或云节点，不把 GB10 写死成产品前提。</p>
              </div>
              <div className="flex gap-3">
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
                <p><strong className="text-foreground">实体急停：</strong>远程网页只能停止命令并依赖 watchdog；真正断扭矩必须通过机器人实体急停或断电。</p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
