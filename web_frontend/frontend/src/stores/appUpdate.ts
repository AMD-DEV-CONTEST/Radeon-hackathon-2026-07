import { computed, ref } from 'vue'
import { getVersion } from '@tauri-apps/api/app'
import { defineStore } from 'pinia'
import { invoke, isTauri } from '@tauri-apps/api/core'
import { relaunch } from '@tauri-apps/plugin-process'
import { check, type DownloadEvent, type Update } from '@tauri-apps/plugin-updater'

type UpdateStatus =
  | 'idle'
  | 'checking'
  | 'available'
  | 'downloading'
  | 'installing'
  | 'error'

export type UpdateCheckResult = 'available' | 'up-to-date' | 'unavailable'

export interface AppUpdateMetadata {
  currentVersion: string
  version: string
  date: string
  body: string
}

export const useAppUpdateStore = defineStore('appUpdate', () => {
  const status = ref<UpdateStatus>('idle')
  const metadata = ref<AppUpdateMetadata | null>(null)
  const downloadedBytes = ref(0)
  const contentLength = ref(0)
  const error = ref('')
  const currentVersion = ref('')
  let pendingUpdate: Update | null = null
  let checkedThisLaunch = false
  let activeCheck: Promise<UpdateCheckResult> | null = null

  const visible = computed(() =>
    ['available', 'downloading', 'installing', 'error'].includes(status.value),
  )
  const progress = computed(() => {
    if (!contentLength.value) return 0
    return Math.min(1, downloadedBytes.value / contentLength.value)
  })

  async function loadCurrentVersion(): Promise<string> {
    if (currentVersion.value) return currentVersion.value
    if (!isTauri()) return ''
    currentVersion.value = await getVersion()
    return currentVersion.value
  }

  function checkAtStartup(): Promise<UpdateCheckResult> {
    void loadCurrentVersion().catch(() => undefined)
    if (checkedThisLaunch) return activeCheck || Promise.resolve('up-to-date')
    checkedThisLaunch = true
    return checkForUpdate()
  }

  function checkForUpdate(): Promise<UpdateCheckResult> {
    void loadCurrentVersion().catch(() => undefined)
    if (!isTauri() || import.meta.env.DEV) return Promise.resolve('unavailable')
    if (activeCheck) return activeCheck
    status.value = 'checking'
    error.value = ''
    activeCheck = check({ timeout: 30_000 })
      .then(async (update) => {
        if (!update) {
          status.value = 'idle'
          return 'up-to-date' as const
        }
        if (pendingUpdate) await pendingUpdate.close()
        pendingUpdate = update
        metadata.value = {
          currentVersion: update.currentVersion,
          version: update.version,
          date: update.date || '',
          body: update.body || '',
        }
        status.value = 'available'
        return 'available' as const
      })
      .catch((reason: unknown) => {
        status.value = 'idle'
        console.warn('Application update check failed:', reason)
        return 'unavailable' as const
      })
      .finally(() => {
        activeCheck = null
      })
    return activeCheck
  }

  async function install(): Promise<void> {
    const update = pendingUpdate
    if (!update || !['available', 'error'].includes(status.value)) return
    status.value = 'downloading'
    downloadedBytes.value = 0
    contentLength.value = 0
    error.value = ''
    let backendStopped = false
    try {
      await update.download(handleDownloadEvent, { timeout: 30 * 60 * 1000 })
      status.value = 'installing'
      await invoke('shutdown_backend')
      backendStopped = true
      await update.install()
      await relaunch()
    } catch (reason) {
      if (backendStopped) await invoke('restart_backend').catch(() => undefined)
      status.value = 'error'
      error.value = reason instanceof Error ? reason.message : String(reason)
    }
  }

  async function dismiss(): Promise<void> {
    if (status.value === 'downloading' || status.value === 'installing') return
    const update = pendingUpdate
    pendingUpdate = null
    metadata.value = null
    error.value = ''
    status.value = 'idle'
    if (update) await update.close().catch(() => undefined)
  }

  function handleDownloadEvent(event: DownloadEvent): void {
    if (event.event === 'Started') {
      contentLength.value = event.data.contentLength || 0
      return
    }
    if (event.event === 'Progress') {
      downloadedBytes.value += event.data.chunkLength
    }
  }

  return {
    status,
    metadata,
    downloadedBytes,
    contentLength,
    error,
    currentVersion,
    visible,
    progress,
    loadCurrentVersion,
    checkAtStartup,
    checkForUpdate,
    install,
    dismiss,
  }
})
