import { useEffect, useState } from 'react'
import { getGpuStatus, type GpuStatus } from '../api/client'
import { GridIcon } from './icons'

export function GpuBadge() {
  const [status, setStatus] = useState<GpuStatus | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getGpuStatus()
      .then(setStatus)
      .catch(() => setStatus(null))
      .finally(() => setLoading(false))

    const id = setInterval(() => {
      getGpuStatus().then(setStatus).catch(() => setStatus(null))
    }, 10000)
    return () => clearInterval(id)
  }, [])

  if (loading) {
    return (
      <span className="inline-flex items-center gap-2 rounded-lg border border-neutral-300 bg-white/60 px-3 py-1.5 text-xs font-medium text-neutral-500">
        <GridIcon className="h-4 w-4" />
        GPU: checking…
      </span>
    )
  }

  if (!status) {
    return (
      <span className="inline-flex items-center gap-2 rounded-lg border border-neutral-300 bg-white/60 px-3 py-1.5 text-xs font-medium text-red-600">
        <GridIcon className="h-4 w-4" />
        GPU: unavailable
      </span>
    )
  }

  const label = status.rocm_available
    ? `GPU: ${status.gpu_name || 'AMD ROCm'}`
    : status.torch_cuda_available
      ? `GPU: ${status.gpu_name || 'CUDA'}`
      : 'GPU: CPU'

  return (
    <span
      className="inline-flex items-center gap-2 rounded-lg border border-neutral-300 bg-white/60 px-3 py-1.5 text-xs font-medium text-neutral-700"
      title={`${status.gpu_name || 'Unknown'} · ${status.gpu_memory_mb || 0} MB · HIP ${status.hip_version || '?'}`}
    >
      <GridIcon className="h-4 w-4" />
      {label}
      <span className={`h-2 w-2 rounded-full ${status.rocm_available ? 'bg-emerald-500' : 'bg-amber-500'}`} />
    </span>
  )
}
