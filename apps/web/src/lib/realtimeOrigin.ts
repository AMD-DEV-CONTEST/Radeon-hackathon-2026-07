/**
 * Realtime WebSocket origin in the browser.
 *
 * Delegates to localAgent.ts so that in production (cloud-hosted) the
 * WebSocket connects directly to the user's Local Agent on localhost:8002,
 * while in dev mode (Vite proxy) relative paths still work.
 *
 * Override: VITE_REALTIME_WS_URL=e.g. wss://api.example.com (no path suffix).
 */
import { agentWsUrl } from './localAgent'

export function getRealtimeWsOrigin(): string {
  const env = import.meta.env.VITE_REALTIME_WS_URL as string | undefined
  if (env && String(env).trim()) {
    return String(env).replace(/\/$/, '')
  }
  return agentWsUrl('').replace(/\/$/, '')
}

export function resolveRealtimeWsUrl(path: string): string {
  if (/^wss?:\/\//i.test(path)) return path
  const env = import.meta.env.VITE_REALTIME_WS_URL as string | undefined
  if (env && String(env).trim()) {
    const p = path.startsWith('/') ? path : `/${path}`
    return `${String(env).replace(/\/$/, '')}${p}`
  }
  return agentWsUrl(path)
}
