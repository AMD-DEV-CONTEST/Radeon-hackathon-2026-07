<template>
  <div
    class="message-item"
    :class="[`role-${message.role}`, { streaming }]"
    :data-reference-label="`${roleLabel} · ${formatTime(message.timestamp)}`"
    :data-tip-source-key="registeredSourceKey || undefined"
  >
    <div class="message-avatar">
      <n-avatar :size="36" :style="avatarStyle">
        {{ avatarText }}
      </n-avatar>
    </div>

    <div class="message-content">
      <div class="message-header">
        <n-text strong>{{ roleLabel }}</n-text>
        <n-text depth="3" style="font-size: 12px">
          {{ formatTime(message.timestamp) }}
        </n-text>
        <n-tag
          v-if="dispatchStatusLabel"
          :type="dispatchStatusType"
          size="tiny"
          :bordered="false"
        >
          {{ dispatchStatusLabel }}
        </n-tag>
        <n-button
          v-if="quoteable"
          class="quote-button"
          quaternary
          circle
          size="tiny"
          title="引用"
          @click="$emit('quote', message)"
        >
          <template #icon><n-icon><ReturnUpBackOutline /></n-icon></template>
        </n-button>
      </div>

      <div ref="messageBodyRef" class="message-body">
        <div
          v-if="thinking"
          class="thinking-content"
          role="status"
          aria-live="polite"
          :aria-label="message.content || t('roles.assistantThinking')"
        >
          <span class="thinking-label">{{ message.content || t('roles.assistantThinking') }}</span>
          <span class="thinking-dots" aria-hidden="true">
            <span class="thinking-dot"></span>
            <span class="thinking-dot"></span>
            <span class="thinking-dot"></span>
          </span>
        </div>
        <template v-else>
          <MessagePartRenderer
            v-for="part in visibleParts"
            :key="part.id"
            :part="part"
            :streaming="streaming"
            :highlight-mentions="isGroupUserMessage"
            :mention-names="mentionNames"
            :workspace-context="workspaceContext"
          />
        </template>

        <span
          v-if="streaming && !thinking"
          class="streaming-ink-dots"
          aria-hidden="true"
        >
          <span></span>
          <span></span>
          <span></span>
        </span>
      </div>
    </div>

    <button
      v-for="marker in tipMarkers"
      :key="marker.tipId"
      class="tip-marker"
      :class="{ 'tip-marker-answering': marker.answering }"
      :style="{ left: `${marker.x}px`, top: `${marker.y}px` }"
      type="button"
      title="Tiping"
      @click="openTip(marker.tipId, $event)"
    >
      <TipingIcon :size="20" scroll-motion />
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { CSSProperties } from 'vue'
import { NAvatar, NButton, NIcon, NTag, NText } from 'naive-ui'
import { ReturnUpBackOutline } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import MessagePartRenderer from './MessagePartRenderer.vue'
import type { TranscriptItem } from '@/types/protocol'
import { conversationVisibleParts } from '@/utils/toolPresentation'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'
import { useTipStore, type TipMessageContext } from '@/stores/tips'
import TipingIcon from './TipingIcon.vue'
import { useTipMarkerLayout } from '@/composables/chat/useTipMarkerLayout'

type TipContextConfig = Omit<TipMessageContext, 'sourceMessageId' | 'sourceRole' | 'sourceContent'>

const props = withDefaults(
  defineProps<{
    message: TranscriptItem
    streaming?: boolean
    thinking?: boolean
    quoteable?: boolean
    tipContext?: TipContextConfig | null
    workspaceContext?: WorkspaceRequestContext | null
  }>(),
  {
    streaming: false,
    thinking: false,
    quoteable: false,
    tipContext: null,
    workspaceContext: null,
  }
)

defineEmits<{
  quote: [message: TranscriptItem]
}>()

const { locale, t } = useI18n()
const tipStore = useTipStore()
const registeredSourceKey = ref('')
const messageBodyRef = ref<HTMLElement | null>(null)
const messageTips = computed(() => registeredSourceKey.value ? tipStore.tipsForSource(registeredSourceKey.value) : [])
const { tipMarkers } = useTipMarkerLayout(messageBodyRef, messageTips)

watch(
  () => props.tipContext,
  (context) => {
    if (registeredSourceKey.value) tipStore.unregisterSource(registeredSourceKey.value)
    registeredSourceKey.value = context
      ? tipStore.registerSource({
          ...context,
          sourceMessageId: props.message.id,
          sourceRole: props.message.role,
          sourceContent: props.message.content,
        })
      : ''
  },
  { immediate: true, deep: true },
)

