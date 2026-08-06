/**
 * M27 — OpenAI Realtime 语音助手：浏览器端音频采集 / 播放 + WS 客户端.
 *
 * 嵌入 `ReachyChatTab`，不依赖官方 Conversation App 子进程 / Gradio 页面。
 * 连接到本地 Agent 的 `/ws/reachy/voice/realtime` 桥接端点（见
 * `apps/realtime/api/reachy_realtime_voice.py`），该端点把浏览器的麦克风音频
 * 原样转发给 OpenAI Realtime API，并把模型触发的 function call 接到我们自己
 * 的机器人动作库上。
 *
 * 音频格式约定（跟后端 session.update 保持一致）：24kHz 单声道 PCM16。
 */
import { agentWsUrl } from './localAgent'

export type VoiceConnectionState = 'idle' | 'connecting' | 'ready' | 'closed' | 'error'

export interface VoiceToolExecuted {
  name: string
  arguments: Record<string, unknown>
  result: { ok: boolean; [key: string]: unknown }
}

export type VoiceProvider = 'openai' | 'qwen'

export interface ReachyRealtimeVoiceOptions {
  provider?: VoiceProvider
  apiKey: string
  model?: string
  voice?: string
  instructions?: string
  onStateChange?: (state: VoiceConnectionState) => void
  onError?: (message: string) => void
  onUserSpeechStart?: () => void
  onUserSpeechStop?: () => void
  onAssistantTextDelta?: (delta: string) => void
  onAssistantTextDone?: (text: string) => void
  onUserTranscriptDelta?: (delta: string) => void
  onUserTranscriptDone?: (text: string) => void
  onToolExecuted?: (info: VoiceToolExecuted) => void
  onAssistantSpeakingChange?: (speaking: boolean) => void
}

// Fallback rates until the backend's `botversex.ready` event tells us the real
// negotiated rates (OpenAI: in/out 24k; Qwen: in 16k, out 24k).
const DEFAULT_INPUT_RATE = 24000
const DEFAULT_OUTPUT_RATE = 24000
// ~85ms chunks at 24kHz — small enough for low latency, big enough not to spam the socket.
const CAPTURE_BUFFER_SIZE = 2048

function floatTo16BitPCM(float32: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(float32.length * 2)
  const view = new DataView(buffer)
  let offset = 0
  for (let i = 0; i < float32.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, float32[i]))
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return buffer
}

function base64FromArrayBuffer(buf: ArrayBuffer): string {
  let binary = ''
  const bytes = new Uint8Array(buf)
  const chunkSize = 0x8000
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize)
    binary += String.fromCharCode(...chunk)
  }
  return btoa(binary)
}

function pcm16Base64ToFloat32(base64: string): Float32Array {
  const binary = atob(base64)
  const len = binary.length
  const bytes = new Uint8Array(len)
  for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i)
  const view = new DataView(bytes.buffer)
  const sampleCount = Math.floor(len / 2)
  const out = new Float32Array(sampleCount)
  for (let i = 0; i < sampleCount; i++) {
    out[i] = view.getInt16(i * 2, true) / 0x8000
  }
  return out
}

/** Naive linear-interpolation resampler — good enough for speech, no external deps. */
function resample(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate) return input
  const ratio = fromRate / toRate
  const outLength = Math.round(input.length / ratio)
  const out = new Float32Array(outLength)
  for (let i = 0; i < outLength; i++) {
    const srcPos = i * ratio
    const i0 = Math.floor(srcPos)
    const i1 = Math.min(i0 + 1, input.length - 1)
    const frac = srcPos - i0
    out[i] = input[i0] * (1 - frac) + input[i1] * frac
  }
  return out
}

export class ReachyRealtimeVoiceClient {
  private ws: WebSocket | null = null
  private micStream: MediaStream | null = null
  private captureCtx: AudioContext | null = null
  private captureNode: ScriptProcessorNode | null = null
  private captureSource: MediaStreamAudioSourceNode | null = null
  private playbackCtx: AudioContext | null = null
  private nextPlaybackTime = 0
  private activeSources: AudioBufferSourceNode[] = []
  private assistantTextBuf = ''
  private userTranscriptBuf = ''
  private opts: ReachyRealtimeVoiceOptions
  private state: VoiceConnectionState = 'idle'
  private speaking = false
  private inputRate = DEFAULT_INPUT_RATE
  private outputRate = DEFAULT_OUTPUT_RATE

  constructor(opts: ReachyRealtimeVoiceOptions) {
    this.opts = opts
  }

  private setState(s: VoiceConnectionState) {
    this.state = s
    this.opts.onStateChange?.(s)
  }

