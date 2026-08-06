import { useAppStore } from '../store/appStore'
import { ArrowLeftIcon, MinimizeIcon, CloseIcon } from '../components/icons'
import { GpuBadge } from '../components/GpuBadge'
import { ModelTurntable } from '../components/ModelTurntable'
import { ViewModeToggle } from '../components/ViewModeToggle'
import { PrintReport } from '../components/PrintReport'

export function ResultPage() {
  const { currentJob, setPage } = useAppStore()

  const baseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000'
  const modelUrl = currentJob?.result_model_path
    ? `${baseUrl}/files/${encodeURIComponent(currentJob.result_model_path)}`
    : null

  return (
    <div className="flex h-screen flex-col bg-[#e8e8e8]">
      <header className="flex items-center justify-between border-b border-neutral-300 px-6 py-4">
        <div className="flex items-center gap-3">
          <button type="button" onClick={() => setPage('landing')} className="rounded-lg p-2 text-neutral-600 hover:bg-white/60">
            <ArrowLeftIcon className="h-5 w-5" />
          </button>
          <span className="text-sm font-semibold text-neutral-800">Astronaut Explorer</span>
          <GpuBadge />
        </div>
        <div className="flex items-center gap-2">
          <button type="button" className="rounded-lg p-2 text-neutral-600 hover:bg-white/60">
            <MinimizeIcon className="h-5 w-5" />
          </button>
          <button type="button" onClick={() => setPage('landing')} className="rounded-lg p-2 text-neutral-600 hover:bg-white/60">
            <CloseIcon className="h-5 w-5" />
          </button>
        </div>
      </header>

      <main className="flex flex-1 gap-6 overflow-hidden p-6">
        <div className="relative flex flex-1 flex-col rounded-2xl border border-neutral-300 bg-white/60 p-4">
          <div className="flex-1 overflow-hidden">
            <ModelTurntable modelUrl={modelUrl} />
          </div>
          <div className="mt-4 flex items-center justify-center">
            <ViewModeToggle />
          </div>
        </div>

        <aside className="w-96 overflow-y-auto">
          <PrintReport />
          <button
            type="button"
            onClick={() => setPage('director')}
            className="mt-4 w-full text-center text-sm text-neutral-500 underline underline-offset-4 hover:text-neutral-800"
          >
            Edit Again
          </button>
        </aside>
      </main>
    </div>
  )
}
