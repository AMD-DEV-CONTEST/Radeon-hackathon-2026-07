import { repairAiMarkdown } from './repair'

interface OpenFence {
  marker: '`' | '~'
  length: number
}

export function prepareMarkdownSource(content: string, options: { streaming?: boolean } = {}): string {
  const normalized = repairAiMarkdown(content)
  return options.streaming ? closeStreamingFence(normalized) : normalized
}

function closeStreamingFence(content: string): string {
  const lines = content.split('\n')
  let openFence: OpenFence | null = null
  for (const line of lines) {
    const fence = parseFenceLine(line)
    if (!fence) continue
    if (!openFence) {
      openFence = fence
    } else if (fence.marker === openFence.marker && fence.length >= openFence.length) {
      openFence = null
    }
  }
  if (!openFence) return content
  const closing = openFence.marker.repeat(openFence.length)
  return `${content}${content.endsWith('\n') ? '' : '\n'}${closing}\n`
}

function parseFenceLine(line: string): OpenFence | null {
  const match = line.match(/^ {0,3}(`{3,}|~{3,})/)
  if (!match) return null
  const fence = match[1]
  return {
    marker: fence[0] as '`' | '~',
    length: fence.length,
  }
}
