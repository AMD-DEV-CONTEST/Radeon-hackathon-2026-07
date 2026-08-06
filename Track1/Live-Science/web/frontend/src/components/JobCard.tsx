import { forwardRef } from 'react'
import { formatTime, resolveArtifactUrl } from '../api'
import type { Job, JobStatus } from '../types'

function artifactLabel(key: string): string {
  const labels: Record<string, string> = {
    video: 'MP4 Video',
    gif: 'GIF',
    poster: 'Poster',
    subtitles: 'Subtitles (SRT)',
    manifest: 'Bridge manifest',
  }
  if (key.startsWith('keyframe_')) return 'Keyframe ' + key.slice('keyframe_'.length)
  return labels[key] ?? key
}

const STATUS_STYLE: Record<JobStatus, string> = {
  pending: 'border-warn/50 bg-warn/10 text-warn',
  running: 'border-radeon-500/50 bg-radeon-500/10 text-radeon-400',
  completed: 'border-ok/50 bg-ok/10 text-ok',
  failed: 'border-danger/50 bg-danger/10 text-danger',
}

const JobCard = forwardRef<HTMLDivElement, { job: Job; highlighted: boolean }>(
  function JobCard({ job, highlighted }, ref) {
    const active = job.status === 'pending' || job.status === 'running'
    const pct = Math.round(job.progress * 100)

    const gifUrl = job.artifacts.gif ? resolveArtifactUrl(job.artifacts.gif) : null
    const videoUrl = job.artifacts.video ? resolveArtifactUrl(job.artifacts.video) : null
    const otherArtifacts = Object.entries(job.artifacts).filter(
      ([k]) => k !== 'gif' && k !== 'video',
    )

    return (
      <article
        ref={ref}
        className={`clip-angled border bg-ink-950 p-5 transition-all ${
          highlighted ? 'border-radeon-500/70 glow-red' : 'border-line hover:border-line-strong'
        }`}
      >
        <header className="flex flex-wrap items-center gap-2.5">
          <span className="font-mono text-xs font-bold text-fg" title={job.id}>
            #{job.id}
          </span>
          <span className="clip-angled-sm border border-line bg-ink-850 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-radeon-400">
            {job.engine}
          </span>
          <span
            className={`clip-angled-sm border px-2 py-0.5 text-[11px] font-semibold ${STATUS_STYLE[job.status] ?? 'border-line bg-ink-850 text-mut'}`}
          >
            {job.status}
          </span>
          {job.manifest?.route && (
            <span className="clip-angled-sm border border-ember-500/40 bg-ember-500/10 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ember-400">
              {job.manifest.route}
            </span>
          )}
          <span className="ml-auto font-mono text-[11px] text-dim">{formatTime(job.created_at)}</span>
        </header>

        {job.text && (
          <p className="mt-3 line-clamp-2 text-sm font-semibold text-fg" title={job.text}>
            {job.text}
          </p>
        )}

        {job.manifest?.reason && (
          <p className="mt-1 text-xs text-mut" title={job.manifest.reason}>
            {job.manifest.reason}
          </p>
        )}

        {/* progress bar */}
        <div className="relative mt-3 h-3.5 overflow-hidden border border-line bg-ink-850 clip-angled-sm">
          <div
            className={`h-full bg-gradient-to-r from-radeon-600 via-radeon-500 to-ember-500 transition-[width] duration-400 ease-out ${
              active ? 'animate-shimmer' : ''
            }`}
            style={
              active
                ? {
                    width: `${Math.max(pct, 8)}%`,
                    backgroundImage:
                      'linear-gradient(90deg, #c8102e, #ff3b43, #ff6a00, #ff3b43, #c8102e)',
                    backgroundSize: '200% 100%',
                  }
                : { width: `${pct}%` }
            }
          />
          <span className="absolute inset-0 flex items-center justify-center font-mono text-[10px] font-bold text-fg/90">
            {pct}%
          </span>
        </div>
        <p className="mt-1.5 text-xs text-dim">
          {job.message ?? ''}
          {active && ' · rendering, auto-refreshing'}
        </p>

        {job.error && (
          <div className="mt-3 border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
            <strong>Error: </strong>
            {job.error.message || job.error.type}
          </div>
        )}

        {Object.keys(job.metrics).length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {Object.entries(job.metrics).map(([k, v]) => (
              <span
                key={k}
                className="clip-angled-sm max-w-full truncate border border-line bg-ink-850 px-2 py-0.5 font-mono text-[10px] text-mut"
              >
                {k}: {typeof v === 'object' ? JSON.stringify(v) : String(v)}
              </span>
            ))}
          </div>
        )}

        {/* Inline preview: video first, GIF fallback; hidden until completed.
            Only the tracked (highlighted) video autoplays; others stay paused
            to reduce concurrency load. */}
        {(videoUrl || gifUrl) && job.status === 'completed' && (
          <div className="mt-4 border border-line bg-ink-950 p-2 clip-angled-sm">
            {videoUrl ? (
              <video
                src={videoUrl}
                controls
                autoPlay={highlighted}
                loop
                muted
                playsInline
                preload={highlighted ? 'auto' : 'metadata'}
                className="mx-auto block max-h-[360px] w-full"
              />
            ) : gifUrl ? (
              <img
                src={gifUrl}
                alt={job.text ?? 'rendered animation'}
                className="mx-auto block max-h-[360px] w-full"
              />
            ) : null}
          </div>
        )}

        {Object.keys(job.artifacts).length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {videoUrl && (
              <a
                className="clip-angled-sm border border-radeon-500/40 bg-radeon-500/10 px-3 py-1.5 text-xs font-semibold text-radeon-400 transition-all hover:glow-red-sm"
                href={videoUrl}
                target="_blank"
                rel="noreferrer"
                download
              >
                ⬇ {artifactLabel('video')}
              </a>
            )}
            {gifUrl && (
              <a
                className="clip-angled-sm border border-radeon-500/40 bg-radeon-500/10 px-3 py-1.5 text-xs font-semibold text-radeon-400 transition-all hover:glow-red-sm"
                href={gifUrl}
                target="_blank"
                rel="noreferrer"
                download
              >
                ⬇ {artifactLabel('gif')}
              </a>
            )}
            {otherArtifacts.map(([key, url]) => (
              <a
                key={key}
                className="clip-angled-sm border border-line bg-ink-850 px-3 py-1.5 text-xs text-mut transition-all hover:border-line-strong hover:text-fg"
                href={resolveArtifactUrl(url)}
                target="_blank"
                rel="noreferrer"
                download
              >
                ⬇ {artifactLabel(key)}
              </a>
            ))}
          </div>
        )}
      </article>
    )
  },
)

export default JobCard