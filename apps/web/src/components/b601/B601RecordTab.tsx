/**
 * B601 示教录制 — 对齐 SO-101 Step4Record 的官方 LeRobot 手感：
 *   owner/name 两段 repo_id → ~/.cache/huggingface/lerobot/<owner>/<name>/
 *   轮询进度 / 日志，结束后可进训练页。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  FolderOpen,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  SkipForward,
  Square,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { B601RecordCoach } from './B601RecordCoach'
import { B601EpisodeReview } from './B601EpisodeReview'
import {
  b601DatasetCheck,
  b601DatasetEpisodes,
  b601DatasetFrame,
  b601DatasetPush,
  b601DatasetsList,
  b601DatasetVideos,
  b601DatasetVizStart,
  b601DatasetVizStatus,
  b601DatasetVizStop,
  b601RecordMark,
  b601RecordRerecord,
  b601RecordSkip,
  b601RecordStart,
  b601RecordStatus,
  b601RecordStop,
  b601TeleopStopSafe,
  isValidB601RepoId,
  normaliseB601RepoId,
  suggestB601RepoId,
  type B601CameraPrefs,
  type B601DatasetCheck,
  type B601DatasetListItem,
  type B601DatasetPushResult,
  type B601DatasetVideo,
  type B601EpisodeVideo,
  type B601Session,
} from '../../lib/b601Api'
interface Props {
  camerasAvailable: number
  cameraPrefs: B601CameraPrefs
  teleopRunning: boolean
  /** Optional prefix for suggested repo, e.g. b601-dm */
  repoPrefix?: string
  /** Fired when record CLI exits with rc=0 (or user marks done). */
  onDatasetReady?: (repoId: string) => void
  /** Keep parent stage / emergency bar in sync. */
  onRunningChange?: (running: boolean) => void
  lastDatasetId?: string | null
  /** When true, hide the “export snapshot” affordance. */
  hideSnapshot?: boolean
  onSnapshot?: (repoId: string) => void
  /** Drive virtual arm from video timeline. */
  onPlaybackJoints?: (joints: Record<string, number> | null) => void
  onPlaybackActiveChange?: (active: boolean) => void
  /** Short line for left stage overlay while recording. */
  onCoachLine?: (line: string | null) => void
}

