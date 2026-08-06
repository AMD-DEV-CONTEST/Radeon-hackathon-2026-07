<template>
  <div class="session-panel">
    <div class="sidebar-header">
      <n-text strong>{{ panelTitle }}</n-text>
      <n-button
        v-if="activeAgentPackageId"
        size="small"
        :disabled="!canStartNewConversationSession"
        @click="openNewSessionDialog"
      >
          <template #icon>
            <n-icon><Add /></n-icon>
          </template>
          {{ t('sessions.new') }}
      </n-button>
      <n-button v-else size="small" :disabled="!canStartNewConversationSession" @click="handleNewSession">
        <template #icon>
          <n-icon><Add /></n-icon>
        </template>
        {{ t('sessions.new') }}
      </n-button>
    </div>

    <div class="sidebar-search">
      <n-input
        v-model:value="searchQuery"
        :placeholder="t('common.searchSessions')"
        clearable
      >
        <template #prefix>
          <n-icon><Search /></n-icon>
        </template>
      </n-input>
    </div>

    <n-scrollbar class="session-list">
      <n-list hoverable clickable>
        <n-list-item
          v-for="session in filteredSessions"
          :key="session.session_id"
          :class="{ active: isActiveSession(session) }"
          @click="handleSelectSession(session)"
        >
          <div class="session-item">
            <div class="session-title-row">
              <div class="session-title">
                {{ sessionTitle(session) }}
              </div>
              <n-button
                size="tiny"
                quaternary
                circle
                :aria-label="t('sessions.delete')"
                @click.stop="confirmDeleteSession(session)"
              >
                <template #icon>
                  <n-icon><TrashOutline /></n-icon>
                </template>
              </n-button>
            </div>
            <div class="session-meta">
              <n-tag size="tiny" :type="modeTagType(sessionMode(session))">
                {{ modeLabel(sessionMode(session)) }}
              </n-tag>
              <n-tag
                v-if="sessionWorkspaceLabel(session)"
                size="tiny"
                :bordered="false"
              >
                {{ sessionWorkspaceLabel(session) }}
              </n-tag>
              <n-text depth="3" style="font-size: 11px">
                {{ formatTime(session.updated_at) }}
              </n-text>
            </div>
            <n-text
              v-if="sessionWorkspacePath(session)"
              depth="3"
              class="session-workspace-path"
              :title="sessionWorkspacePath(session)"
            >
              {{ sessionWorkspacePath(session) }}
            </n-text>
            <div class="session-stats">
              <n-text depth="3" style="font-size: 11px">
                <n-icon size="12">
                  <ChatbubbleEllipses />
                </n-icon>
                {{ t('sessions.turns', { count: sessionTurnCount(session) }) }}
              </n-text>
            </div>
          </div>
        </n-list-item>
      </n-list>

      <n-empty
        v-if="filteredSessions.length === 0"
        :description="t('sessions.empty')"
        size="small"
        class="sessions-empty"
      />
    </n-scrollbar>

  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NEmpty, NIcon, NInput, NList, NListItem, NScrollbar, NTag, NText, useDialog } from 'naive-ui'
import { Add, ChatbubbleEllipses, Search, TrashOutline } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import { useSessionStore } from '@/stores/session'
import { useRuntimeStore } from '@/stores/runtime'
import { useAgentStore } from '@/stores/agent'
import { useCommand } from '@/composables/useCommand'
import { useConversationSessionNavigation } from '@/composables/useConversationSessionNavigation'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'
import type { SessionView } from '@/stores/session'
import type { AgentSessionView } from '@/stores/agent'
import type { WorkspaceProjectView } from '@/api/workspace'

const props = withDefaults(
  defineProps<{
    title?: string
  }>(),
  {
    title: '',
  }
)
const emit = defineEmits<{
  requestNewAgentSession: [packageId: string, initialWorkspaceId: string | null]
}>()

