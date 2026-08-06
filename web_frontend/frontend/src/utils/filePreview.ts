import type { WorkspaceFileView } from '@/types/protocol'
import {
  CODE_EXTENSIONS,
  IMAGE_EXTENSIONS,
  resourceExtension,
} from '@/utils/resourcePresentation'

export type FilePreviewKind = 'text' | 'markdown' | 'code' | 'image' | 'pdf' | 'unsupported'

export function fileExtension(file: WorkspaceFileView): string {
  return resourceExtension(file.name)
}

export function filePreviewKind(file: WorkspaceFileView): FilePreviewKind {
  const extension = fileExtension(file)
  const mimeType = String(file.mimeType || '').toLowerCase()
  if (file.kind === 'text' && ['md', 'markdown', 'mdx'].includes(extension)) return 'markdown'
  if (file.kind === 'text' && CODE_EXTENSIONS.has(extension)) return 'code'
  if (mimeType.startsWith('image/') || IMAGE_EXTENSIONS.has(extension)) return 'image'
  if (mimeType === 'application/pdf' || extension === 'pdf') return 'pdf'
  if (file.kind === 'text') return 'text'
  return 'unsupported'
}

export function filePreviewDataUrl(file: WorkspaceFileView): string {
  if (file.contentBase64) {
    return `data:${file.mimeType || 'application/octet-stream'};base64,${file.contentBase64}`
  }
  if (fileExtension(file) === 'svg' && file.content) {
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(file.content)}`
  }
  return ''
}
