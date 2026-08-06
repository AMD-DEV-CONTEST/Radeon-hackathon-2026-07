import { useAppStore } from '../store/appStore'
import { BoxIcon, DownloadIcon, FileIcon } from './icons'

export function PrintReport() {
  const job = useAppStore((s) => s.currentJob)
  const report = job?.print_report

  if (!report) {
    return (
      <div className="rounded-2xl border border-neutral-300 bg-white/60 p-5">
        <h3 className="mb-3 text-sm font-semibold text-neutral-800">Print Report</h3>
        <p className="text-xs text-neutral-500">Generate a model to see print metrics.</p>
      </div>
    )
  }

  const rows = [
    { icon: BoxIcon, label: 'Volume', value: `${report.volume_cm3} cm³` },
    { icon: BoxIcon, label: 'Dimensions', value: Array.isArray(report.dimensions_mm) ? `${report.dimensions_mm[0]} × ${report.dimensions_mm[1]} × ${report.dimensions_mm[2]} mm` : '-' },
    { icon: BoxIcon, label: 'Wall Thickness', value: `${report.wall_thickness_mm || '-'} mm` },
    { icon: BoxIcon, label: 'Watertight', value: report.is_watertight ? 'Verified' : 'Not watertight' },
  ]

  const baseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000'
  const modelUrl = job.result_model_path
    ? `${baseUrl}/files/${encodeURIComponent(job.result_model_path)}`
    : null
  const stlUrl = job.output_mode === 'relief_2d5'
    ? modelUrl?.replace('.glb', '.stl') || modelUrl
    : null

  return (
    <div className="rounded-2xl border border-neutral-300 bg-white/60 p-5">
      <h3 className="mb-4 text-sm font-semibold text-neutral-800">Print Report</h3>

      <div className="space-y-3">
        {rows.map((row) => {
          const Icon = row.icon
          return (
            <div key={row.label} className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Icon className="h-5 w-5 text-neutral-500" />
                <span className="text-sm text-neutral-600">{row.label}</span>
              </div>
              <span className="text-sm font-medium text-neutral-800">{row.value}</span>
            </div>
          )
        })}
      </div>

      <div className="mt-5 space-y-2">
        {modelUrl && (
          <a
            href={modelUrl}
            download
            className="flex items-center justify-center gap-2 rounded-xl bg-neutral-800 py-3 text-sm font-medium text-white transition hover:bg-neutral-700"
          >
            <DownloadIcon className="h-4 w-4" />
            Download {job.output_mode === 'relief_2d5' ? 'GLB' : 'GLB'}
          </a>
        )}
        {stlUrl && (
          <a
            href={stlUrl}
            download
            className="flex items-center justify-center gap-2 rounded-xl border border-neutral-300 bg-white py-3 text-sm font-medium text-neutral-700 transition hover:bg-neutral-50"
          >
            <DownloadIcon className="h-4 w-4" />
            Download STL
          </a>
        )}
        <button
          type="button"
          onClick={() => alert('PDF report generation is coming soon.')}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-neutral-300 bg-white py-3 text-sm font-medium text-neutral-700 transition hover:bg-neutral-50"
        >
          <FileIcon className="h-4 w-4" />
          Download Print Report (PDF)
        </button>
      </div>
    </div>
  )
}
