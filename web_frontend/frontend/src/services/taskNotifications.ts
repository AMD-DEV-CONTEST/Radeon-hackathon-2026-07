import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'
import {
  isPermissionGranted,
  onAction,
  requestPermission,
  sendNotification,
  type Options as NativeNotificationOptions,
} from '@tauri-apps/plugin-notification'
import type { PluginListener } from '@tauri-apps/api/core'
import type { Router } from 'vue-router'
import { translate, type I18nKey } from '@/i18n'
import { useAgentGroupStore } from '@/stores/agentGroup'
import { useRuntimeStore } from '@/stores/runtime'
import { useTaskNotificationPreferencesStore, type TaskNotificationCategory } from '@/stores/taskNotificationPreferences'
import { useUiStore } from '@/stores/ui'

export type TaskNotificationStatus = 'completed' | 'failed' | 'cancelled' | 'skipped'

export type TaskNotificationTarget =
  | {
      kind: 'conversation'
      mode: 'create_agent' | 'evolve_agent' | 'agent_package'
      sessionId: string | null
      packageId: string | null
      conversationScope?: string | null
    }
  | { kind: 'agentGroup'; groupId: string }
  | { kind: 'scheduler' }

export interface TaskTerminalNotification {
  key: string
  category: TaskNotificationCategory
  status: TaskNotificationStatus
  subject?: string | null
  body?: string | null
  target: TaskNotificationTarget
}

const SEEN_NOTIFICATION_STORAGE_KEY = 'fast-agent-factory.seenTaskNotifications'
const MAX_SEEN_NOTIFICATION_KEYS = 256
const MAX_NOTIFICATION_BODY_LENGTH = 240
const NATIVE_TARGET_EXTRA_KEY = 'fastAgentFactoryTarget'
const NATIVE_TARGET_STORAGE_KEY = 'fast-agent-factory.nativeNotificationTargets'
const MAX_NATIVE_NOTIFICATION_TARGETS = 128

let router: Router | null = null
let nativeActionListener: PluginListener | null = null
let initialization: Promise<void> | null = null
const pendingNotifications: TaskTerminalNotification[] = []
const seenKeys = readSeenKeys()
const nativeTargets = readNativeTargets()

export function initializeTaskNotifications(appRouter: Router): Promise<void> {
  router = appRouter
  if (initialization) return initialization
  initialization = initializeNativeNotifications()
    .catch((error) => {
      console.warn('Native task notifications are unavailable:', error)
    })
    .finally(() => {
      const pending = pendingNotifications.splice(0)
      pending.forEach((notification) => void deliverTaskNotification(notification))
    })
  return initialization
}

export function disposeTaskNotifications(): void {
  nativeActionListener?.unregister()
  nativeActionListener = null
  router = null
  initialization = null
}

export function publishTaskNotification(notification: TaskTerminalNotification): void {
  if (!router) {
    pendingNotifications.push(notification)
    return
  }
  void deliverTaskNotification(notification)
}

export async function requestNativeTaskNotificationPermission(): Promise<boolean> {
  return ensureNativePermission(true)
}

async function initializeNativeNotifications(): Promise<void> {
  if (!isTauri()) return
  nativeActionListener = await onAction((notification) => {
    const target = targetFromNativeNotification(notification)
    if (!target) return
    forgetNativeTarget(notification.id)
    openNotificationTargetSafely(target)
  })
  const preferences = useTaskNotificationPreferencesStore()
  if (preferences.active) await ensureNativePermission(true)
}

async function deliverTaskNotification(notification: TaskTerminalNotification): Promise<void> {
  const preferences = useTaskNotificationPreferencesStore()
  if (!preferences.isCategoryEnabled(notification.category) || seenKeys.has(notification.key)) return
  rememberSeenKey(notification.key)

  if (await isCurrentTargetVisible(notification.target)) return

  const title = notificationTitle(notification)
  const body = compactBody(notification.body) || statusFallback(notification.status)
  const focused = await isAppFocused()
  if (focused || !isTauri()) {
    showInAppNotification(notification, title, body)
    return
  }

  if (!(await ensureNativePermission(false))) {
    showInAppNotification(notification, title, body)
    return
  }

  const notificationId = stableNotificationId(notification.key)
  rememberNativeTarget(notificationId, notification.target)
  try {
    sendNotification({
      id: notificationId,
      title,
      body,
      autoCancel: true,
      group: notification.category,
      extra: {
        [NATIVE_TARGET_EXTRA_KEY]: JSON.stringify(notification.target),
      },
    })
  } catch (error) {
    forgetNativeTarget(notificationId)
    console.warn('Native task notification delivery failed:', error)
    showInAppNotification(notification, title, body)
  }
}

