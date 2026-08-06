<template>
  <div class="factory-view">
    <div class="chat-container">
      <!-- 消息列表 -->
      <div class="messages-section">
        <n-scrollbar ref="scrollbarRef" class="messages-scrollbar">
          <div class="messages-list">
            <div
              v-if="
                timelineItems.length === 0
                && thinkingMessages.length === 0
                && activeSchedulerRunCards.length === 0
                && !hasActiveStreams
              "
              class="chat-empty"
              role="status"
              :aria-label="t('factory.emptyChat')"
            >
              <svg class="chat-empty-icon" viewBox="0 0 136 112" role="img" aria-hidden="true">
                <path class="chat-empty-bubble chat-empty-bubble-back" d="M22 27.5C22 16.7 30.7 8 41.5 8h52C104.3 8 113 16.7 113 27.5v24C113 62.3 104.3 71 93.5 71H65l-15.8 17.5c-2.5 2.8-7.2 1-7.2-2.7V71h-.5C30.7 71 22 62.3 22 51.5v-24Z" />
                <path class="chat-empty-bubble chat-empty-bubble-front" d="M8 45.5C8 34.7 16.7 26 27.5 26h52C90.3 26 99 34.7 99 45.5v24C99 80.3 90.3 89 79.5 89H51L35.2 106.5c-2.5 2.8-7.2 1-7.2-2.7V89h-.5C16.7 89 8 80.3 8 69.5v-24Z" />
                <path class="chat-empty-line" d="M29 51h38M29 63h25" />
                <circle class="chat-empty-dot" cx="77" cy="63" r="2.2" />
              </svg>
            </div>

            <template v-for="item in timelineItems" :key="`${item.kind}-${item.id}`">
              <MessageItem
                :message="item.message"
                :streaming="isMessageStreaming(item.message.streamId)"
                quoteable
                :tip-context="tipContextFor(item.message)"
                :workspace-context="messageWorkspaceContext"
                @quote="addMessageReference"
              />
            </template>

            <SchedulerRunStatusCard
              v-for="notice in activeSchedulerRunCards"
              :key="`scheduler-${notice.id}`"
              :notice="notice"
              dismissible
              @details="uiStore.openSchedulerActivityDrawer"
              @dismiss="runtimeStore.dismissSchedulerNoticeFromConversation(notice.id)"
            />

            <MessageItem
              v-for="message in thinkingMessages"
              :key="message.id"
              :message="message"
              thinking
              :workspace-context="messageWorkspaceContext"
            />
          </div>
        </n-scrollbar>
      </div>

      <ToolApprovalPanel
        v-if="hasApprovalRequests"
        class="approval-section"
      />
      <PublishConfirmationPanel
        v-if="runtimeStore.isPublishConfirmationPending"
        class="approval-section"
      />
      <ResourceRequestPanel
        v-if="resourceRequests.length && resourceWorkspaceId"
        :workspace-id="resourceWorkspaceId"
        :requests="resourceRequests"
        @configured="handleResourceConfigured"
        @skip="handleResourceSkipped"
      />

      <!-- 输入区 -->
      <div class="input-section">
        <MessageInput
          ref="inputRef"
          :placeholder="inputPlaceholder"
          :disabled="inputDisabled"
          :disabled-hint="modelConfigurationMissing ? t('chat.configureModelLink') : ''"
          :disabled-hint-route="{ name: 'ModelPool' }"
          :is-running="runtimeStore.hasActiveRun"
          :queued-count="runtimeStore.queuedRequestCount"
          :queued-messages="runtimeStore.queuedMessages"
          attachments-enabled
          model-selector-enabled
          :model-options="runtimeMainModelOptions"
          :selected-model-profile-id="selectedMainModelProfileId"
          reasoning-control-enabled
          :reasoning-intensity="reasoningIntensity"
          :reference-scope="referenceScope"
          @update:selected-model-profile-id="setSelectedMainModelProfileId"
          @update:reasoning-intensity="setReasoningIntensity"
          @send="handleSend"
          @cancel="handleCancel"
          @steer="handleSteer"
        >
          <template #before-send><ContextProgressControl /></template>
        </MessageInput>
      </div>
    </div>
    <ConversationFloatingDock
      :session-id="backgroundTaskSessionId"
      @request-new-agent-session="requestNewAgentSession"
    />
    <NewAgentSessionDialog
      v-if="pendingWorkspaceAction"
      :show="true"
      :package-id="pendingWorkspaceAction.packageId"
      :initial-workspace-id="pendingWorkspaceAction.initialWorkspaceId"
      @update:show="handleWorkspaceDialogVisibility"
      @create="completeWorkspaceSelection"
    />
    <TipPanel v-if="tipScopeId" :scope-type="tipScopeType" :scope-id="tipScopeId" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NScrollbar } from 'naive-ui'
