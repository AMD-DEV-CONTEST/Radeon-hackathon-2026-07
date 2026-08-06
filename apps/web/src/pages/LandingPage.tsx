import { useEffect, useState } from 'react'
import { useAppStore } from '../store/appStore'
import { fetchStyles, uploadImage, agentPlan, agentExecute } from '../api/client'
import { UploadZone } from '../components/UploadZone'
import { StyleCards } from '../components/StyleCards'
import { GpuBadge } from '../components/GpuBadge'
import { LogoIcon, ArrowRightIcon, HelpIcon, UserIcon } from '../components/icons'

const SAMPLE_PROJECTS = [
  { id: '1', name: 'Sneaker', time: '2h ago' },
  { id: '2', name: 'Robot Toy', time: '5h ago' },
  { id: '3', name: 'Sports Car', time: '1d ago' },
  { id: '4', name: 'Ancient Coin', time: '2d ago' },
  { id: '5', name: 'Lounge Chair', time: '3d ago' },
  { id: '6', name: 'Low Poly Deer', time: '4d ago' },
]

export function LandingPage() {
  const {
    setStyles,
    selectedStyleId,
    setPlan,
    setJob,
    setPage,
    addProject,
  } = useAppStore()

  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [prompt, setPrompt] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetchStyles().then((styles) => {
      setStyles(styles)
    })
  }, [setStyles])

  const handleFileSelect = (f: File) => {
    setFile(f)
    setPreviewUrl(URL.createObjectURL(f))
  }

  const startGenerate = async () => {
    if (!file) return
    setLoading(true)

    try {
      const upload = await uploadImage(file)
      const styleName = useAppStore.getState().styles.find((s) => s.id === selectedStyleId)?.name || 'Realistic 3D'
      const userInput = prompt.trim() || styleName

      const plan = await agentPlan(userInput, upload.path)
      setPlan(plan)

      const exec = await agentExecute(plan, upload.path)
      setJob({
        id: exec.job_id,
        status: 'pending',
        input_image_path: upload.path,
        style: plan.style_id,
        prompt: plan.user_prompt,
        output_mode: plan.output_mode,
        result_model_path: null,
        result_preview_path: null,
        multiview_image_paths: null,
        print_report: null,
        error_message: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      })

      addProject({
        id: exec.job_id,
        name: userInput.slice(0, 30),
        thumbnailUrl: previewUrl || undefined,
        jobId: exec.job_id,
        updatedAt: new Date().toISOString(),
      })

      setPage('director')
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Generation failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-[#e8e8e8]">
      <header className="flex items-center justify-between px-8 py-5">
        <div className="flex items-center gap-2">
          <LogoIcon className="h-6 w-6 text-neutral-800" />
          <span className="text-base font-semibold text-neutral-800">3DGenerateFlow</span>
        </div>
        <div className="flex items-center gap-3">
          <GpuBadge />
          <button type="button" className="rounded-lg border border-neutral-300 bg-white/60 p-2 text-neutral-600 hover:bg-white">
            <HelpIcon className="h-5 w-5" />
          </button>
          <button type="button" className="rounded-lg border border-neutral-300 bg-white/60 p-2 text-neutral-600 hover:bg-white">
            <UserIcon className="h-5 w-5" />
          </button>
        </div>
      </header>

      <main className="flex flex-1 flex-col items-center justify-center px-6 pb-8">
        <div className="w-full max-w-3xl">
          <UploadZone onFileSelect={handleFileSelect} previewUrl={previewUrl} />

          <div className="mt-8">
            <p className="mb-3 text-center text-[10px] font-semibold uppercase tracking-widest text-neutral-500">Choose Style</p>
            <StyleCards compact />
          </div>

          <div className="mt-5">
            <input
              type="text"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe your idea (optional)…"
              className="w-full rounded-xl border border-neutral-300 bg-white/60 px-4 py-3 text-sm text-neutral-800 placeholder:text-neutral-400 focus:border-neutral-500 focus:outline-none"
            />
          </div>

          <button
            type="button"
            onClick={startGenerate}
            disabled={!file || loading}
            className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl bg-neutral-900 py-3.5 text-sm font-semibold text-white transition hover:bg-neutral-800 disabled:opacity-50"
          >
            {loading ? 'Starting…' : 'Start Generate'}
            <ArrowRightIcon className="h-4 w-4" />
          </button>
        </div>
      </main>

      <section className="px-8 pb-8">
        <p className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-neutral-500">Recent Projects</p>
        <div className="scrollbar-hide flex gap-3 overflow-x-auto">
          {SAMPLE_PROJECTS.map((p) => (
            <div
              key={p.id}
              className="flex min-w-[180px] items-center gap-3 rounded-xl border border-neutral-300 bg-white/60 p-3"
            >
              <div className="h-12 w-12 rounded-lg bg-neutral-200" />
              <div className="flex-1">
                <p className="text-sm font-medium text-neutral-800">{p.name}</p>
                <p className="text-[10px] text-neutral-500">{p.time}</p>
              </div>
              <button type="button" className="text-neutral-400 hover:text-neutral-700">
                <span className="sr-only">More</span>
                <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="1" />
                  <circle cx="19" cy="12" r="1" />
                  <circle cx="5" cy="12" r="1" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
