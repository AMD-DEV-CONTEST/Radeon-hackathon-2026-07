/**
 * M26 — 视觉 Tab.
 *
 * 取代旧的 `ReachyCameraPanel`（独立 Card）：把摄像头预览、设备选择、
 * 头部跟踪开关 + DOA 圆盘放在同一处。
 *
 * 预览打开时通过 `onPreviewChange` 通知主区 Stage 显示画中画。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Eye, EyeOff, Loader2, RefreshCw, Camera, CameraOff, Compass } from 'lucide-react'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import {
  getReachyDoA,
  getReachyHeadTrackerStatus,
  listReachyCameras,
  reachyCameraSnapshotUrl,
  startReachyHeadTracker,
  stopReachyHeadTracker,
  type ReachyCameraDevice,
  type ReachyDoAInfo,
  type ReachyHeadTrackerStatus,
} from '../../lib/reachyApi'

interface Props {
  daemonOnline: boolean
  /** Called when the camera preview toggles — parent uses this to show PiP. */
  onPreviewChange?: (state: { on: boolean; device: number; url: string | null }) => void
}

export function ReachyVisionTab({ daemonOnline, onPreviewChange }: Props) {
  const [devices, setDevices] = useState<ReachyCameraDevice[]>([])
  const [selected, setSelected] = useState<number>(0)
  const [previewOn, setPreviewOn] = useState(false)
  const [tracker, setTracker] = useState<ReachyHeadTrackerStatus | null>(null)
  const [doa, setDoa] = useState<ReachyDoAInfo | null>(null)
  const [busy, setBusy] = useState<'start' | 'stop' | 'refresh' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [snapshotKey, setSnapshotKey] = useState(0)
  const [previewError, setPreviewError] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const snapRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Use the shared helper so the URL matches the backend's actual endpoint
  // (`/api/reachy/camera/snapshot?device=N&w=...&h=...`) — NOT
  // `/api/reachy/camera/N/snapshot` which 404s and leaves the PiP as a black box.
  const snapshotUrl = previewOn
    ? `${reachyCameraSnapshotUrl(selected, 480, 360)}&_=${snapshotKey}`
    : null

  const refreshDevices = useCallback(async () => {
    setBusy('refresh')
    try {
      const r = await listReachyCameras()
      setDevices(r.devices || [])
      if (r.devices.length && !r.devices.some((d) => d.index === selected)) {
        setSelected(r.devices[0].index)
      }
    } catch (e) {
      setError(`摄像头列表获取失败：${(e as Error).message}`)
    } finally {
      setBusy(null)
    }
  }, [selected])

  const refreshTracker = useCallback(async () => {
    if (!daemonOnline) {
      setTracker(null)
      setDoa(null)
      return
    }
    try {
      const [t, d] = await Promise.all([
        getReachyHeadTrackerStatus().catch(() => null),
        getReachyDoA().catch(() => null),
      ])
      setTracker(t)
      setDoa(d)
    } catch { /* ignore */ }
  }, [daemonOnline])

  useEffect(() => {
    let cancelled = false
    const t = window.setTimeout(() => {
      if (cancelled) return
      void refreshDevices()
      void refreshTracker()
      // Daemon offline → still poll but much slower (no point hammering 502s).
      pollRef.current = setInterval(() => void refreshTracker(), daemonOnline ? 1500 : 15000)
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(t)
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [refreshDevices, refreshTracker, daemonOnline])

  useEffect(() => {
    if (!previewOn) {
      if (snapRef.current) clearInterval(snapRef.current)
      snapRef.current = null
      setPreviewError(false)
      onPreviewChange?.({ on: false, device: selected, url: null })
      return
    }
    // Bump snapshot key periodically for MJPEG-ish refresh. We DON'T notify
    // the Stage here — the <img> onLoad handler does that only after a frame
    // actually loads, so a broken snapshot URL never produces an empty PiP.
    setPreviewError(false)
    snapRef.current = setInterval(() => setSnapshotKey((k) => k + 1), 500)
    return () => {
      if (snapRef.current) clearInterval(snapRef.current)
      snapRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewOn, selected])

  const handleStartTracker = useCallback(async () => {
    setBusy('start')
    setError(null)
    try {
      await startReachyHeadTracker(selected)
      await refreshTracker()
    } catch (e) {
      setError(`启动头部跟踪失败：${(e as Error).message}`)
    } finally {
      setBusy(null)
    }
  }, [refreshTracker, selected])

  const handleStopTracker = useCallback(async () => {
    setBusy('stop')
    setError(null)
    try {
      await stopReachyHeadTracker()
      await refreshTracker()
    } catch (e) {
      setError(`停止失败：${(e as Error).message}`)
    } finally {
      setBusy(null)
    }
  }, [refreshTracker])

  return (
    <div className="space-y-3">
      {/* Preview + device select */}
      <section className="rounded-md border border-white/10 bg-muted/20">
        <div className="flex items-center justify-between border-b border-white/5 px-2.5 py-1.5">
          <div className="flex items-center gap-1.5 text-xs font-medium">
            <Camera className="h-3.5 w-3.5 text-sky-300" />
            摄像头
          </div>
          <button
            onClick={() => void refreshDevices()}
            className="rounded p-1 text-muted-foreground hover:bg-white/5 hover:text-foreground"
            title="刷新设备"
          >
            <RefreshCw className={`h-3 w-3 ${busy === 'refresh' ? 'animate-spin' : ''}`} />
          </button>
        </div>
        <div className="p-2 space-y-2">
          {devices.length === 0 ? (
            <div className="flex flex-col items-center py-6 text-center text-[11px] text-muted-foreground">
              <CameraOff className="h-5 w-5 text-white/30 mb-1" />
              未检测到摄像头
            </div>
          ) : (
            <>
              <select
                value={selected}
                onChange={(e) => setSelected(Number(e.target.value))}
                disabled={busy !== null}
                className="w-full h-8 rounded-md border bg-background px-2 text-xs"
              >
                {devices.map((d) => (
                  <option key={d.index} value={d.index}>
                    #{d.index} {String(d.name ?? `camera-${d.index}`)}
                  </option>
                ))}
              </select>
              <div className="relative aspect-video w-full overflow-hidden rounded-md border border-white/10 bg-black">
                {previewOn ? (
                  <img
                    src={snapshotUrl ?? undefined}
                    alt="camera preview"
                    className="h-full w-full object-cover"
                    onError={() => {
                      // Snapshot endpoint returned an error (e.g. device busy,
                      // daemon down, or no frame). Stop notifying the Stage so
                      // it doesn't render an empty black PiP box.
                      setPreviewError(true)
                      onPreviewChange?.({ on: false, device: selected, url: null })
                    }}
                    onLoad={() => {
                      if (previewError) setPreviewError(false)
                      onPreviewChange?.({ on: true, device: selected, url: snapshotUrl })
                    }}
                  />
                ) : (
                  <div className="flex h-full items-center justify-center text-[11px] text-muted-foreground">
                    <CameraOff className="h-5 w-5 text-white/30" />
                  </div>
                )}
                {previewOn && previewError && (
                  <div className="absolute inset-0 flex items-center justify-center bg-black/70 text-center text-[11px] text-amber-300">
                    <div className="px-2">
                      无法读取摄像头画面<br />
                      <span className="text-white/50">设备可能被占用或 daemon 离线</span>
                    </div>
                  </div>
                )}
              </div>
              <div className="flex gap-1.5">
                <Button
                  size="sm"
                  variant={previewOn ? 'secondary' : 'outline'}
                  className="h-7 flex-1 text-xs"
                  disabled={!daemonOnline || busy !== null}
                  onClick={() => setPreviewOn((v) => !v)}
                >
                  {previewOn ? '关闭预览' : '开启预览'}
                </Button>
              </div>
            </>
          )}
        </div>
      </section>

      {/* Head tracker */}
      <section className="rounded-md border border-white/10 bg-muted/20">
        <div className="flex items-center justify-between border-b border-white/5 px-2.5 py-1.5">
          <div className="flex items-center gap-1.5 text-xs font-medium">
            <Eye className="h-3.5 w-3.5 text-emerald-300" />
            头部跟踪
          </div>
          <Badge
            variant="outline"
            className={`text-[9px] ${
              tracker?.running
                ? 'border-emerald-500/40 text-emerald-300'
                : 'border-white/20 text-muted-foreground'
            }`}
          >
            {tracker?.running ? `运行中 ${tracker.fps ?? 0}fps` : '未运行'}
          </Badge>
        </div>
        <div className="p-2 space-y-1.5">
          <p className="text-[10px] text-muted-foreground">
            机器人头部跟随摄像头识别到的人脸。
          </p>
          <div className="flex gap-1.5">
            {!tracker?.running ? (
              <Button
                size="sm"
                variant="outline"
                className="h-7 flex-1 text-xs border-emerald-500/40 text-emerald-200"
                onClick={handleStartTracker}
                disabled={!daemonOnline || busy !== null}
              >
                {busy === 'start' ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Eye className="h-3.5 w-3.5" />
                )}
                启动跟踪
              </Button>
            ) : (
              <Button
                size="sm"
                variant="destructive"
                className="h-7 flex-1 text-xs"
                onClick={handleStopTracker}
                disabled={busy !== null}
              >
                <EyeOff className="h-3.5 w-3.5" />
                停止
              </Button>
            )}
          </div>
        </div>
      </section>

      {/* DOA */}
      <section className="rounded-md border border-white/10 bg-muted/20">
        <div className="flex items-center justify-between border-b border-white/5 px-2.5 py-1.5">
          <div className="flex items-center gap-1.5 text-xs font-medium">
            <Compass className="h-3.5 w-3.5 text-amber-300" />
            声源方向 (DOA)
          </div>
          <span className="font-mono text-[10px] text-muted-foreground">
            {doa?.angle != null ? `${doa.angle.toFixed(0)}°` : '—'}
          </span>
        </div>
        <div className="p-2">
          <DoADial directionDeg={doa?.angle ?? null} />
        </div>
      </section>

      {error && (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 p-2 text-xs text-red-200">
          {error}
        </div>
      )}
    </div>
  )
}

function DoADial({ directionDeg }: { directionDeg: number | null }) {
  // Render an SVG circle with a needle pointing to directionDeg (0=front).
  const has = directionDeg != null && !Number.isNaN(directionDeg)
  const angle = has ? directionDeg! : 0
  const cx = 70, cy = 70, r = 50
  const needleEnd = {
    x: cx + Math.sin((angle * Math.PI) / 180) * r * 0.85,
    y: cy - Math.cos((angle * Math.PI) / 180) * r * 0.85,
  }
  return (
    <svg viewBox="0 0 140 140" className="mx-auto h-[120px] w-[120px]">
      <circle cx={cx} cy={cy} r={r} fill="rgba(255,255,255,0.04)" stroke="rgba(255,255,255,0.15)" />
      <text x={cx} y={18} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.5)">前</text>
      <text x={cx} y={132} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.5)">后</text>
      <text x={10} y={cy + 3} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.5)">左</text>
      <text x={130} y={cy + 3} textAnchor="middle" fontSize="9" fill="rgba(255,255,255,0.5)">右</text>
      {has ? (
        <line
          x1={cx}
          y1={cy}
          x2={needleEnd.x}
          y2={needleEnd.y}
          stroke="rgb(251, 191, 36)"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      ) : (
        <text x={cx} y={cy + 3} textAnchor="middle" fontSize="10" fill="rgba(255,255,255,0.3)">无声</text>
      )}
      <circle cx={cx} cy={cy} r="3" fill={has ? 'rgb(251, 191, 36)' : 'rgba(255,255,255,0.3)'} />
    </svg>
  )
}
