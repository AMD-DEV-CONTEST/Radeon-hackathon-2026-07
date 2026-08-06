import { requestJson } from './http'

export interface FileFormatGroupCapabilities {
  group_id: string
  knowledge_extensions: string[]
  attachment_extensions: string[]
  preview_extensions: string[]
}

export interface FileProcessingCapabilities {
  knowledge_extensions: string[]
  attachment_extensions: string[]
  preview_extensions: string[]
  knowledge_accept: string
  attachment_accept: string
  parser_backends: string[]
  format_groups: FileFormatGroupCapabilities[]
}

export const fileApi = {
  capabilities: () => requestJson<FileProcessingCapabilities>('/api/files/capabilities'),
}
