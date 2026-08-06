<template>
  <n-modal
    :show="updateStore.visible && !startupStore.initializing"
    :mask-closable="false"
    :close-on-esc="false"
    :closable="canDismiss"
    preset="card"
    class="update-dialog"
    style="width: min(560px, calc(100vw - 32px)); max-width: 560px"
    title="发现新版本"
    @close="updateStore.dismiss"
  >
    <div v-if="updateStore.metadata" class="update-dialog__content">
      <div class="update-dialog__version">
        <span>v{{ updateStore.metadata.currentVersion }}</span>
        <span aria-hidden="true">→</span>
        <strong>v{{ updateStore.metadata.version }}</strong>
      </div>
      <time v-if="updateStore.metadata.date" :datetime="updateStore.metadata.date">
        {{ formattedDate }}
      </time>
      <div
        v-if="renderedNotes"
        class="markdown-content update-dialog__notes"
        v-html="renderedNotes"
      />
      <p v-else class="update-dialog__empty">该版本没有附加更新说明。</p>

      <div v-if="updateStore.status === 'downloading'" class="update-dialog__progress">
        <div>
          <span>正在下载安装包</span>
          <strong>{{ progressLabel }}</strong>
        </div>
        <n-progress
          type="line"
          :percentage="Math.round(updateStore.progress * 100)"
          :show-indicator="false"
          processing
        />
      </div>
      <div v-else-if="updateStore.status === 'installing'" class="update-dialog__progress">
        <div><span>正在安装并准备重启</span></div>
        <n-progress type="line" :percentage="100" :show-indicator="false" processing />
      </div>
      <n-alert v-else-if="updateStore.status === 'error'" type="error" title="更新失败">
        {{ updateStore.error }}
      </n-alert>
    </div>

    <template #footer>
      <div class="update-dialog__actions">
        <n-button
          :disabled="updateStore.status === 'downloading' || updateStore.status === 'installing'"
          @click="updateStore.dismiss"
        >
          {{ updateStore.status === 'error' ? '关闭' : '稍后提醒' }}
        </n-button>
        <n-button
          v-if="updateStore.status === 'available' || updateStore.status === 'error'"
          type="primary"
          @click="updateStore.install"
        >
          {{ updateStore.status === 'error' ? '重新下载' : '立即更新' }}
        </n-button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAppUpdateStore } from '@/stores/appUpdate'
import { useStartupStore } from '@/stores/startup'
import { renderMarkdownDocument } from '@/rendering/markdown'

const updateStore = useAppUpdateStore()
const startupStore = useStartupStore()
const canDismiss = computed(() =>
  updateStore.status !== 'downloading' && updateStore.status !== 'installing',
)

const renderedNotes = computed(() =>
  renderMarkdownDocument(updateStore.metadata?.body || '', {
    surface: 'app_update',
  }).html,
)
const formattedDate = computed(() => {
  const value = updateStore.metadata?.date
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(date)
})
const progressLabel = computed(() => {
  const downloaded = formatBytes(updateStore.downloadedBytes)
  if (!updateStore.contentLength) return downloaded
  return `${downloaded} / ${formatBytes(updateStore.contentLength)}`
})

function formatBytes(value: number): string {
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}
</script>

<style scoped>
.update-dialog__content {
  display: grid;
  gap: 16px;
}

.update-dialog__version {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: 'SF Mono', Monaco, Consolas, monospace;
}

.update-dialog__version span {
  color: var(--app-text-muted);
}

.update-dialog__version strong {
  color: var(--app-text-strong);
  font-size: 18px;
}

.update-dialog__content time,
.update-dialog__empty {
  color: var(--app-text-secondary);
  font-size: 13px;
}

.update-dialog__notes {
  max-height: min(320px, 42vh);
  overflow: auto;
  padding: 14px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}

.update-dialog__progress {
  display: grid;
  gap: 8px;
}

.update-dialog__progress > div,
.update-dialog__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
</style>
