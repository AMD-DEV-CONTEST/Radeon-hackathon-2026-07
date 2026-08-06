<template>
  <div class="knowledge-manager">
    <div class="manager-header">
      <div class="manager-title">
        <n-text strong>{{ t('knowledge.title') }}</n-text>
      </div>
      <div class="manager-controls">
        <ResourceTargetSelector
          v-model="resourceContext.selectedValue.value"
          :options="resourceContext.targetOptions.value"
        />
        <n-space>
          <n-button
            v-if="selectedCount > 0"
            :loading="busyAction === 'delete'"
            @click="confirmDeleteSources(selectedSources)"
          >
            {{ t('knowledge.deleteSelected', { count: selectedCount }) }}
          </n-button>
          <n-button type="primary" @click="showCreateModal = true">
            <template #icon>
              <n-icon><Add /></n-icon>
            </template>
            {{ t('knowledge.add') }}
          </n-button>
        </n-space>
      </div>
    </div>

    <div v-if="embeddingConfigurationMissing && !embeddingConfigurationLoading" class="embedding-guidance">
      <div class="embedding-guidance-copy">
        <n-text strong>{{ t('knowledge.embeddingModelMissing') }}</n-text>
        <n-text depth="3">{{ t('knowledge.embeddingModelMissingHint') }}</n-text>
      </div>
      <button type="button" class="embedding-guidance-link" @click="openModelPool">
        <span>{{ t('knowledge.configureEmbeddingModel') }}</span>
        <n-icon size="14"><ArrowForward /></n-icon>
      </button>
    </div>

    <n-scrollbar class="source-list">
      <div class="source-grid">
        <n-card
          v-for="source in knowledgeStore.sources"
          :key="sourceKey(source)"
          hoverable
          class="source-card"
          @click="handleSelectSource(source)"
        >
          <div class="source-header">
            <n-checkbox
              v-if="sourceIdOf(source)"
              class="source-select"
              :checked="selectedSourceIds.has(sourceIdOf(source)!)"
              @click.stop
              @update:checked="(checked) => setSourceSelected(sourceIdOf(source)!, checked)"
            />
            <div class="source-avatar" :style="{ color: getSourceColor(source) }">
              <n-icon size="22">
                <component :is="getSourceIcon(source)" />
              </n-icon>
            </div>
            <div class="source-info">
              <n-text strong class="source-name">{{ sourceDisplayName(source) }}</n-text>
              <n-tag :type="getStatusType(source.status)" size="small" class="source-status">
                {{ sourceStatusLabel(source.status) }}
              </n-tag>
            </div>
          </div>

          <n-divider style="margin: 12px 0" />

          <div class="source-stats">
            <div v-if="source.documentCount != null" class="stat-item">
              <n-icon size="14" class="stat-icon"><Document /></n-icon>
              <span class="stat-text">{{ t('knowledge.documents', { count: source.documentCount }) }}</span>
            </div>
            <div v-if="source.mode" class="stat-item">
              <n-icon size="14" class="stat-icon"><Settings /></n-icon>
              <span class="stat-text">{{ source.mode }}</span>
            </div>
          </div>

          <div v-if="ingestionOf(source)" class="ingestion-progress">
            <div class="ingestion-progress-header">
              <n-text depth="3">{{ ingestionMessage(source) }}</n-text>
              <n-text depth="3">{{ ingestionOf(source)?.percent }}%</n-text>
            </div>
            <n-progress
              type="line"
              :percentage="ingestionOf(source)?.percent || 0"
              :status="ingestionProgressStatus(source)"
              :show-indicator="false"
              :height="6"
              border-radius="3"
            />
            <n-text v-if="ingestionOf(source)?.error" type="error" class="ingestion-error">
              {{ ingestionOf(source)?.error }}
            </n-text>
          </div>

          <div class="source-actions">
            <n-button
              size="small"
              :loading="busyAction === 'reindex' && busySourceId === sourceIdOf(source)"
              @click.stop="handleReindex(source)"
            >
              {{ t('knowledge.reindex') }}
            </n-button>
            <n-dropdown
              :options="getSourceActions(source)"
              @select="(key) => handleAction(key, source)"
            >
              <n-button size="small" quaternary circle>
                <n-icon><EllipsisHorizontal /></n-icon>
              </n-button>
            </n-dropdown>
          </div>
        </n-card>
      </div>

      <n-empty
        v-if="knowledgeStore.sources.length === 0"
        :description="t('knowledge.empty')"
        class="manager-empty"
      >
        <template #icon>
          <n-icon size="56" class="manager-empty-icon">
            <Library />
          </n-icon>
        </template>
        <template #extra>
          <n-button type="primary" @click="showCreateModal = true">{{ t('knowledge.addFirst') }}</n-button>
        </template>
      </n-empty>
    </n-scrollbar>

    <!-- 创建知识源弹窗 -->
    <KnowledgeSourceFormModal
      v-model:show="showCreateModal"
      :submitting="busyAction === 'create'"
      @submit="handleCreate"
    />

    <n-drawer v-model:show="documentsDrawerOpen" width="min(880px, 100vw)" placement="right">
      <n-drawer-content :title="t('knowledge.documentsTitle')" closable>
        <div class="documents-panel">
          <div class="documents-title">{{ documentsTitle }}</div>
          <n-empty
            v-if="knowledgeStore.documents.length === 0"
            :description="t('knowledge.noDocuments')"
            size="small"
          />
          <div v-else class="documents-layout">
            <div class="document-list" role="list">
              <button
                v-for="document in knowledgeStore.documents"
                :key="document.documentId || document.payload?.document_id || document.title"
                type="button"
                class="document-item"
                :class="{ active: selectedDocument?.documentId === document.documentId }"
                :disabled="documentLoading"
                @click="openDocument(document)"
              >
                <span class="document-title">
                  {{ document.title || document.name || t('knowledge.document') }}
                </span>
                <span class="document-meta">
                  {{ document.documentType || document.kind || 'document' }}
                </span>
              </button>
            </div>
            <div class="document-preview">
              <n-empty
                v-if="!selectedDocument"
                :description="t('knowledge.selectDocumentToPreview')"
                size="small"
              />
              <n-spin v-else-if="documentLoading" size="small" />
              <FilePreviewContent v-else-if="knowledgePreviewFile" :file="knowledgePreviewFile" />
              <n-empty v-else :description="t('knowledge.documentPreviewUnavailable')" size="small" />
            </div>
          </div>
        </div>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton,
  NCard,
  NCheckbox,
  NDivider,
  NDrawer,
  NDrawerContent,
  NDropdown,
  NEmpty,
  NIcon,
  NProgress,
  NScrollbar,
  NSpace,
  NSpin,
  NTag,
  NText,
} from 'naive-ui'
import { Add, ArrowForward, Document, Library, Settings, EllipsisHorizontal } from '@/components/icons'
import { useKnowledgeManager } from '@/composables/knowledge/useKnowledgeManager'
import KnowledgeSourceFormModal from './KnowledgeSourceFormModal.vue'
import ResourceTargetSelector from '@/components/resources/ResourceTargetSelector.vue'
import FilePreviewContent from '@/components/workspace/FilePreviewContent.vue'
import { useI18n } from '@/composables/useI18n'
import type { KnowledgeSourceView, WorkspaceFileView } from '@/types/protocol'
import type { KnowledgeIngestionProgress } from '@/stores/knowledge'