function showInAppNotification(
  notification: TaskTerminalNotification,
  title: string,
  body: string,
): void {
  useUiStore().addNotification({
    type: notification.status === 'completed'
      ? 'success'
      : notification.status === 'skipped'
        ? 'warning'
        : 'error',
    title,
    message: body,
    duration: notification.status === 'completed' ? 8000 : 10000,
    actionLabel: translate(useUiStore().locale, 'common.view'),
    onAction: () => openNotificationTargetSafely(notification.target),
  })
}

async function ensureNativePermission(requestIfMissing: boolean): Promise<boolean> {
  if (!isTauri()) return false
  if (await isPermissionGranted()) return true
  if (!requestIfMissing) return false
  return (await requestPermission()) === 'granted'
}

async function isAppFocused(): Promise<boolean> {
  if (typeof document === 'undefined') return false
  if (document.visibilityState !== 'visible' || !document.hasFocus()) return false
  if (!isTauri()) return true
  try {
    return await getCurrentWindow().isFocused()
  } catch {
    return document.hasFocus()
  }
}

async function isCurrentTargetVisible(target: TaskNotificationTarget): Promise<boolean> {
  if (!(await isAppFocused()) || !router) return false
  const routeName = String(router.currentRoute.value.name || '')
  if (target.kind === 'scheduler') return routeName === 'Scheduler'
  if (target.kind === 'agentGroup') {
    return routeName === 'AgentGroup' && useAgentGroupStore().activeGroup?.group_id === target.groupId
  }
  if (routeName !== 'Factory') return false
  const runtimeStore = useRuntimeStore()
  if (target.conversationScope) {
    return runtimeStore.activeConversationScope === target.conversationScope
  }
  return target.mode === 'agent_package'
    ? runtimeStore.activeAgentSessionId === target.sessionId
    : runtimeStore.activeFactorySessionId === target.sessionId
}

async function openNotificationTarget(target: TaskNotificationTarget): Promise<void> {
  if (!router) return
  const focusPromise = focusApplicationWindow().catch((error) => {
    console.warn('Failed to focus the application window:', error)
  })
  if (target.kind === 'scheduler') {
    await router.push({ name: 'Scheduler' })
    await focusPromise
    return
  }
  if (target.kind === 'agentGroup') {
    await router.push({ name: 'AgentGroup' })
    await useAgentGroupStore().loadGroup(target.groupId)
    await focusPromise
    return
  }
  if (target.mode === 'agent_package' && target.packageId && target.sessionId) {
    await router.push({
      name: 'Factory',
      query: {
        package_id: target.packageId,
        session_id: target.sessionId,
      },
    })
    await focusPromise
    return
  }
  await router.push({ name: 'Factory' })
  await focusPromise
}

function openNotificationTargetSafely(target: TaskNotificationTarget): void {
  void openNotificationTarget(target).catch((error) => {
    console.warn('Failed to open task notification target:', error)
  })
}

async function focusApplicationWindow(): Promise<void> {
  if (!isTauri()) return
  const window = getCurrentWindow()
  await window.unminimize()
  await window.show()
  await window.setFocus()
}

function targetFromNativeNotification(notification: NativeNotificationOptions): TaskNotificationTarget | null {
  const serialized = notification.extra?.[NATIVE_TARGET_EXTRA_KEY]
  const embedded = parseNotificationTarget(serialized)
  if (embedded) return embedded
  const notificationId = Number(notification.id)
  return Number.isInteger(notificationId)
    ? nativeTargets.get(notificationId) || null
    : null
}

