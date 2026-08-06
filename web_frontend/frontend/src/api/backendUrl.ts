import { invoke, isTauri } from '@tauri-apps/api/core'

let backendBaseUrl: Promise<string> | null = null
let resolvedBackendBaseUrl: string | null = null
const BACKEND_READINESS_TIMEOUT_MS = 60_000
const BACKEND_READINESS_POLL_INTERVAL_MS = 200

interface BackendStatus {
  running: boolean
  error?: string | null
  log_path?: string | null
  log_tail?: string | null
}

export function backendUrl(path: string): Promise<string> {
  if (!isTauri()) return Promise.resolve(path)

  backendBaseUrl ??= invoke<string>('backend_url').then((value) => {
    const url = new URL(value)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      throw new Error(`Unsupported backend protocol: ${url.protocol}`)
    }
    resolvedBackendBaseUrl = url.toString()
    return resolvedBackendBaseUrl
  })

  return backendBaseUrl.then((baseUrl) => new URL(path, baseUrl).toString())
}

export async function initializeBackendUrl(): Promise<void> {
  await backendUrl('/')
}

export async function restartBackend(): Promise<void> {
  backendBaseUrl = null
  resolvedBackendBaseUrl = null
  if (isTauri()) {
    await invoke('restart_backend')
  }
}

export async function waitForBackendReady(): Promise<void> {
  const healthUrl = await backendUrl('/health')
  const deadline = Date.now() + BACKEND_READINESS_TIMEOUT_MS
  let lastFailure = ''

  while (Date.now() < deadline) {
    try {
      const response = await fetch(healthUrl, { cache: 'no-store' })
      if (response.ok) return
      lastFailure = `HTTP ${response.status}`
    } catch (error) {
      lastFailure = error instanceof Error ? error.message : String(error)
      const processFailure = await backendProcessFailure()
      if (processFailure) {
        throw new Error(processFailure)
      }
    }
    await delay(BACKEND_READINESS_POLL_INTERVAL_MS)
  }

  throw new Error(`Backend initialization timed out${lastFailure ? `: ${lastFailure}` : ''}`)
}

async function backendProcessFailure(): Promise<string | null> {
  if (!isTauri()) return null
  try {
    const status = await invoke<BackendStatus>('backend_status')
    if (status.running) return null
    const details = [
      status.error || 'Python backend process exited before becoming ready.',
      status.log_tail?.trim(),
      status.log_path ? `Log: ${status.log_path}` : '',
    ].filter(Boolean)
    return details.join('\n\n')
  } catch {
    return null
  }
}

async function delay(milliseconds: number): Promise<void> {
  await new Promise(resolve => window.setTimeout(resolve, milliseconds))
}

export function resolvedBackendUrl(path: string): string {
  if (!isTauri()) return path
  if (!resolvedBackendBaseUrl) {
    throw new Error('Backend URL has not been initialized')
  }
  return new URL(path, resolvedBackendBaseUrl).toString()
}