const { t } = useI18n()
const router = useRouter()

const {
  busyAction,
  busySourceId,
  embeddingConfigurationLoading,
  embeddingConfigurationMissing,
  confirmDeleteSources,
  documentsDrawerOpen,
  documentsTitle,
  documentLoading,
  getSourceActions,
  getSourceColor,
  getSourceIcon,
  getStatusType,
  handleAction,
  handleCreate,
  handleReindex,
  handleSelectSource,
  knowledgeStore,
  openDocument,
  resourceContext,
  selectedCount,
  selectedSourceIds,
  selectedDocument,
  selectedSources,
  setSourceSelected,
  showCreateModal,
  sourceIdOf,
  sourceKey,
} = useKnowledgeManager()

function openModelPool(): void {
  void router.push({ name: 'ModelPool' })
}

const knowledgePreviewFile = computed<WorkspaceFileView | null>(() => {
  const content = String(knowledgeStore.currentDocument?.content || '')
  if (!selectedDocument.value || !content) return null
  return {
    name: selectedDocument.value.title || selectedDocument.value.name || t('knowledge.document'),
    kind: 'text',
    mimeType: 'text/plain',
    encoding: 'utf-8',
    content,
    contentBase64: '',
    sizeBytes: new TextEncoder().encode(content).byteLength,
    truncated: knowledgeStore.currentDocument?.truncated === true,
    payload: {
      preview_mode: 'extracted_text',
      document_id: selectedDocument.value.documentId,
      document_type: selectedDocument.value.documentType,
    },
  }
})

