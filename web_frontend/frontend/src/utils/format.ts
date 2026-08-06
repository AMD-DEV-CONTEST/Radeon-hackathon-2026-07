import type { Locale } from '@/i18n'

interface RelativeTimeLabels {
  justNow: string
  minutesAgo: (minutes: number) => string
  yesterdayAt: (time: string) => string
}

export function formatTime(timestamp: string, locale: Locale = 'zh-CN', labels?: RelativeTimeLabels): string {
  if (!timestamp) {
    return ''
  }

  const date = new Date(timestamp)

  // 检查日期是否有效
  if (isNaN(date.getTime())) {
    console.warn('Invalid timestamp:', timestamp)
    return timestamp
  }

  const now = new Date()
  const diff = now.getTime() - date.getTime()

  if (diff < 60000) {
    return labels?.justNow || new Intl.RelativeTimeFormat(locale, { numeric: 'auto' }).format(0, 'minute')
  }

  if (diff < 3600000) {
    const minutes = Math.floor(diff / 60000)
    return labels?.minutesAgo(minutes) || new Intl.RelativeTimeFormat(locale, { numeric: 'auto' }).format(-minutes, 'minute')
  }

  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString(locale, {
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (date.toDateString() === yesterday.toDateString()) {
    const time = date.toLocaleTimeString(locale, {
      hour: '2-digit',
      minute: '2-digit',
    })
    return labels?.yesterdayAt(time) || time
  }

  return date.toLocaleDateString(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  if (ms < 3600000) return `${(ms / 60000).toFixed(1)}min`
  return `${(ms / 3600000).toFixed(1)}h`
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}
