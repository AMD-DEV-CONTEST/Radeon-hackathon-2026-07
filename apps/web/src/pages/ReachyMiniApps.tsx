/**
 * M22 — Reachy Mini Apps store page.
 *
 * Lists every HuggingFace Space app that the Allan daemon knows about,
 * plus currently installed ones, with one-click install / start / stop /
 * remove / update. Install/remove/update stream their job logs through
 * the /ws/reachy/apps-manager/{job_id} WebSocket so the user sees
 * download progress in real time.
 *
 * This is the BotverseX-flavored equivalent of the daemon's built-in
 * dashboard app store. The "one-click conversation" entry point lives
 * on the robot page (ConversationPanel); this page is for power users
 * who want to install other apps or update existing ones.
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  ExternalLink,
  Loader2,
  Package,
  Play,
  RefreshCw,
  RotateCcw,
  Square,
  Trash2,
  Upload,
} from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import {
  checkReachyAppUpdates,
  getCurrentReachyAppStatus,
  getReachyJobStatus,
  installReachyApp,
  listReachyApps,
  listReachyAppsBySource,
  removeReachyApp,
  restartCurrentReachyApp,
  startReachyApp,
  stopCurrentReachyApp,
  updateReachyApp,
  type ReachyApp,
  type ReachyAppStatus,
  type ReachyAppUpdatesResponse,
  type ReachyJobInfo,
} from '../lib/reachyApi'

type SourceTab = 'hf_space' | 'installed' | 'all'

const SOURCE_LABELS: Record<SourceTab, string> = {
  hf_space: 'HuggingFace Space',
  installed: '已安装',
  all: '全部',
}

function sourceBadgeClass(source: string): string {
  if (source === 'installed') return 'border-emerald-500/40 text-emerald-300'
  if (source === 'hf_space') return 'border-sky-500/40 text-sky-300'
  return 'border-white/10 text-muted-foreground'
}

function useAppsManagerSocket(jobId: string | null): ReachyJobInfo | null {
  const [job, setJob] = useState<ReachyJobInfo | null>(null)
  useEffect(() => {
    if (!jobId) {
      // Defer the reset so setState is not called synchronously inside the effect body.
      const t = window.setTimeout(() => setJob(null), 0)
      return () => window.clearTimeout(t)
    }
    let cancelled = false
    let ws: WebSocket | null = null
    const url = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/reachy/apps-manager/${encodeURIComponent(jobId)}`
    try {
      ws = new WebSocket(url)
    } catch {
      return
    }
    ws.onmessage = (ev) => {
      if (cancelled) return
      try {
        const msg = JSON.parse(ev.data)
        if (msg?.type === 'reachy_apps_job' && msg?.payload) setJob(msg.payload)
        else if (msg?.type === 'reachy_apps_error') setJob({ status: 'failed', error: msg?.message, logs: [] })
      } catch {
        // ignore non-JSON frames
      }
    }
    ws.onclose = () => {
      // WS closed: fall back to HTTP polling for terminal status.
      if (cancelled || !jobId) return
      const poll = async () => {
        try {
          const j = await getReachyJobStatus(jobId)
          if (!cancelled) setJob(j)
        } catch {
          // ignore
        }
      }
      void poll()
      const t = setInterval(() => void poll(), 2000)
      setTimeout(() => clearInterval(t), 30_000)
    }
    return () => {
      cancelled = true
      if (ws) {
        try { ws.close() } catch { /* ignore */ }
      }
    }
  }, [jobId])
  return job
}

