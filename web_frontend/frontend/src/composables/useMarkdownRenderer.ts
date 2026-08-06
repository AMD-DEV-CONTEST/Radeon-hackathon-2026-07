import { nextTick, onMounted, onUpdated, type Ref } from 'vue'
import {
  enhanceRenderedMarkdown,
  renderMarkdownDocument,
  type MarkdownRenderOptions,
} from '@/rendering/markdown'

export function useMarkdownRenderer(rootRef: Ref<ParentNode | null>) {
  function renderMarkdown(content: string, options: MarkdownRenderOptions = {}): string {
    return renderMarkdownDocument(content, options).html
  }

  function refreshMarkdownEnhancements() {
    nextTick(() => {
      void enhanceRenderedMarkdown(rootRef.value)
    })
  }

  onMounted(refreshMarkdownEnhancements)
  onUpdated(refreshMarkdownEnhancements)

  return {
    renderMarkdown,
    refreshMarkdownEnhancements,
  }
}