function notificationTitle(notification: TaskTerminalNotification): string {
  const locale = useUiStore().locale
  const subject = String(notification.subject || '').trim()
    || translate(locale, categoryTitleKey(notification.category))
  return translate(locale, 'taskNotification.title', {
    subject,
    status: translate(locale, statusTitleKey(notification.status)),
  })
}

function categoryTitleKey(category: TaskNotificationCategory): I18nKey {
  const keys: Record<TaskNotificationCategory, I18nKey> = {
    conversation: 'taskNotification.conversation',
    agentGroup: 'taskNotification.agentGroup',
    scheduler: 'taskNotification.scheduler',
  }
  return keys[category]
}

function statusTitleKey(status: TaskNotificationStatus): I18nKey {
  const keys: Record<TaskNotificationStatus, I18nKey> = {
    completed: 'taskNotification.completed',
    failed: 'taskNotification.failed',
    cancelled: 'taskNotification.cancelled',
    skipped: 'taskNotification.skipped',
  }
  return keys[status]
}

function statusFallback(status: TaskNotificationStatus): string {
  return translate(useUiStore().locale, statusTitleKey(status))
}

function compactBody(value: string | null | undefined): string {
  const normalized = String(value || '').replace(/\s+/g, ' ').trim()
  if (normalized.length <= MAX_NOTIFICATION_BODY_LENGTH) return normalized
  return `${normalized.slice(0, MAX_NOTIFICATION_BODY_LENGTH - 1)}…`
}

function stableNotificationId(value: string): number {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(index)) | 0
  }
  return hash
}

function readSeenKeys(): Set<string> {
  if (typeof window === 'undefined') return new Set()
  try {
    const stored = JSON.parse(window.localStorage.getItem(SEEN_NOTIFICATION_STORAGE_KEY) || '[]')
    return new Set(Array.isArray(stored) ? stored.map(String) : [])
  } catch {
    return new Set()
  }
}

function rememberSeenKey(key: string): void {
  seenKeys.add(key)
  while (seenKeys.size > MAX_SEEN_NOTIFICATION_KEYS) {
    const oldest = seenKeys.values().next().value
    if (oldest === undefined) break
    seenKeys.delete(oldest)
  }
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(SEEN_NOTIFICATION_STORAGE_KEY, JSON.stringify([...seenKeys]))
  }
}

function readNativeTargets(): Map<number, TaskNotificationTarget> {
  if (typeof window === 'undefined') return new Map()
  try {
    const stored = JSON.parse(
      window.localStorage.getItem(NATIVE_TARGET_STORAGE_KEY) || '[]',
    ) as Array<[unknown, unknown]>
    const entries = Array.isArray(stored)
      ? stored.flatMap(([id, target]) => {
          const numericId = Number(id)
          const parsedTarget = parseNotificationTarget(target)
          return Number.isInteger(numericId) && parsedTarget
            ? [[numericId, parsedTarget] as const]
            : []
        })
      : []
    return new Map(entries)
  } catch {
    return new Map()
  }
}

function rememberNativeTarget(id: number, target: TaskNotificationTarget): void {
  nativeTargets.delete(id)
  nativeTargets.set(id, target)
  while (nativeTargets.size > MAX_NATIVE_NOTIFICATION_TARGETS) {
    const oldest = nativeTargets.keys().next().value
    if (oldest === undefined) break
    nativeTargets.delete(oldest)
  }
  persistNativeTargets()
}

function forgetNativeTarget(id: number | undefined): void {
  if (!Number.isInteger(id)) return
  nativeTargets.delete(Number(id))
  persistNativeTargets()
}

function persistNativeTargets(): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(
    NATIVE_TARGET_STORAGE_KEY,
    JSON.stringify([...nativeTargets.entries()]),
  )
}

function parseNotificationTarget(value: unknown): TaskNotificationTarget | null {
  if (typeof value === 'string') {
    try {
      return parseNotificationTarget(JSON.parse(value))
    } catch {
      return null
    }
  }
  if (!value || typeof value !== 'object') return null
  const target = value as Partial<TaskNotificationTarget>
  return ['conversation', 'agentGroup', 'scheduler'].includes(
    String(target.kind || ''),
  )
    ? target as TaskNotificationTarget
    : null
}