  getState(): VoiceConnectionState {
    return this.state
  }

  async connect(): Promise<void> {
    if (this.state === 'connecting' || this.state === 'ready') return
    this.setState('connecting')

    try {
      this.micStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
    } catch (e) {
      this.setState('error')
      this.opts.onError?.(`无法获取麦克风权限：${(e as Error).message}`)
      return
    }

    // 创建一个"心跳" AudioContext 并立刻 resume，把这次用户点击的 gesture 注册到
    // 浏览器的 autoplay 白名单里——否则后面在 `botversex.ready` 异步回调里创建的
    // playbackCtx 会被卡在 suspended，结果是麦克风在收音、机器人也在回复，但你听
    // 不到任何声音（"开了麦克风但什么反应也没有"的常见根因）。
    try {
      const primer = new AudioContext()
      this.playbackCtx = primer
      this.nextPlaybackTime = primer.currentTime
      await primer.resume()
    } catch {
      /* ignore — real contexts created later */
    }

    // Playback AudioContext is created after the `botversex.ready` event, once
    // we know the negotiated output sample rate (differs per provider).
    this.nextPlaybackTime = 0

    const url = agentWsUrl('/ws/reachy/voice/realtime')
    const ws = new WebSocket(url)
    this.ws = ws

    ws.onopen = () => {
      ws.send(JSON.stringify({
        type: 'botversex.init',
        provider: this.opts.provider ?? 'openai',
        api_key: this.opts.apiKey,
        model: this.opts.model,
        voice: this.opts.voice,
        instructions: this.opts.instructions,
      }))
    }

    ws.onmessage = (evt) => this.handleServerEvent(evt.data as string)

    ws.onerror = () => {
      this.opts.onError?.('语音连接出错（WebSocket）')
    }

    ws.onclose = () => {
      if (this.state !== 'error') this.setState('closed')
      this.teardownCapture()
    }
  }

  private startCapture() {
    if (!this.micStream) return
    // ScriptProcessorNode is deprecated but universally supported and simplest
    // for a first cut — AudioWorklet would need a separately-served module file.
    const ctx = new AudioContext()
    this.captureCtx = ctx
    void ctx.resume()
    const source = ctx.createMediaStreamSource(this.micStream)
    this.captureSource = source
    const node = ctx.createScriptProcessor(CAPTURE_BUFFER_SIZE, 1, 1)
    this.captureNode = node

    node.onaudioprocess = (e) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return
      const input = e.inputBuffer.getChannelData(0)
      const resampled = resample(input, ctx.sampleRate, this.inputRate)
      const pcm = floatTo16BitPCM(resampled)
      const b64 = base64FromArrayBuffer(pcm)
      this.ws.send(JSON.stringify({ type: 'input_audio_buffer.append', audio: b64 }))
    }

