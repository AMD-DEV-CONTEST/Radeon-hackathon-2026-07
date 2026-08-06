import { useState } from 'react'

const suggestions = [
  'Plan a launch strategy using the uploaded PDF and produce next steps.',
  'Summarize the document and extract risks, milestones, and deliverables.',
  'Create a benchmark-ready hackathon demo script from the local knowledge base.',
]

export default function Composer({ onSubmit, disabled }) {
  const [value, setValue] = useState('')

  function submit(message) {
    const trimmed = message.trim()
    if (!trimmed || disabled) return
    onSubmit(trimmed)
    setValue('')
  }

  return (
    <div className="panel p-4">
      <div className="mb-3 flex flex-wrap gap-2">
        {suggestions.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            onClick={() => submit(suggestion)}
            className="rounded-full border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-300 transition hover:border-cyan-400/40 hover:bg-cyan-500/10 hover:text-white"
          >
            {suggestion}
          </button>
        ))}
      </div>
      <div className="rounded-3xl border border-white/10 bg-slate-950/80 p-3 shadow-2xl shadow-cyan-950/20">
        <textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          rows={4}
          placeholder="Describe the multi-step outcome you want AgentFlow AI to autonomously plan, research, execute, and review..."
          className="w-full resize-none bg-transparent px-2 py-2 text-sm leading-7 text-white outline-none placeholder:text-slate-500"
        />
        <div className="mt-3 flex items-center justify-between gap-3 border-t border-white/8 pt-3">
          <p className="text-xs text-slate-500">Offline-first • Ollama only • No API keys</p>
          <button
            type="button"
            disabled={disabled}
            onClick={() => submit(value)}
            className="rounded-2xl bg-gradient-to-r from-cyan-500 to-fuchsia-500 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Launch workflow
          </button>
        </div>
      </div>
    </div>
  )
}
