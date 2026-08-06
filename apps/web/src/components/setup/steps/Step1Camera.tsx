/**
 * Camera picker used by the SO-101 connection stage.
 *
 * - Calls GET /api/camera/devices (proxied to realtime :8002) and renders
 *   the list of V4L2 cameras the system actually opened.
 * - Lets the user pick one and preview it live via an <img> tag pointed at
 *   the MJPEG endpoint. A cache-buster query arg forces the <img> to
 *   reconnect whenever the user re-selects a device.
 * - Persist the choice into setup state; later stages will
 *   consume it from the provider instead of asking the user again.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Camera, RefreshCw, WifiOff } from 'lucide-react'
import { Button } from '../../ui/button'
import { cn } from '../../../lib/utils'
import { agentFetch, agentHttpUrl } from '../../../lib/localAgent'
import type { CameraDeviceInfo } from '../../../lib/setup-types'
import { SetupStepCard } from '../SetupStepCard'
import { useSetup } from '../SetupProvider'

interface Step1CameraProps {
  embedded?: boolean
}

export function Step1Camera({ embedded = false }: Step1CameraProps = {}) {
  const { state, setCamera, goNext } = useSetup()
  const [devices, setDevices] = useState<CameraDeviceInfo[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [selected, setSelected] = useState<number | null>(
    state.camera?.deviceIndex ?? null,
  )
  // Bump to force <img> to re-request the MJPEG stream.
  const [streamNonce, setStreamNonce] = useState(0)
  const firstLoad = useRef(true)

  // Extra diagnostics from /api/camera/status so we can distinguish
  // "no /dev/video at all" from "device exists but is busy" and render
  // different hints in each case. Falls back to null on older backends.
  const [status, setStatus] = useState<{
    present_count: number
    usable_count: number
    busy_count: number
    nodes: Array<{ index: number; opened: boolean; readable: boolean; path: string }>
  } | null>(null)

  const commitCamera = useCallback(
    (device: CameraDeviceInfo) => {
      setCamera({
        deviceIndex: device.index,
        label: `Camera ${device.index} (${device.width}x${device.height}@${Math.round(device.fps)})`,
        width: device.width || 640,
        height: device.height || 480,
        fps: Math.round(device.fps) || 30,
      })
    },
    [setCamera],
  )

  const loadDevices = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      // Before probing, drop any stale MJPEG stream we were serving. If a
      // previous record crashed (or the user just came back from recording),
      // the preview <img> may still be frozen on the last frame. Stopping
      // here makes the probe authoritative and the preview truly live.
      await agentFetch('/api/camera/stop_streams', { method: 'POST' }).catch(() => null)
      await new Promise((r) => setTimeout(r, 150))

      // /api/camera/devices is on realtime (:8002) — no auth required.
      // /api/camera/status is only on M12+ realtime; treat 404 as "no extra info".
      const [devResp, statusResp] = await Promise.all([
        agentFetch('/api/camera/devices'),
        agentFetch('/api/camera/status').catch(() => null),
      ])
      if (!devResp.ok) throw new Error(`HTTP ${devResp.status}`)
      const body = (await devResp.json()) as { devices: CameraDeviceInfo[] }
      setDevices(body.devices)
      if (statusResp && statusResp.ok) {
        try {
          setStatus(await statusResp.json())
        } catch {
          setStatus(null)
        }
      } else {
        setStatus(null)
      }

      // Sync selection with reality. Three cases:
      //   a) no usable devices → wipe selection AND clear setup.camera so
      //      recording can't later re-submit a stale index.
      //   b) previously selected index vanished → fall back to the first
      //      available one (do not silently keep a dead index).
      //   c) first-ever render with a single camera → auto-select it.
      if (body.devices.length === 0) {
        setSelected(null)
        if (state.camera !== null) setCamera(null)
      } else if (selected !== null && body.devices.some((d) => d.index === selected)) {
        // keep remembered selection, but still bump the nonce so a
        // re-scan after "force reset" forces a fresh MJPEG connection
        // instead of showing the stale cached frame.
        setStreamNonce((n) => n + 1)
      } else {
        // Fall back to the first usable device (not just when length === 1);
        // handles the index 0→1 hot-swap that bit us in M11 debugging.
        const fallback = body.devices[0].index
        setSelected(fallback)
        if (embedded) commitCamera(body.devices[0])
        // Bump preview nonce so the <img> reconnects to the new device.
        setStreamNonce((n) => n + 1)
      }
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [commitCamera, embedded, selected, state.camera, setCamera])

  // Initial load on mount.
  useEffect(() => {
    if (firstLoad.current) {
      firstLoad.current = false
      void loadDevices()
    }
  }, [loadDevices])

  const selectedDevice = devices?.find((d) => d.index === selected) ?? null

  const handleNext = () => {
    if (!selectedDevice) return
    commitCamera(selectedDevice)
    goNext()
  }

  const body = (
    <>
      {err && (
        <div className="flex items-center gap-2 rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-300">
          <AlertTriangle className="h-4 w-4" />
          <span>无法连接本地实时服务：{err}</span>
        </div>
      )}

      {/* ── Device list ───────────────────────────────────────────────── */}
      <div className="grid gap-2">
        <div className="text-xs font-medium uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
          可用摄像头
        </div>
        {loading && !devices && (
          <div className="text-sm text-[hsl(var(--muted-foreground))]">正在扫描 /dev/video*…</div>
        )}
        {devices && devices.length === 0 && (
          <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-300">
            <WifiOff className="h-4 w-4 mt-0.5 shrink-0" />
            <div className="space-y-1">
              {status && status.busy_count > 0 ? (
                <>
                  <div>
                    <strong>摄像头被占用。</strong>有 {status.busy_count} 个 /dev/video*
                    节点无法打开，通常是浏览器预览、Zoom、OBS 或上次异常退出的录制进程还占着。
                  </div>
                  <div className="text-xs opacity-80">
                    检测到的节点：{' '}
                    {status.nodes
                      .map((n) => `${n.path}${n.opened ? '' : ' (busy)'}`)
                      .join(', ')}
                  </div>
                  <div className="text-xs">
                    关闭其他摄像头应用，或点击{' '}
                    <button
                      type="button"
                      className="underline"
                      onClick={async () => {
                        // Drop preview streams we own.
                        await agentFetch('/api/camera/stop_streams', {
                          method: 'POST',
                        }).catch(() => null)
                        // Force-reset recording state so a
                        // crashed lerobot-record child stops holding cameras
                        // and ports — idempotent and safe when idle.
                        await agentFetch('/api/recording/reset', { method: 'POST' }).catch(
                          () => null,
                        )
                        // Let V4L2 actually release the fd before we
                        // try to re-open it in the probe.
                        await new Promise((r) => setTimeout(r, 250))
                        // Force the <img> to drop its cached frame
                        // so the user sees a real live preview, not a
                        // frozen one.
                        setStreamNonce((n) => n + 1)
                        void loadDevices()
                      }}
                    >
                      强制释放
                    </button>{' '}
                    清理预览流和异常录制资源，然后重新扫描。
                  </div>
                </>
              ) : (
                <span>
                  没有检测到摄像头。插入 USB 摄像头后点击 <strong>重新扫描</strong>。
                </span>
              )}
            </div>
          </div>
        )}
        {devices && devices.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-2">
            {devices.map((d) => {
              const isSelected = d.index === selected
              return (
                <button
                  key={d.index}
                  type="button"
                  onClick={() => {
                    setSelected(d.index)
                    commitCamera(d)
                    setStreamNonce((n) => n + 1)
                  }}
                  className={cn(
                    'flex items-start gap-3 rounded-lg border p-3 text-left transition-colors',
                    isSelected
                      ? 'border-[hsl(var(--primary))]/60 bg-[hsl(var(--primary))]/10'
                      : 'border-[hsl(var(--border))]/60 bg-[hsl(var(--card))]/40 hover:bg-[hsl(var(--muted))]',
                  )}
                >
                  <Camera className="h-5 w-5 mt-0.5 text-[hsl(var(--primary))]" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">
                      {d.path || `/dev/video${d.index}`}
                    </div>
                    <div className="text-xs text-[hsl(var(--muted-foreground))]">
                      {d.width}×{d.height} @ {Math.round(d.fps || 0)}fps · {d.backend}
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {/* ── 实时预览 ─────────────────────────────────────────────────── */}
      {selectedDevice && (
        <div className="space-y-2">
          <div className="text-xs font-medium uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
            实时预览
          </div>
          <div className="overflow-hidden rounded-lg border border-[hsl(var(--border))]/60 bg-black">
            <img
              key={`cam-${selectedDevice.index}-${streamNonce}`}
              src={agentHttpUrl(`/api/camera/mjpeg?device=${selectedDevice.index}&w=${selectedDevice.width || 640}&h=${selectedDevice.height || 480}&fps=${Math.round(selectedDevice.fps) || 30}&_n=${streamNonce}`)}
              alt={`来自 /dev/video${selectedDevice.index} 的实时预览`}
              className="w-full max-h-[360px] object-contain bg-black"
            />
          </div>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            在镜头前挥一下手，画面应该实时变化。如果一直黑屏，拔插摄像头后重新扫描。
          </p>
        </div>
      )}

      {/* ── Troubleshooting ───────────────────────────────────────────── */}
      <details className="rounded-lg border border-[hsl(var(--border))]/40 bg-[hsl(var(--muted))]/20 px-3 py-2 text-xs text-[hsl(var(--muted-foreground))]">
        <summary className="cursor-pointer select-none font-medium text-[hsl(var(--foreground))]">
          摄像头不显示？
        </summary>
        <ul className="list-disc pl-5 space-y-0.5">
          <li>先确认主机上有 <code>/dev/video*</code>：<code>ls -l /dev/video*</code></li>
          <li>如果有设备但这里没有，当前用户可能不在 <code>video</code> 组里。</li>
          <li>同一时间只能有一个进程占用摄像头，请关闭 Zoom / OBS / 其他预览页面。</li>
        </ul>
      </details>
    </>
  )

  if (embedded) {
    return (
      <section className="rounded-lg border border-[hsl(var(--border))]/60 bg-[hsl(var(--card))]/40 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-medium">1. 选择摄像头</h3>
            <p className="text-xs text-[hsl(var(--muted-foreground))]">
              选一个能实时预览的 USB 摄像头，后面录制和推理都会复用它。
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={loadDevices} disabled={loading}>
            <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
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
      title="选择摄像头"
      description="确认 USB 摄像头能实时预览。后面录制和推理都会复用这个设备。"
      headerExtra={
        <Button variant="outline" size="sm" onClick={loadDevices} disabled={loading}>
          <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
          重新扫描
        </Button>
      }
      nextDisabled={selectedDevice === null}
      onNext={handleNext}
    >
      {body}
    </SetupStepCard>
  )
}
