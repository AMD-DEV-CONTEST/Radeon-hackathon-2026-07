<template>
  <n-drawer v-model:show="show" :width="drawerWidth" placement="right" class="glass-drawer">
    <n-drawer-content :title="t('settings.title')" closable class="glass-drawer-content">
      <div class="settings-body">
        <!-- 分组：外观与语言 -->
        <section class="settings-group">
          <header class="group-header">
            <div class="group-icon" aria-hidden="true">
              <n-icon size="18"><ColorPalette /></n-icon>
            </div>
            <div class="group-title-block">
              <div class="group-title">{{ t('settings.groupAppearance') }}</div>
              <div class="group-desc">{{ t('settings.groupAppearanceDesc') }}</div>
            </div>
          </header>

          <div class="group-body">
            <div class="field-row">
              <label class="field-label">{{ t('settings.theme') }}</label>
              <n-radio-group v-model:value="themeMode" size="small" class="field-control soft-segmented-control">
                <n-radio-button
                  v-for="option in themeOptions"
                  :key="option.value"
                  :value="option.value"
                >
                  {{ option.label }}
                </n-radio-button>
              </n-radio-group>
            </div>

            <div class="field-divider" aria-hidden="true"></div>

            <div class="field-row">
              <label class="field-label">{{ t('settings.language') }}</label>
              <n-radio-group v-model:value="locale" size="small" class="field-control soft-segmented-control">
                <n-radio-button
                  v-for="option in localeOptions"
                  :key="option.value"
                  :value="option.value"
                >
                  {{ option.label }}
                </n-radio-button>
              </n-radio-group>
            </div>
          </div>
        </section>

        <section class="settings-group">
          <header class="group-header">
            <div class="group-icon" aria-hidden="true">
              <n-icon size="18"><Time /></n-icon>
            </div>
            <div class="group-title-block">
              <div class="group-title">{{ t('settings.groupRuntime') }}</div>
              <div class="group-desc">{{ t('settings.groupRuntimeDesc') }}</div>
            </div>
          </header>

          <div class="group-body">
            <div class="field-block">
              <div class="field-block-head">
                <label class="field-label">{{ t('settings.requestTimeout') }}</label>
              </div>
              <n-input-number
                v-model:value="requestTimeoutSeconds"
                class="field-input"
                :min="0"
                :step="30"
                :show-button="true"
              >
                <template #suffix>{{ t('settings.seconds') }}</template>
              </n-input-number>
              <p class="field-hint">{{ t('settings.requestTimeoutHint') }}</p>
            </div>

            <div class="field-divider" aria-hidden="true"></div>

            <div class="field-block">
              <div class="field-block-head">
                <label class="field-label">{{ t('settings.maxRetries') }}</label>
              </div>
              <n-input-number
                v-model:value="maxRetries"
                class="field-input"
                :min="0"
                :step="1"
                :precision="0"
                :show-button="true"
              />
              <p class="field-hint">{{ t('settings.maxRetriesHint') }}</p>
            </div>

            <div class="field-divider" aria-hidden="true"></div>

            <div class="field-block">
              <div class="field-block-head">
                <label class="field-label">{{ t('settings.maxParallelSubAgents') }}</label>
              </div>
              <n-input-number
                v-model:value="maxParallelSubAgents"
                class="field-input"
                :min="1"
                :step="1"
                :precision="0"
                :show-button="true"
              />
              <p class="field-hint">{{ t('settings.maxParallelSubAgentsHint') }}</p>
              <p v-if="runtimePreferences.maxParallelSubAgentsSaveFailed" class="field-error">
                {{ t('settings.maxParallelSubAgentsSaveFailed') }}
              </p>
            </div>
          </div>
        </section>

        <section class="settings-group">
          <header class="group-header">
            <div class="group-icon" aria-hidden="true">
              <n-icon size="18"><NotificationsOutline /></n-icon>
            </div>
            <div class="group-title-block">
              <div class="group-title">{{ t('settings.groupNotifications') }}</div>
              <div class="group-desc">{{ t('settings.groupNotificationsDesc') }}</div>
            </div>
          </header>

          <div class="group-body">
            <div class="field-row">
              <div class="field-copy">
                <label class="field-label">{{ t('settings.taskNotifications') }}</label>
                <p class="field-hint">{{ t('settings.taskNotificationsHint') }}</p>
              </div>
              <n-switch
                :value="taskNotificationPreferences.enabled"
                @update:value="setTaskNotificationsEnabled"
              />
            </div>

            <template v-if="taskNotificationPreferences.enabled">
              <div class="field-divider" aria-hidden="true"></div>
              <div
                v-for="option in taskNotificationCategoryOptions"
                :key="option.category"
                class="field-row"
              >
                <label class="field-label">{{ option.label }}</label>
                <n-switch
                  :value="taskNotificationPreferences.categories[option.category]"
                  @update:value="taskNotificationPreferences.setCategoryEnabled(option.category, $event)"
                />
              </div>
            </template>
          </div>
        </section>

        <section class="settings-group">
          <header class="group-header">
            <div class="group-icon" aria-hidden="true">
              <n-icon size="18"><TrashOutline /></n-icon>
            </div>
            <div class="group-title-block">
              <div class="group-title">{{ t('settings.groupData') }}</div>
              <div class="group-desc">{{ t('settings.groupDataDesc') }}</div>
            </div>
          </header>

          <div class="group-body">
            <div class="field-row">
              <div class="field-copy">
                <label class="field-label">{{ t('settings.conversationStorage') }}</label>
                <p class="field-hint">{{ conversationUsageText }}</p>
              </div>
              <n-button
                type="error"
                secondary
                :loading="clearingConversations"
                :disabled="loadingConversationUsage"
                @click="confirmClearConversations"
              >
                <template #icon><n-icon><TrashOutline /></n-icon></template>
                {{ t('settings.clearConversations') }}
              </n-button>
            </div>
            <p v-if="conversationStorageError" class="field-error">{{ conversationStorageError }}</p>
          </div>
        </section>

        <!-- 页脚：关于 -->
        <footer class="settings-footer">
          <div class="footer-title">{{ t('settings.about') }}</div>
          <div class="footer-brand-row">
            <div class="footer-brand">
              FastAgentFactory
              <span class="footer-version">v{{ appUpdateStore.currentVersion || '—' }}</span>
            </div>
            <n-button
              size="small"
              secondary
              :loading="appUpdateStore.status === 'checking'"
              @click="checkForUpdates"
            >
              <template #icon>
                <n-icon><Refresh /></n-icon>
              </template>
              {{ t('settings.checkForUpdates') }}
            </n-button>
          </div>
          <div v-if="updateCheckMessage" class="footer-update-status" role="status">
            {{ updateCheckMessage }}
          </div>
          <div class="footer-desc">{{ t('settings.description') }}</div>
        </footer>
      </div>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NIcon,
  NInputNumber,
  NRadioButton,
  NRadioGroup,
  NSwitch,
  useDialog,
} from 'naive-ui'
import { ColorPalette, NotificationsOutline, Refresh, Time, TrashOutline } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import { useUiStore } from '@/stores/ui'
import { useRuntimePreferencesStore } from '@/stores/runtimePreferences'
import {
  useTaskNotificationPreferencesStore,
  type TaskNotificationCategory,
} from '@/stores/taskNotificationPreferences'
import type { Locale } from '@/i18n'
import type { ThemeMode } from '@/stores/ui'
import { requestNativeTaskNotificationPermission } from '@/services/taskNotifications'
import { useAppUpdateStore } from '@/stores/appUpdate'
import { storageApi, type ConversationStorageUsage } from '@/api/storage'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

