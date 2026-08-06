export type MarkdownRenderSurface =
  | 'chat_message'
  | 'reasoning'
  | 'workspace_preview'
  | 'app_update'

export interface MarkdownRenderOptions {
  streaming?: boolean
  surface?: MarkdownRenderSurface
  resolveImageUrl?: (source: string) => string | null
}

export interface MarkdownRenderResult {
  html: string
  source: string
}
