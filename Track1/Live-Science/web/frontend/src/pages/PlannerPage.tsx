import { useState } from 'react'
import { api } from '../api'
import type { EngineName } from '../types'

interface Props {
  onSubmitted: (jobId: string) => void
}

const ENGINES: { id: EngineName; label: string; tag: string; hint: string; icon: string }[] = [
  {
    id: 'auto',
    label: 'Auto',
    tag: 'Route from final video',
    hint: 'Phase 1 decides after rendering: program video or model video (FLUX + LTX)',
    icon: '◎',
  },
  {
    id: 'deterministic',
    label: 'Deterministic',
    tag: 'Program video',
    hint: 'Phase 1 generates a subtitled programmatic teaching video',
    icon: '◈',
  },
  {
    id: 'generative',
    label: 'Generative',
    tag: 'Model video',
    hint: 'Local FLUX keyframes + LTX continuous video (requires ComfyUI)',
    icon: '✦',
  },
]

function StepTitle({ n, title, hint }: { n: string; title: string; hint?: string }) {
  return (
    <div className="mb-4 flex items-center gap-3">
      <span className="font-mono text-sm font-bold text-radeon-400">{n}</span>
      <h2 className="whitespace-nowrap text-base font-bold text-fg">{title}</h2>
      {hint && <span className="whitespace-nowrap text-xs text-dim">{hint}</span>}
      <span className="energy-line h-px flex-1 opacity-30" />
    </div>
  )
}

export default function PlannerPage({ onSubmitted }: Props) {
  const [text, setText] = useState('')
  const [supplement, setSupplement] = useState('')
  const [engine, setEngine] = useState<EngineName>('auto')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!text.trim()) {
      setError('Please enter the document text to process')
      return
    }
    const requestText = supplement.trim()
      ? `${text.trim()}\n\nSupplement: ${supplement.trim()}`
      : text.trim()
    setSubmitting(true)
    setError(null)
    try {
      const job = await api.createJob({ text: requestText, engine })
      onSubmitted(job.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="animate-fade-up">
      {/* input content */}
      <div className="clip-angled border border-line bg-ink-900 p-6">
        <StepTitle n="01" title="Input" hint="Teaching document / concept / process description" />
        <label htmlFor="doc-text" className="sr-only">
          Teaching document text
        </label>
        <textarea
          id="doc-text"
          rows={7}
          placeholder="Paste a teaching document / concept / process to animate, e.g. How is an oxbow lake formed? …"
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="clip-angled-sm w-full resize-y border border-line bg-ink-950 px-4 py-3 text-sm text-fg outline-none transition-all placeholder:text-dim focus:border-radeon-500/70 focus:glow-red-sm"
        />
        <label htmlFor="doc-supplement" className="sr-only">
          Supplementary note
        </label>
        <textarea
          id="doc-supplement"
          rows={3}
          placeholder="Optional: supplementary note (target audience, the full process to emphasize, etc.)"
          value={supplement}
          onChange={(e) => setSupplement(e.target.value)}
          className="clip-angled-sm mt-3 w-full resize-y border border-line bg-ink-950 px-4 py-3 text-sm text-fg outline-none transition-all placeholder:text-dim focus:border-radeon-500/70"
        />
        {error && <p className="mt-3 text-sm text-danger">{error}</p>}
      </div>

      {/* engine selection */}
      <div className="clip-angled animate-fade-up mt-5 border border-line bg-ink-900 p-6">
        <StepTitle n="02" title="Rendering engine" hint="Auto lets Phase 1 pick program vs model route from the final render" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ENGINES.map((en) => {
            const isSel = engine === en.id
            return (
              <button
                key={en.id}
                onClick={() => setEngine(en.id)}
                aria-pressed={isSel}
                className={`clip-angled relative border p-4 text-left transition-all ${
                  isSel
                    ? 'border-radeon-500/70 bg-ink-850 glow-red'
                    : 'border-line bg-ink-950 hover:border-line-strong hover:bg-ink-850'
                }`}
              >
                {isSel && <span className="energy-line absolute inset-y-0 left-0 w-1" />}
                <div className="flex items-center gap-2">
                  <span className={`text-lg ${isSel ? 'text-radeon-400' : 'text-dim'}`}>
                    {en.icon}
                  </span>
                  <span className="text-sm font-bold text-fg">{en.label}</span>
                </div>
                <div className="mt-0.5 font-mono text-[10px] uppercase tracking-[0.14em] text-radeon-400/90">
                  {en.tag}
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-mut">{en.hint}</p>
              </button>
            )
          })}
        </div>

        <button
          onClick={submit}
          disabled={submitting}
          className="clip-angled btn-primary mt-5 w-full px-6 py-3.5 text-base tracking-wide transition-all hover:glow-red disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
        >
          {submitting ? 'Submitting…' : '⚡ Generate teaching video'}
        </button>
      </div>
    </section>
  )
}