const sessionStore = useSessionStore()
const runtimeStore = useRuntimeStore()
const agentStore = useAgentStore()
const commands = useCommand()
const { canStartNewConversationSession, startNewConversationSession } = useConversationSessionNavigation()
const { openAgentSession } = useAgentSessionNavigation()
const { locale, t } = useI18n()
const searchQuery = ref('')
const dialog = useDialog()

const panelTitle = computed(() => props.title || t('sessions.main'))

const activeSessionMode = computed<'create_agent' | 'evolve_agent' | null>(() => {
  if (runtimeStore.currentMode === 'create_agent') return 'create_agent'
  if (runtimeStore.currentMode === 'evolve_agent') return 'evolve_agent'
  return null
})
const activeAgentPackageId = computed(() => agentStore.activeChatPackageId)
const filteredSessions = computed(() => {
  const query = searchQuery.value.toLowerCase()
  const sessions: ConversationSession[] = activeAgentPackageId.value
    ? agentStore.agentSessions.filter((session) => session.package_id === activeAgentPackageId.value)
    : activeSessionMode.value
      ? sessionStore.sessions
      : []
  return sessions.filter((session) => {
    if (!sessionBelongsToActiveMode(session)) return false
    if (!query) return true
    return (
      sessionTitle(session).toLowerCase().includes(query) ||
      Boolean(session.first_user_input?.toLowerCase().includes(query))
    )
  })
})

function handleNewSession() {
  void startNewConversationSession()
}

function openNewSessionDialog() {
  const packageId = activeAgentPackageId.value
  if (!packageId) return
  emit('requestNewAgentSession', packageId, runtimeStore.activeWorkspaceId)
}

type ConversationSession = SessionView | AgentSessionView

function handleSelectSession(session: ConversationSession) {
  if (isAgentSession(session)) {
    void openAgentSession(session)
    return
  }
  if (activeSessionMode.value) {
    commands.switchSession(session.session_id, activeSessionMode.value)
  }
}

function confirmDeleteSession(session: ConversationSession) {
  dialog.warning({
    title: t('sessions.deleteTitle'),
    content: t('sessions.deleteContent', { title: sessionTitle(session) }),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: () => {
      if (isAgentSession(session)) {
        void commands.deleteAgentPackageSession(session.package_id, session.session_id)
        return
      }
      if (activeSessionMode.value) {
        commands.deleteSession(session.session_id, activeSessionMode.value)
      }
    },
  })
}

function sessionBelongsToActiveMode(session: ConversationSession): boolean {
  if (isAgentSession(session)) {
    return session.package_id === activeAgentPackageId.value
  }
  if (!activeSessionMode.value) return false
  if (activeSessionMode.value === 'evolve_agent') {
    const packageId = agentStore.selectedPackageId
    if (packageId && session.evolve_agent_package_id !== packageId) return false
  }
  if (session.session_id === sessionStore.currentSessionId && runtimeStore.currentMode === activeSessionMode.value) {
    return true
  }
  if (session.current_mode === activeSessionMode.value) return true
  if (sessionTurnCount(session) > 0) return true
  if (activeSessionMode.value === 'create_agent') return Boolean(session.create_agent_session_id)
  return Boolean(session.evolve_agent_package_id)
}

function sessionTurnCount(session: ConversationSession): number {
  if (isAgentSession(session)) return session.turn_count
  const modeCounts = session.mode_turn_counts || {}
  const count = activeSessionMode.value ? modeCounts[activeSessionMode.value] : undefined
  if (typeof count === 'number') return count
  if (activeSessionMode.value === 'create_agent') return session.create_agent_turn_count
  if (activeSessionMode.value === 'evolve_agent') return session.evolve_agent_turn_count || 0
  return 0
}

function sessionTitle(session: ConversationSession): string {
  if (isAgentSession(session)) {
    return session.display_title || session.first_user_input || t('sessions.newSession')
  }
  const modeTitle = activeSessionMode.value ? session.mode_titles?.[activeSessionMode.value] : null
  return modeTitle || session.display_title || session.first_user_input || t('sessions.newSession')
}