onBeforeUnmount(() => {
  if (registeredSourceKey.value) tipStore.unregisterSource(registeredSourceKey.value)
})

function openTip(tipId: string, event: MouseEvent) {
  const tip = messageTips.value.find(item => item.tip_id === tipId)
  if (!tip) return
  const marker = event.currentTarget as HTMLElement
  const bounds = marker.getBoundingClientRect()
  tipStore.selectTip(tip.scope_type, tip.scope_id, tip.tip_id, {
    x: bounds.left + bounds.width / 2,
    y: bounds.top + bounds.height / 2,
  })
}


const roleLabel = computed(() => {
  const displayName = String(props.message.metadata?.display_name || '').trim()
  if (displayName) return displayName
  if (props.message.role === 'user') return t('roles.user')
  if (props.message.role === 'system') return t('roles.system')
  return t('roles.assistant')
})

const avatarStyle = computed<CSSProperties>(() => {
  if (props.message.role === 'assistant') {
    if (Boolean(props.message.metadata?.agent_group_speaker)) {
      return groupAgentAvatarStyle(props.message.metadata)
    }
    return {
      background: 'var(--app-surface)',
      color: 'var(--app-text)',
      border: '1px solid var(--app-text)',
    }
  }
  return {
    background: 'var(--app-text)',
    color: 'var(--app-text-inverse)',
  }
})

const avatarText = computed(() => {
  const avatarLabel = String(props.message.metadata?.avatar_label || '').trim()
  if (avatarLabel) return avatarLabel.slice(0, 2)
  if (props.message.role === 'user') return 'U'
  if (props.message.role === 'system') return 'S'
  return 'A'
})

const visibleParts = computed(() => conversationVisibleParts(props.message.parts))
const isGroupUserMessage = computed(() => (
  props.message.role === 'user' && Boolean(props.message.metadata?.agent_group_message)
))
const mentionNames = computed(() => {
  const value = props.message.metadata?.mention_names
  return Array.isArray(value) ? value.map(item => String(item)).filter(Boolean) : []
})
const dispatchStatusLabel = computed(() => {
  if (props.message.role !== 'user') return ''
  const state = String(props.message.metadata?.dispatch_state || '')
  if (state === 'queued') {
    const position = Number(props.message.metadata?.queue_position || 0)
    return position > 0
      ? t('chat.messageQueuedAt', { position })
      : t('chat.messageQueued')
  }
  if (state === 'running') return t('chat.messageRunning')
  return ''
})
const dispatchStatusType = computed(() => (
  props.message.metadata?.dispatch_state === 'queued' ? 'warning' : 'info'
))

