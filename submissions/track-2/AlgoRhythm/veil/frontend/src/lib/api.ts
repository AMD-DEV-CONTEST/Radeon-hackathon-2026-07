// ── REST API client ────────────────────────────────────────────────────────
import type {
  LoginResponse, UploadResponse, DocumentResponse,
  SelfTestResponse, AuditLogResponse, ChatResponse, OverrideResponse,
  EditType,
} from '@/types'

let _token: string | null = null

export function setToken(t: string | null) { _token = t }
export function getToken() { return _token }

function headers(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { ...extra }
  if (_token) h['X-Veil-Token'] = _token
  return h
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: headers(init?.headers as Record<string, string>),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, body.detail ?? res.statusText)
  }
  return res.json()
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

export const api = {
  login(role: string, passphrase: string): Promise<LoginResponse> {
    return request('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role, passphrase }),
    })
  },

  selftest(): Promise<SelfTestResponse> {
    return request('/api/security/selftest')
  },

  uploadDocument(file: File): Promise<UploadResponse> {
    const fd = new FormData()
    fd.append('file', file)
    return request('/api/documents', { method: 'POST', body: fd })
  },

  getDocument(documentId: string): Promise<DocumentResponse> {
    return request(`/api/documents/${documentId}`)
  },

  getAuditLog(n = 100): Promise<AuditLogResponse> {
    return request(`/api/audit?n=${n}`)
  },

  chat(documentId: string, message: string): Promise<ChatResponse> {
    return request(`/api/documents/${documentId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    })
  },

  applyOverride(
    documentId: string,
    aggressiveness: string,
    overrides: Record<string, EditType>,
  ): Promise<OverrideResponse> {
    return request(`/api/documents/${documentId}/override`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ aggressiveness, overrides }),
    })
  },
}