const uiStore = useUiStore()
const runtimePreferences = useRuntimePreferencesStore()
const taskNotificationPreferences = useTaskNotificationPreferencesStore()
const appUpdateStore = useAppUpdateStore()
const { localeOptions, t } = useI18n()
const updateCheckMessage = ref('')
const dialog = useDialog()
const conversationUsage = ref<ConversationStorageUsage | null>(null)
const loadingConversationUsage = ref(false)
const clearingConversations = ref(false)
const conversationStorageError = ref('')

onMounted(() => {
  void appUpdateStore.loadCurrentVersion()
  void loadConversationUsage()
})

watch(() => props.show, visible => {
  if (visible) void loadConversationUsage()
})

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const drawerWidth = computed(() => {
  if (typeof window === 'undefined') return 460
  return Math.min(460, window.innerWidth - 24)
})

const locale = computed({
  get: () => uiStore.locale,
  set: (value: Locale) => uiStore.setLocale(value),
})

const themeMode = computed({
  get: () => uiStore.themeMode,
  set: (value: ThemeMode) => uiStore.setThemeMode(value),
})

const requestTimeoutSeconds = computed({
  get: () => runtimePreferences.requestTimeoutSeconds,
  set: (value: number | null) => {
    if (value !== null) runtimePreferences.setRequestTimeoutSeconds(value)
  },
})

