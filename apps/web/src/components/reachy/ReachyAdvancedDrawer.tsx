/**
 * M26 — 高级抽屉.
 *
 * 折叠面板，默认收起。内含：
 *   - Daemon 启停 + 日志 tail
 *   - 录制自定义动作 (start / stop / save)
 *   - goto 滑块 (roll / pitch / yaw / bodyYaw / duration)
 *   - 重力补偿 / 使能 / 禁用
 *
 * 默认新手不会进这里，进来的都是知道自己要做什么的人。
 */
import { useCallback, useEffect, useState } from 'react'
import { Activity, BookOpen, ExternalLink, Loader2, Play, Power, RotateCcw, Square, Save, Trash2 } from 'lucide-react'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import {
  discardReachyRecord,
  getReachyRecordStatus,
  gotoSleep,
  moveGoto,
  restartReachyDaemon,
  setMotorMode,
  startReachyDaemon,
  startReachyRecord,
  stopReachyDaemon,
  stopReachyRecord,
  type ReachyGotoRequest,
  type ReachyMotorMode,
  type ReachyRecordStatus,
} from '../../lib/reachyApi'

interface Props {
  daemonOnline: boolean
}

interface GotoTarget {
  roll: number
  pitch: number
  yaw: number
  bodyYaw: number
  duration: number
}

const DEFAULT_GOTO: GotoTarget = { roll: 0, pitch: 0, yaw: 0, bodyYaw: 0, duration: 1.5 }

