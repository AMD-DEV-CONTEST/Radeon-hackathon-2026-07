/**
 * M23 — Reachy Mini camera panel + head tracker toggle.
 *
 * Shows a live MJPEG preview from /dev/video* (Local Agent cv2.VideoCapture)
 * and a toggle to start the head tracker. When the head tracker is on,
 * the panel displays the latest computed (yaw, pitch) target so the user
 * can see that the robot is following their face.
 *
 * Why this is in BotverseX and not the daemon: Allan fork's daemon does
 * NOT expose HTTP camera endpoints (see M21 appendix C). So the Local
 * Agent owns the cv2.VideoCapture lifecycle and the face-detection loop,
 * POSTing head targets to the daemon `/api/move/set_target`.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  Camera,
  CameraOff,
  Eye,
  Loader2,
  RefreshCw,
} from 'lucide-react'
import { Button } from '../ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card'
import { Badge } from '../ui/badge'
import {
  getReachyHeadTrackerStatus,
  listReachyCameras,
  reachyCameraSnapshotUrl,
  startReachyHeadTracker,
  stopReachyHeadTracker,
  type ReachyCameraDevice,
  type ReachyHeadTrackerStatus,
} from '../../lib/reachyApi'

interface Props {
  daemonOnline: boolean
}

export function ReachyCameraPanel({ daemonOnline }: Props) {
  const [devices, setDevices] = useState<ReachyCameraDevice[]>([])
  const [selectedDevice, setSelectedDevice] = useState<number>(0)
  const [previewOn, setPreviewOn] = useState(false)
  const [tracker, setTracker] = useState<ReachyHeadTrackerStatus | null>(null)
  const [busy, setBusy] = useState<'start' | 'stop' | 'refresh' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [snapshotKey, setSnapshotKey] = useState(0)
  const previewRef = useRef<HTMLImageElement | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const snapshotTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refreshDevices = useCallback(async () => {
    setBusy('refresh')
    try {
      const r = await listReachyCameras()
      setDevices(r.devices || [])
      if (r.devices.length > 0 && !r.devices.some((d) => d.index === selectedDevice)) {
        setSelectedDevice(r.devices[0].index)
      }
    } catch (e) {
      setError(`摄像头列表获取失败：${(e as Error).message}`)
    } finally {
      setBusy(null)
    }
  }, [selectedDevice])

  const refreshTracker = useCallback(async () => {
    try {
      const s = await getReachyHeadTrackerStatus()
      setTracker(s)
    } catch {
      setTracker(null)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const startup = window.setTimeout(() => {
      if (cancelled) return
      void refreshDevices()
      void refreshTracker()
      if (cancelled) return
      pollRef.current = setInterval(() => void refreshTracker(), 1500)
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(startup)
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [refreshDevices, refreshTracker])

  // Refresh the snapshot <img> periodically while preview is on.
  useEffect(() => {
    if (!previewOn) {
      if (snapshotTimerRef.current) clearInterval(snapshotTimerRef.current)
      snapshotTimerRef.current = null
      return
    }
    // Defer the first snapshot key bump so setState is not called synchronously
    // inside the effect body.
    snapshotTimerRef.current = setInterval(() => setSnapshotKey((k) => k + 1), 500)
    return () => {
      if (snapshotTimerRef.current) clearInterval(snapshotTimerRef.current)
      snapshotTimerRef.current = null
    }
  }, [previewOn, selectedDevice])

  const handleStartTracker = useCallback(async () => {
    setBusy('start')
    setError(null)
    try {
      await startReachyHeadTracker(selectedDevice)
      await refreshTracker()
    } catch (e) {
      setError(`启动头部跟踪失败：${(e as Error).message}`)
    } finally {
      setBusy(null)
    }
  }, [refreshTracker, selectedDevice])

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

  if (!daemonOnline) {
    return (
      <Card>
        <CardHeader className="py-3 pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Camera className="h-4 w-4" />
            摄像头与头部跟踪
          </CardTitle>
          <CardDescription className="text-xs">M23 视觉能力</CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          <p className="text-xs text-muted-foreground">
            守护进程未连接，启动后可看摄像头画面并让 Reachy 跟随你的脸。
          </p>
        </CardContent>
      </Card>
    )
  }

  const trackerRunning = !!tracker?.running
  const lastTarget = tracker?.last_target
  // tracker.last_face_at is monotonic seconds from the Local Agent; we use
  // a coarse "did we see a face in the latest status poll" proxy via the
  // last_target being non-null rather than a wall-clock comparison so we
  // do not call Date.now() during render (react-hooks/purity rule).
  const faceDetected = trackerRunning && !!lastTarget

  return (
    <Card>
      <CardHeader className="py-3 pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Camera className="h-4 w-4" />
          摄像头与头部跟踪
          {trackerRunning && (
            <Badge variant="outline" className="ml-auto border-emerald-500/40 text-emerald-300">
              <Eye className="h-3 w-3 mr-1" /> 跟踪中
            </Badge>
          )}
        </CardTitle>
        <CardDescription className="text-xs">M23 视觉能力</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {/* Device selector + refresh */}
        <div className="flex items-center gap-2">
          <select
            className="h-8 flex-1 rounded-md border bg-background px-2 text-sm"
            value={selectedDevice}
            onChange={(e) => setSelectedDevice(Number(e.target.value))}
            disabled={trackerRunning || busy !== null}
          >
            {devices.length === 0 ? (
              <option value={0}>未检测到摄像头</option>
            ) : (
              devices.map((d) => (
                <option key={d.index} value={d.index}>
                  /dev/video{d.index}
                  {d.width ? ` (${d.width}×${d.height})` : ''}
                  {d.busy ? ' [busy]' : ''}
                </option>
              ))
            )}
          </select>
          <Button
            size="sm"
            variant="outline"
            className="h-8 px-2"
            onClick={() => void refreshDevices()}
            disabled={busy !== null}
          >
            {busy === 'refresh' ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3" />
            )}
          </Button>
        </div>

        {/* Preview */}
        <div className="relative aspect-[4/3] w-full overflow-hidden rounded-md border border-white/10 bg-black">
          {previewOn ? (
            <img
              ref={previewRef}
              src={`${reachyCameraSnapshotUrl(selectedDevice, 480, 360)}&_=${snapshotKey}`}
              alt="Reachy camera preview"
              className="absolute inset-0 h-full w-full object-cover"
              onError={() => {
                // Stop preview on persistent errors.
                setPreviewOn(false)
                setError('摄像头读取失败，预览已停止。')
              }}
            />
          ) : (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-muted-foreground">
              <CameraOff className="h-8 w-8" />
              <span className="text-xs">预览未开启</span>
            </div>
          )}
          {faceDetected && (
            <div className="absolute top-2 left-2 rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] text-emerald-200 flex items-center gap-1">
              <Eye className="h-2.5 w-2.5" /> 检测到脸
            </div>
          )}
        </div>

        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs flex-1"
            onClick={() => setPreviewOn((p) => !p)}
            disabled={busy !== null}
          >
            <Camera className="h-3 w-3" />
            {previewOn ? '关闭预览' : '开启预览'}
          </Button>
        </div>

        {/* Head tracker toggle */}
        <div className="rounded-md border bg-muted/30 p-2.5 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground flex items-center gap-1">
              <Eye className="h-3 w-3" /> 头部跟踪
            </span>
            <span className="text-xs font-mono text-muted-foreground">
              {trackerRunning
                ? `yaw ${lastTarget?.yaw.toFixed(2) ?? '—'} / pitch ${lastTarget?.pitch.toFixed(2) ?? '—'}`
                : 'off'}
            </span>
          </div>
          <div className="flex gap-1.5">
            {!trackerRunning ? (
              <Button
                size="sm"
                className="h-7 text-xs flex-1"
                onClick={handleStartTracker}
                disabled={busy !== null || devices.length === 0}
              >
                {busy === 'start' ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Eye className="h-3 w-3" />
                )}
                启动跟踪
              </Button>
            ) : (
              <Button
                size="sm"
                variant="destructive"
                className="h-7 text-xs flex-1"
                onClick={handleStopTracker}
                disabled={busy !== null}
              >
                {busy === 'stop' ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <CameraOff className="h-3 w-3" />
                )}
                停止跟踪
              </Button>
            )}
          </div>
          {tracker?.last_error && (
            <p className="text-[10px] text-amber-400/80 flex items-start gap-1">
              <AlertTriangle className="h-3 w-3 mt-0.5" />
              <span className="break-words">{tracker.last_error}</span>
            </p>
          )}
          <p className="text-[10px] text-muted-foreground">
            跟踪开启后，Reachy 会用摄像头人脸位置实时调头部 yaw/pitch，跟随你的脸。
          </p>
        </div>

        {error && (
          <div className="rounded-md border border-red-500/30 bg-red-500/5 p-2 text-xs text-red-300 flex items-start gap-2">
            <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
            <span className="break-words">{error}</span>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
