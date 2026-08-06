import { knowledgeApi } from '@/api/knowledge'
import type { KnowledgeSourceInput, WorkspaceContextInput } from '@/api/resourceTypes'
import { useCommandTransport } from './transport'

export function useKnowledgeCommands() {
  const transport = useCommandTransport()

  const refreshKnowledge = (context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(knowledgeApi.sources(context))
  }

  const addKnowledgeSource = (
    source: KnowledgeSourceInput,
    context?: WorkspaceContextInput,
    onUploadProgress?: (percent: number) => void,
  ) => {
    return transport.applyEventRequest(knowledgeApi.addSource(source, context, onUploadProgress))
  }

  const listKnowledgeDocuments = (sourceId: string, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(knowledgeApi.documents(sourceId, context))
  }

  const readKnowledgeDocument = (documentId: string, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(knowledgeApi.document(documentId, context))
  }

  const searchKnowledge = (query: string, sourceId?: string, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(knowledgeApi.search(query, sourceId, context))
  }

  const removeKnowledgeSource = (sourceId: string, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(knowledgeApi.removeSource(sourceId, context))
  }

  const reindexKnowledgeSource = (sourceId: string, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(knowledgeApi.reindexSource(sourceId, context))
  }

  return {
    refreshKnowledge,
    addKnowledgeSource,
    listKnowledgeDocuments,
    readKnowledgeDocument,
    searchKnowledge,
    removeKnowledgeSource,
    reindexKnowledgeSource,
  }
}
