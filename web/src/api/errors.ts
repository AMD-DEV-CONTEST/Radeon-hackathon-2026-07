// Unified API error model and status -> user-facing message mapping.
//
// The backend returns a structured `ErrorDetail` body for most errors:
//   { "error_code": str, "message": str, "user_message": str, "details": {} }
// FastAPI validation errors (422) return the default shape:
//   { "detail": [ { "loc": [...], "msg": str, "type": str }, ... ] }
// Network failures (fetch throws) are surfaced as a special status `0`.

export interface ApiErrorBody {
  error_code?: string
  message?: string
  user_message?: string
  details?: Record<string, unknown>
}

/** A network-level failure (fetch threw) or a hard timeout (abort). */
export const NETWORK_ERROR_STATUS = 0

export class ApiError extends Error {
  readonly status: number
  readonly errorCode?: string
  readonly userMessage?: string
  readonly details?: Record<string, unknown>
  readonly raw: unknown

  constructor(
    status: number,
    opts: {
      message?: string
      errorCode?: string
      userMessage?: string
      details?: Record<string, unknown>
      raw?: unknown
    },
  ) {
    const message = opts.userMessage || opts.message || defaultMessageFor(status)
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.errorCode = opts.errorCode
    this.userMessage = opts.userMessage
    this.details = opts.details
    this.raw = opts.raw
  }

  get isNetworkError(): boolean {
    return this.status === NETWORK_ERROR_STATUS
  }

  get isAuthError(): boolean {
    return this.status === 401 || this.status === 403
  }
}

export function defaultMessageFor(status: number): string {
  switch (status) {
    case NETWORK_ERROR_STATUS:
      return '网络连接失败，请检查网络后重试。'
    case 401:
      return '登录状态已过期，请重新登录。'
    case 403:
      return '你没有执行此操作的权限。'
    case 404:
      return '未找到请求的资源。'
    case 409:
      return '该操作与当前状态冲突，请刷新后重试。'
    case 422:
      return '请求被拒绝，部分字段无效。'
    default:
      if (status >= 500) {
        return '服务器发生错误，请稍后重试。'
      }
      return `请求失败（HTTP ${status}）。`
  }
}

function extract422Messages(body: { detail?: unknown }): string | undefined {
  const detail = body.detail
  if (!Array.isArray(detail)) return undefined
  const parts = detail
    .map((item: { loc?: unknown; msg?: string }) => {
      const where = Array.isArray(item?.loc) ? item.loc.slice(1).join('.') : ''
      return where ? `${where}: ${item.msg ?? ''}` : (item?.msg ?? '')
    })
    .filter(Boolean)
  return parts.length > 0 ? parts.join('; ') : undefined
}

/** Build an `ApiError` from an HTTP status and a (best-effort) parsed body. */
export function mapError(status: number, body: unknown): ApiError {
  if (body && typeof body === 'object') {
    let b = body as Record<string, unknown>
    // Some routers raise HTTPException(detail={error_code, ...}); FastAPI then
    // nests the structured body under `detail`. Unwrap it so both shapes map
    // to the same ApiError (task lifecycle/import/confirmation errors use it).
    if (
      b.detail &&
      typeof b.detail === 'object' &&
      !Array.isArray(b.detail) &&
      (b.detail as Record<string, unknown>).error_code !== undefined
    ) {
      b = b.detail as Record<string, unknown>
    }
    if (status === 422 && b.detail !== undefined) {
      const msg = extract422Messages(b as { detail?: unknown })
      return new ApiError(status, {
        errorCode: 'VALIDATION_ERROR',
        message: msg,
        userMessage: msg ?? defaultMessageFor(422),
        raw: body,
      })
    }
    const errorCode = typeof b.error_code === 'string' ? b.error_code : undefined
    const message = typeof b.message === 'string' ? b.message : undefined
    const userMessage = typeof b.user_message === 'string' ? b.user_message : undefined
    const details =
      b.details && typeof b.details === 'object'
        ? (b.details as Record<string, unknown>)
        : undefined
    if (errorCode || message || userMessage) {
      return new ApiError(status, { errorCode, message, userMessage, details, raw: body })
    }
  }
  return new ApiError(status, { raw: body })
}
