import { useAppStore } from '../store/appStore'
import { UploadIcon, StyleIcon, GridIcon, BoxIcon, CheckIcon, ExportIcon } from './icons'

const STEPS = [
  { id: 'upload', label: 'Upload', icon: UploadIcon },
  { id: 'style', label: 'Style', icon: StyleIcon },
  { id: 'multiview', label: 'Multiview', icon: GridIcon },
  { id: '3d', label: '3D', icon: BoxIcon },
  { id: 'printcheck', label: 'Print Check', icon: CheckIcon },
  { id: 'export', label: 'Export', icon: ExportIcon },
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

export function StoryboardTimeline() {
  const status = useAppStore((s) => s.currentJob?.status || 'pending')
  const activeIndex = STATUS_ORDER[status] ?? 0
  const failed = status === 'failed'

  return (
    <div className="flex items-center gap-2 rounded-2xl border border-neutral-300 bg-white/60 p-4">
      {STEPS.map((step, idx) => {
        const Icon = step.icon
        const isCurrent = idx === activeIndex && !failed
        const isDone = idx < activeIndex || (status === 'completed' && idx < 5)
        return (
          <div key={step.id} className="flex items-center gap-2">
            <div
              className={`
                flex flex-col items-center gap-1.5 rounded-xl px-4 py-3 transition
                ${isCurrent
                  ? 'bg-neutral-800 text-white shadow-sm'
                  : isDone
                    ? 'bg-neutral-200 text-neutral-700'
                    : 'bg-neutral-100 text-neutral-400'}
              `}
            >
              <Icon className="h-5 w-5" />
              <span className="text-[10px] font-medium uppercase tracking-wide">{step.label}</span>
            </div>
            {idx < STEPS.length - 1 && (
              <div className={`h-px w-5 ${isDone ? 'bg-neutral-400' : 'bg-neutral-300'}`} />
            )}
          </div>
        )
      })}
    </div>
  )
}
