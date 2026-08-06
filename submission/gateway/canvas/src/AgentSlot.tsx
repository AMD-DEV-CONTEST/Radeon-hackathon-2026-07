import { UserPlus, Bot } from 'lucide-react'

export interface AgentSlotData {
  id: string
  name: string
  agentType: string
  status: 'idle' | 'working' | 'done' | 'offline'
  opinion?: string
}

interface AgentSlotProps {
  agents: AgentSlotData[]
  stage: string
  onInvite?: () => void
}

export function AgentSlot({ agents, stage, onInvite }: AgentSlotProps) {
  const statusIcon = (status: string) => {
    switch (status) {
      case 'done': return '✅'
      case 'working': return '🔄'
      case 'idle': return '⏳'
      default: return '⬤'
    }
  }

  return (
    <div className="agent-slot-panel">
      <div className="agent-slot-header">
        <span>{stage}阶段</span>
        {onInvite && (
          <button className="invite-btn" onClick={onInvite}>
            <UserPlus size={14} /> 拉人
          </button>
        )}
      </div>
      <div className="agent-slot-list">
        {agents.length === 0 && (
          <div className="agent-slot-empty">点击"拉人"邀请 Agent 进入此阶段</div>
        )}
        {agents.map(agent => (
          <div key={agent.id} className={`agent-slot ${agent.status}`}>
            <Bot size={16} className="agent-slot-icon" />
            <span className="agent-slot-name">{agent.name}</span>
            <span className="agent-slot-type">{agent.agentType}</span>
            <span className="agent-slot-status">{statusIcon(agent.status)}</span>
            {agent.opinion && (
              <div className="agent-opinion">{agent.opinion}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
