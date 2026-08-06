<template>
  <div class="agent-session-panel">
    <div class="panel-header">
      <div class="header-title">
        <n-text strong>{{ t('agentSessions.title') }}</n-text>
        <n-text depth="3" class="package-name">
          {{ packageTitle }}
        </n-text>
      </div>
      <div class="header-actions">
        <n-button size="small" type="primary" @click="requestNewSession">
          {{ t('agentSessions.newChat') }}
        </n-button>
        <n-button size="small" @click="refreshSessions">
          <template #icon>
            <n-icon><Refresh /></n-icon>
          </template>
        </n-button>
      </div>
    </div>

    <div class="panel-search">
      <n-input
        v-model:value="searchQuery"
        :placeholder="t('agentSessions.searchPlaceholder')"
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
          :class="{ active: session.session_id === agentStore.selectedSessionId }"
          @click="enterExistingSession(session.session_id)"
        >
          <div class="session-item">
            <div class="session-title-row">
              <div class="session-title">
                {{ session.display_title || session.first_user_input || t('sessions.newSession') }}
              </div>
              <n-button
                size="tiny"
                quaternary
                circle
                :aria-label="t('agentSessions.delete')"
                @click.stop="confirmDeleteSession(session)"
              >
                <template #icon>
                  <n-icon><TrashOutline /></n-icon>
                </template>
              </n-button>
            </div>
            <div class="session-meta">
              <n-tag size="tiny" type="success">
                {{ t('agentSessions.tag') }}
              </n-tag>
              <n-tag v-if="session.workspace" size="tiny" :bordered="false">
                {{
                  session.workspace.mode === 'project'
                    ? t('sessions.sharedWorkspace')
                    : t('sessions.isolatedWorkspace')
                }}
              </n-tag>
              <n-text depth="3" class="meta-text">
                {{ formatTime(session.updated_at) }}
              </n-text>
            </div>
            <n-text
              v-if="session.workspace?.workdir_root"
              depth="3"
              class="workspace-path"
              :title="session.workspace.workdir_root"
            >
              {{ session.workspace.workdir_root }}
            </n-text>
            <div class="session-stats">
              <n-text depth="3" class="meta-text">
                <n-icon size="12">
                  <ChatbubbleEllipses />
                </n-icon>
                {{ t('sessions.turns', { count: session.turn_count }) }}
              </n-text>
            </div>
          </div>
        </n-list-item>
      </n-list>

      <n-empty
        v-if="filteredSessions.length === 0"
        :description="t('agentSessions.empty')"
        size="small"
        style="margin-top: 40px"
      />
    </n-scrollbar>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NEmpty, NIcon, NInput, NList, NListItem, NScrollbar, NTag, NText, useDialog } from 'naive-ui'
import { ChatbubbleEllipses, Refresh, Search, TrashOutline } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import { useAgentStore } from '@/stores/agent'
import { useCommand } from '@/composables/useCommand'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'

const props = defineProps<{
  packageId: string
}>()
const emit = defineEmits<{
  requestNewSession: [packageId: string, initialWorkspaceId: string | null]
}>()

const agentStore = useAgentStore()
const commands = useCommand()
const { openAgentSession } = useAgentSessionNavigation()
const { locale, t } = useI18n()
const searchQuery = ref('')
const dialog = useDialog()

const currentPackage = computed(() => {
  return agentStore.agentPackages.find((pkg) => pkg.package_id === props.packageId) || null
})

const packageTitle = computed(() => {
  const pkg = currentPackage.value
  return pkg?.agent_name || pkg?.name || t('common.unnamedAgent')
})

const filteredSessions = computed(() => {
  if (!searchQuery.value) return agentStore.agentSessions
  const query = searchQuery.value.toLowerCase()
  return agentStore.agentSessions.filter((session) => (
    session.display_title?.toLowerCase().includes(query) ||
    session.first_user_input?.toLowerCase().includes(query)
  ))
})

function refreshSessions() {
  commands.listAgentPackageSessions(props.packageId)
}

function requestNewSession() {
  emit('requestNewSession', props.packageId, null)
}

function enterExistingSession(sessionId: string) {
  const session = agentStore.agentSessions.find((item) => item.session_id === sessionId)
  if (session) void openAgentSession({ ...session })
}

function confirmDeleteSession(session: { session_id: string; display_title: string | null; first_user_input: string | null }) {
  const title = session.display_title || session.first_user_input || t('sessions.newSession')
  dialog.warning({
    title: t('agentSessions.deleteTitle'),
    content: t('agentSessions.deleteContent', { title }),
    positiveText: t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: () => {
      void commands.deleteAgentPackageSession(props.packageId, session.session_id)
    },
  })
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

watch(
  () => props.packageId,
  () => {
    refreshSessions()
  }
)
</script>

<style scoped>
.agent-session-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--app-surface);
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  padding: var(--app-space-md) var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
}

.header-title {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xxs);
}

.package-name {
  font-size: var(--app-font-sm);
  color: var(--app-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  flex-shrink: 0;
}

.panel-search {
  padding: var(--app-space-md) var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
}

.session-list {
  flex: 1;
  min-height: 0;
}

.agent-session-panel :deep(.n-list-item) {
  transition: background-color var(--app-transition-fast);
}

.agent-session-panel :deep(.n-list-item__main) {
  min-width: 0;
  width: 100%;
}

.agent-session-panel :deep(.n-list-item.active) {
  background: var(--app-surface-pressed);
  position: relative;
}

.agent-session-panel :deep(.n-list-item.active)::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: var(--app-radius-pill);
  background: var(--app-text);
}

.session-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  min-width: 0;
}

.session-title-row {
  display: flex;
  align-items: flex-start;
  gap: var(--app-space-xs);
}

.session-title {
  font-size: 14px;
  font-weight: 500;
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

.session-meta,
.session-stats {
  display: flex;
  align-items: center;
  gap: 8px;
}

.workspace-path {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
}

.meta-text {
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
</style>