const maxRetries = computed({
  get: () => runtimePreferences.maxRetries,
  set: (value: number | null) => {
    if (value !== null) runtimePreferences.setMaxRetries(value)
  },
})

const maxParallelSubAgents = computed({
  get: () => runtimePreferences.maxParallelSubAgents,
  set: (value: number | null) => {
    if (value !== null) runtimePreferences.setMaxParallelSubAgents(value)
  },
})

const themeOptions = computed<Array<{ label: string; value: ThemeMode }>>(() => [
  { label: t('settings.themeLight'), value: 'light' },
  { label: t('settings.themeDark'), value: 'dark' },
  { label: t('settings.themeAuto'), value: 'auto' },
])

const taskNotificationCategoryOptions = computed<Array<{
  category: TaskNotificationCategory
  label: string
}>>(() => [
  { category: 'conversation', label: t('settings.notificationConversation') },
  { category: 'agentGroup', label: t('settings.notificationAgentGroup') },
  { category: 'scheduler', label: t('settings.notificationScheduler') },
])

const conversationUsageText = computed(() => {
  if (loadingConversationUsage.value && !conversationUsage.value) return t('settings.storageLoading')
  const usage = conversationUsage.value
  if (!usage) return t('settings.storageUnavailable')
  return t('settings.conversationStorageUsage', {
    size: formatBytes(usage.bytes_used),
    count: usage.session_count,
  })
})

function setTaskNotificationsEnabled(value: boolean): void {
  taskNotificationPreferences.setEnabled(value)
  if (value) void requestNativeTaskNotificationPermission()
}

async function checkForUpdates(): Promise<void> {
  updateCheckMessage.value = ''
  const result = await appUpdateStore.checkForUpdate()
  if (result === 'available') {
    updateCheckMessage.value = t('settings.updateAvailable')
  } else if (result === 'up-to-date') {
    updateCheckMessage.value = t('settings.upToDate')
  } else {
    updateCheckMessage.value = t('settings.updateCheckUnavailable')
  }
}

async function loadConversationUsage(): Promise<void> {
  if (loadingConversationUsage.value) return
  loadingConversationUsage.value = true
  conversationStorageError.value = ''
  try {
    conversationUsage.value = await storageApi.conversationUsage()
  } catch (error) {
    conversationStorageError.value = error instanceof Error ? error.message : String(error)
  } finally {
    loadingConversationUsage.value = false
  }
}

function confirmClearConversations(): void {
  const usage = conversationUsage.value
  dialog.warning({
    title: t('settings.clearConversationsConfirmTitle'),
    content: t('settings.clearConversationsConfirmContent', {
      size: formatBytes(usage?.bytes_used || 0),
      count: usage?.session_count || 0,
    }),
    positiveText: t('settings.clearConversationsConfirmAction'),
    negativeText: t('common.cancel'),
    onPositiveClick: clearConversations,
  })
}

async function clearConversations(): Promise<void> {
  if (clearingConversations.value) return
  clearingConversations.value = true
  conversationStorageError.value = ''
  try {
    const result = await storageApi.clearConversations()
    conversationUsage.value = result.after
  } catch (error) {
    conversationStorageError.value = error instanceof Error ? error.message : String(error)
  } finally {
    clearingConversations.value = false
  }
}

function formatBytes(value: number): string {
  const bytes = Math.max(0, Number(value) || 0)
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let amount = bytes / 1024
  let index = 0
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024
    index += 1
  }
  return `${amount >= 10 ? amount.toFixed(1) : amount.toFixed(2)} ${units[index]}`
}
</script>

<style scoped>
.settings-body {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xl);
  padding-bottom: var(--app-space-lg);
}

/* ========== 分组 ========== */
.settings-group {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
  overflow: hidden;
  animation: app-fade-in-up 0.28s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.settings-group + .settings-group {
  animation-delay: 0.06s;
}

.group-header {
  display: flex;
  align-items: center;
  gap: var(--app-space-md);
  padding: var(--app-space-md) var(--app-space-lg);
  background: var(--app-surface-muted);
  border-bottom: 1px solid var(--app-divider);
}

.group-icon {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--app-radius-md);
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  color: var(--app-text);
}

