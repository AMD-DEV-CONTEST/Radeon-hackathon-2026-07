/**
 * Reachy 对话 Tab — 方案 A：官方双工为主路径。
 *
 * 主面板：Pollen Conversation App（默认 HuggingFace realtime，无需 OpenAI/Gemini Key）
 *   + 内嵌 Web UI（:7860）
 * 高级折叠：Seeed 豆包本体对话、浏览器嵌入式 Realtime（需 Key）
 * 已移除：DeepSeek 文字 + Piper/espeak 零 Key 念稿面板
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Ear,
  ExternalLink,
  Loader2,
  Mic,
  Mic2,
  MicOff,
  Sparkles,
  Square,
  Volume2,
} from 'lucide-react'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import {
  getReachyConversationEnvTemplateV2,
  getReachyConversationStatusV2,
  getReachySeeedConversationStatus,
  installReachySeeedConversation,
  getReachyAudioLevel,
  listReachyAudioInputs,
  setupReachySeeedConversation,
  setReachyAudioInput,
  startReachyConversationV2,
  startReachySeeedConversation,
  stopReachyConversation,
  stopReachySeeedConversation,
  type ReachyAudioInputSource,
  type ReachyConversationBackend,
  type ReachyConversationEnvTemplateV2,
  type ReachyConversationProvider,
  type ReachySeeedConversationStatus,
} from '../../lib/reachyApi'
import { reachyRandomMotionStore } from '../../lib/reachyRandomMotionStore'
import {
  ReachyRealtimeVoiceClient,
  type VoiceConnectionState,
  type VoiceProvider,
  type VoiceToolExecuted,
} from '../../lib/reachyRealtimeVoice'

interface Props {
  daemonOnline: boolean
}

const LS_KEYS = {
  backend: 'botversex.reachy.official.backend',
  apiKey: 'botversex.reachy.official.apiKey',
  model: 'botversex.reachy.official.model',
  noCamera: 'botversex.reachy.official.noCamera',
  advancedOpen: 'botversex.reachy.advanced.open',
  proProvider: 'botversex.reachy.pro.provider',
  proApiKey: 'botversex.reachy.pro.apiKey',
  proModel: 'botversex.reachy.pro.model',
  proOpen: 'botversex.reachy.pro.open',
  voiceProvider: 'botversex.reachy.voice.provider',
  voiceOpenaiKey: 'botversex.reachy.voice.openaiKey',
  voiceQwenKey: 'botversex.reachy.voice.qwenKey',
  seeedLlmKey: 'botversex.reachy.seeed.llmKey',
  seeedAsrKey: 'botversex.reachy.seeed.asrKey',
  seeedModel: 'botversex.reachy.seeed.model',
  seeedOpen: 'botversex.reachy.seeed.open',
  audioInputId: 'botversex.reachy.official.audioInputId',
}

const VOICE_PROVIDER_META: Record<VoiceProvider, { label: string; keyEnv: string; keyHint: string; placeholder: string }> = {
  openai: {
    label: 'OpenAI Realtime',
    keyEnv: 'OPENAI_API_KEY',
    keyHint: 'platform.openai.com/api-keys',
    placeholder: 'sk-…',
  },
  qwen: {
    label: '通义千问 (国内·阿里云百炼)',
    keyEnv: 'DASHSCOPE_API_KEY',
    keyHint: 'bailian.console.aliyun.com',
    placeholder: 'sk-…（百炼 DashScope key）',
  },
}

function loadLS(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}
function saveLS(key: string, val: string) {
  try {
    localStorage.setItem(key, val)
  } catch {
    /* ignore */
  }
}

