import { useCallback, useEffect, useState } from 'react'
import { ChevronRight, Loader2, MapPin } from 'lucide-react'
import { Button } from '../ui/button'
import { B601_ZERO_POSE } from '../../lib/b601Joints'
import {
  b601KinematicsMovePose,
  getB601KinematicsHealth,
  getB601KinematicsReadyPose,
  type ReadyPoseResponse,
} from '../../lib/b601KinematicsApi'
import { getB601Ros2Health } from '../../lib/b601Ros2Api'

/** Official zero / folded pose FK (matches B601_ZERO_POSE). */
const FOLD_ZERO_FALLBACK = { x: 0.302, y: 0, z: 0.218, roll: 0, pitch: 0, yaw: 0 }

type MoveMode = 'preview' | 'live'

interface Props {
  teleopRunning: boolean
  recordRunning: boolean
  busy: boolean
  onBusy: (v: boolean) => void
  onTargetPose?: (pos: [number, number, number] | null) => void
  onPreviewJoints?: (joints: Record<string, number>) => void
  ros2BringupRunning?: boolean
}

export function B601KinematicsTab({
  teleopRunning,
  recordRunning,
  busy,
  onBusy,
  onTargetPose,
  onPreviewJoints,
}: Props) {
  const [kinHealth, setKinHealth] = useState<Awaited<ReturnType<typeof getB601KinematicsHealth>> | null>(null)
  const [readyPose, setReadyPose] = useState<ReadyPoseResponse | null>(null)
  const [moveMode, setMoveMode] = useState<MoveMode>('preview')
  const [seedJoints, setSeedJoints] = useState<Record<string, number>>({ ...B601_ZERO_POSE })
  const [x, setX] = useState(String(FOLD_ZERO_FALLBACK.x))
  const [y, setY] = useState(String(FOLD_ZERO_FALLBACK.y))
  const [z, setZ] = useState(String(FOLD_ZERO_FALLBACK.z))
  const [roll, setRoll] = useState(String(FOLD_ZERO_FALLBACK.roll))
  const [pitch, setPitch] = useState(String(FOLD_ZERO_FALLBACK.pitch))
  const [yaw, setYaw] = useState(String(FOLD_ZERO_FALLBACK.yaw))
  const [msg, setMsg] = useState<string | null>(null)
  const [msgOk, setMsgOk] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const [k] = await Promise.all([getB601KinematicsHealth(), getB601Ros2Health()])
      setKinHealth(k)
      if (k.ready_pose) {
        setReadyPose({ ok: true, ...k.ready_pose })
      } else if (k.pinocchio) {
        try {
          setReadyPose(await getB601KinematicsReadyPose())
        } catch {
          /* offline */
        }
      }
    } catch {
      setKinHealth(null)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const t = setInterval(() => void refresh(), 8000)
    return () => clearInterval(t)
  }, [refresh])

  const blocked = teleopRunning || recordRunning
  const canPreview = !blocked && !busy && Boolean(kinHealth?.pinocchio)
  const canLive = !blocked && !busy && Boolean(kinHealth?.pinocchio && kinHealth?.sdk)
  const canRun = moveMode === 'preview' ? canPreview : canLive

  const applyFoldZero = () => {
    const rp = readyPose
    const joints = rp?.joints ?? B601_ZERO_POSE
    const pos = rp?.position ?? [FOLD_ZERO_FALLBACK.x, FOLD_ZERO_FALLBACK.y, FOLD_ZERO_FALLBACK.z]
    const ori = rp?.orientation ?? [FOLD_ZERO_FALLBACK.roll, FOLD_ZERO_FALLBACK.pitch, FOLD_ZERO_FALLBACK.yaw]
    setSeedJoints({ ...joints, joint7: 0 })
    setX(String(Number(pos[0].toFixed(3))))
    setY(String(Number(pos[1].toFixed(3))))
    setZ(String(Number(pos[2].toFixed(3))))
    setRoll(String(Number(ori[0].toFixed(3))))
    setPitch(String(Number(ori[1].toFixed(3))))
    setYaw(String(Number(ori[2].toFixed(3))))
    onTargetPose?.([pos[0], pos[1], pos[2]])
    onPreviewJoints?.({ ...joints, joint7: joints.joint7 ?? 0 })
    setMsg('已设为折叠零位（与下方「零点姿态」相同），上方 3D 会跟着动')
    setMsgOk(true)
  }

  const runMove = async () => {
    const position = [parseFloat(x), parseFloat(y), parseFloat(z)]
    const orientation = [parseFloat(roll), parseFloat(pitch), parseFloat(yaw)]
    if (position.some((v) => Number.isNaN(v))) {
      setMsg('坐标填错了，请检查数字')
      setMsgOk(false)
      return
    }
    if (moveMode === 'live') {
      if (!window.confirm('从臂将自动走到目标位置，请确认周围无人无物。继续？')) {
        return
      }
    }
    onTargetPose?.(position as [number, number, number])
    onBusy(true)
    setMsg(null)
    const dryRun = moveMode === 'preview'
    try {
      await b601KinematicsMovePose({
        position,
        orientation,
        q_seed: seedJoints,
        dry_run: dryRun,
        duration: 2.0,
      })
      setMsgOk(true)
      setMsg(
        dryRun
          ? '试算成功：这个折叠零位是够得着的（臂未动）'
          : '从臂已移动到目标附近',
      )
    } catch (e) {
      setMsgOk(false)
      const raw = e instanceof Error ? e.message : '失败'
      setMsg(
        raw.includes('IK') || raw.includes('收敛') || raw.includes('够不着')
          ? '试算失败 — 请先点「折叠零位」再试；若仍失败，把从臂手动摆到折叠姿势后点「读取从臂」'
          : raw.includes('409') || raw.includes('遥操')
            ? '请先停止遥操或录数据'
            : raw,
      )
    } finally {
      onBusy(false)
    }
  }

  const statusLine = !kinHealth?.pinocchio
    ? { tone: 'warn' as const, text: '自动到位尚未装好 — 请联系管理员' }
    : !kinHealth.sdk
      ? { tone: 'info' as const, text: '可以试算；真机自动走过去还需机械臂驱动' }
      : { tone: 'ok' as const, text: '已就绪' }

  return (
    <div className="space-y-4 text-xs">
      <div>
        <h3 className="text-sm font-medium text-foreground">自动到位</h3>
        <p className="mt-1 text-muted-foreground leading-relaxed">
          让从臂<strong className="font-medium text-foreground/90">自己走到指定姿势</strong>。
          跟着主臂动请用「遥操」。手推着玩请用同页「手推漂浮」。
        </p>
      </div>

      <div
        className={`rounded-md border px-3 py-2 leading-relaxed ${
          statusLine.tone === 'ok'
            ? 'border-emerald-500/30 bg-emerald-950/20 text-emerald-100'
            : statusLine.tone === 'warn'
              ? 'border-amber-500/30 bg-amber-950/20 text-amber-100'
              : 'border-sky-500/30 bg-sky-950/20 text-sky-100'
        }`}
      >
        {statusLine.text}
      </div>

      {blocked && (
        <p className="text-amber-200/90">遥操或录数据进行中 — 请先停止。</p>
      )}

      <div className="space-y-2">
        <div className="flex flex-col gap-1.5">
          <label className="flex cursor-pointer items-start gap-2 rounded-md border border-white/10 bg-black/20 px-3 py-2 has-[:checked]:border-primary/40 has-[:checked]:bg-primary/10">
            <input
              type="radio"
              name="b601-move-mode"
              className="mt-0.5"
              checked={moveMode === 'preview'}
              onChange={() => setMoveMode('preview')}
            />
            <span>
              <span className="font-medium text-foreground">先试算（推荐）</span>
              <span className="mt-0.5 block text-muted-foreground">只检查能不能到，臂不动</span>
            </span>
          </label>
          <label className="flex cursor-pointer items-start gap-2 rounded-md border border-white/10 bg-black/20 px-3 py-2 has-[:checked]:border-primary/40 has-[:checked]:bg-primary/10">
            <input
              type="radio"
              name="b601-move-mode"
              className="mt-0.5"
              checked={moveMode === 'live'}
              onChange={() => setMoveMode('live')}
            />
            <span>
              <span className="font-medium text-foreground">真机走过去</span>
              <span className="mt-0.5 block text-muted-foreground">电机会转</span>
            </span>
          </label>
        </div>
      </div>

      <Button size="sm" variant="outline" className="w-full" onClick={applyFoldZero}>
        <MapPin className="mr-1.5 h-3.5 w-3.5" />
        折叠零位（= 零点姿态）
      </Button>

      <Button size="sm" className="w-full" disabled={!canRun} onClick={() => void runMove()}>
        {busy ? (
          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
        ) : (
          <ChevronRight className="mr-1.5 h-3.5 w-3.5" />
        )}
        {moveMode === 'preview' ? '试算折叠零位' : '走到折叠零位'}
      </Button>

      {msg && (
        <p className={msgOk ? 'text-muted-foreground leading-relaxed' : 'text-amber-200/90 leading-relaxed'}>
          {msg}
        </p>
      )}

      <details className="rounded-md border border-white/10 bg-black/20 px-3 py-2">
        <summary className="cursor-pointer text-muted-foreground">进阶：手动改坐标</summary>
        <div className="mt-3 grid grid-cols-3 gap-2">
          {(
            [
              ['前 x', x, setX],
              ['左 y', y, setY],
              ['高 z', z, setZ],
              ['滚转', roll, setRoll],
              ['俯仰', pitch, setPitch],
              ['偏航', yaw, setYaw],
            ] as const
          ).map(([label, val, set]) => (
            <label key={label} className="space-y-0.5">
              <span className="text-muted-foreground">{label}</span>
              <input
                className="w-full rounded border border-white/10 bg-black/30 px-2 py-1 text-foreground"
                value={val}
                onChange={(e) => set(e.target.value)}
              />
            </label>
          ))}
        </div>
      </details>
    </div>
  )
}
