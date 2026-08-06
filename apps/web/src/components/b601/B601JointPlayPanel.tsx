import { useCallback, useEffect, useState } from 'react'
import { Loader2, RotateCcw, ScanLine } from 'lucide-react'
import { Button } from '../ui/button'
import { getB601Joints } from '../../lib/b601Api'
import { B601_ARM_JOINTS, B601_ZERO_POSE, b601DefaultJointPose, b601MotorRadToUrdf } from '../../lib/b601Joints'

interface Props {
  onChange: (joints: Record<string, number>) => void
  /** 从臂 7/7 就绪 */
  hardwareReady?: boolean
  /** CAN 已通即可尝试只读（不必等 7/7） */
  canLinked?: boolean
  teleopRunning?: boolean
  /** 手推漂浮中：滑条只读并跟随真机 */
  gravityCompRunning?: boolean
  /** 遥操 / 手推 / 回放：滑条只读并镜像这些关节 */
  mirrorJoints?: Record<string, number> | null
  /** 「读取从臂」时保存电机原始零点基准，用于 3D 与真机对齐 */
  onMotorBaseline?: (raw: Record<string, number> | null) => void
  /** Collapse body when recording (joint play is secondary). */
  collapsed?: boolean
}

export function B601JointPlayPanel({
  onChange,
  hardwareReady,
  canLinked = false,
  teleopRunning,
  gravityCompRunning = false,
  mirrorJoints,
  onMotorBaseline,
  collapsed = false,
}: Props) {
  const [pose, setPose] = useState(b601DefaultJointPose)
  const [reading, setReading] = useState(false)
  const [readPhase, setReadPhase] = useState<string | null>(null)
  const [readErr, setReadErr] = useState<string | null>(null)
  const [open, setOpen] = useState(!collapsed)

  const canRead = (hardwareReady || canLinked) && !teleopRunning && !gravityCompRunning
  const mirroring = Boolean(mirrorJoints && Object.keys(mirrorJoints).length >= 3)
  const slidersLocked = teleopRunning || gravityCompRunning || reading || mirroring

  useEffect(() => {
    setOpen(!collapsed)
  }, [collapsed])

  useEffect(() => {
    if (!mirrorJoints || Object.keys(mirrorJoints).length < 3) return
    const next = { ...B601_ZERO_POSE }
    for (const joint of B601_ARM_JOINTS) {
      const v = mirrorJoints[joint.id]
      if (typeof v !== 'number' || !Number.isFinite(v)) continue
      // Gripper motor space is often ≤0; slider / URDF want 0..0.05 open.
      if (joint.id === 'joint7') {
        const gAbs = Math.abs(v)
        next.joint7 = gAbs > 0.25 ? Math.min(0.05, (gAbs / 25) * 0.05) : Math.min(0.05, gAbs)
      } else {
        next[joint.id] = v
      }
    }
    setPose(next)
  }, [mirrorJoints])

  // Push pose to parent after commit — never call onChange inside setState updaters.
  useEffect(() => {
    onChange(pose)
  }, [pose, onChange])

  const applyPose = useCallback((next: Record<string, number>) => {
    setPose(next)
  }, [])

  const update = useCallback((id: string, value: number) => {
    setPose((prev) => ({ ...prev, [id]: value }))
  }, [])

  const resetToZero = () => {
    setReadErr(null)
    onMotorBaseline?.(null)
    applyPose(b601DefaultJointPose())
  }

  const readFollowerPose = async () => {
    setReadErr(null)
    setReading(true)
    setReadPhase('正在占用 CAN 并读取 7 个关节（约 15–30 秒，请勿点其他按钮）…')
    try {
      const j = await getB601Joints()
      if (!j.joints || Object.keys(j.joints).length < 3) {
        setReadErr('读不到从臂角度。请确认 CAN 绿灯、从臂已上电，且未在遥操中；等几秒后重试。')
        return
      }
      setReadPhase('已读到数据，正在更新 3D…')
      const next = { ...B601_ZERO_POSE }
      for (const joint of B601_ARM_JOINTS) {
        const v = j.joints[joint.id]
        if (typeof v === 'number' && Number.isFinite(v)) next[joint.id] = v
      }
      onMotorBaseline?.({ ...next })
      applyPose(b601MotorRadToUrdf(next, next) ?? next)
      setReadPhase('读取完成')
    } catch (e) {
      setReadErr(e instanceof Error ? e.message : '读取失败')
    } finally {
      setReading(false)
      window.setTimeout(() => setReadPhase(null), 2500)
    }
  }

  return (
    <div className="space-y-2 rounded-lg border border-white/10 bg-black/25 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <button
          type="button"
          className="min-w-0 flex-1 text-left"
          onClick={() => setOpen((v) => !v)}
        >
          <p className="text-sm font-medium text-foreground/90">
            {teleopRunning || mirroring
              ? '关节同步（只读）'
              : hardwareReady
                ? '拖动关节（3D 预览）'
                : '试玩：拖动关节（仅 3D）'}
            <span className="ml-2 text-[10px] font-normal text-muted-foreground">
              {open ? '收起' : '展开'}
            </span>
          </p>
          <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
            {teleopRunning ? (
              '遥操中 — 数值实时跟从臂，不驱动电机。'
            ) : gravityCompRunning ? (
              '手推漂浮 — 滑条与 3D 实时跟随真机。'
            ) : mirroring ? (
              '回放中'
            ) : (
              <>
                <strong className="font-normal text-amber-200/90">滑条不会驱动从臂电机</strong>
                ，只更新上方模型。动真机请用「开始遥操」。
              </>
            )}
          </p>
        </button>
        {open && (
          <div className="flex shrink-0 flex-wrap gap-1">
            {canRead && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 text-xs"
                disabled={reading}
                onClick={() => void readFollowerPose()}
              >
                {reading ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <ScanLine className="mr-1 h-3 w-3" />}
                {reading ? '读取中…' : '读取从臂'}
              </Button>
            )}
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-8 text-xs"
              disabled={slidersLocked}
              onClick={resetToZero}
            >
              <RotateCcw className="mr-1 h-3 w-3" />
              零点姿态
            </Button>
          </div>
        )}
      </div>

      {open && (
        <>
          {reading && readPhase && (
            <p className="flex items-center gap-2 text-[11px] text-sky-200/90">
              <Loader2 className="h-3 w-3 animate-spin shrink-0" />
              {readPhase}
            </p>
          )}
          {readErr && <p className="text-[11px] text-amber-300/90">{readErr}</p>}

          <div className="grid gap-2 sm:grid-cols-2">
            {B601_ARM_JOINTS.map((j) => {
              const rad = pose[j.id] ?? 0
              const deg = (rad * 180) / Math.PI
              return (
                <label key={j.id} className="flex items-center gap-2 text-[11px]">
                  <span className="w-14 shrink-0 text-muted-foreground">{j.label}</span>
                  <input
                    type="range"
                    min={j.min}
                    max={j.max}
                    step={0.01}
                    value={rad}
                    disabled={slidersLocked}
                    className="min-w-0 flex-1 accent-[hsl(var(--primary))]"
                    onChange={(e) => update(j.id, parseFloat(e.target.value))}
                  />
                  <span className="w-12 shrink-0 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
                    {j.id === 'joint7' ? rad.toFixed(3) : `${deg.toFixed(0)}°`}
                  </span>
                </label>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
