import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  Download,
  Film,
  Loader2,
  Maximize2,
  Minimize2,
  Plus,
  SkipBack,
  SkipForward,
  Square,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { Button } from '../ui/button'
import { ReachyInteractiveViewer } from './ReachyInteractiveViewer'
import {
  composeReachyMove,
  loadReachyMoveJson,
} from '../../lib/reachyApi'
import {
  ANTENNA_LIMIT,
  BODY_YAW_LIMIT,
  NEUTRAL_POSE,
  clampPose,
  createDefaultClip,
  deleteKeyframeAt,
  findKeyframeAt,
  HEAD_LIMIT,
  interpolatePose,
  moveJsonToClip,
  poseToMoveJson,
  upsertKeyframe,
  type ReachyMoveJson,
  type ReachyEditPart,
  type ReachyMotionClip,
  type ReachyPoseFrame,
} from '../../lib/reachyMotionClip'

const PART_LABELS: Record<ReachyEditPart, string> = {
  head: '头部',
  body: '身体',
  leftAntenna: '左天线',
  rightAntenna: '右天线',
}

export interface ReachyMotionEditorProps {
  urdfUrl?: string
  customMoves?: string[]
  onExported?: (result: { move_name: string; display_name?: string; category: string }) => void
  onExit?: () => void
}

const HEAD_AXIS_LABELS = {
  roll: { en: 'Roll', zh: '滚转', hint: '左右倾' },
  pitch: { en: 'Pitch', zh: '俯仰', hint: '点头' },
  yaw: { en: 'Yaw', zh: '偏航', hint: '左右转' },
} as const

function radToDeg(rad: number): string {
  return `${((rad * 180) / Math.PI).toFixed(1)}°`
}

function LabeledRadSlider({
  id,
  label,
  hint,
  value,
  min,
  max,
  step,
  onChange,
  disabled,
}: {
  id: string
  label: string
  hint?: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
  disabled?: boolean
}) {
  const ticks = useMemo(() => {
    const count = 5
    const out: number[] = []
    for (let i = 0; i <= count; i += 1) {
      out.push(min + ((max - min) * i) / count)
    }
    return out
  }, [min, max])

  return (
    <label className="block space-y-1" htmlFor={id}>
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-foreground">
          {label}
          {hint ? <span className="text-muted-foreground ml-1">({hint})</span> : null}
        </span>
        <span className="font-mono text-[11px] text-[hsl(var(--primary))] shrink-0">
          {radToDeg(value)} · {value.toFixed(3)} rad
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        list={`${id}-ticks`}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full"
      />
      <datalist id={`${id}-ticks`}>
        {ticks.map((t) => (
          <option key={t} value={t} label={radToDeg(t)} />
        ))}
      </datalist>
      <div className="flex justify-between text-[10px] text-muted-foreground font-mono px-0.5">
        <span>{radToDeg(min)}</span>
        <span>0</span>
        <span>{radToDeg(max)}</span>
      </div>
    </label>
  )
}

function LabeledTimeSlider({
  id,
  label,
  value,
  min,
  max,
  step,
  onChange,
  disabled,
}: {
  id: string
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
  disabled?: boolean
}) {
  return (
    <label className="block space-y-1" htmlFor={id}>
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono text-[hsl(var(--primary))]">{value.toFixed(1)} s</span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full"
      />
      <div className="flex justify-between text-[10px] text-muted-foreground font-mono">
        <span>{min.toFixed(1)} s</span>
        <span>{max.toFixed(1)} s</span>
      </div>
    </label>
  )
}