export function B601RecordTab({
  camerasAvailable,
  cameraPrefs,
  teleopRunning,
  repoPrefix = 'b601',
  onDatasetReady,
  onRunningChange,
  lastDatasetId,
  hideSnapshot,
  onSnapshot,
  onPlaybackJoints,
  onPlaybackActiveChange,
  onCoachLine,
}: Props) {
  const [repoId, setRepoId] = useState(() => suggestB601RepoId(repoPrefix))
  const [taskDesc, setTaskDesc] = useState('抓取演示')
  const [numEpisodes, setNumEpisodes] = useState(5)
  const [episodeTime, setEpisodeTime] = useState(30)
  const [resetTime, setResetTime] = useState(5)
  const [starting, setStarting] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [skipping, setSkipping] = useState(false)
  const [session, setSession] = useState<B601Session | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [datasetCheck, setDatasetCheck] = useState<B601DatasetCheck | null>(null)
  const [previewVideos, setPreviewVideos] = useState<B601DatasetVideo[]>([])
  const [previewPlaying, setPreviewPlaying] = useState(false)
  const [phaseSince, setPhaseSince] = useState<number | null>(null)
  const [nowTick, setNowTick] = useState(() => Date.now())
  const [hubRepoId, setHubRepoId] = useState('')
  const [hfToken, setHfToken] = useState('')
  /** Qualia cloud train needs a public HF dataset (or Qualia-side HF token). Default public. */
  const [pushPrivate, setPushPrivate] = useState(false)
  const [pushing, setPushing] = useState(false)
  const [pushResult, setPushResult] = useState<B601DatasetPushResult | null>(null)
  const [hfOpen, setHfOpen] = useState(false)
  const [logOpen, setLogOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(true)
  const [history, setHistory] = useState<B601DatasetListItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  /** browse = 只看往期；capture = 新采集表单。录制中强制 capture。 */
  const [dataPane, setDataPane] = useState<'browse' | 'capture'>('browse')
  const [vizEpisode, setVizEpisode] = useState(0)
  const [vizBusy, setVizBusy] = useState(false)
  const [vizRunning, setVizRunning] = useState(false)
  const [vizHint, setVizHint] = useState<string | null>(null)
  const [marking, setMarking] = useState(false)
  const [rerecording, setRerecording] = useState(false)
  const [markHint, setMarkHint] = useState<string | null>(null)
  const [resetPreview, setResetPreview] = useState<B601EpisodeVideo[]>([])
  const [reviewKey, setReviewKey] = useState(0)
  const [reviewSummary, setReviewSummary] = useState<{
    num_episodes: number
    bad_count: number
    unmarked_count: number
  } | null>(null)
  const logRef = useRef<HTMLPreElement | null>(null)
  const completedRef = useRef<string | null>(null)
  const videoRefs = useRef<(HTMLVideoElement | null)[]>([])
  const syncingSeek = useRef(false)
  const lastFrameFetch = useRef(0)
  const frameReqSeq = useRef(0)
  const playbackRepoRef = useRef<string | null>(null)
  const markedThisEpisodeRef = useRef<number | null>(null)

  const noCamera = camerasAvailable === 0
  const running = !!session?.running
  const episode = session?.episode_current ?? 0
  const total = session?.episode_total ?? numEpisodes
  const progressPct = total > 0 ? Math.min(100, (episode / total) * 100) : 0
  const phase = session?.record_phase
  const readyDataset = lastDatasetId || (session?.returncode === 0 ? session.repo_id : null)
  const phaseElapsedRaw =
    phaseSince != null && (phase === 'recording' || phase === 'resetting')
      ? Math.max(0, Math.floor((nowTick - phaseSince) / 1000))
      : session?.phase_elapsed_s != null
        ? Math.max(0, Math.floor(session.phase_elapsed_s))
        : 0
  const phaseTargetS =
    phase === 'recording'
      ? (session?.episode_time_s ?? episodeTime)
      : phase === 'resetting'
        ? (session?.reset_time_s ?? resetTime)
        : null
  /** Display clock stops at target; overtime is a separate hint (phase switch lag). */
  const phaseElapsedS =
    phaseTargetS != null ? Math.min(phaseElapsedRaw, phaseTargetS) : phaseElapsedRaw
  const phaseOvertime = phaseTargetS != null && phaseElapsedRaw > phaseTargetS
  /** LeRobot crashes if you skip before any frame — keep skip off for first 2s of recording. */
  const skipTooEarly =
    phase === 'recording' && phaseSince != null && nowTick - phaseSince < 2000
  const skipDisabled = skipping || stopping || skipTooEarly || phase === 'saving' || phase === 'starting'

  const loadPreview = useCallback(async (id: string) => {
    try {
      const r = await b601DatasetVideos(id)
      setPreviewVideos(r.videos ?? [])
      setPreviewPlaying(false)
      videoRefs.current = []
    } catch {
      setPreviewVideos([])
    }
  }, [])

  const syncVideosTo = useCallback((t: number, except?: HTMLVideoElement | null) => {
    if (syncingSeek.current) return
    syncingSeek.current = true
    for (const v of videoRefs.current) {
      if (!v || v === except) continue
      if (Math.abs(v.currentTime - t) > 0.08) v.currentTime = t
    }
    syncingSeek.current = false
  }, [])

  const syncArmToVideoTime = useCallback(
    (
      t: number,
      opts?: { force?: boolean; episode_index?: number; t_rel?: number },
    ) => {
      const id = playbackRepoRef.current
      if (!id || !isValidB601RepoId(id) || !onPlaybackJoints) return
      const now = performance.now()
      if (!opts?.force && now - lastFrameFetch.current < 28) return
      lastFrameFetch.current = now
      const seq = ++frameReqSeq.current
      void b601DatasetFrame(id, t, {
        episode_index: opts?.episode_index,
        t_rel: opts?.t_rel,
      })
        .then((r) => {
          if (seq !== frameReqSeq.current) return
          if (r.ok && r.joints) onPlaybackJoints(r.joints)
        })
        .catch(() => {})
    },
    [onPlaybackJoints],
  )

  useEffect(() => {
    playbackRepoRef.current = readyDataset || normaliseB601RepoId(repoId)
  }, [readyDataset, repoId])

  useEffect(() => {
    // Playing video → active; pausing keeps last pose so 3D doesn't snap to zero.
    if (previewPlaying) onPlaybackActiveChange?.(true)
  }, [previewPlaying, onPlaybackActiveChange])

  const playAllPreview = useCallback(async () => {
    const vids = videoRefs.current.filter(Boolean) as HTMLVideoElement[]
    if (!vids.length) return
    const t = vids[0].currentTime
    for (const v of vids) {
      v.currentTime = t
      try {
        await v.play()
      } catch {
        /* autoplay policy */
      }
    }
    setPreviewPlaying(true)
    onPlaybackActiveChange?.(true)
    syncArmToVideoTime(t)
  }, [onPlaybackActiveChange, syncArmToVideoTime])

  const pauseAllPreview = useCallback(() => {
    for (const v of videoRefs.current) v?.pause()
    setPreviewPlaying(false)
    onPlaybackActiveChange?.(false)
  }, [onPlaybackActiveChange])

  const restartAllPreview = useCallback(() => {
    for (const v of videoRefs.current) {
      if (!v) continue
      v.currentTime = 0
    }
    void playAllPreview()
  }, [playAllPreview])

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    try {
      const r = await b601DatasetsList(repoPrefix)
      setHistory(r.items ?? [])
    } catch {
      setHistory([])
    } finally {
      setHistoryLoading(false)
    }
  }, [repoPrefix])

  const fetchStatus = useCallback(async () => {
    try {
      const s = await b601RecordStatus()
      setSession(s)
      onRunningChange?.(!!s.running)
      if (!s.running && s.returncode === 0 && s.repo_id) {
        if (completedRef.current !== s.repo_id) {
          completedRef.current = s.repo_id
          onDatasetReady?.(s.repo_id)
          void loadPreview(s.repo_id)
          void loadHistory()
          setReviewKey((k) => k + 1)
        }
      }
    } catch {
      /* transient */
    }
  }, [loadHistory, loadPreview, onDatasetReady, onRunningChange])

  useEffect(() => {
    void fetchStatus()
    // Faster poll while recording so coach countdown / phase flips feel live.
    const ms = running ? 500 : 2000
    const t = window.setInterval(fetchStatus, ms)
    return () => window.clearInterval(t)
  }, [fetchStatus, running])

  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [session?.log_tail?.length])

  useEffect(() => {
    if (phase === 'recording' || phase === 'resetting') {
      setPhaseSince(Date.now())
    } else {
      setPhaseSince(null)
    }
  }, [phase, episode])

  useEffect(() => {
    if (phase !== 'recording' && phase !== 'resetting' && phase !== 'saving' && phase !== 'starting') {
      return
    }
    const t = window.setInterval(() => setNowTick(Date.now()), 200)
    return () => window.clearInterval(t)
  }, [phase])

  useEffect(() => {
    if (!onCoachLine) return
    if (!running && !starting) {
      onCoachLine(null)
      return
    }
    const ep = episode > 0 ? `${episode}/${total || '?'}` : `—/${total || '?'}`
    const remain =
      phaseTargetS != null ? Math.max(0, phaseTargetS - phaseElapsedS) : null
    let line: string
    if (starting && !running) line = '请准备 · 正在启动'
    else if (phase === 'starting') line = '请准备 · 连接硬件中'
    else if (phase === 'recording' && phaseElapsedS < 3) {
      line = `请准备 ${Math.max(1, 3 - Math.floor(phaseElapsedS))} · 正在录第 ${ep} 条`
    } else if (phase === 'recording') {
      line =
        remain != null
          ? `正在录第 ${ep} 条 · 剩 ${remain}s`
          : `正在录第 ${ep} 条`
    } else if (phase === 'resetting') {
      line =
        remain != null && remain <= 2
          ? `第 ${ep} 条复位即将结束 · 剩 ${remain}s`
          : remain != null
            ? `第 ${ep} 条复位中 · 剩 ${remain}s`
            : `第 ${ep} 条复位中`
    } else if (phase === 'saving')
      line =
        episode > 0
          ? `正在保存第 ${ep} 条（刚录完，不是下一条）`
          : '保存中 · 写视频中'
    else if (phase === 'done') line = '采集完成'
    else if (phase === 'error') line = '采集出错'
    else line = episode > 0 ? `正在处理第 ${ep} 条` : '采集中'
    onCoachLine(line)
  }, [
    onCoachLine,
    running,
    starting,
    phase,
    episode,
    total,
    phaseElapsedS,
    phaseTargetS,
  ])

  useEffect(() => {
    const id = readyDataset || normaliseB601RepoId(repoId)
    if (!id.includes('/')) return
    const name = id.split('/')[1] || id
    setHubRepoId((prev) => (prev ? prev : `YOUR_HF_USERNAME/${name}`))
  }, [readyDataset, repoId])

  const doStart = useCallback(async () => {
    setErrorMsg(null)
    const id = normaliseB601RepoId(repoId)
    if (!isValidB601RepoId(id)) {
      setErrorMsg(
        '数据集名字格式不对：必须是 owner/name（两段、一个斜杠），例如 local/b601-dm-pick01。\n' +
          '不要用 local/b601/xxx —— 三段路径进不了官方数据集列表。',
      )
      return
    }
    if (id !== repoId) setRepoId(id)
    if (noCamera) {
      setErrorMsg('未检测到可用摄像头。请先到「视觉」Tab 选好正面/侧面相机并保存。')
      return
    }

    setStarting(true)
    setSession(null) // clear stale rc=1 / 「出错了」教练板
    try {
      // Avoid LeRobot FileExistsError: empty/partial dirs from a failed start still block create.
      let startId = id
      try {
        const chk = await b601DatasetCheck(id)
        if (chk.exists) {
          startId = suggestB601RepoId(repoPrefix)
          setRepoId(startId)
          setErrorMsg(null)
        }
      } catch {
        /* offline check — backend also auto-bumps */
      }
      if (teleopRunning) await b601TeleopStopSafe()
      const s = await b601RecordStart({
        repo_id: startId,
        single_task: taskDesc.trim() || 'b601 demonstration',
        num_episodes: numEpisodes,
        episode_time_s: episodeTime,
        reset_time_s: resetTime,
        camera_indices: cameraPrefs.indices,
      })
      if (s.repo_id && s.repo_id !== startId) {
        setRepoId(s.repo_id)
      }
      setSession(s)
      onRunningChange?.(!!s.running)
      completedRef.current = null
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : '启动录制失败')
    } finally {
      setStarting(false)
    }
  }, [
    repoId,
    repoPrefix,
    noCamera,
    teleopRunning,
    taskDesc,
    numEpisodes,
    episodeTime,
    resetTime,
    cameraPrefs.indices,
    onRunningChange,
  ])

  const doStop = useCallback(async () => {
    setStopping(true)
    setErrorMsg(null)
    try {
      const s = await b601RecordStop()
      setSession(s)
      onRunningChange?.(!!s.running)
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : '停止失败')
    } finally {
      setStopping(false)
    }
  }, [onRunningChange])

  const doSkip = useCallback(async () => {
    setSkipping(true)
    setErrorMsg(null)
    try {
      const s = await b601RecordSkip()
      setSession(s)
    } catch (e) {
      setErrorMsg(
        (e instanceof Error ? e.message : '跳过失败') +
          '\n也可在键盘上按 →（右方向键）跳过当前录制/复位段。',
      )
    } finally {
      setSkipping(false)
    }
  }, [])

  /** 1-based UI episode → 0-based index of the episode just finished / being reviewed. */
  const markEpisodeIndex = episode > 0 ? episode - 1 : null

  const doMark = useCallback(
    async (verdict: 'ok' | 'bad') => {
      const id = normaliseB601RepoId(repoId)
      if (markEpisodeIndex == null) return
      setMarking(true)
      setErrorMsg(null)
      try {
        await b601RecordMark({
          repo_id: id,
          episode_index: markEpisodeIndex,
          verdict,
        })
        markedThisEpisodeRef.current = markEpisodeIndex
        setMarkHint(
          verdict === 'bad'
            ? `第 ${markEpisodeIndex + 1} 条已标「不满意」— 结束后可删除`
            : `第 ${markEpisodeIndex + 1} 条已标「可用」`,
        )
        setReviewKey((k) => k + 1)
      } catch (e) {
        setErrorMsg(e instanceof Error ? e.message : '标记失败')
      } finally {
        setMarking(false)
      }
    },
    [markEpisodeIndex, repoId],
  )

  const doRerecord = useCallback(async () => {
    setRerecording(true)
    setErrorMsg(null)
    try {
      const s = await b601RecordRerecord()
      setSession(s)
      setMarkHint('已请求重录本条（←）')
      if (markEpisodeIndex != null) {
        try {
          await b601RecordMark({
            repo_id: normaliseB601RepoId(repoId),
            episode_index: markEpisodeIndex,
            verdict: 'clear',
          })
        } catch {
          /* ignore */
        }
      }
    } catch (e) {
      setErrorMsg(
        (e instanceof Error ? e.message : '重录失败') +
          '\n也可在键盘上按 ←（左方向键）重录当前条。',
      )
    } finally {
      setRerecording(false)
    }
  }, [markEpisodeIndex, repoId])

  // During reset/saving: async load last episode preview if encode finished.
  useEffect(() => {
    if (!(phase === 'resetting' || phase === 'saving')) {
      setResetPreview([])
      return
    }
    if (markEpisodeIndex == null) return
    const id = normaliseB601RepoId(repoId)
    let cancelled = false
    const t = window.setTimeout(() => {
      void b601DatasetEpisodes(id)
        .then((r) => {
          if (cancelled) return
          const ep = r.episodes?.find((e) => e.episode_index === markEpisodeIndex)
          setResetPreview(ep?.videos ?? [])
        })
        .catch(() => {
          if (!cancelled) setResetPreview([])
        })
    }, 400)
    return () => {
      cancelled = true
      window.clearTimeout(t)
    }
  }, [phase, markEpisodeIndex, repoId, episode])

  useEffect(() => {
    markedThisEpisodeRef.current = null
    setMarkHint(null)
  }, [episode])

  const doCheckDataset = useCallback(async () => {
    const id = normaliseB601RepoId(repoId)
    try {
      setDatasetCheck(await b601DatasetCheck(id))
      void loadPreview(id)
      setReviewKey((k) => k + 1)
    } catch {
      setDatasetCheck(null)
    }
  }, [loadPreview, repoId])

  const clearPlayback = useCallback(() => {
    pauseAllPreview()
    setPreviewPlaying(false)
    onPlaybackJoints?.(null)
    onPlaybackActiveChange?.(false)
    playbackRepoRef.current = null
  }, [onPlaybackActiveChange, onPlaybackJoints, pauseAllPreview])

  const openPastDataset = useCallback(
    (id: string) => {
      setDataPane('browse')
      setHistoryOpen(false) // 选中后收起列表，把空间留给视频
      setRepoId(id)
      onDatasetReady?.(id)
      void loadPreview(id)
      void b601DatasetCheck(id).then(setDatasetCheck).catch(() => setDatasetCheck(null))
      setReviewKey((k) => k + 1)
      // 3D 由审片组件按「本条 front 时间轴」驱动；先清掉旧姿态避免串条
      clearPlayback()
      playbackRepoRef.current = id
    },
    [clearPlayback, loadPreview, onDatasetReady],
  )

  useEffect(() => {
    if (running) setDataPane('capture')
  }, [running])

  useEffect(() => {
    void loadHistory()
  }, [loadHistory])

  useEffect(() => {
    if (readyDataset) void loadPreview(readyDataset)
  }, [loadPreview, readyDataset])

  useEffect(() => {
    if (dataPane !== 'browse' || running) return
    let cancelled = false
    const tick = async () => {
      try {
        const s = await b601DatasetVizStatus()
        if (!cancelled) setVizRunning(Boolean(s.running))
      } catch {
        /* ignore */
      }
    }
    void tick()
    const t = window.setInterval(() => void tick(), 4000)
    return () => {
      cancelled = true
      window.clearInterval(t)
    }
  }, [dataPane, running])

  const openRerunViz = useCallback(async () => {
    const id = normaliseB601RepoId(readyDataset || repoId)
    if (!isValidB601RepoId(id)) {
      setVizHint('请先选一条往期数据集')
      return
    }
    setVizBusy(true)
    setVizHint(null)
    setErrorMsg(null)
    try {
      const r = await b601DatasetVizStart({ repo_id: id, episode_index: vizEpisode })
      setVizRunning(Boolean(r.running))
      setVizHint(
        r.running
          ? `已打开 Rerun：${id} · episode ${vizEpisode}（本机新窗口，含相机+state/action）`
          : r.message || '已启动',
      )
      if (r.last_error) setErrorMsg(r.last_error)
    } catch (e) {
      setVizRunning(false)
      setErrorMsg(e instanceof Error ? e.message : '打开 Rerun 失败')
    } finally {
      setVizBusy(false)
    }
  }, [readyDataset, repoId, vizEpisode])

  const stopRerunViz = useCallback(async () => {
    setVizBusy(true)
    try {
      await b601DatasetVizStop()
      setVizRunning(false)
      setVizHint('已停止推流（Rerun 窗口可手动关掉）')
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : '停止失败')
    } finally {
      setVizBusy(false)
    }
  }, [])

  const markDoneManually = useCallback(() => {
    const id = normaliseB601RepoId(repoId)
    if (isValidB601RepoId(id)) onDatasetReady?.(id)
  }, [repoId, onDatasetReady])

  const doPush = useCallback(async () => {
    const localId = normaliseB601RepoId(readyDataset || repoId)
    const hub = hubRepoId.trim()
    setPushing(true)
    setPushResult(null)
    setErrorMsg(null)
    try {
      if (!isValidB601RepoId(localId)) {
        throw new Error('本地数据集 ID 格式不对')
      }
      if (!isValidB601RepoId(hub) || hub.startsWith('local/') || hub.includes('YOUR_HF_USERNAME')) {
        throw new Error('请把 Hub 数据集 ID 改成你的 HF 用户名/数据集名，例如 ethanxxx/b601-dm-pick01')
      }
      const r = await b601DatasetPush({
        repo_id: localId,
        hub_repo_id: hub,
        token: hfToken.trim() || undefined,
        private: pushPrivate,
      })
      setPushResult(r)
      if (!r.ok) setErrorMsg(r.message)
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : '上传失败')
    } finally {
      setPushing(false)
    }
  }, [readyDataset, repoId, hubRepoId, hfToken, pushPrivate])

  const browsing = dataPane === 'browse' && !running

  return (
    <div className="space-y-4 text-sm">
      <div className="flex gap-1 rounded-lg border border-white/10 bg-black/30 p-1">
        <button
          type="button"
          disabled={running}
          onClick={() => setDataPane('browse')}
          className={`flex-1 rounded-md px-2 py-1.5 text-xs transition-colors ${
            browsing
              ? 'bg-[hsl(var(--primary))]/20 font-medium text-foreground'
              : 'text-muted-foreground hover:text-foreground/80'
          }`}
        >
          看往期
        </button>
        <button
          type="button"
          onClick={() => {
            setDataPane('capture')
            clearPlayback()
            setPreviewVideos([])
            if (!running) setRepoId(suggestB601RepoId(repoPrefix))
          }}
          className={`flex-1 rounded-md px-2 py-1.5 text-xs transition-colors ${
            !browsing
              ? 'bg-[hsl(var(--primary))]/20 font-medium text-foreground'
              : 'text-muted-foreground hover:text-foreground/80'
          }`}
        >
          新采集
        </button>
      </div>

      {browsing ? (
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          选往期回看；开录请切「新采集」。
        </p>
      ) : (
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          配置任务与时长后开始采集。数据写入{' '}
          <code className="text-[10px]">~/.cache/huggingface/lerobot/&lt;owner&gt;/&lt;name&gt;/</code>
        </p>
      )}

      {!browsing && (
        <div className="rounded-md border border-white/10 bg-black/25 px-3 py-2 text-[11px] text-muted-foreground">
          相机来自「视觉」：正面 Cam {cameraPrefs.front} · 侧面 Cam {cameraPrefs.side}
          {cameraPrefs.top == null ? '' : ` · 顶部 Cam ${cameraPrefs.top}`}
          {noCamera ? '（未检测到可用摄像头）' : ' · 要改请先回视觉页'}
        </div>
      )}

      {noCamera && !browsing && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          未检测到可用摄像头。接好 USB 相机后去「视觉」Tab 预览并保存。
        </div>
      )}

      {teleopRunning && !browsing && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          遥操仍在运行 — 点「开始采集」会先自动停止遥操。
        </div>
      )}

      {browsing && (
      <div className="rounded-md border border-white/10 bg-black/25 px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <button
            type="button"
            className="text-left text-xs font-medium"
            onClick={() => setHistoryOpen((v) => !v)}
          >
            选往期数据集 {historyOpen ? '· 收起' : '· 展开'}
            <span className="ml-2 font-normal text-muted-foreground">
              {historyLoading
                ? '加载中…'
                : readyDataset
                  ? `当前 ${readyDataset}`
                  : `${history.length} 个`}
            </span>
          </button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-[11px]"
            disabled={historyLoading}
            onClick={() => void loadHistory()}
          >
            <RefreshCw className={`mr-1 h-3 w-3 ${historyLoading ? 'animate-spin' : ''}`} />
            刷新
          </Button>
        </div>
        {historyOpen && (
          <div className="mt-2 max-h-52 space-y-1 overflow-y-auto">
            {history.length === 0 && !historyLoading ? (
              <p className="text-[11px] text-muted-foreground">还没有本地数据集。</p>
            ) : (
              history.map((item) => {
                const active =
                  item.repo_id === readyDataset || item.repo_id === normaliseB601RepoId(repoId)
                const when = item.mtime
                  ? new Date(item.mtime * 1000).toLocaleString('zh-CN', {
                      month: '2-digit',
                      day: '2-digit',
                      hour: '2-digit',
                      minute: '2-digit',
                    })
                  : ''
                return (
                  <button
                    key={item.repo_id}
                    type="button"
                    disabled={running}
                    onClick={() => openPastDataset(item.repo_id)}
                    className={`flex w-full flex-col rounded-md border px-2 py-1.5 text-left transition-colors ${
                      active
                        ? 'border-emerald-500/40 bg-emerald-500/10'
                        : 'border-white/5 bg-black/20 hover:border-white/15 hover:bg-white/5'
                    }`}
                  >
                    <code className="truncate font-mono text-[11px] text-foreground/90">
                      {item.repo_id}
                    </code>
                    <span className="mt-0.5 text-[10px] text-muted-foreground">
                      {item.num_episodes != null ? `${item.num_episodes} episodes` : '—'}
                      {item.total_frames != null ? ` · ${item.total_frames} frames` : ''}
                      {item.size_mb != null ? ` · ${item.size_mb} MB` : ''}
                      {when ? ` · ${when}` : ''}
                    </span>
                  </button>
                )
              })
            )}
          </div>
        )}
      </div>
      )}

      {browsing && previewVideos.length === 0 && readyDataset && (
        <p className="text-[11px] text-muted-foreground">正在准备审片…</p>
      )}

      {browsing && readyDataset && (
        <B601EpisodeReview
          repoId={normaliseB601RepoId(readyDataset)}
          refreshKey={reviewKey}
          mode="browse"
          onChanged={setReviewSummary}
          onPlaybackTime={(tFrontGlobal, meta) => {
            playbackRepoRef.current = normaliseB601RepoId(readyDataset)
            onPlaybackActiveChange?.(true)
            syncArmToVideoTime(tFrontGlobal, {
              force: meta?.force,
              episode_index: meta?.episode_index,
              t_rel: meta?.t_rel,
            })
          }}
          onPlaybackPlayingChange={(playing) => {
            if (!playing) {
              // keep last snapped pose; still mark active so HUD shows recorded joints
              onPlaybackActiveChange?.(true)
            } else {
              onPlaybackActiveChange?.(true)
            }
          }}
        />
      )}

      {browsing && (readyDataset || isValidB601RepoId(normaliseB601RepoId(repoId))) && (
        <div className="rounded-md border border-sky-500/25 bg-sky-950/30 px-3 py-2 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-xs font-medium text-sky-100">Rerun</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              episode
              <Input
                type="number"
                min={0}
                max={999}
                value={vizEpisode}
                disabled={vizBusy || running}
                onChange={(e) => setVizEpisode(Math.max(0, Number(e.target.value) || 0))}
                className="h-7 w-16 font-mono text-xs"
              />
            </label>
            {!vizRunning ? (
              <Button
                size="sm"
                className="h-7"
                disabled={vizBusy || running}
                onClick={() => void openRerunViz()}
              >
                {vizBusy ? (
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Play className="mr-1 h-3.5 w-3.5" />
                )}
                用 Rerun 打开
              </Button>
            ) : (
              <Button
                size="sm"
                variant="secondary"
                className="h-7"
                disabled={vizBusy}
                onClick={() => void stopRerunViz()}
              >
                {vizBusy ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Square className="mr-1 h-3.5 w-3.5" />}
                停止推流
              </Button>
            )}
          </div>
          {vizHint && <p className="text-[10px] leading-relaxed text-sky-100/90">{vizHint}</p>}
        </div>
      )}

      {!browsing && (
      <>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-1 sm:col-span-2">
          <span className="text-xs font-medium">新采集数据集 ID（owner/name）</span>
          <Input
            value={repoId}
            onChange={(e) => setRepoId(e.target.value)}
            disabled={running || starting}
            placeholder="local/b601-dm-pick01"
            className="font-mono text-xs"
          />
          <span className="text-[10px] text-muted-foreground">
            开始采集会写入这个 ID。换新时间戳：{' '}
            <button
              type="button"
              className="underline underline-offset-2"
              disabled={running}
              onClick={() => setRepoId(suggestB601RepoId(repoPrefix))}
            >
              换一个
            </button>
          </span>
        </label>

        <label className="block space-y-1 sm:col-span-2">
          <span className="text-xs font-medium">任务描述（写入 dataset.single_task）</span>
          <Input
            value={taskDesc}
            onChange={(e) => setTaskDesc(e.target.value)}
            disabled={running || starting}
            placeholder="抓取红色方块放到托盘"
          />
        </label>

        <label className="block space-y-1">
          <span className="text-xs font-medium">Episode 数</span>
          <Input
            type="number"
            min={1}
            max={200}
            value={numEpisodes}
            disabled={running || starting}
            onChange={(e) => setNumEpisodes(Math.max(1, Number(e.target.value) || 1))}
          />
        </label>
        <label className="block space-y-1">
          <span className="text-xs font-medium">单条时长 (s)</span>
          <Input
            type="number"
            min={5}
            max={600}
            value={episodeTime}
            disabled={running || starting}
            onChange={(e) => setEpisodeTime(Math.max(5, Number(e.target.value) || 30))}
          />
        </label>
        <label className="block space-y-1">
          <span className="text-xs font-medium">复位时长 (s)</span>
          <Input
            type="number"
            min={0}
            max={120}
            value={resetTime}
            disabled={running || starting}
            onChange={(e) => setResetTime(Math.max(0, Number(e.target.value) || 0))}
          />
        </label>
      </div>

      <B601RecordCoach
        running={running || starting}
        phase={starting && !running ? 'starting' : phase}
        episode={episode}
        total={total}
        phaseElapsedS={phaseElapsedS}
        phaseTargetS={phaseTargetS}
        phaseOvertime={phaseOvertime}
        hint={session?.phase_hint}
      />

      <div className="flex flex-wrap items-center gap-2">
        {!running ? (
          <Button size="sm" onClick={() => void doStart()} disabled={starting || noCamera}>
            {starting ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Play className="mr-1 h-4 w-4" />}
            {starting ? '正在启动…' : '开始采集'}
          </Button>
        ) : (
          <>
            <Button
              size="sm"
              onClick={() => void doSkip()}
              disabled={skipDisabled}
              className="bg-amber-600 hover:bg-amber-500"
              title={
                skipTooEarly
                  ? '再示教约 2 秒后再跳过，避免空 episode'
                  : phase === 'resetting'
                    ? '跳过剩余复位，进入下一条'
                    : '结束本段录制并进入复位'
              }
            >
              {skipping ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <SkipForward className="mr-1 h-4 w-4" />
              )}
              {skipTooEarly
                ? '示教中…稍后再跳'
                : phase === 'resetting'
                  ? '复位完成·下一条'
                  : '提前结束本段·继续'}
            </Button>
            <Button size="sm" variant="destructive" onClick={() => void doStop()} disabled={stopping}>
              {stopping ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Square className="mr-1 h-4 w-4" />}
              {stopping ? '正在停止…' : '停止采集'}
            </Button>
          </>
        )}

        <Button size="sm" variant="outline" onClick={() => void doCheckDataset()} disabled={starting}>
          <RefreshCw className="mr-1 h-3.5 w-3.5" />
          检查 / 预览
        </Button>

        {!hideSnapshot && onSnapshot && (
          <Button
            size="sm"
            variant="outline"
            disabled={starting || running}
            onClick={() => onSnapshot(normaliseB601RepoId(repoId))}
          >
            导出快照
          </Button>
        )}

        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <CircleDot className={running ? 'h-3 w-3 text-emerald-400' : 'h-3 w-3'} />
          {running
            ? `运行中 · 第 ${episode > 0 ? episode : '—'}/${total} 条`
            : session?.returncode != null
              ? `已结束 · rc=${session.returncode}${session.returncode === 0 ? '（成功）' : '（异常）'}`
              : '未启动'}
        </div>
        {(phase === 'recording' || phase === 'resetting' || phase === 'saving') && (
          <p className="text-[11px] text-muted-foreground">
            {phase === 'recording'
              ? '状态：正在录当前这一条'
              : phase === 'resetting'
                ? '状态：当前条已录完，复位中'
                : '状态：正在保存刚录完的当前条（不是下一条）'}
          </p>
        )}

        {readyDataset && (
          <div className="ml-auto flex items-center gap-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-300">
            <CheckCircle2 className="h-3.5 w-3.5" />
            <code className="font-mono">{readyDataset}</code>
            <Link
              to={`/datasets/${encodeURIComponent(readyDataset)}`}
              className="underline underline-offset-2"
            >
              打开数据集页
            </Link>
          </div>
        )}
      </div>

      {(phase === 'resetting' || phase === 'saving') && markEpisodeIndex != null && (
        <div className="space-y-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-xs font-medium text-amber-50">
              第 {markEpisodeIndex + 1} 条
            </p>
            {reviewSummary && (
              <span className="text-[11px] text-muted-foreground">
                不满意 {reviewSummary.bad_count} · 未标 {reviewSummary.unmarked_count}
              </span>
            )}
          </div>
          {resetPreview.length > 0 ? (
            <div className="grid grid-cols-2 gap-2">
              {[...resetPreview]
                .sort((a, b) => {
                  const rank = (k: string) =>
                    k.toLowerCase().includes('front') ? 0 : k.toLowerCase().includes('side') ? 1 : 9
                  return rank(a.key) - rank(b.key)
                })
                .slice(0, 2)
                .map((v) => {
                  const title = v.key.toLowerCase().includes('front')
                    ? '正面'
                    : v.key.toLowerCase().includes('side')
                      ? '侧面'
                      : v.key
                  return (
                    <div key={v.url + v.key} className="overflow-hidden rounded border border-white/10 bg-black/40">
                      <div className="px-1.5 py-0.5 text-[10px] font-medium text-foreground/80">{title}</div>
                      <video
                        src={v.url}
                        className="aspect-video max-h-[100px] w-full object-contain"
                        muted
                        playsInline
                        preload="metadata"
                        onLoadedMetadata={(e) => {
                          const from = Number(v.from_timestamp ?? 0)
                          try {
                            e.currentTarget.currentTime = from
                          } catch {
                            /* ignore */
                          }
                        }}
                      />
                    </div>
                  )
                })}
            </div>
          ) : (
            <p className="text-[11px] text-muted-foreground">编码中…可先标记或重录</p>
          )}
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <Button
              size="sm"
              className="h-10 bg-rose-700 text-white hover:bg-rose-600"
              disabled={marking}
              onClick={() => void doMark('bad')}
            >
              {marking ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <ThumbsDown className="mr-1 h-3.5 w-3.5" />}
              不满意（回头删）
            </Button>
            <Button
              size="sm"
              className="h-10 border-amber-400/50 bg-amber-600/90 text-white hover:bg-amber-500"
              disabled={rerecording}
              onClick={() => void doRerecord()}
              title="当场重录本条（键盘 ←）"
            >
              {rerecording ? (
                <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
              ) : (
                <RotateCcw className="mr-1 h-3.5 w-3.5" />
              )}
              重录本条
            </Button>
            <Button
              size="sm"
              className="h-10 bg-emerald-600 text-white hover:bg-emerald-500"
              disabled={marking}
              onClick={() => void doMark('ok')}
            >
              <ThumbsUp className="mr-1 h-3.5 w-3.5" />
              可用
            </Button>
          </div>
          {markHint && <p className="text-[11px] text-emerald-200/90">{markHint}</p>}
        </div>
      )}

      {running && (
        <div>
          <div className="mb-1 flex justify-between text-[11px] text-muted-foreground">
            <span>当前条进度（正在处理的这一条）</span>
            <span>
              {episode > 0 ? episode : '—'} / {total}
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded bg-white/10">
            <div className="h-full bg-emerald-500 transition-all" style={{ width: `${progressPct}%` }} />
          </div>
        </div>
      )}
      </>
      )}

      {!browsing && previewVideos.length > 0 && (
        <p className="text-[11px] text-muted-foreground">
          本批已落盘。请用下方「审片」按条查看：每条是正面 + 侧面成对，不要把散视频当成一条。
        </p>
      )}

      {!browsing && datasetCheck && (
        <div className="rounded-md border border-white/10 bg-black/25 px-3 py-2 text-[11px] text-muted-foreground">
          {datasetCheck.exists ? (
            <>
              已找到 <code className="font-mono text-foreground">{datasetCheck.repo_id}</code>
              {datasetCheck.num_episodes != null ? ` · ${datasetCheck.num_episodes} episodes` : ''}
              {datasetCheck.path ? (
                <div className="mt-1 flex items-center gap-1 truncate">
                  <FolderOpen className="h-3 w-3 shrink-0" />
                  <code className="truncate font-mono text-[10px]">{datasetCheck.path}</code>
                </div>
              ) : null}
            </>
          ) : (
            <>磁盘上还没有 <code className="font-mono">{datasetCheck.repo_id}</code></>
          )}
        </div>
      )}

      {!browsing && (readyDataset || datasetCheck?.exists) && (
        <B601EpisodeReview
          repoId={normaliseB601RepoId(readyDataset || repoId)}
          refreshKey={reviewKey}
          mode="after-batch"
          onChanged={setReviewSummary}
          onPlaybackTime={(tFrontGlobal, meta) => {
            const id = normaliseB601RepoId(readyDataset || repoId)
            playbackRepoRef.current = id
            onPlaybackActiveChange?.(true)
            syncArmToVideoTime(tFrontGlobal, {
              force: meta?.force,
              episode_index: meta?.episode_index,
              t_rel: meta?.t_rel,
            })
          }}
        />
      )}

      {!browsing && (
      <div className="rounded-md border border-white/10 bg-black/25 px-3 py-2">
        <button
          type="button"
          className="flex w-full items-center justify-between text-xs font-medium"
          onClick={() => setHfOpen((v) => !v)}
        >
          <span>上传到 Hugging Face（次要）</span>
          <span className="text-[10px] text-muted-foreground">{hfOpen ? '收起' : '展开'}</span>
        </button>
        {hfOpen && (
          <div className="mt-2 space-y-2">
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              本地是 <code className="text-[10px]">local/…</code>
              ，Hub 上必须用你的用户名。Token 只写本机缓存。
              {reviewSummary && reviewSummary.bad_count > 0
                ? ` 当前还有 ${reviewSummary.bad_count} 条「不满意」未删除，上传会被拒绝。`
                : ''}
            </p>
            <label className="block space-y-1">
              <span className="text-[11px] text-muted-foreground">Hub 数据集 ID（owner/name）</span>
              <Input
                value={hubRepoId}
                onChange={(e) => setHubRepoId(e.target.value)}
                disabled={pushing || running}
                placeholder="yourname/b601-dm-pick01"
                className="font-mono text-xs"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-[11px] text-muted-foreground">HF Access Token（可空）</span>
              <Input
                type="password"
                value={hfToken}
                onChange={(e) => setHfToken(e.target.value)}
                disabled={pushing || running}
                placeholder="hf_…"
                className="font-mono text-xs"
                autoComplete="off"
              />
            </label>
            <label className="flex items-start gap-2 text-[11px] text-muted-foreground">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={pushPrivate}
                disabled={pushing || running}
                onChange={(e) => setPushPrivate(e.target.checked)}
              />
              <span>
                私有仓库（默认关闭）。Qualia 云端训练目前读不到私有 HF 数据，若要云训请保持公开。
              </span>
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={pushing || running || (reviewSummary?.bad_count ?? 0) > 0}
                title={
                  (reviewSummary?.bad_count ?? 0) > 0
                    ? '请先删除不满意的条目'
                    : undefined
                }
                onClick={() => void doPush()}
              >
                {pushing ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
                {pushing ? '上传中…' : '上传当前数据集'}
              </Button>
              <span className="text-[10px] text-muted-foreground">
                将上传 {readyDataset || normaliseB601RepoId(repoId) || '（先填数据集 ID）'}
              </span>
            </div>
            {pushResult?.ok && (
              <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1.5 text-[11px] text-emerald-200">
                已上传 {pushResult.hub_repo_id}
                {pushResult.url ? (
                  <>
                    {' · '}
                    <a href={pushResult.url} target="_blank" rel="noreferrer" className="underline">
                      打开 Hub
                    </a>
                  </>
                ) : null}
              </div>
            )}
          </div>
        )}
      </div>
      )}

      {errorMsg && (
        <div className="flex items-start gap-2 rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="whitespace-pre-wrap">{errorMsg}</div>
        </div>
      )}

      {!browsing && session?.last_error && !errorMsg && (
        <div className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[11px]">{session.last_error}</pre>
        </div>
      )}

      {!browsing && (running || (session?.log_tail?.length ?? 0) > 0) && (
        <div className="rounded-md border border-white/10 bg-black/60">
          <button
            type="button"
            className="flex w-full items-center justify-between border-b border-white/10 px-3 py-1.5 text-[11px] text-muted-foreground"
            onClick={() => setLogOpen((v) => !v)}
          >
            <span>日志（排查用 · {logOpen ? '收起' : '展开'}）</span>
            {session?.dataset_dir && (
              <span className="flex max-w-[55%] items-center gap-1 truncate">
                <FolderOpen className="h-3 w-3 shrink-0" />
                <code className="truncate font-mono text-[10px]">{session.dataset_dir}</code>
              </span>
            )}
          </button>
          {(logOpen || phase === 'error') && (
            <pre
              ref={logRef}
              className="max-h-56 overflow-auto p-3 text-[11px] leading-snug text-emerald-200"
            >
              {(session?.log_tail ?? []).join('\n') || '（暂无输出）'}
            </pre>
          )}
        </div>
      )}

      {!running && session?.repo_id && session.returncode !== 0 && onDatasetReady && (
        <div className="flex items-center justify-between gap-2 rounded-md border border-white/10 bg-black/25 p-3">
          <span className="text-[11px] text-muted-foreground">
            若你确认已采完 <code className="font-mono">{session.repo_id}</code>，可手动标记完成。
          </span>
          <Button size="sm" variant="secondary" onClick={markDoneManually}>
            <CheckCircle2 className="mr-1 h-3.5 w-3.5" />
            标记完成
          </Button>
        </div>
      )}
    </div>
  )
}