import { useRuntimeStore } from '@/stores/runtime'
import { useAgentStore } from '@/stores/agent'
import { useUiStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'
import { useFactoryConversation } from '@/composables/factory/useFactoryConversation'
import { useFactoryMessageProjection } from '@/composables/factory/useFactoryMessageProjection'
import { useCommand } from '@/composables/useCommand'
import MessageItem from '@/components/chat/MessageItem.vue'
import MessageInput from '@/components/chat/MessageInput.vue'
import ToolApprovalPanel from '@/components/chat/ToolApprovalPanel.vue'
import PublishConfirmationPanel from '@/components/chat/PublishConfirmationPanel.vue'
import ResourceRequestPanel from '@/components/chat/ResourceRequestPanel.vue'
import SchedulerRunStatusCard from '@/components/scheduler/SchedulerRunStatusCard.vue'
import ConversationFloatingDock from '@/components/chat/ConversationFloatingDock.vue'
import NewAgentSessionDialog from '@/components/agent/NewAgentSessionDialog.vue'
import ContextProgressControl from '@/components/chat/ContextProgressControl.vue'
import type { RuntimeAttachmentInput } from '@/types/protocol'
import type { TranscriptItem } from '@/types/protocol'
import { useContextReferenceStore } from '@/stores/contextReferences'
import { messageContextReference } from '@/utils/contextReferences'
import TipPanel from '@/components/chat/TipPanel.vue'
import type { TipMessageContext } from '@/stores/tips'
import { useResourceContext } from '@/composables/useResourceContext'
import { useWorkspaceStore } from '@/stores/workspace'
import {
  isAgentSessionsLanding as routeIsAgentSessionsLanding,
  isNewAgentWorkspaceSelectionConfirmed,
} from '@/utils/agentSessionRoute'
import { SYSTEM_CHAT_PACKAGE_ID } from '@/utils/resourceScope'
import { agentPackageConversationScope } from '@/stores/runtime/scopes'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'

const runtimeStore = useRuntimeStore()
const agentStore = useAgentStore()
const uiStore = useUiStore()
const commands = useCommand()
const workspaceStore = useWorkspaceStore()
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const scrollbarRef = ref()
const inputRef = ref()
const referenceStore = useContextReferenceStore()
const resourceContext = useResourceContext()
const { startNewAgentSession } = useAgentSessionNavigation()
type PendingWorkspaceAction = {
  kind: 'new_session'
  packageId: string
  initialWorkspaceId: string | null
} | {
  kind: 'first_message'
  packageId: string
  initialWorkspaceId: null
  message: string
  attachments: RuntimeAttachmentInput[]
}
const pendingWorkspaceAction = ref<PendingWorkspaceAction | null>(null)
const messageWorkspaceContext = computed(() => resourceContext.workspaceContext.value)
const referenceScope = computed(() => [
  'factory',
  runtimeStore.currentMode,
  runtimeStore.activeFactorySessionId || runtimeStore.activeAgentSessionId || 'new',
].join(':'))
const tipScope = computed(() => {
  if (runtimeStore.activeAgentSessionId) {
    return { scopeType: 'agent-session', scopeId: runtimeStore.activeAgentSessionId }
  }
  if (runtimeStore.activeFactorySessionId) {
    return { scopeType: 'factory-session', scopeId: runtimeStore.activeFactorySessionId }
  }
  return null
})
const tipScopeType = computed(() => tipScope.value?.scopeType || 'factory-session')
const tipScopeId = computed(() => tipScope.value?.scopeId || '')

const {
  inputPlaceholder,
  inputDisabled,
  modelConfigurationMissing,
  loadRuntimeMainModelProfiles,
  runtimeMainModelOptions,
  reasoningIntensity,
  selectedMainModelProfileId,
  setSelectedMainModelProfileId,
  setReasoningIntensity,
  cancelRequest,
  sendMessage,
  steerQueuedRequest,
} = useFactoryConversation()

const {
  activeStreamContentKey,
  hasActiveStreams,
  hasApprovalRequests,
  isMessageStreaming,
  thinkingMessages,
  timelineItems,
} = useFactoryMessageProjection()

const resourceRequests = computed(() => {
  const values = runtimeStore.pendingInterrupt?.payload?.resource_requests
  return Array.isArray(values) ? values.filter((item): item is {
    resource_id: string
    description?: string
    secret?: boolean
    required?: boolean
    value_schema?: Record<string, unknown>
    secret_fields?: string[]
  } => Boolean(item && typeof item.resource_id === 'string')) : []
})

const resourceWorkspaceId = computed(() => String(
  runtimeStore.pendingInterrupt?.payload?.workspace_id
    || resourceContext.workspaceContext.value.createAgentSessionId
    || '',
).trim())

const backgroundTaskSessionId = computed(() => (
  runtimeStore.activeAgentSessionId || runtimeStore.activeFactorySessionId || null
))

const activeSchedulerRunCards = computed(() => {
  const scope = runtimeStore.activeConversationScope
  if (!scope) return []
  return runtimeStore.schedulerRunNotices.filter((notice) => notice.conversationScope === scope)
})

function handleSend(message: string, attachments: RuntimeAttachmentInput[]) {
  const packageId = agentStore.activeChatPackageId
  const routedWorkspaceSelection = newAgentWorkspaceSelectionFromRoute()
  if (
    packageId
    && !agentStore.selectedSessionId
    && !runtimeStore.activeWorkspaceId
    && !routedWorkspaceSelection.confirmed
  ) {
    pendingWorkspaceAction.value = {
      kind: 'first_message',
      packageId,
      initialWorkspaceId: null,
      message,
      attachments,
    }
    return
  }
  sendAndFollow(
    message,
    attachments,
    routedWorkspaceSelection.confirmed ? routedWorkspaceSelection.workspaceId : undefined,
  )
}

function requestNewAgentSession(packageId: string, initialWorkspaceId: string | null) {
  pendingWorkspaceAction.value = {
    kind: 'new_session',
    packageId,
    initialWorkspaceId,
  }
}

function handleWorkspaceDialogVisibility(show: boolean) {
  if (show) return
  restorePendingDraft()
  pendingWorkspaceAction.value = null
}

async function completeWorkspaceSelection(workspaceId: string | null) {
  const action = pendingWorkspaceAction.value
  if (!action) return
  pendingWorkspaceAction.value = null
  await startNewAgentSession(action.packageId, {
    workspaceId,
    workspaceSelectionConfirmed: true,
  })
  if (action.kind === 'first_message' && !sendAndFollow(action.message, action.attachments, workspaceId)) {
    inputRef.value?.restoreDraft(action.message, action.attachments)
  }
}

function restorePendingDraft() {
  const action = pendingWorkspaceAction.value
  if (action?.kind === 'first_message') {
    inputRef.value?.restoreDraft(action.message, action.attachments)
  }
}

function sendAndFollow(
  message: string,
  attachments: RuntimeAttachmentInput[],
  workspaceId?: string | null,
): boolean {
  if (!sendMessage(message, attachments, workspaceId)) return false
  nextTick(() => {
    scrollToBottom('smooth')
  })
  return true
}

function handleCancel() {
  cancelRequest()
}

function handleSteer(requestId: string) {
  steerQueuedRequest(requestId)
}

function addMessageReference(message: TranscriptItem) {
  referenceStore.add(messageContextReference(message), referenceScope.value)
  nextTick(() => inputRef.value?.focus())
}

function tipContextFor(message: TranscriptItem): Omit<TipMessageContext, 'sourceMessageId' | 'sourceRole' | 'sourceContent'> | null {
  if (!tipScopeId.value || message.role !== 'assistant') return null
  const modelProfileId = String(message.metadata?.model_profile_id || '').trim() || null
  const messageReasoningIntensity = message.metadata?.reasoning_intensity
  return {
    scopeType: tipScopeType.value,
    scopeId: tipScopeId.value,
    agentPackageId: String(message.metadata?.package_id || agentStore.activeChatPackageId || 'factory_chat'),
    modelProfileId,
    reasoningIntensity: typeof messageReasoningIntensity === 'number' ? messageReasoningIntensity : null,
  }
}

function handleResourceConfigured(resourceIds: string[]) {
  handleSend(`运行时资源 ${resourceIds.join(', ')} 已安全配置。`, [])
}

function handleResourceSkipped() {
  handleSend('该运行时资源暂不配置，请继续完成可实现部分；发布后可在包详情中填写。', [])
}

function scrollToBottom(behavior: ScrollBehavior = 'auto') {
  scrollbarRef.value?.scrollTo({ position: 'bottom', behavior })
}

function scrollContainer(): HTMLElement | null {
  const scrollbar = scrollbarRef.value as any
  return scrollbar?.scrollbarInstRef?.containerRef
    || scrollbar?.containerRef
    || scrollbar?.$el?.querySelector?.('.n-scrollbar-container')
    || null
}

function isNearBottom(): boolean {
  const container = scrollContainer()
  if (!container) return true
  return container.scrollHeight - container.scrollTop - container.clientHeight < 96
}

function followBottomIfNeeded() {
  const shouldFollow = isNearBottom()
  nextTick(() => {
    if (shouldFollow) scrollToBottom()
  })
}

// 监听消息变化，自动滚动
watch(
  () => runtimeStore.transcript.length,
  followBottomIfNeeded,
)

watch(
  () => runtimeStore.tools.map((tool) => `${tool.activityKey}:${tool.status}:${tool.timestamp}`).join('|'),
  followBottomIfNeeded,
)

watch(
  () => activeSchedulerRunCards.value.map((notice) => `${notice.id}:${notice.status}`).join('|'),
  followBottomIfNeeded,
)

// 监听流式输出，自动滚动
watch(
  () => activeStreamContentKey.value,
  followBottomIfNeeded,
)

let routeActivationVersion = 0

onMounted(async () => {
  // Model availability controls the input state and must not wait for session restoration.
  void loadRuntimeMainModelProfiles()
  await activateCurrentRoute()

  if (!route.meta.showcaseMode) {
    nextTick(() => {
      inputRef.value?.focus()
    })
  }
})

watch(
  () => route.fullPath,
  () => void activateCurrentRoute(),
)

watch(
  () => `${agentStore.activeChatPackageId || ''}:${runtimeStore.activeAgentSessionId || ''}`,
  () => {
    const packageId = agentStore.activeChatPackageId
    const sessionId = runtimeStore.activeAgentSessionId
    if (route.name !== 'Factory' || !packageId) return
    if (
      !sessionId
      && agentStore.selectedSessionId === null
      && routeQueryText(route.query.package_id) === packageId
      && Boolean(routeQueryText(route.query.session_id))
      && runtimeStore.currentMode === 'agent_package'
    ) {
      void router.replace({ name: 'Factory', query: { package_id: packageId, new: '1' } })
      return
    }
    if (!sessionId) return
    if (routeQueryText(route.query.package_id) !== packageId || routeQueryText(route.query.new) !== '1') return
    if (
      routeQueryText(route.query.session_id) === sessionId
    ) return
    void router.replace({ name: 'Factory', query: { package_id: packageId, session_id: sessionId } })
  },
)

async function activateCurrentRoute(): Promise<void> {
  const version = ++routeActivationVersion
  await openRoutedAgentSession(version)
}

async function openRoutedAgentSession(version: number): Promise<boolean> {
  if (route.name !== 'Factory') return false
  if (routeIsAgentSessionsLanding(route.query)) {
    agentStore.leaveAgentChat()
    runtimeStore.showEmptyAgentPackageSession()
    if (agentStore.agentPackages.length === 0) commands.listAgentPackages()
    return true
  }
  const packageId = routeQueryText(route.query.package_id)
  const sessionId = routeQueryText(route.query.session_id)
  if (!packageId) {
    await router.replace({
      name: 'Factory',
      query: { package_id: SYSTEM_CHAT_PACKAGE_ID },
    })
    return true
  }
  activateAgentWorkspace()
  if (!sessionId && routeQueryText(route.query.new) === '1') {
    const workspaceId = routeQueryText(route.query.workspace_id)
    if (emptyAgentRouteIsActive(packageId, workspaceId)) return true
    agentStore.enterAgentChat(packageId, null)
    runtimeStore.showEmptyAgentPackageSession(packageId, workspaceId)
    await commands.selectAgentPackage(packageId, 'run')
    return true
  }
  if (!sessionId) {
    const rememberedSessionId = agentStore.lastAgentSession?.packageId === packageId
      ? agentStore.lastAgentSession.sessionId
      : null
    agentStore.enterAgentChat(packageId, null)
    runtimeStore.showEmptyAgentPackageSession(packageId)
    await commands.listAgentPackageSessions(packageId)
    if (version !== routeActivationVersion || routeQueryText(route.query.package_id) !== packageId) return true
    const preferred = preferredSessionForPackage(packageId, rememberedSessionId)
    await router.replace({
      name: 'Factory',
      query: preferred
        ? { package_id: packageId, session_id: preferred.session_id }
        : { package_id: packageId, new: '1' },
    })
    return true
  }
  const routedScope = agentPackageConversationScope(packageId, sessionId)
  if (
    agentStore.activeChatPackageId === packageId
    && runtimeStore.currentMode === 'agent_package'
    && runtimeStore.activeAgentSessionId === sessionId
    && runtimeStore.activeConversationScope === routedScope
  ) {
    return true
  }
  agentStore.enterAgentChat(packageId, sessionId)
  runtimeStore.expectAgentPackageSession(packageId, sessionId)
  await commands.selectAgentPackage(packageId, 'run')
  if (version !== routeActivationVersion || !routeMatchesAgentSession(packageId, sessionId)) return true
  await commands.loadAgentPackageSession(
    packageId,
    sessionId,
  )
  return true
}

function activateAgentWorkspace(): void {
  workspaceStore.setScope('workdir')
}

function preferredSessionForPackage(packageId: string, rememberedSessionId: string | null) {
  const sessions = agentStore.agentSessions
    .filter((session) => session.package_id === packageId)
    .sort((left, right) => (right.updated_at || right.created_at).localeCompare(left.updated_at || left.created_at))
  if (rememberedSessionId) {
    const preferred = sessions.find((session) => session.session_id === rememberedSessionId)
    if (preferred) return preferred
  }
  return sessions[0] || null
}

function routeMatchesAgentSession(packageId: string, sessionId: string): boolean {
  return route.name === 'Factory'
    && routeQueryText(route.query.package_id) === packageId
    && routeQueryText(route.query.session_id) === sessionId
}

function emptyAgentRouteIsActive(packageId: string, workspaceId: string | null): boolean {
  return agentStore.activeChatPackageId === packageId
    && agentStore.selectedSessionId === null
    && runtimeStore.activeAgentSessionId === null
    && runtimeStore.currentMode === 'agent_package'
    && runtimeStore.activeWorkspaceId === workspaceId
}

function routeQueryText(value: unknown): string | null {
  const raw = Array.isArray(value) ? value[0] : value
  const text = String(raw || '').trim()
  return text || null
}

function newAgentWorkspaceSelectionFromRoute(): { confirmed: boolean; workspaceId: string | null } {
  const confirmed = route.name === 'Factory'
    && routeQueryText(route.query.new) === '1'
    && isNewAgentWorkspaceSelectionConfirmed(route.query)
  return {
    confirmed,
    workspaceId: confirmed ? routeQueryText(route.query.workspace_id) : null,
  }
}
</script>

<style scoped>
.factory-view {
  height: 100%;
  display: flex;
  flex-direction: row;
  background: var(--app-surface);
  position: relative;
}

.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: var(--app-space-xl) clamp(54px, 6vw, 80px) var(--app-space-lg);
  max-width: var(--app-chat-max-width);
  margin: 0 auto;
  width: min(100%, var(--app-chat-max-width));
  transition: width .24s var(--app-transition-spring), max-width .24s var(--app-transition-spring);
}