function PoseSliders({
  pose,
  selectedPart,
  onChange,
  disabled,
}: {
  pose: ReachyPoseFrame
  selectedPart: ReachyEditPart
  onChange: (pose: ReachyPoseFrame) => void
  disabled?: boolean
}) {
  if (selectedPart === 'head') {
    return (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {(['roll', 'pitch', 'yaw'] as const).map((key) => {
          const meta = HEAD_AXIS_LABELS[key]
          return (
            <LabeledRadSlider
              key={key}
              id={`head-${key}`}
              label={`${meta.zh} ${meta.en}`}
              hint={meta.hint}
              value={pose.head[key]}
              min={-HEAD_LIMIT}
              max={HEAD_LIMIT}
              step={0.01}
              disabled={disabled}
              onChange={(v) => onChange(clampPose({
                ...pose,
                head: { ...pose.head, [key]: v },
              }))}
            />
          )
        })}
      </div>
    )
  }
  if (selectedPart === 'body') {
    return (
      <LabeledRadSlider
        id="body-yaw"
        label="身体偏航 Body Yaw"
        hint="底座左右转"
        value={pose.bodyYaw}
        min={-BODY_YAW_LIMIT}
        max={BODY_YAW_LIMIT}
        step={0.01}
        disabled={disabled}
        onChange={(v) => onChange(clampPose({ ...pose, bodyYaw: v }))}
      />
    )
  }
  const idx = selectedPart === 'leftAntenna' ? 0 : 1
  return (
    <LabeledRadSlider
      id={`antenna-${idx}`}
      label={idx === 0 ? '左天线 Left' : '右天线 Right'}
      hint="天线摆动"
      value={pose.antennas[idx]}
      min={-ANTENNA_LIMIT}
      max={ANTENNA_LIMIT}
      step={0.01}
      disabled={disabled}
      onChange={(v) => {
        const antennas = [...pose.antennas] as [number, number]
        antennas[idx] = v
        onChange(clampPose({ ...pose, antennas }))
      }}
    />
  )
}