function sourceDisplayName(source: KnowledgeSourceView): string {
  return source.name || t('knowledge.sourceFallback')
}

function sourceStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: t('agents.statusReady'),
    registered: t('knowledge.ingestionQueued'),
    uploading: t('knowledge.uploading'),
    indexing: t('knowledge.updating'),
    failed: t('run.failed'),
  }
  return labels[status] || status || t('common.unknown')
}

function ingestionOf(source: KnowledgeSourceView): KnowledgeIngestionProgress | null {
  const sourceId = sourceIdOf(source)
  return sourceId ? knowledgeStore.ingestionBySource[sourceId] || null : null
}

function ingestionMessage(source: KnowledgeSourceView): string {
  const ingestion = ingestionOf(source)
  if (!ingestion) return ''
  if (ingestion.status === 'completed') return t('knowledge.ingestionCompleted')
  if (ingestion.status === 'failed') return t('knowledge.ingestionFailed')
  if (ingestion.status === 'queued') return t('knowledge.ingestionQueued')
  return ingestion.phase
    ? t('knowledge.ingestionPhase', { phase: ingestionPhaseLabel(ingestion.phase) })
    : t('knowledge.ingestionRunning')
}

function ingestionPhaseLabel(phase: string): string {
  const labels: Record<string, string> = {
    upload: t('knowledge.phaseUpload'),
    discover: t('knowledge.phaseDiscover'),
    load: t('knowledge.phaseLoad'),
    normalize: t('knowledge.phaseNormalize'),
    chunk: t('knowledge.phaseChunk'),
    embed: t('knowledge.phaseEmbed'),
    index: t('knowledge.phaseIndex'),
    finalize: t('knowledge.phaseFinalize'),
  }
  return labels[phase] || phase
}

function ingestionProgressStatus(source: KnowledgeSourceView): 'default' | 'success' | 'error' | 'warning' {
  const status = ingestionOf(source)?.status
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'error'
  if (status === 'cancelled') return 'warning'
  return 'default'
}
</script>

<style scoped>
.knowledge-manager {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: var(--app-space-xl);
  max-width: var(--app-content-max-width);
  width: 100%;
  margin: 0 auto;
}

.manager-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  margin-bottom: var(--app-space-xl);
  flex-wrap: wrap;
}

.manager-title {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
  min-width: 0;
}

.embedding-guidance {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  margin: calc(var(--app-space-md) * -1) 0 var(--app-space-lg);
  padding: 10px 14px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}

.embedding-guidance-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
  font-size: var(--app-font-sm);
}

.embedding-guidance-link {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 5px;
  padding: 4px 2px;
  border: 0;
  border-bottom: 1px solid var(--app-text);
  background: transparent;
  color: var(--app-text);
  font-size: var(--app-font-sm);
  font-weight: 650;
  cursor: pointer;
}

.embedding-guidance-link:hover {
  opacity: 0.68;
}

.manager-controls {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--app-space-md);
  flex-wrap: wrap;
}

.source-list {
  flex: 1;
  min-height: 0;
  margin: 0 calc(var(--app-space-xs) * -1);
  padding: 0 var(--app-space-xs) var(--app-space-lg);
}

.source-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--app-space-lg);
}

