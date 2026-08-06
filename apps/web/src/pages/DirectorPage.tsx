import { useEffect, useState } from 'react'
import { useAppStore } from '../store/appStore'
import { getJob, fetchStyles } from '../api/client'
import { LogoIcon, SaveIcon, ExportIcon, ArrowLeftIcon, AssetIcon, StyleIcon, ParameterIcon } from '../components/icons'
import { GpuBadge } from '../components/GpuBadge'
import { StoryboardTimeline } from '../components/StoryboardTimeline'
import { ModelTurntable } from '../components/ModelTurntable'
import { ParameterPanel } from '../components/ParameterPanel'
import { AiAssistant } from '../components/AiAssistant'
import { TaskLog } from '../components/TaskLog'
import { StyleCards } from '../components/StyleCards'

const TABS = [
  { id: 'assets', label: 'Asset Library', icon: AssetIcon },
  { id: 'styles', label: 'Style Library', icon: StyleIcon },
  { id: 'params', label: 'Parameters', icon: ParameterIcon },
]

export function DirectorPage() {
  const { currentJob, setPage, updateJob, setStyles, styles } = useAppStore()
  const [activeTab, setActiveTab] = useState('params')

  useEffect(() => {
    if (!currentJob) return
    if (currentJob.status === 'completed' || currentJob.status === 'failed') return

    const id = setInterval(async () => {
      try {
        const updated = await getJob(currentJob.id)
        updateJob(updated)
        if (updated.status === 'completed') {
          setTimeout(() => setPage('result'), 1500)
        }
      } catch (err) {
        console.error('Polling failed', err)
      }
    }, 2000)

    return () => clearInterval(id)
  }, [currentJob, updateJob, setPage])

  useEffect(() => {
    if (styles.length === 0) {
      fetchStyles().then(setStyles)
    }
  }, [styles.length, setStyles])

  const baseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000'
  const modelUrl = currentJob?.result_model_path
    ? `${baseUrl}/files/${encodeURIComponent(currentJob.result_model_path)}`
    : null

  const statusLabel = currentJob?.status || 'pending'

  return (
    <div className="flex h-screen flex-col bg-[#e8e8e8]">
      <header className="flex items-center justify-between border-b border-neutral-300 px-6 py-4">
        <div className="flex items-center gap-3">
          <button type="button" onClick={() => setPage('landing')} className="rounded-lg p-2 text-neutral-600 hover:bg-white/60">
            <ArrowLeftIcon className="h-5 w-5" />
          </button>
          <div className="flex items-center gap-2">
            <LogoIcon className="h-5 w-5 text-neutral-800" />
            <span className="text-sm font-semibold text-neutral-800">Director Console</span>
          </div>
          <span className="text-neutral-300">/</span>
          <span className="text-sm text-neutral-600">Project Orion</span>
        </div>
        <div className="flex items-center gap-3">
          <button type="button" className="flex items-center gap-2 rounded-lg border border-neutral-300 bg-white/60 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-white">
            <SaveIcon className="h-4 w-4" />
            Save
          </button>
          <button type="button" className="flex items-center gap-2 rounded-lg border border-neutral-300 bg-white/60 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-white">
            <ExportIcon className="h-4 w-4" />
            Export
          </button>
          <GpuBadge />
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <aside className="flex w-56 flex-col border-r border-neutral-300 bg-[#e8e8e8] p-4">
          {TABS.map((tab) => {
            const Icon = tab.icon
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`
                  mb-2 flex items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium transition
                  ${activeTab === tab.id ? 'bg-neutral-800 text-white' : 'text-neutral-600 hover:bg-white/60'}
                `}
              >
                <Icon className="h-5 w-5" />
                {tab.label}
              </button>
            )
          })}

          <div className="mt-6 flex-1 overflow-y-auto">
            {activeTab === 'assets' && (
              <div className="space-y-2">
                <p className="text-xs text-neutral-500">No assets yet.</p>
              </div>
            )}
            {activeTab === 'styles' && <StyleCards />}
            {activeTab === 'params' && <ParameterPanel />}
          </div>
        </aside>

        <main className="flex flex-1 flex-col overflow-hidden p-4">
          <div className="mb-4">
            <StoryboardTimeline />
          </div>

          <div className="flex flex-1 gap-4 overflow-hidden">
            <div className="relative flex flex-1 flex-col overflow-hidden rounded-2xl border border-neutral-300 bg-white/60 p-4">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Preview</p>
                <span className="rounded-full bg-neutral-200 px-2 py-0.5 text-[10px] font-medium text-neutral-700 uppercase">
                  {statusLabel}
                </span>
              </div>
              <div className="flex-1 overflow-hidden">
                <ModelTurntable modelUrl={modelUrl} />
              </div>
            </div>

            <aside className="flex w-80 flex-col gap-4 overflow-y-auto">
              <AiAssistant />
              <TaskLog />
            </aside>
          </div>
        </main>
      </div>
    </div>
  )
}
