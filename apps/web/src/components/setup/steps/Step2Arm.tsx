/**
 * Arm picker used by the SO-101 connection stage.
 *
 * 默认路径只做三件事：扫描串口、测试端口、指派主控臂/执行臂。
 * 标定和排障仍然保留，但放在折叠区里，避免新手一进来就被细节淹没。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  Cable,
  Check,
  ChevronDown,
  CircleDot,
  FolderOpen,
  Loader2,
  RefreshCw,
  Wand2,
  Zap,
  ZapOff,
} from 'lucide-react'
import { Button } from '../../ui/button'
import { cn } from '../../../lib/utils'
import { agentFetch, agentWsUrl } from '../../../lib/localAgent'
import type { PortsResponse, WiggleResponse } from '../../../lib/setup-types'
import { SetupStepCard } from '../SetupStepCard'
import { useSetup } from '../SetupProvider'

type PortEntry = PortsResponse['ports'][number]

interface PortWiggleState {
  status: 'idle' | 'running' | 'done' | 'error'
  message: string | null
  voltage: number | null
}

interface AutoStatus {
  running: boolean
  returncode?: number | null
  synced_to_so101?: boolean
  log_tail?: string[]
  last_error?: string | null
}

type CalRole = 'follower' | 'leader'

const ROLE_META: Record<
  CalRole,
  { category: 'robots' | 'teleoperators'; robotType: string; label: string }
> = {
  follower: { category: 'robots', robotType: 'so101_follower', label: '执行臂' },
  leader: { category: 'teleoperators', robotType: 'so101_leader', label: '主控臂' },
}

interface Step2ArmProps {
  embedded?: boolean
}

export function Step2Arm({ embedded = false }: Step2ArmProps = {}) {
  const { state, setFollowerPort, setLeaderPort, goNext } = useSetup()
  const [ports, setPorts] = useState<PortEntry[] | null>(null)
  const [scanning, setScanning] = useState(false)
  const [scanErr, setScanErr] = useState<string | null>(null)
  const [wiggles, setWiggles] = useState<Record<string, PortWiggleState>>({})
  const firstLoad = useRef(true)

  const followerPort = state.followerPort?.port ?? null
  const leaderPort = state.leaderPort?.port ?? null

  const doScan = useCallback(async () => {
    setScanning(true)
    setScanErr(null)
    try {
      const r = await agentFetch('/api/setup/ports')
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const body = (await r.json()) as PortsResponse
      setPorts(body.ports)
    } catch (e) {
      setScanErr((e as Error).message)
    } finally {
      setScanning(false)
    }
  }, [])

  useEffect(() => {
    if (firstLoad.current) {
      firstLoad.current = false
      void doScan()
    }
  }, [doScan])

  const doWiggle = useCallback(async (port: string) => {
    setWiggles((prev) => ({
      ...prev,
      [port]: { status: 'running', message: null, voltage: null },
    }))
    try {
      const r = await agentFetch('/api/setup/wiggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ port, offset_ticks: 200, cycles: 3 }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const body = (await r.json()) as WiggleResponse
      setWiggles((prev) => ({
        ...prev,
        [port]: {
          status: body.ok ? 'done' : 'error',
          message: body.message,
          voltage: body.present_voltage_v,
        },
      }))
    } catch (e) {
      setWiggles((prev) => ({
        ...prev,
        [port]: { status: 'error', message: (e as Error).message, voltage: null },
      }))
    }
  }, [])

  const pickFollower = useCallback(
    (p: PortEntry) => {
      setFollowerPort({
        port: p.port,
        motorCount: p.motor_count,
        looksLikeFeetech: p.looks_like_feetech,
      })
      if (ports && !leaderPort) {
        const other = ports.find((q) => q.port !== p.port && q.looks_like_feetech)
        if (other) {
          setLeaderPort({
            port: other.port,
            motorCount: other.motor_count,
            looksLikeFeetech: other.looks_like_feetech,
          })
        }
      }
    },
    [leaderPort, ports, setFollowerPort, setLeaderPort],
  )

  const pickLeader = useCallback(
    (p: PortEntry) => {
      setLeaderPort({
        port: p.port,
        motorCount: p.motor_count,
        looksLikeFeetech: p.looks_like_feetech,
      })
      if (ports && !followerPort) {
        const other = ports.find((q) => q.port !== p.port && q.looks_like_feetech)
        if (other) {
          setFollowerPort({
            port: other.port,
            motorCount: other.motor_count,
            looksLikeFeetech: other.looks_like_feetech,
          })
        }
      }
    },
    [followerPort, ports, setFollowerPort, setLeaderPort],
  )

  const canProceed = followerPort !== null && leaderPort !== null

  const body = (
    <>
      {scanErr && (
        <div className="flex items-center gap-2 rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-300">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>扫描串口失败：{scanErr}</span>
        </div>
      )}

      {scanning && !ports && (
        <div className="flex items-center gap-2 text-sm text-[hsl(var(--muted-foreground))]">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>正在扫描串口…</span>
        </div>
      )}

      {ports && ports.length === 0 && (
        <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-300">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <div className="space-y-1">
            <div>没找到串口设备。</div>
            <div className="text-xs text-amber-300/80">
              确认 SO-101 的 USB 线插好，然后点「重新扫描」。
            </div>
          </div>
        </div>
      )}

      {ports && ports.length > 0 && (
        <div className="grid gap-2.5">
          {ports.map((p) => {
            const w = wiggles[p.port] ?? {
              status: 'idle' as const,
              message: null,
              voltage: null,
            }
            const isFollower = p.port === followerPort
            const isLeader = p.port === leaderPort
            const canWiggle = p.looks_like_feetech && w.status !== 'running'

            return (
              <div
                key={p.port}
                className={cn(
                  'rounded-lg border p-3 transition-colors',
                  isFollower
                    ? 'border-[hsl(var(--primary))]/60 bg-[hsl(var(--primary))]/10'
                    : isLeader
                      ? 'border-sky-500/40 bg-sky-500/5'
                      : 'border-[hsl(var(--border))]/60 bg-[hsl(var(--card))]/40',
                )}
              >
                <div className="flex items-start gap-3">
                  <Cable className="h-5 w-5 mt-0.5 text-[hsl(var(--primary))] shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-sm font-medium">{p.port}</span>
                      {isFollower && (
                        <span className="inline-flex items-center gap-1 rounded-full border border-[hsl(var(--primary))]/60 bg-[hsl(var(--primary))]/20 px-2 py-0.5 text-[10px] font-medium text-[hsl(var(--primary))]">
                          <Zap className="h-3 w-3" />
                          执行臂
                        </span>
                      )}
                      {isLeader && (
                        <span className="inline-flex items-center gap-1 rounded-full border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-[10px] font-medium text-sky-300">
                          <ZapOff className="h-3 w-3" />
                          主控臂
                        </span>
                      )}
                      {!isFollower && !isLeader && p.looks_like_feetech && (
                        <span className="text-[10px] text-emerald-300/80">
                          识别到 {p.motor_count} 个舵机
                        </span>
                      )}
                      {w.voltage != null && (
                        <span className="text-[10px] text-[hsl(var(--muted-foreground))]">
                          当前电压 {w.voltage.toFixed(1)}V
                          {w.voltage >= 10.5 && (
                            <span className="ml-1 text-emerald-400/80">（像执行臂）</span>
                          )}
                          {w.voltage < 10.5 && (
                            <span className="ml-1 text-sky-300/80">（像主控臂）</span>
                          )}
                        </span>
                      )}
                    </div>
                    {p.error && <div className="text-xs text-red-300 mt-1">{p.error}</div>}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => doWiggle(p.port)}
                      disabled={!canWiggle}
                      title="让这个端口的夹爪晃几下，看是哪个臂"
                    >
                      {w.status === 'running' ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Wand2 className="h-3.5 w-3.5" />
                      )}
                      测试端口
                    </Button>
                  </div>
                </div>

                {w.status === 'running' && (
                  <div className="mt-2 rounded-md px-2.5 py-1.5 text-xs bg-[hsl(var(--muted))]/30 text-[hsl(var(--muted-foreground))]">
                    正在晃动夹爪… 请观察哪个臂动了。
                  </div>
                )}
                {w.status === 'done' && (
                  <div className="mt-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1.5 text-xs text-emerald-200">
                    夹爪动了。请按你看到的结果，把这个端口设为执行臂或主控臂。
                  </div>
                )}
                {w.status === 'error' && w.message && (
                  <div className="mt-2 rounded-md border border-red-500/40 bg-red-500/10 px-2.5 py-1.5 text-xs text-red-200">
                    测试失败：{w.message}
                  </div>
                )}

                <div className="mt-2 flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant={isFollower ? 'default' : 'secondary'}
                    onClick={() => pickFollower(p)}
                    disabled={!p.looks_like_feetech}
                    title="执行臂会接 12V 电源，负责真正执行动作"
                  >
                    <Zap className="h-3.5 w-3.5 mr-1" />
                    {isFollower ? '已设为执行臂' : '这是执行臂'}
                  </Button>
                  <Button
                    size="sm"
                    variant={isLeader ? 'default' : 'secondary'}
                    onClick={() => pickLeader(p)}
                    disabled={!p.looks_like_feetech}
                    title="主控臂由你手动拖动，用来示教动作"
                  >
                    <ZapOff className="h-3.5 w-3.5 mr-1" />
                    {isLeader ? '已设为主控臂' : '这是主控臂'}
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      <div className="rounded-lg border border-[hsl(var(--border))]/40 bg-[hsl(var(--muted))]/20 p-3 text-sm space-y-1.5">
        <div className="text-[11px] uppercase tracking-wide text-[hsl(var(--muted-foreground))]">
          当前指派
        </div>
        <div className="flex items-center gap-2">
          <Zap className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
          <span className="text-xs">执行臂：</span>
          <code className="font-mono text-xs">
            {followerPort ?? '未指派（必填）'}
          </code>
        </div>
        <div className="flex items-center gap-2">
          <ZapOff className="h-3.5 w-3.5 text-sky-300" />
          <span className="text-xs">主控臂：</span>
          <code className="font-mono text-xs">
            {leaderPort ?? '未指派（必填）'}
          </code>
        </div>
      </div>

      <details className="rounded-lg border border-[hsl(var(--border))]/40 bg-[hsl(var(--muted))]/10 px-3 py-2">
        <summary className="cursor-pointer select-none text-xs font-medium text-[hsl(var(--foreground))]">
          标定文件（首次装机或动作不准时再打开）
        </summary>
        <div className="mt-3 space-y-3">
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            可以选择已有标定，或新建自动 / 手动标定。端口会复用上面的主控臂和执行臂指派。
          </p>
        <CalibrationSelector role="follower" port={followerPort} />
        <CalibrationSelector role="leader" port={leaderPort} />
        </div>
      </details>

      <details className="rounded-lg border border-[hsl(var(--border))]/40 bg-[hsl(var(--muted))]/10 px-3 py-2 text-xs text-[hsl(var(--muted-foreground))]">
        <summary className="cursor-pointer select-none font-medium text-[hsl(var(--foreground))]">
          扫不到端口？
        </summary>
        <ul className="list-disc pl-5 pt-2 space-y-1">
          <li>
            USB 插好后应出现 <code>/dev/ttyACM*</code> 或 <code>/dev/ttyUSB*</code>。
          </li>
          <li>
            Linux 下把当前用户加入 <code>dialout</code> 组：
            <code className="ml-1">sudo usermod -aG dialout $USER</code>，然后重登录。
          </li>
          <li>
            端口被占用（比如另一个 teleop 进程）扫描会失败：
            <code className="ml-1">sudo fuser /dev/ttyACM0</code> 看谁占着。
          </li>
        </ul>
      </details>
    </>
  )

  if (embedded) {
    return (
      <section className="rounded-lg border border-[hsl(var(--border))]/60 bg-[hsl(var(--card))]/40 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-medium">2. 识别两只机械臂</h3>
            <p className="text-xs text-[hsl(var(--muted-foreground))]">
              点“测试端口”观察哪只臂动了，再分别设为主控臂和执行臂。
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={doScan} disabled={scanning}>
            <RefreshCw className={cn('h-4 w-4 mr-1', scanning && 'animate-spin')} />
            重新扫描
          </Button>
        </div>
        <div className="mt-4 space-y-6">{body}</div>
      </section>
    )
  }

  return (
    <SetupStepCard
      stepId="connect"
      title="连接机械臂"
      description="测试端口，识别主控臂和执行臂。两个角色都指派完成后，才能进入遥操作试运行。"
      headerExtra={
        <Button variant="outline" size="sm" onClick={doScan} disabled={scanning}>
          <RefreshCw className={cn('h-4 w-4 mr-1', scanning && 'animate-spin')} />
          重新扫描
        </Button>
      }
      nextDisabled={!canProceed}
      nextLabel={canProceed ? '下一步：遥操作试运行' : '请先指派主控臂和执行臂'}
      onNext={goNext}
    >
      {body}
    </SetupStepCard>
  )
}

// ─── CalibrationSelector ──────────────────────────────────────────────────
//
// 一个 role（follower/leader）一个选择器：
//   - 下拉：已有 .json + "+ 新建标定"
//   - 选了文件：什么都不做（只是记一下选择）
//   - 选了 "new"：展开 Manual / Auto 方法切换面板
//
// 端口由父组件传入（来自上面已指派的执行臂 / 主控臂）。

function CalibrationSelector({
  role,
  port,
}: {
  role: CalRole
  port: string | null
}) {
  const meta = ROLE_META[role]
  const [files, setFiles] = useState<string[]>([])
  const [selection, setSelection] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      const r = await agentFetch(
        `/api/calibrate/files?category=${meta.category}&robot_type=${meta.robotType}`,
      )
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const body = (await r.json()) as { ids?: string[] }
      setFiles(body.ids ?? [])
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [meta.category, meta.robotType])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const isNew = selection === '__new__'

  return (
    <div className="rounded-lg border border-[hsl(var(--border))]/60 bg-[hsl(var(--card))]/40 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-medium">
          {meta.label}
          <span className="ml-2 text-[10px] font-normal text-[hsl(var(--muted-foreground))]">
            ({meta.robotType})
          </span>
          {port && (
            <code className="ml-2 rounded bg-[hsl(var(--muted))]/40 px-1.5 py-0.5 font-mono text-[10px]">
              {port}
            </code>
          )}
          {!port && (
            <span className="ml-2 text-[10px] text-amber-400">未指派端口</span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void refresh()}
            disabled={loading}
            title="重新扫描标定文件"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              const path = `~/.cache/huggingface/lerobot/calibration/${meta.category}/${meta.robotType}`
              navigator.clipboard?.writeText(path).catch(() => undefined)
            }}
            title="复制标定文件夹路径"
          >
            <FolderOpen className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <select
        value={selection}
        onChange={(e) => setSelection(e.target.value)}
        className="block w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2 py-1.5 text-xs"
        disabled={loading}
      >
        <option value="">{loading ? '加载中…' : '选择标定文件…'}</option>
        <option value="__new__">+ 新建标定</option>
        {files.map((f) => (
          <option key={f} value={f}>
            {f}.json
          </option>
        ))}
      </select>

      {err && <div className="text-[11px] text-red-400">{err}</div>}

      {selection && !isNew && (
        <div className="flex items-center gap-1.5 rounded-md border border-emerald-500/30 bg-emerald-500/5 px-2 py-1 text-[11px] text-emerald-300">
          <Check className="h-3 w-3" />
          已选用：{selection}.json
        </div>
      )}

      {isNew && (
        <CalibrationMethodPicker
          role={role}
          port={port}
          onSaved={(name) => {
            void refresh().then(() => setSelection(name))
          }}
        />
      )}
    </div>
  )
}

// ─── CalibrationMethodPicker ──────────────────────────────────────────────
//
// "+ 新建标定" 选中后展开。Manual / Auto 切换 + 名称输入 +执行面板。

function CalibrationMethodPicker({
  role,
  port,
  onSaved,
}: {
  role: CalRole
  port: string | null
  onSaved: (name: string) => void
}) {
  const [method, setMethod] = useState<'auto' | 'manual'>('auto')
  const [name, setName] = useState(role === 'follower' ? 'my_follower' : 'my_leader')

  return (
    <div className="space-y-3 rounded-md border border-[hsl(var(--border))]/40 bg-[hsl(var(--muted))]/30 p-3">
      <div className="flex gap-2">
        <Button
          size="sm"
          variant={method === 'auto' ? 'default' : 'outline'}
          onClick={() => setMethod('auto')}
          className="flex-1"
        >
          自动标定
        </Button>
        <Button
          size="sm"
          variant={method === 'manual' ? 'default' : 'outline'}
          onClick={() => setMethod('manual')}
          className="flex-1"
        >
          手动标定
        </Button>
      </div>

      <p className="text-[11px] text-[hsl(var(--muted-foreground))]">
        {method === 'auto'
          ? '让程序自动驱动每个舵机到机械极限，发现 range / homing。约 2 分钟，请保持机械臂周围无阻挡。'
          : '手动两步：先把臂摆到中间位置点 Set Homing，再活动每个关节到极限录制 range。'}
      </p>

      <div className="space-y-1">
        <label className="text-[11px] text-[hsl(var(--muted-foreground))]">
          标定文件名
        </label>
        <input
          className="block w-full rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2 py-1.5 font-mono text-xs"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={role === 'follower' ? 'my_follower' : 'my_leader'}
        />
        <p className="text-[10px] text-[hsl(var(--muted-foreground))]">
          会保存为 <code>{name || '<name>'}.json</code>。
        </p>
      </div>

      {!port && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/5 px-2 py-1.5 text-[11px] text-amber-300">
          请先在上面把这个角色指派到一个串口，再启动标定。
        </div>
      )}

      {method === 'auto' ? (
        <AutoPanel role={role} port={port} name={name} onSaved={onSaved} />
      ) : (
        <ManualPanel role={role} port={port} name={name} onSaved={onSaved} />
      )}
    </div>
  )
}

// ─── AutoPanel ────────────────────────────────────────────────────────────

function AutoPanel({
  role,
  port,
  name,
  onSaved,
}: {
  role: CalRole
  port: string | null
  name: string
  onSaved: (name: string) => void
}) {
  const [status, setStatus] = useState<AutoStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [logsOpen, setLogsOpen] = useState(false)
  const prevRunning = useRef<boolean | null>(null)
  const savedRef = useRef(false)

  // Poll status. Only meaningful when this role's panel is mounted.
  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      try {
        const r = await agentFetch('/api/calibrate/auto/status')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const body = (await r.json()) as AutoStatus
        if (!cancelled) setStatus(body)
      } catch {
        // advisory, don't surface poll errors
      }
    }
    void tick()
    const t = window.setInterval(tick, 1500)
    return () => {
      cancelled = true
      window.clearInterval(t)
    }
  }, [])

  // Detect transition running → not running
  useEffect(() => {
    if (!status) return
    const prev = prevRunning.current
    if (prev === true && status.running === false) {
      if (status.returncode === 0 && !savedRef.current) {
        savedRef.current = true
        onSaved(name)
      }
    }
    prevRunning.current = status.running
  }, [status, name, onSaved])

  const start = async () => {
    if (!port || !name) return
    setBusy(true)
    setErr(null)
    savedRef.current = false
    try {
      const r = await agentFetch('/api/calibrate/auto/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ port, robot_id: name }),
      })
      if (!r.ok) {
        let detail = ''
        try {
          const body = (await r.json()) as {
            detail?:
              | string
              | {
                  code?: string
                  message?: string
                  fix_hint?: string
                  missing?: string[]
                }
          }
          if (typeof body.detail === 'string') {
            detail = body.detail
          } else if (body.detail) {
            if (body.detail.code === 'missing_dependency') {
              const miss = body.detail.missing?.join(', ') ?? 'unknown'
              const hint = body.detail.fix_hint ? `；修复：${body.detail.fix_hint}` : ''
              detail = `缺少依赖：${miss}${hint}`
            } else {
              detail = body.detail.message ?? ''
            }
          }
        } catch {
          detail = await r.text()
        }
        throw new Error(detail || `HTTP ${r.status}`)
      }
      setStatus((await r.json()) as AutoStatus)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const stop = async () => {
    setBusy(true)
    try {
      const r = await agentFetch('/api/calibrate/auto/stop', { method: 'POST' })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setStatus((await r.json()) as AutoStatus)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const running = status?.running === true
  const done = status?.running === false && status?.returncode === 0 && savedRef.current

  return (
    <div className="space-y-2">
      {!running && !done && (
        <Button size="sm" className="w-full" onClick={() => void start()} disabled={busy || !port || !name}>
          启动自动标定
        </Button>
      )}

      {running && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-[hsl(var(--primary))]" />
            <span className="text-xs">标定进行中…</span>
            <Button size="sm" variant="destructive" className="ml-auto" onClick={() => void stop()} disabled={busy}>
              停止
            </Button>
          </div>
          <p className="text-[11px] text-[hsl(var(--muted-foreground))]">
            机械臂会自动运动，请远离工作区。
          </p>
        </div>
      )}

      {status?.log_tail && status.log_tail.length > 0 && (
        <div className="rounded-md border border-[hsl(var(--border))]/40">
          <button
            type="button"
            onClick={() => setLogsOpen((o) => !o)}
            className="flex w-full items-center justify-between px-2 py-1.5 text-[11px] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
          >
            <span>日志（{status.log_tail.length}）</span>
            <ChevronDown
              className={cn('h-3 w-3 transition-transform', logsOpen && 'rotate-180')}
            />
          </button>
          {logsOpen && (
            <pre className="max-h-40 overflow-auto whitespace-pre-wrap border-t border-[hsl(var(--border))]/40 bg-black/40 p-2 text-[10px] text-emerald-300/80">
              {status.log_tail.slice(-20).join('\n')}
            </pre>
          )}
        </div>
      )}

      {done && (
        <div className="flex items-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1.5 text-[11px] text-emerald-200">
          <Check className="h-3.5 w-3.5" />
          自动标定完成并保存为 {name}.json
        </div>
      )}

      {err && <div className="text-[11px] text-red-400">{err}</div>}

      <p className="text-[10px] text-[hsl(var(--muted-foreground))]">
        端口：<code className="font-mono">{port ?? '未指派'}</code> · 角色：{role}
      </p>
    </div>
  )
}

// ─── ManualPanel ──────────────────────────────────────────────────────────
//
// Two-step protocol per backend WS spec at /api/calibrate/manual/ws：
//   1. start (port, device_type, device_id) → connected
//   2. set_homing                          → homing_done
//   3. start_recording                     → recording (server pushes positions)
//   4. stop_recording                      → recording_done
//   5. save                                → saved {path, device_id}

type ManualPhase =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'homing'
  | 'homing_done'
  | 'recording'
  | 'saving'
  | 'saved'
  | 'error'

interface ManualMotorRow {
  pos: number
  min: number
  max: number
}

function ManualPanel({
  role,
  port,
  name,
  onSaved,
}: {
  role: CalRole
  port: string | null
  name: string
  onSaved: (name: string) => void
}) {
  const [phase, setPhase] = useState<ManualPhase>('idle')
  const [err, setErr] = useState<string | null>(null)
  const [motors, setMotors] = useState<string[]>([])
  const [positions, setPositions] = useState<Record<string, ManualMotorRow>>({})
  const [savedPath, setSavedPath] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    return () => {
      const ws = wsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify({ action: 'disconnect' }))
        } catch {
          // ignore
        }
        ws.close()
      }
    }
  }, [])

  const send = (msg: unknown) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify(msg))
  }

  const connect = () => {
    if (!port || !name) return
    setErr(null)
    setPhase('connecting')
    setSavedPath(null)
    setMotors([])
    setPositions({})

    const ws = new WebSocket(agentWsUrl('/api/calibrate/manual/ws'))
    wsRef.current = ws

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          action: 'start',
          port,
          device_type: role,
          device_id: name,
        }),
      )
    }

    ws.onmessage = (ev) => {
      let payload: { type: string; [k: string]: unknown } | null = null
      try {
        payload = JSON.parse(ev.data as string)
      } catch {
        return
      }
      if (!payload) return

      switch (payload.type) {
        case 'connected':
          setMotors((payload.motors as string[]) ?? [])
          setPhase('connected')
          break
        case 'homing_done':
          setPhase('homing_done')
          break
        case 'recording_started':
          setPhase('recording')
          break
        case 'positions': {
          const ms = payload.motors as Record<string, ManualMotorRow> | undefined
          if (ms) setPositions(ms)
          break
        }
        case 'recording_done':
          // Server returned mins/maxes; we can immediately save.
          setPhase('saving')
          send({ action: 'save' })
          break
        case 'saved':
          setSavedPath((payload.path as string | undefined) ?? null)
          setPhase('saved')
          onSaved(name)
          break
        case 'error':
          setErr((payload.message as string | undefined) ?? 'unknown error')
          setPhase('error')
          break
        default:
          break
      }
    }

    ws.onerror = () => {
      setErr('WebSocket connection failed')
      setPhase('error')
    }
    ws.onclose = () => {
      // Don't downgrade phase on close — `saved` / `error` are terminal.
      if (phase === 'connecting' || phase === 'connected' || phase === 'homing' || phase === 'recording' || phase === 'homing_done' || phase === 'saving') {
        setPhase((p) => (p === 'saved' || p === 'error' ? p : 'idle'))
      }
    }
  }

  const setHoming = () => {
    setPhase('homing')
    send({ action: 'set_homing' })
  }
  const startRecording = () => {
    send({ action: 'start_recording' })
  }
  const stopRecording = () => {
    send({ action: 'stop_recording' })
  }
  const reset = () => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ action: 'disconnect' }))
      } catch {
        // ignore
      }
      ws.close()
    }
    wsRef.current = null
    setPhase('idle')
    setErr(null)
    setSavedPath(null)
    setMotors([])
    setPositions({})
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-[11px]">
        <PhaseDot active={phase === 'connected' || phase === 'homing' || phase === 'homing_done'} done={phase === 'recording' || phase === 'saved' || phase === 'saving'} />
        <span>1. 摆到中间位置 → Set Homing</span>
        <div className="ml-2 h-px w-4 bg-[hsl(var(--border))]" />
        <PhaseDot active={phase === 'recording'} done={phase === 'saved'} />
        <span>2. 录制 range</span>
      </div>

      {phase === 'idle' || phase === 'error' ? (
        <Button
          size="sm"
          className="w-full"
          onClick={connect}
          disabled={!port || !name}
        >
          连接 &amp; 开始
        </Button>
      ) : null}

      {phase === 'connecting' && (
        <div className="flex items-center gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
          <Loader2 className="h-3 w-3 animate-spin" />
          连接中…
        </div>
      )}

      {phase === 'connected' && (
        <div className="space-y-2">
          <p className="text-[11px] text-[hsl(var(--muted-foreground))]">
            把机械臂手动摆到 <strong>所有关节的中间位置</strong>，然后点 Set Homing。
          </p>
          <Button size="sm" className="w-full" onClick={setHoming}>
            Set Homing
          </Button>
        </div>
      )}

      {phase === 'homing' && (
        <div className="flex items-center gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
          <Loader2 className="h-3 w-3 animate-spin" />
          正在写入 homing…
        </div>
      )}

      {phase === 'homing_done' && (
        <Button size="sm" className="w-full" onClick={startRecording}>
          开始录制 Range
        </Button>
      )}

      {phase === 'recording' && (
        <div className="space-y-2">
          <p className="text-[11px] text-[hsl(var(--muted-foreground))]">
            手动把每个关节缓慢运动到所有极限，下方实时跟踪 min/current/max。完成后点 Done 保存。
          </p>
          {motors.length > 0 && (
            <div className="overflow-x-auto rounded-md border border-[hsl(var(--border))]/40 bg-black/40">
              <table className="w-full font-mono text-[10px]">
                <thead className="text-emerald-400/70">
                  <tr>
                    <th className="px-2 py-1 text-left">Motor</th>
                    <th className="px-2 py-1 text-right">Min</th>
                    <th className="px-2 py-1 text-right">Current</th>
                    <th className="px-2 py-1 text-right">Max</th>
                  </tr>
                </thead>
                <tbody className="text-emerald-300">
                  {motors.map((m) => {
                    const r = positions[m]
                    return (
                      <tr key={m} className="border-t border-white/5">
                        <td className="px-2 py-1">{m}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{r?.min ?? '—'}</td>
                        <td className="px-2 py-1 text-right tabular-nums font-bold">{r?.pos ?? '—'}</td>
                        <td className="px-2 py-1 text-right tabular-nums">{r?.max ?? '—'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          <Button size="sm" className="w-full" onClick={stopRecording}>
            <Check className="h-3.5 w-3.5 mr-1" />
            完成（保存）
          </Button>
        </div>
      )}

      {phase === 'saving' && (
        <div className="flex items-center gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
          <Loader2 className="h-3 w-3 animate-spin" />
          保存中…
        </div>
      )}

      {phase === 'saved' && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1.5 text-[11px] text-emerald-200">
            <Check className="h-3.5 w-3.5" />
            手动标定已保存
          </div>
          {savedPath && (
            <code className="block break-all rounded bg-[hsl(var(--muted))]/30 px-2 py-1 font-mono text-[10px]">
              {savedPath}
            </code>
          )}
          <Button size="sm" variant="outline" className="w-full" onClick={reset}>
            重新标定
          </Button>
        </div>
      )}

      {err && <div className="text-[11px] text-red-400">手动标定错误：{err}</div>}

      <p className="text-[10px] text-[hsl(var(--muted-foreground))]">
        端口：<code className="font-mono">{port ?? '未指派'}</code> · 角色：{role}
      </p>
    </div>
  )
}

function PhaseDot({ active, done }: { active: boolean; done: boolean }) {
  if (done) return <Check className="h-3 w-3 text-emerald-400" />
  if (active) return <CircleDot className="h-3 w-3 text-[hsl(var(--primary))]" />
  return <CircleDot className="h-3 w-3 text-[hsl(var(--muted-foreground))]/40" />
}