.source-card {
  cursor: pointer;
  transition: transform var(--app-transition-spring), box-shadow var(--app-transition-base);
  border-radius: var(--app-radius-lg);
  animation: app-fade-in-up 0.5s var(--app-transition-spring) both;
  will-change: transform;
}

.source-card:nth-child(1) { animation-delay: 0.08s; }
.source-card:nth-child(2) { animation-delay: 0.16s; }
.source-card:nth-child(3) { animation-delay: 0.24s; }
.source-card:nth-child(4) { animation-delay: 0.32s; }
.source-card:nth-child(5) { animation-delay: 0.40s; }
.source-card:nth-child(n+6) { animation-delay: 0.48s; }

.source-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--app-shadow-lg);
}

.source-card:active {
  transform: translateY(-2px) scale(0.98);
  transition-duration: 0.12s;
}

.source-header {
  display: flex;
  gap: var(--app-space-md);
  align-items: center;
}

.source-select {
  flex-shrink: 0;
}

.source-avatar {
  width: 44px;
  height: 44px;
  flex: 0 0 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}

.source-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
  min-width: 0;
}

.source-name {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: var(--app-leading-tight);
}

.source-status {
  align-self: flex-start;
}

.source-stats {
  display: flex;
  gap: var(--app-space-lg);
  margin: var(--app-space-md) 0;
}

.stat-item {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-xs);
  font-size: var(--app-font-sm);
  color: var(--app-text-secondary);
  line-height: 1.4;
  min-width: 0;
}

.stat-icon {
  flex-shrink: 0;
  color: var(--app-text-muted);
}

.stat-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-actions {
  display: flex;
  gap: var(--app-space-sm);
  margin-top: var(--app-space-md);
  flex-wrap: wrap;
}

.ingestion-progress {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
  margin-top: var(--app-space-sm);
}

.ingestion-progress-header {
  display: flex;
  justify-content: space-between;
  gap: var(--app-space-sm);
  font-size: var(--app-font-xs);
}

.ingestion-error {
  font-size: var(--app-font-xs);
  overflow-wrap: anywhere;
}

.documents-panel {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-md);
  height: 100%;
  min-height: 0;
}

.documents-title {
  font-size: var(--app-font-xl);
  font-weight: 600;
}

.documents-layout {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  flex: 1;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
}

.document-list {
  min-height: 0;
  overflow-y: auto;
  padding: var(--app-space-sm);
  border-right: 1px solid var(--app-divider);
  background: var(--app-surface-muted);
}

.document-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--app-space-xs);
  padding: var(--app-space-sm) var(--app-space-md);
  border: 0;
  border-radius: var(--app-radius-md);
  background: transparent;
  color: var(--app-text);
  text-align: left;
  cursor: pointer;
}

.document-item:hover,
.document-item.active {
  background: var(--app-surface);
}

.document-item.active {
  box-shadow: var(--app-shadow-sm);
}

.document-title {
  font-size: var(--app-font-lg);
  font-weight: 500;
}

.document-meta {
  font-size: var(--app-font-sm);
  color: var(--app-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.document-preview {
  min-width: 0;
  min-height: 420px;
  display: flex;
  align-items: stretch;
  justify-content: center;
  overflow: hidden;
  background: var(--app-surface);
}

.document-preview > :deep(*) {
  width: 100%;
}

.manager-empty {
  margin-top: 12vh;
  animation: app-fade-in-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.manager-empty-icon {
  display: block;
  color: var(--app-text-muted);
  opacity: 0.55;
  line-height: 1;
}

@media (max-width: 640px) {
  .knowledge-manager {
    padding: var(--app-space-md);
  }
  .embedding-guidance {
    align-items: flex-start;
    flex-direction: column;
  }
  .source-grid {
    grid-template-columns: 1fr;
    gap: var(--app-space-md);
  }
  .documents-layout {
    grid-template-columns: 1fr;
    overflow: visible;
  }
  .document-list {
    max-height: 220px;
    border-right: 0;
    border-bottom: 1px solid var(--app-divider);
  }
}
</style>
