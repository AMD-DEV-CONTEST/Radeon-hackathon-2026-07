/**
 * Data recording stage.
 *
 * 目标：用户在当前页面里，一键把 lerobot-record 跑起来，采集 N 条 episode，
 * 不跳外部页面、不需要命令行。后端是 apps/realtime/api/record_control.py
 * 上的 /api/recording/*，它包装官方 lerobot-record CLI。
 *
 * 流程：
 *   1. 复用连接阶段选中的相机 / 串口。
 *   2. 用户填：数据集名字 + 任务描述 + episode 数 + 单条时长。
 *   3. 点"开始采集" → POST /api/recording/start。后台启动官方 lerobot-record。
 *      UI 每 2 秒轮询 /api/recording/status 拿日志和 episode 进度。
 *   4. lerobot-record 的交互方式：每条 episode 之间需要按 ↑ 或 Enter 继续。
 *      我们在 /start 时已经往它 stdin 喂了几个 \n，但真正录制是用户在真实
 *      键盘（或物理 leader 按钮）上控制。当 N 条都录完后 CLI 自己退出。
 *   5. 用户也可以点"停止"提前结束 → POST /api/recording/stop。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  FolderOpen,
  Loader2,
  Play,
  RefreshCw,
  Square,
} from 'lucide-react'
import { Button } from '../../ui/button'
import { Input } from '../../ui/input'
import { agentFetch } from '../../../lib/localAgent'
import { SetupStepCard } from '../SetupStepCard'
import { useSetup } from '../SetupProvider'

// ---------------------------------------------------------------------------
// Shape from /api/recording/*
// ---------------------------------------------------------------------------

interface SessionStatus {
  running: boolean
  session_id?: string | null
  pid?: number | null
  returncode?: number | null
  started_at?: number | null
  log_tail: string[]
  last_error?: string | null
  current_episode?: number | null
  total_episodes?: number | null
  dataset_dir?: string | null
  repo_id?: string | null
}

interface DatasetCheck {
  exists: boolean
  repo_id: string
  path?: string | null
  num_episodes?: number | null
}

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------

/** ``amd/pick-block-1630`` 这种 slug —— lerobot-record 要的是 HF 风格 id。
 *
 * ``owner`` 默认是 ``your-hf-user`` 占位符，组件挂载时会异步向
 * ``/api/hf/whoami`` 拿真实 HF 用户名替换之，避免用户落到一个自己没有
 * 写权限的 org 下（Qualia 只接受 HF dataset 仓库，所以 owner 必须匹配
 * 当前 token 能推送的 user/org）。
 */
function stamp(): string {
  const ts = new Date()
  return (
    `${ts.getFullYear()}${String(ts.getMonth() + 1).padStart(2, '0')}` +
    `${String(ts.getDate()).padStart(2, '0')}_` +
    `${String(ts.getHours()).padStart(2, '0')}${String(ts.getMinutes()).padStart(2, '0')}`
  )
}

function suggestRepoId(owner?: string | null): string {
  const who = (owner || 'your-hf-user').trim() || 'your-hf-user'
  return `${who}/so101-${stamp()}`
}

function normaliseRepoId(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._/-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/(^-|-$)/g, '')
}

function isValidRepoId(s: string): boolean {
  return /^[a-z0-9._-]+\/[a-z0-9._-]+$/.test(s)
}

// ---------------------------------------------------------------------------
// Step body.
// ---------------------------------------------------------------------------

