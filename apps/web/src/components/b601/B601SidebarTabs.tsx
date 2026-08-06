import { useState, type ReactNode } from 'react'
import { ChevronDown, ChevronUp, Database, Eye, Hand, Rocket, Settings2 } from 'lucide-react'
import { cn } from '../../lib/utils'

/** Main loop order: teleop → cameras → record → deploy. Rare tools live under Advanced. */
export type B601Tab = 'teleop' | 'vision' | 'record' | 'motion'

interface Props {
  activeTab: B601Tab
  onTabChange: (tab: B601Tab) => void
  teleopPanel: ReactNode
  visionPanel: ReactNode
  recordPanel: ReactNode
  motionPanel: ReactNode
  advancedPanel: ReactNode
}

const TABS: Array<{ id: B601Tab; label: string; icon: typeof Hand }> = [
  { id: 'teleop', label: '遥操', icon: Hand },
  { id: 'vision', label: '视觉', icon: Eye },
  { id: 'record', label: '数据', icon: Database },
  { id: 'motion', label: '部署', icon: Rocket },
]

const HINTS: Record<B601Tab, string> = {
  teleop: '① 用手遥控机械臂，熟悉手感',
  vision: '② 选好正面/侧面相机并预览（后面录数据和部署都用）',
  record: '③ 数据',
  motion: '④ 选训练好的模型，部署到机械臂',
}

export function B601SidebarTabs({
  activeTab,
  onTabChange,
  teleopPanel,
  visionPanel,
  recordPanel,
  motionPanel,
  advancedPanel,
}: Props) {
  const [advancedOpen, setAdvancedOpen] = useState(false)

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-white/5 bg-[#0b0f1a]/40">
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
            </button>
          )
        })}
      </div>
      <p className="shrink-0 border-b border-white/5 bg-black/20 px-3 py-1 text-[10px] text-muted-foreground">
        {HINTS[activeTab]}
      </p>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {activeTab === 'teleop' && teleopPanel}
        {activeTab === 'vision' && visionPanel}
        {activeTab === 'record' && recordPanel}
        {activeTab === 'motion' && motionPanel}
      </div>

      <div className="shrink-0 border-t border-white/5 bg-black/30">
        <button
          type="button"
          onClick={() => setAdvancedOpen((v) => !v)}
          className="flex w-full items-center justify-between px-3 py-2 text-xs text-muted-foreground hover:bg-white/5 hover:text-foreground transition-colors"
        >
          <span className="flex items-center gap-1.5">
            <Settings2 className="h-3.5 w-3.5" />
            高级（标定 · 故障恢复 · 自动到位）
          </span>
          {advancedOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
        {advancedOpen && (
          <div className="max-h-[360px] overflow-y-auto border-t border-white/5 p-3 space-y-3">
            {advancedPanel}
          </div>
        )}
      </div>
    </div>
  )
}
