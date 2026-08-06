/**
 * M26 — Reachy Mini 右栏 Tab 容器.
 *
 * 取代旧的「9 个 Card 上下堆叠」布局，改成 3 个 Tab + 1 个底部「高级」折叠抽屉。
 * 默认 Tab 是「对话」——新手最常用、零 Key 即可用。
 *
 *   ┌────────────────────────────────┐
 *   │ [对话] [动作] [视觉]            │
 *   ├────────────────────────────────┤
 *   │                                │
 *   │   当前 Tab 内容                 │
 *   │                                │
 *   ├────────────────────────────────┤
 *   │ 高级 ⌄                          │ (折叠抽屉，默认收起)
 *   └────────────────────────────────┘
 */
import { useState, useSyncExternalStore, type ReactNode } from 'react'
import { MessageSquare, Music4, Eye, Settings2, ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '../../lib/utils'
import { reachyRandomMotionStore } from '../../lib/reachyRandomMotionStore'

export type ReachyTab = 'chat' | 'motion' | 'vision'

interface Props {
  daemonOnline: boolean
  activeTab: ReachyTab
  onTabChange: (tab: ReachyTab) => void
  chatPanel: ReactNode
  motionPanel: ReactNode
  visionPanel: ReactNode
  advancedPanel: ReactNode
}

const TABS: Array<{ id: ReachyTab; label: string; icon: typeof MessageSquare }> = [
  { id: 'chat', label: '对话', icon: MessageSquare },
  { id: 'motion', label: '动作', icon: Music4 },
  { id: 'vision', label: '视觉', icon: Eye },
]

export function ReachySidebarTabs({
  daemonOnline,
  activeTab,
  onTabChange,
  chatPanel,
  motionPanel,
  visionPanel,
  advancedPanel,
}: Props) {
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const randomActive = useSyncExternalStore(
    reachyRandomMotionStore.subscribe,
    reachyRandomMotionStore.getActive,
    reachyRandomMotionStore.getActive,
  )

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-white/5 bg-[#0b0f1a]/40">
      {/* Tab header */}
      <div className="flex shrink-0 items-center gap-0.5 border-b border-white/5 bg-black/30 px-1.5 py-1.5">
        {TABS.map((t) => {
          const Icon = t.icon
          const active = activeTab === t.id
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => onTabChange(t.id)}
              className={cn(
                'flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs transition-colors',
                active
                  ? 'bg-[hsl(var(--primary))]/15 text-foreground font-medium'
                  : 'text-muted-foreground hover:bg-white/5 hover:text-foreground/80',
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {t.label}
              {t.id === 'motion' && randomActive ? (
                <span className="h-1.5 w-1.5 rounded-full bg-violet-400 animate-pulse" title="随机表演进行中" />
              ) : null}
            </button>
          )
        })}
      </div>

      {/* Tab body */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {activeTab === 'chat' && chatPanel}
        {activeTab === 'motion' && motionPanel}
        {activeTab === 'vision' && visionPanel}
      </div>

      {/* Advanced drawer */}
      <div className="shrink-0 border-t border-white/5 bg-black/30">
        <button
          type="button"
          onClick={() => setAdvancedOpen((v) => !v)}
          className="flex w-full items-center justify-between px-3 py-2 text-xs text-muted-foreground hover:bg-white/5 hover:text-foreground transition-colors"
        >
          <span className="flex items-center gap-1.5">
            <Settings2 className="h-3.5 w-3.5" />
            高级 · daemon / 录制 / goto
          </span>
          {advancedOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
        {advancedOpen && (
          <div className="max-h-[320px] overflow-y-auto border-t border-white/5 p-3 space-y-3">
            {advancedPanel}
          </div>
        )}
      </div>

      {/* Offline banner */}
      {!daemonOnline && (
        <div className="shrink-0 border-t border-amber-500/30 bg-amber-500/5 px-3 py-1.5 text-[10px] text-amber-200">
          守护进程未连接 — 部分功能不可用。点高级 → daemon 启动。
        </div>
      )}
    </div>
  )
}
