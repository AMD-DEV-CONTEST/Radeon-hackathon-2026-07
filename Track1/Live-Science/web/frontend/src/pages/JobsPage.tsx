import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Job } from '../types'
import JobCard from '../components/JobCard'

interface Props {
  trackedJobId: string | null
  active: boolean
  onTrackedDone: () => void
}

const PAGE_SIZE = 20
const POLL_MS = 3000

export default function JobsPage({ trackedJobId, active, onTrackedDone }: Props) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const trackedRef = useRef<HTMLDivElement | null>(null)
  const lastTrackedStatus = useRef<string | null>(null)

  const jobsRef = useRef<Job[]>([])
  jobsRef.current = jobs

  /** Fetch the job list. quiet = background poll (keeps the current list on error). */
  const loadList = useCallback(async (quiet = false) => {
    if (!quiet) setRefreshing(true)
    try {
      const r = await api.listJobs(PAGE_SIZE, 0)
      setJobs(r.jobs)
      setTotal(r.total)
      setError(null)
      setLoaded(true)
    } catch (e) {
      if (!quiet) setError(e instanceof Error ? e.message : String(e))
      // quiet failures keep the last good list instead of wiping the UI
    } finally {
      if (!quiet) setRefreshing(false)
    }
  }, [])

  /** Poll a single tracked job and merge it into the list (cheap). */
  const loadTracked = useCallback(async () => {
    if (!trackedJobId) return
    try {
      const job = await api.getJob(trackedJobId)
      setJobs((prev) => {
        const i = prev.findIndex((j) => j.id === job.id)
        if (i >= 0) {
          const next = [...prev]
          next[i] = job
          return next
        }
        return [job, ...prev]
      })
      setError(null)
      setLoaded(true)
      if (job.status === 'completed' || job.status === 'failed') onTrackedDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [trackedJobId, onTrackedDone])

  // Activation + polling loop. Only runs while this tab is active.
  useEffect(() => {
    if (!active) return
    if (!loaded) void loadList(false)
    const timer = window.setInterval(async () => {
      if (trackedJobId) {
        await loadTracked()
        return
      }
      const hasActive = jobsRef.current.some(
        (j) => j.status === 'pending' || j.status === 'running',
      )
      if (hasActive) await loadList(true)
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [active, trackedJobId, loaded, loadList, loadTracked])

  // Scroll to the tracked job only when its status transitions (not on every poll).
  useEffect(() => {
    if (!trackedJobId) return
    const status = jobs.find((j) => j.id === trackedJobId)?.status ?? null
    if (status && status !== lastTrackedStatus.current) {
      trackedRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
      lastTrackedStatus.current = status
    }
  }, [jobs, trackedJobId])

  const loadMore = useCallback(async () => {
    try {
      const r = await api.listJobs(PAGE_SIZE, jobs.length)
      setJobs((prev) => {
        const seen = new Set(prev.map((j) => j.id))
        return [...prev, ...r.jobs.filter((j) => !seen.has(j.id))]
      })
      setTotal(r.total)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [jobs.length])

  const activeCount = jobs.filter((j) => j.status === 'pending' || j.status === 'running').length
  const doneCount = jobs.filter((j) => j.status === 'completed').length

  return (
    <section className="animate-fade-up">
      <div className="clip-angled border border-line bg-ink-900 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-3 text-base font-bold text-fg">
              <span className="clip-angled-sm flex h-7 w-7 items-center justify-center bg-gradient-to-br from-radeon-500 to-ember-600 text-sm text-white glow-red-sm">
                ⚡
              </span>
              Jobs
            </h2>
            <p className="mt-1 font-mono text-[11px] uppercase tracking-[0.14em] text-dim">
              {total} total ·{' '}
              <span className={activeCount ? 'text-radeon-400' : 'text-dim'}>{activeCount} rendering</span>{' '}
              ·{' '}
              <span className={doneCount ? 'text-ok' : 'text-dim'}>{doneCount} completed</span>
            </p>
          </div>
          <button
            onClick={() => void loadList(false)}
            disabled={refreshing}
            className="clip-angled-sm border border-line bg-ink-850 px-4 py-2 text-sm text-mut transition-all hover:border-radeon-500/60 hover:text-fg disabled:opacity-50"
          >
            {refreshing ? 'Refreshing…' : '↻ Refresh'}
          </button>
        </div>

        {error && <p className="mt-4 text-sm text-danger">⚠ {error} (list may be stale)</p>}

        {!loaded && !error && (
          <div className="mt-4 flex flex-col gap-3" aria-busy="true" aria-label="Loading job list">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="clip-angled border border-line bg-ink-950 p-5"
                aria-hidden="true"
              >
                <div className="h-3 w-32 animate-pulse rounded bg-ink-800" />
                <div className="mt-3 h-3 w-2/3 animate-pulse rounded bg-ink-800" />
                <div className="mt-4 h-3 w-1/2 animate-pulse rounded bg-ink-800" />
              </div>
            ))}
          </div>
        )}

        {loaded && jobs.length === 0 && (
          <p className="mt-6 text-center text-sm text-dim">
            No jobs yet — go to the Create tab to submit your first video.
          </p>
        )}

        <div className="mt-4 flex flex-col gap-3">
          {jobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              highlighted={job.id === trackedJobId}
              ref={job.id === trackedJobId ? trackedRef : undefined}
            />
          ))}
        </div>

        {loaded && jobs.length < total && (
          <button
            onClick={() => void loadMore()}
            className="clip-angled-sm mx-auto mt-5 block border border-line bg-ink-850 px-6 py-2 text-sm text-mut transition-all hover:border-radeon-500/60 hover:text-fg"
          >
            Load more (showing {jobs.length} / {total})
          </button>
        )}
      </div>
    </section>
  )
}
