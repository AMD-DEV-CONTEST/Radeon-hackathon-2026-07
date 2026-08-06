import type { FactoryFrontendCommand, FactoryFrontendEvent } from '@/types/protocol'
import { backendUrl } from './backendUrl'

interface EventResponse {
  event: FactoryFrontendEvent
}

export interface CommandResponse {
  accepted: boolean
  command: FactoryFrontendCommand
}

export interface BlobResponse {
  blob: Blob
  filename: string | null
}

export interface ApiValidationIssue {
  path: string
  message: string
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown
  readonly validationIssues: ApiValidationIssue[]

  constructor(status: number, detail: unknown, validationIssues: ApiValidationIssue[]) {
    super(apiErrorSummary(status, detail, validationIssues))
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.validationIssues = validationIssues
  }
}

export async function postCommand(command: FactoryFrontendCommand): Promise<CommandResponse> {
  return requestJson<CommandResponse>('/api/commands', {
    method: 'POST',
    body: JSON.stringify({ command }),
  })
}

export async function requestEvent(url: string, init: RequestInit = {}): Promise<FactoryFrontendEvent> {
  const response = await requestJson<EventResponse>(url, init)
  return response.event
}

export function requestFormEvent(
  url: string,
  formData: FormData,
  onUploadProgress?: (percent: number) => void,
): Promise<FactoryFrontendEvent> {
  return backendUrl(url).then((requestUrl) => new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', requestUrl)
    request.upload.addEventListener('progress', (event) => {
      if (!event.lengthComputable || event.total <= 0) return
      onUploadProgress?.(Math.round((event.loaded / event.total) * 100))
    })
    request.addEventListener('load', () => {
      if (request.status < 200 || request.status >= 300) {
        reject(apiErrorFromText(request.status, request.responseText))
        return
      }
      try {
        const data = JSON.parse(request.responseText) as EventResponse
        resolve(data.event)
      } catch (error) {
        reject(error)
      }
    })
    request.addEventListener('error', () => reject(new Error('Knowledge upload request failed')))
    request.addEventListener('abort', () => reject(new Error('Knowledge upload request was cancelled')))
    request.send(formData)
  }))
}

export async function requestBlob(url: string, init: RequestInit = {}): Promise<BlobResponse> {
  const response = await fetch(await backendUrl(url), init)
  if (!response.ok) {
    throw await apiErrorFromResponse(response)
  }
  return {
    blob: await response.blob(),
    filename: filenameFromDisposition(response.headers.get('content-disposition')),
  }
}

export async function requestJson<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(await backendUrl(url), {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  })
  if (!response.ok) {
    throw await apiErrorFromResponse(response)
  }
  return response.json() as Promise<T>
}

export function withQuery(path: string, params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value))
    }
  })
  const query = search.toString()
  return query ? `${path}?${query}` : path
}

function filenameFromDisposition(disposition: string | null): string | null {
  if (!disposition) return null
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) return decodeURIComponent(utf8Match[1])
  const asciiMatch = disposition.match(/filename="?([^";]+)"?/i)
  return asciiMatch?.[1] || null
}

async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  return apiErrorFromText(response.status, await response.text())
}

function apiErrorFromText(status: number, text: string): ApiError {
  const payload = parseErrorPayload(text)
  const detail = errorDetail(payload)
  return new ApiError(status, detail, validationIssues(detail))
}

function parseErrorPayload(text: string): unknown {
  if (!text.trim()) return null
  try {
    return JSON.parse(text)
  } catch {
    return text.trim()
  }
}

function errorDetail(payload: unknown): unknown {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return payload
  return 'detail' in payload ? (payload as { detail?: unknown }).detail : payload
}

function validationIssues(detail: unknown): ApiValidationIssue[] {
  if (Array.isArray(detail)) {
    return detail.flatMap((item) => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return []
      const record = item as Record<string, unknown>
      const location = Array.isArray(record.loc) ? record.loc.map(String) : []
      return [{
        path: location.filter(part => part !== 'body').join('.'),
        message: typeof record.msg === 'string' ? record.msg : 'Invalid value',
      }]
    })
  }
  if (typeof detail !== 'string' || !detail.includes('ValidationError')) return []
  const lines = detail.split(/\r?\n/)
  return lines.flatMap((line, index) => {
    const path = line.trim()
    const message = lines[index + 1]?.trim() || ''
    if (!path || !message || !/^(Value error|Field required|Input should)/i.test(message)) return []
    return [{ path, message: message.replace(/\s*\[type=.*$/, '') }]
  })
}

function apiErrorSummary(
  status: number,
  detail: unknown,
  issues: ApiValidationIssue[],
): string {
  if (issues.length) {
    const fields = [...new Set(issues.map(issue => issue.path).filter(Boolean))]
    return fields.length
      ? `Invalid submitted fields: ${fields.join(', ')}`
      : 'Submitted data is invalid'
  }
  if (typeof detail === 'string' && detail.includes('ValidationError')) {
    return 'Submitted data is invalid'
  }
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const message = (detail as Record<string, unknown>).message
    if (typeof message === 'string' && message.trim()) return message.trim()
  }
  return `HTTP ${status}`
}
