<template>
  <n-popover trigger="hover" placement="top" :show-arrow="false" :delay="80" :duration="160">
    <template #trigger>
      <button
        class="context-progress-trigger"
        :class="{ 'is-compressing': isCompressing, 'is-unknown': usagePercent === null }"
        type="button"
        :aria-label="t('status.context')"
      >
        <svg viewBox="0 0 36 36" aria-hidden="true">
          <circle class="ring-track" cx="18" cy="18" r="14.5" pathLength="100" />
          <circle
            class="ring-value"
            cx="18"
            cy="18"
            r="14.5"
            pathLength="100"
            :style="{ strokeDasharray: ringDasharray }"
          />
          <circle
            v-if="thresholdPercent !== null"
            class="ring-threshold"
            cx="18"
            cy="18"
            r="14.5"
            pathLength="100"
            :style="{ transform: `rotate(${thresholdAngle}deg)` }"
          />
        </svg>
        <span class="ring-label">{{ ringLabel }}</span>
      </button>
    </template>

    <div class="context-progress-bubble" role="status" aria-live="polite">
      <div class="bubble-heading">
        <strong>{{ t('status.context') }}</strong>
        <span>{{ usageText }}</span>
      </div>
      <div class="bubble-meter">
        <span :style="{ width: meterWidth }"></span>
        <i v-if="thresholdPercent !== null" :style="{ left: `${thresholdPercent}%` }"></i>
      </div>
      <div class="bubble-meta">
        <span>{{ percentText }}</span>
        <span>{{ thresholdText }}</span>
      </div>
      <div v-if="compressionText" class="compression-copy" :class="runtimeStore.contextActivity.status">
        <i v-if="isCompressing"></i>
        <span>{{ compressionText }}</span>
      </div>
    </div>
  </n-popover>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NPopover } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import {
  contextWindowPercentLabel,
  contextWindowThresholdLabel,
  contextWindowThresholdPercent,
  contextWindowUsageLabel,
  contextWindowUsagePercent,
  formatCompactTokenCount,
} from '@/utils/contextWindowMeter'

const runtimeStore = useRuntimeStore()
const { t } = useI18n()
const contextWindow = computed(() => runtimeStore.contextWindow)
const usagePercent = computed(() => contextWindow.value ? contextWindowUsagePercent(contextWindow.value) : null)
const thresholdPercent = computed(() => contextWindow.value ? contextWindowThresholdPercent(contextWindow.value) : null)
const meterWidth = computed(() => `${usagePercent.value ?? 0}%`)
const ringDasharray = computed(() => `${Math.max(0, usagePercent.value ?? 0)} 100`)
const thresholdAngle = computed(() => ((thresholdPercent.value ?? 0) / 100) * 360 - 90)
const ringLabel = computed(() => usagePercent.value === null ? '–' : `${Math.round(usagePercent.value)}`)
const usageText = computed(() => contextWindow.value ? contextWindowUsageLabel(contextWindow.value) : '- / -')
const percentText = computed(() => contextWindow.value
  ? contextWindowPercentLabel(contextWindow.value, {
    unknownUsage: t('status.waitContextEvent'),
    used: t('status.recorded'),
    compressionThreshold: t('status.compressionThreshold', { tokens: '' }).trim(),
  })
  : t('status.waitContextEvent'))
const thresholdText = computed(() => contextWindow.value
  ? contextWindowThresholdLabel(contextWindow.value, {
    unknownUsage: t('status.waitContextEvent'),
    used: t('status.recorded'),
    compressionThreshold: t('status.compressionThreshold', { tokens: '' }).trim(),
  })
  : t('status.compressionThreshold', { tokens: '-' }))
const isCompressing = computed(() => runtimeStore.contextActivity.status === 'running')
const compressionText = computed(() => {
  const activity = runtimeStore.contextActivity
  const payload = activity.payload || {}
  if (activity.status === 'running') {
    return t('status.contextCompressionRunning', {
      before: formatCompactTokenCount(optionalNumber(payload.token_estimate_before)),
    })
  }
  if (activity.status === 'completed') {
    return t('status.contextCompressionCompleted', {
      before: formatCompactTokenCount(optionalNumber(payload.token_estimate_before)),
      after: formatCompactTokenCount(optionalNumber(payload.token_estimate_after)),
      count: Number(payload.original_message_count || 0) - Number(payload.compressed_message_count || 0),
    })
  }
  if (activity.status === 'failed') {
    return t('status.contextCompressionFailed', { reason: String(payload.error || t('common.unknown')) })
  }
  return ''
})

function optionalNumber(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}
</script>

<style scoped>
.context-progress-trigger {
  position: relative;
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--app-text);
  cursor: default;
  transition: transform .22s cubic-bezier(.16, 1, .3, 1), background .18s ease;
}
.context-progress-trigger:hover { transform: scale(1.08); background: var(--app-surface-muted); }
.context-progress-trigger svg { position: absolute; inset: 2px; width: 34px; height: 34px; transform: rotate(-90deg); overflow: visible; }
.context-progress-trigger circle { fill: none; stroke-width: 2.4; }
.ring-track { stroke: var(--app-divider); }
.ring-value { stroke: var(--app-text); stroke-linecap: round; transition: stroke-dasharray .48s cubic-bezier(.16, 1, .3, 1); }
.ring-threshold { stroke: var(--app-warning); stroke-width: 4 !important; stroke-dasharray: 1.5 98.5; transform-origin: 18px 18px; }
.ring-label { position: relative; z-index: 1; font-size: 9px; font-weight: 700; }
.is-compressing .ring-value { stroke-dasharray: 18 82 !important; animation: context-ring-spin 1.1s linear infinite; }
.is-compressing { animation: context-control-breathe 1.8s ease-in-out infinite; }
.context-progress-bubble { width: 280px; padding: 5px 3px; }
.bubble-heading, .bubble-meta { display: flex; justify-content: space-between; gap: 12px; }
.bubble-heading { align-items: baseline; font-size: 12px; }
.bubble-heading span, .bubble-meta { color: var(--app-text-muted); font-size: 10px; }
.bubble-meter { position: relative; height: 5px; margin: 12px 0 8px; overflow: visible; border-radius: 999px; background: var(--app-divider); }
.bubble-meter span { display: block; height: 100%; border-radius: inherit; background: var(--app-text); transition: width .48s cubic-bezier(.16, 1, .3, 1); }
.bubble-meter i { position: absolute; top: -3px; width: 1px; height: 11px; background: var(--app-warning); }
.compression-copy { display: flex; align-items: flex-start; gap: 7px; margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--app-divider); font-size: 11px; line-height: 1.45; }
.compression-copy i { width: 6px; height: 6px; flex: 0 0 auto; margin-top: 5px; border-radius: 50%; background: currentColor; animation: context-dot-pulse 1s ease-in-out infinite; }
.compression-copy.failed { color: var(--app-error); }
.compression-copy.completed { color: var(--app-success); }
@keyframes context-ring-spin { to { transform: rotate(360deg); } }
@keyframes context-control-breathe { 50% { opacity: .72; } }
@keyframes context-dot-pulse { 50% { transform: scale(1.65); opacity: .45; } }
@media (prefers-reduced-motion: reduce) { .context-progress-trigger, .ring-value, .is-compressing, .compression-copy i { animation: none; transition: none; } }
</style>
