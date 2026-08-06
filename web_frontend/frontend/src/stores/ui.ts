/**
 * UI 状态 Store
 * 管理全局 UI 状态（主题、侧边栏、弹窗等）
 */

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import {
  defaultLocale,
  localeStorageKey,
  normalizeLocale,
  type Locale,
} from '@/i18n'

export type ThemeMode = 'light' | 'dark' | 'auto'
export type ConversationDockPanel = 'workspace' | 'memory' | 'sessions' | 'tasks'

const STORAGE_KEYS = {
  locale: localeStorageKey,
  themeMode: 'fast-agent-factory.themeMode',
} as const

function readStoredLocale(): Locale {
  if (typeof window === 'undefined') return defaultLocale
  const stored = window.localStorage.getItem(STORAGE_KEYS.locale)
  return stored ? normalizeLocale(stored) : defaultLocale
}

function readStoredThemeMode(): ThemeMode {
  if (typeof window === 'undefined') return 'light'
  const stored = window.localStorage.getItem(STORAGE_KEYS.themeMode)
  if (stored === 'dark' || stored === 'light' || stored === 'auto') return stored
  return 'light'
}

function detectSystemDark(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

function writeStorage(key: string, value: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(key, value)
}

export const useUiStore = defineStore('ui', () => {
  // ========== 主题 ==========
  const themeMode = ref<ThemeMode>(readStoredThemeMode())
  const isDarkMode = ref(detectSystemDark())
  const locale = ref<Locale>(readStoredLocale())

  // ========== 布局 ==========
  const conversationDockPanel = ref<ConversationDockPanel | null>(null)

  // ========== 弹窗/抽屉 ==========
  const settingsDrawerOpen = ref(false)
  const debugDrawerOpen = ref(false)
  const schedulerActivityDrawerOpen = ref(false)

  // ========== 通知 ==========
  interface Notification {
    id: string
    type: 'info' | 'success' | 'warning' | 'error'
    title: string
    message?: string
    duration?: number
    actionLabel?: string
    onAction?: () => void
  }

  const notifications = ref<Notification[]>([])

  function addNotification(notification: Omit<Notification, 'id'>): string {
    const id = `notif-${Date.now()}-${Math.random().toString(36).slice(2)}`
    notifications.value.push({ id, ...notification })

    // 自动移除
    if (notification.duration !== 0) {
      setTimeout(() => {
        removeNotification(id)
      }, notification.duration || 5000)
    }

    return id
  }

  function removeNotification(id: string): void {
    const index = notifications.value.findIndex((n) => n.id === id)
    if (index !== -1) {
      notifications.value.splice(index, 1)
    }
  }

  // ========== 加载状态 ==========
  const globalLoading = ref(false)
  const loadingTasks = ref<Set<string>>(new Set())

  function startLoading(taskId?: string): string {
    const id = taskId || `task-${Date.now()}-${Math.random().toString(36).slice(2)}`
    loadingTasks.value.add(id)
    globalLoading.value = true
    return id
  }

  function stopLoading(taskId: string): void {
    loadingTasks.value.delete(taskId)
    if (loadingTasks.value.size === 0) {
      globalLoading.value = false
    }
  }

  // ========== 计算属性 ==========
  const actualTheme = computed(() => {
    if (themeMode.value === 'auto') {
      return isDarkMode.value ? 'dark' : 'light'
    }
    return themeMode.value
  })

  // ========== Actions ==========
  function setConversationDockPanel(panel: ConversationDockPanel | null): void {
    conversationDockPanel.value = panel
  }

  function toggleConversationDockPanel(panel: ConversationDockPanel): void {
    conversationDockPanel.value = conversationDockPanel.value === panel ? null : panel
  }

  function setThemeMode(mode: ThemeMode): void {
    themeMode.value = mode
    writeStorage(STORAGE_KEYS.themeMode, mode)
    if (mode !== 'auto') {
      isDarkMode.value = mode === 'dark'
    } else {
      isDarkMode.value = detectSystemDark()
    }
  }

  function setLocale(nextLocale: Locale): void {
    locale.value = nextLocale
    writeStorage(STORAGE_KEYS.locale, nextLocale)
  }

  function toggleSettingsDrawer(): void {
    settingsDrawerOpen.value = !settingsDrawerOpen.value
  }

  function toggleDebugDrawer(): void {
    debugDrawerOpen.value = !debugDrawerOpen.value
  }

  function openSchedulerActivityDrawer(): void {
    schedulerActivityDrawerOpen.value = true
  }

  function closeSchedulerActivityDrawer(): void {
    schedulerActivityDrawerOpen.value = false
  }

  // 初始化主题监听
  if (typeof window !== 'undefined') {
    watch(
      locale,
      (value) => {
        document.documentElement.lang = value
      },
      { immediate: true }
    )

    // 监听系统主题变化，仅在 auto 模式下生效
    if (window.matchMedia) {
      const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
      const handler = (event: MediaQueryListEvent) => {
        if (themeMode.value === 'auto') {
          isDarkMode.value = event.matches
        }
      }
      if (typeof mediaQuery.addEventListener === 'function') {
        mediaQuery.addEventListener('change', handler)
      } else if (typeof (mediaQuery as MediaQueryList & { addListener?: (fn: (e: MediaQueryListEvent) => void) => void }).addListener === 'function') {
        (mediaQuery as MediaQueryList & { addListener: (fn: (e: MediaQueryListEvent) => void) => void }).addListener(handler)
      }
    }
  }

  return {
    // State
    themeMode,
    isDarkMode,
    locale,
    conversationDockPanel,
    settingsDrawerOpen,
    debugDrawerOpen,
    schedulerActivityDrawerOpen,
    notifications,
    globalLoading,
    loadingTasks,

    // Computed
    actualTheme,

    // Actions
    setConversationDockPanel,
    toggleConversationDockPanel,
    setThemeMode,
    setLocale,
    toggleSettingsDrawer,
    toggleDebugDrawer,
    openSchedulerActivityDrawer,
    closeSchedulerActivityDrawer,
    addNotification,
    removeNotification,
    startLoading,
    stopLoading,
  }
})