    source.connect(node)
    // Some browsers require the processor node to be connected to a destination
    // to keep firing onaudioprocess, even though we don't want to hear ourselves.
    const mute = ctx.createGain()
    mute.gain.value = 0
    node.connect(mute)
    mute.connect(ctx.destination)
  }

  private teardownCapture() {
    try { this.captureNode?.disconnect() } catch { /* ignore */ }
    try { this.captureSource?.disconnect() } catch { /* ignore */ }
    try { this.captureCtx?.close() } catch { /* ignore */ }
    this.captureNode = null
    this.captureSource = null
    this.captureCtx = null
    try { this.micStream?.getTracks().forEach((t) => t.stop()) } catch { /* ignore */ }
    this.micStream = null
  }

  private stopPlayback() {
    for (const src of this.activeSources) {
      try { src.stop() } catch { /* ignore */ }
    }
    this.activeSources = []
    if (this.playbackCtx) this.nextPlaybackTime = this.playbackCtx.currentTime
  }

  private playChunk(base64Audio: string) {
    if (!this.playbackCtx) return
    const ctx = this.playbackCtx
    const float32 = pcm16Base64ToFloat32(base64Audio)
    if (float32.length === 0) return
    const buffer = ctx.createBuffer(1, float32.length, this.outputRate)
    buffer.copyToChannel(float32, 0)

    const src = ctx.createBufferSource()
    src.buffer = buffer
    src.connect(ctx.destination)

    const now = ctx.currentTime
    const startAt = Math.max(now, this.nextPlaybackTime)
    src.start(startAt)
    this.nextPlaybackTime = startAt + buffer.duration

    this.activeSources.push(src)
    src.onended = () => {
      this.activeSources = this.activeSources.filter((s) => s !== src)
      if (this.activeSources.length === 0 && this.speaking) {
        this.speaking = false
        this.opts.onAssistantSpeakingChange?.(false)
      }
    }
  }

  private handleServerEvent(raw: string) {
    let event: Record<string, unknown>
    try {
      event = JSON.parse(raw)
    } catch {
      return
    }
    const type = event.type as string

    switch (type) {
      case 'botversex.ready': {
        const inRate = Number(event.input_sample_rate)
        const outRate = Number(event.output_sample_rate)
        if (Number.isFinite(inRate) && inRate > 0) this.inputRate = inRate
        if (Number.isFinite(outRate) && outRate > 0) this.outputRate = outRate
        // 用协商好的输出采样率重建 playback context（primer 用的是浏览器默认 48k）。
        // 因为 connect() 里 primer 已经把 autoplay 解锁，这里新 ctx 可以直接 resume。
        try { this.playbackCtx?.close() } catch { /* ignore */ }
        this.playbackCtx = new AudioContext({ sampleRate: this.outputRate })
        this.nextPlaybackTime = this.playbackCtx.currentTime
        void this.playbackCtx.resume()
        this.setState('ready')
        this.startCapture()
        break
      }
      case 'botversex.error':
        this.setState('error')
        this.opts.onError?.((event.message as string) || (event.error as string) || '未知语音错误')
        break
      case 'botversex.tool_executed':
        this.opts.onToolExecuted?.({
          name: event.name as string,
          arguments: (event.arguments as Record<string, unknown>) || {},
          result: (event.result as { ok: boolean }) || { ok: false },
        })
        break
      case 'input_audio_buffer.speech_started':
        this.opts.onUserSpeechStart?.()
        // Barge-in: stop whatever we're currently playing so the user isn't
        // talked over — matches the interruption pattern from OpenAI's docs.
        this.stopPlayback()
        break
      case 'input_audio_buffer.speech_stopped':
        this.opts.onUserSpeechStop?.()
        break
      case 'conversation.item.input_audio_transcription.delta':
        this.userTranscriptBuf += (event.delta as string) || (event.text as string) || ''
        this.opts.onUserTranscriptDelta?.((event.delta as string) || (event.text as string) || '')
        break
      case 'conversation.item.input_audio_transcription.text':
        this.userTranscriptBuf += (event.text as string) || ''
        this.opts.onUserTranscriptDelta?.((event.text as string) || '')
        break
      case 'conversation.item.input_audio_transcription.completed':
        this.opts.onUserTranscriptDone?.((event.transcript as string) || this.userTranscriptBuf)
        this.userTranscriptBuf = ''
        break
      case 'response.output_audio.delta':
      case 'response.audio.delta': {
        const delta = event.delta as string
        if (delta) {
          if (!this.speaking) {
            this.speaking = true
            this.opts.onAssistantSpeakingChange?.(true)
          }
          this.playChunk(delta)
        }
        break
      }
      // Assistant transcript deltas. OpenAI GA uses `response.output_*`; Qwen
      // (and OpenAI beta) use `response.audio_transcript.*` / `response.text.*`.
      case 'response.output_audio_transcript.delta':
      case 'response.output_text.delta':
      case 'response.audio_transcript.delta':
      case 'response.text.delta': {
        const delta = (event.delta as string) || ''
        this.assistantTextBuf += delta
        this.opts.onAssistantTextDelta?.(delta)
        break
      }
      case 'response.output_audio_transcript.done':
      case 'response.output_text.done':
      case 'response.audio_transcript.done':
      case 'response.text.done': {
        const finalText = (event.transcript as string) || (event.text as string) || this.assistantTextBuf
        this.opts.onAssistantTextDone?.(finalText)
        this.assistantTextBuf = ''
        break
      }
      case 'response.done':
        if (this.assistantTextBuf) {
          this.opts.onAssistantTextDone?.(this.assistantTextBuf)
          this.assistantTextBuf = ''
        }
        break
      case 'error':
        this.opts.onError?.((event.message as string) || 'OpenAI Realtime 返回错误')
        break
      default:
        break
    }
  }

  /** Manually trigger a text-only turn (e.g. quick text fallback alongside voice). */
  sendText(text: string) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return
    this.ws.send(JSON.stringify({
      type: 'conversation.item.create',
      item: { type: 'message', role: 'user', content: [{ type: 'input_text', text }] },
    }))
    this.ws.send(JSON.stringify({ type: 'response.create' }))
  }

  disconnect() {
    this.stopPlayback()
    this.teardownCapture()
    try { this.playbackCtx?.close() } catch { /* ignore */ }
    this.playbackCtx = null
    try { this.ws?.close() } catch { /* ignore */ }
    this.ws = null
    this.setState('idle')
  }
}
