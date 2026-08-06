function StatCard({ label, value, helper }) {
  return (
    <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.25em] text-slate-500">{label}</p>
      <p className="mt-2 text-xl font-semibold text-white">{value}</p>
      {helper ? <p className="mt-1 text-xs text-slate-400">{helper}</p> : null}
    </div>
  )
}

export default function StatusPanel({ health, systemInfo, benchmarks, latestResponse }) {
  const totals = benchmarks?.totals || {}
  const ollama = systemInfo?.ollama || {}
  const selectedModel = latestResponse?.agent_status?.selected_model || health?.selected_model || ollama?.selected_model

  return (
    <aside className="panel flex h-full flex-col gap-5 p-5">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Control tower</h2>
        <p className="mt-2 text-sm text-slate-400">Live status for agents, hardware, benchmarks, and local model routing.</p>
      </div>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">LLM status</h3>
          <span className={`status-pill ${health?.ollama_running ? 'status-online' : 'status-error'}`}>
            {health?.ollama_running ? 'Online' : 'Offline'}
          </span>
        </div>
        <div className="space-y-3 rounded-2xl border border-white/8 bg-white/4 p-4">
          <div>
            <p className="text-xs text-slate-500">Selected model</p>
            <p className="mt-1 text-sm font-semibold text-white">{selectedModel || 'No model selected yet'}</p>
          </div>
          <div>
            <p className="text-xs text-slate-500">Model pool</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {(health?.available_models || []).length ? (
                health.available_models.map((model) => (
                  <span key={model} className="rounded-full border border-white/10 bg-slate-950/60 px-3 py-1 text-xs text-slate-300">
                    {model}
                  </span>
                ))
              ) : (
                <span className="text-xs text-slate-500">Install qwen2.5:7b, llama3.2:3b, or mistral:7b in Ollama.</span>
              )}
            </div>
          </div>
          <p className="text-xs leading-6 text-slate-400">{health?.message}</p>
        </div>
      </section>

      <section>
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Agent status</h3>
        <div className="space-y-3 rounded-2xl border border-white/8 bg-white/4 p-4">
          {[
            ['Planner Agent', 'Creates the autonomous execution plan.'],
            ['Research Agent', 'Queries local ChromaDB knowledge.'],
            ['Memory Agent', 'Recalls SQLite conversation memory.'],
            ['Tool Agent', 'Runs safe local tools only.'],
            ['Reviewer Agent', 'Polishes the final response.'],
          ].map(([name, description]) => (
            <div key={name} className="flex items-start justify-between gap-3 rounded-xl border border-white/6 bg-slate-950/70 p-3">
              <div>
                <p className="text-sm font-semibold text-white">{name}</p>
                <p className="mt-1 text-xs text-slate-400">{description}</p>
              </div>
              <span className="status-pill status-online">Ready</span>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Benchmark dashboard</h3>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-1">
          <StatCard label="Workflow runs" value={totals.runs || 0} helper="Total orchestrated executions" />
          <StatCard label="Average latency" value={`${totals.avg_duration_ms || 0} ms`} helper="Across stored benchmark runs" />
          <StatCard label="Success rate" value={`${totals.success_rate || 0}%`} helper="Completed agent pipelines" />
          <StatCard label="Docs indexed" value={totals.documents || 0} helper="Local files in ChromaDB" />
        </div>
      </section>

      <section>
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">GPU / CPU</h3>
        <div className="space-y-3 rounded-2xl border border-white/8 bg-white/4 p-4">
          <div>
            <p className="text-xs text-slate-500">CPU</p>
            <p className="mt-1 text-sm font-semibold text-white">
              {systemInfo?.cpu?.name || 'Unknown CPU'} • {systemInfo?.cpu?.logical_cores || '?'} cores
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-500">Memory</p>
            <p className="mt-1 text-sm font-semibold text-white">
              {systemInfo?.memory?.available_gb ?? '?'} GB free / {systemInfo?.memory?.total_gb ?? '?'} GB total
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-500">GPU</p>
            <div className="mt-2 space-y-2 text-sm text-slate-300">
              {(systemInfo?.gpu || []).map((gpu, index) => (
                <div key={`${gpu.name}-${index}`} className="rounded-xl border border-white/6 bg-slate-950/70 p-3">
                  <p className="font-medium text-white">{gpu.name}</p>
                  {gpu.memory_total ? <p className="mt-1 text-xs text-slate-400">Memory: {gpu.memory_total}</p> : null}
                  {gpu.details ? <p className="mt-1 text-xs text-slate-500">{gpu.details}</p> : null}
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
    </aside>
  )
}