function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = now.getTime() - date.getTime()

  // 小于 1 分钟
  if (diff < 60000) {
    return t('time.justNow')
  }

  // 小于 1 小时
  if (diff < 3600000) {
    const minutes = Math.floor(diff / 60000)
    return t('time.minutesAgo', { count: minutes })
  }

  // 今天
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString(locale.value, {
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  // 更早
  return date.toLocaleString(locale.value, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function groupAgentAvatarStyle(metadata: Record<string, unknown>): CSSProperties {
  const seed = String(metadata.package_id || metadata.display_name || 'agent')
  const hues = [8, 28, 48, 84, 142, 174, 202, 226, 278, 326]
  const hue = hues[stableColorIndex(seed, hues.length)]
  return {
    background: `hsl(${hue} 58% 42%)`,
    color: '#ffffff',
    border: '1px solid transparent',
  }
}

function stableColorIndex(value: string, size: number): number {
  let hash = 0
  for (const character of value) hash = (hash * 31 + character.codePointAt(0)!) >>> 0
  return hash % size
}

</script>

<style scoped>
.message-item {
  position: relative;
  display: flex;
  gap: var(--app-space-md);
  padding: var(--app-space-lg) var(--app-space-md);
  border-radius: var(--app-radius-lg);
  transition: background-color var(--app-transition-base), transform var(--app-transition-spring), box-shadow var(--app-transition-base);
  animation: app-fade-in-up 0.55s var(--app-transition-spring) both;
}

.tip-marker {
  position: absolute;
  transform: translate(-50%, -100%);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-text);
  box-shadow: none;
  cursor: pointer;
  font: inherit;
  z-index: 2;
  isolation: isolate;
  transition: border-color var(--app-transition-base), background-color var(--app-transition-base), transform var(--app-transition-spring);
  animation: tip-marker-arrive .76s var(--app-transition-spring) both;
}

.tip-marker::after {
  content: '';
  position: absolute;
  inset: 1px;
  z-index: -1;
  border: 1px solid color-mix(in srgb, var(--app-text) 72%, transparent);
  border-radius: 50%;
  animation: tip-marker-ripple 1.25s ease-out .12s 2 both;
}

.tip-marker:hover {
  background: transparent;
  transform: translate(-50%, -100%) scale(1.06);
}

.tip-marker-answering {
  animation: tip-marker-arrive .76s var(--app-transition-spring) both,
             tip-marker-breathe 1.55s ease-in-out .76s infinite;
}

@keyframes tip-marker-arrive {
  0% { opacity: 0; transform: translate(-50%, -82%) scale(.2) rotate(-16deg); }
  46% { opacity: 1; transform: translate(-50%, -108%) scale(1.24) rotate(7deg); }
  72% { transform: translate(-50%, -96%) scale(.9) rotate(-3deg); }
  100% { opacity: 1; transform: translate(-50%, -100%) scale(1) rotate(0); }
}

@keyframes tip-marker-ripple {
  0% { opacity: .72; transform: scale(.42); }
  72%, 100% { opacity: 0; transform: scale(1.8); }
}

@keyframes tip-marker-breathe {
  0%, 100% { opacity: .68; transform: translate(-50%, -100%) scale(.96); }
  50% { opacity: 1; transform: translate(-50%, -100%) scale(1.04); }
}

.message-item.role-assistant {
  background: var(--app-surface-elevated);
  border: none;
  box-shadow: var(--app-shadow-sm);
}

.message-item.streaming {
  position: relative;
  animation: none;
}

.message-item.streaming::before {
  content: '';
  position: absolute;
  left: 0;
  top: 18px;
  bottom: 18px;
  width: 2px;
  background: var(--app-border-hover);
  border-radius: var(--app-radius-pill);
  opacity: 0.42;
  animation: app-pulse-soft 2.4s ease-in-out infinite;
}

.message-item.role-user {
  background-color: transparent;
}

.message-item:hover {
  background-color: var(--app-surface-hover);
  transform: translateX(2px);
}

.message-item.role-assistant:hover {
  box-shadow: var(--app-shadow-md);
  transform: translateX(4px) translateY(-1px);
}

.message-item + .message-item {
  margin-top: var(--app-space-md);
}

.message-avatar {
  flex-shrink: 0;
  padding-top: 2px;
  animation: app-pop-in 0.35s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.message-content {
  flex: 1;
  min-width: 0;
}

.message-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--app-space-sm);
  margin-bottom: var(--app-space-sm);
}

.quote-button {
  margin-left: auto;
}

.message-body {
  position: relative;
  font-size: var(--app-font-lg);
  line-height: var(--app-leading-relaxed);
}

.message-body :deep(.tip-layout-anchor) {
  display: inline-block;
  width: 0;
  height: calc(1lh + var(--app-space-xl));
  vertical-align: baseline;
  pointer-events: none;
}

@media (prefers-reduced-motion: reduce) {
  .tip-marker,
  .tip-marker::after,
  .tip-marker-answering {
    animation: none;
  }
}

.streaming-ink-dots {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 18px;
  margin-left: 6px;
  vertical-align: text-bottom;
}

.streaming-ink-dots > span {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--app-text);
  opacity: 0.34;
  transform: scale(0.78);
  animation: streaming-ink-breathe 1.2s ease-in-out infinite;
}

.streaming-ink-dots > span:nth-child(2) { animation-delay: 0.16s; }
.streaming-ink-dots > span:nth-child(3) { animation-delay: 0.32s; }

@keyframes streaming-ink-breathe {
  0%, 65%, 100% { opacity: 0.34; transform: scale(0.78); }
  32% { opacity: 0.9; transform: scale(1.16); }
}

@media (prefers-reduced-motion: reduce) {
  .streaming-ink-dots > span {
    animation: none;
    opacity: 0.58;
    transform: none;
  }
}

.thinking-content {
  width: fit-content;
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 5px 12px;
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: var(--app-surface-muted);
}

.thinking-label {
  color: var(--app-text-secondary);
  font-size: 13px;
  line-height: 20px;
}

.thinking-dots {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.thinking-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--app-text);
  animation: thinking-pulse 1.05s ease-in-out infinite;
}

.thinking-dot:nth-child(2) {
  animation-delay: 0.14s;
}

.thinking-dot:nth-child(3) {
  animation-delay: 0.28s;
}

@keyframes thinking-pulse {
  0%,
  80%,
  100% {
    opacity: 0.32;
    transform: translateY(0);
  }
  40% {
    opacity: 1;
    transform: translateY(-3px);
  }
}
</style>
