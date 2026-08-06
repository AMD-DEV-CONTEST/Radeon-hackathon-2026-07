import type { ContextWindowView } from '@/types/protocol'

export interface ContextWindowMeterLabels {
  unknownUsage: string
  used: string
  compressionThreshold: string
}

export function contextWindowUsagePercent(contextWindow: ContextWindowView): number | null {
  const ratio = contextWindowUsageRatio(contextWindow)
  return ratio === null ? null : ratio * 100
}

export function contextWindowThresholdPercent(contextWindow: ContextWindowView): number | null {
  const threshold = contextWindow.compressionThresholdTokens
  const total = contextWindow.contextWindowTokens
  if (!threshold || !total || threshold <= 0 || total <= 0) {
    return null
  }
  return clamp((threshold / total) * 100, 0, 100)
}

export function contextWindowUsageLabel(contextWindow: ContextWindowView): string {
  return `${formatCompactTokenCount(contextWindow.tokenCount)} / ${formatCompactTokenCount(contextWindow.contextWindowTokens)}`
}

export function contextWindowPercentLabel(contextWindow: ContextWindowView, labels?: ContextWindowMeterLabels): string {
  const percent = contextWindowUsagePercent(contextWindow)
  if (percent === null) {
    return labels?.unknownUsage || 'Usage unknown'
  }
  return `${labels?.used || 'Used'} ${formatPercent(percent)}`
}

export function contextWindowThresholdLabel(contextWindow: ContextWindowView, labels?: ContextWindowMeterLabels): string {
  return `${labels?.compressionThreshold || 'Compression threshold'} ${formatCompactTokenCount(contextWindow.compressionThresholdTokens)}`
}

function contextWindowUsageRatio(contextWindow: ContextWindowView): number | null {
  if (contextWindow.tokenCount === null || !contextWindow.contextWindowTokens) {
    return null
  }
  return clamp(contextWindow.tokenCount / contextWindow.contextWindowTokens, 0, 1)
}

export function formatCompactTokenCount(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return '-'
  }
  const absolute = Math.abs(value)
  if (absolute >= 1_000_000) {
    return `${trimNumber(value / 1_000_000)}M`
  }
  if (absolute >= 1_000) {
    return `${trimNumber(value / 1_000)}k`
  }
  return String(Math.round(value))
}

function formatPercent(value: number): string {
  if (value >= 10) {
    return `${value.toFixed(1)}%`
  }
  if (value > 0) {
    return `${value.toFixed(2)}%`
  }
  return '0%'
}

function trimNumber(value: number): string {
  return value.toFixed(value >= 10 ? 0 : 1).replace(/\.0$/, '')
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}
