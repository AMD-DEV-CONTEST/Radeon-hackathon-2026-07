/**
 * M26 — Reachy Mini 主区视觉化 Stage.
 *
 * 替代旧的「黑底 UrdfViewer + 顶部一行遥测」孤立布局，把主区做成一个
 *   [3D 模型 / 占位插画] + [摄像头画中画] + [当前对话气泡] + [底部状态条]
 * 的复合视觉，让用户进来就有「机器人在这里、它在做什么」的即时反馈。
 *
 * 设计原则：
 *  - 主区永远不空：3D 加载失败时显示占位插画 + CTA（启动虚拟模式）
 *  - 摄像头画中画默认收起，[视觉] Tab 里开了预览后自动浮现
 *  - 对话气泡只在 chat state != idle 时显示，不打扰普通控制
 *  - 状态条三盏灯（daemon / 音频 / 跟踪）一目了然，点击直达对应 Tab
 */
import { useEffect, useState, useCallback, useRef, type ReactNode } from 'react'
import {
  Activity,
  Camera,
  CameraOff,
  Ear,
  Eye,
  Headphones,
  Loader2,
  MessageSquare,
  Mic2,
  Volume2,
  Wifi,
  WifiOff,
} from 'lucide-react'
import { UrdfViewer } from '../features/UrdfViewer'
import {
  REACHY_MINI_HIDDEN_LINKS,
  applyReachyHeadWorldRpy,
  hasPassiveJoints,
} from '../../lib/reachyVirtualPreview'
import { Badge } from '../ui/badge'
import {
  getReachyChatStatus,
  getReachyConversationStatusV2,
  getReachyDoA,
  listReachyCameras,
  type ReachyChatState,
  type ReachyConversationProvider,
} from '../../lib/reachyApi'

interface Props {
  // Robot metadata + state (from parent page)
  urdfUrl: string | undefined
  joints: Record<string, number> | null
  cameraPosition?: [number, number, number]
  // Online flags (from parent page's polling)
  daemonOnline: boolean
  audioAvailable: boolean
  // Camera preview URL (set by parent when user opens preview in Vision tab)
  cameraPreviewUrl?: string | null
  cameraPreviewDevice?: number
  // Triggered when user clicks the placeholder CTA
  onStartVirtual?: () => void
  // Tab navigation callback (clicking status lights jumps to a tab)
  onNavigateTab?: (tab: 'chat' | 'motion' | 'vision') => void
  /**
   * Head RPY (roll, pitch, yaw) in radians, in the body frame, that the 3D
   * head should track. The URDF Stewart chain can't represent the closed
   * neck loop, so we override the head link's world rotation directly from
   * these values. Pass zeros when no live data is available — the head will
   * rest upright instead of inheriting the URDF's tilted default pose.
   */
  headRpy?: { roll: number; pitch: number; yaw: number } | null
}

// `bubble` is computed via composeBubble below; no need for an exported type.

