import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  Camera,
  CameraOff,
  CircleDot,
  Play,
  Plug,
  PlugZap,
  Square,
} from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { UrdfViewer } from '../components/features/UrdfViewer'
import { useTeleopWebSocket } from '../hooks/useTeleopWebSocket'
import { agentFetch, agentHttpUrl } from '../lib/localAgent'
import { JOINT_NAMES, type JointMap } from '../types/botclaw'

type RecordState = 'idle' | 'recording' | 'busy' | 'error'

const EMPTY_JOINTS: JointMap = { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0, '6': 0 }

function stateLabel(s: ReturnType<typeof useTeleopWebSocket>['state']): string {
  switch (s) {
    case 'idle':
      return '未连接'
    case 'connecting':
      return '连接中'
    case 'connected':
      return '已连接'
    case 'disconnected':
      return '已断开'
    case 'error':
      return '连接错误'
  }
}

function stateDotClass(s: ReturnType<typeof useTeleopWebSocket>['state']): string {
  switch (s) {
    case 'connected':
      return 'text-green-400 animate-pulse'
    case 'connecting':
      return 'text-amber-400 animate-pulse'
    case 'error':
      return 'text-red-400'
    default:
      return 'text-muted-foreground'
  }
}

export function Teleop() {
  const { state, lastUpdate, fps, error, connect, disconnect } = useTeleopWebSocket({
    url: '/ws/ui',
    autoConnect: false,
    reconnect: false,
  })

  const [recordState, setRecordState] = useState<RecordState>('idle')
  const [recordMsg, setRecordMsg] = useState<string | null>(null)

  const joints: JointMap = useMemo(() => {
    if (!lastUpdate) return EMPTY_JOINTS
    return lastUpdate.joints
  }, [lastUpdate])

  const [cameraEnabled, setCameraEnabled] = useState(false)

  const sendRecord = useCallback(async (action: 'start' | 'stop') => {
    setRecordState('busy')
    setRecordMsg(null)
    try {
      const body: Record<string, unknown> = { action }
      if (action === 'start' && cameraEnabled) {
        body.camera_device = '0'
      }
      const resp = await fetch('/api/record', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await resp.json().catch(() => ({})) as Record<string, unknown>
      if (!resp.ok) {
        setRecordState('error')
        setRecordMsg((data.detail as string) ?? `HTTP ${resp.status}`)
        return
      }
      if (action === 'start') {
        setRecordState('recording')
        const cam = body.camera_device ? ' (with camera)' : ''
        setRecordMsg(`已开始录制${cam}`)
      } else {
        setRecordState('idle')
        const frames = data.frames as number | undefined
        const imgs = data.image_frames as number | undefined
        const imgMsg = imgs && imgs > 0 ? `, ${imgs} images` : ''
        setRecordMsg(`已停止录制${frames ? `, 共 ${frames} 帧${imgMsg}` : ''}`)
      }
    } catch (e) {
      setRecordState('error')
      setRecordMsg((e as Error).message)
    }
  }, [cameraEnabled])

  const robotId = lastUpdate?.robot_id ?? '—'
  const metaFps = lastUpdate?.meta?.fps

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Teleoperation</h1>
          <p className="text-muted-foreground mt-1">
            手动连接实时服务 <code className="font-mono text-xs">/ws/ui</code>, 实时查看 6 关节状态并录制轨迹.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-md border bg-muted/40">
            <CircleDot className={`h-4 w-4 ${stateDotClass(state)}`} />
            <span className="text-sm font-medium">{stateLabel(state)}</span>
            {state === 'connected' && (
              <Badge variant="outline" className="border-green-500/40 text-green-400">
                {fps} Hz
              </Badge>
            )}
          </div>
          {state === 'connected' ? (
            <Button variant="destructive" onClick={disconnect}>
              <Plug className="h-4 w-4 mr-2" />
              断开
            </Button>
          ) : (
            <Button onClick={connect} disabled={state === 'connecting'}>
              <PlugZap className="h-4 w-4 mr-2" />
              {state === 'connecting' ? '连接中...' : '连接'}
            </Button>
          )}
        </div>
      </div>

      {error && (
        <div className="px-4 py-2 rounded-md bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
          WebSocket error: {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left column: 3D viewer + camera */}
        <div className="lg:col-span-2 space-y-4">
          <Card className="overflow-hidden">
            <CardHeader className="flex-row items-center justify-between space-y-0 py-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Activity className="h-4 w-4" />
                SO-101 虚拟臂
              </CardTitle>
              <div className="text-xs text-muted-foreground font-mono">
                robot_id: {robotId}
                {typeof metaFps === 'number' && `  ·  source fps: ${metaFps.toFixed(1)}`}
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <div className="h-[480px]">
                <UrdfViewer urdfUrl="/api/urdf/so101.urdf" joints={joints} />
              </div>
            </CardContent>
          </Card>

          <CameraPreview />
        </div>

        {/* Right column: joints + recording */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="py-3">
              <CardTitle className="text-base">关节状态 (rad)</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3">
                {JOINT_NAMES.map((n) => (
                  <JointCard key={n} id={n} value={joints[n] ?? 0} />
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="py-3">
              <CardTitle className="text-base">数据录制</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center gap-2">
                <Button
                  className="flex-1"
                  onClick={() => sendRecord('start')}
                  disabled={recordState === 'recording' || recordState === 'busy' || state !== 'connected'}
                >
                  <Play className="h-4 w-4 mr-2" />
                  开始录制
                </Button>
                <Button
                  variant="destructive"
                  className="flex-1"
                  onClick={() => sendRecord('stop')}
                  disabled={recordState !== 'recording'}
                >
                  <Square className="h-4 w-4 mr-2" />
                  停止录制
                </Button>
              </div>
              {recordState === 'recording' && (
                <div className="px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs">
                  ● 正在录制 ...
                </div>
              )}
              {recordState === 'error' && recordMsg && (
                <div className="px-3 py-2 rounded-md bg-red-500/10 border border-red-500/30 text-red-300 text-xs">
                  {recordMsg}
                </div>
              )}
              {recordState === 'idle' && recordMsg && (
                <div className="px-3 py-2 rounded-md bg-muted/40 border text-xs text-muted-foreground">
                  {recordMsg}
                </div>
              )}
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={cameraEnabled}
                  onChange={(e) => setCameraEnabled(e.target.checked)}
                  disabled={recordState === 'recording'}
                />
                <Camera className="h-3.5 w-3.5" />
                Record with camera (vision dataset)
              </label>
              <p className="text-[11px] text-muted-foreground">
                录制通过 <code className="font-mono">/api/record</code> 透传到 realtime 服务 (:8002), 停止后自动导出 parquet.
                {cameraEnabled && ' Camera frames will be saved alongside joint data.'}
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

function CameraPreview() {
  const [enabled, setEnabled] = useState(false)
  const [hasCamera, setHasCamera] = useState<boolean | null>(null)
  const imgRef = useRef<HTMLImageElement>(null)

  useEffect(() => {
    let cancelled = false
    agentFetch('/api/camera/devices')
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled) setHasCamera(data.devices?.length > 0)
      })
      .catch(() => {
        if (!cancelled) setHasCamera(false)
      })
    return () => { cancelled = true }
  }, [])

  const mjpegUrl = agentHttpUrl('/api/camera/mjpeg?fps=15&quality=70')

  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row items-center justify-between space-y-0 py-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Camera className="h-4 w-4" />
          Camera Preview
        </CardTitle>
        <div className="flex items-center gap-2">
          {hasCamera === false && (
            <Badge variant="outline" className="border-amber-500/40 text-amber-400 text-xs">
              No camera
            </Badge>
          )}
          <Button
            variant={enabled ? 'destructive' : 'default'}
            size="sm"
            onClick={() => setEnabled((v) => !v)}
            disabled={hasCamera === false}
          >
            {enabled ? (
              <><CameraOff className="h-3.5 w-3.5 mr-1.5" /> Stop</>
            ) : (
              <><Camera className="h-3.5 w-3.5 mr-1.5" /> Start</>
            )}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="h-[300px] bg-black/60 flex items-center justify-center">
          {enabled ? (
            <img
              ref={imgRef}
              src={mjpegUrl}
              alt="Live camera"
              className="w-full h-full object-contain"
              onError={() => setEnabled(false)}
            />
          ) : (
            <div className="text-muted-foreground text-sm flex flex-col items-center gap-2">
              <CameraOff className="h-8 w-8 opacity-40" />
              <span>{hasCamera === false ? 'No camera detected' : 'Click Start to preview'}</span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function JointCard({ id, value }: { id: string; value: number }) {
  return (
    <div className="p-3 rounded-lg bg-muted/40 border">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">
        Joint {id}
      </div>
      <div className="font-mono text-lg font-semibold">{value.toFixed(3)}</div>
    </div>
  )
}
