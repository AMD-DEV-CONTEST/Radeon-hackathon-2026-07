import DOMPurify from 'dompurify'
import { unified } from 'unified'
import remarkParse from 'remark-parse'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import remarkRehype from 'remark-rehype'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import rehypeSanitize from 'rehype-sanitize'
import rehypeStringify from 'rehype-stringify'
import { rehypeMermaid } from './plugins/rehypeMermaid'
import { rehypeImageSources } from './plugins/rehypeImageSources'
import { markdownSanitizeSchema } from './sanitize'
import { prepareMarkdownSource } from './source'
import type { MarkdownRenderOptions, MarkdownRenderResult } from './types'
import 'highlight.js/styles/github-dark.css'
import 'katex/dist/katex.min.css'

const processor = unified()
  .use(remarkParse)
  .use(remarkGfm)
  .use(remarkMath)
  .use(remarkRehype, { allowDangerousHtml: false })
  .use(rehypeImageSources)
  .use(rehypeMermaid)
  .use(rehypeKatex)
  .use(rehypeHighlight, { detect: false })
  .use(rehypeSanitize, markdownSanitizeSchema())
  .use(rehypeStringify)

export function renderMarkdownDocument(content: string, options: MarkdownRenderOptions = {}): MarkdownRenderResult {
  const source = prepareMarkdownSource(content, options)
  try {
    const html = String(processor.processSync({
      value: source,
      data: {
        resolveImageUrl: options.resolveImageUrl,
        surface: options.surface,
      },
    }))
    return {
      source,
      html: sanitizeMarkdownHtml(html),
    }
  } catch (err) {
    console.error('Markdown parse error:', err)
    return {
      source,
      html: escapeHtml(content),
    }
  }
}

export function escapeHtml(text: string): string {
  const map: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;',
  }
  return text.replace(/[&<>"']/g, (m) => map[m])
}

function sanitizeMarkdownHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true, svg: true, mathMl: true },
    ADD_ATTR: ['target', 'rel', 'class'],
  })
}
