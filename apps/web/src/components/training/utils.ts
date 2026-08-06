export function parseApiError(raw: string): string {
  try {
    const jsonStart = raw.indexOf('{')
    if (jsonStart >= 0) {
      const body = JSON.parse(raw.slice(jsonStart)) as {
        detail?: string | { message?: string; code?: string }
      }
      if (typeof body.detail === 'string') return body.detail
      if (body.detail?.message) return body.detail.message
    }
  } catch {
    /* keep raw */
  }
  if (raw.includes('quota_training_concurrent')) {
    return '训练名额被旧任务占用了。系统会先同步旧任务，请稍后重试或取消旧任务。'
  }
  return raw.replace(/^\d+\s+/, '').trim() || raw
}

export function fmtTs(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

export function fmtDuration(s: number | null | undefined): string {
  if (!s || !Number.isFinite(s)) return '—'
  if (s < 60) return `${s.toFixed(1)} 秒`
  const m = Math.floor(s / 60)
  return `${m} 分 ${(s - m * 60).toFixed(0)} 秒`
}
