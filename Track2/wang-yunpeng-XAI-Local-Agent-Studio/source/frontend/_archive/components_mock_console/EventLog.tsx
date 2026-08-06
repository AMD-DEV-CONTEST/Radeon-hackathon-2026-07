import { useEffect, useRef } from 'react'
import { useStore } from '../store'

const TYPE_COLOR: Record<string, string> = {
  thinking: '#0891b2',
  tool_call: '#7c3aed',
  tool_result: '#16a34a',
  interrupt: '#dc2626',
  progress: '#d97706',
  agent_switch: '#2563eb',
  done: '#0d9488',
  system: '#64748b',
}

export function EventLog() {
  const events = useStore((s) => s.events)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [events])

  return (
    <div className="eventlog">
      <div className="eventlog-h">📡 A2UI 事件流</div>
      <div className="eventlog-body" ref={ref}>
        {events.map((e) => (
          <div className="ev" key={e.id}>
            <span className="ev-type" style={{ color: TYPE_COLOR[e.type] || '#333', borderColor: TYPE_COLOR[e.type] || '#333' }}>{e.type}</span>
            <span className="ev-msg">{e.msg}</span>
            <span className="ev-ts">{new Date(e.ts).toLocaleTimeString()}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