export function ReachyAdvancedDrawer({ daemonOnline }: Props) {
  const [gotoTarget, setGotoTarget] = useState<GotoTarget>(DEFAULT_GOTO)
  const [busy, setBusy] = useState<'daemon-start' | 'daemon-stop' | 'daemon-restart' | 'goto' | 'motor' | 'rec-start' | 'rec-stop' | 'rec-save' | 'rec-discard' | null>(null)
  const [record, setRecord] = useState<ReachyRecordStatus | null>(null)
  const [recName, setRecName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const refreshRecord = useCallback(async () => {
    try { setRecord(await getReachyRecordStatus()) } catch { setRecord(null) }
  }, [])

  useEffect(() => {
    let cancelled = false
    const t = window.setTimeout(() => {
      if (cancelled) return
      void refreshRecord()
    }, 0)
    const p = setInterval(() => void refreshRecord(), 2000)
    return () => { cancelled = true; window.clearTimeout(t); clearInterval(p) }
  }, [refreshRecord])

  const handleDaemon = useCallback(async (action: 'start' | 'stop' | 'restart') => {
    setError(null); setMessage(null)
    setBusy(action === 'start' ? 'daemon-start' : action === 'stop' ? 'daemon-stop' : 'daemon-restart')
    try {
      if (action === 'start') await startReachyDaemon(true)
      else if (action === 'stop') await stopReachyDaemon(true)
      else await restartReachyDaemon()
      setMessage(`守护进程 ${action === 'start' ? '启动' : action === 'stop' ? '停止' : '重启'}指令已发送`)
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(null) }
  }, [])

  const handleGoto = useCallback(async () => {
    if (!daemonOnline || busy) return
    setError(null); setMessage('goto 指令已发送')
    setBusy('goto')
    const payload: ReachyGotoRequest = {
      head_pose: {
        roll: gotoTarget.roll,
        pitch: gotoTarget.pitch,
        yaw: gotoTarget.yaw,
      },
      body_yaw: gotoTarget.bodyYaw,
      duration: gotoTarget.duration,
      interpolation: 'minjerk',
    }
    try { await moveGoto(payload) }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(null) }
  }, [busy, daemonOnline, gotoTarget])

  const handleMotor = useCallback(async (mode: ReachyMotorMode) => {
    setError(null); setMessage(null)
    setBusy('motor')
    try {
      await setMotorMode(mode)
      setMessage(`电机模式: ${mode}`)
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(null) }
  }, [])

  const handleRecStart = useCallback(async () => {
    setError(null); setBusy('rec-start')
    try { await startReachyRecord() } catch (e) { setError((e as Error).message) }
    finally { setBusy(null); void refreshRecord() }
  }, [refreshRecord])

  const handleRecStop = useCallback(async () => {
    setError(null); setBusy('rec-stop')
    try { await stopReachyRecord() } catch (e) { setError((e as Error).message) }
    finally { setBusy(null); void refreshRecord() }
  }, [refreshRecord])

  const handleRecSave = useCallback(async () => {
    setError(null); setBusy('rec-save')
    try {
      const name = recName.trim() || `custom_${Date.now()}`
      await stopReachyRecord({ name, display_name: name })
      setRecName('')
      setMessage(`已保存: ${name}`)
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(null); void refreshRecord() }
  }, [recName])

  const handleRecDiscard = useCallback(async () => {
    setError(null); setBusy('rec-discard')
    try { await discardReachyRecord(); setMessage('录制已丢弃') }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(null); void refreshRecord() }
  }, [refreshRecord])

  const recRunning = !!record?.active
  const recPaused = !!record?.captured

  return (
    <div className="space-y-3 text-xs">
      <ReachySpecsPanel />

      {/* Daemon */}
      <Section title="守护进程 (daemon)" icon={<Power className="h-3.5 w-3.5 text-emerald-300" />}>
        <div className="flex items-center gap-1.5">
          <Badge variant="outline" className={`text-[9px] ${daemonOnline ? 'border-emerald-500/40 text-emerald-300' : 'border-red-500/40 text-red-300'}`}>
            {daemonOnline ? '在线' : '离线'}
          </Badge>
          <Button size="sm" variant="outline" className="h-6 text-[10px]" disabled={busy !== null} onClick={() => handleDaemon('start')}>
            {busy === 'daemon-start' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
            启动
          </Button>
          <Button size="sm" variant="outline" className="h-6 text-[10px]" disabled={busy !== null} onClick={() => handleDaemon('stop')}>
            {busy === 'daemon-stop' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Square className="h-3 w-3" />}
            停止
          </Button>
          <Button size="sm" variant="outline" className="h-6 text-[10px]" disabled={busy !== null} onClick={() => handleDaemon('restart')}>
            {busy === 'daemon-restart' ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}
            重启
          </Button>
        </div>
      </Section>

      {/* Recording */}
      <Section title="录制自定义动作" icon={<Activity className="h-3.5 w-3.5 text-sky-300" />}>
        <div className="flex items-center gap-1.5">
          {!recRunning && !recPaused ? (
            <Button size="sm" variant="outline" className="h-6 text-[10px] border-sky-500/40 text-sky-200" disabled={busy !== null || !daemonOnline} onClick={handleRecStart}>
              <Play className="h-3 w-3" /> 开始录制
            </Button>
          ) : (
            <>
              {recRunning && !recPaused && (
                <Button size="sm" variant="outline" className="h-6 text-[10px]" disabled={busy !== null} onClick={handleRecStop}>
                  <Square className="h-3 w-3" /> 停止
                </Button>
              )}
              <Button size="sm" variant="outline" className="h-6 text-[10px] border-emerald-500/40 text-emerald-200" disabled={busy !== null} onClick={handleRecSave}>
                {busy === 'rec-save' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                保存
              </Button>
              <Button size="sm" variant="outline" className="h-6 text-[10px] border-red-500/40 text-red-200" disabled={busy !== null} onClick={handleRecDiscard}>
                <Trash2 className="h-3 w-3" /> 丢弃
              </Button>
            </>
          )}
          <span className="ml-auto text-[10px] text-muted-foreground">
            {recRunning ? '录制中…' : recPaused ? '已暂停' : '待命'}
          </span>
        </div>
        <input
          type="text"
          value={recName}
          onChange={(e) => setRecName(e.target.value)}
          placeholder="动作名 (可选，默认 custom_<时间>)"
          className="mt-1.5 w-full h-7 rounded-md border bg-background px-2 text-[11px] font-mono"
        />
      </Section>

      {/* Goto */}
      <Section title="goto (头部 + 身体)" icon={<RotateCcw className="h-3.5 w-3.5 text-amber-300" />}>
        <div className="space-y-1.5">
          <Slider
            label="roll"
            min={-0.6} max={0.6} step={0.01} value={gotoTarget.roll}
            onChange={(v) => setGotoTarget((g) => ({ ...g, roll: v }))}
          />
          <Slider
            label="pitch"
            min={-0.6} max={0.6} step={0.01} value={gotoTarget.pitch}
            onChange={(v) => setGotoTarget((g) => ({ ...g, pitch: v }))}
          />
          <Slider
            label="yaw"
            min={-0.8} max={0.8} step={0.01} value={gotoTarget.yaw}
            onChange={(v) => setGotoTarget((g) => ({ ...g, yaw: v }))}
          />
          <Slider
            label="bodyYaw"
            min={-1.5} max={1.5} step={0.05} value={gotoTarget.bodyYaw}
            onChange={(v) => setGotoTarget((g) => ({ ...g, bodyYaw: v }))}
          />
          <Slider
            label="duration (s)"
            min={0.3} max={5} step={0.1} value={gotoTarget.duration}
            onChange={(v) => setGotoTarget((g) => ({ ...g, duration: v }))}
          />
          <div className="flex gap-1.5 pt-1">
            <Button size="sm" variant="outline" className="h-7 flex-1 text-[11px]" disabled={busy !== null || !daemonOnline} onClick={handleGoto}>
              {busy === 'goto' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
              发送 goto
            </Button>
            <Button size="sm" variant="ghost" className="h-7 text-[11px]" onClick={() => setGotoTarget(DEFAULT_GOTO)}>
              重置
            </Button>
          </div>
        </div>
      </Section>

      {/* Motor mode */}
      <Section title="电机模式" icon={<Power className="h-3.5 w-3.5 text-purple-300" />}>
        <div className="flex gap-1.5">
          <Button size="sm" variant="outline" className="h-6 text-[10px]" disabled={busy !== null || !daemonOnline} onClick={() => handleMotor('enabled')}>
            使能
          </Button>
          <Button size="sm" variant="outline" className="h-6 text-[10px]" disabled={busy !== null || !daemonOnline} onClick={() => handleMotor('disabled')}>
            禁用
          </Button>
          <Button size="sm" variant="outline" className="h-6 text-[10px]" disabled={busy !== null || !daemonOnline} onClick={() => handleMotor('gravity_compensation')}>
            重力补偿
          </Button>
        </div>
        <div className="mt-1.5 flex gap-1.5">
          <Button size="sm" variant="ghost" className="h-6 text-[10px]" disabled={busy !== null || !daemonOnline} onClick={() => void gotoSleep().catch((e) => setError((e as Error).message))}>
            睡眠
          </Button>
        </div>
        {error && <div className="mt-2 text-[10px] text-red-300">{error}</div>}
        {message && !error && <div className="mt-2 text-[10px] text-emerald-300">{message}</div>}
      </Section>
    </div>
  )
}

function ReachySpecsPanel() {
  return (
    <div className="rounded-md border border-white/5 bg-white/5 px-2 py-1.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
      <BookOpen className="h-3.5 w-3.5 shrink-0 text-violet-300" />
      <span>入门说明在页面顶部（未连接时）。</span>
      <a
        href="https://wiki.seeedstudio.com/cn/reachymini_getting_started/"
        target="_blank"
        rel="noreferrer"
        className="ml-auto inline-flex items-center gap-0.5 text-violet-300 hover:underline shrink-0"
      >
        Seeed Wiki
        <ExternalLink className="h-3 w-3" />
      </a>
    </div>
  )
}

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-md border border-white/5 bg-white/5 p-2">
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-foreground/80">
        {icon}
        {title}
      </div>
      {children}
    </section>
  )
}

function Slider({
  label, min, max, step, value, onChange,
}: {
  label: string
  min: number
  max: number
  step: number
  value: number
  onChange: (v: number) => void
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-16 font-mono text-[10px] text-muted-foreground">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="flex-1"
      />
      <span className="w-12 text-right font-mono text-[10px] text-foreground/70">{value.toFixed(2)}</span>
    </div>
  )
}
