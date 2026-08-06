/**
 * useEventStream Composable
 * 封装 SSE 事件流连接。运行类命令通过 HTTP 发出，实时事件通过这里进入 reducer。
 */

import { ref } from 'vue'
import { EventStreamClient, type ConnectionStatus } from '@/api/events'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import { syncDomainStoresFromRuntime } from '@/stores/runtimeSync'
import { useAgentGroupStore } from '@/stores/agentGroup'
import { useUiStore } from '@/stores/ui'
import type { FactoryFrontendEvent } from '@/types/protocol'
import { agentPackagesApi } from '@/api/agentPackages'
import { postCommand } from '@/api/http'
import { backendUrl } from '@/api/backendUrl'
import { switchSessionCommand } from '@/api/commands'
import {
  captureTaskNotificationEventContext,
  publishTaskNotificationsForEvent,
} from '@/services/taskNotificationEvents'

let client: EventStreamClient | null = null
const status = ref<ConnectionStatus>('disconnected')
let initialized = false

export function applyRuntimeEvent(event: FactoryFrontendEvent): void {
  const notificationContext = captureTaskNotificationEventContext(event)
  if (event.payload?.group_id && event.payload?.group_run_id) {
    useAgentGroupStore().applyRuntimeEvent(event)
    publishTaskNotificationsForEvent(event, notificationContext)
    return
  }
  const runtimeStore = useRuntimeStore()
  runtimeStore.handleEvent(event)
  syncDomainStoresFromRuntime(event)
  publishTaskNotificationsForEvent(event, notificationContext)
  if (event.event_type === 'runtime_ready' && event.payload?.event_replay?.gap === true) {
    void restoreActiveConversation(runtimeStore).catch((error) => {
      console.error('Failed to restore active conversation after an SSE replay gap:', error)
    })
  }
}

async function restoreActiveConversation(runtimeStore: ReturnType<typeof useRuntimeStore>): Promise<void> {
  if (runtimeStore.currentMode === 'agent_package' && runtimeStore.activeAgentSessionId) {
    const packageId = activeAgentPackageId(runtimeStore)
    if (!packageId) return
    const restored = await agentPackagesApi.session(packageId, runtimeStore.activeAgentSessionId)
    applyRuntimeEvent(restored)
    return
  }
  if (
    runtimeStore.activeFactorySessionId
    && ['create_agent', 'evolve_agent'].includes(String(runtimeStore.currentMode || ''))
  ) {
    await postCommand(switchSessionCommand(runtimeStore.activeFactorySessionId, runtimeStore.currentMode))
  }
}

function activeAgentPackageId(runtimeStore: ReturnType<typeof useRuntimeStore>): string | null {
  const selected = String(runtimeStore.selectedAgentPackage?.package_id || '').trim()
  if (selected) return selected
  const scope = String(runtimeStore.activeConversationScope || '')
  const parts = scope.split(':')
  return parts.length === 3 && parts[0] === 'agent_package' ? parts[1] || null : null
}

export function useEventStream() {
  const runtimeStore = useRuntimeStore()
  const uiStore = useUiStore()
  const { t } = useI18n()

  async function connect() {
    if (client) return

    const eventUrl = await backendUrl('/events')
    if (client) return

    client = new EventStreamClient({
      url: eventUrl,
      onEvent: (event) => {
        applyRuntimeEvent(event)
      },
      onStatusChange: (newStatus) => {
        status.value = newStatus
        runtimeStore.connectionStatus = newStatus

        if (newStatus === 'connected') {
          uiStore.addNotification({
            type: 'success',
            title: t('connection.connected'),
            message: t('eventStream.connectedMessage'),
            duration: 3000,
          })
        } else if (newStatus === 'error') {
          uiStore.addNotification({
            type: 'error',
            title: t('connection.error'),
            message: t('eventStream.failedMessage'),
            duration: 5000,
          })
        } else if (newStatus === 'reconnecting') {
          uiStore.addNotification({
            type: 'warning',
            title: t('connection.reconnecting'),
            message: t('eventStream.reconnectingMessage'),
            duration: 3000,
          })
        }
      },
      onError: (error) => {
        console.error('Event stream error:', error)
      },
    })

    client.connect()
    initialized = true
  }

  function disconnect() {
    if (!client) return
    client.disconnect()
    client = null
    initialized = false
  }

  return {
    status,
    initialized,
    connect,
    disconnect,
  }
}
