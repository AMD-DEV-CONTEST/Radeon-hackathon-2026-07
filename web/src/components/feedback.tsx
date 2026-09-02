import type { ReactNode } from 'react'
import { ApiError } from '../api/errors'

export function FullScreenLoading({ label = '正在加载…' }: { label?: string }) {
  return (
    <div className="center-screen" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <p>{label}</p>
    </div>
  )
}

export function LoadingBlock({ label = '正在加载…' }: { label?: string }) {
  return (
    <div className="loading-block" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

export function EmptyState({
  title,
  hint,
}: {
  title: string
  hint?: string
}) {
  return (
    <div className="empty-state" role="status">
      <h3>{title}</h3>
      {hint ? <p>{hint}</p> : null}
    </div>
  )
}

/**
 * User-facing error surfacing. Always shows a human-readable message and never
 * dumps a raw stack trace. Optionally offers a retry action.
 */
export function ErrorBanner({
  error,
  onRetry,
}: {
  error: ApiError | Error | null
  onRetry?: () => void
}) {
  if (!error) return null
  const message =
    error instanceof ApiError ? error.userMessage || error.message : error.message
  return (
    <div className="error-banner" role="alert">
      <span>{message}</span>
      {onRetry ? (
        <button type="button" className="retry" onClick={onRetry}>
          重试
        </button>
      ) : null}
    </div>
  )
}

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="page-header">
      <h1>{title}</h1>
      {children}
    </header>
  )
}
