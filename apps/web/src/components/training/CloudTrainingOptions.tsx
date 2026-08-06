import { FormField } from './shared'
import type { QualiaInstance } from './types'

const HOUR_PRESETS = [0.5, 1, 2, 4, 8]

export function CloudTrainingOptions({
  qHours,
  setQHours,
  qInstance,
  setQInstance,
  qInstances,
  costLabel,
  qualiaLocked,
}: {
  qHours: number
  setQHours: (n: number) => void
  qInstance: string
  setQInstance: (s: string) => void
  qInstances: QualiaInstance[]
  costLabel?: string | null
  qualiaLocked: boolean
}) {
  if (qualiaLocked) return null

  return (
    <div className="rounded-lg border border-sky-500/25 bg-sky-500/5 p-4 space-y-4">
      <p className="text-sm font-medium text-sky-100">设置时长和 GPU</p>

      <FormField label="租用时长（小时）">
        <div className="flex flex-wrap gap-2">
          {HOUR_PRESETS.map((h) => (
            <button
              key={h}
              type="button"
              onClick={() => setQHours(h)}
              className={`px-3 py-1.5 rounded-md border text-sm transition-colors ${
                qHours === h
                  ? 'border-primary bg-primary/15 text-primary'
                  : 'border-border hover:bg-muted/50'
              }`}
            >
              {h} 小时
            </button>
          ))}
        </div>
        <input
          type="number"
          min={0.25}
          step={0.25}
          value={qHours}
          onChange={(e) => setQHours(Math.max(0.25, Number(e.target.value) || 1))}
          className="mt-2 w-full max-w-[140px] px-2 py-1.5 rounded border bg-background text-sm"
        />
      </FormField>

      <FormField label="GPU 机型">
        {qInstances.length === 0 ? (
          <p className="text-xs text-muted-foreground">加载机型列表中…</p>
        ) : (
          <select
            value={qInstance}
            onChange={(e) => setQInstance(e.target.value)}
            className="w-full px-2 py-2 rounded border bg-background text-sm"
          >
            {qInstances.map((inst) => (
              <option key={inst.id} value={inst.id}>
                {inst.gpu_description} · {inst.credits_per_hour} credits/小时
              </option>
            ))}
          </select>
        )}
      </FormField>

      {costLabel && (
        <p className="text-sm text-sky-300">
          预计费用：{costLabel}
        </p>
      )}
    </div>
  )
}
