<template>
  <aside v-if="visible" ref="panelRef" class="tip-panel" aria-label="Tiping">
    <header class="tip-panel-header">
      <div>
        <TipingIcon :size="20" />
        <strong>Tiping</strong>
      </div>
      <n-button quaternary circle size="small" :title="t('common.close')" @click="tipStore.close(scopeType, scopeId)">×</n-button>
    </header>

    <div v-if="currentDraft || currentTip" class="tip-panel-body">
      <blockquote class="tip-source">{{ currentDraft?.selectedText || currentTip?.selected_text }}</blockquote>

      <div v-if="currentTip" class="tip-thread">
        <div
          v-for="message in currentTip.messages"
          :key="message.message_id"
          class="tip-message"
          :class="`tip-message-${message.role}`"
          :aria-label="message.role === 'user' ? t('roles.user') : t('roles.assistant')"
        >
          <div>
            <MessagePartRenderer :part="tipMessagePart(message)" />
          </div>
        </div>
        <div v-if="currentTip.status === 'answering'" class="tip-answering" role="status">
          <i></i><i></i><i></i>
        </div>
        <n-alert v-if="currentTip.error" type="error" :show-icon="false">{{ currentTip.error }}</n-alert>
      </div>

      <n-alert v-if="scopeError" type="error" :show-icon="false">{{ scopeError }}</n-alert>
    </div>

    <div v-else class="tip-panel-empty">{{ t('tips.selectTextHint') }}</div>

    <footer v-if="currentDraft || currentTip" class="tip-composer">
      <n-input
        ref="inputRef"
        v-model:value="question"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 6 }"
        :placeholder="t('tips.questionPlaceholder')"
        :disabled="submitting"
        @keydown="handleKeydown"
      />
      <div class="tip-composer-actions">
        <n-button
          v-if="currentTip && !currentTip.tip_id.startsWith('pending-')"
          quaternary
          type="error"
          size="small"
          :disabled="submitting"
          @click="removeCurrent"
        >
          {{ t('common.delete') }}
        </n-button>
        <n-button type="primary" size="small" :loading="submitting" :disabled="!question.trim()" @click="submit">
          {{ t('tips.ask') }}
        </n-button>
      </div>
    </footer>
  </aside>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { NAlert, NButton, NInput } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import { useTipStore } from '@/stores/tips'
import type { TipMessageView } from '@/api/tips'
import MessagePartRenderer from '@/components/chat/MessagePartRenderer.vue'
import TipingIcon from '@/components/chat/TipingIcon.vue'
import type { TextMessagePart } from '@/types/protocol'

const props = defineProps<{
  scopeType: string
  scopeId: string
}>()

const tipStore = useTipStore()
const { t } = useI18n()
const question = ref('')
const inputRef = ref<InstanceType<typeof NInput> | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const submitting = ref(false)
const scope = computed(() => tipStore.scopeKey(props.scopeType, props.scopeId))
const visible = computed(() => Boolean(props.scopeId) && tipStore.isOpen(props.scopeType, props.scopeId))
const currentDraft = computed(() => tipStore.draft(props.scopeType, props.scopeId))
const currentTip = computed(() => tipStore.activeTip(props.scopeType, props.scopeId))
const scopeError = computed(() => tipStore.errors[scope.value])
const panelLaunchToken = computed(() => tipStore.panelLaunchToken(props.scopeType, props.scopeId))

watch(
  () => [props.scopeType, props.scopeId].join(':'),
  () => {
    question.value = ''
    if (props.scopeId) void tipStore.loadScope(props.scopeType, props.scopeId)
  },
  { immediate: true },
)

watch(
  () => [visible.value, currentDraft.value?.selectedText || '', currentTip.value?.tip_id || ''].join(':'),
  () => {
    if (visible.value) nextTick(() => inputRef.value?.focus())
  },
)

watch(
  () => [visible.value, panelLaunchToken.value] as const,
  async ([isVisible]) => {
    if (!isVisible) return
    await nextTick()
    animatePanelFromOrigin()
  },
)

async function submit() {
  const prompt = question.value.trim()
  if (!prompt || submitting.value) return
  submitting.value = true
  question.value = ''
  try {
    if (currentDraft.value) {
      await tipStore.createFromDraft(props.scopeType, props.scopeId, prompt)
    } else if (currentTip.value) {
      await tipStore.followUp(props.scopeType, props.scopeId, currentTip.value.tip_id, prompt)
    }
  } finally {
    submitting.value = false
  }
}

async function removeCurrent() {
  if (!currentTip.value) return
  await tipStore.deleteTip(props.scopeType, props.scopeId, currentTip.value.tip_id)
  tipStore.close(props.scopeType, props.scopeId)
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  void submit()
}

