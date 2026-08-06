import { useAppStore, type ViewMode3D } from '../store/appStore'

const MODES: { id: ViewMode3D; label: string }[] = [
  { id: 'solid', label: 'Solid' },
  { id: 'wireframe', label: 'Wireframe' },
  { id: 'texture', label: 'Texture' },
  { id: 'printbed', label: 'Print Bed' },
]

export function ViewModeToggle() {
  const { previewMode, setPreviewMode } = useAppStore()

  return (
    <div className="flex items-center justify-center gap-2">
      {MODES.map((mode) => (
        <button
          key={mode.id}
          type="button"
          onClick={() => setPreviewMode(mode.id)}
          className={`
            flex h-10 w-10 items-center justify-center rounded-lg border transition
            ${previewMode === mode.id
              ? 'border-neutral-800 bg-neutral-800 text-white'
              : 'border-neutral-300 bg-white text-neutral-600 hover:border-neutral-500'}
          `}
          title={mode.label}
        >
          <ModeIcon mode={mode.id} active={previewMode === mode.id} />
        </button>
      ))}
    </div>
  )
}

function ModeIcon({ mode, active }: { mode: ViewMode3D; active: boolean }) {
  const color = active ? 'currentColor' : '#525252'
  if (mode === 'solid') {
    return (
      <svg viewBox="0 0 24 24" fill={color} stroke="currentColor" strokeWidth="1.5" className="h-5 w-5">
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
      </svg>
    )
  }
  if (mode === 'wireframe') {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5">
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
        <path d="M3.27 6.96 12 12l8.73-5.05" />
        <path d="M12 22.08V12" />
      </svg>
    )
  }
  if (mode === 'texture') {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5">
        <circle cx="12" cy="12" r="10" />
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v4" />
        <path d="M12 18v4" />
        <path d="M2 12h4" />
        <path d="M18 12h4" />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5">
      <path d="M3 15h18" />
      <path d="M3 19h18" />
      <path d="M8 15v-4h8v4" />
    </svg>
  )
}
