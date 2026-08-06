function Metric({ label, value }) {
  return (
    <div className="rounded-xl border border-white/6 bg-slate-950/70 px-3 py-2">
      <p className="text-[10px] uppercase tracking-[0.25em] text-slate-500">{label}</p>
      <p className="mt-1 text-sm font-semibold text-white">{value}</p>
    </div>
  )
}

function AssistantDetails({ message }) {
  if (message.role !== 'assistant') return null

  return (
    <div className="mt-4 space-y-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Metric label="Latency" value={`${message.benchmark?.duration_ms || 0} ms`} />
        <Metric label="Citations" value={message.citations?.length || 0} />
        <Metric label="Tools" value={message.tools?.length || 0} />
        <Metric label="Memory" value={message.benchmark?.memory_items || 0} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Task plan</h4>
          <p className="mb-3 text-sm font-medium text-white">{message.plan?.goal}</p>
          <ul className="space-y-2 text-sm text-slate-300">
            {(message.plan?.tasks || []).map((task, index) => (
              <li key={`${task}-${index}`} className="flex gap-2">
                <span className="mt-1 h-2 w-2 rounded-full bg-cyan-400" />
                <span>{task}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Execution timeline</h4>
          <div className="space-y-3">
            {(message.timeline || []).map((entry, index) => (
              <div key={`${entry.agent}-${index}`} className="timeline-node">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-semibold text-white">{entry.agent}</p>
                  <span
                    className={`status-pill ${
                      entry.status === 'completed'
                        ? 'status-online'
                        : entry.status === 'degraded'
                          ? 'status-warn'
                          : 'status-error'
                    }`}
                  >
                    {entry.status}
                  </span>
                </div>
                <p className="mt-1 text-xs text-slate-300">{entry.summary}</p>
                <p className="mt-1 text-[11px] text-slate-500">{entry.duration_ms} ms</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {message.citations?.length ? (
        <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Research citations</h4>
          <div className="space-y-3">
            {message.citations.map((citation, index) => (
              <div key={`${citation.document_id}-${index}`} className="rounded-xl border border-white/6 bg-slate-950/70 p-3">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <p className="text-sm font-semibold text-white">{citation.filename}</p>
                  <span className="text-xs text-slate-500">Page {citation.page || '?'}</span>
                </div>
                <p className="text-sm text-slate-300">{citation.snippet}</p>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {message.tools?.length ? (
        <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Tool execution</h4>
          <div className="space-y-3">
            {message.tools.map((tool, index) => (
              <div key={`${tool.name}-${index}`} className="rounded-xl border border-white/6 bg-slate-950/70 p-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-semibold text-white">{tool.name}</p>
                  <span className={`status-pill ${tool.status === 'success' ? 'status-online' : 'status-error'}`}>
                    {tool.status}
                  </span>
                </div>
                <p className="mt-2 text-xs text-slate-500">Input: {tool.input}</p>
                <p className="mt-1 text-sm text-slate-300">Output: {tool.output}</p>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default function MessageList({ messages, sending }) {
  return (
    <div className="scroll-area flex-1 space-y-5 overflow-auto pr-2">
      {messages.length === 0 ? (
        <div className="hero-card">
          <div className="max-w-3xl">
            <span className="inline-flex rounded-full border border-cyan-400/30 bg-cyan-500/10 px-3 py-1 text-xs font-semibold tracking-[0.2em] text-cyan-300">
              AUTONOMOUS MULTI-AGENT TASK AUTOMATION
            </span>
            <h1 className="mt-5 text-4xl font-semibold tracking-tight text-white md:text-5xl">
              AgentFlow AI orchestrates local specialists, not just a single chat model.
            </h1>
            <p className="mt-4 max-w-2xl text-base leading-7 text-slate-300">
              Start with a complex task, upload a PDF, and watch Planner, Research, Memory, Tool, and Reviewer agents collaborate through an execution timeline.
            </p>
          </div>
        </div>
      ) : null}

      {messages.map((message) => (
        <article key={message.id} className={`message-card ${message.role === 'user' ? 'message-user' : 'message-assistant'}`}>
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400">
                {message.role === 'user' ? 'Mission request' : 'AgentFlow synthesis'}
              </p>
              <p className="mt-1 text-sm text-slate-500">{message.created_at}</p>
            </div>
            {message.model ? <span className="status-pill status-online">{message.model}</span> : null}
          </div>
          <div className="prose-block text-sm leading-7 whitespace-pre-wrap text-slate-100">{message.content}</div>
          <AssistantDetails message={message} />
        </article>
      ))}

      {sending ? (
        <div className="message-card message-assistant">
          <p className="text-sm font-medium text-white">Agents are collaborating…</p>
          <div className="mt-4 flex gap-2">
            {['Planner', 'Research', 'Memory', 'Tool', 'Reviewer'].map((agent) => (
              <div key={agent} className="rounded-full border border-white/10 bg-white/6 px-3 py-2 text-xs text-slate-300">
                {agent}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
