import { MonitorUp } from 'lucide-react'
import { AgentWindow, type AgentWindowState } from './AgentWindow'

interface WindowManagerProps {
  windows: AgentWindowState[]
  focusedId: string | null
  sessionId: string | null
  currentRound: number
  onFocus: (id: string) => void
  onPatch: (id: string, patch: Partial<AgentWindowState>) => void
  onMinimize: (id: string) => void
  onRestore: (id: string) => void
  onClose: (id: string) => void
  onLeaderSubmit?: (
    id: string,
    kind: 'audit' | 'deployment' | 'decision',
    value: string,
  ) => Promise<void>
}

export function WindowManager({
  windows,
  focusedId,
  sessionId,
  currentRound,
  onFocus,
  onPatch,
  onMinimize,
  onRestore,
  onClose,
  onLeaderSubmit,
}: WindowManagerProps) {
  return (
    <div className="window-layer">
      {windows.map((window) => (
        <AgentWindow
          key={window.id}
          window={window}
          focused={window.id === focusedId}
          sessionId={sessionId}
          currentRound={currentRound}
          onFocus={onFocus}
          onPatch={onPatch}
          onMinimize={onMinimize}
          onClose={onClose}
          onLeaderSubmit={
            onLeaderSubmit
              ? async (kind, value) => { await onLeaderSubmit(window.id, kind, value ?? '') }
              : undefined
          }
        />
      ))}

      <div className="agent-taskbar">
        {windows.map((window) => (
          <button
            key={window.id}
            className={`taskbar-item ${window.minimized ? 'minimized' : ''} ${window.id === focusedId ? 'focused' : ''}`}
            onClick={() => {
              onRestore(window.id)
              onFocus(window.id)
            }}
          >
            <MonitorUp size={13} />
            <span>{window.agentName}</span>
            <small>{window.role}</small>
          </button>
        ))}
        {windows.length === 0 && (
          <div className="taskbar-empty">从左侧宿舍拉一个 standby Agent 进入大画布</div>
        )}
      </div>
    </div>
  )
}
