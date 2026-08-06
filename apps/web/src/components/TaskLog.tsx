import { useAppStore } from '../store/appStore'
import { ClockIcon, CheckIcon, BoxIcon, GridIcon, StyleIcon, UploadIcon, ExportIcon } from './icons'

const LOG_STEPS = [
  { key: 'preprocessing', label: 'Upload received', icon: UploadIcon },
  { key: 'generating_multiview', label: 'Multiview generated', icon: GridIcon },
  { key: 'generating_3d', label: '3D mesh generated', icon: BoxIcon },
  { key: 'postprocessing', label: 'Auto orientation applied', icon: StyleIcon },
  { key: 'completed', label: 'Export ready', icon: ExportIcon },
]

const STATUS_ORDER: Record<string, number> = {
  pending: 0,
  preprocessing: 1,
  generating_multiview: 2,
  generating_3d: 3,
  postprocessing: 4,
  completed: 5,
  failed: -1,
}

export function TaskLog() {
  const status = useAppStore((s) => s.currentJob?.status || 'pending')
  const updatedAt = useAppStore((s) => s.currentJob?.updated_at)
  const currentIndex = STATUS_ORDER[status] ?? 0

  return (
    <div className="rounded-2xl border border-neutral-300 bg-white/60 p-4">
      <div className="mb-3 flex items-center gap-2">
        <ClockIcon className="h-4 w-4 text-neutral-600" />
        <h3 className="text-sm font-semibold text-neutral-800">Task Log</h3>
      </div>

      <div className="space-y-3">
        {LOG_STEPS.map((step, idx) => {
          const Icon = step.icon
          const done = idx < currentIndex || status === 'completed'
          const current = idx === currentIndex && status !== 'completed'
          return (
            <div key={step.key} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div
                  className={`flex h-6 w-6 items-center justify-center rounded-full ${done ? 'bg-emerald-100 text-emerald-700' : current ? 'bg-neutral-800 text-white' : 'bg-neutral-200 text-neutral-400'}`}
                >
                  {done ? <CheckIcon className="h-3 w-3" /> : <Icon className="h-3 w-3" />}
                </div>
                <span className={`text-xs ${done ? 'text-neutral-600' : current ? 'text-neutral-800 font-medium' : 'text-neutral-400'}`}>
                  {step.label}
                </span>
              </div>
              {done && updatedAt && (
                <span className="text-[10px] text-neutral-400">
                  {new Date(updatedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
