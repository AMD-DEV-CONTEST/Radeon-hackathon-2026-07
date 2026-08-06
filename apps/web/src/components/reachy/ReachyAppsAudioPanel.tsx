/**
 * M21 — Reachy Mini Apps / Volume / DoA panel.
 *
 * Surfaces the Allan daemon's open-source ecosystem surface area that
 * BotverseX now proxies:
 *   - Current Reachy App status badge + Stop/Restart buttons
 *   - Speaker + Microphone volume sliders + test sound button
 *   - Direction of Arrival (microphone array) live indicator
 *   - Full daemon lifecycle controls (start/stop/restart)
 *
 * All requests go through `agentFetch` → Local Agent :8002 → daemon :8010.
 * When daemon is offline, the panel shows a friendly placeholder rather
 * than throwing.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  Loader2,
  Mic,
  Mic2,
  Pause,
  Play,
  RotateCcw,
  Square,
  Volume2,
} from 'lucide-react'
import { Button } from '../ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card'
import { Badge } from '../ui/badge'
import {
  getCurrentReachyAppStatus,
  getReachyDaemonState,
  getReachyDoA,
  getReachyMicVolume,
  getReachySpeakerVolume,
  playReachyTestSound,
  restartCurrentReachyApp,
  restartReachyDaemon,
  setReachyMicVolume,
  setReachySpeakerVolume,
  startReachyDaemon,
  stopCurrentReachyApp,
  stopReachyDaemon,
  type ReachyAppStatus,
  type ReachyDaemonState,
  type ReachyDoAInfo,
  type ReachyVolumeResponse,
} from '../../lib/reachyApi'

interface Props {
  daemonOnline: boolean
}

function fmtAngle(rad: number | null | undefined): string {
  if (rad == null || !Number.isFinite(rad)) return '—'
  const deg = (rad * 180) / Math.PI
  return `${deg.toFixed(0)}°`
}

function directionLabel(rad: number | null | undefined): string {
  if (rad == null || !Number.isFinite(rad)) return '—'
  const deg = (rad * 180) / Math.PI
  if (deg < 30) return '左前'
  if (deg < 60) return '正前'
  if (deg < 90) return '右前'
  if (deg < 135) return '右侧'
  return '右后'
}

export function ReachyAppsAudioPanel({ daemonOnline }: Props) {
  const [app, setApp] = useState<ReachyAppStatus | null>(null)
  const [appBusy, setAppBusy] = useState<'stop' | 'restart' | null>(null)
  const [daemonState, setDaemonState] = useState<ReachyDaemonState | null>(null)
  const [daemonBusy, setDaemonBusy] = useState<'start' | 'stop' | 'restart' | null>(null)

  const [speaker, setSpeaker] = useState<ReachyVolumeResponse | null>(null)
  const [mic, setMic] = useState<ReachyVolumeResponse | null>(null)
  const [speakerInput, setSpeakerInput] = useState<number>(50)
  const [micInput, setMicInput] = useState<number>(50)
  const [volumeBusy, setVolumeBusy] = useState<'speaker' | 'mic' | 'test' | null>(null)
  const [testSound, setTestSound] = useState<string | null>(null)

  const [doa, setDoa] = useState<ReachyDoAInfo | null>(null)
  const [doaError, setDoaError] = useState<string | null>(null)

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = useCallback(async () => {
    if (!daemonOnline) {
      setApp(null)
      setDaemonState(null)
      setSpeaker(null)
      setMic(null)
      setDoa(null)
      return
    }
    const tasks: Promise<void>[] = [
      getCurrentReachyAppStatus()
        .then((s) => setApp(s))
        .catch(() => setApp(null)),
      getReachyDaemonState()
        .then((s) => setDaemonState(s))
        .catch(() => setDaemonState(null)),
      getReachySpeakerVolume()
        .then((v) => {
          setSpeaker(v)
          setSpeakerInput(v.volume)
        })
        .catch(() => setSpeaker(null)),
      getReachyMicVolume()
        .then((v) => {
          setMic(v)
          setMicInput(v.volume)
        })
        .catch(() => setMic(null)),
      getReachyDoA()
        .then((d) => {
          setDoa(d)
          setDoaError(d == null ? '音频未启用或无麦克风' : null)
        })
        .catch((e) => {
          setDoa(null)
          setDoaError((e as Error).message || '无法获取 DOA')
        }),
    ]
    await Promise.allSettled(tasks)
  }, [daemonOnline])

  useEffect(() => {
    let cancelled = false
    // Defer the first poll out of the effect body so setState calls inside
    // refresh() do not run synchronously during the effect (react-hooks/
    // set-state-in-effect).
    const startup = window.setTimeout(() => {
      if (cancelled) return
      void refresh()
      if (cancelled) return
      pollRef.current = setInterval(() => void refresh(), 5000)
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(startup)
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [daemonOnline, refresh])

  const handleStopApp = useCallback(async () => {
    setAppBusy('stop')
    try {
      await stopCurrentReachyApp()
      await refresh()
    } catch (e) {
      console.error('[reachy] stop app failed:', e)
    } finally {
      setAppBusy(null)
    }
  }, [refresh])

  const handleRestartApp = useCallback(async () => {
    setAppBusy('restart')
    try {
      await restartCurrentReachyApp()
      await refresh()
    } catch (e) {
      console.error('[reachy] restart app failed:', e)
    } finally {
      setAppBusy(null)
    }
  }, [refresh])

  const handleStartDaemon = useCallback(async () => {
    setDaemonBusy('start')
    try {
      await startReachyDaemon(true)
      await refresh()
    } catch (e) {
      console.error('[reachy] start daemon failed:', e)
    } finally {
      setDaemonBusy(null)
    }
  }, [refresh])

  const handleStopDaemon = useCallback(async () => {
    setDaemonBusy('stop')
    try {
      await stopReachyDaemon(true)
      await refresh()
    } catch (e) {
      console.error('[reachy] stop daemon failed:', e)
    } finally {
      setDaemonBusy(null)
    }
  }, [refresh])

  const handleRestartDaemon = useCallback(async () => {
    setDaemonBusy('restart')
    try {
      await restartReachyDaemon()
      await refresh()
    } catch (e) {
      console.error('[reachy] restart daemon failed:', e)
    } finally {
      setDaemonBusy(null)
    }
  }, [refresh])

  const handleSpeakerChange = useCallback(async (v: number) => {
    setSpeakerInput(v)
    setVolumeBusy('speaker')
    try {
      const r = await setReachySpeakerVolume(v)
      setSpeaker(r)
    } catch (e) {
      console.error('[reachy] set speaker volume failed:', e)
    } finally {
      setVolumeBusy(null)
    }
  }, [])

  const handleMicChange = useCallback(async (v: number) => {
    setMicInput(v)
    setVolumeBusy('mic')
    try {
      const r = await setReachyMicVolume(v)
      setMic(r)
    } catch (e) {
      console.error('[reachy] set mic volume failed:', e)
    } finally {
      setVolumeBusy(null)
    }
  }, [])

  const handleTestSound = useCallback(async () => {
    setVolumeBusy('test')
    setTestSound(null)
    try {
      const r = await playReachyTestSound()
      setTestSound(r.status === 'ok' ? '播放成功' : r.message || r.status)
    } catch (e) {
      setTestSound((e as Error).message || '播放失败')
    } finally {
      setVolumeBusy(null)
    }
  }, [])

  if (!daemonOnline) {
    return (
      <Card>
        <CardHeader className="py-3 pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Activity className="h-4 w-4" />
            Apps / 音频 / DOA
          </CardTitle>
          <CardDescription className="text-xs">M21 官方 Reachy 生态接入</CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          <p className="text-xs text-muted-foreground">
            守护进程未连接，启动后可装 App、调音量、看声源方向。
          </p>
        </CardContent>
      </Card>
    )
  }

  const appRunning = !!app?.running
  const daemonStateLabel = daemonState?.state ?? 'unknown'

  return (
    <Card>
      <CardHeader className="py-3 pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Activity className="h-4 w-4" />
          Apps / 音频 / DOA
          <Badge variant="outline" className="ml-auto text-[10px]">
            daemon: {daemonStateLabel}
          </Badge>
        </CardTitle>
        <CardDescription className="text-xs">M21 官方 Reachy 生态接入</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {/* Current App */}
        <div className="rounded-md border bg-muted/30 p-2.5 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
              当前 App
            </span>
            <Badge
              variant="outline"
              className={
                appRunning
                  ? 'border-emerald-500/40 text-emerald-300'
                  : 'border-white/10 text-muted-foreground'
              }
            >
              {appRunning ? '运行中' : '空闲'}
            </Badge>
          </div>
          <div className="text-sm font-mono truncate">
            {app?.name || '—'}
          </div>
          {appRunning && (
            <div className="flex gap-1.5">
              <Button
                size="sm"
                variant="destructive"
                className="h-7 text-xs"
                onClick={handleStopApp}
                disabled={appBusy !== null}
              >
                {appBusy === 'stop' ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Square className="h-3 w-3" />
                )}
                停止
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-xs"
                onClick={handleRestartApp}
                disabled={appBusy !== null}
              >
                {appBusy === 'restart' ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <RotateCcw className="h-3 w-3" />
                )}
                重启
              </Button>
            </div>
          )}
          <p className="text-[10px] text-muted-foreground">
            完整 App 商店与对话面板将在 M22 推出
          </p>
        </div>

        {/* Speaker volume */}
        <div className="rounded-md border bg-muted/30 p-2.5 space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground flex items-center gap-1">
              <Volume2 className="h-3 w-3" /> 扬声器
            </span>
            <span className="text-xs font-mono">{speaker?.volume ?? '—'}</span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            value={speakerInput}
            onChange={(e) => void handleSpeakerChange(Number(e.target.value))}
            disabled={volumeBusy === 'speaker'}
            className="w-full h-1.5 accent-[hsl(var(--primary))]"
          />
          <Button
            size="sm"
            variant="outline"
            className="h-7 w-full text-xs"
            onClick={handleTestSound}
            disabled={volumeBusy === 'test'}
          >
            {volumeBusy === 'test' ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Play className="h-3 w-3" />
            )}
            测试音
          </Button>
          {testSound && (
            <p className="text-[10px] text-muted-foreground">{testSound}</p>
          )}
        </div>

        {/* Mic volume */}
        <div className="rounded-md border bg-muted/30 p-2.5 space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground flex items-center gap-1">
              {doa?.speech_detected ? <Mic2 className="h-3 w-3" /> : <Mic className="h-3 w-3" />}
              麦克风
            </span>
            <span className="text-xs font-mono">{mic?.volume ?? '—'}</span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            value={micInput}
            onChange={(e) => void handleMicChange(Number(e.target.value))}
            disabled={volumeBusy === 'mic'}
            className="w-full h-1.5 accent-[hsl(var(--primary))]"
          />
        </div>

        {/* DOA */}
        <div className="rounded-md border bg-muted/30 p-2.5 space-y-1">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
              声源方向 (DOA)
            </span>
            <span
              className={`text-xs font-mono ${
                doa?.speech_detected ? 'text-emerald-300' : 'text-muted-foreground'
              }`}
            >
              {fmtAngle(doa?.angle)} · {directionLabel(doa?.angle)}
            </span>
          </div>
          <div className="flex items-center gap-2 text-[10px]">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                doa?.speech_detected ? 'bg-emerald-400 animate-pulse' : 'bg-muted-foreground/40'
              }`}
            />
            <span className="text-muted-foreground">
              {doa?.speech_detected ? '检测到说话' : '安静'}
            </span>
            {doaError && (
              <span className="text-amber-400/80 flex items-center gap-1">
                <AlertTriangle className="h-3 w-3" /> {doaError}
              </span>
            )}
          </div>
        </div>

        {/* Daemon lifecycle */}
        <div className="rounded-md border border-dashed bg-muted/20 p-2.5 space-y-1.5">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Daemon 生命周期
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={handleStartDaemon}
              disabled={daemonBusy !== null}
            >
              {daemonBusy === 'start' ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Play className="h-3 w-3" />
              )}
              启动
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={handleStopDaemon}
              disabled={daemonBusy !== null}
            >
              {daemonBusy === 'stop' ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Pause className="h-3 w-3" />
              )}
              停止
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={handleRestartDaemon}
              disabled={daemonBusy !== null}
            >
              {daemonBusy === 'restart' ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RotateCcw className="h-3 w-3" />
              )}
              重启
            </Button>
          </div>
          <p className="text-[10px] text-muted-foreground">
            重启 daemon 会停止当前 App 与所有进行中的动作
          </p>
        </div>
      </CardContent>
    </Card>
  )
}
