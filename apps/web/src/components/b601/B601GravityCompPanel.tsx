import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Hand, Loader2, Square } from 'lucide-react'
import { Button } from '../ui/button'
import { getB601Joints } from '../../lib/b601Api'
import { b601DefaultJointPose, b601MotorJointsForViewer, b601MotorRadToUrdf } from '../../lib/b601Joints'
import {
  b601GravityCompStart,
  b601GravityCompStatus,
  b601GravityCompStop,
} from '../../lib/b601Ros2Api'

interface Props {
  busy: boolean
  teleopRunning: boolean
  /** CAN 已通（不必等 7/7 电机） */
  canLinked?: boolean
  onBusy: (v: boolean) => void
  onMotorBaseline?: (raw: Record<string, number> | null) => void
  onDisplayJoints?: (joints: Record<string, number>) => void
  onRunningChange?: (running: boolean) => void
}

export function B601GravityCompPanel({
  busy,
  teleopRunning,
  canLinked = false,
  onBusy,
  onMotorBaseline,
  onDisplayJoints,
  onRunningChange,
}: Props) {
  const [running, setRunning] = useState(false)
  const [mode, setMode] = useState<'basic' | 'lock'>('basic')
  const [gain2, setGain2] = useState('1.0')
  const [gain3, setGain3] = useState('1.0')
  const [msg, setMsg] = useState<string | null>(null)

  const poll = useCallback(async () => {
    try {
      const s = await b601GravityCompStatus()
      const on = Boolean(s.running)
      setRunning(on)
      onRunningChange?.(on)
    } catch {
      /* offline */
    }
  }, [onRunningChange])

  useEffect(() => {
    void poll()
    const t = setInterval(() => void poll(), running ? 500 : 3000)
    return () => clearInterval(t)
  }, [poll, running])

  const start = async () => {
    if (
      !window.confirm(
        '开启后从臂会变轻，你可以用手推到任意姿势。\n\n' +
          '「随意手推」：推到哪里就停在哪里。\n' +
          '「松手定住」：你停手后，尽量保持那个姿势。\n\n' +
          '关闭前必须扶住臂！确认开启？',
      )
    ) {
      return
    }
    onBusy(true)
    setMsg(null)
    try {
      // Sync 3D to real arm before MIT enable — avoids "3D shows 0 but arm reads 0.25" confusion.
      try {
        const j = await getB601Joints()
        if (j.joints && Object.keys(j.joints).length >= 3) {
          const raw = { ...j.joints }
          onMotorBaseline?.(raw)
          onDisplayJoints?.(b601MotorRadToUrdf(raw, raw) ?? b601DefaultJointPose())
        }
      } catch {
        /* CAN busy — stream will catch up */
      }
      await b601GravityCompStart({
        mode,
        joint_gains: { 2: parseFloat(gain2) || 1.0, 3: parseFloat(gain3) || 1.0 },
      })
      onRunningChange?.(true)
      setRunning(true)
      setMsg(
        mode === 'basic'
          ? '已开启 — 用手推到哪，臂就停在哪儿（不会自己弹回去）'
          : '已开启 — 推到位松手后会尽量定住；移动中仍会跟手',
      )
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '启动失败')
    } finally {
      onBusy(false)
    }
  }

  const stop = async () => {
    onBusy(true)
    try {
      await b601GravityCompStop()
      onRunningChange?.(false)
      setRunning(false)
      setMsg('已关闭 — 从臂已卸力，请确认它在安全位置')
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '关闭失败')
    } finally {
      onBusy(false)
    }
  }

  return (
    <div className="space-y-3 text-xs border-t border-white/10 pt-3">
      <div>
        <h3 className="text-sm font-medium text-foreground flex items-center gap-1.5">
          <Hand className="h-3.5 w-3.5" />
          手推漂浮（重力补偿）
        </h3>
        <p className="mt-1 text-muted-foreground leading-relaxed">
          抵消重力后，臂变轻好推。<strong className="text-foreground/90">与遥操不能同时开</strong>
          （共用 CAN，二选一）。遥操 = 跟主臂动；手推漂浮 = 用手推从臂玩。
        </p>
        <p className="mt-1 text-[11px] text-muted-foreground/90 leading-relaxed">
          开启前：折叠待命 → 下方「读取从臂」。开启/关闭时电机短促发声（MIT）属正常。
        </p>
      </div>

      <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-950/30 p-2 text-amber-100">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <p>关闭前一只手扶住从臂，再点「关闭并扶住臂」。</p>
      </div>

      {teleopRunning && <p className="text-amber-200">请先停止遥操。</p>}
      {!canLinked && !running && (
        <p className="text-muted-foreground leading-relaxed">
          未检测到 CAN / 从臂 — 面板仍可见；接上并在下方连接面板连好 CAN 后即可开启。
        </p>
      )}

      {!running && (
        <div className="flex flex-col gap-1.5">
          <label className="flex cursor-pointer items-start gap-2 rounded-md border border-white/10 px-3 py-2 has-[:checked]:border-primary/40 has-[:checked]:bg-primary/10">
            <input
              type="radio"
              name="gc-mode"
              className="mt-0.5"
              checked={mode === 'basic'}
              onChange={() => setMode('basic')}
            />
            <span>
              <span className="font-medium text-foreground">随意手推（推荐）</span>
              <span className="mt-0.5 block text-muted-foreground">
                抵消重力，推到哪停哪 — 对应官方 gravity compensation 示例
              </span>
            </span>
          </label>
          <label className="flex cursor-pointer items-start gap-2 rounded-md border border-white/10 px-3 py-2 has-[:checked]:border-primary/40 has-[:checked]:bg-primary/10">
            <input
              type="radio"
              name="gc-mode"
              className="mt-0.5"
              checked={mode === 'lock'}
              onChange={() => setMode('lock')}
            />
            <span>
              <span className="font-medium text-foreground">松手定住（端东西）</span>
              <span className="mt-0.5 block text-muted-foreground">
                手推时跟手；停手后加大刚度，尽量保持该姿势（轻物如空杯可试，重物仍会下垂）
              </span>
            </span>
          </label>
        </div>
      )}

      {running && (
        <p className="rounded-md border border-emerald-500/30 bg-emerald-950/20 px-3 py-2 text-emerald-100">
          运行中 — 可手推从臂；3D 约 60Hz 跟随（请先「读取从臂」对齐零点）
        </p>
      )}

      <div className="flex gap-2">
        {!running ? (
          <Button size="sm" className="flex-1" disabled={busy || teleopRunning || !canLinked} onClick={() => void start()}>
            <Hand className="mr-1 h-3 w-3" />
            开启手推漂浮
          </Button>
        ) : (
          <Button size="sm" variant="destructive" className="flex-1" disabled={busy} onClick={() => void stop()}>
            {busy ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Square className="mr-1 h-3 w-3" />}
            关闭并扶住臂
          </Button>
        )}
      </div>

      <details className="rounded-md border border-white/10 bg-black/20 px-3 py-2">
        <summary className="cursor-pointer text-muted-foreground">进阶：大臂 / 小臂补偿增益</summary>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <label className="space-y-0.5">
            <span className="text-muted-foreground">大臂</span>
            <input
              className="w-full rounded border border-white/10 bg-black/30 px-2 py-1"
              value={gain2}
              onChange={(e) => setGain2(e.target.value)}
            />
          </label>
          <label className="space-y-0.5">
            <span className="text-muted-foreground">小臂</span>
            <input
              className="w-full rounded border border-white/10 bg-black/30 px-2 py-1"
              value={gain3}
              onChange={(e) => setGain3(e.target.value)}
            />
          </label>
        </div>
      </details>

      {msg && <p className="text-muted-foreground leading-relaxed">{msg}</p>}
    </div>
  )
}