function sessionWorkspace(session: ConversationSession): WorkspaceProjectView | null {
  if (!isAgentSession(session)) return null
  if (session.workspace) {
    return {
      ...session.workspace,
      owner_package_id: session.package_id,
      archived: false,
      created_at: session.created_at,
      updated_at: session.updated_at,
    }
  }
  return null
}

function sessionWorkspaceLabel(session: ConversationSession): string {
  const workspace = sessionWorkspace(session)
  if (!workspace) return ''
  const kind = workspace.mode === 'project'
    ? t('sessions.sharedWorkspace')
    : t('sessions.isolatedWorkspace')
  return `${kind} · ${workspace.title}`
}

function sessionWorkspacePath(session: ConversationSession): string {
  return sessionWorkspace(session)?.workdir_root || ''
}

function isAgentSession(session: ConversationSession): session is AgentSessionView {
  return typeof (session as AgentSessionView).package_id === 'string'
}

function isActiveSession(session: ConversationSession): boolean {
  return isAgentSession(session)
    ? session.session_id === agentStore.selectedSessionId
    : session.session_id === sessionStore.currentSessionId
}

function sessionMode(session: ConversationSession): string {
  return isAgentSession(session) ? 'agent_package' : activeSessionMode.value || 'agent_package'
}

function modeLabel(mode: string): string {
  const labels: Record<string, string> = {
    create_agent: t('sessions.modeCreate'),
    evolve_agent: t('sessions.modeEvolve'),
    agent_package: t('sessions.modeAgent'),
  }
  return labels[mode] || mode
}

function modeTagType(mode: string): 'default' | 'success' | 'info' | 'warning' {
  const types: Record<string, any> = {
    create_agent: 'info',
    evolve_agent: 'warning',
    agent_package: 'success',
  }
  return types[mode] || 'default'
}

function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  if (diff < 3600000) {
    const minutes = Math.floor(diff / 60000)
    return new Intl.RelativeTimeFormat(locale.value, { numeric: 'auto' }).format(-minutes, 'minute')
  }

  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' })
  }

  return date.toLocaleDateString(locale.value, { month: '2-digit', day: '2-digit' })
}

onMounted(() => {
  refreshSessions()
})

watch(activeAgentPackageId, refreshSessions)

function refreshSessions() {
  const packageId = activeAgentPackageId.value
  if (packageId) {
    void commands.listAgentPackageSessions(packageId)
    return
  }
  commands.listSessions()
}

</script>

<style scoped>
.session-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--app-surface);
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--app-space-md) var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
}

.sidebar-search {
  padding: var(--app-space-md) var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
}

.session-list {
  flex: 1;
  min-height: 0;
}

.session-item {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
  padding: var(--app-space-xs) 0;
  width: 100%;
  min-width: 0;
}

.session-title-row {
  display: flex;
  align-items: flex-start;
  gap: var(--app-space-xs);
}

.session-panel :deep(.n-list-item) {
  transition: background-color var(--app-transition-fast);
  border-radius: var(--app-radius-md);
  animation: app-fade-in 0.2s ease both;
}

.session-panel :deep(.n-list-item__main) {
  min-width: 0;
  width: 100%;
}

.session-panel :deep(.n-list-item.active) {
  background: var(--app-surface-pressed);
  position: relative;
}

.session-panel :deep(.n-list-item.active)::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: var(--app-radius-pill);
  background: var(--app-text);
}

.session-title {
  font-size: var(--app-font-lg);
  font-weight: 500;
  color: var(--app-text);
  flex: 1;
  min-width: 0;
  line-height: 1.35;
  overflow-wrap: anywhere;
  word-break: break-word;
  white-space: normal;
}

.session-title-row :deep(.n-button) {
  flex: 0 0 auto;
}

.session-meta {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
}

.session-stats {
  display: flex;
  align-items: center;
  gap: var(--app-space-md);
}

.session-workspace-path {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
}


.session-stats :deep(.n-text) {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-xs);
}

.sessions-empty {
  margin-top: var(--app-space-xxl);
  animation: app-fade-in 0.24s ease both;
}
</style>
