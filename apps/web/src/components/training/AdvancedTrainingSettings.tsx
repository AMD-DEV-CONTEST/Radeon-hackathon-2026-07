import { ChevronDown, ChevronRight } from 'lucide-react'
import { FormField, NumberIn } from './shared'
import type { AlgoOption, QualiaInstance } from './types'

export function AdvancedTrainingSettings({
  open,
  onToggle,
  algorithms,
  algo,
  onAlgoChange,
  trainBackend,
  epochs,
  setEpochs,
  batchSize,
  setBatchSize,
  lr,
  setLr,
  hidden,
  setHidden,
  qInstance,
  setQInstance,
  qHours,
  setQHours,
  qBatch,
  setQBatch,
  qInstances,
  hfDatasetId,
  setHfDatasetId,
  qCameraKeys,
  setQCameraKeys,
  qModelId,
  setQModelId,
}: {
  open: boolean
  onToggle: () => void
  algorithms: AlgoOption[]
  algo: string
  onAlgoChange: (id: string) => void
  trainBackend: 'local' | 'qualia'
  epochs: number
  setEpochs: (n: number) => void
  batchSize: number
  setBatchSize: (n: number) => void
  lr: number
  setLr: (n: number) => void
  hidden: number
  setHidden: (n: number) => void
  qInstance: string
  setQInstance: (s: string) => void
  qHours: number
  setQHours: (n: number) => void
  qBatch: number
  setQBatch: (n: number) => void
  qInstances: QualiaInstance[]
  hfDatasetId: string
  setHfDatasetId: (s: string) => void
  qCameraKeys: string
  setQCameraKeys: (s: string) => void
  qModelId: string
  setQModelId: (s: string) => void
}) {
  return (
    <div className="rounded-lg border border-dashed border-muted-foreground/30">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground hover:text-foreground"
      >
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        专家模式 · 高级参数
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-3 border-t border-border/50 pt-3">
          <FormField label="Algorithm">
            <select
              value={algo}
              onChange={(e) => onAlgoChange(e.target.value)}
              className="w-full px-2 py-1.5 rounded border bg-background text-xs"
            >
              {algorithms.map((a) => (
                <option key={a.id} value={a.id} disabled={a.available === false}>
                  {a.name} ({a.backend})
                </option>
              ))}
            </select>
          </FormField>
          {trainBackend === 'qualia' && (
            <>
              <FormField label="GPU instance">
                <select
                  value={qInstance}
                  onChange={(e) => setQInstance(e.target.value)}
                  className="w-full px-2 py-1.5 rounded border bg-background font-mono text-xs"
                >
                  {qInstances.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.gpu_description}
                    </option>
                  ))}
                </select>
              </FormField>
              <div className="grid grid-cols-2 gap-2">
                <FormField label="Hours">
                  <NumberIn value={qHours} setValue={setQHours} min={0.1} max={48} step={0.5} />
                </FormField>
                <FormField label="Batch">
                  <NumberIn value={qBatch} setValue={setQBatch} min={1} max={512} />
                </FormField>
              </div>
              <FormField label="HF dataset id">
                <input
                  value={hfDatasetId}
                  onChange={(e) => setHfDatasetId(e.target.value)}
                  className="w-full px-2 py-1.5 rounded border bg-background font-mono text-xs"
                  placeholder="留空自动"
                />
              </FormField>
              <FormField label="Camera keys">
                <input
                  value={qCameraKeys}
                  onChange={(e) => setQCameraKeys(e.target.value)}
                  className="w-full px-2 py-1.5 rounded border bg-background font-mono text-[11px]"
                  placeholder="留空自动"
                />
              </FormField>
              {qModelId && (
                <FormField label="Base model">
                  <input
                    value={qModelId}
                    onChange={(e) => setQModelId(e.target.value)}
                    className="w-full px-2 py-1.5 rounded border bg-background font-mono text-[10px]"
                  />
                </FormField>
              )}
            </>
          )}
          <div className="grid grid-cols-2 gap-2">
            <FormField label="Epochs">
              <NumberIn value={epochs} setValue={setEpochs} min={1} max={1000} />
            </FormField>
            <FormField label="Batch">
              <NumberIn
                value={trainBackend === 'qualia' ? qBatch : batchSize}
                setValue={trainBackend === 'qualia' ? setQBatch : setBatchSize}
                min={1}
                max={1024}
              />
            </FormField>
            <FormField label="LR">
              <NumberIn value={lr} setValue={setLr} min={1e-5} max={1} step={1e-4} />
            </FormField>
            <FormField label="Hidden">
              <NumberIn value={hidden} setValue={setHidden} min={8} max={1024} />
            </FormField>
          </div>
        </div>
      )}
    </div>
  )
}
