/**
 * Turn FastAPI error bodies into human-readable Chinese/English messages.
 */
export function formatApiDetail(detail: unknown, fallback = '请求失败，请稍后重试'): string {
  if (detail == null) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => formatApiDetail(item, '')).filter(Boolean)
    return parts.length > 0 ? parts.join('；') : fallback
  }
  if (typeof detail === 'object') {
    const o = detail as Record<string, unknown>
    if (typeof o.msg === 'string') {
      const loc = Array.isArray(o.loc) ? o.loc.filter((x) => x !== 'body').join('.') : ''
      const msg = o.msg
      if (msg.includes('valid email') || msg.includes('value is not a valid email')) {
        return loc ? `${loc}: 请输入有效邮箱地址` : '请输入有效邮箱地址'
      }
      if (msg.includes('at least 8')) {
        return '密码至少 8 位'
      }
      if (msg.includes('String should have at least')) {
        return '用户名至少 3 个字符'
      }
      return loc ? `${loc}: ${msg}` : msg
    }
    if (typeof o.message === 'string') return o.message
  }
  return fallback
}

export async function readApiError(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json()
    if (body?.detail != null) return formatApiDetail(body.detail, fallback)
    if (typeof body?.message === 'string') return body.message
  } catch {
    /* noop */
  }
  return fallback
}
