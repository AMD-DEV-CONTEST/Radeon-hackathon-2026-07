/**
 * Knowledge Store
 * 管理知识库源和文档
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import type {
  KnowledgeSourceView,
  KnowledgeDocumentView,
  KnowledgeSearchResultView,
  FactoryFrontendEvent,
} from '@/types/protocol'

export interface KnowledgeIngestionProgress {
  sourceId: string
  jobId: string | null
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  phase: string | null
  percent: number
  message: string
  error: string | null
  counts: Record<string, number>
}

export const useKnowledgeStore = defineStore('knowledge', () => {
  const sources = ref<KnowledgeSourceView[]>([])
  const selectedSourceId = ref<string | null>(null)
  const documents = ref<KnowledgeDocumentView[]>([])
  const searchResults = ref<KnowledgeSearchResultView[]>([])
  const currentDocument = ref<any | null>(null)
  const ingestionBySource = ref<Record<string, KnowledgeIngestionProgress>>({})

  function setSources(newSources: KnowledgeSourceView[]): void {
    let nextSelectedSourceId = selectedSourceId.value
    let nextDocuments = documents.value
    let nextCurrentDocument = currentDocument.value
    if (
      nextSelectedSourceId &&
      !newSources.some((source) => source.payload?.source_id === nextSelectedSourceId)
    ) {
      nextSelectedSourceId = null
      nextDocuments = []
      nextCurrentDocument = null
    }
    sources.value = newSources
    const sourceIds = new Set(newSources.map((source) => String(source.payload?.source_id || '')).filter(Boolean))
    ingestionBySource.value = Object.fromEntries(
      Object.entries(ingestionBySource.value).filter(([sourceId]) => sourceIds.has(sourceId)),
    )
    selectedSourceId.value = nextSelectedSourceId
    documents.value = nextDocuments
    currentDocument.value = nextCurrentDocument
  }

  function selectSource(sourceId: string | null): void {
    selectedSourceId.value = sourceId
    documents.value = []
    currentDocument.value = null
  }

  function setDocuments(newDocuments: KnowledgeDocumentView[]): void {
    documents.value = newDocuments
  }

  function setSearchResults(results: KnowledgeSearchResultView[]): void {
    searchResults.value = results
  }

  function setCurrentDocument(doc: any): void {
    currentDocument.value = doc
  }

  function addPendingSource(sourceId: string, displayName: string, mode: string): void {
    const source: KnowledgeSourceView = {
      name: displayName,
      status: 'uploading',
      documentCount: null,
      mode,
      updatedAt: new Date().toISOString(),
      payload: {
        source_id: sourceId,
        display_name: displayName,
        mount_mode: mode,
        status: 'uploading',
        local_pending: true,
      },
    }
    sources.value = [source, ...sources.value.filter((item) => item.payload?.source_id !== sourceId)]
    ingestionBySource.value = {
      ...ingestionBySource.value,
      [sourceId]: {
        sourceId,
        jobId: null,
        status: 'running',
        phase: 'upload',
        percent: 5,
        message: '',
        error: null,
        counts: {},
      },
    }
  }

  function removePendingSource(sourceId: string): void {
    sources.value = sources.value.filter((source) => source.payload?.source_id !== sourceId)
    const nextIngestion = { ...ingestionBySource.value }
    delete nextIngestion[sourceId]
    ingestionBySource.value = nextIngestion
  }

  function updatePendingSourceProgress(sourceId: string, percent: number): void {
    const current = ingestionBySource.value[sourceId]
    if (!current) return
    ingestionBySource.value = {
      ...ingestionBySource.value,
      [sourceId]: {
        ...current,
        percent: Math.max(0, Math.min(100, Math.round(percent))),
      },
    }
  }

  function applyIngestionEvent(event: FactoryFrontendEvent): void {
    const sourceId = String(event.payload?.source_id || '').trim()
    if (!sourceId) return
    const progress = event.payload?.progress && typeof event.payload.progress === 'object'
      ? event.payload.progress
      : {}
    const current = Number(progress.current || 0)
    const total = Number(progress.total || 0)
    const explicitPercent = Number(progress.percent)
    const previous = ingestionBySource.value[sourceId]
    const status = ingestionStatus(event.event_type)
    const percent = status === 'completed'
      ? 100
      : Number.isFinite(explicitPercent)
        ? explicitPercent
        : total > 0
          ? (current / total) * 100
          : previous?.percent || 0
    const rawError = event.payload?.error
    ingestionBySource.value = {
      ...ingestionBySource.value,
      [sourceId]: {
        sourceId,
        jobId: String(event.payload?.job_id || '').trim() || previous?.jobId || null,
        status,
        phase: String(event.payload?.phase || '').trim() || previous?.phase || null,
        percent: Math.max(0, Math.min(100, Math.round(percent))),
        message: String(event.payload?.message || previous?.message || ''),
        error: status === 'failed'
          ? String(rawError?.message || rawError || event.payload?.message || '') || null
          : null,
        counts: event.payload?.counts && typeof event.payload.counts === 'object'
          ? event.payload.counts
          : previous?.counts || {},
      },
    }
  }

  function reset(): void {
    sources.value = []
    selectedSourceId.value = null
    documents.value = []
    searchResults.value = []
    currentDocument.value = null
    ingestionBySource.value = {}
  }

  return {
    sources,
    selectedSourceId,
    documents,
    searchResults,
    currentDocument,
    ingestionBySource,
    setSources,
    selectSource,
    setDocuments,
    setSearchResults,
    setCurrentDocument,
    addPendingSource,
    removePendingSource,
    updatePendingSourceProgress,
    applyIngestionEvent,
    reset,
  }
})

function ingestionStatus(eventType: string): KnowledgeIngestionProgress['status'] {
  if (eventType === 'knowledge_ingestion_completed') return 'completed'
  if (eventType === 'knowledge_ingestion_failed') return 'failed'
  if (eventType === 'knowledge_ingestion_cancelled') return 'cancelled'
  if (eventType === 'knowledge_ingestion_queued') return 'queued'
  return 'running'
}