function tipMessagePart(message: TipMessageView): TextMessagePart {
  return {
    id: `tip-part-${message.message_id}`,
    type: 'text',
    format: message.role === 'assistant' ? 'markdown' : 'plain',
    text: message.content,
    status: 'completed',
  }
}

function animatePanelFromOrigin() {
  const panel = panelRef.value
  if (!panel || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  const origin = tipStore.panelOrigin(props.scopeType, props.scopeId)
  const bounds = panel.getBoundingClientRect()
  const originX = origin ? origin.x - bounds.left : bounds.width
  const originY = origin ? origin.y - bounds.top : 52
  panel.getAnimations().forEach(animation => animation.cancel())
  panel.style.transformOrigin = `${originX}px ${originY}px`
  const animation = panel.animate(
    [
      { opacity: 0, transform: 'scale(0.06)', borderRadius: '32px' },
      { opacity: 0.72, transform: 'scale(0.92)', borderRadius: '24px', offset: 0.68 },
      { opacity: 1, transform: 'scale(1)', borderRadius: '22px' },
    ],
    {
      duration: 560,
      easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
      fill: 'both',
    },
  )
  animation.onfinish = () => {
    animation.cancel()
    panel.style.transformOrigin = ''
  }
}
</script>

<style scoped>
.tip-panel { align-self: stretch; width: clamp(300px, 26vw, 390px); min-width: 300px; min-height: 0; margin: 12px 12px 12px 0; display: flex; flex-direction: column; overflow: hidden; border: 1px solid color-mix(in srgb, var(--app-border) 64%, transparent); border-radius: 22px; background: color-mix(in srgb, var(--app-surface) 94%, transparent); box-shadow: 0 14px 38px color-mix(in srgb, var(--app-text) 9%, transparent), 0 2px 8px color-mix(in srgb, var(--app-text) 5%, transparent); backdrop-filter: blur(18px); }
.tip-panel-header { display: flex; justify-content: space-between; align-items: center; min-height: 48px; padding: 7px 10px 7px var(--app-space-md); }
.tip-panel-header > div { display: flex; align-items: center; gap: var(--app-space-xs); }
.tip-panel-header strong { font-size: 13px; font-weight: 600; letter-spacing: .01em; }
.tip-panel-body { flex: 1; min-height: 0; overflow: auto; padding: var(--app-space-xs) var(--app-space-lg) var(--app-space-md); }
.tip-panel-empty { flex: 1; display: grid; place-items: center; padding: var(--app-space-xl); color: var(--app-text-muted); text-align: center; }
.tip-source { margin: 0 0 var(--app-space-lg); padding: var(--app-space-sm) var(--app-space-md); border: 0; border-radius: 14px; background: color-mix(in srgb, var(--app-surface-muted) 62%, transparent); color: var(--app-text-muted); font-size: 12px; line-height: 1.55; white-space: pre-wrap; }
.tip-thread { display: grid; gap: var(--app-space-md); }
.tip-message { min-width: 0; }
.tip-message > div { line-height: 1.65; }
.tip-message-user { justify-self: end; max-width: 88%; }
.tip-message-user > div { padding: 7px 11px; border-radius: 15px 15px 6px 15px; background: color-mix(in srgb, var(--app-surface-muted) 76%, transparent); color: var(--app-text-secondary); font-size: 13px; }
.tip-message-assistant > div { padding: 0; background: transparent; color: var(--app-text); }
.tip-answering { display: flex; gap: 5px; padding: var(--app-space-sm); }
.tip-answering i { width: 6px; height: 6px; border-radius: 50%; background: var(--app-info); animation: tip-dot 1s ease-in-out infinite; }
.tip-answering i:nth-child(2) { animation-delay: .15s; }
.tip-answering i:nth-child(3) { animation-delay: .3s; }
.tip-composer { padding: var(--app-space-sm) var(--app-space-md) var(--app-space-md); border-top: 0; }
.tip-composer :deep(.n-input) { border-radius: 16px; background: color-mix(in srgb, var(--app-surface-muted) 58%, transparent); }
.tip-composer-actions { display: flex; justify-content: flex-end; gap: var(--app-space-sm); margin-top: var(--app-space-sm); }
@keyframes tip-dot { 0%, 100% { opacity: .35; transform: translateY(0); } 50% { opacity: 1; transform: translateY(-3px); } }
@media (max-width: 900px) { .tip-panel { position: absolute; inset: 10px 10px 10px auto; z-index: 30; width: min(88vw, 390px); margin: 0; box-shadow: 0 18px 48px color-mix(in srgb, var(--app-text) 14%, transparent); } }
</style>