.messages-section {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.messages-scrollbar {
  height: 100%;
}

.messages-list {
  padding: var(--app-space-lg) var(--app-space-lg) var(--app-space-xxl);
}

.chat-empty {
  display: grid;
  place-items: center;
  margin-top: 15vh;
  animation: app-fade-in-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.chat-empty-icon {
  width: 112px;
  height: auto;
  overflow: visible;
  color: var(--app-text);
  opacity: 0.72;
  animation: empty-conversation-breathe 3.2s ease-in-out infinite;
}

.chat-empty-bubble {
  fill: var(--app-surface);
  stroke: currentColor;
  stroke-linejoin: round;
  stroke-width: 2.5;
}

.chat-empty-bubble-back {
  opacity: 0.32;
}

.chat-empty-bubble-front {
  opacity: 0.92;
}

.chat-empty-line {
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-width: 3;
}

.chat-empty-dot {
  fill: currentColor;
}

@keyframes empty-conversation-breathe {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-3px); }
}

.approval-section {
  margin-top: var(--app-space-md);
}

.input-section {
  margin-top: var(--app-space-lg);
  padding-top: var(--app-space-sm);
}

/* 窄屏适配 */
@media (max-width: 768px) {
  .chat-container {
    padding: var(--app-space-md);
  }
}

/* 超宽屏（>1600）保留呼吸感，稍微放宽 */
@media (min-width: 1600px) {
  .chat-container {
    max-width: 1100px;
  }
}
</style>
