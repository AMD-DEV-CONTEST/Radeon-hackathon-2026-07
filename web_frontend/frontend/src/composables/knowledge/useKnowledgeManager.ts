import { computed, onMounted, ref, watch } from 'vue'
import { useDialog } from 'naive-ui'
import { DocumentText, FolderOutline, Globe } from '@/components/icons'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { useManagedResourceContext } from '@/composables/useManagedResourceContext'
import { useKnowledgeStore } from '@/stores/knowledge'
import { isAvailableEmbeddingModelProfile, modelPoolApi } from '@/api/modelPool'
import type { KnowledgeDocumentView, KnowledgeSourceView } from '@/types/protocol'

export function useKnowledgeManager() {
  const knowledgeStore = useKnowledgeStore()
  const commands = useCommand()
  const dialog = useDialog()
  const resourceContext = useManagedResourceContext('package_only')
  const { t } = useI18n()

  const showCreateModal = ref(false)
  const documentsDrawerOpen = ref(false)
  const documentsTitle = ref('')
  const selectedDocument = ref<KnowledgeDocumentView | null>(null)
  const documentLoading = ref(false)
  const selectedSourceIds = ref<Set<string>>(new Set())
  const busyAction = ref<'create' | 'delete' | 'reindex' | null>(null)
  const busySourceId = ref<string | null>(null)
  const embeddingConfigurationMissing = ref(false)
  const embeddingConfigurationLoading = ref(false)

  async function refreshEmbeddingConfiguration(): Promise<void> {
    embeddingConfigurationLoading.value = true
    try {
      const [defaultData, profileData] = await Promise.all([
        modelPoolApi.defaults(),
        modelPoolApi.profiles(),
      ])
      const embeddingProfileId = String(defaultData.defaults.embedding || '').trim()
      embeddingConfigurationMissing.value = !embeddingProfileId
        || !profileData.profiles.some((profile) => (
          profile.profile_id === embeddingProfileId
          && isAvailableEmbeddingModelProfile(profile)
        ))
    } catch {
      embeddingConfigurationMissing.value = true
    } finally {
      embeddingConfigurationLoading.value = false
    }
  }

  const selectedSources = computed(() => {
    return knowledgeStore.sources.filter((source) => {
      const sourceId = sourceIdOf(source)
      return Boolean(sourceId && selectedSourceIds.value.has(sourceId))
    })
  })
  const selectedCount = computed(() => selectedSources.value.length)

  function handleSelectSource(source: KnowledgeSourceView) {
    const sourceId = source.payload?.source_id
    if (sourceId) {
      knowledgeStore.selectSource(sourceId)
    }
  }

  async function handleReindex(source: KnowledgeSourceView) {
    const sourceId = sourceIdOf(source)
    if (!sourceId || busyAction.value) return
    busyAction.value = 'reindex'
    busySourceId.value = sourceId
    try {
      const event = await commands.reindexKnowledgeSource(sourceId, resourceContext.workspaceContext.value)
      if (event) {
        void commands.refreshKnowledge(resourceContext.workspaceContext.value)
      }
    } finally {
      busyAction.value = null
      busySourceId.value = null
    }
  }

  async function handleCreate(sourceData: any) {
    if (busyAction.value) return
    const pendingSourceId = `pending_${crypto.randomUUID().split('-').join('')}`
    const displayName = String(sourceData?.display_name || '').trim() || t('knowledge.sourceFallback')
    const mountMode = String(sourceData?.mount_mode || 'index_only')
    knowledgeStore.addPendingSource(pendingSourceId, displayName, mountMode)
    showCreateModal.value = false
    const event = await commands.addKnowledgeSource(
      sourceData,
      resourceContext.workspaceContext.value,
      (percent) => knowledgeStore.updatePendingSourceProgress(pendingSourceId, percent),
    )
    knowledgeStore.removePendingSource(pendingSourceId)
    if (event) {
      void commands.refreshKnowledge(resourceContext.workspaceContext.value)
    }
  }

  function handleAction(key: string, source: KnowledgeSourceView) {
    switch (key) {
      case 'documents':
        void openDocuments(source)
        break
      case 'remove':
        confirmDeleteSources([source])
        break
    }
  }

  function getSourceActions(_source: KnowledgeSourceView) {
    return [
      { label: t('knowledge.viewDocuments'), key: 'documents' },
      { label: t('common.delete'), key: 'remove' },
    ]
  }

  async function openDocuments(source: KnowledgeSourceView) {
    const sourceId = sourceIdOf(source)
    if (!sourceId) return
    knowledgeStore.selectSource(sourceId)
    documentsTitle.value = source.name || t('knowledge.sourceFallback')
    selectedDocument.value = null
    knowledgeStore.setCurrentDocument(null)
    documentsDrawerOpen.value = true
    await commands.listKnowledgeDocuments(sourceId, resourceContext.workspaceContext.value)
  }

  async function openDocument(document: KnowledgeDocumentView) {
    if (!document.documentId || documentLoading.value) return
    selectedDocument.value = document
    knowledgeStore.setCurrentDocument(null)
    documentLoading.value = true
    try {
      await commands.readKnowledgeDocument(document.documentId, resourceContext.workspaceContext.value)
    } finally {
      documentLoading.value = false
    }
  }

  function setSourceSelected(sourceId: string, checked: boolean) {
    const next = new Set(selectedSourceIds.value)
    if (checked) {
      next.add(sourceId)
    } else {
      next.delete(sourceId)
    }
    selectedSourceIds.value = next
  }

  function confirmDeleteSources(sources: KnowledgeSourceView[]) {
    const targets = sources.filter((source) => sourceIdOf(source))
    if (targets.length === 0 || busyAction.value) return
    const names = targets.map((source) => source.name || t('knowledge.sourceFallback')).join('、')
    dialog.warning({
      title: targets.length > 1 ? t('knowledge.confirmBulkDeleteTitle') : t('knowledge.confirmDeleteTitle'),
      content: t('knowledge.confirmDeleteContent', { names }),
      positiveText: targets.length > 1 ? t('knowledge.confirmBulkPositive', { count: targets.length }) : t('common.delete'),
      negativeText: t('common.cancel'),
      onPositiveClick: () => {
        void deleteSources(targets)
      },
    })
  }

  async function deleteSources(sources: KnowledgeSourceView[]) {
    busyAction.value = 'delete'
    let deleted = 0
    try {
      for (const source of sources) {
        const sourceId = sourceIdOf(source)
        if (!sourceId) continue
        const event = await commands.removeKnowledgeSource(sourceId, resourceContext.workspaceContext.value)
        if (event) {
          deleted += 1
          setSourceSelected(sourceId, false)
        }
      }
      if (deleted > 0) {
        void commands.refreshKnowledge(resourceContext.workspaceContext.value)
      }
    } finally {
      busyAction.value = null
    }
  }

  function resetCurrentKnowledgeView() {
    selectedSourceIds.value = new Set()
    documentsDrawerOpen.value = false
    documentsTitle.value = ''
    selectedDocument.value = null
    documentLoading.value = false
    knowledgeStore.reset()
  }

  watch(
    () => resourceContext.workspaceContextKey.value,
    () => {
      resetCurrentKnowledgeView()
      void commands.refreshKnowledge(resourceContext.workspaceContext.value)
    },
  )

  onMounted(() => {
    commands.listAgentPackages()
    resetCurrentKnowledgeView()
    void commands.refreshKnowledge(resourceContext.workspaceContext.value)
    void refreshEmbeddingConfiguration()
  })

  return {
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
    openDocument,
    knowledgeStore,
    resourceContext,
    refreshEmbeddingConfiguration,
    selectedCount,
    selectedSourceIds,
    selectedDocument,
    selectedSources,
    setSourceSelected,
    showCreateModal,
    sourceIdOf,
    sourceKey,
  }
}

function sourceIdOf(source: KnowledgeSourceView): string | null {
  const sourceId = source.payload?.source_id
  return sourceId ? String(sourceId) : null
}

function sourceKey(source: KnowledgeSourceView): string {
  return sourceIdOf(source) || source.name
}

function getSourceIcon(source: KnowledgeSourceView) {
  const kind = source.payload?.kind
  if (kind === 'folder' || kind === 'file') return FolderOutline
  if (kind === 'url') return Globe
  return DocumentText
}

function getSourceColor(source: KnowledgeSourceView): string {
  const colors = ['#18a058', '#2080f0', '#f0a020']
  const kind = source.payload?.kind || ''
  return colors[kind.length % colors.length]
}

function getStatusType(status: string): 'default' | 'success' | 'warning' | 'error' | 'info' {
  const types: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
    ready: 'success',
    indexing: 'info',
    failed: 'error',
  }
  return types[status] || 'default'
}