export default function ReachyMiniApps() {
  const [tab, setTab] = useState<SourceTab>('hf_space')
  const [apps, setApps] = useState<ReachyApp[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [current, setCurrent] = useState<ReachyAppStatus | null>(null)
  const [updates, setUpdates] = useState<ReachyAppUpdatesResponse | null>(null)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [busyApp, setBusyApp] = useState<string | null>(null)
  const job = useAppsManagerSocket(activeJobId)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [list, cur, upd] = await Promise.allSettled([
        tab === 'all' ? listReachyApps() : listReachyAppsBySource(tab),
        getCurrentReachyAppStatus(),
        checkReachyAppUpdates(false),
      ])
      if (list.status === 'fulfilled') setApps(list.value)
      else if (list.status === 'rejected') setError((list.reason as Error).message)
      if (cur.status === 'fulfilled') setCurrent(cur.value)
      if (upd.status === 'fulfilled') setUpdates(upd.value)
    } finally {
      setLoading(false)
    }
  }, [tab])

  useEffect(() => {
    let cancelled = false
    const startup = window.setTimeout(() => {
      if (cancelled) return
      void refresh()
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(startup)
    }
  }, [refresh])

  const handleInstall = useCallback(async (app: ReachyApp) => {
    setBusyApp(app.name)
    setError(null)
    try {
      const r = await installReachyApp(app)
      setActiveJobId(r.job_id)
    } catch (e) {
      setError(`安装 ${app.name} 失败：${(e as Error).message}`)
    } finally {
      setBusyApp(null)
    }
  }, [])

  const handleRemove = useCallback(async (name: string) => {
    if (!confirm(`确认卸载 ${name}？`)) return
    setBusyApp(name)
    setError(null)
    try {
      const r = await removeReachyApp(name)
      setActiveJobId(r.job_id)
    } catch (e) {
      setError(`卸载 ${name} 失败：${(e as Error).message}`)
    } finally {
      setBusyApp(null)
    }
  }, [])

  const handleStart = useCallback(async (name: string) => {
    setBusyApp(name)
    setError(null)
    try {
      await startReachyApp(name)
      await refresh()
    } catch (e) {
      setError(`启动 ${name} 失败：${(e as Error).message}`)
    } finally {
      setBusyApp(null)
    }
  }, [refresh])

  const handleStop = useCallback(async () => {
    setBusyApp('__current__')
    setError(null)
    try {
      await stopCurrentReachyApp()
      await refresh()
    } catch (e) {
      setError(`停止失败：${(e as Error).message}`)
    } finally {
      setBusyApp(null)
    }
  }, [refresh])

  const handleRestart = useCallback(async () => {
    setBusyApp('__current__')
    setError(null)
    try {
      await restartCurrentReachyApp()
      await refresh()
    } catch (e) {
      setError(`重启失败：${(e as Error).message}`)
    } finally {
      setBusyApp(null)
    }
  }, [refresh])

  const handleUpdate = useCallback(async (name: string) => {
    setBusyApp(name)
    setError(null)
    try {
      const r = await updateReachyApp(name)
      setActiveJobId(r.job_id)
    } catch (e) {
      setError(`更新 ${name} 失败：${(e as Error).message}`)
    } finally {
      setBusyApp(null)
    }
  }, [])

  const jobRunning = job?.status && !['done', 'completed', 'failed', 'success'].includes(String(job.status).toLowerCase())

  return (
    <div className="container mx-auto px-4 py-6 space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <Link
          to="/robots/reachy_mini"
          className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-[hsl(var(--border))] hover:bg-[hsl(var(--muted))]/40"
          aria-label="Back to Reachy Mini"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[hsl(var(--primary))]/15">
          <Package className="h-5 w-5 text-[hsl(var(--primary))]" />
        </div>
        <div className="flex-1 min-w-[200px]">
          <h1 className="text-xl font-semibold tracking-tight">Reachy Mini Apps</h1>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            HuggingFace Space 应用商店 · 官方 + 社区 Reachy Mini 应用
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          刷新
        </Button>
      </div>

      {/* Current app banner */}
      {current?.running && (
        <div className="rounded-md border border-emerald-500/40 bg-emerald-500/5 p-3 text-sm flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="border-emerald-500/40 text-emerald-300">运行中</Badge>
          <span className="font-mono text-emerald-200">{current.name}</span>
          <span className="flex-1" />
          <Button size="sm" variant="outline" onClick={handleRestart} disabled={busyApp === '__current__'}>
            {busyApp === '__current__' ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}
            重启
          </Button>
          <Button size="sm" variant="destructive" onClick={handleStop} disabled={busyApp === '__current__'}>
            <Square className="h-3 w-3" />
            停止
          </Button>
        </div>
      )}

      {/* Job progress banner */}
      {activeJobId && job && (
        <div className="rounded-md border border-sky-500/40 bg-sky-500/5 p-3 text-sm space-y-2">
          <div className="flex items-center gap-2">
            {jobRunning ? (
              <Loader2 className="h-4 w-4 animate-spin text-sky-300" />
            ) : (
              <CheckCircle2 className="h-4 w-4 text-emerald-300" />
            )}
            <span className="font-mono text-sky-200">job: {activeJobId.slice(0, 8)}…</span>
            <Badge variant="outline" className="ml-auto">{job.status ?? '...'}</Badge>
            <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setActiveJobId(null)}>
              关闭
            </Button>
          </div>
          {job.logs && job.logs.length > 0 && (
            <pre className="text-[10px] font-mono bg-black/40 rounded p-2 max-h-32 overflow-y-auto whitespace-pre-wrap break-words text-muted-foreground">
              {job.logs.slice(-12).join('\n')}
            </pre>
          )}
        </div>
      )}

      {/* Updates available */}
      {updates && updates.apps_with_updates.length > 0 && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm text-amber-200">
          <div className="flex items-center gap-2 mb-1">
            <Upload className="h-4 w-4" />
            <span>{updates.apps_with_updates.length} 个 App 有更新</span>
          </div>
          <ul className="text-xs space-y-0.5 font-mono">
            {updates.apps_with_updates.map((u) => (
              <li key={u.app_name}>· {u.app_name} — {u.installed_sha.slice(0, 7)} → {u.latest_sha.slice(0, 7)}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Source tabs */}
      <div className="flex gap-1 border-b">
        {(Object.keys(SOURCE_LABELS) as SourceTab[]).map((t) => (
          <button
            key={t}
            className={`px-3 py-1.5 text-sm border-b-2 transition-colors ${
              tab === t
                ? 'border-[hsl(var(--primary))] text-[hsl(var(--primary))]'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
            onClick={() => setTab(t)}
          >
            {SOURCE_LABELS[t]}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* App grid */}
      {loading && apps.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground text-sm">加载中…</div>
      ) : apps.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground text-sm">
          没有{SOURCE_LABELS[tab]} App。确保守护进程已连接且 HuggingFace 可达。
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {apps.map((app) => {
            const isInstalled = app.source_kind === 'installed'
            const isRunning = current?.running && current?.name === app.name
            const hasUpdate = updates?.apps_with_updates.some((u) => u.app_name === app.name)
            const hfUrl = app.extra && typeof app.extra === 'object' && 'id' in app.extra
              ? `https://huggingface.co/spaces/${String((app.extra as Record<string, unknown>).id)}`
              : app.url
            return (
              <Card key={`${app.source_kind}-${app.name}`} className="flex flex-col">
                <CardHeader className="py-3 pb-2">
                  <div className="flex items-start gap-2">
                    <Package className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
                    <div className="flex-1 min-w-0">
                      <CardTitle className="text-sm truncate">{app.name}</CardTitle>
                      <CardDescription className="text-xs line-clamp-2">
                        {app.description || '无描述'}
                      </CardDescription>
                    </div>
                    <Badge variant="outline" className={sourceBadgeClass(app.source_kind)}>
                      {SOURCE_LABELS[app.source_kind as SourceTab] ?? app.source_kind}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="pt-0 mt-auto space-y-2">
                  {hfUrl && (
                    <a
                      href={hfUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[10px] text-sky-300 hover:underline inline-flex items-center gap-1"
                    >
                      <ExternalLink className="h-3 w-3" /> HuggingFace Space
                    </a>
                  )}
                  <div className="flex flex-wrap gap-1.5">
                    {!isInstalled && (
                      <Button
                        size="sm"
                        className="h-7 text-xs"
                        onClick={() => void handleInstall(app)}
                        disabled={busyApp === app.name}
                      >
                        {busyApp === app.name ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Download className="h-3 w-3" />
                        )}
                        安装
                      </Button>
                    )}
                    {isInstalled && !isRunning && (
                      <Button
                        size="sm"
                        className="h-7 text-xs"
                        onClick={() => void handleStart(app.name)}
                        disabled={busyApp === app.name}
                      >
                        {busyApp === app.name ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Play className="h-3 w-3" />
                        )}
                        启动
                      </Button>
                    )}
                    {isRunning && (
                      <Button
                        size="sm"
                        variant="destructive"
                        className="h-7 text-xs"
                        onClick={handleStop}
                        disabled={busyApp === '__current__'}
                      >
                        <Square className="h-3 w-3" />
                        停止
                      </Button>
                    )}
                    {isInstalled && hasUpdate && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs"
                        onClick={() => void handleUpdate(app.name)}
                        disabled={busyApp === app.name}
                      >
                        {busyApp === app.name ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Upload className="h-3 w-3" />
                        )}
                        更新
                      </Button>
                    )}
                    {isInstalled && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs"
                        onClick={() => void handleRemove(app.name)}
                        disabled={busyApp === app.name}
                      >
                        <Trash2 className="h-3 w-3" />
                        卸载
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        提示：HuggingFace Space 安装可能需要数十秒至数分钟，视网络与 Space 大小而定。从中国大陆访问建议设置 HF 镜像。
      </p>
    </div>
  )
}