export function ReachyChatTab({ daemonOnline }: Props) {
  const [busy, setBusy] = useState<'start' | 'stop' | 'send' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const [backend, setBackend] = useState<ReachyConversationBackend>(
    () => (loadLS(LS_KEYS.backend, 'huggingface') as ReachyConversationBackend) || 'huggingface',
  )
  const [apiKey, setApiKey] = useState(() => loadLS(LS_KEYS.apiKey, ''))
  const [model, setModel] = useState(() => loadLS(LS_KEYS.model, ''))
  const [noCamera, setNoCamera] = useState(() => loadLS(LS_KEYS.noCamera, 'true') === 'true')
  const [audioInputId, setAudioInputId] = useState(() => loadLS(LS_KEYS.audioInputId, ''))
  const [audioInputs, setAudioInputs] = useState<ReachyAudioInputSource[]>([])
  const [advancedOpen, setAdvancedOpen] = useState(() => loadLS(LS_KEYS.advancedOpen, 'false') === 'true')

  const [template, setTemplate] = useState<ReachyConversationEnvTemplateV2 | null>(null)
  const [convRunning, setConvRunning] = useState(false)
  const [convState, setConvState] = useState('stopped')
  const [convProvider, setConvProvider] = useState<ReachyConversationProvider | null>(null)
  const [convGradioUrl, setConvGradioUrl] = useState<string | null>(null)
  const [appInstalled, setAppInstalled] = useState(false)
  const [logTail, setLogTail] = useState<string[]>([])

  const [proOpen, setProOpen] = useState(() => loadLS(LS_KEYS.proOpen, 'false') === 'true')
  const [proProvider, setProProvider] = useState<ReachyConversationProvider>(
    () => (loadLS(LS_KEYS.proProvider, 'openai_pro') as ReachyConversationProvider) || 'openai_pro',
  )
  const [proApiKey, setProApiKey] = useState(() => loadLS(LS_KEYS.proApiKey, ''))
  const [proModel, setProModel] = useState(() => loadLS(LS_KEYS.proModel, ''))

  const [seeedOpen, setSeeedOpen] = useState(() => loadLS(LS_KEYS.seeedOpen, 'false') === 'true')
  const [seeedStatus, setSeeedStatus] = useState<ReachySeeedConversationStatus | null>(null)
  const [seeedLlmKey, setSeeedLlmKey] = useState(() => loadLS(LS_KEYS.seeedLlmKey, ''))
  const [seeedAsrKey, setSeeedAsrKey] = useState(() => loadLS(LS_KEYS.seeedAsrKey, ''))
  const [seeedModel, setSeeedModel] = useState(() => loadLS(LS_KEYS.seeedModel, 'doubao-seed-character-251128'))
  const [seeedSetupBusy, setSeeedSetupBusy] = useState(false)
  const seeedSetupDoneRef = useRef(false)

  const voiceClientRef = useRef<ReachyRealtimeVoiceClient | null>(null)
  const [voiceState, setVoiceState] = useState<VoiceConnectionState>('idle')
  const [voiceSpeaking, setVoiceSpeaking] = useState(false)
  const [voiceListening, setVoiceListening] = useState(false)
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const [voiceProvider, setVoiceProvider] = useState<VoiceProvider>(
    () => (loadLS(LS_KEYS.voiceProvider, 'openai') as VoiceProvider) || 'openai',
  )
  const [voiceOpenaiKey, setVoiceOpenaiKey] = useState(() => loadLS(LS_KEYS.voiceOpenaiKey, ''))
  const [voiceQwenKey, setVoiceQwenKey] = useState(() => loadLS(LS_KEYS.voiceQwenKey, ''))
  const activeVoiceKey = voiceProvider === 'qwen' ? voiceQwenKey : voiceOpenaiKey
  const setActiveVoiceKey = useCallback(
    (val: string) => (voiceProvider === 'qwen' ? setVoiceQwenKey(val) : setVoiceOpenaiKey(val)),
    [voiceProvider],
  )

  const refresh = useCallback(async () => {
    try {
      const [conv, seeed] = await Promise.all([
        getReachyConversationStatusV2().catch(() => null),
        getReachySeeedConversationStatus().catch(() => null),
      ])
      if (conv) {
        setConvRunning(conv.running)
        setConvState(conv.state)
        setConvProvider(conv.provider)
        setConvGradioUrl(conv.gradio_url ?? null)
        setAppInstalled(!!conv.pro_backend_installed)
        setLogTail(conv.log_tail ?? [])
      }
      if (seeed) setSeeedStatus(seeed)
    } catch {
      /* ignore */
    }
  }, [])

  const loadTemplate = useCallback(async () => {
    try {
      setTemplate(await getReachyConversationEnvTemplateV2())
    } catch {
      /* ignore */
    }
  }, [])

  const loadAudioInputs = useCallback(async () => {
    try {
      const r = await listReachyAudioInputs()
      setAudioInputs(r.sources ?? [])
      setAudioInputId((prev) => prev || r.default_id || '')
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const startup = window.setTimeout(() => {
      if (cancelled) return
      void loadTemplate()
      void refresh()
      void loadAudioInputs()
    }, 0)
    const poll = setInterval(() => void refresh(), 3000)
    return () => {
      cancelled = true
      window.clearTimeout(startup)
      clearInterval(poll)
    }
  }, [loadTemplate, refresh, loadAudioInputs])

  useEffect(() => {
    if (!seeedStatus?.running && !convRunning) return undefined
    const poll = setInterval(() => void refresh(), 800)
    return () => clearInterval(poll)
  }, [seeedStatus?.running, convRunning, refresh])

  useEffect(() => {
    if (seeedSetupDoneRef.current) return
    seeedSetupDoneRef.current = true
    setSeeedSetupBusy(true)
    void setupReachySeeedConversation()
      .then(() => refresh())
      .catch(() => {})
      .finally(() => setSeeedSetupBusy(false))
  }, [refresh])

  useEffect(() => () => {
    voiceClientRef.current?.disconnect()
  }, [])

  const stopCompetingMotion = useCallback(() => {
    reachyRandomMotionStore.stop()
  }, [])

  const handleOfficialStart = useCallback(async () => {
    setError(null)
    setSuccess(null)
    if (!daemonOnline) {
      setError('机器人未连接。请先启动 Reachy daemon。')
      return
    }
    const info = template?.backends[backend]
    if (info?.requires_key && !apiKey.trim()) {
      setError(`${info.label} 需要填写 API Key（${info.key_env ?? ''}）`)
      return
    }
    setBusy('start')
    saveLS(LS_KEYS.backend, backend)
    saveLS(LS_KEYS.apiKey, apiKey)
    saveLS(LS_KEYS.model, model)
    saveLS(LS_KEYS.noCamera, String(noCamera))
    saveLS(LS_KEYS.audioInputId, audioInputId)
    stopCompetingMotion()
    voiceClientRef.current?.disconnect()
    voiceClientRef.current = null
    try {
      if (audioInputId) {
        await setReachyAudioInput(audioInputId).catch(() => null)
      }
      const r = await startReachyConversationV2({
        provider: 'official',
        backend,
        api_key: apiKey.trim() || null,
        model: model.trim() || null,
        gradio: true,
        no_camera: noCamera,
        auto_install: true,
        audio_input_id: audioInputId || null,
      })
      if (!r.ok) setError(r.message || '启动失败')
      else {
        setSuccess(
          r.gradio_url
            ? `官方双工已启动 · UI ${r.gradio_url}`
            : r.message || '官方双工已启动',
        )
      }
      void refresh()
    } catch (e) {
      setError(parseErr((e as Error).message))
    } finally {
      setBusy(null)
    }
  }, [daemonOnline, template, backend, apiKey, model, noCamera, audioInputId, stopCompetingMotion, refresh])

  const handleOfficialStop = useCallback(async () => {
    setBusy('stop')
    setError(null)
    try {
      await stopReachyConversation()
      setSuccess('已停止官方对话')
      void refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }, [refresh])

  const handleProStart = useCallback(async () => {
    setError(null)
    const provInfo = template?.providers[proProvider]
    if (provInfo?.requires_key && !proApiKey.trim()) {
      setError(`${provInfo.label} 需要填写 API Key（${provInfo.key_env ?? ''}）`)
      return
    }
    setBusy('start')
    saveLS(LS_KEYS.proProvider, proProvider)
    saveLS(LS_KEYS.proApiKey, proApiKey)
    saveLS(LS_KEYS.proModel, proModel)
    stopCompetingMotion()
    try {
      const mappedBackend = proProvider === 'openai_pro' ? 'openai' : 'gemini'
      const r = await startReachyConversationV2({
        provider: proProvider,
        backend: mappedBackend,
        api_key: proApiKey.trim() || null,
        model: proModel.trim() || null,
        gradio: true,
        auto_install: true,
      })
      if (!r.ok) setError(r.message || '启动失败')
      void refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }, [template, proProvider, proApiKey, proModel, stopCompetingMotion, refresh])

  const handleProStop = useCallback(async () => {
    setBusy('stop')
    try {
      await stopReachyConversation()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
      void refresh()
    }
  }, [refresh])

  const handleVoiceStart = useCallback(() => {
    if (!activeVoiceKey.trim() && voiceProvider !== 'qwen') {
      setVoiceError(`需要填写 ${VOICE_PROVIDER_META[voiceProvider].keyEnv}`)
      return
    }
    setVoiceError(null)
    saveLS(LS_KEYS.voiceProvider, voiceProvider)
    saveLS(LS_KEYS.voiceOpenaiKey, voiceOpenaiKey)
    saveLS(LS_KEYS.voiceQwenKey, voiceQwenKey)
    stopCompetingMotion()
    const client = new ReachyRealtimeVoiceClient({
      provider: voiceProvider,
      apiKey: activeVoiceKey.trim(),
      onStateChange: setVoiceState,
      onError: (msg) => setVoiceError(msg),
      onUserSpeechStart: () => setVoiceListening(true),
      onUserSpeechStop: () => setVoiceListening(false),
      onAssistantSpeakingChange: setVoiceSpeaking,
      onToolExecuted: (_info: VoiceToolExecuted) => {},
    })
    voiceClientRef.current = client
    void client.connect()
  }, [activeVoiceKey, voiceProvider, voiceOpenaiKey, voiceQwenKey, stopCompetingMotion])

  const handleVoiceStop = useCallback(() => {
    voiceClientRef.current?.disconnect()
    voiceClientRef.current = null
    setVoiceState('idle')
    setVoiceSpeaking(false)
    setVoiceListening(false)
  }, [])

  const handleSeeedStart = useCallback(async () => {
    if (!daemonOnline) {
      setError('机器人未连接。请先启动 Reachy daemon。')
      return
    }
    const hasLlm = !!seeedLlmKey.trim()
    const hasAsr = !!seeedAsrKey.trim()
    const hasStored = !!seeedStatus?.keys_configured
    if (!hasStored && (!hasLlm || !hasAsr)) {
      setError('请填写豆包 LLM Key 和语音识别 Key')
      return
    }
    setError(null)
    setBusy('start')
    if (hasLlm) saveLS(LS_KEYS.seeedLlmKey, seeedLlmKey)
    if (hasAsr) saveLS(LS_KEYS.seeedAsrKey, seeedAsrKey)
    saveLS(LS_KEYS.seeedModel, seeedModel)
    stopCompetingMotion()
    voiceClientRef.current?.disconnect()
    try {
      const r = await startReachySeeedConversation({
        llm_api_key: seeedLlmKey.trim(),
        asr_api_key: seeedAsrKey.trim(),
        model: seeedModel.trim() || 'doubao-seed-character-251128',
        auto_install: true,
        save_keys: true,
      })
      if (!r.ok) setError(r.message || '启动失败')
      void refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }, [daemonOnline, seeedLlmKey, seeedAsrKey, seeedModel, seeedStatus?.keys_configured, stopCompetingMotion, refresh])

  const handleSeeedStop = useCallback(async () => {
    setBusy('stop')
    try {
      await stopReachySeeedConversation()
      void refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }, [refresh])

  const handleSeeedInstall = useCallback(async () => {
    setBusy('send')
    try {
      await installReachySeeedConversation(false)
      void refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }, [refresh])

  const officialRunning =
    convRunning && (convProvider === 'official' || convProvider === 'openai_pro' || convProvider === 'gemini_pro')
  const backendInfo = template?.backends[backend]
  const needsKey = !!backendInfo?.requires_key
  const stateLabel =
    convState === 'installing'
      ? '安装中…'
      : convState === 'starting'
        ? '启动中…'
        : officialRunning
          ? '对话中'
          : convState === 'error'
            ? '出错'
            : '未启动'

  return (
    <div className="space-y-3">
      {/* Primary: official duplex */}
      <div className="rounded-md border border-sky-500/30 bg-sky-500/5">
        <div className="flex items-center justify-between border-b border-sky-500/20 px-2.5 py-1.5">
          <div className="flex items-center gap-1.5 text-xs font-medium text-sky-100">
            <Mic2 className="h-3.5 w-3.5" />
            官方实时对话
          </div>
          <Badge
            variant="outline"
            className={`text-[9px] ${
              officialRunning
                ? 'border-emerald-500/40 text-emerald-300'
                : convState === 'error'
                  ? 'border-red-500/40 text-red-300'
                  : 'border-white/20 text-muted-foreground'
            }`}
          >
            {stateLabel}
          </Badge>
        </div>

        <div className="space-y-2 p-2.5">
          <p className="text-[10px] leading-relaxed text-muted-foreground">
            官方双工语音（HuggingFace realtime，
            <span className="text-emerald-300">无需 OpenAI/Gemini Key</span>
            ）。点「开始对话」即可；默认仅音频，不装摄像头重依赖。
          </p>

          {!appInstalled && !officialRunning && (
            <div className="flex items-start gap-1.5 rounded border border-amber-500/30 bg-amber-500/10 p-1.5 text-[10px] text-amber-100">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
              首次会自动准备（本机已预装则可直接用）。
            </div>
          )}

          <div className="grid grid-cols-3 gap-1.5">
            {(['huggingface', 'openai', 'gemini'] as const).map((b) => {
              const info = template?.backends[b]
              const active = backend === b
              return (
                <button
                  key={b}
                  type="button"
                  disabled={officialRunning || busy !== null}
                  onClick={() => setBackend(b)}
                  className={`rounded-md border px-2 py-1.5 text-left text-xs transition-colors ${
                    active
                      ? 'border-sky-500/60 bg-sky-500/15 text-foreground'
                      : 'border-white/10 text-muted-foreground hover:border-white/20'
                  } ${officialRunning ? 'cursor-not-allowed opacity-60' : ''}`}
                >
                  <div className="truncate font-medium">{info?.label ?? b}</div>
                  <div className={`text-[9px] ${info?.requires_key ? 'text-amber-300/80' : 'text-emerald-300/80'}`}>
                    {info?.requires_key ? '需 API Key' : '零 Key'}
                  </div>
                </button>
              )
            })}
          </div>

          {needsKey && (
            <div className="space-y-1">
              <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                <span>{backendInfo?.key_env ?? 'API_KEY'}</span>
                {backendInfo?.key_hint && (
                  <a
                    href={backendInfo.key_hint}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-0.5 text-sky-300/80 hover:text-sky-200"
                  >
                    获取 Key <ExternalLink className="h-2.5 w-2.5" />
                  </a>
                )}
              </div>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                disabled={officialRunning}
                placeholder={`输入 ${backendInfo?.label} API Key`}
                className="h-8 w-full rounded-md border bg-background px-2 font-mono text-xs"
              />
            </div>
          )}

          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={officialRunning}
            placeholder="模型（可选，留空用默认）"
            className="h-8 w-full rounded-md border bg-background px-2 font-mono text-xs"
          />

          <label className="flex items-center gap-2 text-[10px] text-muted-foreground">
            <input
              type="checkbox"
              checked={noCamera}
              disabled={officialRunning}
              onChange={(e) => setNoCamera(e.target.checked)}
            />
            仅音频（--no-camera）
          </label>

          <div className="space-y-1">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[10px] text-muted-foreground">麦克风输入</span>
              <button
                type="button"
                className="text-[10px] text-sky-300/80 hover:text-sky-200"
                disabled={officialRunning}
                onClick={() => void loadAudioInputs()}
              >
                刷新列表
              </button>
            </div>
            <select
              value={audioInputId}
              disabled={officialRunning}
              onChange={(e) => {
                setAudioInputId(e.target.value)
                saveLS(LS_KEYS.audioInputId, e.target.value)
              }}
              className="h-8 w-full rounded-md border bg-background px-2 text-xs"
            >
              <option value="">系统默认</option>
              {audioInputs.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                  {s.default ? '（当前默认）' : ''}
                </option>
              ))}
            </select>
            <p className="text-[10px] leading-relaxed text-muted-foreground">
              多麦克风时请手动选一个（如 MCP01 / Reachy Mini）。改完需重新「开始对话」。
            </p>
          </div>

          {officialRunning && !daemonOnline && (
            <div className="rounded border border-amber-500/40 bg-amber-500/10 p-2 text-[10px] leading-relaxed text-amber-100">
              <div className="flex items-center gap-1.5 font-medium">
                <AlertTriangle className="h-3.5 w-3.5" />
                机器人 daemon 已断开 — 头/身体不会动
              </div>
              <div className="mt-0.5 text-amber-100/80">
                官方待机呼吸、说话点头、idle 动作都依赖 daemon。请确认机器人供电与 USB，然后在高级面板「启动守护进程」，再停止并重新「开始对话」。
              </div>
            </div>
          )}

          <MicLoudnessMeter sourceId={audioInputId || null} />

          <div className="flex gap-1.5">
            {!officialRunning ? (
              <Button
                size="sm"
                className="h-8 flex-1"
                onClick={handleOfficialStart}
                disabled={busy !== null || !daemonOnline}
              >
                {busy === 'start' ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Mic className="h-3.5 w-3.5" />
                )}
                开始对话
              </Button>
            ) : (
              <Button
                size="sm"
                variant="destructive"
                className="h-8 flex-1"
                onClick={handleOfficialStop}
                disabled={busy !== null}
              >
                {busy === 'stop' ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Square className="h-3.5 w-3.5" />
                )}
                停止
              </Button>
            )}
            {convGradioUrl && (
              <a
                href={convGradioUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-8 items-center gap-1 rounded-md border border-sky-500/30 bg-sky-500/10 px-2 text-xs text-sky-200"
              >
                新标签打开 <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>

          {officialRunning && <OfficialTranscript logTail={logTail} />}

          {officialRunning && convGradioUrl && (
            <div className="overflow-hidden rounded-md border border-white/10 bg-black/40">
              <iframe
                title="Reachy official conversation UI"
                src={convGradioUrl}
                className="h-[460px] w-full bg-black"
                allow="microphone; camera; autoplay"
              />
            </div>
          )}

          {officialRunning && logTail.length > 0 && (
            <details className="rounded border border-white/10 bg-black/20">
              <summary className="cursor-pointer px-2 py-1 text-[10px] text-muted-foreground">
                原始日志（调试）
              </summary>
              <pre className="max-h-24 overflow-auto p-1.5 font-mono text-[9px] text-muted-foreground">
                {logTail.slice(-12).join('\n')}
              </pre>
            </details>
          )}
        </div>
      </div>

      {success && (
        <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-2 text-[10px] text-emerald-100">
          {success}
        </div>
      )}
      {error && (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 p-2 text-xs text-red-200">
          ⚠ {error}
        </div>
      )}

      {/* Advanced backups */}
      <div className="rounded-md border border-white/10 bg-muted/10">
        <button
          type="button"
          onClick={() => {
            const next = !advancedOpen
            setAdvancedOpen(next)
            saveLS(LS_KEYS.advancedOpen, String(next))
          }}
          className="flex w-full items-center justify-between px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-white/5"
        >
          <span className="flex items-center gap-1.5 font-medium">
            <Sparkles className="h-3.5 w-3.5" />
            高级备选（豆包 / 浏览器 Realtime）
          </span>
          {advancedOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
        {advancedOpen && (
          <div className="space-y-2 border-t border-white/5 p-2">
            <SeeedNativeSection
              open={seeedOpen}
              onToggle={() => {
                const next = !seeedOpen
                setSeeedOpen(next)
                saveLS(LS_KEYS.seeedOpen, String(next))
              }}
              status={seeedStatus}
              setupBusy={seeedSetupBusy}
              llmKey={seeedLlmKey}
              setLlmKey={setSeeedLlmKey}
              asrKey={seeedAsrKey}
              setAsrKey={setSeeedAsrKey}
              model={seeedModel}
              setModel={setSeeedModel}
              busy={busy !== null}
              daemonOnline={daemonOnline}
              onStart={handleSeeedStart}
              onStop={handleSeeedStop}
              onInstall={handleSeeedInstall}
            />
            <ProSection
              open={proOpen}
              onToggle={() => {
                const next = !proOpen
                setProOpen(next)
                saveLS(LS_KEYS.proOpen, String(next))
              }}
              template={template}
              proProvider={proProvider}
              setProProvider={setProProvider}
              proApiKey={proApiKey}
              setProApiKey={setProApiKey}
              proModel={proModel}
              setProModel={setProModel}
              isRunning={!!(convRunning && (convProvider === 'openai_pro' || convProvider === 'gemini_pro'))}
              gradioUrl={convGradioUrl}
              busy={busy !== null}
              onStart={handleProStart}
              onStop={handleProStop}
              voiceProvider={voiceProvider}
              setVoiceProvider={setVoiceProvider}
              voiceKey={activeVoiceKey}
              setVoiceKey={setActiveVoiceKey}
              voiceState={voiceState}
              voiceSpeaking={voiceSpeaking}
              voiceListening={voiceListening}
              voiceError={voiceError}
              onVoiceStart={handleVoiceStart}
              onVoiceStop={handleVoiceStop}
            />
          </div>
        )}
      </div>
    </div>
  )
}

/** Realtime PipeWire mic loudness bar — speak to see if the selected input is live. */
function MicLoudnessMeter({ sourceId }: { sourceId: string | null }) {
  const [rms, setRms] = useState(0)
  const [peak, setPeak] = useState(0)
  const [db, setDb] = useState(-120)
  const [ok, setOk] = useState(true)
  const [hint, setHint] = useState<string | null>(null)
  const inFlight = useRef(false)

  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      if (cancelled || inFlight.current) return
      inFlight.current = true
      try {
        const r = await getReachyAudioLevel(sourceId, 70)
        if (cancelled) return
        setOk(!!r.ok)
        setRms(r.rms ?? 0)
        setPeak(r.peak ?? 0)
        setDb(r.db ?? -120)
        setHint(r.ok ? null : r.reason || r.error || '无法采样')
      } catch {
        if (!cancelled) {
          setOk(false)
          setHint('电平采样失败')
        }
      } finally {
        inFlight.current = false
      }
    }
    void tick()
    const id = window.setInterval(() => void tick(), 180)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [sourceId])

  // Map RMS to a more readable bar (speech often sits ~0.01–0.2).
  const level = Math.min(1, Math.pow(Math.max(rms, peak * 0.6), 0.45) * 2.2)
  const active = level > 0.08
  const barColor = !ok
    ? 'bg-red-400/70'
    : level > 0.75
      ? 'bg-amber-400'
      : active
        ? 'bg-emerald-400'
        : 'bg-sky-400/50'

  return (
    <div className="space-y-1 rounded border border-white/10 bg-black/20 px-2 py-1.5">
      <div className="flex items-center justify-between gap-2 text-[10px]">
        <span className="flex items-center gap-1 text-muted-foreground">
          <Mic className={`h-3 w-3 ${active ? 'text-emerald-300' : 'text-muted-foreground'}`} />
          输入响度
          {active ? (
            <span className="text-emerald-300">有声</span>
          ) : (
            <span className="text-muted-foreground/70">静音 / 很轻</span>
          )}
        </span>
        <span className="font-mono text-muted-foreground/80">{db > -119 ? `${db.toFixed(0)} dB` : '—'}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-sm bg-white/10">
        <div
          className={`h-full transition-[width] duration-75 ${barColor}`}
          style={{ width: `${Math.round(level * 100)}%` }}
        />
      </div>
      {hint ? (
        <div className="text-[9px] text-amber-200/80">{hint}</div>
      ) : (
        <div className="text-[9px] text-muted-foreground/70">对着所选麦克风说话，条会跳动即表示在收音。</div>
      )}
    </div>
  )
}

type OfficialTurn = { role: 'user' | 'assistant'; text: string; partial?: boolean }

/** Parse official Conversation App log lines: `role=user|user_partial|assistant content=...` */
function parseOfficialTranscript(logTail: string[] | undefined): {
  turns: OfficialTurn[]
  partial: string | null
} {
  const turns: OfficialTurn[] = []
  let partial: string | null = null
  for (const raw of logTail ?? []) {
    const m = raw.match(/role=(user_partial|user|assistant)\s+content=(.*)$/)
    if (!m) continue
    const role = m[1]
    const text = (m[2] ?? '').trim()
    if (!text) continue
    if (role === 'user_partial') {
      partial = text
    } else if (role === 'user') {
      partial = null
      turns.push({ role: 'user', text })
    } else {
      turns.push({ role: 'assistant', text })
    }
  }
  return { turns: turns.slice(-8), partial }
}

function OfficialTranscript({ logTail }: { logTail: string[] }) {
  const { turns, partial } = parseOfficialTranscript(logTail)
  const lastTs = (() => {
    for (let i = (logTail?.length ?? 0) - 1; i >= 0; i--) {
      const m = logTail[i]?.match(/(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/)
      if (m) return m[1]
    }
    return null
  })()
  const stale =
    !!lastTs &&
    (() => {
      const t = Date.parse(lastTs.replace(' ', 'T'))
      return Number.isFinite(t) && Date.now() - t > 90_000
    })()

  if (turns.length === 0 && !partial) {
    return (
      <div className="rounded border border-white/10 bg-black/20 p-2 text-[10px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <Ear className="h-3 w-3 animate-pulse text-sky-300" />
          等待识别…
        </span>
        <div className="mt-0.5 text-muted-foreground/70">你说的话会显示在这里（来自对话日志转写）。</div>
      </div>
    )
  }
  return (
    <div className="space-y-1.5 rounded border border-sky-500/20 bg-sky-500/5 p-2">
      <div className="flex items-center justify-between gap-2 text-[10px] text-sky-200">
        <span className="inline-flex items-center gap-1.5">
          <Ear className="h-3 w-3" />
          对话转写
        </span>
        {lastTs && <span className="font-mono text-muted-foreground/70">{lastTs.slice(11)}</span>}
      </div>
      {stale && (
        <div className="rounded bg-amber-500/10 px-2 py-1 text-[10px] text-amber-200">
          转写已超过 90 秒未更新。若响度条也不动，请换麦克风并「停止 → 开始对话」重建会话。
        </div>
      )}
      <div className="max-h-40 space-y-1 overflow-y-auto">
        {turns.map((turn, i) => (
          <div
            key={`${turn.role}-${i}-${turn.text.slice(0, 24)}`}
            className={`rounded px-2 py-1 text-[11px] leading-relaxed ${
              turn.role === 'user' ? 'bg-sky-500/10 text-sky-100' : 'bg-emerald-500/10 text-emerald-100'
            }`}
          >
            <span className="mr-1 text-[9px] uppercase text-muted-foreground/60">
              {turn.role === 'user' ? '你' : 'Reachy'}
            </span>
            {turn.text}
          </div>
        ))}
        {partial && (
          <div className="rounded bg-sky-500/10 px-2 py-1 text-[11px] leading-relaxed text-sky-100/80">
            <span className="mr-1 text-[9px] uppercase text-muted-foreground/60">你</span>
            {partial}
            <span className="ml-0.5 animate-pulse">…</span>
          </div>
        )}
      </div>
    </div>
  )
}

type SeeedPhase = 'listening' | 'thinking' | 'speaking' | 'idle'

interface SeeedTurn {
  role: 'user' | 'assistant'
  text: string
}

/**
 * Parse the Seeed subprocess's plain stdout tail (`[USER] ...`, `[REACHY] ...`,
 * `[STATE] listening|thinking|speaking|idle`, `[ASR] 未听清...`) into a small
 * transcript + current phase, so the UI can show what the robot heard instead
 * of a raw log dump.
 */
function parseSeeedTranscript(logTail: string[] | undefined): {
  turns: SeeedTurn[]
  phase: SeeedPhase
  unclear: boolean
} {
  const turns: SeeedTurn[] = []
  let phase: SeeedPhase = 'idle'
  let unclear = false
  for (const raw of logTail ?? []) {
    const line = raw.trim()
    const userMatch = line.match(/\[USER\]\s*(.*)/)
    const reachyMatch = line.match(/\[REACHY\]\s*(.*)/)
    const stateMatch = line.match(/\[STATE\]\s*(listening|thinking|speaking|idle)/)
    const asrMatch = line.match(/\[ASR\] Received text:\s*(.*)/)
    if (userMatch && userMatch[1]) {
      turns.push({ role: 'user', text: userMatch[1] })
      unclear = false
    } else if (reachyMatch && reachyMatch[1]) {
      turns.push({ role: 'assistant', text: reachyMatch[1] })
    } else if (asrMatch && asrMatch[1] && !line.includes("Received text: b'")) {
      const draft = asrMatch[1].trim()
      if (draft && (turns.length === 0 || turns[turns.length - 1].role !== 'user')) {
        turns.push({ role: 'user', text: `${draft}…` })
      } else if (draft && turns[turns.length - 1]?.role === 'user') {
        turns[turns.length - 1] = { role: 'user', text: `${draft}…` }
      }
    } else if (stateMatch) {
      phase = stateMatch[1] as SeeedPhase
    } else if (line.includes('未听清')) {
      unclear = true
    }
  }
  return { turns: turns.slice(-6), phase, unclear }
}

const SEEED_PHASE_LABEL: Record<SeeedPhase, string> = {
  listening: '聆听中…',
  thinking: '思考中…',
  speaking: '正在说…',
  idle: '待命',
}

function SeeedTranscript({ status }: { status: ReachySeeedConversationStatus | null }) {
  const { turns, phase, unclear } = parseSeeedTranscript(status?.log_tail)
  if (turns.length === 0 && !unclear) {
    return (
      <div className="rounded border border-white/10 bg-black/20 p-2 text-[10px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <Ear className="h-3 w-3 animate-pulse text-sky-300" />
          {SEEED_PHASE_LABEL[phase]}
        </span>
        <div className="mt-0.5 text-muted-foreground/70">对着机器人说话，这里会实时显示它听到的内容。</div>
      </div>
    )
  }
  return (
    <div className="space-y-1.5 rounded border border-white/10 bg-black/20 p-2">
      <div className="flex items-center gap-1.5 text-[10px] text-emerald-200">
        {phase === 'listening' && <Ear className="h-3 w-3 animate-pulse text-sky-300" />}
        {phase === 'thinking' && <Loader2 className="h-3 w-3 animate-spin text-amber-300" />}
        {phase === 'speaking' && <Volume2 className="h-3 w-3 text-emerald-300" />}
        <span>{SEEED_PHASE_LABEL[phase]}</span>
      </div>
      <div className="max-h-32 space-y-1 overflow-y-auto">
        {turns.map((turn, i) => (
          <div
            key={i}
            className={`rounded px-2 py-1 text-[11px] leading-relaxed ${
              turn.role === 'user' ? 'bg-sky-500/10 text-sky-100' : 'bg-emerald-500/10 text-emerald-100'
            }`}
          >
            <span className="mr-1 text-[9px] uppercase text-muted-foreground/60">
              {turn.role === 'user' ? '你' : 'Reachy'}
            </span>
            {turn.text}
          </div>
        ))}
        {unclear && (
          <div className="rounded bg-amber-500/10 px-2 py-1 text-[10px] text-amber-200">未听清，请再说一次</div>
        )}
      </div>
    </div>
  )
}

function SeeedNativeSection({
  open,
  onToggle,
  status,
  setupBusy,
  llmKey,
  setLlmKey,
  asrKey,
  setAsrKey,
  model,
  setModel,
  busy,
  daemonOnline,
  onStart,
  onStop,
  onInstall,
}: {
  open: boolean
  onToggle: () => void
  status: ReachySeeedConversationStatus | null
  setupBusy: boolean
  llmKey: string
  setLlmKey: (s: string) => void
  asrKey: string
  setAsrKey: (s: string) => void
  model: string
  setModel: (s: string) => void
  busy: boolean
  daemonOnline: boolean
  onStart: () => void
  onStop: () => void
  onInstall: () => void
}) {
  const running = !!status?.running
  const keysReady = !!status?.keys_configured || (!!llmKey.trim() && !!asrKey.trim())
  return (
    <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between px-2.5 py-1.5 text-xs transition-colors hover:bg-white/5"
      >
        <span className="flex items-center gap-1.5 font-medium text-emerald-200">
          <Mic2 className="h-3.5 w-3.5" />
          本体对话（豆包）
        </span>
        <span className="flex items-center gap-1.5">
          {setupBusy && (
            <Badge variant="outline" className="border-amber-500/40 text-[9px] text-amber-200">
              配置中…
            </Badge>
          )}
          {status?.installed && !setupBusy && (
            <Badge variant="outline" className="border-emerald-500/40 text-[9px] text-emerald-300">
              已就绪
            </Badge>
          )}
          {running && (
            <Badge variant="outline" className="border-emerald-500/40 text-[9px] text-emerald-300">
              运行中
            </Badge>
          )}
          {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </span>
      </button>

      {open && (
        <div className="space-y-2 border-t border-emerald-500/20 p-2.5">
          <div className="text-[10px] leading-relaxed text-muted-foreground">
            Seeed 开源豆包方案：麦克风/喇叭走机器人本体。需火山引擎 Key。
          </div>
          {status?.audio_hint && (
            <div className="rounded border border-amber-500/30 bg-amber-500/10 p-1.5 text-[9px] text-amber-200/90">
              {status.audio_hint}
            </div>
          )}
          <div className="space-y-1">
            <div className="text-[10px] text-muted-foreground">豆包 LLM API Key（方舟）</div>
            <input
              type="password"
              value={llmKey}
              onChange={(e) => setLlmKey(e.target.value)}
              disabled={running}
              placeholder={status?.keys_configured ? '已配置（可留空）' : '火山引擎方舟 API Key'}
              className="h-8 w-full rounded-md border bg-background px-2 font-mono text-xs"
            />
          </div>
          <div className="space-y-1">
            <div className="text-[10px] text-muted-foreground">豆包语音识别 API Key</div>
            <input
              type="password"
              value={asrKey}
              onChange={(e) => setAsrKey(e.target.value)}
              disabled={running}
              placeholder={status?.keys_configured ? '已配置（可留空）' : '语音识别 Key'}
              className="h-8 w-full rounded-md border bg-background px-2 font-mono text-xs"
            />
          </div>
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={running}
            placeholder="Model ID"
            className="h-8 w-full rounded-md border bg-background px-2 font-mono text-xs"
          />
          <div className="flex gap-1.5">
            {!running ? (
              <Button
                size="sm"
                className="h-8 flex-1 bg-emerald-600 hover:bg-emerald-500"
                onClick={onStart}
                disabled={busy || setupBusy || !daemonOnline || !keysReady}
              >
                <Mic className="h-3.5 w-3.5" />
                启动本体对话
              </Button>
            ) : (
              <Button size="sm" variant="destructive" className="h-8 flex-1" onClick={onStop} disabled={busy}>
                <MicOff className="h-3.5 w-3.5" />
                停止
              </Button>
            )}
            {!status?.installed && (
              <Button size="sm" variant="outline" className="h-8" onClick={onInstall} disabled={busy}>
                安装
              </Button>
            )}
          </div>
          {running && <SeeedTranscript status={status} />}
        </div>
      )}
    </div>
  )
}

function ProSection({
  open,
  onToggle,
  template,
  proProvider,
  setProProvider,
  proApiKey,
  setProApiKey,
  proModel,
  setProModel,
  isRunning,
  gradioUrl,
  busy,
  onStart,
  onStop,
  voiceProvider,
  setVoiceProvider,
  voiceKey,
  setVoiceKey,
  voiceState,
  voiceSpeaking,
  voiceListening,
  voiceError,
  onVoiceStart,
  onVoiceStop,
}: {
  open: boolean
  onToggle: () => void
  template: ReachyConversationEnvTemplateV2 | null
  proProvider: ReachyConversationProvider
  setProProvider: (p: ReachyConversationProvider) => void
  proApiKey: string
  setProApiKey: (s: string) => void
  proModel: string
  setProModel: (s: string) => void
  isRunning: boolean
  gradioUrl: string | null
  busy: boolean
  onStart: () => void
  onStop: () => void
  voiceProvider: VoiceProvider
  setVoiceProvider: (p: VoiceProvider) => void
  voiceKey: string
  setVoiceKey: (s: string) => void
  voiceState: VoiceConnectionState
  voiceSpeaking: boolean
  voiceListening: boolean
  voiceError: string | null
  onVoiceStart: () => void
  onVoiceStop: () => void
}) {
  const isVoiceMode = proProvider === 'openai_pro'
  const voiceConnected = voiceState === 'ready' || voiceState === 'connecting'
  const voiceMeta = VOICE_PROVIDER_META[voiceProvider]

  return (
    <div className="rounded-md border border-white/10 bg-muted/20">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between px-2.5 py-1.5 text-xs transition-colors hover:bg-white/5"
      >
        <span className="flex items-center gap-1.5 font-medium text-amber-200">
          <Sparkles className="h-3.5 w-3.5" />
          实验：浏览器实时语音
        </span>
        {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
      </button>

      {open && (
        <div className="space-y-2 border-t border-white/5 p-2.5">
          <div className="text-[10px] text-muted-foreground">
            麦克风在电脑上。优先用上方「官方实时对话」（零 Key）。
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {(['openai_pro', 'gemini_pro'] as const).map((p) => {
              const active = proProvider === p
              const disabled = isRunning || voiceConnected
              const label = p === 'openai_pro' ? '实时语音 (OpenAI/通义)' : (template?.providers[p]?.label ?? 'Gemini')
              return (
                <button
                  key={p}
                  type="button"
                  disabled={disabled}
                  onClick={() => setProProvider(p)}
                  className={`rounded-md border px-2 py-1.5 text-left text-xs transition-colors ${
                    active
                      ? 'border-amber-500/60 bg-amber-500/15 text-foreground'
                      : 'border-white/10 text-muted-foreground hover:border-white/20'
                  } ${disabled ? 'cursor-not-allowed opacity-60' : ''}`}
                >
                  <div className="font-medium">{label}</div>
                  <div className="text-[9px] text-amber-300/80">需 Key</div>
                </button>
              )
            })}
          </div>

          {isVoiceMode ? (
            <>
              <div className="grid grid-cols-2 gap-1.5">
                {(['openai', 'qwen'] as const).map((p) => {
                  const active = voiceProvider === p
                  return (
                    <button
                      key={p}
                      type="button"
                      disabled={voiceConnected}
                      onClick={() => setVoiceProvider(p)}
                      className={`rounded-md border px-2 py-1.5 text-left text-[11px] transition-colors ${
                        active
                          ? 'border-sky-500/60 bg-sky-500/15 text-foreground'
                          : 'border-white/10 text-muted-foreground hover:border-white/20'
                      } ${voiceConnected ? 'cursor-not-allowed opacity-60' : ''}`}
                    >
                      {VOICE_PROVIDER_META[p].label}
                    </button>
                  )
                })}
              </div>
              <div className="space-y-1">
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{voiceMeta.keyEnv}</div>
                <input
                  type="password"
                  value={voiceKey}
                  onChange={(e) => setVoiceKey(e.target.value)}
                  disabled={voiceConnected}
                  placeholder={voiceProvider === 'qwen' ? '留空则用 bl CLI key' : voiceMeta.placeholder}
                  className="h-8 w-full rounded-md border bg-background px-2 font-mono text-xs"
                />
              </div>
              <div className="flex gap-1.5">
                {!voiceConnected ? (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-8 flex-1 border-amber-500/40 text-amber-200 hover:bg-amber-500/10"
                    onClick={onVoiceStart}
                  >
                    <Mic className="h-3.5 w-3.5" />
                    开始语音对话
                  </Button>
                ) : (
                  <Button size="sm" variant="destructive" className="h-8 flex-1" onClick={onVoiceStop}>
                    <MicOff className="h-3.5 w-3.5" />
                    结束语音对话
                  </Button>
                )}
              </div>
              {voiceConnected && (
                <Badge variant="outline" className="text-[9px]">
                  {voiceState === 'connecting'
                    ? '连接中…'
                    : voiceListening
                      ? '在听你说…'
                      : voiceSpeaking
                        ? '正在说话…'
                        : '已连接'}
                </Badge>
              )}
              {voiceError && (
                <div className="rounded-md border border-red-500/40 bg-red-500/10 p-1.5 text-[10px] text-red-200">
                  {voiceError}
                </div>
              )}
            </>
          ) : (
            <>
              <input
                type="password"
                value={proApiKey}
                onChange={(e) => setProApiKey(e.target.value)}
                disabled={isRunning}
                placeholder="GEMINI_API_KEY"
                className="h-8 w-full rounded-md border bg-background px-2 font-mono text-xs"
              />
              <input
                type="text"
                value={proModel}
                onChange={(e) => setProModel(e.target.value)}
                disabled={isRunning}
                placeholder="模型名 (可选)"
                className="h-8 w-full rounded-md border bg-background px-2 font-mono text-xs"
              />
              <div className="flex gap-1.5">
                {!isRunning ? (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-8 flex-1 border-amber-500/40 text-amber-200 hover:bg-amber-500/10"
                    onClick={onStart}
                    disabled={busy}
                  >
                    {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                    启动 Gemini
                  </Button>
                ) : (
                  <>
                    <Button size="sm" variant="destructive" className="h-8 flex-1" onClick={onStop} disabled={busy}>
                      <Square className="h-3.5 w-3.5" />
                      停止
                    </Button>
                    {gradioUrl && (
                      <a
                        href={gradioUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="flex items-center gap-1 rounded-md border border-sky-500/30 bg-sky-500/10 px-2 text-xs text-sky-200"
                      >
                        UI
                      </a>
                    )}
                  </>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function parseErr(msg: string): string {
  try {
    const j = JSON.parse(msg)
    return j?.detail?.message || j?.detail || msg
  } catch {
    return msg
  }
}
