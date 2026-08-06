interface OpenFence {
  marker: '`' | '~'
  length: number
}

export function repairAiMarkdown(content: string): string {
  const lines = content.replace(/\r\n?/g, '\n').split('\n')
  const normalized: string[] = []
  let openFence: OpenFence | null = null

  for (const line of lines) {
    const fence = parseFenceLine(line)
    if (fence) {
      normalized.push(line)
      if (!openFence) {
        openFence = fence
      } else if (fence.marker === openFence.marker && fence.length >= openFence.length) {
        openFence = null
      }
      continue
    }
    normalized.push(openFence ? line : normalizeLineStart(line))
  }

  return normalized.join('\n').trim()
}

function normalizeLineStart(line: string): string {
  return line
    .replace(/^( {0,3}#{1,6})(?=[^\s#])/, '$1 ')
    .replace(/^(\s{0,3})([-*+])(?=\S)/, '$1$2 ')
    .replace(/^(\s{0,3}\d{1,2}[.)])(?=\S)/, '$1 ')
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