function ReachyMotionEditorInner({
  urdfUrl,
  customMoves = [],
  onExported,
  onExit,
}: ReachyMotionEditorProps) {
  const [clip, setClip] = useState<ReachyMotionClip>(() => createDefaultClip(3))
  const [scrubTime, setScrubTime] = useState(0)
  const [selectedPart, setSelectedPart] = useState<ReachyEditPart>('head')
  const [moveName, setMoveName] = useState('新动作')
  const [importName, setImportName] = useState('')
  const [isPreviewing, setIsPreviewing] = useState(false)
  const [previewTime, setPreviewTime] = useState<number | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dockExpanded, setDockExpanded] = useState(true)
  const previewRaf = useRef<number | null>(null)
  const previewStarted = useRef(0)

  const activeKeyframe = useMemo(
    () => findKeyframeAt(clip, scrubTime),
    [clip, scrubTime],
  )

  const editPose = useMemo(() => {
    if (activeKeyframe) return activeKeyframe.pose
    return interpolatePose(clip, scrubTime)
  }, [activeKeyframe, clip, scrubTime])

  const displayPose = useMemo(() => {
    if (previewTime !== null) return interpolatePose(clip, previewTime)
    return editPose
  }, [clip, editPose, previewTime])

  const stopPreview = useCallback(() => {
    if (previewRaf.current !== null) {
      cancelAnimationFrame(previewRaf.current)
      previewRaf.current = null
    }
    setIsPreviewing(false)
    setPreviewTime(null)
  }, [])

  useEffect(() => () => stopPreview(), [stopPreview])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onExit?.()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onExit])

  const handlePoseChange = useCallback((pose: ReachyPoseFrame) => {
    setClip((prev) => upsertKeyframe(prev, scrubTime, pose))
  }, [scrubTime])

  const handleDurationChange = (duration: number) => {
    const d = Math.max(0.5, Math.min(30, duration))
    setClip((prev) => {
      const keys = prev.keyframes.filter((k) => k.t <= d)
      if (!keys.length || keys[0].t > 0) {
        keys.unshift({ t: 0, pose: interpolatePose(prev, 0) })
      }
      if (keys[keys.length - 1].t < d) {
        keys.push({ t: d, pose: interpolatePose(prev, d) })
      }
      keys.sort((a, b) => a.t - b.t)
      return { ...prev, duration: d, keyframes: keys }
    })
    if (scrubTime > d) setScrubTime(d)
  }

  const handleResetPose = () => {
    setClip((prev) => upsertKeyframe(prev, scrubTime, NEUTRAL_POSE))
    setMessage('已重置为中性姿态')
  }

  const handleAddKeyframe = () => {
    setClip((prev) => upsertKeyframe(prev, scrubTime, editPose))
    setMessage(`已在 ${scrubTime.toFixed(1)}s 添加关键帧`)
  }

  const handleDeleteKeyframe = () => {
    if (!activeKeyframe) return
    setClip((prev) => deleteKeyframeAt(prev, activeKeyframe.t))
    setMessage(`已删除 ${activeKeyframe.t.toFixed(1)}s 关键帧`)
  }

  const sortedKeyframes = useMemo(
    () => [...clip.keyframes].sort((a, b) => a.t - b.t),
    [clip.keyframes],
  )

  const jumpKeyframe = (dir: -1 | 1) => {
    if (!sortedKeyframes.length) return
    const current = scrubTime
    if (dir < 0) {
      const prev = [...sortedKeyframes].reverse().find((k) => k.t < current - 0.01)
      setScrubTime(prev ? prev.t : 0)
    } else {
      const next = sortedKeyframes.find((k) => k.t > current + 0.01)
      setScrubTime(next ? next.t : clip.duration)
    }
  }

  const startPreview = () => {
    stopPreview()
    setIsPreviewing(true)
    previewStarted.current = performance.now()
    const tick = () => {
      const elapsed = (performance.now() - previewStarted.current) / 1000
      if (elapsed >= clip.duration) {
        setPreviewTime(clip.duration)
        stopPreview()
        return
      }
      setPreviewTime(elapsed)
      previewRaf.current = requestAnimationFrame(tick)
    }
    previewRaf.current = requestAnimationFrame(tick)
  }

  const handleExport = async () => {
    setBusy('export')
    setError(null)
    setMessage(null)
    try {
      const moveJson = poseToMoveJson(clip, {
        densifyHz: 10,
        description: moveName.trim(),
      })
      const result = await composeReachyMove({
        name: moveName.trim() || `custom_${Date.now()}`,
        display_name: moveName.trim(),
        description: moveJson.description,
        time: moveJson.time,
        set_target_data: moveJson.set_target_data,
      })
      setMessage(`已导出: ${result.display_name ?? result.move_name}`)
      onExported?.(result)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const handleImport = async () => {
    if (!importName.trim()) return
    setBusy('import')
    setError(null)
    try {
      const data = await loadReachyMoveJson('custom', importName.trim())
      const imported = moveJsonToClip(data as ReachyMoveJson)
      setClip(imported)
      setScrubTime(0)
      setMoveName(imported.displayName ?? importName.trim())
      setMessage(`已导入: ${importName.trim()}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const overlay = (
    <div className="fixed inset-0 z-[200] flex flex-col bg-[#070a12]">
      {/* Top bar */}
      <div className="flex shrink-0 items-center gap-3 border-b border-white/10 px-4 py-2 bg-[#0b0f1a]/95">
        <h2 className="text-sm font-semibold">动作编排 · Sim2Real</h2>
        <span className="text-[10px] text-muted-foreground hidden sm:inline">
          滚转/俯仰/偏航 = 头的左右倾、点头、左右转 · 滑块显示角度(°)与弧度(rad)
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-8 text-xs"
            onClick={() => setDockExpanded((v) => !v)}
          >
            {dockExpanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
            {dockExpanded ? '收起操作台' : '展开操作台'}
          </Button>
          <Button size="sm" variant="outline" className="h-8 text-xs" onClick={onExit}>
            <X className="h-3.5 w-3.5" />
            退出 (Esc)
          </Button>
        </div>
      </div>

      {/* 3D viewport — fills remaining space above dock */}
      <div className="relative flex-1 min-h-0">
        <ReachyInteractiveViewer
          urdfUrl={urdfUrl}
          displayPose={displayPose}
          editPose={editPose}
          onPoseChange={handlePoseChange}
          selectedPart={selectedPart}
          className="absolute inset-0 h-full w-full"
          cameraPosition={[0.2, 0.26, 0.36]}
          orbitTarget={[0, 0.11, 0]}
        />
        {isPreviewing && (
          <div className="absolute top-4 left-4 z-10 px-3 py-1.5 rounded-md bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-sm font-mono">
            预览 {(previewTime ?? 0).toFixed(2)}s / {clip.duration.toFixed(1)}s
          </div>
        )}
        <div className="absolute top-4 right-4 z-10 px-2 py-1 rounded bg-black/60 border border-white/10 text-[11px] text-slate-300 max-w-[280px]">
          预览为运动学示意（非物理仿真）：头部 RPY 近似驱动颈部连杆。导出后真机按 head RPY 精确执行。
        </div>
      </div>

      {/* Bottom control dock */}
      {dockExpanded && (
        <div className="shrink-0 max-h-[min(42vh,360px)] overflow-y-auto border-t border-white/10 bg-[#0b0f1a]/98 px-4 py-3 space-y-3">
          <div className="flex flex-wrap gap-1">
            {(Object.keys(PART_LABELS) as ReachyEditPart[]).map((part) => (
              <Button
                key={part}
                size="sm"
                variant={selectedPart === part ? 'default' : 'outline'}
                className="h-8 text-xs"
                onClick={() => setSelectedPart(part)}
                disabled={isPreviewing}
              >
                {PART_LABELS[part]}
              </Button>
            ))}
          </div>

          <PoseSliders
            pose={editPose}
            selectedPart={selectedPart}
            onChange={handlePoseChange}
            disabled={isPreviewing}
          />

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <LabeledTimeSlider
              id="clip-duration"
              label="总时长"
              value={clip.duration}
              min={0.5}
              max={15}
              step={0.1}
              disabled={isPreviewing}
              onChange={handleDurationChange}
            />
            <div className="space-y-1">
              <LabeledTimeSlider
                id="clip-scrub"
                label="时间轴位置"
                value={scrubTime}
                min={0}
                max={clip.duration}
                step={0.1}
                disabled={isPreviewing}
                onChange={setScrubTime}
              />
              <div className="relative h-4 mt-1">
                {sortedKeyframes.map((k) => (
                  <button
                    key={k.t}
                    type="button"
                    title={`${k.t.toFixed(1)}s`}
                    className={`absolute top-0 w-2.5 h-4 -ml-1 rounded-sm ${
                      Math.abs(k.t - scrubTime) < 0.05
                        ? 'bg-[hsl(var(--primary))]'
                        : 'bg-slate-500 hover:bg-slate-300'
                    }`}
                    style={{ left: `${clip.duration > 0 ? (k.t / clip.duration) * 100 : 0}%` }}
                    onClick={() => setScrubTime(k.t)}
                    disabled={isPreviewing}
                  />
                ))}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
            <Button size="sm" variant="outline" onClick={() => jumpKeyframe(-1)} disabled={isPreviewing}>
              <SkipBack className="h-4 w-4" />
            </Button>
            <Button size="sm" variant="outline" onClick={handleResetPose} disabled={isPreviewing}>
              重置姿态
            </Button>
            <Button size="sm" variant="outline" onClick={handleAddKeyframe} disabled={isPreviewing}>
              <Plus className="h-4 w-4" />
              关键帧
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={handleDeleteKeyframe}
              disabled={isPreviewing || !activeKeyframe}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
            <Button size="sm" variant="outline" onClick={() => jumpKeyframe(1)} disabled={isPreviewing}>
              <SkipForward className="h-4 w-4" />
            </Button>
            {isPreviewing ? (
              <Button size="sm" variant="destructive" onClick={stopPreview}>
                <Square className="h-4 w-4" />
                停止
              </Button>
            ) : (
              <Button size="sm" onClick={startPreview}>
                <Film className="h-4 w-4" />
                预览
              </Button>
            )}
            <Button size="sm" variant="secondary" onClick={handleExport} disabled={!!busy || clip.keyframes.length < 2}>
              {busy === 'export' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              导出
            </Button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <input
              type="text"
              className="h-9 w-full rounded-md border bg-background px-2 text-sm"
              placeholder="动作名称，如：转圈"
              value={moveName}
              onChange={(e) => setMoveName(e.target.value)}
              disabled={!!busy}
            />
            <div className="flex gap-2">
              <select
                className="h-9 flex-1 rounded-md border bg-background px-2 text-sm"
                value={importName}
                onChange={(e) => setImportName(e.target.value)}
                disabled={!!busy}
              >
                <option value="">导入 custom 动作…</option>
                {customMoves.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
              <Button size="sm" variant="outline" className="h-9" onClick={handleImport} disabled={!!busy || !importName}>
                {busy === 'import' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              </Button>
            </div>
          </div>

          {message && <p className="text-xs text-emerald-400">{message}</p>}
          {error && <p className="text-xs text-red-400">{error}</p>}
        </div>
      )}
    </div>
  )

  return createPortal(overlay, document.body)
}

export const ReachyMotionEditor = memo(ReachyMotionEditorInner)
