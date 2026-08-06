import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'
import {
  isAvailableChatModelProfile,
  modelPoolApi,
  resolveRuntimeMainModelProfileId,
  type ModelPoolProfile,
} from '@/api/modelPool'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useRuntimePreferencesStore } from '@/stores/runtimePreferences'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import type { RuntimeAttachmentInput, TranscriptAttachmentView } from '@/types/protocol'
import { isAgentSessionsLanding } from '@/utils/agentSessionRoute'
import { SYSTEM_CHAT_PACKAGE_ID } from '@/utils/resourceScope'

export function useFactoryConversation() {
  const route = useRoute()
  const runtimeStore = useRuntimeStore()
  const agentStore = useAgentStore()
  const uiStore = useUiStore()
  const runtimePreferences = useRuntimePreferencesStore()
  const commands = useCommand()
  const { t } = useI18n()
  const chatModelProfiles = ref<ModelPoolProfile[]>([])
  const modelProfilesLoaded = ref(false)
  const {
    mainModelProfileId: selectedMainModelProfileId,
    reasoningIntensity,
  } = storeToRefs(runtimePreferences)

  const isAgentChatActive = computed(() => Boolean(agentStore.activeChatPackageId))
  const requiresRuntimeMainModel = computed(() => (
    !agentStore.activeChatPackageId || agentStore.activeChatPackageId === SYSTEM_CHAT_PACKAGE_ID
  ))
  const isAgentSessionLanding = computed(() => (
    route.name === 'Factory' && isAgentSessionsLanding(route.query)
  ))
  const runtimeMainModelOptions = computed(() => (
    chatModelProfiles.value.map((profile) => ({
      label: profile.display_name || profile.served_model_name || profile.profile_id,
      value: profile.profile_id,
    }))
  ))
  const inputPlaceholder = computed(() => (
    isAgentSessionLanding.value
      ? t('factory.selectAgentFirst')
      : t('chat.inputPlaceholder')
  ))
  const inputDisabled = computed(() => (
    runtimeStore.isInputLocked
    || runtimeStore.isPublishConfirmationPending
    || chatModelProfiles.value.length === 0
    || (requiresRuntimeMainModel.value && !selectedMainModelProfileId.value)
    || (isAgentSessionLanding.value && !isAgentChatActive.value)
  ))
  const modelConfigurationMissing = computed(() => (
    modelProfilesLoaded.value
    && (
      chatModelProfiles.value.length === 0
      || (requiresRuntimeMainModel.value && !selectedMainModelProfileId.value)
    )
  ))

  async function loadRuntimeMainModelProfiles() {
    try {
      const response = await modelPoolApi.profiles()
      chatModelProfiles.value = response.profiles.filter(isAvailableChatModelProfile)
      const profileId = await resolveRuntimeMainModelProfileId(
        chatModelProfiles.value,
        selectedMainModelProfileId.value,
      )
      setSelectedMainModelProfileId(profileId)
    } catch (error) {
      uiStore.addNotification({
        type: 'warning',
        title: t('modelPool.loadFailedTitle'),
        message: error instanceof Error ? error.message : String(error),
        duration: 3000,
      })
    } finally {
      modelProfilesLoaded.value = true
    }
  }

  function setSelectedMainModelProfileId(profileId: string) {
    runtimePreferences.setMainModelProfileId(profileId)
    const profile = chatModelProfiles.value.find((item) => item.profile_id === profileId)
    if (profile?.capabilities.reasoning_supported === false) {
      runtimePreferences.setReasoningIntensity(null)
    }
  }

  function runtimeModelOptions() {
    const profileId = selectedMainModelProfileId.value.trim()
    return {
      ...(profileId ? { mainModelProfileId: profileId } : {}),
      ...(reasoningIntensity.value !== null ? { reasoningIntensity: reasoningIntensity.value } : {}),
      requestTimeoutSeconds: runtimePreferences.requestTimeoutSeconds,
      maxRetries: runtimePreferences.maxRetries,
      userConfig: {
        max_parallel_sub_agents: runtimePreferences.maxParallelSubAgents,
      },
    }
  }

  function setReasoningIntensity(value: number | null) {
    runtimePreferences.setReasoningIntensity(value)
  }

  function sendMessage(
    message: string,
    attachments: RuntimeAttachmentInput[],
    workspaceId?: string | null,
  ): boolean {
    if (chatModelProfiles.value.length === 0) {
      uiStore.addNotification({
        type: 'warning',
        title: t('chat.modelRequiredTitle'),
        message: t('chat.modelRequiredMessage'),
        duration: 4000,
      })
      return false
    }
    const payloadAttachments = attachments.length > 0 ? attachments : undefined
    const visibleAttachments = attachmentViews(attachments)
    const packageId = agentStore.activeChatPackageId
    if (packageId) {
      const agentSessionId = agentStore.selectedSessionId || undefined
      const newSessionWorkspaceId = workspaceId === undefined
        ? runtimeStore.activeWorkspaceId
        : String(workspaceId || '').trim() || null
      const command = commands.sendAgentPackageMessage(
        packageId,
        message,
        agentSessionId,
        payloadAttachments,
        runtimeModelOptions(),
        undefined,
        agentSessionId ? null : newSessionWorkspaceId,
      )
      runtimeStore.addUserMessage(message, command.request_id, {
        mode: 'agent_package',
        package_id: packageId,
        agent_session_id: agentSessionId || null,
        ...runtimeSelectionMetadata(),
      }, visibleAttachments)
      return true
    }

    if (requiresRuntimeMainModel.value && !selectedMainModelProfileId.value.trim()) {
      uiStore.addNotification({
        type: 'warning',
        title: t('chat.modelRequiredTitle'),
        message: t('chat.modelRequiredMessage'),
        duration: 4000,
      })
      return false
    }

    return false
  }

  function runtimeSelectionMetadata(): Record<string, string | number> {
    const profileId = selectedMainModelProfileId.value.trim()
    return {
      ...(profileId ? { model_profile_id: profileId } : {}),
      ...(reasoningIntensity.value !== null ? { reasoning_intensity: reasoningIntensity.value } : {}),
    }
  }

  function cancelRequest() {
    const requestId = runtimeStore.activeRequestId
    runtimeStore.markActiveRequestStopping(requestId)
    commands.cancelRequest('user_cancelled', requestId)
  }

  function steerQueuedRequest(requestId: string) {
    commands.steerRequest(requestId)
  }

  watch(isAgentChatActive, (active) => {
    if (!active && !selectedMainModelProfileId.value && chatModelProfiles.value.length > 0) {
      void resolveRuntimeMainModelProfileId(chatModelProfiles.value)
        .then(setSelectedMainModelProfileId)
    }
  })

  return {
    isAgentChatActive,
    isAgentSessionLanding,
    inputPlaceholder,
    inputDisabled,
    modelConfigurationMissing,
    cancelRequest,
    loadRuntimeMainModelProfiles,
    runtimeMainModelOptions,
    reasoningIntensity,
    selectedMainModelProfileId,
    sendMessage,
    steerQueuedRequest,
    setSelectedMainModelProfileId,
    setReasoningIntensity,
  }
}

function attachmentViews(attachments: RuntimeAttachmentInput[]): TranscriptAttachmentView[] {
  return attachments.map((attachment) => ({
    kind: attachment.kind,
    name: attachment.name,
    source_kind: attachment.source_kind,
    mime_type: attachment.mime_type,
  }))
}