.group-title-block {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.group-title {
  font-size: var(--app-font-lg);
  font-weight: 600;
  color: var(--app-text-strong);
  letter-spacing: -0.01em;
}

.group-desc {
  font-size: var(--app-font-sm);
  color: var(--app-text-muted);
  line-height: var(--app-leading-normal);
}

.group-body {
  padding: var(--app-space-lg);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-lg);
}

/* ========== 简单一行字段（label + control） ========== */
.field-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  flex-wrap: wrap;
}

.field-label {
  flex-shrink: 0;
  font-size: var(--app-font-md);
  font-weight: 500;
  color: var(--app-text);
}

.field-copy {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
}

.field-control {
  flex-shrink: 0;
}

/* ========== 分隔线 ========== */
.field-divider {
  height: 1px;
  background: var(--app-divider);
  margin: 0 calc(var(--app-space-lg) * -1);
}

/* ========== 复合字段块（含提示、当前值、输入、按钮） ========== */
.field-block {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
}

.field-block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
}

.field-badge {
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.field-hint {
  margin: 0;
  font-size: var(--app-font-sm);
  color: var(--app-text-muted);
  line-height: var(--app-leading-normal);
}

.field-error {
  margin: 0;
  color: var(--app-error);
  font-size: var(--app-font-sm);
  line-height: var(--app-leading-normal);
}

.field-current {
  display: flex;
  align-items: baseline;
  gap: var(--app-space-sm);
  padding: var(--app-space-sm) var(--app-space-md);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  border: 1px solid var(--app-border);
}

.field-current-label {
  font-size: var(--app-font-xs);
  color: var(--app-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.field-current-value {
  font-size: var(--app-font-md);
  font-weight: 600;
  color: var(--app-text-strong);
  font-variant-numeric: tabular-nums;
}

.field-input {
  width: 100%;
}

.env-textarea :deep(.n-input__textarea-el) {
  font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', monospace;
  font-size: var(--app-font-sm);
  line-height: 1.55;
}

.field-meta {
  margin: 0;
  padding: var(--app-space-xs) var(--app-space-md);
  font-size: var(--app-font-xs);
  color: var(--app-text-muted);
  background: var(--app-surface-muted);
  border-left: 2px solid var(--app-border);
  border-radius: 0 var(--app-radius-sm) var(--app-radius-sm) 0;
  word-break: break-all;
}

.field-actions {
  display: flex;
  gap: var(--app-space-sm);
  margin-top: var(--app-space-xxs);
}

/* ========== 页脚：关于 ========== */
.settings-footer {
  padding-top: var(--app-space-lg);
  border-top: 1px solid var(--app-divider);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xxs);
  animation: app-fade-in-up 0.28s cubic-bezier(0.16, 1, 0.3, 1) 0.12s both;
}

.footer-title {
  font-size: var(--app-font-xs);
  font-weight: 600;
  color: var(--app-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: var(--app-space-xxs);
}

.footer-brand {
  font-size: var(--app-font-lg);
  font-weight: 600;
  color: var(--app-text-strong);
  display: flex;
  align-items: baseline;
  gap: var(--app-space-sm);
}

.footer-brand-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
}

.footer-update-status {
  color: var(--app-text-secondary);
  font-size: var(--app-font-sm);
}

.footer-version {
  font-size: var(--app-font-sm);
  font-weight: 400;
  color: var(--app-text-muted);
  font-variant-numeric: tabular-nums;
}

.footer-desc {
  font-size: var(--app-font-sm);
  color: var(--app-text-muted);
  line-height: var(--app-leading-normal);
}

/* ========== 窄屏 ========== */
@media (max-width: 480px) {
  .field-row {
    flex-direction: column;
    align-items: stretch;
  }
  .field-control {
    width: 100%;
  }
  .group-body {
    padding: var(--app-space-md);
  }
  .group-header {
    padding: var(--app-space-sm) var(--app-space-md);
  }
}

/* ========== 液态玻璃抽屉 ========== */
:deep(.glass-drawer .n-drawer-body-content-wrapper) {
  background: var(--app-glass-background);
  backdrop-filter: var(--app-glass-blur);
  -webkit-backdrop-filter: var(--app-glass-blur);
}

@supports not (backdrop-filter: blur(1px)) {
  :deep(.glass-drawer .n-drawer-body-content-wrapper) {
    background: var(--app-surface-elevated);
  }
}
</style>