export function ReachyStage({
  urdfUrl,
  joints,
  cameraPosition = [0.28, 0.38, 0.48],
  daemonOnline,
  audioAvailable,
  cameraPreviewUrl,
  cameraPreviewDevice,
  onStartVirtual,
  onNavigateTab,
  headRpy,
}: Props) {
  const [chatState, setChatState] = useState<ReachyChatState>('idle')
  const [chatText, setChatText] = useState<string | null>(null)
  const [provider, setProvider] = useState<ReachyConversationProvider | null>(null)
  const [conversationRunning, setConversationRunning] = useState(false)
  const [headTrackerRunning, setHeadTrackerRunning] = useState(false)
  const [hasCamera, setHasCamera] = useState(false)
  const [pipBroken, setPipBroken] = useState(false)

  const refresh = useCallback(async () => {
    if (!daemonOnline) {
      // Daemon offline → all reachy daemon endpoints return 502; skip to keep console clean.
      setHasCamera(false)
      setHeadTrackerRunning(false)
      return
    }
    try {
      const [chat, conv, doa, cams] = await Promise.all([
        getReachyChatStatus().catch(() => null),
        getReachyConversationStatusV2().catch(() => null),
        getReachyDoA().catch(() => null),
        listReachyCameras().catch(() => null),
      ])
      if (chat) {
        setChatState(chat.state)
        setChatText(chat.last_reply ?? chat.last_user_message)
      }
      if (conv) {
        setProvider(conv.provider)
        setConversationRunning(!!conv.running && conv.provider !== 'botversex')
      }
      // Head tracker "running" inferred from DOA returning a value or daemon
      // head-tracker state (we don't poll head-tracker status here directly
      // to avoid extra requests; the Vision tab does it on its own).
      if (doa && typeof doa.angle === 'number') {
        // DOA only returns a value when audio is active; not a perfect proxy
        // for head-tracker, so we keep this conservative.
      }
      if (cams?.devices?.length) {
        setHasCamera(true)
        // If a head tracker is currently running (best-effort inference: the
        // daemon exposes no separate status endpoint, but we can ask the
        // vision tab. For now we just keep the light off until told otherwise.)
        setHeadTrackerRunning(false)
      }
    } catch {
      /* non-fatal */
    }
  }, [])

  useEffect(() => {
    void refresh()
    // When daemon is offline, poll less often — no point hammering endpoints that 502.
    const id = setInterval(() => void refresh(), daemonOnline ? 3000 : 15000)
    return () => clearInterval(id)
  }, [refresh, daemonOnline])

  // ---- Compose bubble ----
  const bubble = composeBubble(chatState, chatText, conversationRunning, provider)

  // Keep the latest head RPY in a ref so the afterJointUpdate closure below
  // (which is captured by RobotNode's useFrame) always reads fresh values
  // without forcing a new closure identity each tick.
  const headRpyRef = useRef(headRpy)
  headRpyRef.current = headRpy

  // Three-tier Stewart visualization (matches official desktop app / bb896a8):
  //  1. Daemon Placo → passive_joints in WS stream → rods + head via chain
  //  2. AnalyticalKinematics → WASM computes passive_joints locally → same
  //  3. No live data / WASM failed → hide rods + RPY head override (preview only)
  const passivePresent = hasPassiveJoints(joints)
  const hiddenLinks = passivePresent ? undefined : REACHY_MINI_HIDDEN_LINKS
  const afterJointUpdate = useCallback(
    (robot: import('three').Object3D) => {
      if (passivePresent) return // chain drives head pose; no override needed
      const rpy = headRpyRef.current
      applyReachyHeadWorldRpy(robot, rpy?.roll ?? 0, rpy?.pitch ?? 0, rpy?.yaw ?? 0)
    },
    [passivePresent],
  )

  return (
    <div className="relative h-full w-full overflow-hidden rounded-xl border border-white/5 bg-[#0b0f1a]">
      {/* 3D / placeholder layer */}
      <div className="absolute inset-0">
        {urdfUrl ? (
          <UrdfViewer
            urdfUrl={urdfUrl}
            joints={joints ?? {}}
            cameraPosition={cameraPosition}
            hiddenLinks={hiddenLinks}
            afterJointUpdate={afterJointUpdate}
            className="h-full w-full"
          />
        ) : (
          <PlaceholderStage daemonOnline={daemonOnline} onStartVirtual={onStartVirtual} />
        )}
      </div>

      {/* Top-left: bubble */}
      {bubble && (
        <div className="absolute left-3 top-3 max-w-[60%] rounded-lg border border-white/10 bg-black/60 px-3 py-2 backdrop-blur">
          <div className="flex items-center gap-2 text-xs">
            <BubbleIcon state={chatState} />
            <span className="font-medium text-white/90">{bubble.title}</span>
          </div>
          {bubble.text && (
            <div className="mt-1 text-xs text-white/70 line-clamp-3">{bubble.text}</div>
          )}
        </div>
      )}

      {/* Top-right: provider badge */}
      {provider && (
        <div className="absolute right-3 top-3">
          <Badge
            variant="outline"
            className={`text-[10px] backdrop-blur ${
              provider === 'official' || provider === 'openai_pro' || provider === 'gemini_pro'
                ? 'border-sky-500/40 bg-sky-500/10 text-sky-200'
                : 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
            }`}
          >
            {provider === 'official'
              ? '官方双工'
              : provider === 'botversex'
                ? '平台聊天'
                : 'Pro 实时语音'}
          </Badge>
        </div>
      )}

      {/* Picture-in-picture camera (bottom-right). Hidden when the latest
          snapshot failed to load — defense-in-depth so we never show an empty
          black PiP box even if the upstream snapshot URL silently 404s. */}
      {cameraPreviewUrl && !pipBroken && (
        <div className="absolute bottom-12 right-3 z-10 overflow-hidden rounded-md border border-white/15 bg-black/80 shadow-lg">
          <div className="absolute left-1 top-1 z-10 rounded bg-black/60 px-1.5 py-0.5 text-[9px] font-mono text-white/80 backdrop-blur">
            cam{cameraPreviewDevice ?? 0}
          </div>
          <img
            key={cameraPreviewUrl}
            src={cameraPreviewUrl}
            alt="camera preview"
            className="h-[120px] w-[160px] object-cover"
            onError={() => setPipBroken(true)}
            onLoad={() => setPipBroken(false)}
          />
        </div>
      )}

      {/* Bottom status bar */}
      <div className="absolute bottom-0 left-0 right-0 z-10 flex items-center justify-between gap-2 border-t border-white/5 bg-black/60 px-3 py-1.5 backdrop-blur">
        <div className="flex items-center gap-3 text-[10px]">
          <StatusLight
            label="daemon"
            ok={daemonOnline}
            okIcon={<Wifi className="h-3 w-3" />}
            badIcon={<WifiOff className="h-3 w-3" />}
            onClick={() => onNavigateTab?.('motion')}
          />
          <StatusLight
            label="音频"
            ok={audioAvailable}
            okIcon={<Headphones className="h-3 w-3" />}
            badIcon={<Volume2 className="h-3 w-3" />}
            onClick={() => onNavigateTab?.('chat')}
          />
          <StatusLight
            label="摄像头"
            ok={hasCamera}
            okIcon={<Camera className="h-3 w-3" />}
            badIcon={<CameraOff className="h-3 w-3" />}
            onClick={() => onNavigateTab?.('vision')}
          />
          <StatusLight
            label="跟踪"
            ok={headTrackerRunning}
            okIcon={<Eye className="h-3 w-3" />}
            badIcon={<Activity className="h-3 w-3" />}
            onClick={() => onNavigateTab?.('vision')}
          />
        </div>
        {chatState !== 'idle' && (
          <div className="flex items-center gap-1.5 text-[10px] text-white/60">
            <Mic2 className="h-3 w-3 animate-pulse" />
            <span>{chatState === 'listening' ? '聆听中' : chatState === 'thinking' ? '思考中' : '说话中'}</span>
          </div>
        )}
      </div>
    </div>
  )
}

