import { getCurrentWindow } from '@tauri-apps/api/window'
import { invoke, isTauri } from '@tauri-apps/api/core'

export type DesktopPlatform = 'windows' | 'macos' | 'linux' | 'unknown'

let platformRequest: Promise<DesktopPlatform> | null = null

export function desktopPlatform(): Promise<DesktopPlatform> {
  if (!isTauri()) return Promise.resolve('unknown')
  if (!platformRequest) {
    platformRequest = invoke<string>('desktop_platform')
      .then(normalizeDesktopPlatform)
      .catch(() => 'unknown')
  }
  return platformRequest
}

export async function minimizeDesktopWindow(): Promise<void> {
  await getCurrentWindow().minimize()
}

export async function toggleMaximizeDesktopWindow(): Promise<void> {
  await getCurrentWindow().toggleMaximize()
}

export async function closeDesktopWindow(): Promise<void> {
  await getCurrentWindow().close()
}

export async function startDesktopWindowDrag(): Promise<void> {
  await getCurrentWindow().startDragging()
}

function normalizeDesktopPlatform(value: string): DesktopPlatform {
  if (value === 'windows' || value === 'macos' || value === 'linux') return value
  return 'unknown'
}
