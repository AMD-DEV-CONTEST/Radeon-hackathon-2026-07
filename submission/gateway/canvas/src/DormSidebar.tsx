import { ChevronDown, ChevronRight, Circle, Monitor, Server, UserPlus } from 'lucide-react'

export type DormAgentStatus = 'standby' | 'busy' | 'offline' | 'error'
export type DormMachineStatus = 'online' | 'offline' | 'unknown' | 'error'
export type SessionRole = 'leader' | 'reviewer' | 'implementer' | 'ops' | 'observer'

export interface DormAgent {
  agentTemplateId: string
  agentName: string
  agentType: string
  status: DormAgentStatus
  capabilities: Record<string, unknown>
}

export interface DormMachine {
  machineId: string
  displayName: string
  location: string
  status: DormMachineStatus
  launcherStatus?: 'connected' | 'disconnected' | 'starting'
  agents: DormAgent[]
}

interface DormSidebarProps {
  machines: DormMachine[]
  onSummon: (machine: DormMachine, agent: DormAgent, role: SessionRole) => void
  disabled?: boolean
}

const roles: SessionRole[] = ['leader', 'reviewer', 'implementer', 'ops', 'observer']

function machineIcon(location: string) {
  if (location.includes('ecs') || location.includes('aws') || location.includes('gcp')) {
    return <Server size={15} />
  }
  return <Monitor size={15} />
}

export function DormSidebar({ machines, onSummon, disabled }: DormSidebarProps) {
  const sorted = [...machines].sort((a, b) => a.displayName.localeCompare(b.displayName))

  return (
    <section className="dorm-sidebar">
      <div className="section-title">
        <h2>Dorms / Machines</h2>
        <span className="dorm-count">{sorted.length}</span>
      </div>

      <div className="dorm-list">
        {sorted.map((machine) => (
          <details key={machine.machineId} className={`dorm-machine ${machine.status}`} open={machine.status === 'online'}>
            <summary>
              <span className="dorm-chevron closed"><ChevronRight size={13} /></span>
              <span className="dorm-chevron opened"><ChevronDown size={13} /></span>
              <span className={`dorm-light ${machine.status}`} />
              {machineIcon(machine.location)}
              <span className="dorm-name">{machine.displayName}</span>
              <span className="dorm-status">{machine.status}</span>
            </summary>

            <div className="dorm-meta">
              launcher {machine.launcherStatus ?? 'disconnected'} · {machine.location}
            </div>

            <div className="dorm-agents">
              {machine.agents.length === 0 && (
                <div className="dorm-empty">未开机 / 未注册</div>
              )}
              {machine.agents.map((agent) => (
                <DormAgentRow
                  key={agent.agentTemplateId}
                  machine={machine}
                  agent={agent}
                  disabled={disabled || machine.status !== 'online' || agent.status !== 'standby'}
                  onSummon={onSummon}
                />
              ))}
            </div>
          </details>
        ))}
      </div>
    </section>
  )
}

function DormAgentRow({
  machine,
  agent,
  disabled,
  onSummon,
}: {
  machine: DormMachine
  agent: DormAgent
  disabled?: boolean
  onSummon: (machine: DormMachine, agent: DormAgent, role: SessionRole) => void
}) {
  const selectId = `${machine.machineId}-${agent.agentTemplateId}-role`

  return (
    <div className={`dorm-agent ${agent.status}`}>
      <Circle size={9} className="dorm-agent-dot" />
      <div className="dorm-agent-main">
        <strong>{agent.agentName}</strong>
        <small>{agent.agentType} · {agent.status}</small>
      </div>
      <select
        id={selectId}
        className="role-select"
        defaultValue="observer"
        disabled={disabled}
      >
        {roles.map((role) => (
          <option key={role} value={role}>{role}</option>
        ))}
      </select>
      <button
        className="summon-btn"
        disabled={disabled}
        title={disabled ? 'Agent unavailable' : '拉进当前大画布'}
        onClick={() => {
          const select = document.getElementById(selectId) as HTMLSelectElement | null
          onSummon(machine, agent, (select?.value as SessionRole) || 'observer')
        }}
      >
        <UserPlus size={13} />
      </button>
    </div>
  )
}