export function Step4Record() {
  const { state, setLastDataset, setCamera, goNext } = useSetup()

  // Form state — suggest a fresh repo_id every mount so users don't
  // accidentally append to yesterday's dataset. If recording has previously
  // completed we pre-fill the last successful id as a starting point, but
  // bump the timestamp suffix so "Start recording" again produces a new
  // dataset directory instead of mixing episodes.
  const [repoId, setRepoId] = useState<string>(suggestRepoId())
  const [taskDesc, setTaskDesc] = useState<string>('抓取积木并放到托盘上')
  const [numEpisodes, setNumEpisodes] = useState<number>(5)
  const [episodeTime, setEpisodeTime] = useState<number>(30)
  const [resetTime, setResetTime] = useState<number>(5)
  const [fps, setFps] = useState<number>(Math.max(5, Math.min(60, state.camera?.fps ?? 30)))

  // Runtime state
  const [starting, setStarting] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [session, setSession] = useState<SessionStatus | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [datasetCheck, setDatasetCheck] = useState<DatasetCheck | null>(null)

  const logRef = useRef<HTMLPreElement | null>(null)

  // ---------------- Prereqs from previous steps ----------------
  const leaderPort = state.leaderPort?.port ?? null
  const followerPort = state.followerPort?.port ?? null
  const camera = state.camera

  const missing: string[] = []
  if (!camera) missing.push('摄像头')
  if (!leaderPort) missing.push('主控臂端口')
  if (!followerPort) missing.push('执行臂端口')
  if (!state.completed.teleop) missing.push('遥操作试运行')

  // ---------------- Status polling ----------------
  const fetchStatus = useCallback(async () => {
    try {
      const r = await agentFetch('/api/recording/status')
      if (!r.ok) return
      const s: SessionStatus = await r.json()
      setSession(s)
      // Once the CLI exits cleanly (rc===0 and all episodes done), auto-
      // mark this stage as complete so the user can train next.
      if (!s.running && s.returncode === 0 && s.repo_id) {
        setLastDataset(s.repo_id)
      }
    } catch {
      /* transient */
    }
  }, [setLastDataset])

  useEffect(() => {
    void fetchStatus()
    const t = window.setInterval(fetchStatus, 2000)
    return () => window.clearInterval(t)
  }, [fetchStatus])

  // Resolve the real HF owner on mount. If the user hasn't customized the
  // suggested ``your-hf-user/so101-...`` placeholder yet, swap in whatever
  // ``/api/hf/whoami`` reports — that way the default dataset id is always
  // a repo the configured HF token can actually create and Qualia can read.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await agentFetch('/api/hf/whoami')
        if (!r.ok) return
        const j: { ok?: boolean; username?: string } = await r.json()
        if (cancelled) return
        const who = j?.ok && j.username ? j.username : ''
        if (!who) return
        setRepoId((cur) => {
          // Only rewrite the owner half if the current value still looks
          // like the auto-suggestion (empty, ``your-hf-user/...`` or the
          // legacy ``botversex/...`` hardcode). Never clobber a user edit.
          const m = cur.match(/^([^/]*)\/(.+)$/)
          if (!m) return suggestRepoId(who)
          const [_, owner, name] = m
          if (owner === 'your-hf-user' || owner === 'botversex' || owner === '') {
            return `${who}/${name}`
          }
          return cur
        })
      } catch {
        /* offline / no token — keep the placeholder, user can type it. */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Auto-scroll the log pane
  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [session?.log_tail?.length])

  // ---------------- Actions ----------------
  const doStart = useCallback(async () => {
    setErrorMsg(null)
    if (!leaderPort || !followerPort) {
      setErrorMsg('请先在“连接设备”里配置好主控臂和执行臂。')
      return
    }
    const id = normaliseRepoId(repoId)
    if (!isValidRepoId(id)) {
      setErrorMsg(
        '数据集名字格式不对：应该是 ``owner/name``，只能用小写字母、数字、-、_、.',
      )
      return
    }
    if (id !== repoId) setRepoId(id)

    // Camera pre-flight + self-heal (reproducible runs, not one-shot):
    //   1. Always force-release any stale preview streams we're serving.
    //   2. Re-probe /api/camera/devices to get the *current* readable set.
    //   3. If our stored camera.deviceIndex is no longer readable, rewrite
    //      the setup store so the UI + this request both use a valid index.
    //   4. If nothing is readable, ask the user to power-cycle the camera
    //      (we can't recover kernel-level USB busy from userspace).
    let effectiveCameraIndex: number | null = camera?.deviceIndex ?? null
    let effectiveCameraFps: number = fps
    if (camera) {
      try {
        // Drop any MJPEG preview streams we're still serving.
        // This both frees V4L2 fds for lerobot-record and prevents a frozen
        // <img> from showing the user a stale "last frame".
        await agentFetch('/api/camera/stop_streams', { method: 'POST' }).catch(() => null)
        // Small settle so V4L2 actually closes the fd before the probe.
        await new Promise((r) => setTimeout(r, 200))

        // Re-probe the current camera list.
        const r = await agentFetch('/api/camera/devices')
        if (r.ok) {
          const body = (await r.json()) as {
            devices: Array<{ index: number; width?: number; height?: number; fps?: number }>
          }
          const available = body.devices
          if (available.length === 0) {
            setErrorMsg(
              '相机当前不可用（所有 /dev/video* 都无法打开）。\n' +
                '排查：\n' +
                '  1) 看看终端里 ls -l /dev/video*，确认设备节点存在；\n' +
                '  2) 拔掉 USB 相机再插回去（内核级 busy 只能这样恢复）；\n' +
              '  3) 回到“连接设备”重新扫描摄像头。',
            )
            return
          }
          const chosen =
            available.find((d) => d.index === camera.deviceIndex) ?? available[0]
          effectiveCameraIndex = chosen.index
          effectiveCameraFps = Math.max(
            5,
            Math.min(60, Math.round(chosen.fps || fps) || fps),
          )

          // If we had to switch index, overwrite setup store so the
          // next start/refresh is self-consistent (no more "stuck on old
          // index 1" ghost state).
          if (chosen.index !== camera.deviceIndex) {
            setCamera({
              deviceIndex: chosen.index,
              label: `Camera ${chosen.index} (${chosen.width ?? 640}x${
                chosen.height ?? 480
              }@${effectiveCameraFps})`,
              width: chosen.width ?? 640,
              height: chosen.height ?? 480,
              fps: effectiveCameraFps,
            })
            setErrorMsg(
              `原来选的摄像头 index=${camera.deviceIndex} 现在打不开，已自动切换到 index=${chosen.index}。再点一次“开始采集”即可。`,
            )
            setFps(effectiveCameraFps)
            // Do NOT auto-submit — give the user one click of confirmation
            // so they know we swapped the device. Reproducible and obvious.
            return
          }
          // Also align fps if the hardware reports something different than
          // what the form has (e.g. 25 vs 30).
          if (effectiveCameraFps !== fps) setFps(effectiveCameraFps)
        }
      } catch {
        /* 网络抖动就让后端再判一次 */
      }
    }

    setStarting(true)
    try {
      const body = {
        leader_port: leaderPort,
        follower_port: followerPort,
        cameras: effectiveCameraIndex != null
          ? [
              {
                name: 'top',
                index_or_path: effectiveCameraIndex,
                width: 640,
                height: 480,
                fps: effectiveCameraFps,
              },
            ]
          : [],
        repo_id: id,
        single_task: taskDesc.trim() || 'so101 demonstration',
        num_episodes: numEpisodes,
        episode_time_s: episodeTime,
        reset_time_s: resetTime,
        fps,
        push_to_hub: false,
      }
      const r = await agentFetch('/api/recording/start', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) {
        const detail = await r.json().catch(() => ({}))
        const d = detail?.detail
        let msg: string
        if (typeof d === 'string') {
          msg = d
        } else if (d?.code === 'camera_unavailable') {
          const miss = Array.isArray(d.missing) ? d.missing : []
          const avail = Array.isArray(d.available_indices) ? d.available_indices : []
          msg =
            `${d.message}\n` +
            `请求的相机：${miss
              .map((m: { name?: string; requested_index?: number }) =>
                `${m.name ?? '?'}=index ${m.requested_index}`,
              )
              .join(', ')}\n` +
            (avail.length > 0
              ? `当前可用的 index：${avail.join(', ')} —— 请回“连接设备”重新选一下。`
              : '当前没有任何可用相机 —— 请回“连接设备”重新扫描。')
        } else if (d?.code === 'port_in_use') {
          msg = `串口被占用：${d.message ?? ''}\n通常是 teleop 还没停。请先结束遥控再采集。`
        } else {
          msg = d?.message ?? `请求失败（HTTP ${r.status}）`
        }
        setErrorMsg(msg)
        return
      }
      const s: SessionStatus = await r.json()
      setSession(s)
    } catch (e) {
      setErrorMsg(`启动失败：${(e as Error).message}`)
    } finally {
      setStarting(false)
    }
  }, [
    leaderPort,
    followerPort,
    camera,
    repoId,
    taskDesc,
    numEpisodes,
    episodeTime,
    resetTime,
    fps,
    setCamera,
  ])

  const doStop = useCallback(async () => {
    setStopping(true)
    setErrorMsg(null)
    try {
      const r = await agentFetch('/api/recording/stop', { method: 'POST' })
      if (r.ok) {
        const s: SessionStatus = await r.json()
        setSession(s)
      }
    } catch (e) {
      setErrorMsg(`停止失败：${(e as Error).message}`)
    } finally {
      setStopping(false)
    }
  }, [])

  const doCheckDataset = useCallback(async () => {
    const id = normaliseRepoId(repoId)
    try {
      const r = await agentFetch(`/api/recording/dataset_check?repo_id=${encodeURIComponent(id)}`)
      if (r.ok) setDatasetCheck(await r.json())
    } catch {
      /* ignore */
    }
  }, [repoId])

  const markDoneManually = useCallback(() => {
    const id = normaliseRepoId(repoId)
    if (isValidRepoId(id)) setLastDataset(id)
  }, [repoId, setLastDataset])

  // ---------------- Derived UI state ----------------
  const running = !!session?.running
  const episode = session?.current_episode ?? 0
  const total = session?.total_episodes ?? numEpisodes
  const progressPct = total > 0 ? Math.min(100, (episode / total) * 100) : 0

  // ---------------- Render ----------------
  return (
    <SetupStepCard
      stepId="record"
      title="录一段示教"
      description="录几条你亲手示范的动作。采集完成后，下一阶段会直接带着这个数据集去训练。"
      nextDisabled={!state.completed.record}
      onNext={goNext}
    >
      <div className="grid gap-4 text-sm">
        {/* -------- 前置条件 -------- */}
        {missing.length > 0 && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-amber-200">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
            <div>
              还差这些东西才能采集：
              <ul className="mt-1 list-disc pl-5">
                {missing.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
              请先回到前面的步骤把它们配置好。
            </div>
          </div>
        )}

        <details className="rounded-lg border border-[hsl(var(--border))]/60 bg-[hsl(var(--card))]/40 px-3 py-2">
          <summary className="cursor-pointer select-none text-sm font-medium">
            当前设备
          </summary>
          <ul className="mt-2 grid gap-1 text-[hsl(var(--muted-foreground))]">
            <li>
              相机：
              <code className="ml-1 font-mono text-[hsl(var(--foreground))]">
                {camera ? `${camera.label} (index ${camera.deviceIndex})` : '未选择'}
              </code>
            </li>
            <li>
              主控臂：
              <code className="ml-1 font-mono text-[hsl(var(--foreground))]">{leaderPort ?? '—'}</code>
            </li>
            <li>
              执行臂：
              <code className="ml-1 font-mono text-[hsl(var(--foreground))]">{followerPort ?? '—'}</code>
            </li>
          </ul>
        </details>

        {/* -------- 参数表单 -------- */}
        <div className="grid gap-3 rounded-lg border border-[hsl(var(--border))]/60 bg-[hsl(var(--card))]/40 p-3">
          <div className="font-medium">录制内容</div>

          <label className="grid gap-1">
            <span className="text-xs text-[hsl(var(--muted-foreground))]">
              数据集名字
            </span>
            <div className="flex gap-2">
              <Input
                value={repoId}
                onChange={(e) => setRepoId(e.target.value)}
                placeholder="your-hf-user/pick-block"
                className="font-mono"
                disabled={running}
              />
              <Button type="button" variant="secondary" onClick={doCheckDataset} title="检查本地是否已有同名数据集">
                <RefreshCw className="h-4 w-4" /> 检查
              </Button>
            </div>
            {datasetCheck && (
              <div className="text-xs">
                {datasetCheck.exists ? (
                  <span className="text-amber-400">
                    本地已存在：{datasetCheck.path}
                    {typeof datasetCheck.num_episodes === 'number'
                      ? `（${datasetCheck.num_episodes} 条 episode）`
                      : ''}
                    —— 再次采集会追加 / 覆盖，注意。
                  </span>
                ) : (
                  <span className="text-emerald-400">本地干净，可以放心开录。</span>
                )}
              </div>
            )}
          </label>

          <label className="grid gap-1">
            <span className="text-xs text-[hsl(var(--muted-foreground))]">任务描述（给模型看的自然语言指令）</span>
            <Input
              value={taskDesc}
              onChange={(e) => setTaskDesc(e.target.value)}
              placeholder="抓取积木并放到托盘上"
              disabled={running}
            />
          </label>

          <details className="rounded-md border border-[hsl(var(--border))]/50 px-3 py-2">
            <summary className="cursor-pointer select-none text-xs font-medium text-[hsl(var(--muted-foreground))]">
              高级参数
            </summary>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <label className="grid gap-1">
                <span className="text-xs text-[hsl(var(--muted-foreground))]">采集条数</span>
                <Input
                  type="number"
                  min={1}
                  max={200}
                  value={numEpisodes}
                  onChange={(e) => setNumEpisodes(Number(e.target.value) || 1)}
                  disabled={running}
                />
              </label>
              <label className="grid gap-1">
                <span className="text-xs text-[hsl(var(--muted-foreground))]">单条时长 (秒)</span>
                <Input
                  type="number"
                  min={5}
                  max={600}
                  value={episodeTime}
                  onChange={(e) => setEpisodeTime(Number(e.target.value) || 10)}
                  disabled={running}
                />
              </label>
              <label className="grid gap-1">
                <span className="text-xs text-[hsl(var(--muted-foreground))]">条间复位 (秒)</span>
                <Input
                  type="number"
                  min={0}
                  max={120}
                  value={resetTime}
                  onChange={(e) => setResetTime(Number(e.target.value) || 0)}
                  disabled={running}
                />
              </label>
              <label className="grid gap-1">
                <span className="text-xs text-[hsl(var(--muted-foreground))]">帧率 FPS</span>
                <Input
                  type="number"
                  min={5}
                  max={60}
                  value={fps}
                  onChange={(e) => setFps(Number(e.target.value) || 30)}
                  disabled={running}
                />
              </label>
            </div>
          </details>
        </div>

        {/* -------- 控制按钮 + 状态 -------- */}
        <div className="flex flex-wrap items-center gap-3">
          {!running ? (
            <Button onClick={doStart} disabled={starting || missing.length > 0} className="min-w-[9rem]">
              {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              {starting ? '正在启动…' : '开始采集'}
            </Button>
          ) : (
            <Button onClick={doStop} variant="destructive" disabled={stopping} className="min-w-[9rem]">
              {stopping ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />}
              {stopping ? '正在停止…' : '停止采集'}
            </Button>
          )}

          <div className="flex items-center gap-2 text-xs">
            <CircleDot className={running ? 'h-3 w-3 text-emerald-400' : 'h-3 w-3 text-[hsl(var(--muted-foreground))]'} />
            <span className="text-[hsl(var(--muted-foreground))]">
              {running
                ? `运行中 · pid=${session?.pid ?? '-'} · episode ${episode}/${total}`
                : session?.returncode != null
                ? `已结束 · rc=${session.returncode}${session.returncode === 0 ? '（成功）' : '（异常）'}`
                : '未启动'}
            </span>
          </div>

          {state.completed.record && state.lastDatasetId && (
            <div className="ml-auto flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-xs text-emerald-300">
              <CheckCircle2 className="h-3.5 w-3.5" />
              已完成：<code className="font-mono">{state.lastDatasetId}</code>
            </div>
          )}
        </div>

        {/* -------- 进度条 -------- */}
        {running && (
          <div>
            <div className="mb-1 flex justify-between text-xs text-[hsl(var(--muted-foreground))]">
              <span>episode 进度</span>
              <span>
                {episode} / {total}
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded bg-[hsl(var(--border))]/40">
              <div
                className="h-full bg-emerald-500 transition-all"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        )}

        {/* -------- 错误提示 -------- */}
        {errorMsg && (
          <div className="flex items-start gap-2 rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
            <div className="whitespace-pre-wrap">{errorMsg}</div>
          </div>
        )}
        {session?.last_error && !errorMsg && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-amber-200">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
            <div>
              子进程报了一条错误：
              <pre className="mt-1 overflow-x-auto whitespace-pre-wrap font-mono text-xs">
                {session.last_error}
              </pre>
            </div>
          </div>
        )}

        {/* -------- 日志面板 -------- */}
        {(running || session?.log_tail?.length) && (
          <div className="rounded-lg border border-[hsl(var(--border))]/60 bg-black/60 p-0">
            <div className="flex items-center justify-between border-b border-[hsl(var(--border))]/60 px-3 py-1 text-xs text-[hsl(var(--muted-foreground))]">
              <span className="font-medium">lerobot-record 日志（最新 {session?.log_tail?.length ?? 0} 行）</span>
              {session?.dataset_dir && (
                <span className="flex items-center gap-1">
                  <FolderOpen className="h-3 w-3" />
                  <code className="font-mono text-[10px]">{session.dataset_dir}</code>
                </span>
              )}
            </div>
            <pre
              ref={logRef}
              className="max-h-64 overflow-auto p-3 text-[11px] leading-snug text-emerald-200"
            >
              {(session?.log_tail ?? []).join('\n') || '（暂无输出）'}
            </pre>
          </div>
        )}

        {/* -------- 手动标记完成（极端情况兜底） -------- */}
        {!running && !state.completed.record && session?.repo_id && (
          <div className="flex items-center justify-between rounded-lg border border-[hsl(var(--border))]/60 bg-[hsl(var(--card))]/40 p-3">
            <span className="text-xs text-[hsl(var(--muted-foreground))]">
              如果你确认已经采完 <code className="font-mono">{session.repo_id}</code>，可以手动点下面的按钮继续下一步。
            </span>
            <Button size="sm" variant="secondary" onClick={markDoneManually}>
              <CheckCircle2 className="h-4 w-4" /> 标记完成
            </Button>
          </div>
        )}
      </div>
    </SetupStepCard>
  )
}