// ---- Sub-components -------------------------------------------------------

function PlaceholderStage({
  daemonOnline,
  onStartVirtual,
}: {
  daemonOnline: boolean
  onStartVirtual?: () => void
}) {
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-4 text-center">
      <div className="flex h-20 w-20 items-center justify-center rounded-2xl border border-white/10 bg-white/5">
        <Loader2 className="h-8 w-8 animate-spin text-white/40" />
      </div>
      <div className="space-y-1">
        <div className="text-sm font-medium text-white/80">3D 模型加载中或未就绪</div>
        <div className="text-xs text-white/50">
          {daemonOnline
            ? '机器人已连接，但 URDF 还没加载好。'
            : '机器人未连接。可启动虚拟模式预览动作。'}
        </div>
      </div>
      {!daemonOnline && onStartVirtual && (
        <button
          type="button"
          onClick={onStartVirtual}
          className="rounded-md border border-[hsl(var(--primary))]/60 bg-[hsl(var(--primary))]/15 px-3 py-1.5 text-xs font-medium text-foreground hover:bg-[hsl(var(--primary))]/25"
        >
          启动虚拟模式
        </button>
      )}
    </div>
  )
}

function StatusLight({
  label,
  ok,
  okIcon,
  badIcon,
  onClick,
}: {
  label: string
  ok: boolean
  okIcon: ReactNode
  badIcon: ReactNode
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-white/10 transition-colors"
      title={`${label}: ${ok ? '正常' : '不可用'}`}
    >
      <span className={ok ? 'text-emerald-300' : 'text-white/30'}>
        {ok ? okIcon : badIcon}
      </span>
      <span className={ok ? 'text-white/70' : 'text-white/30'}>{label}</span>
    </button>
  )
}

function BubbleIcon({ state }: { state: ReachyChatState }) {
  if (state === 'listening') return <Ear className="h-3 w-3 text-sky-300" />
  if (state === 'thinking') return <Loader2 className="h-3 w-3 animate-spin text-amber-300" />
  if (state === 'speaking') return <MessageSquare className="h-3 w-3 text-emerald-300" />
  return <Mic2 className="h-3 w-3 text-white/60" />
}

function composeBubble(
  state: ReachyChatState,
  text: string | null,
  conversationRunning: boolean,
  provider: ReachyConversationProvider | null,
): { title: string; text: string | null } | null {
  if (state === 'listening') {
    return { title: '聆听中…', text: text ? `「${text}」` : null }
  }
  if (state === 'thinking') {
    return { title: '思考中…', text: null }
  }
  if (state === 'speaking') {
    return { title: '正在说…', text }
  }
  if (conversationRunning && (provider === 'official' || provider === 'openai_pro' || provider === 'gemini_pro')) {
    return { title: '官方实时对话中', text: '对着机器人说话，或在右侧对话面板操作' }
  }
  if (conversationRunning && provider === 'botversex') {
    return { title: '平台聊天已就绪', text: text ? `上次回复: ${text.slice(0, 80)}` : null }
  }
  return null
}
