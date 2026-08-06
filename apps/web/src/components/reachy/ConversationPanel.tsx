/**
 * M22 — Reachy Mini Conversation App control panel.
 *
 * Surfaces the official `pollen-robotics/reachy_mini_conversation_app` to
 * non-technical users: pick a backend (HuggingFace / OpenAI / Gemini), supply
 * an API key when needed, click "Start conversation", and Reachy Mini starts
 * listening + talking + dispatching LLM tools (dance / emotion / head tracking).
 *
 * API Key safety:
 *   - Keys live in browser localStorage only.
 *   - On Start, the key is POSTed to the Local Agent which injects it into the
 *     Conversation App subprocess env. It is never persisted on disk by the
 *     Local Agent and never sent to the cloud.
 *   - The status endpoint only reports which backend is configured, never the
 *     key itself.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  ExternalLink,
  Loader2,
  Mic,
  Mic2,
  Play,
  Power,
  RotateCcw,
  Square,
  Volume2,
} from 'lucide-react'
import { Button } from '../ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card'
import { Badge } from '../ui/badge'
import {
  getReachyConversationEnvTemplate,
  getReachyConversationStatus,
  restartReachyConversation,
  startReachyConversation,
  stopReachyConversation,
  type ReachyConversationBackend,
  type ReachyConversationEnvTemplate,
  type ReachyConversationStatus,
  type ReachyHeadTracker,
} from '../../lib/reachyApi'

const LS_KEYS = {
  backend: 'botversex.reachy.conversation.backend',
  apiKey: 'botversex.reachy.conversation.apiKey',
  model: 'botversex.reachy.conversation.model',
  headTracker: 'botversex.reachy.conversation.headTracker',
  gradio: 'botversex.reachy.conversation.gradio',
  noCamera: 'botversex.reachy.conversation.noCamera',
}

function loadLS(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

function saveLS(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // ignore
  }
}

interface Props {
  daemonOnline: boolean
}

export function ConversationPanel({ daemonOnline }: Props) {
  const [template, setTemplate] = useState<ReachyConversationEnvTemplate | null>(null)
  const [status, setStatus] = useState<ReachyConversationStatus | null>(null)
  const [busy, setBusy] = useState<'start' | 'stop' | 'restart' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const [backend, setBackend] = useState<ReachyConversationBackend>(
    () => loadLS(LS_KEYS.backend, 'huggingface') as ReachyConversationBackend,
  )
  const [apiKey, setApiKey] = useState<string>(() => loadLS(LS_KEYS.apiKey, ''))
  const [model, setModel] = useState<string>(() => loadLS(LS_KEYS.model, ''))
  const [headTracker, setHeadTracker] = useState<ReachyHeadTracker | ''>(
    () => (loadLS(LS_KEYS.headTracker, '') as ReachyHeadTracker | '') || '',
  )
  const [gradio, setGradio] = useState<boolean>(() => loadLS(LS_KEYS.gradio, 'true') === 'true')
  const [noCamera, setNoCamera] = useState<boolean>(() => loadLS(LS_KEYS.noCamera, 'false') === 'true')

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = useCallback(async () => {
    try {
      const s = await getReachyConversationStatus()
      setStatus(s)
    } catch (e) {
      setStatus(null)
      setError((e as Error).message)
    }
  }, [])

  const loadTemplate = useCallback(async () => {
    try {
      const t = await getReachyConversationEnvTemplate()
      setTemplate(t)
    } catch {
      // Non-fatal; UI can still render with defaults.
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const startup = window.setTimeout(() => {
      if (cancelled) return
      void loadTemplate()
      void refresh()
      if (cancelled) return
      pollRef.current = setInterval(() => void refresh(), 4000)
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(startup)
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [loadTemplate, refresh])

  const persistConfig = useCallback(() => {
    saveLS(LS_KEYS.backend, backend)
    saveLS(LS_KEYS.apiKey, apiKey)
    saveLS(LS_KEYS.model, model)
    saveLS(LS_KEYS.headTracker, headTracker)
    saveLS(LS_KEYS.gradio, String(gradio))
    saveLS(LS_KEYS.noCamera, String(noCamera))
  }, [backend, apiKey, model, headTracker, gradio, noCamera])

  const handleStart = useCallback(async () => {
    setError(null)
    setSuccess(null)
    const backendInfo = template?.backends[backend]
    if (backendInfo?.requires_key && !apiKey.trim()) {
      setError(`${backendInfo.label} 需要填写 API Key（${backendInfo.key_env ?? ''}）`)
      return
    }
    setBusy('start')
    persistConfig()
    try {
      const r = await startReachyConversation({
        provider: 'official',
        backend,
        api_key: apiKey.trim() || null,
        model: model.trim() || null,
        head_tracker: headTracker || null,
        gradio,
        no_camera: noCamera,
        auto_install: true,
      })
      setSuccess(r.message + (r.gradio_url ? ` · Gradio: ${r.gradio_url}` : ''))
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }, [backend, apiKey, model, headTracker, gradio, noCamera, persistConfig, template, refresh])

  const handleStop = useCallback(async () => {
    setError(null)
    setSuccess(null)
    setBusy('stop')
    try {
      const r = await stopReachyConversation()
      setSuccess(r.message)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }, [refresh])

  const handleRestart = useCallback(async () => {
    setError(null)
    setSuccess(null)
    const backendInfo = template?.backends[backend]
    if (backendInfo?.requires_key && !apiKey.trim()) {
      setError(`${backendInfo.label} 需要填写 API Key（${backendInfo.key_env ?? ''}）`)
      return
    }
    setBusy('restart')
    persistConfig()
    try {
      const r = await restartReachyConversation({
        provider: 'official',
        backend,
        api_key: apiKey.trim() || null,
        model: model.trim() || null,
        head_tracker: headTracker || null,
        gradio,
        no_camera: noCamera,
        auto_install: true,
      })
      setSuccess(r.message + (r.gradio_url ? ` · Gradio: ${r.gradio_url}` : ''))
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }, [backend, apiKey, model, headTracker, gradio, noCamera, persistConfig, template, refresh])

  if (!daemonOnline) {
    return (
      <Card>
        <CardHeader className="py-3 pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Mic className="h-4 w-4" />
            一键对话 (Conversation App)
          </CardTitle>
          <CardDescription className="text-xs">官方 Reachy Mini 语音对话</CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          <p className="text-xs text-muted-foreground">
            守护进程未连接。启动后即可一键开启对话。
          </p>
        </CardContent>
      </Card>
    )
  }

  const running = !!status?.running
  const appInstalled = !!status?.app_installed
  const stateLabel = status?.state ?? 'unknown'
  const stateColor =
    stateLabel === 'running'
      ? 'border-emerald-500/40 text-emerald-300'
      : stateLabel === 'starting' || stateLabel === 'installing'
        ? 'border-amber-500/40 text-amber-300'
        : stateLabel === 'error'
          ? 'border-red-500/40 text-red-300'
          : 'border-white/10 text-muted-foreground'

  const backendInfo = template?.backends[backend]
  const showApiKey = backendInfo?.requires_key ?? false

  return (
    <Card>
      <CardHeader className="py-3 pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Mic className="h-4 w-4" />
          一键对话 (Conversation App)
          <Badge variant="outline" className={`ml-auto text-[10px] ${stateColor}`}>
            {stateLabel}
          </Badge>
        </CardTitle>
        <CardDescription className="text-xs">
          官方 Pollen Robotics Conversation App · 语音 + LLM 工具调度
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {/* App install warning */}
        {!appInstalled && !running && (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-[11px] text-amber-200 flex items-start gap-2">
            <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
            <span>
              Conversation App 未安装。点击「启动对话」会自动从 HuggingFace 安装（首次约 1-3 分钟）。
            </span>
          </div>
        )}

        {/* Backend selector */}
        <div className="rounded-md border bg-muted/30 p-2.5 space-y-1.5">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
            LLM 后端
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            {(['huggingface', 'openai', 'gemini'] as const).map((b) => {
              const info = template?.backends[b]
              const active = backend === b
              return (
                <button
                  key={b}
                  type="button"
                  disabled={running}
                  onClick={() => setBackend(b)}
                  className={`rounded-md border px-2 py-1.5 text-xs transition-colors text-left ${
                    active
                      ? 'border-[hsl(var(--primary))]/60 bg-[hsl(var(--primary))]/15 text-foreground'
                      : 'border-white/10 hover:border-white/20 text-muted-foreground'
                  } ${running ? 'opacity-60 cursor-not-allowed' : ''}`}
                >
                  <div className="font-medium truncate">
                    {info?.label ?? b}
                  </div>
                  {info?.requires_key ? (
                    <div className="text-[9px] text-amber-300/80">需 API Key</div>
                  ) : (
                    <div className="text-[9px] text-emerald-300/80">零 Key</div>
                  )}
                </button>
              )
            })}
          </div>
        </div>

        {/* API key */}
        {showApiKey && (
          <div className="rounded-md border bg-muted/30 p-2.5 space-y-1.5">
            <div className="flex items-center justify-between text-[10px] uppercase tracking-wide text-muted-foreground">
              <span>{backendInfo?.key_env ?? 'API_KEY'}</span>
              {backendInfo?.key_hint && (
                <a
                  href={backendInfo.key_hint}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-0.5 text-[9px] text-sky-300/80 hover:text-sky-200"
                >
                  获取 Key <ExternalLink className="h-2.5 w-2.5" />
                </a>
              )}
            </div>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              disabled={running}
              placeholder={`输入 ${backendInfo?.label} API Key`}
              className="w-full h-8 rounded-md border bg-background px-2 text-xs font-mono"
            />
            <p className="text-[9px] text-muted-foreground">
              Key 只存在浏览器 localStorage，启动时通过本机 Agent 注入到 subprocess env，不上云不落盘
            </p>
          </div>
        )}

        {/* Model override */}
        <div className="rounded-md border bg-muted/30 p-2.5 space-y-1.5">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
            模型（可选，留空用默认）
          </div>
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={running}
            placeholder={
              backendInfo?.default_model
                ? `默认: ${backendInfo.default_model}`
                : '留空使用后端默认'
            }
            className="w-full h-8 rounded-md border bg-background px-2 text-xs font-mono"
          />
        </div>

        {/* Vision / camera options */}
        <div className="rounded-md border bg-muted/30 p-2.5 space-y-2">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
            视觉 / 摄像头
          </div>
          <label className="flex items-center justify-between text-xs cursor-pointer">
            <span>启动 Gradio Web UI</span>
            <input
              type="checkbox"
              checked={gradio}
              onChange={(e) => setGradio(e.target.checked)}
              disabled={running}
              className="h-3.5 w-3.5"
            />
          </label>
          <label className="flex items-center justify-between text-xs cursor-pointer">
            <span>无摄像头（仅音频）</span>
            <input
              type="checkbox"
              checked={noCamera}
              onChange={(e) => setNoCamera(e.target.checked)}
              disabled={running}
              className="h-3.5 w-3.5"
            />
          </label>
          <div className="space-y-1">
            <div className="text-[10px] text-muted-foreground">头部跟踪（可选）</div>
            <select
              value={headTracker}
              onChange={(e) => setHeadTracker(e.target.value as ReachyHeadTracker | '')}
              disabled={running}
              className="w-full h-7 rounded-md border bg-background px-2 text-xs"
            >
              <option value="">关闭</option>
              <option value="mediapipe">MediaPipe (CPU, 轻量)</option>
              <option value="yolo">YOLOv11n (需 GPU)</option>
            </select>
          </div>
        </div>

        {/* Actions */}
        <div className="flex flex-wrap gap-1.5">
          {!running ? (
            <Button
              size="sm"
              className="h-8 flex-1"
              onClick={handleStart}
              disabled={busy !== null}
            >
              {busy === 'start' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Power className="h-3.5 w-3.5" />
              )}
              启动对话
            </Button>
          ) : (
            <>
              <Button
                size="sm"
                variant="destructive"
                className="h-8 flex-1"
                onClick={handleStop}
                disabled={busy !== null}
              >
                {busy === 'stop' ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Square className="h-3.5 w-3.5" />
                )}
                停止
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-8"
                onClick={handleRestart}
                disabled={busy !== null}
              >
                {busy === 'restart' ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RotateCcw className="h-3.5 w-3.5" />
                )}
                重启
              </Button>
            </>
          )}
        </div>

        {/* Gradio link */}
        {running && status?.gradio_url && (
          <a
            href={status.gradio_url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center justify-between rounded-md border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-xs text-sky-200 hover:bg-sky-500/20 transition-colors"
          >
            <span className="flex items-center gap-1.5">
              <Play className="h-3 w-3" />
              打开 Gradio UI ({status.gradio_url})
            </span>
            <ExternalLink className="h-3 w-3" />
          </a>
        )}

        {/* Live status */}
        {running && (
          <div className="rounded-md border bg-muted/20 p-2.5 space-y-1">
            <div className="flex items-center justify-between text-[10px] uppercase tracking-wide text-muted-foreground">
              <span className="flex items-center gap-1">
                <Activity className="h-3 w-3" /> 实时状态
              </span>
              <span className="text-emerald-300/80 flex items-center gap-1">
                <Mic2 className="h-3 w-3" /> pid: {status?.pid ?? '—'}
              </span>
            </div>
            <div className="text-xs text-muted-foreground">
              启动时间: {status?.started_at ? new Date(status.started_at * 1000).toLocaleTimeString() : '—'}
            </div>
            {status?.log_tail && status.log_tail.length > 0 && (
              <div className="mt-1.5 max-h-24 overflow-y-auto rounded bg-black/30 p-1.5 text-[10px] font-mono text-muted-foreground">
                {status.log_tail.slice(-8).map((line, i) => (
                  <div key={i} className="truncate">{line}</div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Messages */}
        {error && (
          <div className="rounded-md border border-red-500/40 bg-red-500/10 p-2 text-xs text-red-200">
            ⚠ {error}
          </div>
        )}
        {success && (
          <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 p-2 text-xs text-emerald-200">
            ✓ {success}
          </div>
        )}

        {/* Footer note */}
        <div className="text-[10px] text-muted-foreground space-y-0.5">
          <div className="flex items-center gap-1">
            <Volume2 className="h-3 w-3" />
            对话时 Reachy 会自动播放语音 + 调度 LLM 工具（dance / emotion / head_tracking）
          </div>
          <div>
            默认 HuggingFace 后端零 Key 可用。OpenAI / Gemini 需自备 Key。
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
